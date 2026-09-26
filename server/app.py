"""Break Area Management System - local web server.

Runs with the Python standard library only (no pip install needed).
Start it with start.bat; every PC on the network can then open the address
printed in the console window. Everybody must log in; what each user may see and
do is set by the administrator (Users page) and checked here for every request.
"""
import hashlib
import json
import logging
import logging.handlers
import mimetypes
import os
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # the portable (embedded) Python does not add the script folder itself

import xlsx  # noqa: E402
from auth import ALL, PERMISSIONS, ROLES, AuthError, Forbidden  # noqa: E402
from store import BadRequest, Conflict, now  # noqa: E402
from sync import SyncService  # noqa: E402
from system import System  # noqa: E402

ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.environ.get('BAMS_CONFIG') or os.path.join(ROOT, 'config.json')
DEFAULT_CONFIG = {
    'port': 8080,
    'host': '0.0.0.0',
    'data_dir': 'data',
    'backup_dir': 'backups',
    'extra_backup_dirs': [],
    'backup_interval_hours': 6,
    'keep_auto_backups': 200,
    'max_upload_mb': 50,
    'open_browser': True,
    'session_idle_minutes': 30,
    'session_max_hours': 12,
    'max_failed_logins': 5,
    'lockout_minutes': 15,
    'min_password_length': 8,
    'device_name': '',
    'sync_enabled': True,
    'sync_port': 8443,
    'sync_interval_seconds': 5,
    'peer_addresses': {},
}
STATIC = {'/': 'index.html', '/index.html': 'index.html'}
STATIC_DIRS = ('/css/', '/js/', '/lib/')
UPLOAD_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
              '.ppt', '.pptx', '.txt', '.csv', '.zip'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic'}
INLINE_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.pdf'}
TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8',
         '.json': 'application/json', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.heic': 'image/heic',
         '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    else:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    return cfg


def resolve(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


CFG = load_config()
DATA_DIR = resolve(CFG['data_dir'])
UPLOADS = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, 'logs'), exist_ok=True)

log = logging.getLogger('bams')
log.setLevel(logging.INFO)
_fh = logging.handlers.RotatingFileHandler(os.path.join(DATA_DIR, 'logs', 'server.log'), maxBytes=5 * 1048576, backupCount=20, encoding='utf-8')
_fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
log.addHandler(_fh)


def say(msg):
    log.info(msg)
    print(f'[{datetime.now():%H:%M:%S}] {msg}', flush=True)


SYSTEM = System(DATA_DIR, CFG, UPLOADS, resolve(CFG['backup_dir']), [resolve(d) for d in CFG['extra_backup_dirs']], log=say)
STORE, AUTH, BACKUPS, JOURNAL, NODE = SYSTEM.store, SYSTEM.auth, SYSTEM.backups, SYSTEM.journal, SYSTEM.node
SYNC = SyncService(SYSTEM, CFG, UPLOADS, log=say)
PLACEHOLDER = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200"><rect width="320" height="200" fill="#eef1f5"/>'
               b'<text x="160" y="96" font-family="Segoe UI,Arial" font-size="15" text-anchor="middle" fill="#6b7785">Photo is being copied</text>'
               b'<text x="160" y="118" font-family="Segoe UI,Arial" font-size="12" text-anchor="middle" fill="#8a95a3">from another PC\u2026</text></svg>')
COOKIE = 'bams_sid'
LOCAL_IPS = ('127.0.0.1', '::1', '::ffff:127.0.0.1')
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self' data: blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
PERM_LABEL = {p: label for _, ps in PERMISSIONS for p, label in ps}
REPORT_PERMS = [p for p in ALL if p.startswith('report.')] + ['export.excel', 'logs.view', 'logs.activity', 'logs.security']
ENTITY_TITLE = {'areas': 'break areas', 'inventory': 'inventory', 'surveys': 'satisfaction results', 'photos': 'photos',
                'docs': 'documents', 'issues': 'issues', 'issueLog': 'issue follow-ups', 'maintenance': 'maintenance',
                'inspections': 'inspections', 'history': 'transactions', 'itemTypes': 'item types', 'settings': 'settings'}
