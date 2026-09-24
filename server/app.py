"""Break Area Management System - local web server.

Runs with the Python standard library only (no pip install needed).
Start it with start.bat; every PC on the network can then open the address
printed in the console window.
"""
import json
import logging
import logging.handlers
import mimetypes
import os
import socket
import sys
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # the portable (embedded) Python does not add the script folder itself

import xlsx  # noqa: E402
from backup import Backups  # noqa: E402
from store import BadRequest, Conflict, Store, now  # noqa: E402

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
}
STATIC = {'/': 'index.html', '/index.html': 'index.html'}
STATIC_DIRS = ('/css/', '/js/', '/lib/')
UPLOAD_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
              '.ppt', '.pptx', '.txt', '.csv', '.zip'}
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


STORE = Store(DATA_DIR)
BACKUPS = Backups(STORE, UPLOADS, resolve(CFG['backup_dir']), [resolve(d) for d in CFG['extra_backup_dirs']],
                  CFG['keep_auto_backups'], CFG['backup_interval_hours'], log=say)


def lan_urls(port):
    urls = [f'http://{socket.gethostname()}:{port}/']
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith('127.'):
                urls.append(f'http://{ip}:{port}/')
    except OSError:
        pass
    return urls


class Handler(BaseHTTPRequestHandler):
    server_version = 'BAMS/1.0'
    protocol_version = 'HTTP/1.1'

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):
        pass  # API calls are logged explicitly below; static files are not worth logging

    @property
    def user(self):
        return unquote(self.headers.get('X-User') or '').strip()[:80] or 'Unknown'

    @property
    def ip(self):
        return self.client_address[0]

    def send(self, code, body=b'', ctype='application/json', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        if code >= 400:  # the request body may be unread - don't reuse this connection
            self.close_connection = True
            self.send_header('Connection', 'close')
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def body(self, limit=20 * 1048576):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            raise BadRequest(f'Request too large ({n // 1048576} MB)')
        return self.rfile.read(n) if n else b''

    def json_body(self):
        raw = self.body(200 * 1048576)
        return json.loads(raw.decode('utf-8')) if raw else {}

    def handle_safely(self, fn):
        try:
            fn()
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
        self.handle_safely(self._get)

    def do_POST(self):
        self.handle_safely(self._post)

    def _get(self):
        url = urlparse(self.path)
        p, qs = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        if p == '/api/state':
            return self.send(200, STORE.state(), headers={'Cache-Control': 'no-store'})
        if p == '/api/version':
            return self.send(200, {'version': STORE.version()}, headers={'Cache-Control': 'no-store'})
        if p == '/api/info':
            db_size = sum(os.path.getsize(os.path.join(DATA_DIR, f)) for f in os.listdir(DATA_DIR) if f.startswith('bams.db'))
            up_size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(UPLOADS) for f in fs)
            return self.send(200, {'urls': lan_urls(CFG['port']), 'dataDir': DATA_DIR, 'backupDir': BACKUPS.dir,
                                   'extraBackupDirs': BACKUPS.extra, 'dbSize': db_size, 'uploadsSize': up_size,
                                   'backupIntervalHours': CFG['backup_interval_hours'], 'lastBackupError': BACKUPS.last_error,
                                   'counts': STORE.counts(), 'serverTime': now()})
        if p == '/api/backups':
            return self.send(200, BACKUPS.list())
        if p == '/api/trash':
            return self.send(200, STORE.trash())
        if p in ('/api/audit', '/api/activity'):
            return self.send(200, STORE.query_log('audit' if p == '/api/audit' else 'activity', qs.get('q', ''), qs.get('user', ''),
                                                  qs.get('type', ''), qs.get('area', ''), qs.get('from', ''), qs.get('to', ''),
                                                  min(1000, int(qs.get('limit', 200))), int(qs.get('offset', 0))))
        if p == '/api/export.xlsx':
            data = xlsx.build(STORE.export_sheets())
            log.info('EXPORT full workbook by %s (%s)', self.user, self.ip)
            STORE.log_activity(self.user, self.ip, [{'type': 'export', 'action': 'Full Excel export', 'target': 'All data'}])
            return self.send(200, data, TYPES['.xlsx'], {'Content-Disposition': f'attachment; filename="BAMS_Full_Export_{datetime.now():%Y-%m-%d_%H%M}.xlsx"'})
        if p.startswith('/files/'):
            return self.serve_file(UPLOADS, p[len('/files/'):], upload=True)
        if p in STATIC:
            return self.serve_file(ROOT, STATIC[p])
        if p.startswith(STATIC_DIRS):
            return self.serve_file(ROOT, p.lstrip('/'))
        self.send(404, {'error': 'Not found'})

    def _post(self):
        p = urlparse(self.path).path
        qs = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if p == '/api/commit':
            d = self.json_body()
            label = str(d.get('label') or 'Change')[:200]
            if d.get('force') and STORE.counts().get('Break Areas'):
                BACKUPS.create('pre-import')
            res = STORE.commit(self.user, self.ip, label, d.get('ops'), bool(d.get('force')))
            log.info('COMMIT %s (%s) "%s" %s changes', self.user, self.ip, label, res['changes'])
            return self.send(200, res)
        if p == '/api/first-run':
            won = STORE.claim_first_run()
            if won:
                say(f'New database - sample data is being loaded by {self.user} ({self.ip})')
            return self.send(200, {'loadSample': won})
        if p == '/api/upload':
            return self.upload(qs.get('name', 'file'))
        if p == '/api/log':
            d = self.json_body()
            STORE.log_activity(self.user, self.ip, d.get('events') or [])
            return self.send(200, {'ok': True})
        if p == '/api/xlsx':
            d = self.json_body()
            data = xlsx.build([(s.get('name', 'Sheet'), s.get('head', []), s.get('rows', [])) for s in d.get('sheets', [])])
            name = ''.join(ch for ch in str(d.get('filename') or 'export') if ch.isalnum() or ch in ' _-.')[:80]
            return self.send(200, data, TYPES['.xlsx'], {'Content-Disposition': f'attachment; filename="{name}.xlsx"'})
        if p == '/api/backups':
            name = BACKUPS.create('manual')
            log.info('BACKUP manual by %s: %s', self.user, name)
            return self.send(200, {'name': name})
        if p == '/api/backups/restore':
            d = self.json_body()
            safety = BACKUPS.restore(d.get('name'))
            STORE.log_activity(self.user, self.ip, [{'type': 'restore', 'action': 'Restored backup', 'target': d.get('name'),
                                                      'detail': 'Safety backup of the data before restore: ' + safety}])
            say(f'Backup {d.get("name")} restored by {self.user} ({self.ip}); previous data saved as {safety}')
            return self.send(200, {'ok': True, 'safety': safety})
        if p == '/api/trash/restore':
            d = self.json_body()
            return self.send(200, STORE.restore_txn(self.user, self.ip, str(d.get('txn'))))
        self.send(404, {'error': 'Not found'})

    # ------------------------------------------------------------ files
    def upload(self, name):
        ext = os.path.splitext(name)[1].lower()
        if ext not in UPLOAD_EXT:
            raise BadRequest(f'File type {ext or "(none)"} is not allowed')
        data = self.body(int(CFG['max_upload_mb']) * 1048576)
        if not data:
            raise BadRequest('Empty file')
        sub = datetime.now().strftime('%Y-%m')
        os.makedirs(os.path.join(UPLOADS, sub), exist_ok=True)
        fname = uuid.uuid4().hex[:16] + ext
        path = os.path.join(UPLOADS, sub, fname)
        with open(path, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        log.info('UPLOAD %s (%s) %s -> %s/%s %d bytes', self.user, self.ip, name, sub, fname, len(data))
        self.send(200, {'src': f'/files/{sub}/{fname}', 'size': len(data)})

    def serve_file(self, base, rel, upload=False):
        base = os.path.realpath(base)
        path = os.path.realpath(os.path.join(base, unquote(rel)))
        if not path.startswith(base + os.sep) or not os.path.isfile(path):
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
    allow_reuse_address = False  # on Windows reuse would let a second copy share the port silently
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

    print('=' * 64)
    print(' Break Area Management System is running')
    print(f' This PC:        http://localhost:{port}/')
    for u in lan_urls(port):
        print(f' Other PCs:      {u}')
    print(f' Data folder:    {DATA_DIR}')
    print(f' Backups folder: {BACKUPS.dir}')
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
        say('Server stopped')


if __name__ == '__main__':
    main()
