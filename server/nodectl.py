"""Maintenance tools for one PC of the system (run with the server stopped).

  python server/nodectl.py status              this PC, its role, the other PCs, history size
  python server/nodectl.py verify              check the complete history (hashes, chain, all signatures)
  python server/nodectl.py rebuild             re-create data/bams.db from the history (damaged database)
  python server/nodectl.py reset-admin         new temporary password for an administrator (administrator PC only)
  python server/nodectl.py export-authority F  save the administrator key to file F, protected by a passphrase
  python server/nodectl.py import-authority F  make THIS PC the administrator PC with a key saved before

The administrator key signs every change to users, permissions and PCs. If the
administrator PC is lost and no exported key exists, user management cannot be done
any more (everything else keeps working) - keep the export on a USB stick in a safe.
"""
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from node import write_atomic  # noqa: E402


def load_cfg():
    root = os.path.dirname(HERE)
    path = os.environ.get('BAMS_CONFIG') or os.path.join(root, 'config.json')
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)

    def res(p):
        return p if os.path.isabs(p) else os.path.join(root, p)
    data = res(cfg.get('data_dir', 'data'))
    return cfg, data, os.path.join(data, 'uploads'), res(cfg.get('backup_dir', 'backups')), [res(d) for d in cfg.get('extra_backup_dirs', [])]


def open_system():
    from system import System
    cfg, data, uploads, backups, extra = load_cfg()
    return System(data, cfg, uploads, backups, extra, log=print)


