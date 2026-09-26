"""Multi-process test harness: real server processes (server/app.py) with their own temporary data
folders and ports, driven through the same HTTP API the browser uses."""
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'server', 'app.py')
sys.path.insert(0, os.path.join(ROOT, 'server'))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_until(cond, timeout=30, step=0.2, what='condition'):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = cond()
            if last:
                return last
        except Exception as e:  # noqa: BLE001 - keep polling
            last = e
        time.sleep(step)
    raise AssertionError(f'timeout waiting for {what}: {last!r}')


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f'{code}: {msg}')
        self.code = code
        self.msg = msg


class Client:
    """One browser: keeps its own session cookie."""

    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, raw=None, headers=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with self.opener.open(req, timeout=60) as r:
                payload = r.read()
                ctype = r.headers.get('Content-Type', '')
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                msg = json.loads(payload).get('error')
            except ValueError:
                msg = payload[:200]
            raise ApiError(e.code, msg)
        return json.loads(payload) if 'json' in ctype else payload

    def get(self, path):
        return self.call('GET', path)

    def post(self, path, body=None):
        return self.call('POST', path, body if body is not None else {})

    def login(self, username, password):
        return self.post('/api/auth/login', {'username': username, 'password': password})


class Server:
    def __init__(self, name, root=None, data_dir=None, extra_cfg=None):
        self.name = name
        self.root = root or tempfile.mkdtemp(prefix=f'bams-{name}-')
        self.port, self.sync_port = free_port(), free_port()
        self.data_dir = data_dir or os.path.join(self.root, 'data')
        self.cfg_path = os.path.join(self.root, 'config.json')
        cfg = {'port': self.port, 'host': '127.0.0.1', 'data_dir': self.data_dir, 'backup_dir': os.path.join(self.root, 'backups'),
               'open_browser': False, 'sync_port': self.sync_port, 'sync_interval_seconds': 1, 'device_name': name,
               'backup_interval_hours': 1000}
        cfg.update(extra_cfg or {})
        with open(self.cfg_path, 'w') as f:
            json.dump(cfg, f)
        self.proc = None
        self.out = []

    @property
    def base(self):
        return f'http://127.0.0.1:{self.port}'

    @property
    def sync_address(self):
        return f'127.0.0.1:{self.sync_port}'

    def set_cfg(self, **kw):
        with open(self.cfg_path) as f:
            cfg = json.load(f)
        cfg.update(kw)
        with open(self.cfg_path, 'w') as f:
            json.dump(cfg, f)

    def start(self, wait=True):
        env = dict(os.environ, BAMS_CONFIG=self.cfg_path, PYTHONUNBUFFERED='1')
        self.proc = subprocess.Popen([sys.executable, APP], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._drain, args=(self.proc,), daemon=True).start()
        if wait:
            wait_until(lambda: self.status(), 60, what=f'{self.name} to start: ' + ''.join(self.out[-20:]))
        return self

    def _drain(self, proc):
        for line in proc.stdout:
            self.out.append(line)

    def status(self):
        try:
            return Client(self.base).get('/api/auth/status')
        except Exception:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(f'{self.name} exited: ' + ''.join(self.out[-40:]))
            return None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def kill(self):
        """Hard crash (like pulling the power cable)."""
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def client(self):
        return Client(self.base)

    def cleanup(self):
        self.kill()
        shutil.rmtree(self.root, ignore_errors=True)


ADMIN = ('boss', 'Strong-pass1')


def make_authority(srv):
    c = srv.client()
    c.post('/api/auth/setup', {'username': ADMIN[0], 'full_name': 'The Admin', 'password': ADMIN[1]})
    return c


def pair(admin_client, authority, member, name=None):
    """Full pairing flow: code on the administrator PC, join on the new PC, approval with confirmation number."""
    inv = admin_client.post('/api/devices/invite')
    mc = member.client()
    j = mc.post('/api/join', {'address': authority.sync_address, 'code': inv['code'], 'name': name or member.name})
    reqs = wait_until(lambda: [r for r in admin_client.get('/api/devices')['requests'] if r['status'] == 'pending'], 10, what='join request')
    assert reqs[0]['confirm'] == j['confirm'], 'confirmation numbers differ'
    admin_client.post('/api/devices/decide', {'id': reqs[0]['id'], 'approve': True})
    wait_until(lambda: mc.get('/api/join/status')['status'] == 'approved', 20, what='approval')
    wait_until(lambda: member.status()['hasUsers'], 30, what='users to arrive on ' + member.name)
    return mc


class TcpProxy:
    """Forwards a port; can cut every connection (network cable pulled) or stop after N bytes (interrupted transfer)."""

    def __init__(self, target_port):
        self.target = target_port
        self.port = free_port()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', self.port))
        self.sock.listen(50)
        self.up = True
        self.cut_after = None  # bytes from the server side before cutting a connection
        self.conns = []
        self.lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def address(self):
        return f'127.0.0.1:{self.port}'

    def _accept(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            if not self.up:
                c.close()
                continue
            try:
                s = socket.create_connection(('127.0.0.1', self.target), timeout=5)
            except OSError:
                c.close()
                continue
            with self.lock:
                self.conns += [c, s]
            threading.Thread(target=self._pipe, args=(c, s, self.cut_after), daemon=True).start()
            threading.Thread(target=self._pipe, args=(s, c, self.cut_after), daemon=True).start()

    def _pipe(self, a, b, limit):
        sent = 0
        try:
            while True:
                data = a.recv(65536)
                if not data or not self.up:
                    break
                if limit is not None and sent + len(data) > limit:
                    b.sendall(data[:max(0, limit - sent)])
                    break
                b.sendall(data)
                sent += len(data)
        except OSError:
            pass
        for x in (a, b):
            try:
                x.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            x.close()

    def cut(self):
        self.up = False
        with self.lock:
            for c in self.conns:
                try:
                    c.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                c.close()
            self.conns = []

    def restore(self):
        self.up = True

    def close(self):
        self.cut()
        self.sock.close()
