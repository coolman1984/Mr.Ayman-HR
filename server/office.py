"""Office mode: this PC uses the system of the administrator PC, exactly like a personal link does.

Why: in some company networks only the web address of the administrator PC can be reached (the personal links work)
while the separate sharing port of the PCs is blocked. A PC in office mode keeps NO data of its own: no database, no
sharing, no keys. The desktop icon opens a tiny page on this PC that sends the browser to the administrator PC; the
person logs in there with their user name and password (and can stay logged in).

  config.json "office_url": "http://ADMIN-PC:8080/"   -> this PC is in office mode (set by the first screen)
  BAMS.exe tool use-this-pc                            -> back to a normal PC (the setting is removed, nothing else)

The tiny page listens on this PC only (127.0.0.1). When the administrator PC cannot be reached it says so in plain
words, with "Try again" and a box to correct the address.
"""
import html
import http.client
import ipaddress
import json
import os
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import appwindow

WEB_PORT = 8080
TITLE = 'Break Area Management System'


def parse_address(text, port=WEB_PORT):
    """'http://host:port/' from what a person types: ADMIN-PC, 192.168.1.10, 192.168.1.10:8080 or a whole web address
    (a personal link works too: only the PC part is used)."""
    a = str(text or '').strip()
    a = a.split('://', 1)[-1].split('/', 1)[0].split('?', 1)[0].strip().rstrip('.')
    host, _, p = a.rpartition(':')
    if not (host and p.isdigit()) or (':' in host and not host.startswith('[')):  # no port, or a bare IPv6 address
        host, p = a, str(port)
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    if not host or any(ch in host for ch in ' \\@?#[]') or not 0 < int(p) < 65536:
        raise ValueError('Type the address of the administrator PC, for example ADMIN-PC or 192.168.1.10.')
    return f'http://{"[" + host + "]" if ":" in host else host}:{int(p)}/'


def is_this_pc(url, port):
    """The address of this PC's own page (it would open itself in a circle)."""
    u = urlparse(url)
    host = (u.hostname or '').lower().rstrip('.')
    if (u.port or 80) != int(port):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_unspecified:
            return True
    except ValueError:
        pass
    me = socket.gethostname().lower()
    try:
        full = socket.getfqdn().lower()
    except OSError:
        full = me
    mine = {'localhost', me, full, me.split('.')[0], *local_ips()}
    if host in mine:
        return True
    try:  # another name or address of this PC (a DNS alias, a second network card)
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0].split('%')[0])
            if ip.is_loopback or ip.is_unspecified or str(ip) in mine:
                return True
    except (OSError, ValueError, UnicodeError):
        pass
    return False


LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')


def local_request(headers, post):
    """Only the browser on this PC, opened at localhost / 127.0.0.1 (against DNS rebinding: a web site whose name was switched to
    127.0.0.1 sends its own name as Host). A POST must also come from such a page (Origin)."""
    def host_of(v):
        return (urlparse('//' + v).hostname or '').lower() if v else ''
    if host_of(headers.get('Host')) not in LOCAL_HOSTS:
        return False
    if post:
        origin = headers.get('Origin')
        return bool(origin) and origin != 'null' and host_of(urlparse(origin).netloc) in LOCAL_HOSTS
    return True


def check(url, timeout=5):
    """Asks the program at this address who it is. -> {'url', 'name', 'role', 'system'}; ValueError in plain words."""
    u = urlparse(url)
    c = HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        c.request('GET', '/api/auth/status', headers={'Accept': 'application/json'})
        r = c.getresponse()
        body = r.read(65536)
        if r.status != 200:
            raise ValueError('Something answers at that address, but it is not the Break Area Management System.')
        d = json.loads(body.decode('utf-8'))
    except (OSError, socket.timeout, http.client.HTTPException):
        raise ValueError('Nothing answers at that address. Check the address, that the administrator PC is switched on with the program '
                         'running, and that both PCs are in the company network.')
    except (ValueError, UnicodeDecodeError, AttributeError):
        raise ValueError('Something answers at that address, but it is not the Break Area Management System.')
    finally:
        c.close()
    if not isinstance(d, dict) or 'hasUsers' not in d:
        raise ValueError('Something answers at that address, but it is not the Break Area Management System.')
    if not d.get('hasUsers'):
        raise ValueError('The program runs on that PC, but it is not set up yet. Type the address of the administrator PC.')
    node, about = d.get('node') or {}, d.get('about') or {}
    return {'url': url, 'name': str(node.get('name') or u.hostname)[:80], 'role': str(node.get('role') or ''), 'id': str(node.get('id') or ''),
            'system': str(about.get('systemName') or '')[:80]}


def local_ips():
    ips = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    try:  # the address used for the default route (works without DNS)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if ip.count('.') == 3 and not ip.startswith(('127.', '169.254.')))


def discover(port=WEB_PORT, hosts=None):
    """Looks for PCs with the system on the web port in this PC's networks (/24). The administrator PC comes first."""
    if hosts is None:
        mine = local_ips()
        hosts = [f'{ip.rsplit(".", 1)[0]}.{i}' for ip in mine for i in range(1, 255)]
        hosts = [h for h in dict.fromkeys(hosts) if h not in mine]
    found = []

    def probe(h):
        try:
            found.append(check(f'http://{h}:{port}/', timeout=1.5))
        except Exception:  # noqa: BLE001 - anything else in the network (printers, cameras) is simply not it
            pass
    with ThreadPoolExecutor(64) as ex:
        list(ex.map(probe, hosts))
    return sorted(found, key=lambda f: (f['role'] != 'authority', f['name'].lower()))