OP_WORD = {'insert': 'add', 'update': 'change', 'delete': 'delete'}
HISTORY_PERMS = ('inventory.edit', 'inventory.delete', 'areas.create', 'areas.edit', 'maintenance.complete')


def required(entity, op, changed):
    """The permissions (any one of them is enough) needed for one saved change."""
    if entity == 'areas':
        if op == 'insert':
            return ('areas.create',)
        if op == 'delete':
            return ('areas.delete',)
        keys = set(changed)
        if keys <= {'status'}:  # reporting an issue / scheduling or completing maintenance can set the status
            return ('areas.edit', 'issues.create', 'maintenance.create', 'maintenance.complete')
        if keys <= {'lastInspection', 'nextInspection', 'inspectedBy'}:
            return ('areas.edit', 'inspections.create', 'inspections.delete')
        return ('areas.edit',)
    if entity == 'inventory':
        return ('inventory.delete', 'itemtypes.manage') if op == 'delete' else ('inventory.edit',)
    if entity == 'history':
        return HISTORY_PERMS if op == 'insert' else ('areas.delete',)
    return {
        'surveys': {'insert': ('surveys.create',), 'update': ('surveys.edit',), 'delete': ('surveys.delete',)},
        'photos': {'insert': ('files.upload', 'areas.create'), 'update': ('files.upload', 'files.delete'), 'delete': ('files.delete',)},
        'docs': {'insert': ('files.upload',), 'update': ('files.upload',), 'delete': ('files.delete',)},
        'issues': {'insert': ('issues.create',), 'update': ('issues.followup',), 'delete': ('issues.delete',)},
        'issueLog': {'insert': ('issues.followup',), 'update': ('issues.followup',), 'delete': ('issues.delete',)},
        'maintenance': {'insert': ('maintenance.create',), 'update': ('maintenance.complete',), 'delete': ('maintenance.delete',)},
        'inspections': {'insert': ('inspections.create',), 'update': ('inspections.create',), 'delete': ('inspections.delete',)},
        'itemTypes': {'insert': ('itemtypes.manage',), 'update': ('itemtypes.manage',), 'delete': ('itemtypes.manage',)},
        'settings': {'insert': ('settings.edit',), 'update': ('settings.edit',), 'delete': ('settings.edit',)},
    }[entity][op]


def commit_guard(u):
    """Checks every change of a save against the user's permissions and break areas."""
    perms, scope = set(u['perms']), (None if u['areas'] is None else set(u['areas']))

    def guard(changes, force):
        if force:  # replaces everything: import, load sample data, delete all sample data
            if 'data.import' not in perms or scope is not None:
                raise Forbidden('Only a user with the permission "' + PERM_LABEL['data.import'] + '" for all break areas can replace all data.')
            return
        created = {c['id'] for c in changes if c['entity'] == 'areas' and c['op'] == 'insert'}
        removed = {c['id'] for c in changes if c['entity'] == 'areas' and c['op'] == 'delete'}
        for c in changes:
            e, op, area = c['entity'], c['op'], c['area']
            if scope is not None and e not in ('settings', 'itemTypes') and area not in scope:
                raise Forbidden('You are limited to certain break areas and cannot add new ones.' if e == 'areas' and op == 'insert'
                                else 'You can only change the break areas assigned to you.')
            if e != 'areas' and op == 'insert' and area in created and 'areas.create' in perms:
                continue  # contents of a break area that is being created
            if e != 'areas' and op == 'delete' and area in removed and 'areas.delete' in perms:
                continue  # contents of a break area that is being deleted
            need = required(e, op, c['changes'])
            if not perms.intersection(need):
                raise Forbidden(f'You are not allowed to {OP_WORD[op]} {ENTITY_TITLE[e]}. Ask the administrator for the permission "{PERM_LABEL[need[0]]}".')
    return guard


def lan_urls(port):
    urls = [f'http://{socket.gethostname()}:{port}/']
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith('127.'):
                urls.append(f'http://{ip}:{port}/')
    except OSError:
        pass
    return urls


