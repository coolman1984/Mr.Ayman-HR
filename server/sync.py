"""PC-to-PC synchronisation: encrypted connections, pairing new PCs, exchanging
missing changes and copying photos/documents.

Transport: HTTPS (TLS 1.2+/1.3) on its own port (config "sync_port", default 8443).
Every PC has a self-signed certificate; the other PCs know its exact SHA-256
fingerprint from the device list (signed by the administrator PC) and hang up before
sending anything when it does not match.

Authentication of a PC to the server side (no clocks needed, replay-proof):
  1. GET  /sync/challenge          -> single-use random challenge (60 s)
  2. POST /sync/session            -> the client signs "BAMS-SESSION1|server|client|challenge"
                                      with its node key; the answer is a session id and key
  3. every further request carries X-BAMS-Session, a strictly increasing X-BAMS-Seq and
     X-BAMS-MAC = HMAC-SHA256(session key, seq|method|path|sha256(body)).

Exchange (both directions from the connecting side, so one open firewall is enough):
  POST /sync/pull {have}   -> the changesets we lack, in the server's journal order
  POST /sync/push {changes}-> the changesets the server lacks
  GET  /sync/file?path=... -> attachment bytes (Range supported, resumable)

Pairing: the administrator PC creates a short-lived one-time code; the new PC sends a
join request proven with the code; the administrator approves it after comparing a
6-digit confirmation number shown on both screens.
"""
import base64
import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import ssl
import threading
import time
import traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import ed25519
from journal import canonical, now
from version import VERSION as APP_VERSION

PROTOCOL = 1
SCHEMA_VERSION = 3
INVITE_MINUTES = 15
OFFLINE_ERRORS = (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, TimeoutError, socket.timeout, OSError)


class SyncError(Exception):
    """A problem with another PC that needs attention (wrong certificate, refused, broken history)."""


class Revoked(SyncError):
    """The other PC says the administrator removed this PC."""


class Offline(Exception):
    """The other PC cannot be reached right now - completely normal when it is switched off."""


def confirm_code(joiner_pub_hex, authority_fp_hex):
    """6 digits both screens show during pairing; they only match without a man-in-the-middle."""
    h = hashlib.sha256(b'BAMS-CONFIRM1' + bytes.fromhex(joiner_pub_hex) + bytes.fromhex(authority_fp_hex)).digest()
    return f'{int.from_bytes(h[:8], "big") % 1000000:06d}'


def encode_code(ip, port, secret, fp):
    """ONE code the person types on the new PC: the administrator PC's address, a one-time secret and the first
    8 bytes of its certificate fingerprint (so the new PC can recognise the real administrator PC). 80-bit secret and
    64-bit fingerprint: neither can be guessed or forged in the 15 minutes the code is valid."""
    raw = socket.inet_aton(ip) + int(port).to_bytes(2, 'big') + secret + bytes.fromhex(fp[:16])
    s = base64.b32encode(raw).decode('ascii').rstrip('=')
    return '-'.join(s[i:i + 4] for i in range(0, len(s), 4))


def decode_code(code):
    """-> (ip, port, secret, fingerprint prefix). Typing mistakes such as 0/O and 1/I are tolerated."""
    s = ''.join(ch for ch in str(code).upper() if ch.isalnum()).replace('0', 'O').replace('1', 'I').replace('8', 'B')
    try:
        raw = base64.b32decode(s + '=' * (-len(s) % 8))
    except ValueError:
        raise ValueError('The code is not valid. Check that it was typed completely.')
    if len(raw) != 24:
        raise ValueError('The code is not valid. Check that it was typed completely.')
    return socket.inet_ntoa(raw[:4]), int.from_bytes(raw[4:6], 'big'), raw[6:16], raw[16:].hex()


def local_ips():
    ips = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith('127.'):
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
    return sorted(ip for ip in ips if not ip.startswith('127.'))


def mac(key, seq, method, path, body):
    msg = f'{seq}|{method}|{path}|{hashlib.sha256(body).hexdigest()}'.encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


