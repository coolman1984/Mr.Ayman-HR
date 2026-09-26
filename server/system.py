"""Opens all parts of one installation in the right order, upgrades an old single-PC
installation in place, and repairs anything a crash left half-done.

Upgrade of a version-1 installation (first start of this version):
  1. verified backup of bams.db and auth.db ("pre-upgrade"), abort if it fails;
  2. node identity (keys, certificate); a PC with user accounts becomes the
     administrator PC;
  3. journal.db with bootstrap changesets: the user accounts (signed by the
     administrator key), this PC in the device list, every business row including
     deleted ones (with their original timestamps), the SHA-256 of every uploaded
     file and the old audit / activity / security logs;
  4. fold, then identity.json is marked complete.
If anything fails before step 4 the partial journal is moved aside and the upgrade
runs again at the next start; the original data is never changed in the meantime
(the fold rewrites the rows with the same values).
"""
import hashlib
import json
import mimetypes
import os
import sqlite3
from datetime import datetime

from auth import USER_FIELDS, Auth
from backup import Backups
from journal import Journal
from node import Node
from store import ENTITIES, REPLICATED, Store

BOOT_CHUNK = 300


def _ms(ts):
    """ISO time -> HLC value (ms << 16) for the rows that existed before the upgrade."""
    try:
        return int(datetime.fromisoformat(str(ts)).timestamp() * 1000) << 16
    except (TypeError, ValueError):
        return 0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


