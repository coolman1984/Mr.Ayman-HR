"""Users, passwords, sessions and permissions for the Break Area Management System.

Security design (following the OWASP Authentication, Password Storage and Session
Management cheat sheets):
  * Passwords are never stored - only a salted PBKDF2-SHA256 hash (600,000 rounds).
  * A login session is a random 256-bit token in an HttpOnly, SameSite=Strict cookie;
    only its SHA-256 hash is kept on the server. Sessions end after a period of
    inactivity and after a maximum lifetime, on logout, on password change and when
    the user is disabled.
  * After too many wrong passwords the account is locked for a while. The login
    error never says whether the user name or the password was wrong.
  * Every permission is checked on the server for every request - hiding a button
    in the browser is only for convenience.
  * The users live in their own database file (data/auth.db) so that restoring an
    old data backup never brings back a deleted user or an old password.
  * Every login, logout, failed login, lockout and every change to a user or to a
    user's permissions is written to the security log (auth.db and a monthly
    JSON-lines file in data/logs that is never overwritten).

Several PCs: user accounts are replicated to every PC so people can log in even when
the administrator PC is switched off. Only the administrator PC holds the key that signs
account and permission changes (journal.py, kind "admin"); every PC checks that
signature, so no other PC can invent users or permissions. A user's own password change
is allowed on every PC (kind "account", only that user's password fields). Sessions,
failed-login counters and lockouts stay on the PC where they happen.

Run  python server/auth.py reset-admin  on the administrator PC to regain access when the
administrator password is lost.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timedelta

import ed25519
import replica
from journal import PRIORITY, password_proof_message

# (group, [(permission, label)]) - the order is the order shown on the user screen
ADMIN_GROUP = 'Administrator rights - only for administrators'
PERMISSIONS = [
    ('Pages - what the person can open', [
        ('dashboard.view', 'Dashboard'),
        ('areas.view', 'Break Areas list and profiles'),
        ('equipment.view', 'Furniture & Equipment page'),
        ('transactions.view', 'Transactions page'),
        ('maintenance.view', 'Inspection & Maintenance page'),
        ('reports.view', 'Reports page'),
        ('surveys.view', 'Satisfaction survey results'),
    ]),
    ('Break Areas', [
        ('areas.create', 'Add new break areas'),
        ('areas.edit', 'Edit break area details and status'),
        ('areas.delete', 'Delete break areas'),
    ]),
    ('Inventory', [
        ('inventory.edit', 'Add, remove, replace and transfer items'),
        ('inventory.delete', 'Delete an item from an inventory'),
        ('itemtypes.manage', 'Add, edit and delete item types'),
    ]),
    ('Issues', [
        ('issues.create', 'Report issues'),
        ('issues.followup', 'Follow up and close issues'),
        ('issues.delete', 'Delete issues'),
    ]),
    ('Maintenance & Inspections', [
        ('maintenance.create', 'Schedule maintenance'),
        ('maintenance.complete', 'Complete maintenance'),
        ('maintenance.delete', 'Delete maintenance'),
        ('inspections.create', 'Record inspections'),
        ('inspections.delete', 'Delete inspections'),
    ]),
    ('Satisfaction Surveys', [
        ('surveys.create', 'Add results'),
        ('surveys.edit', 'Edit results'),
        ('surveys.delete', 'Delete results'),
    ]),
    ('Photos & Documents', [
        ('files.upload', 'Upload photos and documents, choose the main photo'),
        ('files.download', 'Download documents'),
        ('files.delete', 'Delete photos and documents'),
    ]),
    ('Reports & Export', [
        ('report.register', 'Report: Break Area Register'),
        ('report.inventory', 'Report: Inventory by Break Area'),
        ('report.history', 'Report: Update History'),
        ('report.issues', 'Report: Issues'),
        ('report.inspections', 'Report: Inspection Schedule'),
        ('report.satisfaction', 'Report: Satisfaction Survey'),
        ('report.locations', 'Report: Summary by Location'),
        ('report.labels', 'Print QR code labels'),
        ('export.excel', 'Export page lists to Excel'),
        ('print', 'Print lists and reports / save as PDF'),
        ('report.full', 'Complete database export (all data and logs)'),
    ]),
    ('Settings & Backups', [
        ('logs.view', 'Data changes log (who changed what)'),
        ('settings.view', 'Settings page and server information'),
        ('settings.edit', 'Change general settings (name, locations, targets)'),
        ('backups.manage', 'See and create backups'),
        ('trash.restore', 'Recycle Bin: see and restore deleted records'),
    ]),
    (ADMIN_GROUP, [
        ('users.manage', 'Manage people, links, profiles and permissions'),
        ('logs.activity', 'See what each person did and clicked (activity log)'),
        ('logs.security', 'See logins and the security log'),
        ('backups.restore', 'Restore a backup (all data goes back in time)'),
        ('data.import', 'Import old data, load or delete all sample data'),
    ]),
]
ALL = [p for _, ps in PERMISSIONS for p, _ in ps]
PAGES = ['dashboard.view', 'areas.view', 'equipment.view', 'transactions.view', 'maintenance.view', 'surveys.view']
ADMIN_PERMS = {p for g, ps in PERMISSIONS if g == ADMIN_GROUP for p, _ in ps}
WORK = [p for p in ALL if p not in ADMIN_PERMS]
# ready-made profiles (id, name, permissions); the administrator can change or delete them and make new ones
BUILTIN_PROFILES = [
    ('full-access', 'Full access', WORK),
    ('administrator', 'Administrator', ALL),
    ('data-entry', 'Data Entry', PAGES + ['inventory.edit', 'issues.create', 'issues.followup', 'maintenance.create', 'maintenance.complete',
                                         'inspections.create', 'surveys.create', 'surveys.edit', 'files.upload', 'files.download',
                                         'export.excel', 'print']),
    ('maintenance', 'Maintenance Team', ['dashboard.view', 'areas.view', 'maintenance.view', 'issues.create', 'issues.followup',
                                         'maintenance.complete', 'inspections.create', 'files.upload', 'files.download', 'print']),
    ('viewer', 'Viewer', PAGES + ['reports.view', 'files.download', 'print', 'report.register', 'report.inventory', 'report.history',
                                 'report.issues', 'report.inspections', 'report.satisfaction', 'report.locations']),
    ('visitor', 'Visitor', ['dashboard.view', 'areas.view']),
]
LOCKED_PROFILE = 'administrator'  # always has every right, so there is always a way to manage the system
OLD_ROLE_NAMES = {'Manager': 'Full access'}  # profile names of earlier versions


def role_name(r):
    return OLD_ROLE_NAMES.get(r or '', r or 'Custom')


ITERATIONS = 600_000
USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{3,32}$')
COMMON = {'password', 'password1', 'password123', '12345678', '123456789', '1234567890', '11111111', '00000000', 'qwerty123',
          'qwertyuiop', 'abc12345', 'admin123', 'admin1234', 'administrator', 'welcome1', 'welcome123', 'letmein1', 'iloveyou',
          'samsung1', 'samsung123', 'factory1', 'changeme', 'p@ssw0rd', 'passw0rd', '87654321', '12341234', 'aa123456'}


class AuthError(Exception):
    """Wrong login, locked account, weak password... (HTTP 400/401)."""


class Forbidden(Exception):
    """The user is logged in but is not allowed to do this (HTTP 403)."""


class NotAuthority(Forbidden):
    """User and permission changes can only be made on the administrator PC."""


# replicated user fields (everything else in the users table is local to this PC)
T, J, B = 'text', 'json', 'bool'
USER_FIELDS = [('username', T), ('full_name', T), ('title', T), ('pw_hash', T), ('pw_pub', T), ('perms', J), ('areas', J), ('role', T),
               ('active', B), ('deleted', B), ('must_change', B), ('pw_changed_at', T), ('notes', T), ('created_at', T),
               ('created_by', T), ('updated_at', T), ('updated_by', T), ('link_hash', T), ('link_nonce', T), ('link_at', T), ('link_by', T), ('login', T)]
USER_FIELD_NAMES = {f for f, _ in USER_FIELDS}
PROFILE_FIELDS = [('name', T), ('perms', J), ('deleted', B), ('updated_at', T), ('updated_by', T)]
PROFILE_FIELD_NAMES = {f for f, _ in PROFILE_FIELDS}


def _col(kind, v):
    if kind == B:
        return 1 if v else 0
    if kind == J:
        return None if v is None else json.dumps(v)
    return v




def now():
    return datetime.now().isoformat(timespec='seconds')


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}'


def account_seed(pw, uid):
    """Private key that only the password gives. Its public half (pw_pub) is published with every new password, so any
    PC can check that a password change was made by somebody who knew the old password."""
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), b'BAMS-ACCOUNT1|' + uid.encode('utf-8'), ITERATIONS)


def account_pub(pw, uid):
    return ed25519.public_key(account_seed(pw, uid)).hex()


def verify_password(pw, stored):
    try:
        algo, n, salt, dk = stored.split('$')
        if algo != 'pbkdf2_sha256':
            return False
        test = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), int(n))
        return hmac.compare_digest(test.hex(), dk)
    except (ValueError, AttributeError):
        return False


_DUMMY = hash_password(secrets.token_hex(8))  # verified for unknown user names so timing does not reveal them


def _token_hash(token):
    return hashlib.sha256(token.encode('ascii', 'ignore')).hexdigest()


class Auth:
    def __init__(self, data_dir, cfg=None):
        cfg = cfg or {}
        self.path = os.path.join(data_dir, 'auth.db')
        self.log_dir = os.path.join(data_dir, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        self.idle = timedelta(minutes=max(1, float(cfg.get('session_idle_minutes', 30))))
        self.max_age = timedelta(hours=max(1, float(cfg.get('session_max_hours', 12))))
        self.max_failed = max(3, int(cfg.get('max_failed_logins', 5)))
        self.lock_minutes = max(1, int(cfg.get('lockout_minutes', 15)))
        self.min_len = max(8, int(cfg.get('min_password_length', 8)))
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA busy_timeout=10000')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, full_name TEXT NOT NULL, title TEXT,
                pw_hash TEXT NOT NULL, perms TEXT NOT NULL DEFAULT '[]', areas TEXT, role TEXT,
                active INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0, must_change INTEGER NOT NULL DEFAULT 1,
                failed INTEGER NOT NULL DEFAULT 0, locked_until TEXT, last_login TEXT, last_ip TEXT, pw_changed_at TEXT,
                created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT, ver INTEGER NOT NULL DEFAULT 1, notes TEXT);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created TEXT, last_seen TEXT, ip TEXT, agent TEXT);
            CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS security_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, ip TEXT, event TEXT, target TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS ix_security_ts ON security_log(ts);
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, name TEXT, perms TEXT, deleted INTEGER NOT NULL DEFAULT 0, updated_at TEXT, updated_by TEXT);
        ''')
        have = {r[1] for r in self.conn.execute('PRAGMA table_info(users)')}
        for col in ('pw_pub', 'link_hash', 'link_nonce', 'link_at', 'link_by', 'login'):
            if col not in have:
                self.conn.execute(f'ALTER TABLE users ADD COLUMN {col} TEXT')
        if 'via' not in {r[1] for r in self.conn.execute('PRAGMA table_info(sessions)')}:
            self.conn.execute('ALTER TABLE sessions ADD COLUMN via TEXT')
        replica.install(self.conn)
        self.journal = None
        self.node = None
        self.folder = None

    def attach(self, journal, node):
        self.journal = journal
        self.node = node
        self.folder = UserFolder(self, journal.deps_of)

    def fold_pending(self):
        """Applies account changes from the journal that are not yet in the users table."""
        total = 0
        while True:
            with self.lock:
                items = self.journal.iter_after(replica.markers(self.conn), 2000)
                if not items:
                    return total
                c = self.conn
                c.execute('BEGIN IMMEDIATE')
                try:
                    for env, status in items:
                        self.folder.fold(env, status)
                    c.execute('COMMIT')
                except Exception:
                    c.execute('ROLLBACK')
                    raise
                total += len(items)

    def _write(self, actor, ip, label, ops, kind='admin', check=None):
        """Saves account changes as one changeset (admin: signed with the administrator key).
        check(conn) runs inside the transaction first and may raise to cancel everything."""
        if self.journal is None:
            raise AuthError('The system is still starting. Try again in a moment.')
        if kind == 'admin' and not self.node.is_authority:
            raise NotAuthority(self.authority_hint())
        rec, appended = None, False
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
                extra = check(c) if check else None
                if extra:
                    ops = ops + extra
                with self.journal.lock:
                    rec = self.journal.build(kind, ops, actor=actor['display'] if isinstance(actor, dict) else actor,
                                             actor_id=actor['id'] if isinstance(actor, dict) else '', ip=ip, label=label,
                                             authority=kind == 'admin', deps=replica.markers(c))
                    before = len(self.folder.problems)
                    self.folder.fold(rec['env'], 'ok')
                    if len(self.folder.problems) != before:
                        raise AuthError('This change could not be saved: ' + self.folder.problems[-1])
                    self.journal.append_local(rec)
                    appended = True
                c.execute('COMMIT')
            except Exception:
                try:
                    c.execute('ROLLBACK')
                except sqlite3.OperationalError:
                    pass
                if not appended:
                    raise
                try:
                    self.fold_pending()
                except Exception as e:  # noqa: BLE001 - it is saved in the journal and applied again at the next start
                    self.journal.alert('fold', f'A saved account change could not be applied yet ({e}).', '', 'warning')
        self.journal._notify([rec])
        return rec

    def authority_hint(self):
        name = ''
        if self.journal and self.node and self.node.info.get('authority_node'):
            n = self.journal.roster().get(self.node.info['authority_node']) or {}
            name = n.get('name') or ''
            addr = (n.get('address') or '').split(':')[0]
            if addr:
                name += f' ({addr})'
        return ('User accounts and permissions can only be changed on the administrator PC' + (f' "{name}"' if name else '') +
                '. Open the system on that PC (or its address in the browser) to make this change.')

    # ------------------------------------------------------------ helpers
    @staticmethod
    def display(u):
        return f'{u["full_name"]} ({u["username"]})'

    def _user(self, r):
        if not r:
            return None
        u = dict(r)
        perms = [p for p in json.loads(u['perms'] or '[]') if p in ALL]
        u['perms'] = perms
        u['areas'] = json.loads(u['areas']) if u['areas'] else None
        u['display'] = self.display(u)
        return u

    @staticmethod
    def public(u, online=None):
        out = {k: u[k] for k in ('id', 'username', 'full_name', 'title', 'perms', 'areas', 'role', 'must_change', 'last_login',
                                 'last_ip', 'pw_changed_at', 'created_at', 'created_by', 'updated_at', 'updated_by', 'ver', 'notes')}
        out['active'] = bool(u['active'])
        out['must_change'] = bool(u['must_change'])
        out['locked'] = bool(u['locked_until'] and _parse(u['locked_until']) > datetime.now())
        out['locked_until'] = u['locked_until'] if out['locked'] else None
        out['failed'] = u['failed']
        out['role'] = role_name(u['role'])
        out['login'] = 'link' if u.get('login') == 'link' else 'password'
        out['link_on'] = bool(u.get('link_hash'))
        if online is not None:
            out['online'] = online
        return out

    def get(self, uid):
        with self.lock:
            return self._user(self.conn.execute('SELECT * FROM users WHERE id=? AND deleted=0', (uid,)).fetchone())

    def has_users(self):
        with self.lock:
            return self.conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0

    def log(self, user, ip, event, target='', detail=''):
        ts = now()
        row = (ts, str(user)[:120], ip or '', event[:40], str(target or '')[:200], str(detail or '')[:4000])
        with self.lock:
            self.conn.execute('INSERT INTO security_log (ts,user,ip,event,target,detail) VALUES (?,?,?,?,?,?)', row)
        path = os.path.join(self.log_dir, f'security-{datetime.now():%Y-%m}.jsonl')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(dict(zip(('ts', 'user', 'ip', 'event', 'target', 'detail'), row)), ensure_ascii=False) + '\n')
        if self.journal is not None and self.node is not None and self.node.exists:
            try:
                self.journal.log_security(row[1], row[2], row[3], row[4], row[5], ts=ts)
            except Exception as e:  # the local copy above is kept in any case
                print('security log could not be added to the journal:', e)

    def check_password(self, pw, username='', full_name=''):
        pw = pw or ''
        if len(pw) < self.min_len:
            raise AuthError(f'The password must have at least {self.min_len} characters.')
        if len(pw) > 128:
            raise AuthError('The password is too long (maximum 128 characters).')
        low = pw.lower()
        if low in COMMON or len(set(pw)) < 3:
            raise AuthError('This password is too easy to guess. Choose another one.')
        for part in [username] + (full_name or '').split():
            if part and len(part) >= 3 and part.lower() in low:
                raise AuthError('The password must not contain the user name or the person\'s name.')
        if not (re.search(r'[A-Za-z]', pw) and re.search(r'[^A-Za-z]', pw)):
            raise AuthError('The password must contain letters and at least one number or symbol.')

    # ------------------------------------------------------------ first setup
    def setup(self, username, full_name, password, ip):
        """First administrator of a new system: this PC becomes the administrator PC."""
        username, full_name = (username or '').strip(), (full_name or '').strip()
        if not USERNAME_RE.match(username):
            raise AuthError('User name: 3-32 letters, numbers, dot, dash or underscore (no spaces).')
        if not full_name:
            raise AuthError('Enter the full name.')
        self.check_password(password, username, full_name)
        if self.has_users():
            raise AuthError('The administrator account already exists. Please log in.')
        if self.node.role == 'member':
            raise AuthError('This PC belongs to another administrator PC. Wait until its user accounts have arrived.')
        if self.node.role == 'unconfigured':
            self.node.become_authority()
        h = hash_password(password)
        ts = now()
        uid = uuid.uuid4().hex
        me = self.node
        row = {'username': username, 'full_name': full_name, 'title': 'System Administrator', 'pw_hash': h,
               'pw_pub': account_pub(password, uid), 'perms': list(ALL),
               'areas': None, 'role': 'Administrator', 'active': True, 'deleted': False, 'must_change': False, 'pw_changed_at': ts,
               'notes': '', 'created_at': ts, 'created_by': 'First setup', 'updated_at': ts, 'updated_by': 'First setup'}
        ops = [{'e': 'nodes', 'id': me.id, 'op': 'insert', 'noaudit': True,
                's': {'name': me.name, 'pub': me.pub.hex(), 'cert_fp': me.cert_fp, 'status': 'active', 'role': 'authority', 'address': '',
                      'enrolled_at': ts, 'enrolled_by': 'First setup'}},
               {'e': 'users', 'id': uid, 'op': 'insert', 's': row, 'r': {'id': uid, **row}}]

        def check(c):
            if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                raise AuthError('The administrator account already exists. Please log in.')
        self._write(f'{full_name} ({username})', ip, 'First administrator account', ops, check=check)
        self.log(f'{full_name} ({username})', ip, 'setup', username, 'First administrator account created on this PC (it is now the administrator PC)')

    # ------------------------------------------------------------ login / sessions
    def login(self, username, password, ip, agent=''):
        username = (username or '').strip()[:64]
        with self.lock:
            r = self.conn.execute('SELECT * FROM users WHERE username=? AND deleted=0', (username,)).fetchone()
        u = self._user(r)
        ok = verify_password(password or '', u['pw_hash'] if u else _DUMMY)
        generic = 'Wrong user name or password.'
        if not u:
            self.log(username or '(empty)', ip, 'login-failed', username, 'Unknown user name')
            raise AuthError(generic)
        if u['locked_until'] and _parse(u['locked_until']) > datetime.now():
            self.log(u['display'], ip, 'login-blocked', username, 'Account is locked until ' + u['locked_until'])
            mins = max(1, round((_parse(u['locked_until']) - datetime.now()).total_seconds() / 60))
            raise AuthError(f'This account is locked for {mins} more minute(s) after too many wrong passwords. '
                            'Wait, or ask the administrator to unlock it.')
        if not ok:
            failed = u['failed'] + 1
            locked = (datetime.now() + timedelta(minutes=self.lock_minutes)).isoformat(timespec='seconds') if failed >= self.max_failed else None
            with self.lock:
                self.conn.execute('UPDATE users SET failed=?, locked_until=? WHERE id=?', (0 if locked else failed, locked, u['id']))
            self.log(u['display'], ip, 'login-failed', username, f'Wrong password (attempt {failed} of {self.max_failed})')
            if locked:
                self.log(u['display'], ip, 'account-locked', username, f'Locked for {self.lock_minutes} minutes after {failed} wrong passwords')
                raise AuthError(f'Too many wrong passwords. The account is locked for {self.lock_minutes} minutes.')
            raise AuthError(generic)
        if not u['active']:
            self.log(u['display'], ip, 'login-blocked', username, 'Account is disabled')
            raise AuthError('This account is disabled. Ask the administrator.')
        token = secrets.token_urlsafe(32)
        ts = now()
        with self.lock:
            self.conn.execute('UPDATE users SET failed=0, locked_until=NULL, last_login=?, last_ip=? WHERE id=?', (ts, ip, u['id']))
            self.conn.execute('INSERT INTO sessions (token_hash, user_id, created, last_seen, ip, agent) VALUES (?,?,?,?,?,?)',
                              (_token_hash(token), u['id'], ts, ts, ip, (agent or '')[:300]))
        self.log(u['display'], ip, 'login', username, agent[:300] if agent else '')
        if not u.get('pw_pub') and self.node is not None and self.node.is_authority:
            try:  # account from before the multi-PC version: publish its password key, so it can change its password on any PC
                self._write('System', ip, 'Password key of ' + username, [{'e': 'users', 'id': u['id'], 'op': 'update', 'noaudit': True,
                                                                          's': {'pw_hash': u['pw_hash'], 'pw_pub': account_pub(password, u['id'])}}])
            except Exception as e:  # noqa: BLE001 - logging in must not fail because of this
                print('password key not published:', e)
        return token, self.get(u['id'])

    def session(self, token, ip, touch=True):
        """The logged-in user for this cookie token, or None (expired/unknown)."""
        if not token:
            return None
        th = _token_hash(token)
        with self.lock:
            s = self.conn.execute('SELECT * FROM sessions WHERE token_hash=?', (th,)).fetchone()
            if not s:
                return None
            t = datetime.now()
            reason = ''
            if t - _parse(s['last_seen']) > self.idle:
                reason = f'Logged out automatically after {int(self.idle.total_seconds() // 60)} minutes without activity'
            elif t - _parse(s['created']) > self.max_age:
                reason = f'Logged out automatically after the maximum session time ({int(self.max_age.total_seconds() // 3600)} hours)'
            u = self.get(s['user_id'])
            if not reason and (not u or not u['active']):
                reason = 'Session ended - the account is disabled or deleted'
            if not reason and s['via'] == 'link' and not (u.get('link_hash') and self.link_allowed(u)):
                reason = 'Session ended - the personal link was switched off or the account became an administrator'
            if reason:
                self.conn.execute('DELETE FROM sessions WHERE token_hash=?', (th,))
        if reason:
            self.log(u['display'] if u else s['user_id'], ip, 'session-expired', '', reason)
            return None
        if touch and (t - _parse(s['last_seen'])).total_seconds() > 20:
            with self.lock:
                self.conn.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', (t.isoformat(timespec='seconds'), th))
        if s['via'] == 'link':
            u['must_change'] = False  # came with the personal link: the person may not know the temporary password
            u['via_link'] = True
        return u

    # ------------------------------------------------------------ personal quick links
    @staticmethod
    def link_allowed(u):
        """Administrator accounts never get a link: whoever holds it could change every user and permission."""
        return 'users.manage' not in (u.get('perms') or [])

    def link_token(self, uid, nonce):
        """The secret part of a user's link. Only the administrator PC can work it out again (from its own key), so the
        link can be shown again at any time without being stored anywhere; the other PCs only get its SHA-256."""
        mac = hmac.new(self.node.authority_seed, b'BAMS-LINK1|' + uid.encode() + b'|' + nonce.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac[:21]).decode().rstrip('=')

    def link_user(self, token):
        """The user whose personal link this is (None for an unknown or switched-off link)."""
        token = (token or '')[:100]
        if len(token) < 20:
            return None
        th = _token_hash(token)
        with self.lock:
            u = self._user(self.conn.execute("SELECT * FROM users WHERE link_hash=? AND deleted=0", (th,)).fetchone())
        return u if u and hmac.compare_digest(u.get('link_hash') or '', th) else None

    def link_login(self, token, ip, agent=''):
        """Logs in with a personal link. Returns (session token, user) or raises AuthError."""
        u = self.link_user(token)
        if not u:
            self.log('(personal link)', ip, 'login-link-failed', '', 'Unknown or switched-off personal link')
            raise AuthError('This link does not work any more.')
        if not u['active']:
            self.log(u['display'], ip, 'login-blocked', u['username'], 'Personal link used, but the account is disabled')
            raise AuthError('This account is disabled.')
        if not self.link_allowed(u):
            self.log(u['display'], ip, 'login-blocked', u['username'], 'Personal link refused: administrator accounts must use their password')
            raise AuthError('Administrator accounts must log in with their password.')
        token = secrets.token_urlsafe(32)
        ts = now()
        with self.lock:
            self.conn.execute('UPDATE users SET last_login=?, last_ip=? WHERE id=?', (ts, ip, u['id']))
            self.conn.execute('INSERT INTO sessions (token_hash, user_id, created, last_seen, ip, agent, via) VALUES (?,?,?,?,?,?,?)',
                              (_token_hash(token), u['id'], ts, ts, ip, (agent or '')[:300], 'link'))
        self.log(u['display'], ip, 'login-link', u['username'], 'Logged in with the personal link' + (' - ' + agent[:250] if agent else ''))
        return token, self.session(token, ip, touch=False)

    def link_list(self):
        """Every user with the state of their link, when it was last used and on which PC."""
        used = {}
        if self.journal is not None:
            with self.journal.lock:
                for r in self.journal.conn.execute("SELECT target, ts, node, ip FROM security WHERE event='login-link' ORDER BY ts"):
                    used[r[0].lower()] = {'ts': r[1], 'node': r[2], 'ip': r[3]}
        names = {k: v.get('name') for k, v in self.journal.roster().items()} if self.journal is not None else {}
        out = []
        with self.lock:
            rows = [self._user(r) for r in self.conn.execute('SELECT * FROM users WHERE deleted=0 ORDER BY full_name COLLATE NOCASE')]
        for u in rows:
            last = used.get(u['username'].lower())
            on = bool(u.get('link_hash'))
            out.append({'id': u['id'], 'username': u['username'], 'full_name': u['full_name'], 'title': u['title'], 'active': bool(u['active']),
                        'allowed': self.link_allowed(u), 'on': on, 'created_at': u.get('link_at') if on else None,
                        'created_by': u.get('link_by') if on else None,
                        'token': self.link_token(u['id'], u['link_nonce']) if on and self.node.is_authority and u.get('link_nonce') else None,
                        'last_used': dict(last, pc=names.get(last['node']) or last['node']) if last else None})
        return out

    def link_set(self, actor, ip, uid, on):
        """Creates a new personal link (the old one stops working) or switches it off - on every PC."""
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        if on and not self.link_allowed(u):
            raise AuthError('Administrator accounts cannot get a personal link - they always log in with their password.')
        ts = now()
        nonce = secrets.token_hex(8) if on else ''
        s = {'link_hash': _token_hash(self.link_token(uid, nonce)) if on else '', 'link_nonce': nonce,
             'link_at': ts if on else '', 'link_by': actor['display'] if on else ''}
        was = bool(u.get('link_hash'))
        word = ('new link' if was else 'link created') if on else 'link switched off'
        self._write(actor, ip, ('Personal link for ' if on else 'Personal link off for ') + u['username'], [
            {'e': 'users', 'id': uid, 'op': 'update', 's': s, 'c': {'personal link': ['on' if was else 'off', word]}}] +
            ([] if on and not was else [{'e': 'userCommands', 'id': uuid.uuid4().hex, 'op': 'insert', 'noaudit': True,
                                         's': {'cmd': 'logout-link', 'user': uid}}]))
        self.log(actor['display'], ip, 'link-created' if on else 'link-removed', u['display'],
                 ('A new personal link was made (an older one stops working on every PC)' if was else 'Personal link created') if on
                 else 'Personal link switched off on every PC')

    def logout(self, token, u, ip):
        with self.lock:
            self.conn.execute('DELETE FROM sessions WHERE token_hash=?', (_token_hash(token or ''),))
        if u:
            self.log(u['display'], ip, 'logout', u['username'])

    def _kill(self, uid, keep_token=None):
        with self.lock:
            if keep_token:
                n = self.conn.execute('DELETE FROM sessions WHERE user_id=? AND token_hash<>?', (uid, _token_hash(keep_token))).rowcount
            else:
                n = self.conn.execute('DELETE FROM sessions WHERE user_id=?', (uid,)).rowcount
        return n

    def change_password(self, u, old, new, ip, token):
        with self.lock:
            r = self.conn.execute('SELECT pw_hash FROM users WHERE id=?', (u['id'],)).fetchone()
        if not verify_password(old or '', r['pw_hash']):
            self.log(u['display'], ip, 'password-change-failed', u['username'], 'Current password was wrong')
            raise AuthError('The current password is wrong.')
        if old == new:
            raise AuthError('The new password must be different from the current one.')
        self.check_password(new, u['username'], u['full_name'])
        ts = now()
        uid = u['id']
        new_hash, new_pub, old_seed = hash_password(new), account_pub(new, uid), account_seed(old, uid)
        s = {'pw_hash': new_hash, 'pw_pub': new_pub, 'must_change': False, 'pw_changed_at': ts}
        op = {'e': 'users', 'id': uid, 'op': 'update', 's': s, 'c': {'pw_hash': ['', ''], 'must_change': [bool(u['must_change']), False]}}
        with self.lock:
            rows = self.conn.execute("SELECT fld, origin, cseq, prio, hlc, val FROM sync_field WHERE tbl='users' AND rid=? AND fld IN ('pw_hash','pw_pub')",
                                     (uid,)).fetchall()
        setters = [r for r in rows if r['fld'] == 'pw_hash']
        win = max(setters, key=lambda r: (r['prio'], r['hlc'], r['origin'], r['cseq'])) if setters else None
        pub = next((json.loads(r['val']) for r in rows if win and r['fld'] == 'pw_pub' and (r['origin'], r['cseq']) == (win['origin'], win['cseq'])), None)
        if pub and pub == ed25519.public_key(old_seed).hex():
            frm = [win['origin'], win['cseq']]
            op['p'] = {'from': frm, 'sig': ed25519.sign(old_seed, password_proof_message(uid, new_hash, new_pub, frm)).hex()}
            kind = 'account'
        elif self.node.is_authority:
            kind = 'admin'  # password from before the upgrade: the administrator PC confirms it with its own key
        else:
            raise AuthError('For security, please change your password once on the administrator PC (your password dates from '
                            'before the multi-PC version). After that you can change it on any PC.')
        self._write(u, ip, 'Changed own password', [op], kind=kind)
        n = self._kill(u['id'], keep_token=token)
        self.log(u['display'], ip, 'password-changed', u['username'], f'Changed own password; {n} other session(s) logged out')

    # ------------------------------------------------------------ user management
    def online(self):
        with self.lock:
            cut = (datetime.now() - self.idle).isoformat(timespec='seconds')
            return {r[0]: r[1] for r in self.conn.execute('SELECT user_id, MAX(last_seen) FROM sessions WHERE last_seen>=? GROUP BY user_id', (cut,))}

    def list_users(self):
        on = self.online()
        with self.lock:
            rows = [self._user(r) for r in self.conn.execute('SELECT * FROM users WHERE deleted=0 ORDER BY full_name COLLATE NOCASE')]
        return [self.public(u, on.get(u['id'])) for u in rows]

    # ------------------------------------------------------------ profiles (ready-made sets of permissions)
    def profiles(self, c=None):
        """Every profile: the ready-made ones (possibly changed by the administrator) and the administrator's own."""
        with self.lock:
            c = c or self.conn
            rows = {r['id']: r for r in c.execute('SELECT * FROM profiles')}
            used = {}
            for r in c.execute('SELECT role FROM users WHERE deleted=0'):
                used[role_name(r['role'])] = used.get(role_name(r['role']), 0) + 1
        out = []

        def add(pid, name, perms, builtin):
            perms = ALL if pid == LOCKED_PROFILE else sorted(p for p in perms if p in ALL)
            out.append({'id': pid, 'name': name, 'perms': list(perms), 'builtin': builtin, 'locked': pid == LOCKED_PROFILE,
                        'admin': 'users.manage' in perms, 'users': used.get(name, 0)})
        for pid, name, perms in BUILTIN_PROFILES:
            r = rows.pop(pid, None)
            if r is None:
                add(pid, name, perms, True)
            elif not r['deleted'] or pid == LOCKED_PROFILE:
                add(pid, r['name'] or name, json.loads(r['perms']) if r['perms'] else perms, True)
        for r in sorted(rows.values(), key=lambda r: (r['name'] or '').lower()):
            if not r['deleted'] and r['name']:
                add(r['id'], r['name'], json.loads(r['perms'] or '[]'), False)
        return out

    def save_profile(self, actor, ip, d):
        """Creates or changes a profile; with apply, everybody who has this profile gets the new permissions (on every PC)."""
        if not self.node.is_authority:
            raise NotAuthority(self.authority_hint())
        pid = str(d.get('id') or '') or None
        name = re.sub(r'\s+', ' ', str(d.get('name') or '')).strip()[:40]
        perms = sorted({p for p in (d.get('perms') or []) if p in ALL})
        apply = bool(d.get('apply', True))
        if not name:
            raise AuthError('Give the profile a name, e.g. "Visitor".')
        if name.lower() == 'custom':
            raise AuthError('"Custom" is used for people with their own set of permissions. Choose another name.')
        ts, res = now(), {}

        def check(c):
            profs = self.profiles(c)
            cur = next((p for p in profs if p['id'] == pid), None) if pid else None
            if pid and not cur:
                raise AuthError('This profile no longer exists.')
            if cur and cur['locked']:
                raise AuthError('The Administrator profile always has every right. It cannot be changed.')
            if any(p['name'].lower() == name.lower() and p['id'] != pid for p in profs):
                raise AuthError(f'There is already a profile called "{name}".')
            new_id = pid or uuid.uuid4().hex
            ops = [{'e': 'profiles', 'id': new_id, 'op': 'update' if cur else 'insert',
                    's': {'name': name, 'perms': perms, 'deleted': False, 'updated_at': ts, 'updated_by': actor['display']},
                    'c': {'name': [cur['name'] if cur else '', name], 'perms': [cur['perms'] if cur else [], perms]}}]
            res['n'] = 0
            if cur and apply:
                users = [self._user(r) for r in c.execute('SELECT * FROM users WHERE deleted=0')]
                hit = [u for u in users if role_name(u['role']) == cur['name']]
                admins_after = [u for u in users if u['active'] and ('users.manage' in perms if u in hit else 'users.manage' in u['perms'])]
                if not admins_after:
                    raise AuthError('At least one active person must keep the right to manage people and permissions.')
                for u in hit:
                    if u['id'] == actor['id'] and 'users.manage' not in perms:
                        raise AuthError('You have this profile yourself. You cannot remove your own right to manage people and permissions.')
                    if 'users.manage' in perms and (u.get('login') == 'link' or u.get('link_hash')):
                        raise AuthError(f'{u["full_name"]} has this profile and logs in with a personal link. People with a link cannot '
                                        'manage people and permissions. Switch off their link first, or remove that right.')
                    if sorted(u['perms']) != perms or u['role'] != name:
                        ops.append({'e': 'users', 'id': u['id'], 'op': 'update', 's': {'perms': perms, 'role': name, 'updated_at': ts,
                                                                                         'updated_by': actor['display']},
                                    'c': {'perms': [sorted(u['perms']), perms], 'role': [u['role'], name]}})
                        res['n'] += 1
            res['id'] = new_id
            return ops
        self._write(actor, ip, 'Profile ' + name, [], check=check)
        self.log(actor['display'], ip, 'profile-saved', name, f'{len(perms)} permission(s); updated for {res["n"]} person(s)')
        return {'id': res['id'], 'updated': res['n']}

    def delete_profile(self, actor, ip, pid):
        """The profile disappears; the people who had it keep their permissions (shown as "Custom")."""
        if not self.node.is_authority:
            raise NotAuthority(self.authority_hint())
        ts, res = now(), {}

        def check(c):
            cur = next((p for p in self.profiles(c) if p['id'] == pid), None)
            if not cur:
                raise AuthError('This profile no longer exists.')
            if cur['locked']:
                raise AuthError('The Administrator profile cannot be deleted.')
            res['name'] = cur['name']
            ops = [{'e': 'profiles', 'id': pid, 'op': 'delete', 's': {'name': cur['name'], 'perms': cur['perms'], 'deleted': True,
                                                                       'updated_at': ts, 'updated_by': actor['display']}}]
            for r in c.execute('SELECT id, role FROM users WHERE deleted=0'):
                if role_name(r['role']) == cur['name']:
                    ops.append({'e': 'users', 'id': r['id'], 'op': 'update', 'noaudit': True, 's': {'role': 'Custom'}})
            return ops
        self._write(actor, ip, 'Delete profile', [], check=check)
        self.log(actor['display'], ip, 'profile-deleted', res['name'], 'People who had it keep their permissions')

    def _admins(self, c, exclude=None):
        n = 0
        for r in c.execute('SELECT id, perms FROM users WHERE deleted=0 AND active=1'):
            if r['id'] != exclude and 'users.manage' in json.loads(r['perms'] or '[]'):
                n += 1
        return n

    def save_user(self, actor, ip, d):
        uid = d.get('id')
        username = str(d.get('username') or '').strip()
        full_name = str(d.get('full_name') or '').strip()[:80]
        title = str(d.get('title') or '').strip()[:80]
        notes = str(d.get('notes') or '').strip()[:500]
        role = str(d.get('role') or 'Custom')[:40]
        login = 'link' if d.get('login') == 'link' else 'password'
        perms = sorted({p for p in (d.get('perms') or []) if p in ALL})
        areas = d.get('areas')
        areas = None if areas is None else sorted({str(a)[:120] for a in areas})
        active = bool(d.get('active', True))
        must_change = bool(d.get('must_change', True))
        if not full_name:
            raise AuthError('Enter the full name.')
        if username and not USERNAME_RE.match(username) or not username and (uid or login == 'password'):
            raise AuthError('User name: 3-32 letters, numbers, dot, dash or underscore (no spaces).')
        if login == 'link' and 'users.manage' in perms:
            raise AuthError('People who log in with a personal link cannot manage people and permissions (administrator right). '
                            'Remove that right, or let this person log in with a user name and password.')
        if not self.node.is_authority:
            raise NotAuthority(self.authority_hint())
        ts = now()
        res = {}
        new_row = {'username': username, 'full_name': full_name, 'title': title, 'perms': perms, 'areas': areas, 'role': role,
                   'active': active, 'must_change': must_change, 'notes': notes, 'login': login, 'updated_at': ts, 'updated_by': actor['display']}

        def new_link(user_id):
            nonce = secrets.token_hex(8)
            res['token'] = self.link_token(user_id, nonce)
            return {'link_hash': _token_hash(res['token']), 'link_nonce': nonce, 'link_at': ts, 'link_by': actor['display']}

        def check(c):
            if not username:  # personal link only: the user name is made from the name (it is only shown in the logs)
                base = re.sub(r'[^a-z0-9]+', '.', full_name.lower()).strip('.')[:24] or 'person'
                base = base if len(base) >= 3 else base + '.person'
                n, cand = 1, base
                while c.execute('SELECT 1 FROM users WHERE username=?', (cand,)).fetchone():
                    n += 1
                    cand = f'{base}{n}'
                new_row['username'] = cand
                dup = None
            else:
                dup = c.execute('SELECT id, deleted FROM users WHERE username=?', (username,)).fetchone()
            if dup and dup['id'] != uid:
                raise AuthError(f'The user name "{username}" is already used' + (' by a deleted user.' if dup['deleted'] else '.'))
            if uid:
                old = self._user(c.execute('SELECT * FROM users WHERE id=? AND deleted=0', (uid,)).fetchone())
                if not old:
                    raise AuthError('This user no longer exists.')
                if int(d.get('ver') or 0) != old['ver']:
                    raise AuthError(f'{old["display"]} was changed by {old["updated_by"]} at {old["updated_at"]}. Close and open it again.')
                if uid == actor['id'] and (not active or 'users.manage' not in perms):
                    raise AuthError('You cannot disable yourself or remove your own right to manage users.')
                if (not active or 'users.manage' not in perms) and 'users.manage' in old['perms'] and not self._admins(c, exclude=uid):
                    raise AuthError('At least one active user must keep the right to manage users.')
                old_login = 'link' if old.get('login') == 'link' else 'password'
                cur = {'username': old['username'], 'full_name': old['full_name'], 'title': old['title'], 'perms': sorted(old['perms']),
                       'areas': old['areas'], 'role': old['role'], 'active': bool(old['active']), 'must_change': bool(old['must_change']),
                       'notes': old['notes'], 'login': old_login}
                row, extra = dict(new_row), []
                if login == 'link':
                    row['must_change'] = False
                    if not old.get('link_hash'):
                        row.update(new_link(uid))
                elif old_login == 'link':  # from now on with a password: the link is switched off
                    password = d.get('password') or ''
                    self.check_password(password, username, full_name)
                    row.update({'pw_hash': hash_password(password), 'pw_pub': account_pub(password, uid), 'must_change': True, 'pw_changed_at': ts,
                                'link_hash': '', 'link_nonce': '', 'link_at': '', 'link_by': ''})
                    extra.append({'e': 'userCommands', 'id': uuid.uuid4().hex, 'op': 'insert', 'noaudit': True, 's': {'cmd': 'logout-link', 'user': uid}})
                changes = {f: [cur[f], row[f]] for f in cur if cur.get(f) != row.get(f)}
                if 'pw_hash' in row:
                    changes['pw_hash'] = ['', '']
                res['old'] = old
                return [{'e': 'users', 'id': uid, 'op': 'update', 's': row, 'c': changes}] + extra
            res['uid'] = new_id = uuid.uuid4().hex
            if login == 'link':  # no password at all: a long random one nobody knows
                password = secrets.token_urlsafe(24)
            else:
                password = d.get('password') or ''
                self.check_password(password, username, full_name)
            row = {**new_row, 'pw_hash': hash_password(password), 'pw_pub': account_pub(password, new_id), 'deleted': False, 'pw_changed_at': ts, 'created_at': ts,
                   'created_by': actor['display']}
            if login == 'link':
                row['must_change'] = False
            audit = dict(row)
            if login == 'link':
                row.update(new_link(new_id))
            res['old'] = None
            return [{'e': 'users', 'id': new_id, 'op': 'insert', 's': row, 'r': {'id': new_id, **audit}}]

        self._write(actor, ip, ('Change user ' if uid else 'Create user ') + (username or full_name), [], check=check)
        old = res['old']
        uid = uid or res['uid']
        new = self.get(uid) or self._user(self.conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
        if old is None:
            self.log(actor['display'], ip, 'user-created', new['display'],
                     f'Role: {role}; active: {active}; areas: {"all" if areas is None else len(areas)}; permissions: {", ".join(perms) or "none"}')
        else:
            ch = []
            for k, label in (('username', 'User name'), ('full_name', 'Name'), ('title', 'Job title'), ('role', 'Role'), ('active', 'Active'),
                             ('must_change', 'Must change password'), ('notes', 'Notes')):
                if old[k] != new[k]:
                    ch.append(f'{label}: {old[k]} -> {new[k]}')
            add, rem = sorted(set(new['perms']) - set(old['perms'])), sorted(set(old['perms']) - set(new['perms']))
            if add:
                ch.append('Permissions added: ' + ', '.join(add))
            if rem:
                ch.append('Permissions removed: ' + ', '.join(rem))
            if old['areas'] != new['areas']:
                ch.append(f'Break areas: {"all" if old["areas"] is None else ", ".join(old["areas"])} -> {"all" if new["areas"] is None else ", ".join(new["areas"])}')
            if ch:
                self.log(actor['display'], ip, 'user-changed', new['display'], '; '.join(ch))
            if old['active'] and not new['active']:
                self.log(actor['display'], ip, 'user-disabled', new['display'], 'All open sessions on every PC are ended')
        if res.get('token'):
            self.log(actor['display'], ip, 'link-created', new['display'], 'Personal link created (logs in without a password)')
        out = self.public(new)
        if res.get('token'):
            out['token'] = res['token']
        return out

    def reset_password(self, actor, ip, uid, password):
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        self.check_password(password, u['username'], u['full_name'])
        ts = now()
        self._write(actor, ip, 'Reset password of ' + u['username'], [
            {'e': 'users', 'id': uid, 'op': 'update', 's': {'pw_hash': hash_password(password), 'pw_pub': account_pub(password, uid),
                                                              'must_change': True, 'pw_changed_at': ts,
                                                              'updated_at': ts, 'updated_by': actor['display']},
             'c': {'pw_hash': ['', ''], 'must_change': [bool(u['must_change']), True]}},
            {'e': 'userCommands', 'id': uuid.uuid4().hex, 'op': 'insert', 'noaudit': True, 's': {'cmd': 'unlock', 'user': uid}}])
        self.log(actor['display'], ip, 'password-reset', u['display'], 'Temporary password set by the administrator; must be changed at next '
                 'login; logged out on every PC')

    def _command(self, actor, ip, uid, cmd, label):
        """Unlock / log out: on the administrator PC for every PC, elsewhere for this PC only."""
        if self.node.is_authority:
            self._write(actor, ip, label, [{'e': 'userCommands', 'id': uuid.uuid4().hex, 'op': 'insert', 'noaudit': True,
                                            's': {'cmd': cmd, 'user': uid}}])
            return 'every PC'
        with self.lock:
            if cmd == 'unlock':
                self.conn.execute('UPDATE users SET failed=0, locked_until=NULL WHERE id=?', (uid,))
            else:
                self._kill(uid)
        return 'this PC only (the administrator PC is needed for all PCs)'

    def unlock(self, actor, ip, uid):
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        where = self._command(actor, ip, uid, 'unlock', 'Unlock ' + u['username'])
        self.log(actor['display'], ip, 'user-unlocked', u['display'], 'Unlocked on ' + where)

    def force_logout(self, actor, ip, uid):
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        n = self._kill(uid)
        where = self._command(actor, ip, uid, 'logout', 'Log out ' + u['username'])
        self.log(actor['display'], ip, 'forced-logout', u['display'], f'Sessions ended by the administrator on {where} ({n} here)')
        return n

    def delete_user(self, actor, ip, uid):
        """Soft delete: the account disappears and can never log in again, but its name stays in all logs."""
        if uid == actor['id']:
            raise AuthError('You cannot delete your own account.')
        res = {}

        def check(c):
            u = self._user(c.execute('SELECT * FROM users WHERE id=? AND deleted=0', (uid,)).fetchone())
            if not u:
                raise AuthError('This user no longer exists.')
            if 'users.manage' in u['perms'] and u['active'] and not self._admins(c, exclude=uid):
                raise AuthError('At least one active user must keep the right to manage users.')
            res['u'] = u
            ts = now()
            return [{'e': 'users', 'id': uid, 'op': 'delete', 's': {'deleted': True, 'active': False, 'updated_at': ts, 'updated_by': actor['display']},
                     'b': {'username': u['username'], 'full_name': u['full_name']}}]
        self._write(actor, ip, 'Delete user', [], check=check)
        self.log(actor['display'], ip, 'user-deleted', res['u']['display'], 'Account deleted on every PC (kept in the logs; the user name stays reserved)')

    # ------------------------------------------------------------ log / backup
    def query_log(self, q='', user='', event='', frm='', to='', limit=200, offset=0, node=''):
        if self.journal is not None:
            return self.journal.query('security', q, user, event, '', frm, to, node, limit, offset)
        where, args = [], []
        if q:
            where.append('(target LIKE ? OR detail LIKE ? OR user LIKE ?)')
            args += [f'%{q}%'] * 3
        if user:
            where.append('user=?'); args.append(user)
        if event:
            where.append('event=?'); args.append(event)
        if frm:
            where.append('ts>=?'); args.append(frm)
        if to:
            where.append('ts<=?'); args.append(to + 'T23:59:59')
        w = ('WHERE ' + ' AND '.join(where)) if where else ''
        with self.lock:
            total = self.conn.execute(f'SELECT COUNT(*) FROM security_log {w}', args).fetchone()[0]
            rows = [dict(r) for r in self.conn.execute(f'SELECT * FROM security_log {w} ORDER BY id DESC LIMIT ? OFFSET ?', (*args, int(limit), int(offset)))]
            users = [r[0] for r in self.conn.execute('SELECT DISTINCT user FROM security_log ORDER BY user')]
        return {'total': total, 'rows': rows, 'users': users}

    def backup_to(self, path):
        with self.lock:
            target = sqlite3.connect(path)
            try:
                self.conn.backup(target)
            finally:
                target.close()


class UserFolder:
    """Folds admin/account changesets into the users table (see replica.py for the register rules)."""

    def __init__(self, auth, deps_of):
        self.auth = auth
        self.conn = auth.conn
        self.reg = replica.Registers(auth.conn, deps_of)
        self.problems = []

    def fold(self, env, status):
        mk = self.conn.execute('SELECT cseq FROM sync_marker WHERE origin=?', (env['origin'],)).fetchone()
        if mk and mk[0] >= env['cseq']:
            return
        self.reg.current = env
        if status == 'ok' and env['kind'] in ('admin', 'account'):
            for i, op in enumerate(env['ops']):
                self.conn.execute('SAVEPOINT op')
                try:
                    self._op(env, op)
                    self.conn.execute('RELEASE op')
                except replica.ENVIRONMENTAL:
                    raise
                except Exception as e:  # noqa: BLE001 - deterministic, see replica.ENVIRONMENTAL
                    self.conn.execute('ROLLBACK TO op')
                    self.conn.execute('RELEASE op')
                    self.problems.append(f'{env["origin"]}#{env["cseq"]} op {i}: {e}')
        self.reg.current = None
        replica.set_marker(self.conn, env['origin'], env['cseq'])

    def _op(self, env, op):
        e, uid = op.get('e'), op.get('id')
        if e == 'users':
            if not isinstance(uid, str) or not uid:
                raise ValueError('bad user id')
            for f, v in sorted((op.get('s') or {}).items()):
                if f in USER_FIELD_NAMES:
                    self.reg.write('users', uid, f, env, PRIORITY[env['kind']], env['hlc'], v)
            self.materialize(uid, env)
        elif e == 'profiles':
            if not isinstance(uid, str) or not uid:
                raise ValueError('bad profile id')
            for f, v in sorted((op.get('s') or {}).items()):
                if f in PROFILE_FIELD_NAMES:
                    self.reg.write('profiles', uid, f, env, PRIORITY[env['kind']], env['hlc'], v)
            win = self.reg.resolve(self.reg.entries('profiles', uid), {})
            vals = {f: _col(k, win[f].value) if f in win else None for f, k in PROFILE_FIELDS}
            self.conn.execute('INSERT OR REPLACE INTO profiles (id, name, perms, deleted, updated_at, updated_by) VALUES (?,?,?,?,?,?)',
                              (uid, vals['name'], vals['perms'], vals['deleted'] or 0, vals['updated_at'], vals['updated_by']))
        elif e == 'userCommands':
            s = op.get('s') or {}
            if s.get('cmd') == 'unlock':
                self.conn.execute('UPDATE users SET failed=0, locked_until=NULL WHERE id=?', (s.get('user'),))
            elif s.get('cmd') == 'logout':
                self.conn.execute('DELETE FROM sessions WHERE user_id=?', (s.get('user'),))
            elif s.get('cmd') == 'logout-link':  # the old personal link was replaced or switched off
                self.conn.execute("DELETE FROM sessions WHERE user_id=? AND via='link'", (s.get('user'),))

    def materialize(self, uid, env):
        win = self.reg.resolve(self.reg.entries('users', uid), {})
        vals = {f: _col(k, win[f].value) if f in win else None for f, k in USER_FIELDS}
        cur = self.conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if cur is None:
            if not vals['username'] or not vals['full_name'] or not vals['pw_hash']:
                return  # a password change for an account this PC does not know (cannot happen with causal delivery)
            vals = {k: v for k, v in vals.items() if v is not None}
            self.conn.execute(f'INSERT INTO users (id, {", ".join(vals)}) VALUES (?, {", ".join("?" * len(vals))})', (uid, *vals.values()))
            return
        vals = {k: v for k, v in vals.items() if v is not None or k in ('areas',)}
        if all(cur[k] == v for k, v in vals.items()):
            return
        self.conn.execute(f'UPDATE users SET {", ".join(k + "=?" for k in vals)}, ver=ver+1 WHERE id=?', (*vals.values(), uid))
        mine = env['kind'] == 'account' and env['node'] == (self.auth.node.id if self.auth.node else None)
        if vals.get('pw_hash') != cur['pw_hash'] and not mine:
            self.conn.execute('DELETE FROM sessions WHERE user_id=?', (uid,))  # password changed elsewhere: log out here
        if not vals.get('active', 1) or vals.get('deleted'):
            self.conn.execute('DELETE FROM sessions WHERE user_id=?', (uid,))


if __name__ == '__main__':
    if sys.argv[1:] == ['reset-admin']:
        # emergency access: see server/nodectl.py (works on the administrator PC and signs the change)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import nodectl
        sys.exit(nodectl.cmd_reset_admin())
    else:
        print('Usage: python server/auth.py reset-admin')