# ====================================================================== client connection
class Connection:
    """One authenticated session with another PC."""

    def __init__(self, service, host, port, expect_fp, expect_node=None, timeout=10):
        self.svc, self.host, self.port, self.expect_fp, self.expect_node = service, host, port, expect_fp, expect_node
        self.timeout = timeout
        self.conn = None
        self.session = None
        self.key = None
        self.seq = 0
        self.info = {}
        self.bytes_in = self.bytes_out = 0

    def _connect(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # the certificate is checked below against the pinned fingerprint instead
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        try:
            conn.connect()
        except OFFLINE_ERRORS as e:
            raise Offline(str(e))
        der = conn.sock.getpeercert(binary_form=True)
        fp = hashlib.sha256(der).hexdigest()
        if not fp.startswith(self.expect_fp):
            conn.close()
            raise SyncError(f'The PC at {self.host}:{self.port} is not the expected one (its security certificate is different). '
                            'If it was reinstalled, remove it and add it again.')
        self.peer_fp = fp
        self.conn = conn

    def request(self, method, path, body=None, raw=False, headers=None, sink=None):
        data = b'' if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        h = {'Content-Type': 'application/json', 'Content-Length': str(len(data)), **(headers or {})}
        if self.session:
            self.seq += 1
            h.update({'X-BAMS-Session': self.session, 'X-BAMS-Seq': str(self.seq), 'X-BAMS-MAC': mac(self.key, self.seq, method, path, data)})
        for attempt in (0, 1):
            if self.conn is None:
                self._connect()
            try:
                self.conn.request(method, path, body=data, headers=h)
                resp = self.conn.getresponse()
                if sink is not None and resp.status in (200, 206):
                    return resp, self._stream(resp, sink)
                payload = resp.read()
                break
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError) as e:
                self.close()
                if attempt or self.session:  # never resend an authenticated request (its sequence number is used up)
                    raise Offline(str(e))
            except (http.client.HTTPException, *OFFLINE_ERRORS) as e:  # includes a response cut in the middle
                self.close()
                raise Offline(f'{type(e).__name__}: {e}'[:300])
        self.bytes_out += len(data)
        self.bytes_in += len(payload)
        if resp.status >= 400:
            try:
                err = json.loads(payload)
            except ValueError:
                err = {}
            msg = err.get('error') or resp.reason
            if err.get('revoked'):
                raise Revoked(msg)
            raise SyncError(f'{resp.status}: {msg}')
        if raw:
            return resp, payload
        return json.loads(payload) if payload else {}

    def _stream(self, resp, sink):
        """Writes a download to the open file sink as it arrives, so an interrupted transfer keeps what it got."""
        n = 0
        try:
            while True:
                block = resp.read(65536)
                if not block:
                    break
                sink.write(block)
                n += len(block)
        except (http.client.HTTPException, OSError) as e:
            self.close()
            raise Offline(f'transfer interrupted after {n} bytes: {e}')
        finally:
            sink.flush()
            os.fsync(sink.fileno())
            self.bytes_in += n
        return n

    def login(self):
        me = self.svc.node
        ch = self.request('GET', '/sync/challenge')
        if self.expect_node and ch.get('node') != self.expect_node:
            raise SyncError('The PC at this address is a different device than expected.')
        msg = f'BAMS-SESSION1|{ch["node"]}|{me.id}|{ch["challenge"]}'.encode()
        r = self.request('POST', '/sync/session', {'node': me.id, 'challenge': ch['challenge'], 'sig': me.sign(msg).hex()})
        self.session, self.key, self.info = r['session'], bytes.fromhex(r['key']), r.get('info') or {}
        self.seq = 0
        return self.info

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        self.conn = None


# ====================================================================== server side
class Handler(BaseHTTPRequestHandler):
    server_version = 'BAMS-Sync/1'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype='application/json', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if code >= 400:
            self.send_header('Connection', 'close')
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        svc = self.server.svc
        try:
            raw = self.headers.get('Content-Length') or '0'
            if not raw.isdigit():
                return self._send(400, {'error': 'bad length'})
            n = int(raw)
            path = self.path.split('?')[0]
            open_paths = ('/sync/challenge', '/sync/session', '/sync/join', '/sync/join-status')
            if path in open_paths:
                limit = 64 * 1024  # nothing large before a PC has proven who it is
            elif not svc.session_known(self.headers):
                return self._send(401, {'error': 'not authenticated'})  # the body is not read; the connection is closed
            else:
                limit = 64 * 1048576
            if n > limit:
                return self._send(413, {'error': 'too large'})
            body = self.rfile.read(n) if n else b''
            code, out, ctype, headers = svc.handle(method, self.path, self.headers, body, self.client_address[0])
            self._send(code, out, ctype, headers)
        except (ConnectionError, BrokenPipeError, ssl.SSLError):
            pass
        except Exception as e:
            svc.log('sync server error: ' + traceback.format_exc()[-1500:])
            try:
                self._send(500, {'error': str(e)})
            except OSError:
                pass

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')


class TLSServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != 'nt'  # Windows: reuse would let a second copy share the port silently; elsewhere it only skips TIME_WAIT

    def __init__(self, addr, svc, ctx):
        self.svc = svc
        self.ctx = ctx
        super().__init__(addr, Handler)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(30)
        return self.ctx.wrap_socket(sock, server_side=True), addr

    def handle_error(self, request, client_address):
        pass  # failed TLS handshakes of port scanners etc. are not worth logging


