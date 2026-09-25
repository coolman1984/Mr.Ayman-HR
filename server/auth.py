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

Run  python server/auth.py reset-admin  on the server PC to regain access when the
administrator password is lost.
"""
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

# (group, [(permission, label)]) - the order is the order shown on the user screen
PERMISSIONS = [
    ('Pages - what the user can see', [
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
    ('Logs & Monitoring', [
        ('logs.view', 'Data changes log (who changed what)'),
        ('logs.activity', 'User activity and errors log'),
        ('logs.security', 'Logins and security log'),
    ]),
    ('Administration', [
        ('settings.view', 'Settings page and server information'),
        ('settings.edit', 'Change general settings (name, locations, targets)'),
        ('backups.manage', 'See and create backups'),
        ('backups.restore', 'Restore a backup (all data goes back in time)'),
        ('trash.restore', 'Recycle Bin: see and restore deleted records'),
        ('data.import', 'Import old data, load or delete all sample data'),
        ('users.manage', 'Manage users, passwords and permissions'),
    ]),
]
ALL = [p for _, ps in PERMISSIONS for p, _ in ps]
PAGES = ['dashboard.view', 'areas.view', 'equipment.view', 'transactions.view', 'maintenance.view', 'surveys.view']
_admin_only = {'users.manage', 'backups.restore', 'data.import', 'logs.security'}
ROLES = {
    'Administrator': ALL,
    'Manager': [p for p in ALL if p not in _admin_only],
    'Data Entry': PAGES + ['inventory.edit', 'issues.create', 'issues.followup', 'maintenance.create', 'maintenance.complete',
                           'inspections.create', 'surveys.create', 'surveys.edit', 'files.upload', 'files.download', 'export.excel', 'print'],
    'Maintenance Team': ['dashboard.view', 'areas.view', 'maintenance.view', 'issues.create', 'issues.followup',
                         'maintenance.complete', 'inspections.create', 'files.upload', 'files.download', 'print'],
    'Viewer': PAGES + ['reports.view', 'files.download', 'print', 'report.register', 'report.inventory', 'report.history',
                       'report.issues', 'report.inspections', 'report.satisfaction', 'report.locations'],
}

ITERATIONS = 600_000
USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{3,32}$')
COMMON = {'password', 'password1', 'password123', '12345678', '123456789', '1234567890', '11111111', '00000000', 'qwerty123',
          'qwertyuiop', 'abc12345', 'admin123', 'admin1234', 'administrator', 'welcome1', 'welcome123', 'letmein1', 'iloveyou',
          'samsung1', 'samsung123', 'factory1', 'changeme', 'p@ssw0rd', 'passw0rd', '87654321', '12341234', 'aa123456'}


class AuthError(Exception):
    """Wrong login, locked account, weak password... (HTTP 400/401)."""


class Forbidden(Exception):
    """The user is logged in but is not allowed to do this (HTTP 403)."""


def now():
    return datetime.now().isoformat(timespec='seconds')


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}'


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
        ''')

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
        username, full_name = (username or '').strip(), (full_name or '').strip()
        if not USERNAME_RE.match(username):
            raise AuthError('User name: 3-32 letters, numbers, dot, dash or underscore (no spaces).')
        if not full_name:
            raise AuthError('Enter the full name.')
        self.check_password(password, username, full_name)
        h = hash_password(password)
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
                if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                    raise AuthError('The administrator account already exists. Please log in.')
                ts = now()
                c.execute('INSERT INTO users (id,username,full_name,title,pw_hash,perms,role,must_change,pw_changed_at,created_at,created_by,updated_at,updated_by) '
                          'VALUES (?,?,?,?,?,?,?,0,?,?,?,?,?)',
                          (uuid.uuid4().hex, username, full_name, 'System Administrator', h, json.dumps(ALL), 'Administrator', ts, ts, 'First setup', ts, 'First setup'))
                c.execute('COMMIT')
            except Exception:
                c.execute('ROLLBACK')
                raise
        self.log(f'{full_name} ({username})', ip, 'setup', username, 'First administrator account created on the server PC')

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
            self.conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)', (_token_hash(token), u['id'], ts, ts, ip, (agent or '')[:300]))
        self.log(u['display'], ip, 'login', username, agent[:300] if agent else '')
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
            if reason:
                self.conn.execute('DELETE FROM sessions WHERE token_hash=?', (th,))
        if reason:
            self.log(u['display'] if u else s['user_id'], ip, 'session-expired', '', reason)
            return None
        if touch and (t - _parse(s['last_seen'])).total_seconds() > 20:
            with self.lock:
                self.conn.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', (t.isoformat(timespec='seconds'), th))
        return u

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
        with self.lock:
            self.conn.execute('UPDATE users SET pw_hash=?, must_change=0, pw_changed_at=?, ver=ver+1 WHERE id=?', (hash_password(new), now(), u['id']))
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
        perms = sorted({p for p in (d.get('perms') or []) if p in ALL})
        areas = d.get('areas')
        areas = None if areas is None else sorted({str(a)[:120] for a in areas})
        active = bool(d.get('active', True))
        must_change = bool(d.get('must_change', True))
        if not full_name:
            raise AuthError('Enter the full name.')
        if not USERNAME_RE.match(username):
            raise AuthError('User name: 3-32 letters, numbers, dot, dash or underscore (no spaces).')
        ts = now()
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
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
                    c.execute('UPDATE users SET username=?, full_name=?, title=?, perms=?, areas=?, role=?, active=?, must_change=?, notes=?, '
                              'updated_at=?, updated_by=?, ver=ver+1 WHERE id=?',
                              (username, full_name, title, json.dumps(perms), json.dumps(areas) if areas is not None else None, role,
                               int(active), int(must_change), notes, ts, actor['display'], uid))
                    new = self._user(c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
                else:
                    password = d.get('password') or ''
                    self.check_password(password, username, full_name)
                    uid = uuid.uuid4().hex
                    c.execute('INSERT INTO users (id,username,full_name,title,pw_hash,perms,areas,role,active,must_change,notes,pw_changed_at,'
                              'created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                              (uid, username, full_name, title, hash_password(password), json.dumps(perms),
                               json.dumps(areas) if areas is not None else None, role, int(active), int(must_change), notes, ts,
                               ts, actor['display'], ts, actor['display']))
                    old, new = None, self._user(c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
                c.execute('COMMIT')
            except Exception:
                c.execute('ROLLBACK')
                raise
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
                n = self._kill(uid)
                self.log(actor['display'], ip, 'user-disabled', new['display'], f'{n} open session(s) logged out')
        return self.public(new)

    def reset_password(self, actor, ip, uid, password):
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        self.check_password(password, u['username'], u['full_name'])
        with self.lock:
            self.conn.execute('UPDATE users SET pw_hash=?, must_change=1, failed=0, locked_until=NULL, pw_changed_at=?, updated_at=?, updated_by=?, ver=ver+1 WHERE id=?',
                              (hash_password(password), now(), now(), actor['display'], uid))
        n = self._kill(uid)
        self.log(actor['display'], ip, 'password-reset', u['display'], f'Temporary password set by the administrator; must be changed at next login; {n} session(s) logged out')

    def unlock(self, actor, ip, uid):
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        with self.lock:
            self.conn.execute('UPDATE users SET failed=0, locked_until=NULL WHERE id=?', (uid,))
        self.log(actor['display'], ip, 'user-unlocked', u['display'])

    def force_logout(self, actor, ip, uid):
        u = self.get(uid)
        if not u:
            raise AuthError('This user no longer exists.')
        n = self._kill(uid)
        self.log(actor['display'], ip, 'forced-logout', u['display'], f'{n} session(s) ended by the administrator')
        return n

    def delete_user(self, actor, ip, uid):
        """Soft delete: the account disappears and can never log in again, but its name stays in all logs."""
        if uid == actor['id']:
            raise AuthError('You cannot delete your own account.')
        with self.lock:
            c = self.conn
            u = self._user(c.execute('SELECT * FROM users WHERE id=? AND deleted=0', (uid,)).fetchone())
            if not u:
                raise AuthError('This user no longer exists.')
            if 'users.manage' in u['perms'] and u['active'] and not self._admins(c, exclude=uid):
                raise AuthError('At least one active user must keep the right to manage users.')
            c.execute('UPDATE users SET deleted=1, active=0, updated_at=?, updated_by=?, ver=ver+1 WHERE id=?', (now(), actor['display'], uid))
        self._kill(uid)
        self.log(actor['display'], ip, 'user-deleted', u['display'], 'Account deleted (kept in the logs; the user name stays reserved)')

    # ------------------------------------------------------------ log / backup
    def query_log(self, q='', user='', event='', frm='', to='', limit=200, offset=0):
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


def _reset_admin():
    """Emergency access from the server PC: give an administrator a new temporary password."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.environ.get('BAMS_CONFIG') or os.path.join(root, 'config.json')
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding='utf-8') as f:
            cfg = json.load(f)
    data_dir = cfg.get('data_dir', 'data')
    data_dir = data_dir if os.path.isabs(data_dir) else os.path.join(root, data_dir)
    os.makedirs(data_dir, exist_ok=True)
    a = Auth(data_dir, cfg)
    pw = 'Reset-' + secrets.token_urlsafe(6).replace('_', 'x').replace('-', 'y') + '7'
    admins = [a._user(r) for r in a.conn.execute('SELECT * FROM users WHERE deleted=0 ORDER BY created_at')]
    admins = [u for u in admins if 'users.manage' in u['perms']]
    if admins:
        u = admins[0]
        a.conn.execute('UPDATE users SET pw_hash=?, must_change=1, failed=0, locked_until=NULL, active=1, pw_changed_at=?, ver=ver+1 WHERE id=?',
                       (hash_password(pw), now(), u['id']))
        a._kill(u['id'])
        name = u['username']
    else:
        name = 'admin'
        while a.conn.execute('SELECT 1 FROM users WHERE username=?', (name,)).fetchone():
            name += '1'
        ts = now()
        a.conn.execute('INSERT INTO users (id,username,full_name,title,pw_hash,perms,role,must_change,pw_changed_at,created_at,created_by,updated_at,updated_by) '
                       'VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?)',
                       (uuid.uuid4().hex, name, 'Administrator', 'System Administrator', hash_password(pw), json.dumps(ALL), 'Administrator',
                        ts, ts, 'reset-admin', ts, 'reset-admin'))
    a.log('Server PC', '127.0.0.1', 'admin-reset', name, 'Emergency password reset from the server PC (reset_admin.bat)')
    print('=' * 64)
    print(' Administrator access restored')
    print(f' User name:          {name}')
    print(f' Temporary password: {pw}')
    print(' Log in with it now - you will be asked to choose a new password.')
    print('=' * 64)


if __name__ == '__main__':
    if sys.argv[1:] == ['reset-admin']:
        _reset_admin()
    else:
        print('Usage: python server/auth.py reset-admin')