class System:
    def __init__(self, data_dir, cfg, uploads, backup_dir, extra_backup_dirs=(), log=print):
        self.data_dir, self.cfg, self.uploads, self.log = data_dir, cfg, uploads, log
        if os.path.exists(os.path.join(data_dir, 'node', 'RESET_REQUESTED')):
            self._archive_copy()
        self.node = Node(data_dir)
        self.store = Store(data_dir)
        self.auth = Auth(data_dir, cfg)
        self.backups = Backups(self.store, uploads, backup_dir, extra_backup_dirs, cfg.get('keep_auto_backups', 200),
                               cfg.get('backup_interval_hours', 6), log=log, auth=self.auth)
        fresh = not self.node.exists or not self.node.info.get('setup_complete')
        if fresh:
            self._upgrade(cfg.get('device_name'))
        else:
            self._open_journal()
            self._check_rollback()
            self.store.fold_pending()
            self.auth.fold_pending()
        self.backups.journal = self.journal

    def _archive_copy(self):
        """The data folder was copied from another PC and the administrator chose "set up as a new PC": everything of
        the copied identity is moved aside (nothing is deleted) and this PC starts fresh, ready to join."""
        dest = os.path.join(self.data_dir, 'copied-' + datetime.now().strftime('%Y%m%d_%H%M%S'))
        os.makedirs(dest)
        for n in os.listdir(self.data_dir):
            if n == 'node' or n.split('.db')[0] in ('bams', 'auth', 'journal') and '.db' in n:
                os.replace(os.path.join(self.data_dir, n), os.path.join(dest, n))
        os.remove(os.path.join(dest, 'node', 'RESET_REQUESTED'))
        self.log(f'The copied data was moved to {dest}; this PC starts as a new device.')

    # ------------------------------------------------------------ normal start
    def _open_journal(self):
        self.journal = Journal(self.data_dir, self.node, REPLICATED, log=self.log)
        self.store.attach(self.journal)
        self.auth.attach(self.journal, self.node)

    def _check_rollback(self):
        """If this PC's own history in journal.db is shorter than what it once wrote, the journal was restored
        or lost writes: continue under a new epoch so no change number is ever used twice."""
        written = self.node.last_written()
        have = self.journal.vv()
        lost = {r: c for r, c in written.items() if c > have.get(r, 0)}
        if lost.get(self.node.replica):
            self.node.new_epoch(f'journal rolled back (had {lost[self.node.replica]}, found {have.get(self.node.replica, 0)})')
            self.journal.alert('rollback', 'This PC\'s change history was older than expected (restored or damaged journal). It continues '
                               'with a new numbering; its missing changes come back from the other PCs if they received them.', self.node.id)
            self.log('Journal rollback detected - new epoch ' + self.node.replica)

    # ------------------------------------------------------------ upgrade / first start
    def _upgrade(self, device_name):
        has_data = self.store.counts().get('Break Areas') or self.store.conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
        has_users = self.auth.has_users()
        if has_data or has_users:
            name = self.backups.create('pre-upgrade')  # verified; raises (and stops the start) if it fails
            self.log(f'Backup before the upgrade to the multi-PC version: {name}')
        self._discard_partial()
        if not self.node.exists:
            self.node.create(device_name)
        if has_users and self.node.role == 'unconfigured':
            self.node.become_authority()
        self._open_journal()
        if self.node.is_authority:
            self._boot_accounts()
        self._boot_data()
        self._boot_files()
        self._boot_logs()
        self.store.fold_upgrade()
        self.auth.fold_pending()
        if has_data:
            self.store.mark_initialized()
        self.node.info['setup_complete'] = True
        self.node.info['upgraded_from_v1'] = bool(has_data or has_users)
        self.node.save()
        self.log(f'Multi-PC support ready: this PC is "{self.node.name}" ({self.node.id}), role {self.node.role}')

    def _discard_partial(self):
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        for suffix in ('', '-wal', '-shm'):
            p = os.path.join(self.data_dir, 'journal.db' + suffix)
            if os.path.exists(p):
                os.replace(p, os.path.join(self.data_dir, f'journal.incomplete-{stamp}.db{suffix}'))
        for conn in (self.store.conn, self.auth.conn):
            conn.execute('DELETE FROM sync_field')
            conn.execute('DELETE FROM sync_marker')
            conn.execute('DELETE FROM sync_flags')

    def _boot_accounts(self):
        me = self.node
        ops = [{'e': 'nodes', 'id': me.id, 'op': 'insert', 'noaudit': True,
                's': {'name': me.name, 'pub': me.pub.hex(), 'cert_fp': me.cert_fp, 'status': 'active', 'role': 'authority', 'address': '',
                      'enrolled_at': me.info['created'], 'enrolled_by': 'Upgrade'}}]
        for r in self.auth.conn.execute('SELECT * FROM users ORDER BY created_at, id'):
            s = {}
            for f, kind in USER_FIELDS:
                v = r[f]
                if kind == 'json':
                    v = json.loads(v) if v else None
                elif kind == 'bool':
                    v = bool(v)
                s[f] = v
            ops.append({'e': 'users', 'id': r['id'], 'op': 'insert', 's': s, 'noaudit': True})
        self.journal.write('admin', ops, actor='Upgrade', label='User accounts and administrator PC (upgrade)', authority=True)

    def _boot_data(self):
        chunk = []

        def flush():
            if chunk:
                self.journal.write('bootstrap', list(chunk), actor='Upgrade', label=f'Existing data before the upgrade ({len(chunk)} records)')
                chunk.clear()
        for e, (table, _, fields) in ENTITIES.items():
            for r in self.store.conn.execute(f'SELECT * FROM {table} ORDER BY rowid'):
                s, n = {}, {}
                for js, col, kind, _ in fields:
                    v = self.store._row_js(e, r).get(js)
                    if e == 'inventory' and js == 'qty':
                        if v:
                            n['qty'] = v
                    elif v is not None:
                        s[js] = v
                op = {'e': e, 'id': r['id'], 'op': 'insert', 's': s, 'x': bool(r['deleted']), 'noaudit': True,
                      't': _ms(r['updated_at'] or r['created_at']), 'ci': [r['created_at'], r['created_by']],
                      'ui': [r['updated_at'], r['updated_by']], 'di': [r['deleted_at'], r['deleted_by'], r['deleted_txn']]}
                if n:
                    op['n'] = n
                chunk.append(op)
                if len(chunk) >= BOOT_CHUNK:
                    flush()
        flush()

    def _boot_files(self):
        ops = []
        if os.path.isdir(self.uploads):
            for root, dirs, files in os.walk(self.uploads):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for f in sorted(files):
                    p = os.path.join(root, f)
                    rel = os.path.relpath(p, self.uploads).replace(os.sep, '/')
                    ops.append({'e': 'files', 'id': '/files/' + rel, 'op': 'insert', 'x': False, 'noaudit': True,
                                's': {'sha256': sha256_file(p), 'size': os.path.getsize(p), 'type': mimetypes.guess_type(f)[0] or ''}})
        for i in range(0, len(ops), 500):
            self.journal.write('bootstrap', ops[i:i + 500], actor='Upgrade', label='Photos and documents before the upgrade')

    def _boot_logs(self):
        """The old logs become part of the permanent, replicated history (marked as imported)."""
        sources = [
            (self.store.conn, 'SELECT * FROM audit_log ORDER BY id', lambda r: {
                't': 'audit', 'ts': r['ts'], 'txn': r['txn'], 'user': r['user'], 'ip': r['ip'], 'label': r['label'], 'entity': r['entity'],
                'entity_id': r['entity_id'], 'area_id': r['area_id'], 'op': r['op'], 'changes': r['changes'], 'before': r['before'], 'after': r['after']}),
            (self.store.conn, 'SELECT * FROM activity_log ORDER BY id', lambda r: {
                't': 'activity', **{k: r[k] for k in ('ts', 'user', 'ip', 'type', 'action', 'target', 'page', 'detail')}}),
            (self.auth.conn, 'SELECT * FROM security_log ORDER BY id', lambda r: {
                't': 'security', **{k: r[k] for k in ('ts', 'user', 'ip', 'event', 'target', 'detail')}}),
        ]
        for conn, sql, conv in sources:
            batch = []
            for r in conn.execute(sql):
                batch.append(conv(r))
                if len(batch) >= 500:
                    self.journal.write('log', batch, actor='Upgrade', label='Log entries from before the upgrade (imported)')
                    batch = []
            if batch:
                self.journal.write('log', batch, actor='Upgrade', label='Log entries from before the upgrade (imported)')

    # ------------------------------------------------------------ helpers used by the web server and tools
    def status(self):
        return {'node': self.node.public(), 'fingerprint': self.store.fingerprint(), 'journal': self.journal.stats()}

    def close(self):
        for c in (self.journal.conn, self.store.conn, self.auth.conn):
            try:
                c.close()
            except sqlite3.Error:
                pass