# ====================================================================== the service
class SyncService:
    def __init__(self, system, cfg, uploads, log=print):
        self.sys = system
        self.node = system.node
        self.journal = system.journal
        self.store = system.store
        self.auth = system.auth
        self.uploads = uploads
        self.log = log
        self.port = int(cfg.get('sync_port', 8443))
        self.host = cfg.get('host', '0.0.0.0')
        self.interval = max(1.0, float(cfg.get('sync_interval_seconds', 5)))
        self.overrides = cfg.get('peer_addresses') or {}  # {node_id: "host:port"} from config.json
        self.lock = threading.RLock()
        self.challenges = {}
        self.sessions = {}
        self.workers = {}
        self.status = self.journal.peer_state()
        for st in self.status.values():  # nothing is running yet after a start
            if st.get('state') in ('syncing', 'online'):
                st['state'] = 'unknown'
        self.wake = threading.Condition()
        self.kicked = 0
        self.server = None
        self.stop = False
        self.missing = {}  # attachment path -> {'tries', 'last_error'}
        self.missing_checked = (None, 0)
        self.journal.listeners.append(lambda recs: self.kick())
        self.sync_logger = SyncLog(os.path.join(system.data_dir, 'logs'))

    # ------------------------------------------------------------ lifecycle
    def start(self):
        # sharing is always on: it cannot be switched off on a PC, so nobody can keep their changes away from the others
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.node.tls_cert, self.node.tls_key)
        try:
            self.server = TLSServer((self.host, self.port), self, ctx)
        except OSError as e:
            self.log(f'Sync port {self.port} is not available ({e}) - this PC can still connect to the others.')
            self.server = None
        if self.server:
            threading.Thread(target=self.server.serve_forever, daemon=True, name='sync-server').start()
        threading.Thread(target=self._scheduler, daemon=True, name='sync-scheduler').start()
        threading.Thread(target=self._housekeeping, daemon=True, name='sync-housekeeping').start()

    def shutdown(self):
        self.stop = True
        self.kick()
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def kick(self):
        with self.wake:
            self.kicked += 1
            self.wake.notify_all()

    # ------------------------------------------------------------ peers
    def peers(self):
        """The other active PCs, with the address and certificate fingerprint to use.
        Address: config override > the address the PC last connected to us from (authenticated, so a new IP from
        DHCP is followed automatically) with its known port > the address in the device list / from pairing."""
        out = {}
        if self.node.moved or self.node.role == 'unconfigured':
            return out
        roster = self.journal.roster()
        boot = self.journal.meta('bootstrap_peer') or {}
        for n in roster.values():
            if n['id'] == self.node.id or n.get('status') != 'active' or not n.get('cert_fp'):
                continue
            base = n.get('address') or (boot.get('address') if boot.get('node') == n['id'] else '') or ''
            addr = self.overrides.get(n['id'])
            if not addr and base:
                seen = (self.status.get(n['id']) or {}).get('last_ip')
                host, _, port = base.rpartition(':')
                addr = f'{seen}:{port}' if seen and port.isdigit() else base
            if addr:
                out[n['id']] = {'id': n['id'], 'name': n.get('name') or n['id'], 'address': addr, 'fp': n['cert_fp']}
        if boot and boot.get('node') not in out and boot.get('node') != self.node.id:
            r = roster.get(boot['node'])
            if not r or r.get('status') == 'active':
                out[boot['node']] = {'id': boot['node'], 'name': boot.get('name') or boot['node'],
                                     'address': self.overrides.get(boot['node']) or boot['address'], 'fp': boot['fp']}
        return out

    def _scheduler(self):
        while not self.stop:
            if self.node.role == 'unconfigured' and self.journal.meta('join'):
                try:
                    self.join_progress()
                except Exception as e:
                    self.log('join: ' + str(e))
            for pid, p in self.peers().items():
                w = self.workers.get(pid)
                if w is None or not w.is_alive():
                    w = PeerWorker(self, pid)
                    self.workers[pid] = w
                    w.start()
            with self.wake:
                self.wake.wait(5)

    def peer_status(self, pid):
        with self.lock:
            return self.status.setdefault(pid, {'state': 'unknown', 'fails': 0})

    def save_status(self, pid):
        with self.lock:
            st = dict(self.status.get(pid) or {})
        self.journal.set_peer_state(pid, st)

    # ------------------------------------------------------------ one sync round (client side)
    def sync_with(self, peer):
        """Pull, push and copy files with one PC. Returns a small report."""
        st = self.peer_status(peer['id'])
        host, _, port = peer['address'].rpartition(':')
        if not host:
            host, port = peer['address'], self.port
        started = time.time()
        rep = {'peer': peer['id'], 'name': peer['name'], 'address': peer['address'], 'pulled': 0, 'pushed': 0, 'deferred': 0, 'files': 0}
        c = Connection(self, host, int(port), peer['fp'], peer['id'])
        try:
            with self.lock:
                st['state'] = 'syncing'
            info = c.login()
            rep['session'] = c.session[:8]
            st.update(name_seen=info.get('name'), version=info.get('app'), schema=info.get('schema'), protocol=info.get('protocol'),
                      remote_time=info.get('time'))
            server_vv = {}
            pull_problem = None
            for _ in range(10000):  # pull until nothing is missing
                r = c.request('POST', '/sync/pull', {'have': self.journal.vv()})
                server_vv = {o: v for o, v in (r.get('vv') or {}).items()}
                if r.get('changes'):
                    acc, deferred, problems = self.ingest(r['changes'], peer['id'])
                    rep['pulled'] += len(acc)
                    rep['deferred'] += deferred
                    if problems:
                        pull_problem = 'Changes from this PC were refused: ' + '; '.join(problems[:3])
                        break
                    if not acc and deferred:
                        break  # waiting for something we cannot get from this PC yet
                if not r.get('more'):
                    break
            forks = self.journal.check_heads(server_vv)
            if forks:
                raise SyncError('The history of some PCs differs between this PC and ' + peer['name'] + ': ' + ', '.join(forks))
            for _ in range(10000):  # push what it lacks
                recs, more = self.journal.changes_since({o: v[0] for o, v in server_vv.items()})
                if not recs:
                    break
                r = c.request('POST', '/sync/push', {'changes': recs})
                server_vv = r.get('vv') or server_vv
                rep['pushed'] += r.get('accepted', 0)
                if r.get('problems'):
                    raise SyncError(f'{peer["name"]} refused changes: ' + '; '.join(r['problems'][:3]))
                if not r.get('accepted'):
                    break
            r = c.request('POST', '/sync/pull', {'have': self.journal.vv()})
            server_vv = r.get('vv') or server_vv
            other = {o: v[0] for o, v in server_vv.items()}
            mine = self.journal.vv()
            st['pending_out'] = self.journal.pending_for(other)
            st['pending_in'] = sum(max(0, c_ - mine.get(o, 0)) for o, c_ in other.items())
            st['vv'] = other
            same = st['pending_out'] == 0 and st['pending_in'] == 0
            if same and r.get('fp'):
                st['agree'] = r['fp'] == self.store.fingerprint()
                if not st['agree']:
                    self.journal.alert('divergence', f'This PC and {peer["name"]} have received the same changes but show different data. '
                                       'Please report this to support (see Devices & Sync).', peer['id'], key=f'divergence|{peer["id"]}')
            else:
                st['agree'] = None
            rep['files'] = self.fetch_files(c, peer)
            if pull_problem:
                raise SyncError(pull_problem)  # everything else was still exchanged
            st.update(state='online', last_seen=now(), last_ok=now(), fails=0, last_error='', error_kind='')
            rep['result'] = 'ok'
        except Offline as e:
            st.update(state='offline', fails=st.get('fails', 0) + 1, last_error=str(e)[:300], error_kind='offline')
            rep['result'] = 'offline'
        except Revoked as e:
            self.journal.alert('revoked', 'The administrator removed this PC from the system. It no longer exchanges data with the other PCs.',
                               self.node.id, key='revoked|self')
            st.update(state='error', fails=st.get('fails', 0) + 1, last_error=str(e)[:300], error_kind='revoked')
            rep['result'] = 'revoked'
        except SyncError as e:
            st.update(state='error', last_seen=now() if c.conn else st.get('last_seen'), fails=st.get('fails', 0) + 1,
                      last_error=str(e)[:500], error_kind='error')
            rep['result'] = 'error'
            rep['error'] = str(e)[:500]
        except Exception as e:
            st.update(state='error', fails=st.get('fails', 0) + 1, last_error=f'{type(e).__name__}: {e}'[:500], error_kind='error')
            rep['result'] = 'error'
            rep['error'] = traceback.format_exc()[-800:]
        finally:
            c.close()
        rep['ms'] = int((time.time() - started) * 1000)
        rep['bytes_in'], rep['bytes_out'] = c.bytes_in, c.bytes_out
        st['last_duration_ms'] = rep['ms']
        st['last_try'] = now()
        self.save_status(peer['id'])
        if rep['result'] != 'offline' or st.get('fails') in (1, 10, 100):
            self.sync_logger.write(rep)
        if rep['result'] != 'ok' or rep['pulled'] or rep['pushed'] or rep['files']:
            self.journal.sync_log(peer['id'], rep['result'], rep)
        return rep

    def ingest(self, records, via):
        """Store and fold changesets that arrived from another PC (pull or push)."""
        acc, deferred, problems = self.journal.receive(records, via)
        if acc:
            self.store.fold_pending()
            self.auth.fold_pending()
            self._after_roster_change(acc)
        return acc, deferred, problems

    def _after_roster_change(self, accepted):
        """React when the administrator revoked this PC or when it was enrolled."""
        if any(r['env']['kind'] == 'admin' for r in accepted):
            me = self.journal.roster().get(self.node.id)
            if me and me.get('status') == 'revoked':
                self.journal.alert('revoked', 'The administrator removed this PC from the system. It no longer exchanges data with the other PCs.',
                                   self.node.id, key='revoked|self')

    # ------------------------------------------------------------ attachments (client side)
    def missing_files(self):
        v = self.store.version()
        cached_v, when = self.missing_checked
        if cached_v == v and time.time() - when < 60:
            return [p for p in self.missing]
        found = []
        for p in sorted(self.store.referenced_files()):
            if not os.path.isfile(self.file_path(p)):
                found.append(p)
        with self.lock:
            self.missing = {p: self.missing.get(p, {'tries': 0}) for p in found}
            self.missing_checked = (v, time.time())
        return found

    def file_path(self, src):
        rel = src[len('/files/'):]
        base = os.path.realpath(self.uploads)
        p = os.path.realpath(os.path.join(base, rel))
        if not p.startswith(base + os.sep):
            raise ValueError('bad path')
        return p

    def expected_hash(self, src):
        info = self.store.file_info(src)
        if info:
            return info['sha256'], info['size']
        name = os.path.splitext(os.path.basename(src))[0]
        if src.startswith('/files/cas/') and len(name) == 64:
            return name, None
        return None, None

    def fetch_files(self, c, peer, limit=50):
        done = 0
        for src in self.missing_files()[:limit]:
            sha, size = self.expected_hash(src)
            if not sha:
                continue  # its checksum has not arrived yet
            try:
                if self.fetch_file(c, src, sha, size):
                    done += 1
                    with self.lock:
                        self.missing.pop(src, None)
            except (SyncError, Offline) as e:
                with self.lock:
                    m = self.missing.setdefault(src, {'tries': 0})
                    m['tries'] += 1
                    m['last_error'] = str(e)[:200]
                self.sync_logger.write({'event': 'file', 'path': src, 'result': 'interrupted', 'error': str(e)[:200]})
                if isinstance(e, Offline):
                    break  # the connection is gone; what was received stays in the .part file
        return done

    def fetch_file(self, c, src, sha, size):
        """Downloads one file into uploads/.incoming/<sha>.part (resuming), verifies it and moves it into place."""
        final = self.file_path(src)
        inc = os.path.join(self.uploads, '.incoming')
        os.makedirs(inc, exist_ok=True)
        part = os.path.join(inc, sha + '.part')
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if size is not None and have > size:
            os.remove(part)
            have = 0
        headers = {'Range': f'bytes={have}-'} if have else {}
        with open(part, 'ab') as f:
            try:
                resp, _ = c.request('GET', '/sync/file?path=' + quote(src), raw=True, headers=headers, sink=f)
            except Offline:
                c.close()
                raise
            if resp.status == 204:
                return False  # that PC does not have it either
            if have and resp.status == 200:  # the other PC ignored the range: start again
                f.close()
                with open(part, 'rb') as g:
                    g.seek(have)
                    rest = g.read()
                with open(part, 'wb') as g:
                    g.write(rest)
                    g.flush()
                    os.fsync(g.fileno())
        total = os.path.getsize(part)
        if size is not None and total < size:
            self.sync_logger.write({'event': 'file', 'path': src, 'result': 'interrupted', 'bytes': total, 'size': size})
            return False  # interrupted - continue next time
        h = hashlib.sha256()
        with open(part, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        if h.hexdigest() != sha:
            os.remove(part)
            self.journal.alert('file', f'A copy of {src} received from another PC was damaged and was thrown away. It will be copied again.',
                               '', 'warning', key=f'file|{src}')
            raise SyncError(f'{src}: checksum mismatch')
        os.makedirs(os.path.dirname(final), exist_ok=True)
        os.replace(part, final)
        self.sync_logger.write({'event': 'file', 'path': src, 'bytes': total, 'result': 'ok'})
        return True

    # ------------------------------------------------------------ server side
    def handle(self, method, path, headers, body, ip):
        url = urlparse(path)
        p = url.path
        if self.node.moved:
            return 503, {'error': 'This PC is waiting for a local decision (its data folder seems to come from another PC).'}, 'application/json', {}
        if p == '/sync/challenge' and method == 'GET':
            ch = secrets.token_hex(16)
            with self.lock:
                t = time.time()
                self.challenges = {k: v for k, v in self.challenges.items() if v[0] > t}
                if len(self.challenges) > 1000 or sum(1 for v in self.challenges.values() if v[1] == ip) >= 20:
                    return 429, {'error': 'busy'}, 'application/json', {}
                self.challenges[ch] = (t + 60, ip)
            return 200, {'challenge': ch, 'node': self.node.id}, 'application/json', {}
        if p == '/sync/session' and method == 'POST':
            return self._session(json.loads(body or b'{}'), ip)
        if p == '/sync/join' and method == 'POST':
            return self._join(json.loads(body or b'{}'), ip)
        if p == '/sync/join-status' and method == 'POST':
            return self._join_status(json.loads(body or b'{}'))
        sess = self._auth(method, path, headers, body)
        if sess is None:
            return 401, {'error': 'not authenticated'}, 'application/json', {}
        peer = sess['node']
        with self.lock:
            st = self.status.setdefault(peer, {'state': 'unknown', 'fails': 0})
            st['last_seen'] = now()
            st['last_inbound'] = now()
        if p == '/sync/pull' and method == 'POST':
            d = json.loads(body or b'{}')
            have = {k: int(v) for k, v in (d.get('have') or {}).items()}
            recs, more = self.journal.changes_since(have)
            out = {'changes': recs, 'more': more, 'vv': self.journal.vv_hashes()}
            if not recs:
                out['fp'] = self.store.fingerprint()
            return 200, out, 'application/json', {}
        if p == '/sync/push' and method == 'POST':
            d = json.loads(body or b'{}')
            acc, deferred, problems = self.ingest(d.get('changes') or [], peer)
            if acc:
                self.sync_logger.write({'event': 'push-received', 'peer': peer, 'accepted': len(acc), 'deferred': deferred})
            return 200, {'accepted': len(acc), 'deferred': deferred, 'problems': problems, 'vv': self.journal.vv_hashes()}, 'application/json', {}
        if p == '/sync/file' and method == 'GET':
            src = parse_qs(url.query).get('path', [''])[0]
            if not src.startswith('/files/'):
                return 400, {'error': 'bad path'}, 'application/json', {}
            try:
                fp = self.file_path(src)
            except ValueError:
                return 400, {'error': 'bad path'}, 'application/json', {}
            if not os.path.isfile(fp):
                return 204, b'', 'application/octet-stream', {}
            start = 0
            rng = headers.get('Range') or ''
            if rng.startswith('bytes=') and rng[6:].split('-')[0].isdigit():
                start = int(rng[6:].split('-')[0])
            with open(fp, 'rb') as f:
                f.seek(start)
                data = f.read(32 * 1048576)
            return (206 if start else 200), data, 'application/octet-stream', {}
        return 404, {'error': 'not found'}, 'application/json', {}

    def _session(self, d, ip):
        with self.lock:
            exp = self.challenges.pop(str(d.get('challenge')), None)
        if not exp or exp[0] < time.time():
            return 401, {'error': 'challenge expired or already used'}, 'application/json', {}
        n = self.journal.roster().get(str(d.get('node')))
        if not n or not n.get('pub'):
            expected = {self.node.info.get('authority_node'), (self.journal.meta('bootstrap_peer') or {}).get('node')}
            if str(d.get('node')) not in expected:  # the administrator PC may call before its registration arrived here
                self.journal.alert('unknown-pc', f'An unknown PC at {ip} tried to synchronise.', '', 'warning', key=f'unknown|{ip}')
            return 403, {'error': 'This PC is not registered in this system.'}, 'application/json', {}
        if n.get('status') != 'active':
            self.journal.alert('revoked-pc', f'The removed PC {n.get("name")} ({ip}) tried to synchronise and was refused.', n['id'], 'warning',
                               key=f'revoked-try|{n["id"]}')
            return 403, {'error': 'This PC was removed from the system by the administrator.', 'revoked': True}, 'application/json', {}
        msg = f'BAMS-SESSION1|{self.node.id}|{n["id"]}|{d.get("challenge")}'.encode()
        try:
            ok = ed25519.verify(bytes.fromhex(n['pub']), msg, bytes.fromhex(str(d.get('sig'))))
        except ValueError:
            ok = False
        if not ok:
            self.journal.alert('auth', f'A PC at {ip} pretended to be {n.get("name")}.', n['id'], key=f'auth|{ip}')
            return 403, {'error': 'signature invalid'}, 'application/json', {}
        sid, key = secrets.token_hex(16), secrets.token_bytes(32)
        with self.lock:
            t = time.time()
            self.sessions = {k: v for k, v in self.sessions.items() if v['expires'] > t}
            self.sessions[sid] = {'node': n['id'], 'key': key, 'seq': 0, 'expires': t + 600}
            st = self.status.setdefault(n['id'], {'state': 'unknown', 'fails': 0})
            moved = st.get('last_ip') not in (None, ip)
            st['last_ip'] = ip
        if moved:
            self.save_status(n['id'])
            self.kick()
        info = {'node': self.node.id, 'name': self.node.name, 'app': APP_VERSION, 'schema': SCHEMA_VERSION, 'protocol': PROTOCOL, 'time': now()}
        return 200, {'session': sid, 'key': key.hex(), 'info': info}, 'application/json', {}

    def session_known(self, headers):
        with self.lock:
            s = self.sessions.get(headers.get('X-BAMS-Session') or '')
            return bool(s) and s['expires'] > time.time()

    def _auth(self, method, path, headers, body):
        sid = headers.get('X-BAMS-Session') or ''
        try:
            seq = int(headers.get('X-BAMS-Seq') or 0)
        except ValueError:
            return None
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s['expires'] < time.time():
                return None
            if seq <= s['seq']:
                self.journal.alert('replay', 'A repeated (replayed) sync request was refused.', s['node'], 'warning', key=f'replay|{s["node"]}')
                return None
            if not hmac.compare_digest(mac(s['key'], seq, method, path, body), headers.get('X-BAMS-MAC') or ''):
                return None
            n = self.journal.roster().get(s['node'])
            if not n or n.get('status') != 'active':
                self.sessions.pop(sid, None)
                return None
            s['seq'] = seq
            s['expires'] = time.time() + 600
            return s

    # ------------------------------------------------------------ pairing: administrator PC side
    def create_invite(self, actor):
        if not self.node.is_authority:
            raise PermissionError('Only the administrator PC can add PCs.')
        iid, secret = secrets.token_hex(4), secrets.token_bytes(10)
        exp = (datetime.now() + timedelta(minutes=INVITE_MINUTES)).isoformat(timespec='seconds')
        with self.journal.lock:
            self.journal.conn.execute("DELETE FROM invites WHERE expires_at < ? OR used_at IS NOT NULL", (now(),))
            self.journal.conn.execute('INSERT INTO invites (id, secret_hash, created_at, expires_at, created_by) VALUES (?,?,?,?,?)',
                                      (iid, secret.hex(), now(), exp, actor))
        self.auth.log(actor, '', 'pairing-code', iid, f'Code to add a PC created, valid until {exp}')
        ips = local_ips()
        return {'code': encode_code(ips[0] if ips else '0.0.0.0', self.port, secret, self.node.cert_fp), 'expires': exp,
                'addresses': ips, 'port': self.port}

    def _join(self, d, ip):
        fields = {k: str(d.get(k) or '') for k in ('node', 'name', 'pub', 'cert_fp', 'port')}
        given = str(d.get('mac') or '')
        with self.journal.lock:
            invites = self.journal.conn.execute('SELECT * FROM invites WHERE used_at IS NULL AND expires_at >= ?', (now(),)).fetchall()
        inv = next((i for i in invites if hmac.compare_digest(
            hmac.new(bytes.fromhex(i['secret_hash']), canonical(fields).encode(), hashlib.sha256).hexdigest(), given)), None)
        if not inv:
            self.journal.alert('pairing', f'A PC at {ip} tried to join with a wrong, used or expired code.', '', 'warning', key=f'pairing|{ip}')
            time.sleep(0.5)  # slows down guessing
            return 403, {'error': 'The code is wrong, was already used or has expired. Ask the administrator for a new code.'}, \
                'application/json', {}
        iid = inv['id']
        try:
            ok = len(bytes.fromhex(fields['pub'])) == 32 and len(bytes.fromhex(fields['cert_fp'])) == 32 and len(fields['node']) == 12
        except ValueError:
            ok = False
        if not ok or fields['node'] in self.journal.roster():
            return 400, {'error': 'This PC is already registered or its identity is invalid.'}, 'application/json', {}
        rid = secrets.token_hex(8)
        code = confirm_code(fields['pub'], self.node.cert_fp)
        port = fields['port'] if fields['port'].isdigit() else str(self.port)
        with self.journal.lock:
            self.journal.conn.execute('UPDATE invites SET used_at=? WHERE id=?', (now(), iid))
            self.journal.conn.execute('INSERT INTO join_requests (id, invite_id, node_id, name, pub, cert_fp, address, ip, confirm, status, created_at, secret) '
                                      'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (rid, iid, fields['node'], fields['name'][:60], fields['pub'], fields['cert_fp'],
                                                                             f'{ip}:{port}', ip, code, 'pending', now(), inv['secret_hash']))
        self.auth.log('(new PC)', ip, 'pairing-request', fields['name'], f'PC {fields["name"]} ({ip}) asks to join; confirmation number {code}')
        return 200, {'request': rid, 'confirm': code, 'authority': {'node': self.node.id, 'name': self.node.name}}, 'application/json', {}

    def _join_status(self, d):
        with self.journal.lock:
            r = self.journal.conn.execute('SELECT * FROM join_requests WHERE id=?', (str(d.get('request') or ''),)).fetchone()
        if not r or r['node_id'] != d.get('node'):
            return 404, {'error': 'unknown request'}, 'application/json', {}
        expect = hmac.new(bytes.fromhex(r['secret']), f'{r["id"]}|{r["node_id"]}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, str(d.get('mac') or '')):
            return 403, {'error': 'proof invalid'}, 'application/json', {}
        out = {'status': r['status']}
        if r['status'] == 'approved':
            out.update(cluster=self.node.info['cluster_id'], authority_pub=self.node.info['authority_pub'], authority_node=self.node.id,
                       authority_name=self.node.name, address_seen=r['address'])
        return 200, out, 'application/json', {}

    def join_requests(self):
        with self.journal.lock:
            return [dict(r, secret=None) for r in self.journal.conn.execute(
                "SELECT * FROM join_requests WHERE status='pending' OR created_at > ? ORDER BY created_at DESC",
                ((datetime.now() - timedelta(days=2)).isoformat(timespec='seconds'),))]

    def decide(self, request_id, approve, actor):
        with self.journal.lock:
            r = self.journal.conn.execute('SELECT * FROM join_requests WHERE id=?', (request_id,)).fetchone()
        if not r or r['status'] != 'pending':
            raise ValueError('This request is no longer waiting.')
        if approve:
            ts = now()
            self.auth._write(actor, '', 'Add PC ' + r['name'], [{'e': 'nodes', 'id': r['node_id'], 'op': 'insert', 'noaudit': True,
                                                                  's': {'name': r['name'], 'pub': r['pub'], 'cert_fp': r['cert_fp'], 'address': r['address'],
                                                                        'status': 'active', 'role': 'member', 'enrolled_at': ts,
                                                                        'enrolled_by': actor['display']}}])
        with self.journal.lock:
            self.journal.conn.execute('UPDATE join_requests SET status=?, decided_at=?, decided_by=? WHERE id=?',
                                      ('approved' if approve else 'rejected', now(), actor['display'], request_id))
        self.auth.log(actor['display'], '', 'node-enrolled' if approve else 'pairing-rejected', r['name'],
                      f'PC {r["name"]} ({r["ip"]}, id {r["node_id"]}) ' + ('added to the system' if approve else 'was refused'))
        self.kick()

    def update_node(self, node_id, actor, name=None, address=None, revoke=False):
        n = self.journal.roster().get(node_id)
        if not n:
            raise ValueError('Unknown PC')
        if node_id == self.node.id and revoke:
            raise ValueError('The administrator PC cannot remove itself.')
        s = {}
        if name:
            s['name'] = str(name)[:60]
        if address is not None:
            s['address'] = str(address).strip()[:100]
        if revoke:
            s.update(status='revoked', revoked_at=now(), revoked_by=actor['display'])
        if not s:
            return
        self.auth._write(actor, '', ('Remove PC ' if revoke else 'Change PC ') + (n.get('name') or node_id),
                         [{'e': 'nodes', 'id': node_id, 'op': 'update', 'noaudit': True, 's': s}])
        self.auth.log(actor['display'], '', 'node-revoked' if revoke else 'node-changed', n.get('name') or node_id,
                      'PC removed: it can no longer exchange data' if revoke else json.dumps(s, ensure_ascii=False))
        if revoke:
            with self.lock:
                for sid in [k for k, v in self.sessions.items() if v['node'] == node_id]:
                    self.sessions.pop(sid, None)

    # ------------------------------------------------------------ pairing: new PC side
    def join(self, address, code, device_name):
        """address is optional: normally it is inside the code."""
        if self.node.role != 'unconfigured' or self.auth.has_users():
            raise ValueError('This PC is already set up.')
        host, port, secret, fp_prefix = decode_code(code)
        if address and str(address).strip():
            h, _, p = str(address).strip().rpartition(':')
            host, port = (h, int(p)) if h and p.isdigit() else (str(address).strip(), port)
        if host == '0.0.0.0':
            raise ValueError('The administrator PC has no network address in the code. Type its address below.')
        if device_name:
            self.node.set_name(device_name)
        c = Connection(self, host, int(port), fp_prefix, None, timeout=15)
        try:
            fields = {'node': self.node.id, 'name': self.node.name, 'pub': self.node.pub.hex(), 'cert_fp': self.node.cert_fp, 'port': str(self.port)}
            r = c.request('POST', '/sync/join', {**fields, 'mac': hmac.new(secret, canonical(fields).encode(), hashlib.sha256).hexdigest()})
            fp = c.peer_fp
        except Offline:
            raise ValueError('The administrator PC cannot be reached. Check that it is switched on, that the system runs there, and that '
                             'both PCs are on the company network.')
        except SyncError as e:
            raise ValueError(str(e).split(': ', 1)[-1])
        finally:
            c.close()
        code6 = confirm_code(self.node.pub.hex(), fp)
        pending = {'address': f'{host}:{port}', 'fp': fp, 'request': r['request'], 'secret': secret.hex(), 'confirm': code6,
                   'authority': r.get('authority') or {}, 'since': now()}
        self.journal.set_meta('join', pending)
        return {'confirm': code6, 'authority': pending['authority'], 'status': 'pending'}

    def join_progress(self):
        """Polls the administrator PC; after approval this PC becomes a member and starts the first full sync."""
        j = self.journal.meta('join')
        if not j:
            return {'status': 'none'}
        if self.node.role == 'member' or not j.get('secret'):
            return {'status': 'approved', 'confirm': j['confirm'], 'authority': j['authority'], 'sync': self.summary()}
        host, _, port = j['address'].rpartition(':')
        c = Connection(self, host, int(port), j['fp'], None, timeout=10)
        try:
            r = c.request('POST', '/sync/join-status', {'request': j['request'], 'node': self.node.id,
                                                        'mac': hmac.new(bytes.fromhex(j['secret']), f'{j["request"]}|{self.node.id}'.encode(),
                                                                        hashlib.sha256).hexdigest()})
        except (Offline, SyncError) as e:
            return {'status': 'pending', 'confirm': j['confirm'], 'authority': j['authority'], 'error': str(e)}
        finally:
            c.close()
        if r.get('status') == 'approved':
            self.node.join(r['cluster'], r['authority_pub'], r['authority_node'])
            self.journal.set_meta('join', {**j, 'secret': None})
            self.journal.set_meta('bootstrap_peer', {'node': r['authority_node'], 'name': r.get('authority_name'), 'address': j['address'],
                                                     'fp': j['fp']})
            self.store.mark_initialized()
            self.log(f'This PC joined the system of {r.get("authority_name")} - first synchronisation starts now')
            self.kick()
        elif r.get('status') == 'rejected':
            self.journal.set_meta('join', None)
        return {'status': r.get('status'), 'confirm': j['confirm'], 'authority': j['authority']}

    # ------------------------------------------------------------ summaries for the screens
    def summary(self):
        """Traffic light for every user: single / ok / pending / offline / problem."""
        peers = self.peers()
        roster = [n for n in self.journal.roster().values() if n['id'] != self.node.id and n.get('status') == 'active']
        if self.node.moved:
            return {'state': 'problem', 'text': 'This PC needs a decision by the administrator before it can share data.'}
        if not roster and not peers:
            return {'state': 'single'}
        alerts = [a for a in self.journal.alerts() if a['severity'] == 'error']
        sts = [self.peer_status(p) for p in peers]
        online = [s for s in sts if s.get('state') in ('online', 'syncing')]
        errors = [s for s in sts if s.get('state') == 'error' and s.get('fails', 0) >= 3]
        pending = any((s.get('pending_out') or s.get('pending_in')) for s in online)
        undelivered = not online and self.journal.vv().get(self.node.replica, 0) > max(
            [(s.get('vv') or {}).get(self.node.replica, 0) for s in sts] or [0])
        if alerts or errors:
            state = 'problem'
        elif not online:
            state = 'offline'
        elif pending or any(s.get('state') == 'syncing' for s in sts):
            state = 'pending'
        else:
            state = 'ok'
        files = len(self.missing)
        return {'state': state, 'online': len(online), 'peers': len(peers), 'undelivered': bool(undelivered), 'files_missing': files,
                'problems': len(alerts) + len(errors)}

    def overview(self):
        roster = self.journal.roster()
        peers = self.peers()
        out = []
        for n in sorted(roster.values(), key=lambda x: (x['id'] != self.node.id, (x.get('name') or '').lower())):
            st = dict(self.peer_status(n['id'])) if n['id'] != self.node.id else {}
            st.pop('vv', None)
            out.append({**n, 'self': n['id'] == self.node.id, 'authority': n['id'] == self.node.info.get('authority_node'),
                        'address': (self.overrides.get(n['id']) or n.get('address') or ''), 'status_now': st, 'contacted': n['id'] in peers})
        return {'me': {**self.node.public(), 'fingerprint': self.store.fingerprint(), 'app': APP_VERSION, 'schema': SCHEMA_VERSION,
                       'port': self.port, 'addresses': local_ips(), 'vv': self.journal.vv()},
                'nodes': out, 'summary': self.summary(), 'missing_files': sorted(self.missing)[:200],
                'journal': self.journal.stats(), 'last_verify': self.journal.meta('last_verify'), 'alerts': self.journal.alerts(),
                'requests': self.join_requests() if self.node.is_authority else []}

    def _housekeeping(self):
        last_verify = last_quiet = 0
        while not self.stop:
            time.sleep(10)
            try:
                self.journal.flush_activity()
                if time.time() - last_verify > 6 * 3600:
                    last_verify = time.time()
                    self.journal.verify()
                if self.node.is_authority and time.time() - last_quiet > 3600:
                    last_quiet = time.time()
                    self._quiet_pcs()
            except Exception as e:
                self.log('sync housekeeping: ' + str(e))


    QUIET_DAYS = 3
    _quiet_told = {}

    def _quiet_pcs(self):
        """Administrator PC: a warning (once a day) for every PC that has not exchanged data for several days."""
        limit = datetime.now() - timedelta(days=self.QUIET_DAYS)
        today = datetime.now().strftime('%Y-%m-%d')
        for pid, n in self.journal.roster().items():
            if pid == self.node.id or n.get('status') != 'active':
                continue
            seen = self.peer_status(pid).get('last_seen') or n.get('enrolled_at')
            try:
                quiet = seen and datetime.fromisoformat(seen) < limit
            except ValueError:
                quiet = False
            if quiet and self._quiet_told.get(pid) != today:  # one warning, shown again once a day while it lasts
                self._quiet_told[pid] = today
                self.journal.alert('quiet', f'PC "{n.get("name") or pid}" has not shared its data for more than {self.QUIET_DAYS} days '
                                   f'(last contact {seen.replace("T", " ")}). If it is still used, check that it is switched on and '
                                   'connected to the network. If it is not used any more, remove it in Devices & Sync.',
                                   pid, 'warning', key=f'quiet|{pid}')


class PeerWorker(threading.Thread):
    """Keeps one other PC up to date: every few seconds, immediately after a local change, with back-off
    while it is switched off or failing (5 s doubling up to 1 min when off, 5 min on errors)."""

    def __init__(self, svc, pid):
        super().__init__(daemon=True, name='sync-' + pid)
        self.svc, self.pid = svc, pid

    def run(self):
        svc = self.svc
        last_kick = svc.kicked
        next_try = 0
        while not svc.stop:
            peer = svc.peers().get(self.pid)
            if not peer:
                return
            st = svc.peer_status(self.pid)
            if time.time() >= next_try:
                rep = svc.sync_with(peer)
                fails = st.get('fails', 0)
                if rep['result'] == 'ok':
                    delay = svc.interval
                elif rep['result'] == 'offline':
                    delay = min(60, svc.interval * 2 ** min(fails - 1, 6))
                else:
                    delay = min(300, svc.interval * 2 ** min(fails - 1, 6))
                next_try = time.time() + delay
                st['next_try'] = datetime.fromtimestamp(next_try).isoformat(timespec='seconds')
            with svc.wake:
                if svc.kicked == last_kick:
                    svc.wake.wait(max(0.05, min(5, next_try - time.time())))
                if svc.kicked != last_kick:
                    last_kick = svc.kicked
                    if st.get('state') in ('online', 'syncing', 'unknown'):
                        next_try = min(next_try, time.time() + 0.3)  # something changed: share it now


class SyncLog:
    """data/logs/sync-YYYY-MM.jsonl - one line per sync round / file transfer. Never contains secrets."""

    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.Lock()

    def write(self, entry):
        entry = {'ts': now(), **{k: v for k, v in entry.items() if k not in ('key', 'secret', 'mac')}}
        path = os.path.join(self.folder, f'sync-{datetime.now():%Y-%m}.jsonl')
        with self.lock:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