# ------------------------------------------------------------ config.json of this PC
def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _write(path, cfg):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def office_url(path):
    """The address of the administrator PC when this PC is in office mode, else ''."""
    try:
        return str(_read(path).get('office_url') or '')
    except (OSError, ValueError):
        return ''


def set_office_url(path, url):
    """Stores (or with '' removes) the office address. Only this one setting of config.json is touched."""
    try:
        cfg = _read(path)
    except ValueError:
        raise ValueError('The settings file of this PC (config.json) is damaged.')
    if url:
        cfg['office_url'] = url
    else:
        cfg.pop('office_url', None)
    _write(path, cfg)


# ------------------------------------------------------------ the tiny page on this PC
def page(title, body):
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(TITLE)}</title><style>body{{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f3f5f8;'
            'color:#1b2533;display:flex;min-height:90vh;align-items:center;justify-content:center;margin:0 16px}'
            'main{background:#fff;border-radius:12px;padding:28px 32px;max-width:500px;box-shadow:0 4px 18px #0001}'
            'h1{font-size:1.3rem;margin-top:0}a.btn,button{display:inline-block;font-size:1rem;padding:9px 22px;border:0;border-radius:8px;'
            'background:#1f6feb;color:#fff;cursor:pointer;text-decoration:none}input{font-size:1rem;padding:8px;width:100%;box-sizing:border-box;'
            'margin:6px 0 10px;border:1px solid #c8d0da;border-radius:6px}.small{font-size:.88rem;color:#5b6675}.bad{color:#b42318}'
            f'details{{margin-top:18px}}</style></head><body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>')


def make_handler(config_path):
    class Launcher(BaseHTTPRequestHandler):
        server_version = 'BAMS-Office/1.0'

        def log_message(self, fmt, *args):
            pass

        def send(self, code, body=b'', headers=None):
            body = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def problem(self, url, error, typed=''):
            where = html.escape(urlparse(url).netloc) if url else ''
            body = (f'<p class="bad">{html.escape(error)}</p>'
                    + (f'<p>This PC opens the system of the administrator PC <b>{where}</b>. Check that it is switched on and that the program runs '
                       'there, then press <i>Try again</i>.</p><p><a class="btn" href="/">Try again</a></p>' if url else '')
                    + '<details' + ('' if url else ' open') + '><summary>The address of the administrator PC changed?</summary>'
                    '<form method="post" action="/change"><input name="address" required autocomplete="off" '
                    f'value="{html.escape(typed or where)}" placeholder="e.g. ADMIN-PC or 192.168.1.10">'
                    '<button>Save and open</button></form><p class="small">The administrator sees the address in '
                    '<b>Devices &amp; Sync</b> or <b>Settings → Server &amp; Database</b>.</p></details>')
            return self.send(200, page('The system cannot be opened right now', body))

        def do_GET(self):
            if not local_request(self.headers, False):
                return self.send(403, page('Not allowed', '<p>Open this page on this PC at http://localhost.</p>'))
            if urlparse(self.path).path != '/':
                return self.send(404, page('Not found', '<p><a href="/">Open the system</a></p>'))
            url = office_url(config_path)
            if not url:
                return self.problem('', 'This PC does not know the address of the administrator PC yet.')
            try:
                check(url, timeout=6)
            except ValueError as e:
                return self.problem(url, str(e))
            return self.send(302, b'', {'Location': url})

        def do_POST(self):
            if not local_request(self.headers, True) or urlparse(self.path).path != '/change':
                return self.send(403, page('Not allowed', '<p>This request was blocked.</p>'))
            n = int(self.headers.get('Content-Length') or 0)
            if n > 4096:
                return self.send(400, page('Not allowed', '<p>Request too large.</p>'))
            typed = (parse_qs(self.rfile.read(n).decode('utf-8', 'replace')).get('address') or [''])[0][:200]
            try:
                url = parse_address(typed)
                if is_this_pc(url, self.server.server_address[1]):
                    raise ValueError('That is the address of this PC. Type the address of the administrator PC.')
                check(url, timeout=6)
            except ValueError as e:
                return self.problem(office_url(config_path), str(e), typed)
            set_office_url(config_path, url)
            return self.send(303, b'', {'Location': url})
    return Launcher


class Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != 'nt'
    daemon_threads = True


def serve(config_path, port=WEB_PORT, open_browser=True, app_window=True):
    """Runs the tiny page on this PC (until the program is ended). A second start only opens the browser."""
    try:
        httpd = Server(('127.0.0.1', port), make_handler(config_path))
    except OSError:  # already running (or the port is still taken)
        if open_browser:
            appwindow.open_window(f'http://localhost:{port}/', app_window)
        return False
    print(f'Office mode: this PC opens {office_url(config_path)} (page on http://localhost:{port}/)', flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: appwindow.open_window(f'http://localhost:{port}/', app_window)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None):
    """python server/office.py [--background] - the office mode page (also started by BAMS.exe in office mode)."""
    argv = sys.argv[1:] if argv is None else argv
    home = os.environ.get('BAMS_HOME') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.environ.get('BAMS_CONFIG') or os.path.join(home, 'config.json')
    if '--background' in argv:
        return 0  # nothing to share in office mode: no need to run when Windows starts
    try:
        port = int(_read(path).get('port', WEB_PORT))
    except (OSError, ValueError):
        port = WEB_PORT
    try:
        app_window = appwindow.enabled(_read(path).get('app_window', True))
    except (OSError, ValueError):
        app_window = True
    serve(path, port, open_browser='--no-browser' not in argv, app_window=app_window)
    return 0


if __name__ == '__main__':
    sys.exit(main())