class NotLoggedIn(Exception):
    pass


def is_admin(u):
    """Administrator = may manage users. Monitoring, devices and conflicts need this, checked on every request."""
    return bool(u) and 'users.manage' in u['perms']


class Handler(BaseHTTPRequestHandler):
    server_version = 'BAMS/1.0'
    protocol_version = 'HTTP/1.1'
    u = None  # the logged-in user of this request (set by login_required)
    _read = False  # True once the request body was read

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):
        pass  # API calls are logged explicitly below; static files are not worth logging

    @property
    def user(self):
        return self.u['display'] if self.u else 'Not logged in'

    @property
    def ip(self):
        return self.client_address[0]

    @property
    def token(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == COOKIE:
                return v
        return ''

    def login_required(self, touch=True):
        self.u = AUTH.session(self.token, self.ip, touch)
        if not self.u:
            raise NotLoggedIn()
        return self.u

    def can(self, *perms):
        return bool(self.u) and any(p in self.u['perms'] for p in perms)

    def need(self, *perms):
        if not self.can(*perms):
            raise Forbidden('You do not have permission for this. Ask the administrator for: "' + PERM_LABEL[perms[0]] + '".')

    def send(self, code, body=b'', ctype='application/json', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        unread = self.command == 'POST' and not self._read and int(self.headers.get('Content-Length') or 0)
        if code >= 400 or unread:  # the request body may be unread - don't reuse this connection
            self.close_connection = True
            self.send_header('Connection', 'close')
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        if ctype.startswith('text/html'):
            self.send_header('Content-Security-Policy', CSP)
        headers = dict(headers or {})
        if self.path.startswith('/api/'):
            headers.setdefault('Cache-Control', 'no-store')
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def set_session(self, token):
        return {'Set-Cookie': f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict'}

    def clear_session(self):
        return {'Set-Cookie': f'{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'}

    def body(self, limit=20 * 1048576):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            raise BadRequest(f'Request too large ({n // 1048576} MB)')
        self._read = True
        return self.rfile.read(n) if n else b''

    def json_body(self):
        raw = self.body(200 * 1048576)
        return json.loads(raw.decode('utf-8')) if raw else {}

    def denied(self, msg):
        AUTH.log(self.user, self.ip, 'access-denied', self.path.split('?')[0], msg)
        try:
            STORE.log_activity(self.user, self.ip, [{'type': 'denied', 'action': self.path.split('?')[0], 'detail': msg}])
        except Exception:
            pass

    def handle_safely(self, fn):
        try:
            fn()
        except NotLoggedIn:
            self.send(401, {'error': 'Please log in.', 'login': True}, headers=self.clear_session())
        except Forbidden as e:
            log.info('DENIED %s %s %s', self.user, self.path, e)
            self.denied(str(e))
            self.send(403, {'error': str(e)})
        except AuthError as e:
            self.send(400, {'error': str(e)})
        except Conflict as e:
            log.info('CONFLICT %s %s %s', self.user, self.path, e)
            self.send(409, {'error': str(e)})
        except (BadRequest, ValueError) as e:
            log.info('BAD REQUEST %s %s %s', self.user, self.path, e)
            self.send(400, {'error': str(e)})
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:
            tb = traceback.format_exc()
            log.error('ERROR %s %s\n%s', self.user, self.path, tb)
            try:
                STORE.log_activity(self.user, self.ip, [{'type': 'server-error', 'action': self.path, 'detail': tb[-1900:]}])
            except Exception:
                pass
            self.send(500, {'error': f'Server error: {e}'})

    # ------------------------------------------------------------ routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.u = None
        self.handle_safely(self._get)

    def do_POST(self):
        self.u, self._read = None, False
        self.handle_safely(self._post)

    def me(self):
        u = self.u
        return {**AUTH.public(u), 'display': u['display'], 'permissions': PERMISSIONS, 'roles': ROLES,
                'sessionIdleMinutes': CFG['session_idle_minutes'], 'minPasswordLength': AUTH.min_len, 'admin': is_admin(u),
                'node': {'id': NODE.id, 'name': NODE.name, 'role': NODE.role, 'authority': NODE.is_authority}}

    def need_admin(self):
        if not is_admin(self.u):
            raise Forbidden('Only an administrator can open this.')

    def node_status(self):
        j = JOURNAL.meta('join')
        return {'role': NODE.role, 'name': NODE.name, 'id': NODE.id, 'moved': NODE.moved,
                'join': {'confirm': j['confirm'], 'authority': j.get('authority')} if j and NODE.role == 'unconfigured' else None}

    def _get(self):
        url = urlparse(self.path)
        p, qs = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        if p in STATIC:
            return self.serve_file(ROOT, STATIC[p])
        if p.startswith(STATIC_DIRS):
            return self.serve_file(ROOT, p.lstrip('/'))
        if p == '/api/auth/status':
            u = AUTH.session(self.token, self.ip, touch=False)
            self.u = u
            return self.send(200, {'hasUsers': AUTH.has_users(), 'local': self.ip in LOCAL_IPS, 'me': self.me() if u else None,
                                   'node': self.node_status()})
        if p == '/api/join/status':
            if self.ip not in LOCAL_IPS or AUTH.has_users() and NODE.role != 'member':
                raise Forbidden('Only on this PC itself.')
            return self.send(200, {**SYNC.join_progress(), 'hasUsers': AUTH.has_users()})

        self.login_required(touch=p != '/api/version')
        if p == '/api/me':
            return self.send(200, self.me())
        if p == '/api/state':
            return self.send(200, STORE.state(self.u['areas'], self.can('surveys.view')))
        if p == '/api/version':
            return self.send(200, {'version': STORE.version(), 'me': self.u['ver'], 'mustChange': bool(self.u['must_change']),
                                   'sync': SYNC.summary()})
        if p == '/api/info':
            urls = lan_urls(CFG['port'])
            if not self.can('settings.view'):
                return self.send(200, {'urls': urls})
            db_size = sum(os.path.getsize(os.path.join(DATA_DIR, f)) for f in os.listdir(DATA_DIR) if f.startswith('bams.db'))
            up_size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(UPLOADS) for f in fs)
            return self.send(200, {'urls': urls, 'dataDir': DATA_DIR, 'backupDir': BACKUPS.dir,
                                   'extraBackupDirs': BACKUPS.extra, 'dbSize': db_size, 'uploadsSize': up_size,
                                   'backupIntervalHours': CFG['backup_interval_hours'], 'lastBackupError': BACKUPS.last_error,
                                   'counts': STORE.counts(), 'serverTime': now()})
        if p == '/api/backups':
            self.need('backups.manage', 'backups.restore')
            return self.send(200, BACKUPS.list())
        if p == '/api/trash':
            self.need('trash.restore')
            return self.send(200, STORE.trash())
        if p in ('/api/audit', '/api/activity'):
            self.need('logs.view' if p == '/api/audit' else 'logs.activity')
            if p == '/api/activity':
                self.need_admin()  # what other people clicked is forensic data: administrators only
            node = qs.get('node', '') if is_admin(self.u) else ''
            return self.send(200, STORE.query_log('audit' if p == '/api/audit' else 'activity', qs.get('q', ''), qs.get('user', ''),
                                                  qs.get('type', ''), qs.get('area', ''), qs.get('from', ''), qs.get('to', ''),
                                                  min(1000, int(qs.get('limit', 200))), int(qs.get('offset', 0)), self.u['areas'], node))
        if p == '/api/security':
            self.need('logs.security')
            self.need_admin()
            return self.send(200, AUTH.query_log(qs.get('q', ''), qs.get('user', ''), qs.get('type', ''), qs.get('from', ''), qs.get('to', ''),
                                                 min(1000, int(qs.get('limit', 200))), int(qs.get('offset', 0)), qs.get('node', '')))
        if p == '/api/devices':
            self.need_admin()
            return self.send(200, SYNC.overview())
        if p == '/api/devices/log':
            self.need_admin()
            with JOURNAL.lock:
                rows = [dict(r) for r in JOURNAL.conn.execute('SELECT * FROM sync_log ORDER BY id DESC LIMIT ?', (min(1000, int(qs.get('limit', 300))),))]
            return self.send(200, rows)
        if p == '/api/conflicts':
            self.need_admin()
            return self.send(200, self.conflict_list())
        if p == '/api/users':
            self.need('users.manage')
            return self.send(200, {'users': AUTH.list_users(), 'permissions': PERMISSIONS, 'roles': ROLES, 'authority': NODE.is_authority,
                                   'authorityHint': '' if NODE.is_authority else AUTH.authority_hint()})
        if p == '/api/export.xlsx':
            self.need('report.full')
            if self.u['areas'] is not None:
                raise Forbidden('The complete export contains all break areas; you only have access to some of them.')
            data = xlsx.build(STORE.export_sheets())
            log.info('EXPORT full workbook by %s (%s)', self.user, self.ip)
            STORE.log_activity(self.user, self.ip, [{'type': 'export', 'action': 'Full Excel export', 'target': 'All data'}])
            return self.send(200, data, TYPES['.xlsx'], {'Content-Disposition': f'attachment; filename="BAMS_Full_Export_{datetime.now():%Y-%m-%d_%H%M}.xlsx"'})
        if p.startswith('/files/'):
            if os.path.splitext(p)[1].lower() not in IMAGE_EXT:
                self.need('files.download')
            return self.serve_file(UPLOADS, p[len('/files/'):], upload=True, src=p)
        self.send(404, {'error': 'Not found'})

    def _post(self):
        p = urlparse(self.path).path
        qs = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            raise Forbidden('Request from another web site was blocked.')

        # ---------------- no login needed
        if p == '/api/auth/login':
            d = self.json_body()
            try:
                token, u = AUTH.login(d.get('username'), d.get('password'), self.ip, self.headers.get('User-Agent', ''))
            except AuthError:
                time.sleep(0.6)  # slows down password guessing
                raise
            self.u = u
            say(f'Login: {u["display"]} ({self.ip})')
            return self.send(200, self.me(), headers=self.set_session(token))
        if p == '/api/join':
            if self.ip not in LOCAL_IPS or AUTH.has_users() or NODE.role != 'unconfigured':
                raise Forbidden('Joining is only possible on a new, not yet set up PC, on the PC itself.')
            d = self.json_body()
            try:
                return self.send(200, SYNC.join(d.get('address'), d.get('code'), d.get('name')))
            except ValueError as e:
                raise BadRequest(str(e))
        if p == '/api/join/cancel':
            if self.ip not in LOCAL_IPS or NODE.role != 'unconfigured':
                raise Forbidden('Not possible.')
            JOURNAL.set_meta('join', None)
            return self.send(200, {'ok': True})
        if p == '/api/node/moved':
            if self.ip not in LOCAL_IPS or not NODE.moved:
                raise Forbidden('Only on this PC itself.')
            choice = self.json_body().get('choice')
            if choice == 'same':
                NODE.confirm_same_machine()
                AUTH.log('This PC', self.ip, 'node-confirmed', NODE.name, 'Confirmed on this PC: same computer as before (name or network card changed)')
                SYNC.kick()
                return self.send(200, {'ok': True})
            if choice == 'new':
                with open(os.path.join(NODE.dir, 'RESET_REQUESTED'), 'w') as f:
                    f.write(now())
                return self.send(200, {'ok': True, 'restart': True})
            raise BadRequest('Choose same or new')
        if p == '/api/auth/setup':
            if self.ip not in LOCAL_IPS:
                raise Forbidden('The first administrator account can only be created on the server PC itself.')
            d = self.json_body()
            AUTH.setup(d.get('username'), d.get('full_name'), d.get('password'), self.ip)
            token, self.u = AUTH.login(d.get('username'), d.get('password'), self.ip, self.headers.get('User-Agent', ''))
            say(f'Administrator account created: {self.u["display"]}')
            return self.send(200, self.me(), headers=self.set_session(token))
        if p == '/api/auth/logout':
            u = AUTH.session(self.token, self.ip, touch=False)
            AUTH.logout(self.token, u, self.ip)
            return self.send(200, {'ok': True}, headers=self.clear_session())

        # ---------------- logged in
        self.login_required()
        if p == '/api/auth/password':
            d = self.json_body()
            AUTH.change_password(self.u, d.get('old'), d.get('new'), self.ip, self.token)
            self.u = AUTH.get(self.u['id'])
            return self.send(200, self.me())
        if p == '/api/log':
            d = self.json_body()
            events = [{**e, 'user': self.user} for e in (d.get('events') or []) if isinstance(e, dict)]  # never trust a name sent by the page
            STORE.log_activity(self.user, self.ip, events)
            return self.send(200, {'ok': True})
        if self.u['must_change']:
            raise Forbidden('Please change your temporary password first.')
        if NODE.moved:
            raise Forbidden('This PC needs a decision first: its data folder seems to come from another PC. Open the system on this PC itself.')
        if p == '/api/commit':
            d = self.json_body()
            label = str(d.get('label') or 'Change')[:200]
            force = bool(d.get('force'))
            if force:
                self.need('data.import')
                if STORE.counts().get('Break Areas'):
                    BACKUPS.create('pre-import')
            res = STORE.commit(self.user, self.ip, label, d.get('ops'), force, guard=commit_guard(self.u), user_id=self.u['id'])
            log.info('COMMIT %s (%s) "%s" %s changes', self.user, self.ip, label, res['changes'])
            return self.send(200, res)
        if p == '/api/first-run':
            self.need('data.import')
            won = STORE.claim_first_run()
            if won:
                say(f'New database - sample data is being loaded by {self.user} ({self.ip})')
            return self.send(200, {'loadSample': won})
        if p == '/api/upload':
            self.need('files.upload', 'areas.create', 'settings.edit', 'data.import')
            return self.upload(qs.get('name', 'file'))
        if p == '/api/xlsx':
            self.need(*REPORT_PERMS)
            d = self.json_body()
            data = xlsx.build([(s.get('name', 'Sheet'), s.get('head', []), s.get('rows', [])) for s in d.get('sheets', [])])
            name = ''.join(ch for ch in str(d.get('filename') or 'export') if ch.isalnum() or ch in ' _-.')[:80]
            return self.send(200, data, TYPES['.xlsx'], {'Content-Disposition': f'attachment; filename="{name}.xlsx"'})
        if p == '/api/backups':
            self.need('backups.manage')
            name = BACKUPS.create('manual')
            log.info('BACKUP manual by %s: %s', self.user, name)
            STORE.log_activity(self.user, self.ip, [{'type': 'backup', 'action': 'Backup created', 'target': name}])
            return self.send(200, {'name': name})
        if p == '/api/backups/restore':
            self.need('backups.restore')
            d = self.json_body()
            safety, res = BACKUPS.restore(d.get('name'), self.user, self.ip, self.u['id'])
            STORE.log_activity(self.user, self.ip, [{'type': 'restore', 'action': 'Restored backup', 'target': d.get('name'),
                                                      'detail': f'{res["changes"]} records brought back; safety backup before restore: {safety}'}])
            AUTH.log(self.user, self.ip, 'backup-restored', d.get('name'), f'{res["changes"]} records changed back; safety backup: {safety}')
            say(f'Backup {d.get("name")} restored by {self.user} ({self.ip}); {res["changes"]} records; previous data saved as {safety}')
            return self.send(200, {'ok': True, 'safety': safety, 'changes': res['changes']})
        if p == '/api/trash/restore':
            self.need('trash.restore')
            d = self.json_body()
            return self.send(200, STORE.restore_txn(self.user, self.ip, str(d.get('txn'))))
        if p.startswith('/api/devices/'):
            self.need_admin()
            d = self.json_body()
            action = p[len('/api/devices/'):]
            try:
                if action == 'invite':
                    return self.send(200, SYNC.create_invite(self.user))
                if action == 'decide':
                    SYNC.decide(str(d.get('id')), bool(d.get('approve')), self.u)
                elif action == 'update':
                    SYNC.update_node(str(d.get('id')), self.u, name=d.get('name'), address=d.get('address'))
                elif action == 'revoke':
                    SYNC.update_node(str(d.get('id')), self.u, revoke=True)
                elif action == 'sync-now':
                    for st in SYNC.status.values():
                        st['fails'] = 0
                    SYNC.kick()
                elif action == 'verify':
                    rep = JOURNAL.verify(all_signatures=bool(d.get('all')))
                    AUTH.log(self.user, self.ip, 'integrity-check', 'history', 'OK' if rep['ok'] else f'{rep["problemCount"]} problem(s)')
                    return self.send(200, rep)
                elif action == 'ack':
                    JOURNAL.ack_alert(str(d.get('key')))
                else:
                    return self.send(404, {'error': 'Not found'})
            except PermissionError as e:
                raise Forbidden(str(e))
            except ValueError as e:
                raise BadRequest(str(e))
            return self.send(200, {'ok': True})
        if p == '/api/conflicts/resolve':
            self.need_admin()
            return self.send(200, self.resolve_conflict(self.json_body()))
        if p.startswith('/api/users/'):
            self.need('users.manage')
            d = self.json_body()
            action = p[len('/api/users/'):]
            if action == 'save':
                return self.send(200, AUTH.save_user(self.u, self.ip, d))
            uid = str(d.get('id') or '')
            if action == 'reset':
                AUTH.reset_password(self.u, self.ip, uid, d.get('password'))
            elif action == 'unlock':
                AUTH.unlock(self.u, self.ip, uid)
            elif action == 'logout':
                AUTH.force_logout(self.u, self.ip, uid)
            elif action == 'delete':
                AUTH.delete_user(self.u, self.ip, uid)
            else:
                return self.send(404, {'error': 'Not found'})
            return self.send(200, {'ok': True})
        self.send(404, {'error': 'Not found'})

    # ------------------------------------------------------------ conflicts
    def conflict_list(self):
        out = STORE.conflicts()
        who = {}
        for c in out:
            if c['kind'] == 'conflict':
                for fld, entries in c['detail'].items():
                    for e in entries:
                        k = (e['origin'], e['cseq'])
                        if k not in who:
                            who[k] = JOURNAL.describe(*k)
                        e['by'] = who[k]
            elif c['kind'] == 'deleted-edit':
                c['delete_by'] = JOURNAL.describe(*c['detail']['delete'])
                c['edits_by'] = [JOURNAL.describe(*x) for x in c['detail']['edits'][:10]]
        return out

    def resolve_conflict(self, d):
        """The administrator decides: one value for a field, keep a record deleted, or bring it back."""
        from store import ENTITIES
        entity, rid, action = d.get('entity'), str(d.get('id') or ''), d.get('action')
        if entity not in ENTITIES:
            raise BadRequest('Unknown record type')
        table = ENTITIES[entity][0]
        with STORE.lock:
            r = STORE.conn.execute(f'SELECT * FROM {table} WHERE id=?', (rid,)).fetchone()
        if not r:
            raise BadRequest('Record not found')
        row = STORE._row_js(entity, r)
        ver = row.pop('ver')
        if action == 'value':
            field = d.get('field')
            row[field] = d.get('value')
            op = {'e': entity, 'id': rid, 'op': 'put', 'row': row, 'ver': ver, 'resolve': [field]}
            label = f'Conflict resolved: {field}'
        elif action == 'keep-deleted':
            op = {'e': entity, 'id': rid, 'op': 'del', 'resolve': True}
            label = 'Conflict resolved: keep deleted'
        elif action == 'restore':
            op = {'e': entity, 'id': rid, 'op': 'put', 'row': row}
            label = 'Conflict resolved: record restored'
        else:
            raise BadRequest('Unknown action')
        res = STORE.commit(self.user, self.ip, label, [op], force=action != 'value', user_id=self.u['id'])
        AUTH.log(self.user, self.ip, 'conflict-resolved', f'{entity} {rid}', label)
        return res

    # ------------------------------------------------------------ files
    def upload(self, name):
        ext = os.path.splitext(name)[1].lower()
        if ext not in UPLOAD_EXT:
            raise BadRequest(f'File type {ext or "(none)"} is not allowed')
        data = self.body(int(CFG['max_upload_mb']) * 1048576)
        if not data:
            raise BadRequest('Empty file')
        # content-addressed: the name is the SHA-256 of the content, so the same file is stored once and every PC can check its copy
        sha = hashlib.sha256(data).hexdigest()
        os.makedirs(os.path.join(UPLOADS, 'cas'), exist_ok=True)
        path = os.path.join(UPLOADS, 'cas', sha + ext)
        if not os.path.exists(path):
            tmp = os.path.join(UPLOADS, 'cas', f'.{sha}.{uuid.uuid4().hex[:8]}.tmp')
            with open(tmp, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        src = f'/files/cas/{sha}{ext}'
        STORE.record_file(src, sha, len(data), mimetypes.guess_type(path)[0] or '', self.user, self.ip, self.u['id'])
        log.info('UPLOAD %s (%s) %s -> %s %d bytes', self.user, self.ip, name, src, len(data))
        self.send(200, {'src': src, 'size': len(data)})

    def serve_file(self, base, rel, upload=False, src=None):
        base = os.path.realpath(base)
        path = os.path.realpath(os.path.join(base, unquote(rel)))
        if not path.startswith(base + os.sep) or not os.path.isfile(path):
            if upload and src and STORE.file_info(unquote(src)) and os.path.splitext(path)[1].lower() in IMAGE_EXT:
                # known file that has not been copied from another PC yet - never cached
                return self.send(200, PLACEHOLDER, 'image/svg+xml', {'Cache-Control': 'no-store'})
            if upload and src and STORE.file_info(unquote(src)):
                return self.send(404, {'error': 'This file is still being copied from another PC. Try again in a minute.'})
            return self.send(404, {'error': 'File not found'})
        ext = os.path.splitext(path)[1].lower()
        if upload and ext not in UPLOAD_EXT:
            return self.send(404, {'error': 'File not found'})
        ctype = TYPES.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        headers = {'Cache-Control': 'public, max-age=31536000, immutable'} if upload else {'Cache-Control': 'no-cache'}
        if upload and ext not in INLINE_EXT:
            headers['Content-Disposition'] = 'attachment'
        with open(path, 'rb') as f:
            self.send(200, f.read(), ctype, headers)


class Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != 'nt'  # Windows: reuse would let a second copy share the port silently; elsewhere it only skips TIME_WAIT
    daemon_threads = True


def main():
    port = int(CFG['port'])
    try:
        httpd = Server((CFG['host'], port), Handler)
    except OSError:
        print(f'Port {port} is already in use - the system is probably already running. Opening it in the browser.')
        webbrowser.open(f'http://localhost:{port}/')
        return

    try:
        if STORE.counts().get('Break Areas'):
            BACKUPS.create('startup')
    except Exception as e:
        say('Startup backup failed: ' + str(e))
    BACKUPS.start()
    SYNC.start()

    print('=' * 64)
    print(' Break Area Management System is running')
    print(f' This PC:        http://localhost:{port}/')
    for u in lan_urls(port):
        print(f' Other PCs:      {u}')
    print(f' This PC:        "{NODE.name}" ({NODE.role}, id {NODE.id}), sync port {SYNC.port}')
    print(f' Data folder:    {DATA_DIR}')
    print(f' Backups folder: {BACKUPS.dir}')
    if not AUTH.has_users():
        print(' FIRST START: open http://localhost:%d/ on THIS PC to create the' % port)
        print('              administrator account (not possible from other PCs).')
    print(' Keep this window open. Close it to stop the system.')
    print('=' * 64, flush=True)
    say('Server started')
    if CFG.get('open_browser', True):
        threading.Timer(0.8, lambda: webbrowser.open(f'http://localhost:{port}/')).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        SYNC.shutdown()
        JOURNAL.flush_activity()
        say('Server stopped')


if __name__ == '__main__':
    main()