# ---------------------------------------------------------------- key export (passphrase protected)
def _keys(passphrase, salt):
    k = hashlib.scrypt(passphrase.encode('utf-8'), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
    return k[:32], k[32:]


def _stream(key, nonce, n):
    out, i = b'', 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(4, 'big'), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(secret, passphrase, meta):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    ke, km = _keys(passphrase, salt)
    ct = bytes(a ^ b for a, b in zip(secret, _stream(ke, nonce, len(secret))))
    tag = hmac.new(km, salt + nonce + ct, hashlib.sha256).hexdigest()
    return {'v': 1, 'kdf': 'scrypt-n32768-r8-p1', 'salt': salt.hex(), 'nonce': nonce.hex(), 'ct': ct.hex(), 'tag': tag, **meta}


def unseal(box, passphrase):
    salt, nonce, ct = bytes.fromhex(box['salt']), bytes.fromhex(box['nonce']), bytes.fromhex(box['ct'])
    ke, km = _keys(passphrase, salt)
    if not hmac.compare_digest(hmac.new(km, salt + nonce + ct, hashlib.sha256).hexdigest(), box['tag']):
        raise ValueError('Wrong passphrase or damaged file.')
    return bytes(a ^ b for a, b in zip(ct, _stream(ke, nonce, len(ct))))


# ---------------------------------------------------------------- commands
def cmd_status():
    s = open_system()
    n = s.node
    print(f'This PC:   {n.name}  id {n.id}  role {n.role}  replica {n.replica}')
    print(f'System:    {n.info.get("cluster_id")}  administrator PC {n.info.get("authority_node")}')
    print(f'History:   {s.journal.stats()}')
    for r in s.journal.roster().values():
        print(f'  PC {r["name"]:<20} {r["id"]}  {r.get("status"):<8} {r.get("address") or ""}')
    print('Data fingerprint:', s.store.fingerprint())


def cmd_verify():
    s = open_system()
    rep = s.journal.verify(all_signatures=True)
    print(json.dumps(rep, indent=2))
    return 0 if rep['ok'] else 2


def cmd_rebuild():
    """The history (journal.db) is the source of truth: fold it again into a fresh bams.db."""
    import sqlite3
    cfg, data, uploads, backups, extra = load_cfg()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    old = os.path.join(data, 'bams.db')
    legacy = []
    if os.path.exists(old):
        try:  # keep labels of recycle-bin groups made before the upgrade
            with sqlite3.connect(old) as db:
                legacy = db.execute('SELECT * FROM transactions').fetchall()
        except sqlite3.Error:
            pass
        for suffix in ('', '-wal', '-shm'):
            if os.path.exists(old + suffix):
                os.replace(old + suffix, os.path.join(data, f'bams.broken-{stamp}.db{suffix}'))
    s = open_system()
    with s.store.lock:
        s.store.conn.executemany('INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?)', legacy)
    s.store.mark_initialized()
    print(f'Rebuilt data/bams.db from the history: {s.store.counts()}')
    print('The previous file was kept as bams.broken-' + stamp + '.db')


def cmd_reset_admin():
    s = open_system()
    from auth import ALL, hash_password, now
    import uuid
    if not s.node.is_authority:
        if s.node.role == 'member':
            print('This PC is not the administrator PC. Run reset_admin.bat on the administrator PC.')
            return 1
        s.node.become_authority()
        me = s.node
        s.journal.write('admin', [{'e': 'nodes', 'id': me.id, 'op': 'insert', 'noaudit': True,
                                   's': {'name': me.name, 'pub': me.pub.hex(), 'cert_fp': me.cert_fp, 'status': 'active', 'role': 'authority',
                                         'address': '', 'enrolled_at': now(), 'enrolled_by': 'reset-admin'}}],
                        actor='reset-admin', label='This PC becomes the administrator PC', authority=True)
    a = s.auth
    pw = 'Reset-' + secrets.token_urlsafe(6).replace('_', 'x').replace('-', 'y') + '7'
    admins = [a._user(r) for r in a.conn.execute('SELECT * FROM users WHERE deleted=0 ORDER BY created_at')]
    admins = [u for u in admins if 'users.manage' in u['perms']]
    ts = now()
    if admins:
        u = admins[0]
        name = u['username']
        ops = [{'e': 'users', 'id': u['id'], 'op': 'update', 'c': {'pw_hash': ['', '']},
                's': {'pw_hash': hash_password(pw), 'must_change': True, 'active': True, 'pw_changed_at': ts, 'updated_at': ts, 'updated_by': 'reset-admin'}},
               {'e': 'userCommands', 'id': uuid.uuid4().hex, 'op': 'insert', 'noaudit': True, 's': {'cmd': 'unlock', 'user': u['id']}},
               {'e': 'userCommands', 'id': uuid.uuid4().hex, 'op': 'insert', 'noaudit': True, 's': {'cmd': 'logout', 'user': u['id']}}]
    else:
        name = 'admin'
        while a.conn.execute('SELECT 1 FROM users WHERE username=?', (name,)).fetchone():
            name += '1'
        uid = uuid.uuid4().hex
        row = {'username': name, 'full_name': 'Administrator', 'title': 'System Administrator', 'pw_hash': hash_password(pw), 'perms': list(ALL),
               'areas': None, 'role': 'Administrator', 'active': True, 'deleted': False, 'must_change': True, 'pw_changed_at': ts, 'notes': '',
               'created_at': ts, 'created_by': 'reset-admin', 'updated_at': ts, 'updated_by': 'reset-admin'}
        ops = [{'e': 'users', 'id': uid, 'op': 'insert', 's': row, 'r': {'id': uid, **row}}]
    a._write('reset-admin', '127.0.0.1', 'Emergency administrator password reset', ops)
    a.log('Server PC', '127.0.0.1', 'admin-reset', name, 'Emergency password reset on the administrator PC (reset_admin.bat)')
    print('=' * 64)
    print(' Administrator access restored')
    print(f' User name:          {name}')
    print(f' Temporary password: {pw}')
    print(' Log in with it now - you will be asked to choose a new password.')
    print('=' * 64)
    return 0


def cmd_export(path):
    s = open_system()
    if not s.node.authority_seed:
        print('This PC does not hold the administrator key.')
        return 1
    p1 = getpass.getpass('Passphrase to protect the key (at least 12 characters): ')
    if len(p1) < 12 or p1 != getpass.getpass('Repeat the passphrase: '):
        print('The passphrases are too short or different.')
        return 1
    box = seal(s.node.authority_seed, p1, {'cluster': s.node.info.get('cluster_id'), 'authority_pub': s.node.info.get('authority_pub'),
                                            'exported': datetime.now().isoformat(timespec='seconds'), 'from': s.node.name})
    write_atomic(path, json.dumps(box, indent=2))
    s.auth.log('Server PC', '127.0.0.1', 'authority-exported', path, 'Administrator key exported (passphrase protected)')
    print('Saved. Keep this file and the passphrase in a safe place, separately.')
    return 0


def cmd_import(path):
    s = open_system()
    with open(path, encoding='utf-8') as f:
        box = json.load(f)
    if box.get('cluster') != s.node.info.get('cluster_id'):
        print('This key belongs to another system.')
        return 1
    seed = unseal(box, getpass.getpass('Passphrase: '))
    s.node.install_authority_key(seed)
    s.auth.log('Server PC', '127.0.0.1', 'authority-imported', s.node.name,
               'This PC is now the administrator PC (key imported). Remove the old administrator PC in Devices & Sync.')
    print(f'"{s.node.name}" is now the administrator PC. Start the system and remove the old administrator PC in Devices & Sync.')
    return 0


def main(argv):
    cmds = {'status': cmd_status, 'verify': cmd_verify, 'rebuild': cmd_rebuild, 'reset-admin': cmd_reset_admin}
    if argv[:1] and argv[0] in cmds and len(argv) == 1:
        return cmds[argv[0]]() or 0
    if len(argv) == 2 and argv[0] == 'export-authority':
        return cmd_export(argv[1])
    if len(argv) == 2 and argv[0] == 'import-authority':
        return cmd_import(argv[1])
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
