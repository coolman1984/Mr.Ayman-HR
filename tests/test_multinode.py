"""End-to-end scenarios with real server processes (see TASKS.md for the numbered list).
Each PC is a separate process with its own data folder and ports; some connections go through a
TCP proxy that the test can cut to simulate network failures."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

from harness import ADMIN, APP, ApiError, Server, TcpProxy, make_authority, pair, wait_until


def area_op(aid, name, **kw):
    return {'e': 'areas', 'id': aid, 'op': 'put', 'row': {'name': name, 'status': 'Good', 'location': 'Production', **kw}}


def get_area(c, aid):
    return next((a for a in c.get('/api/state')['areas'] if a['id'] == aid), None)


def edit(c, aid, **fields):
    a = get_area(c, aid)
    row = {k: v for k, v in a.items() if not isinstance(v, list) and k != 'ver'}
    row.update(fields)
    return c.post('/api/commit', {'label': 'edit', 'ops': [{'e': 'areas', 'id': aid, 'op': 'put', 'ver': a['ver'], 'row': row}]})


def move(c, aid, item, delta):
    a = get_area(c, aid)
    e = next((x for x in a['inventory'] if x['item'] == item), None)
    prev = (e or {}).get('qty', 0)
    row = {**({k: v for k, v in e.items() if k != 'ver'} if e else {}), 'areaId': aid, 'item': item, 'qty': prev + delta}
    hid = 'h' + os.urandom(4).hex()
    return c.post('/api/commit', {'label': f'move {delta}', 'ops': [
        {'e': 'inventory', 'id': f'{aid}:{item}', 'op': 'put', 'ver': e['ver'] if e else None, 'row': row},
        {'e': 'history', 'id': hid, 'op': 'put', 'row': {'areaId': aid, 'item': item, 'action': 'Added' if delta > 0 else 'Removed',
                                                          'prev': prev, 'next': prev + delta, 'date': '2026-09-26'}}]})


def fingerprint(c):
    return c.get('/api/devices')['me']['fingerprint']


class Base(unittest.TestCase):
    """Three PCs: admin (authority), pc1, pc2 - each reachable only through its own proxy."""
    N = 3

    @classmethod
    def setUpClass(cls):
        cls.servers = [Server(n).start() for n in ['admin', 'pc1', 'pc2', 'pc3'][:cls.N]]
        cls.proxies = [TcpProxy(s.sync_port) for s in cls.servers]
        # every PC reaches every other PC only through that PC's proxy (so a PC can be "unplugged")
        cls.A = cls.servers[0]
        cls.ac = make_authority(cls.A)
        cls.clients = [cls.ac]
        for s in cls.servers[1:]:
            pair(cls.ac, cls.A, s)
        roster = cls.ac.get('/api/devices')['nodes']
        ids = {n['name']: n['id'] for n in roster}
        for i, s in enumerate(cls.servers):
            s.node_id = ids[s.name]
        overrides = {s.node_id: cls.proxies[i].address for i, s in enumerate(cls.servers)}
        for s in cls.servers:
            s.stop()
            s.set_cfg(peer_addresses=overrides)
            s.start()
        cls.clients = []
        for s in cls.servers:
            c = s.client()
            c.login(*ADMIN)
            cls.clients.append(c)
        cls.ac = cls.clients[0]
        cls.converged()

    @classmethod
    def tearDownClass(cls):
        for p in cls.proxies:
            p.close()
        for s in cls.servers:
            s.cleanup()

    @classmethod
    def relogin(cls, i):
        c = cls.servers[i].client()
        c.login(*ADMIN)
        cls.clients[i] = c
        return c

    @classmethod
    def converged(cls, idx=None, timeout=60):
        idx = idx if idx is not None else range(len(cls.servers))

        def same():
            fps = [fingerprint(cls.clients[i]) for i in idx]
            vvs = [json.dumps(cls.clients[i].get('/api/devices')['me']['vv'], sort_keys=True) for i in idx]
            return len(set(fps)) == 1 and len(set(vvs)) == 1 and fps[0]
        return wait_until(same, timeout, 0.5, what='convergence')

    def unplug(self, i):
        self.proxies[i].cut()

    def plug(self, i):
        self.proxies[i].restore()


class T00_DefinitionOfSuccess(Base):
    """The acceptance scenario: three PCs, the administrator PC switched off, two users keep working (with photos),
    one user PC switched off, the administrator PC returns, then the last PC returns - everything converges."""
    N = 3

    def test_acceptance_story(self):
        A, U1, U2 = self.servers
        ac = self.ac
        # users with limited rights, created on the administrator PC
        for name, pw in (('ali', 'Tree-green42'), ('mona', 'Sky-blue7700')):
            ac.post('/api/users/save', {'username': name, 'full_name': name.title(), 'password': pw, 'must_change': False, 'role': 'Data Entry',
                                        'perms': ['dashboard.view', 'areas.view', 'areas.create', 'areas.edit', 'inventory.edit', 'files.upload',
                                                  'files.download', 'issues.create'], 'areas': None})
        ac.post('/api/commit', {'label': 'start', 'ops': [area_op('S1', 'Main canteen', capacity=40)]})
        move(ac, 'S1', 'chairs', 30)
        self.converged()
        # 1. administrator PC switched off
        A.stop()
        ali, mona = U1.client(), U2.client()
        ali.login('ali', 'Tree-green42')
        mona.login('mona', 'Sky-blue7700')
        # 2. both keep working, including attachments
        img = os.urandom(200_000)
        up = ali.call('POST', '/api/upload?name=canteen.jpg', raw=img, headers={'Content-Type': 'application/octet-stream'})
        ali.post('/api/commit', {'label': 'photo', 'ops': [{'e': 'photos', 'id': 'sp1', 'op': 'put', 'row': {'areaId': 'S1', 'src': up['src'], 'caption': 'New'}}]})
        move(ali, 'S1', 'chairs', -4)
        edit(ali, 'S1', description='painted')
        mona.post('/api/commit', {'label': 'new area', 'ops': [area_op('S2', 'Warehouse corner')]})
        move(mona, 'S1', 'chairs', 6)
        edit(mona, 'S1', capacity=44)
        wait_until(lambda: get_area(mona, 'S1')['description'] == 'painted' and get_area(ali, 'S2'), 30, what='user PCs share without admin')
        # the audit trail is recorded locally with user and PC
        self.assertTrue(any(r['user'].startswith('Ali') for r in self.clients[1].get('/api/audit?limit=50')['rows']))
        # 3. one user PC switched off; work continues on the other one
        U2.stop()
        edit(ali, 'S2', responsible='Ali')
        # 4. administrator PC starts again and syncs with the remaining user PC
        A.start()
        admin = self.relogin(0)
        wait_until(lambda: (get_area(admin, 'S2') or {}).get('responsible') == 'Ali', 60, what='admin catches up with pc1')
        # 5. the last PC returns
        U2.start()
        self.relogin(2)
        self.relogin(1)
        self.converged()
        # ---- after convergence
        for c in self.clients:
            s1 = get_area(c, 'S1')
            self.assertEqual(next(i['qty'] for i in s1['inventory'] if i['item'] == 'chairs'), 32)  # 30 - 4 + 6: nothing lost
            self.assertEqual((s1['description'], s1['capacity']), ('painted', 44))
            self.assertEqual(get_area(c, 'S2')['responsible'], 'Ali')
            self.assertEqual(s1['photos'][0]['src'], up['src'])
        for s in self.servers:  # the photo reached every PC and matches
            wait_until(lambda: os.path.exists(os.path.join(s.data_dir, 'uploads', 'cas', os.path.basename(up['src']))), 60, what='photo copied')
            self.assertEqual(open(os.path.join(s.data_dir, 'uploads', 'cas', os.path.basename(up['src'])), 'rb').read(), img)
        perms = [json.dumps(sorted((u['username'], u['perms'], u['active']) for u in c.get('/api/users')['users']), sort_keys=True) for c in self.clients]
        self.assertEqual(len(set(perms)), 1, 'user permissions agree')
        nodes = {r['node_name'] for r in self.clients[0].get('/api/audit?limit=1000')['rows']}
        self.assertEqual(nodes, {'admin', 'pc1', 'pc2'}, 'history from every PC is visible to the administrator')
        logins = {r['node_name'] for r in self.clients[0].get('/api/security?type=login&limit=1000')['rows']}
        self.assertTrue({'pc1', 'pc2'} <= logins)
        for c in self.clients:
            self.assertTrue(c.post('/api/devices/verify', {'all': True})['ok'], 'log chains verify')
        m2 = self.servers[2].client()
        m2.login('mona', 'Sky-blue7700')
        for path in ('/api/devices', '/api/security', '/api/activity', '/api/conflicts'):
            with self.assertRaises(ApiError) as e:
                m2.get(path)
            self.assertEqual(e.exception.code, 403)


class T01_SingleNode(unittest.TestCase):
    def test_fresh_single_pc(self):
        """1. A fresh installation works alone exactly like before (no devices, indicator hidden)."""
        s = Server('solo').start()
        try:
            st = s.status()
            self.assertFalse(st['hasUsers'])
            self.assertEqual(st['node']['role'], 'unconfigured')
            c = make_authority(s)
            self.assertEqual(c.get('/api/me')['node']['role'], 'authority')
            c.post('/api/commit', {'label': 'x', 'ops': [area_op('a1', 'Area 1')]})
            self.assertEqual(get_area(c, 'a1')['name'], 'Area 1')
            self.assertEqual(c.get('/api/version')['sync']['state'], 'single')
            b = c.post('/api/backups')
            self.assertTrue(b['name'].endswith('_manual.db'))
            self.assertTrue(os.path.exists(os.path.join(s.root, 'backups', 'db', 'journal' + b['name'][4:])))
        finally:
            s.cleanup()


class T02_Upgrade(unittest.TestCase):
    def test_upgrade_v1_installation(self):
        """2. An existing version-1 folder is upgraded in place: data, users, logs, uploads kept; verified backup first."""
        from make_legacy import build
        s = Server('upgraded')
        counts = build(s.data_dir)
        with sqlite3.connect(os.path.join(s.data_dir, 'bams.db')) as db:
            before = db.execute('SELECT id, name, status FROM areas ORDER BY id').fetchall()
        s.start()
        try:
            c = s.client()
            c.login('ayman', 'Secret-pass1')
            st = c.get('/api/state')
            self.assertEqual([(a['id'], a['name'], a['status']) for a in sorted(st['areas'], key=lambda a: a['id'])],
                             [b for b in before if b[0] != 'ba05'])
            self.assertEqual(len(st['areas']), counts['Break Areas'])
            inv = {i['id']: i['qty'] for a in st['areas'] for i in a['inventory']}
            self.assertEqual(inv['ba03:chairs'], 30)
            self.assertEqual(c.get('/api/me')['node']['role'], 'authority')
            users = {u['username'] for u in c.get('/api/users')['users']}
            self.assertEqual(users, {'ayman', 'sara'})
            sec = c.get('/api/security?limit=500')
            self.assertTrue(any(r['event'] == 'login-failed' for r in sec['rows']))
            audit = c.get('/api/audit?limit=500')
            self.assertTrue(any(r['label'] == 'Delete break area 05' for r in audit['rows']))
            self.assertTrue(any(b['name'].endswith('pre-upgrade.db') for b in c.get('/api/backups')))
            trash = c.get('/api/trash')
            self.assertEqual(trash[0]['label'], 'Delete break area 05')
            photo = c.call('GET', '/files/2026-09/abc123.jpg')
            self.assertTrue(photo.startswith(b'\xff\xd8'))
            rep = c.post('/api/devices/verify', {'all': True})
            self.assertTrue(rep['ok'], rep)
            # second start: nothing is upgraded twice
            fp = fingerprint(c)
            s.stop()
            s.start()
            c = s.client()
            c.login('sara', 'Other-pass2')
            self.assertEqual(len(c.get('/api/state')['areas']), counts['Break Areas'])
            c2 = s.client()
            c2.login('ayman', 'Secret-pass1')
            self.assertEqual(fingerprint(c2), fp)
        finally:
            s.cleanup()


class T03_Cluster(Base):
    """3-10, 24-28: users, enrolment, initial and live sync, administrator PC away and back, security."""

    def test_a_users_and_initial_sync(self):
        ac = self.ac
        ac.post('/api/users/save', {'username': 'sara', 'full_name': 'Sara M', 'password': 'Temp-pass99', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'areas.edit', 'inventory.edit'], 'areas': None, 'role': 'Custom'})
        ac.post('/api/commit', {'label': 'data', 'ops': [area_op('A1', 'Area One'), area_op('A2', 'Area Two')]})
        self.converged()
        for i in (1, 2):
            c = self.servers[i].client()
            c.login('sara', 'Temp-pass99')  # the account works on every PC
            self.assertEqual({a['id'] for a in c.get('/api/state')['areas']}, {'A1', 'A2'})

    def test_b_realtime(self):
        """6. A change on one PC appears on the others within seconds."""
        t = time.time()
        self.clients[1].post('/api/commit', {'label': 'rt', 'ops': [area_op('RT', 'Realtime')]})
        wait_until(lambda: get_area(self.clients[2], 'RT'), 15, 0.1, what='realtime')
        self.assertLess(time.time() - t, 10)

    def test_c_admin_away_and_back(self):
        """7-10. Administrator PC switched off, the others keep working and syncing, it catches up when back."""
        self.servers[0].stop()
        self.clients[1].post('/api/commit', {'label': 'while admin off', 'ops': [area_op('OFF1', 'Made while admin off')]})
        wait_until(lambda: get_area(self.clients[2], 'OFF1'), 20, what='pc1 -> pc2 without admin')
        edit(self.clients[2], 'OFF1', description='pc2 edit')
        self.assertEqual(self.clients[2].get('/api/version')['sync']['state'] in ('ok', 'pending', 'problem'), True)
        self.servers[0].start()
        self.relogin(0)
        self.converged()
        self.assertEqual(get_area(self.clients[0], 'OFF1')['description'], 'pc2 edit')

    def test_d_user_disabled_while_pc_offline(self):
        """24-25. Disable a user and change permissions while pc2 is unplugged; pc2 applies both when it reconnects."""
        ac = self.ac
        u = next(x for x in ac.get('/api/users')['users'] if x['username'] == 'sara')
        c2 = self.servers[2].client()
        c2.login('sara', 'Temp-pass99')
        self.unplug(2)
        body = {**u, 'perms': ['dashboard.view', 'areas.view'], 'active': False}
        ac.post('/api/users/save', body)
        # pc2 does not know yet: sara is still logged in there (documented offline window)
        self.assertTrue(c2.get('/api/me'))
        self.plug(2)
        wait_until(lambda: self._logged_out(c2), 30, what='session ended on pc2')
        with self.assertRaises(ApiError):
            self.servers[2].client().login('sara', 'Temp-pass99')
        self.converged()
        pc1_users = {x['username']: x for x in self.clients[1].get('/api/users')['users']}
        self.assertEqual(pc1_users['sara']['perms'], ['areas.view', 'dashboard.view'])
        self.assertFalse(pc1_users['sara']['active'])

    @staticmethod
    def _logged_out(c):
        try:
            c.get('/api/me')
            return False
        except ApiError as e:
            return e.code == 401

    def test_e_member_cannot_do_admin_actions(self):
        """26. Account changes on a PC that is not the administrator PC are refused (403), monitoring needs an administrator."""
        with self.assertRaises(ApiError) as e:
            self.clients[1].post('/api/users/save', {'username': 'evil', 'full_name': 'Evil', 'password': 'Evil-pass12', 'perms': ['users.manage']})
        self.assertEqual(e.exception.code, 403)
        ac = self.ac
        ac.post('/api/users/save', {'username': 'viewer', 'full_name': 'View Er', 'password': 'Look-only77', 'must_change': False,
                                    'perms': ['dashboard.view', 'logs.view', 'logs.activity', 'logs.security'], 'areas': None})
        self.converged()
        v = self.servers[1].client()
        v.login('viewer', 'Look-only77')
        for path in ('/api/devices', '/api/conflicts', '/api/security', '/api/activity', '/api/users', '/api/devices/log'):
            with self.assertRaises(ApiError) as e:
                v.get(path)
            self.assertEqual(e.exception.code, 403, path)
        for path in ('/api/devices/invite', '/api/devices/revoke', '/api/conflicts/resolve', '/api/devices/verify'):
            with self.assertRaises(ApiError) as e:
                v.post(path, {'id': self.servers[2].node_id})
            self.assertEqual(e.exception.code, 403, path)
        rows = v.get('/api/audit?limit=1000')['rows']  # the data-changes log stays available with logs.view ...
        self.assertFalse([r for r in rows if r['entity'] in ('users', 'nodes')], '... but without user accounts')
        self.assertTrue([r for r in self.ac.get('/api/audit?limit=1000')['rows'] if r['entity'] == 'users'])

    def test_f_unknown_pc_and_replay(self):
        """27-28. A PC that is not enrolled cannot open a session; a replayed authenticated request is refused."""
        import sync as syncmod
        from node import Node
        import tempfile
        d = tempfile.mkdtemp()
        stranger = Node(d).create('stranger')

        class Svc:
            node = stranger
        conn = syncmod.Connection(Svc(), '127.0.0.1', self.A.sync_port, '')
        with self.assertRaises(syncmod.SyncError) as e:
            conn.login()
        self.assertIn('403', str(e.exception))
        # a real member session: capture one request and send it again
        svc = Svc()
        import node as nodemod
        svc.node = nodemod.Node(self.servers[1].data_dir)
        conn = syncmod.Connection(svc, '127.0.0.1', self.A.sync_port, '')
        conn.login()
        body = json.dumps({'have': {}}).encode()
        conn.seq += 1
        h = {'X-BAMS-Session': conn.session, 'X-BAMS-Seq': str(conn.seq), 'X-BAMS-MAC': syncmod.mac(conn.key, conn.seq, 'POST', '/sync/pull', body),
             'Content-Type': 'application/json'}
        conn.conn.request('POST', '/sync/pull', body=body, headers=h)
        self.assertEqual(conn.conn.getresponse().status, 200)
        conn.conn.close()
        conn.conn = None
        conn._connect()
        conn.conn.request('POST', '/sync/pull', body=body, headers=h)  # exact replay
        r = conn.conn.getresponse()
        r.read()
        self.assertEqual(r.status, 401)
        # a forged MAC is refused too
        conn.close()
        conn._connect()
        h2 = dict(h, **{'X-BAMS-Seq': str(conn.seq + 5)})
        conn.conn.request('POST', '/sync/pull', body=body, headers=h2)
        self.assertEqual(conn.conn.getresponse().status, 401)
        # wrong certificate fingerprint: refused before sending
        bad = syncmod.Connection(svc, '127.0.0.1', self.A.sync_port, 'ab' * 32)
        with self.assertRaises(syncmod.SyncError):
            bad.login()

    def test_f2_bad_requests_to_the_sync_port(self):
        """Oversized or malformed requests from strangers are refused before anything is read into memory."""
        import socket
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE

        def status(req):
            s = ctx.wrap_socket(socket.create_connection(('127.0.0.1', self.A.sync_port), timeout=10))
            s.sendall(req)
            line = s.recv(100).split(b'\r\n')[0]
            s.close()
            return int(line.split()[1])
        self.assertEqual(status(b'POST /sync/join HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n'), 400)
        self.assertEqual(status(b'POST /sync/join HTTP/1.1\r\nHost: x\r\nContent-Length: 300000000\r\n\r\n'), 413)
        self.assertEqual(status(b'POST /sync/push HTTP/1.1\r\nHost: x\r\nContent-Length: 50000000\r\n\r\n'), 401)

    def test_f3_own_password_change_on_any_pc(self):
        """A user changes their own password on pc1; it works on every PC (proven with the old password's key)."""
        c1 = self.servers[1].client()
        c1.login('viewer', 'Look-only77')
        c1.post('/api/auth/password', {'old': 'Look-only77', 'new': 'Fresh-start88'})
        self.converged()
        c2 = self.servers[2].client()
        c2.login('viewer', 'Fresh-start88')
        with self.assertRaises(ApiError):
            self.servers[0].client().login('viewer', 'Look-only77')
        rows = self.ac.get('/api/security?type=change-rejected&limit=50')['rows']
        self.assertEqual(rows, [], 'the change was accepted everywhere')

    def test_g_revoke(self):
        """Removing a PC: it cannot sync any more; its earlier work stays."""
        ac = self.ac
        self.clients[2].post('/api/commit', {'label': 'before revoke', 'ops': [area_op('RV', 'Before revoke')]})
        self.converged()
        ac.post('/api/devices/revoke', {'id': self.servers[2].node_id})
        wait_until(lambda: any(a['kind'] == 'revoked' for a in self.clients[2].get('/api/devices')['alerts']), 30, what='revocation seen')
        # every other PC must know the removal first: a PC that does not know it yet still passes on what the removed PC made
        # without knowing it was removed (by design - offline-first); CI once ran pc2's change through pc1 that way
        wait_until(lambda: {n['name']: n['status'] for n in self.clients[1].get('/api/devices')['nodes']}.get('pc2') == 'revoked', 30,
                   what='removal known on pc1')
        self.clients[2].post('/api/commit', {'label': 'after revoke', 'ops': [area_op('RV2', 'After revoke')]})
        time.sleep(4)
        self.assertIsNone(get_area(self.ac, 'RV2'))
        self.assertIsNotNone(get_area(self.ac, 'RV'))
        st = {n['name']: n['status'] for n in self.ac.get('/api/devices')['nodes']}
        self.assertEqual(st['pc2'], 'revoked')


class T11_Conflicts(Base):
    """11-18, 31: two/three PCs offline at the same time."""
    N = 3

    def isolate(self):
        for i in range(self.N):
            self.unplug(i)

    def heal(self):
        for i in range(self.N):
            self.plug(i)
        self.converged()

    def test_concurrent_everything(self):
        ac = self.ac
        ac.post('/api/commit', {'label': 'base', 'ops': [area_op('C1', 'Conflict area', capacity=10, description='orig'),
                                                        area_op('C2', 'To delete')]})
        move(ac, 'C1', 'chairs', 20)
        self.converged()
        self.isolate()
        c0, c1, c2 = self.clients
        # 11 independent inserts
        c1.post('/api/commit', {'label': 'ins', 'ops': [area_op('N1', 'New on pc1')]})
        c2.post('/api/commit', {'label': 'ins', 'ops': [area_op('N2', 'New on pc2')]})
        # 12 different fields, 13 same field
        edit(c1, 'C1', capacity=11, description='pc1 text')
        edit(c2, 'C1', responsible='pc2 person', description='pc2 text')
        # 14 concurrent inventory movements on all three PCs
        move(c0, 'C1', 'chairs', +5)
        move(c1, 'C1', 'chairs', -3)
        move(c2, 'C1', 'chairs', +10)
        # 15 delete while another PC edits
        a = get_area(c0, 'C2')
        c0.post('/api/commit', {'label': 'del', 'ops': [{'e': 'areas', 'id': 'C2', 'op': 'del', 'ver': a['ver']}]})
        edit(c1, 'C2', description='edited while deleted elsewhere')
        self.heal()
        for c in self.clients:
            a = get_area(c, 'C1')
            self.assertEqual(a['capacity'], 11)
            self.assertEqual(a['responsible'], 'pc2 person')
            self.assertIn(a['description'], ('pc1 text', 'pc2 text'))
            self.assertEqual(next(i for i in a['inventory'] if i['item'] == 'chairs')['qty'], 32)
            self.assertIsNotNone(get_area(c, 'N1'))
            self.assertIsNotNone(get_area(c, 'N2'))
            self.assertIsNone(get_area(c, 'C2'), '16: the delete must win and not come back')
        conf = self.ac.get('/api/conflicts')
        kinds = {(x['id'], x['kind']) for x in conf}
        self.assertIn(('C1', 'conflict'), kinds)
        self.assertIn(('C2', 'deleted-edit'), kinds)
        # every PC shows the same conflict list
        lists = [sorted((x['id'], x['kind']) for x in c.get('/api/conflicts')) for c in self.clients]
        self.assertEqual(lists[0], lists[1])
        self.assertEqual(lists[0], lists[2])
        # the administrator resolves the text conflict; it disappears everywhere
        self.ac.post('/api/conflicts/resolve', {'entity': 'areas', 'id': 'C1', 'action': 'value', 'field': 'description', 'value': 'agreed text'})
        self.converged()
        for c in self.clients:
            self.assertEqual(get_area(c, 'C1')['description'], 'agreed text')
            self.assertNotIn(('C1', 'conflict'), {(x['id'], x['kind']) for x in c.get('/api/conflicts')})
        # the Recycle Bin still has the deleted area with the edit made on pc1
        self.ac.post('/api/conflicts/resolve', {'entity': 'areas', 'id': 'C2', 'action': 'restore'})
        self.converged()
        self.assertEqual(get_area(self.clients[2], 'C2')['description'], 'edited while deleted elsewhere')

    def test_repeated_disconnects(self):
        """32. Many cut/restore cycles during constant changes on all PCs - still one result."""
        import random
        rnd = random.Random(5)
        self.ac.post('/api/commit', {'label': 'base', 'ops': [area_op('RC', 'Reconnect')]})
        self.converged()
        for rnd_i in range(12):
            for i in range(self.N):
                if rnd.random() < 0.5:
                    self.unplug(i)
                else:
                    self.plug(i)
            c = self.clients[rnd.randrange(self.N)]
            try:
                move(c, 'RC', 'tables', rnd.randint(1, 4))
            except ApiError:
                pass
            time.sleep(rnd.random() * 0.8)
        self.heal()
        qtys = {next((i['qty'] for i in get_area(c, 'RC')['inventory'] if i['item'] == 'tables'), 0) for c in self.clients}
        self.assertEqual(len(qtys), 1)
        rows = [r for r in self.ac.get('/api/audit?area=RC&limit=1000')['rows'] if r['entity_id'] == 'RC:tables']
        moves = sum(json.loads(r['changes'])['qty'][1] - json.loads(r['changes'])['qty'][0] for r in rows if r['op'] == 'update')
        inserts = sum(json.loads(r['after']).get('qty', 0) for r in rows if r['op'] == 'insert')
        self.assertEqual(qtys.pop(), moves + inserts, 'every movement made on any PC is counted exactly once')


class T19_Crashes(Base):
    """19-23: interrupted network, crashes, attachments."""
    N = 2

    def test_a_interrupted_transfer(self):
        """19. The connection is cut in the middle of a large transfer; nothing half-applied, resumes later."""
        self.unplug(0)
        self.unplug(1)
        ops = [area_op(f'B{i:03d}', f'Bulk {i}', description='x' * 2000) for i in range(400)]
        self.ac.post('/api/commit', {'label': 'bulk', 'ops': ops})
        for p in self.proxies:
            p.cut_after = 60000  # every connection dies after 60 kB from the server side
        self.plug(0)
        self.plug(1)
        for _ in range(10):
            time.sleep(0.5)
            n = len([a for a in self.clients[1].get('/api/state')['areas'] if a['id'].startswith('B')])
            self.assertEqual(n, 0, 'the 800 kB change cannot arrive through connections cut after 60 kB, and nothing half-applied')
        for p in self.proxies:
            p.cut_after = None
        self.converged()
        self.assertEqual(len([a for a in self.clients[1].get('/api/state')['areas'] if a['id'].startswith('B')]), 400)

    def test_b_crash_during_sync_and_restart(self):
        """20-21. Hard kill of a PC while it receives changes; after restart everything is consistent and complete."""
        self.unplug(1)
        for k in range(20):
            self.ac.post('/api/commit', {'label': f'crash {k}', 'ops': [area_op(f'K{k:02d}', f'Crash {k}', description='y' * 5000)]})
        self.plug(1)
        time.sleep(0.4)
        self.servers[1].kill()
        self.servers[1].start()
        self.relogin(1)
        rep = self.clients[1].post('/api/devices/verify', {'all': True})
        self.assertTrue(rep['ok'], rep)
        self.converged()
        self.assertEqual(len([a for a in self.clients[1].get('/api/state')['areas'] if a['id'].startswith('K')]), 20)

    def test_c_attachments(self):
        """22-23. Upload on one PC; the other shows a placeholder while the file is missing, continues an interrupted
        download from where it stopped (only the rest travels), verifies it by SHA-256 and never shows a partial file."""
        data = os.urandom(900_000)
        sha = hashlib.sha256(data).hexdigest()
        # the administrator PC cannot be reached by pc1 while the photo is added (its rows still arrive: the administrator
        # PC pushes them), so pc1 certainly has the record but not the file yet
        self.unplug(0)
        up = self.ac.call('POST', '/api/upload?name=big.jpg', raw=data, headers={'Content-Type': 'application/octet-stream'})
        self.assertTrue(up['src'].startswith('/files/cas/'))
        self.ac.post('/api/commit', {'label': 'photo', 'ops': [area_op('P1', 'Photo area'),
                                                              {'e': 'photos', 'id': 'ph1', 'op': 'put', 'row': {'areaId': 'P1', 'src': up['src'], 'main': True}}]})
        wait_until(lambda: get_area(self.clients[1], 'P1'), 30, what='photo row')
        ph = self.clients[1].call('GET', up['src'])
        self.assertIn(b'<svg', ph, 'while the file is missing a placeholder is shown')
        # an earlier download stopped after 300 kB: the part file is kept, never shown as the real file
        part_dir = os.path.join(self.servers[1].data_dir, 'uploads', '.incoming')
        os.makedirs(part_dir, exist_ok=True)
        with open(os.path.join(part_dir, sha + '.part'), 'wb') as f:
            f.write(data[:300_000])
        final = os.path.join(self.servers[1].data_dir, 'uploads', 'cas', os.path.basename(up['src']))
        self.assertFalse(os.path.exists(final), 'a partial file must never be visible as the real file')
        self.assertIn(b'<svg', self.clients[1].call('GET', up['src']))
        logf = os.path.join(self.servers[1].data_dir, 'logs', time.strftime('sync-%Y-%m.jsonl'))
        start = os.path.getsize(logf) if os.path.exists(logf) else 0
        self.plug(0)
        wait_until(lambda: self.clients[1].call('GET', up['src']) == data, 60, what='file copied')
        self.assertEqual(hashlib.sha256(open(final, 'rb').read()).hexdigest(), sha)
        self.assertEqual(os.listdir(part_dir), [])
        with open(logf, 'rb') as f:  # the download continued: only the missing 600 kB travelled
            events = [json.loads(x) for x in f.read()[start:].decode('utf-8').splitlines() if x.strip()]
        done = [e for e in events if e.get('event') == 'file' and e.get('path') == up['src'] and e.get('result') == 'ok']
        self.assertTrue(done, events)
        rounds = [e for e in events if e.get('files')]
        self.assertTrue(rounds and rounds[-1]['bytes_in'] < 800_000, rounds)

    def test_d_corrupt_copy_rejected(self):
        """23. A damaged copy (wrong checksum) is thrown away and never shown."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))
        data = os.urandom(50_000)
        up = self.ac.call('POST', '/api/upload?name=doc.pdf', raw=data, headers={'Content-Type': 'application/octet-stream'})
        # damage the original on the administrator PC before pc1 fetches it
        self.unplug(0)
        src = os.path.join(self.servers[0].data_dir, 'uploads', 'cas', os.path.basename(up['src']))
        with open(src, 'r+b') as f:
            f.seek(100)
            f.write(b'CORRUPTED')
        self.ac.post('/api/commit', {'label': 'doc', 'ops': [area_op('D1', 'Doc area'),
                                                            {'e': 'docs', 'id': 'd1', 'op': 'put', 'row': {'areaId': 'D1', 'src': up['src'], 'name': 'doc.pdf'}}]})
        self.plug(0)
        wait_until(lambda: get_area(self.clients[1], 'D1'), 30, what='doc row')
        wait_until(lambda: any(a['kind'] == 'file' for a in self.clients[1].get('/api/devices')['alerts']), 30, what='damaged copy alert')
        self.assertFalse(os.path.exists(os.path.join(self.servers[1].data_dir, 'uploads', 'cas', os.path.basename(up['src']))))


class T29_Tamper(Base):
    N = 2

    def test_tampering_detected(self):
        """29. Editing or deleting an old log entry is detected by the integrity check (and on the other PC by the chain)."""
        self.ac.post('/api/commit', {'label': 'evidence', 'ops': [area_op('EV', 'Evidence')]})
        self.converged()
        s = self.servers[1]
        s.stop()
        db = sqlite3.connect(os.path.join(s.data_dir, 'journal.db'))
        db.execute("UPDATE audit SET user='somebody else' WHERE label='evidence'")
        row = db.execute("SELECT lsn, body FROM changes WHERE body LIKE '%evidence%'").fetchone()
        db.execute('UPDATE changes SET body=? WHERE lsn=?', (row[1].replace('Evidence', 'Changed'), row[0]))
        db.commit()
        db.close()
        s.start()
        c = self.relogin(1)
        rep = c.post('/api/devices/verify', {'all': True})
        self.assertFalse(rep['ok'])
        text = ' '.join(rep['problems'])
        self.assertIn('changed after it was saved', text)
        self.assertIn('audit log entry was edited', text)
        self.assertTrue(any(a['kind'] == 'integrity' for a in c.get('/api/devices')['alerts']))


class T30_Restore(Base):
    N = 2

    def test_restore_is_a_change_not_a_rollback(self):
        """30. Restoring a backup on one PC brings data back everywhere, keeps history, and does not undo a change
        that another PC made at the same time."""
        ac, c1 = self.clients
        ac.post('/api/commit', {'label': 'r', 'ops': [area_op('R1', 'Restore me', description='good'), area_op('R2', 'Other')]})
        self.converged()
        name = ac.post('/api/backups')['name']
        edit(ac, 'R1', description='bad change')
        a = get_area(ac, 'R2')
        ac.post('/api/commit', {'label': 'oops', 'ops': [{'e': 'areas', 'id': 'R2', 'op': 'del', 'ver': a['ver']}]})
        self.converged()
        self.unplug(1)
        edit(c1, 'R2', capacity=77) if get_area(c1, 'R2') else None
        c1.post('/api/commit', {'label': 'offline work', 'ops': [area_op('R3', 'Made on pc1 meanwhile')]})
        audit_before = ac.get('/api/audit?limit=1000')['total']
        r = ac.post('/api/backups/restore', {'name': name})
        self.assertTrue(r['safety'].endswith('pre-restore.db'))
        self.plug(1)
        self.converged()
        for c in self.clients:
            self.assertEqual(get_area(c, 'R1')['description'], 'good')
            self.assertIsNotNone(get_area(c, 'R2'))
            self.assertIsNotNone(get_area(c, 'R3'), 'work done elsewhere must survive a restore')
        self.assertGreater(ac.get('/api/audit?limit=1000')['total'], audit_before, 'history is never rolled back')


class T31_FourPCs(Base):
    N = 4

    def test_four_pcs_partitioned(self):
        """31. Four PCs in two separate groups, then one PC alone, all changing data; then everything heals."""
        c = self.clients
        c[0].post('/api/commit', {'label': 'base', 'ops': [area_op('F', 'Four', capacity=1)]})
        self.converged()
        # group {0,1} and group {2,3}: cut 0<->2,3 by unplugging 2 and 3 from 0/1 is not possible with one proxy per PC,
        # so: unplug 2 and 3 (they still reach each other? no - both unplugged). Use sequential partitions instead.
        self.unplug(2)
        self.unplug(3)
        move(c[0], 'F', 'tv', 1)
        move(c[1], 'F', 'tv', 2)
        move(c[2], 'F', 'tv', 3)
        move(c[3], 'F', 'tv', 4)
        edit(c[3], 'F', name='Four renamed')
        self.converged([0, 1])
        self.plug(2)
        self.converged([0, 1, 2])
        self.unplug(0)
        move(c[1], 'F', 'tv', 5)
        self.plug(3)
        self.converged([1, 2, 3])
        self.plug(0)
        self.converged()
        for x in c:
            a = get_area(x, 'F')
            self.assertEqual(next(i['qty'] for i in a['inventory'] if i['item'] == 'tv'), 15)
            self.assertEqual(a['name'], 'Four renamed')
        for x in c:
            self.assertTrue(x.post('/api/devices/verify', {'all': True})['ok'])
        # the administrator sees history from every PC
        nodes = {r['node'] for r in c[0].get('/api/audit?limit=1000')['rows']}
        self.assertEqual(len(nodes), 4)


class T32_PersonalLinks(Base):
    """Every user can get a fixed personal link that logs in under their own name on any PC; only the administrator PC
    makes, shows, replaces or switches off links; a replaced link stops working everywhere."""
    N = 2

    @staticmethod
    def _open(c, token):
        """What a browser does: open the link (a page), then the page sends the POST by itself."""
        page = c.get('/k/' + token)
        c.call('POST', '/k/' + token, raw=b'')
        return page

    def _user(self, name):
        return next(x for x in self.ac.get('/api/quick-links')['users'] if x['username'] == name)

    def test_links(self):
        ac, pc1 = self.ac, self.servers[1]
        ac.post('/api/users/save', {'username': 'omar', 'full_name': 'Omar Tarek', 'password': 'Temp-pass55', 'must_change': True,
                                    'perms': ['dashboard.view', 'areas.view', 'areas.create', 'areas.edit'], 'areas': None, 'role': 'Custom'})
        omar = self._user('omar')
        self.assertFalse(omar['on'])
        self.assertTrue(omar['allowed'])
        boss = self._user(ADMIN[0])
        self.assertFalse(boss['allowed'])
        with self.assertRaises(ApiError) as e:  # administrator accounts never get a link
            ac.post('/api/quick-links/set', {'id': boss['id'], 'on': True})
        self.assertEqual(e.exception.code, 400)

        ac.post('/api/quick-links/set', {'id': omar['id'], 'on': True})
        token = self._user('omar')['token']
        self.assertTrue(token and len(token) >= 25)
        self.assertEqual(self._user('omar')['token'], token)  # fixed: shown again the same
        self.converged()

        # a member PC can use the link but cannot make or show links
        self.assertIsNone(next(x for x in self.clients[1].get('/api/quick-links')['users'] if x['username'] == 'omar')['token'])
        with self.assertRaises(ApiError) as e:
            self.clients[1].post('/api/quick-links/set', {'id': omar['id'], 'on': False})
        self.assertEqual(e.exception.code, 403)

        # opening the link without the page's own POST (a chat preview, a scanner) logs nobody in
        c = pc1.client()
        self.assertIn(b'Omar Tarek', c.get('/k/' + token))
        with self.assertRaises(ApiError) as e:
            c.get('/api/me')
        self.assertEqual(e.exception.code, 401)
        # the real browser: logged in as Omar, with Omar's permissions, no password prompt
        self._open(c, token)
        me = c.get('/api/me')
        self.assertEqual((me['username'], me['must_change'], me['viaLink'], me['admin']), ('omar', False, True, False))
        c.post('/api/commit', {'label': 'by link', 'ops': [area_op('LNK', 'Made through the link')]})
        with self.assertRaises(ApiError) as e:
            c.get('/api/users')
        self.assertEqual(e.exception.code, 403)
        with self.assertRaises(ApiError) as e:
            c.get('/api/quick-links')
        self.assertEqual(e.exception.code, 403)
        self.converged()
        rows = ac.get('/api/audit?q=LNK')['rows']
        self.assertTrue(rows and all('omar' in r['user'] for r in rows))
        wait_until(lambda: self._user('omar')['last_used'], 20, what='link use reported')
        self.assertEqual(self._user('omar')['last_used']['pc'], 'pc1')

        # a wrong link: refused and logged
        bad = pc1.client()
        with self.assertRaises(ApiError) as e:
            bad.get('/k/' + 'x' * 28)
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(ApiError) as e:
            bad.call('POST', '/k/' + 'x' * 28, raw=b'')
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(ApiError):
            bad.get('/api/me')
        self.assertTrue(self.clients[1].get('/api/security?type=login-link-failed')['rows'])

        # a request from another web site is refused, and the secret part of the link is never written into a log
        with self.assertRaises(ApiError) as e:
            pc1.client().call('POST', '/k/' + token, raw=b'', headers={'Origin': 'http://evil.example'})
        self.assertEqual(e.exception.code, 403)
        self.converged()
        for x in self.clients:
            self.assertEqual(x.get('/api/security?limit=1000&q=' + token)['rows'], [])
            self.assertEqual(x.get('/api/activity?limit=1000&q=' + token)['rows'], [])
        for srv in self.servers:
            for root, _, files in os.walk(os.path.join(srv.data_dir, 'logs')):
                for f in files:
                    with open(os.path.join(root, f), encoding='utf-8', errors='ignore') as fh:
                        self.assertNotIn(token, fh.read(), f)

        # new link: the old one stops working on every PC, and whoever used it is logged out
        ac.post('/api/quick-links/set', {'id': omar['id'], 'on': True})
        new = self._user('omar')['token']
        self.assertNotEqual(new, token)
        self.converged()
        wait_until(lambda: T03_Cluster._logged_out(c), 20, what='old link session ended')
        with self.assertRaises(ApiError) as e:
            self._open(pc1.client(), token)
        self.assertEqual(e.exception.code, 404)
        c2 = pc1.client()
        self._open(c2, new)
        self.assertEqual(c2.get('/api/me')['username'], 'omar')

        # switched off: the link is dead, the normal password still works
        ac.post('/api/quick-links/set', {'id': omar['id'], 'on': False})
        self.assertFalse(self._user('omar')['on'])
        self.converged()
        wait_until(lambda: T03_Cluster._logged_out(c2), 20, what='link session ended after switch off')
        with self.assertRaises(ApiError):
            self._open(pc1.client(), new)
        pc1.client().login('omar', 'Temp-pass55')

        # an account with a link cannot become an administrator (switch the link off first)
        ac.post('/api/quick-links/set', {'id': omar['id'], 'on': True})
        tok = self._user('omar')['token']
        u = next(x for x in ac.get('/api/users')['users'] if x['username'] == 'omar')
        with self.assertRaises(ApiError) as e:
            ac.post('/api/users/save', {**u, 'perms': u['perms'] + ['users.manage']})
        self.assertEqual(e.exception.code, 400)
        self.converged()
        c3 = pc1.client()
        self._open(c3, tok)
        self.assertEqual(c3.get('/api/me')['username'], 'omar')


class T33_PeopleAndProfiles(Base):
    """A person added with a personal link only (no user name, no password), profiles made and changed on the administrator
    PC and applied to everybody who has them, on every PC."""
    N = 2

    def test_people_and_profiles(self):
        ac, pc1 = self.ac, self.servers[1]
        us = ac.get('/api/users')
        full = next(p for p in us['profiles'] if p['id'] == 'full-access')
        self.assertNotIn('users.manage', full['perms'])
        # a person with only a link: the user name is made from the name, there is no password anybody knows
        r = ac.post('/api/users/save', {'full_name': 'Mona Adel', 'login': 'link', 'role': full['name'], 'perms': full['perms'], 'areas': None})
        self.assertEqual((r['username'], r['login'], r['link_on'], r['must_change']), ('mona.adel', 'link', True, False))
        r2 = ac.post('/api/users/save', {'full_name': 'Mona Adel', 'login': 'link', 'role': 'Visitor', 'perms': ['dashboard.view'], 'areas': None})
        self.assertEqual(r2['username'], 'mona.adel2')  # same name twice: still two different people
        with self.assertRaises(ApiError) as e:  # a link can never carry administrator rights
            ac.post('/api/users/save', {'full_name': 'Boss Two', 'login': 'link', 'perms': ['users.manage'], 'areas': None})
        self.assertEqual(e.exception.code, 400)
        self.converged()
        c = pc1.client()
        T32_PersonalLinks._open(c, r['token'])
        me = c.get('/api/me')
        self.assertEqual((me['username'], sorted(me['perms'])), ('mona.adel', sorted(full['perms'])))

        # a profile of our own, used by a person, then changed: the person is updated on every PC
        g = ac.post('/api/profiles/save', {'name': 'Guest', 'perms': ['dashboard.view']})
        gus = ac.post('/api/users/save', {'full_name': 'Gus Guest', 'login': 'link', 'role': 'Guest', 'perms': ['dashboard.view'], 'areas': None})
        with self.assertRaises(ApiError) as e:
            ac.post('/api/profiles/save', {'name': 'guest', 'perms': []})  # the same name twice
        self.assertEqual(e.exception.code, 400)
        res = ac.post('/api/profiles/save', {'id': g['id'], 'name': 'Guests', 'perms': ['areas.view', 'dashboard.view'], 'apply': True})
        self.assertEqual(res['updated'], 1)
        self.converged()
        on_pc1 = {u['id']: u for u in self.clients[1].get('/api/users')['users']}
        self.assertEqual((on_pc1[gus['id']]['role'], on_pc1[gus['id']]['perms']), ('Guests', ['areas.view', 'dashboard.view']))
        self.assertIn('Guests', [p['name'] for p in self.clients[1].get('/api/users')['profiles']])
        # a ready-made profile can be changed too, the Administrator profile never
        ac.post('/api/profiles/save', {'id': 'visitor', 'name': 'Visitor', 'perms': ['dashboard.view', 'reports.view'], 'apply': True})
        self.assertEqual(next(u for u in ac.get('/api/users')['users'] if u['id'] == r2['id'])['perms'], ['dashboard.view', 'reports.view'])
        with self.assertRaises(ApiError) as e:
            ac.post('/api/profiles/save', {'id': 'administrator', 'name': 'Administrator', 'perms': []})
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(ApiError) as e:  # only on the administrator PC
            self.clients[1].post('/api/profiles/save', {'name': 'Sneaky', 'perms': ['users.manage']})
        self.assertEqual(e.exception.code, 403)
        # a profile that would give a link person administrator rights is refused
        with self.assertRaises(ApiError) as e:
            ac.post('/api/profiles/save', {'id': g['id'], 'name': 'Guests', 'perms': ['users.manage'], 'apply': True})
        self.assertEqual(e.exception.code, 400)
        # deleting a profile: its people keep their permissions
        ac.post('/api/profiles/delete', {'id': g['id']})
        self.converged()
        u = next(x for x in self.clients[1].get('/api/users')['users'] if x['id'] == gus['id'])
        self.assertEqual((u['role'], u['perms']), ('Custom', ['areas.view', 'dashboard.view']))
        self.assertNotIn('Guests', [p['name'] for p in self.clients[1].get('/api/users')['profiles']])

        # from link to password: the link stops, the password works
        u = next(x for x in ac.get('/api/users')['users'] if x['id'] == r['id'])
        with self.assertRaises(ApiError):
            ac.post('/api/users/save', {**u, 'login': 'password'})  # a password is needed
        ac.post('/api/users/save', {**u, 'login': 'password', 'password': 'Fresh-pass42', 'must_change': True})
        self.converged()
        wait_until(lambda: T03_Cluster._logged_out(c), 20, what='link session ended')
        self.assertTrue(pc1.client().login('mona.adel', 'Fresh-pass42')['must_change'])
        with self.assertRaises(ApiError):
            T32_PersonalLinks._open(pc1.client(), r['token'])
        # review regressions -------------------------------------------------------------
        # password -> link: the old password stops working, the person gets a link
        sara = ac.post('/api/users/save', {'username': 'sara.s', 'full_name': 'Sara Saad', 'password': 'Temp-pass66', 'must_change': True,
                                           'perms': ['dashboard.view'], 'areas': None})
        res = ac.post('/api/users/save', {**sara, 'login': 'link'})
        self.assertTrue(res.get('token') and res['link_on'] and not res['must_change'])
        with self.assertRaises(ApiError):
            A2 = self.servers[0].client(); A2.login('sara.s', 'Temp-pass66')
        # a link never carries any administrator right (not only "manage people")
        for bad in (['backups.restore'], ['data.import'], ['logs.security']):
            with self.assertRaises(ApiError) as e:
                ac.post('/api/users/save', {'full_name': 'No Way', 'login': 'link', 'perms': ['dashboard.view'] + bad, 'areas': None})
            self.assertEqual(e.exception.code, 400)
        vis = next(p for p in ac.get('/api/users')['profiles'] if p['id'] == 'visitor')
        with self.assertRaises(ApiError):  # r2 (a link person) has the Visitor profile
            ac.post('/api/profiles/save', {'id': 'visitor', 'name': 'Visitor', 'perms': vis['perms'] + ['backups.restore'], 'apply': True})
        # a password person who also has a link cannot become administrator while the link is on
        ali = ac.post('/api/users/save', {'username': 'ali.k', 'full_name': 'Ali Kamal', 'password': 'Temp-pass77', 'must_change': False,
                                          'perms': ['dashboard.view'], 'areas': None})
        ac.post('/api/quick-links/set', {'id': ali['id'], 'on': True})
        ali = next(x for x in ac.get('/api/users')['users'] if x['id'] == ali['id'])
        with self.assertRaises(ApiError):
            ac.post('/api/users/save', {**ali, 'perms': ali['perms'] + ['users.manage']})
        # the old name "Manager" is reserved
        with self.assertRaises(ApiError):
            ac.post('/api/profiles/save', {'name': 'manager', 'perms': []})
        # links are only made on the administrator PC (a clear message, not a server error)
        with self.assertRaises(ApiError) as e:
            self.clients[1].post('/api/quick-links/set', {'id': ali['id'], 'on': True})
        self.assertEqual(e.exception.code, 403)
        # a link person whose link is off: saving other details does not quietly make a new link
        ac.post('/api/quick-links/set', {'id': r2['id'], 'on': False})
        u2 = next(x for x in ac.get('/api/users')['users'] if x['id'] == r2['id'])
        res = ac.post('/api/users/save', {**u2, 'title': 'Guest'})
        self.assertFalse(res.get('token') or res['link_on'])
        # renaming a profile without "apply": its people follow the new name
        h = ac.post('/api/profiles/save', {'name': 'Helpers', 'perms': ['dashboard.view']})
        hp = ac.post('/api/users/save', {'full_name': 'Hana Help', 'login': 'link', 'role': 'Helpers', 'perms': ['dashboard.view'], 'areas': None})
        ac.post('/api/profiles/save', {'id': h['id'], 'name': 'Helpers Team', 'perms': ['dashboard.view', 'areas.view'], 'apply': False})
        u3 = next(x for x in ac.get('/api/users')['users'] if x['id'] == hp['id'])
        self.assertEqual((u3['role'], u3['perms']), ('Helpers Team', ['dashboard.view']))
        # a link opened in a browser where somebody else is logged in asks first, and never switches by itself
        busy = self.servers[0].client()
        busy.login(*ADMIN)
        page = busy.get('/k/' + hp['token'])
        self.assertIn(b'Continue as Hana Help', page)
        self.assertNotIn(b'quick.js', page)
        self.assertEqual(busy.get('/api/me')['username'], ADMIN[0])
        same = self.servers[0].client()
        T32_PersonalLinks._open(same, hp['token'])
        self.assertEqual(same.get('/api/me')['username'], 'hana.help')
        same.get('/k/' + hp['token'])  # already this person: straight to the system
        self.assertEqual(same.get('/api/me')['username'], 'hana.help')

        # people who are not administrators do not see account and profile changes in the data changes log
        viewer = pc1.client()
        ac.post('/api/users/save', {'username': 'logviewer', 'full_name': 'Log Viewer', 'password': 'Look-only77', 'must_change': False,
                                    'perms': ['dashboard.view', 'logs.view'], 'areas': None})
        self.converged()
        viewer.login('logviewer', 'Look-only77')
        self.assertFalse([x for x in viewer.get('/api/audit?limit=1000')['rows'] if x['entity'] in ('users', 'profiles', 'nodes')])


class T34_InstalledMode(unittest.TestCase):
    """The installed program (BAMS.exe = server/bams_main.py with the web pages packed inside): data, settings and
    backups live in BAMS_HOME (not in the program folder), the pages come from inside the program, nothing else of
    the program folder can be fetched, the maintenance tools work, a second start does not start a second server."""

    def test_installed_mode(self):
        import subprocess
        import sys
        import tempfile
        import urllib.request
        from harness import Client, free_port
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp = tempfile.mkdtemp(prefix='bams-installed-')
        home, packed = os.path.join(tmp, 'ProgramData', 'BAMS'), os.path.join(tmp, 'packed')
        os.makedirs(home)
        os.makedirs(packed)
        subprocess.check_call([sys.executable, os.path.join(root, 'tools', 'make_assets.py'), os.path.join(packed, '_assets.py')],
                              stdout=subprocess.DEVNULL)
        port = free_port()
        with open(os.path.join(home, 'config.json'), 'w') as f:
            json.dump({'port': port, 'sync_port': free_port(), 'open_browser': True, 'host': '127.0.0.1'}, f)
        env = {**os.environ, 'BAMS_HOME': home, 'PYTHONPATH': packed, 'BAMS_MACHINE_ID': 'installed-test'}
        main = os.path.join(root, 'server', 'bams_main.py')
        proc = subprocess.Popen([sys.executable, main, '--background'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = f'http://127.0.0.1:{port}'
            c = Client(base)
            st = wait_until(lambda: self._try(c), 30, what='installed program started')
            self.assertTrue(st['about']['installed'])
            self.assertTrue(st['about']['version'])
            with open(os.path.join(root, 'js', 'app.js'), 'rb') as f:
                self.assertEqual(c.get('/js/app.js'), f.read())  # from inside the program
            self.assertIn(b'Break Area', c.get('/'))
            for bad in ('/js/../server/app.py', '/js/%2e%2e/server/app.py', '/css/../config.json', '/lib/../LICENSE.txt'):
                with self.assertRaises(ApiError) as e:
                    c.get(bad)
                self.assertEqual(e.exception.code, 404, bad)
            make_authority(type('S', (), {'client': lambda self: c})())
            self.assertTrue(os.path.exists(os.path.join(home, 'data', 'auth.db')))
            self.assertTrue(os.path.exists(os.path.join(home, 'data', 'bams.db')))
            self.assertFalse(os.path.exists(os.path.join(root, 'server', 'data')))
            # a second start (desktop icon while it already runs) ends by itself and does not disturb the first
            second = subprocess.run([sys.executable, main, '--background'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            self.assertEqual(second.returncode, 0)
            self.assertTrue(self._try(c))
        finally:
            proc.terminate()
            proc.wait(20)
        # the maintenance tools find the data in BAMS_HOME
        out = subprocess.run([sys.executable, main, 'tool', 'verify'], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _try(c):
        try:
            return c.get('/api/auth/status')
        except Exception:
            return None


class T35_SecondReview(unittest.TestCase):
    """Regressions of the second whole-code review, on one PC."""

    @classmethod
    def setUpClass(cls):
        cls.S = Server('solo').start()
        cls.ac = make_authority(cls.S)
        cls.ac.post('/api/commit', {'label': 'data', 'ops': [area_op('Z1', 'Zone One'), area_op('Z2', 'Zone Two')]})
        move(cls.ac, 'Z2', 'chairs', 12)

    @classmethod
    def tearDownClass(cls):
        cls.S.cleanup()

    def raw_get(self, path):
        import http.client
        h = http.client.HTTPConnection('127.0.0.1', self.S.port, timeout=20)
        h.putrequest('GET', path, skip_accept_encoding=True)
        h.endheaders()
        r = h.getresponse()
        body = r.read()
        h.close()
        return r.status, body

    def test_a_program_folder_cannot_be_read(self):
        """The portable program folder holds data/, keys and config.json next to css/js/lib - none of it may leak."""
        for path in ('/css/../config.json', '/css/../server/app.py', '/js/..%2fserver%2fapp.py', '/lib/%2e%2e/LICENSE.txt',
                     '/css/..\\config.json', '/js/../../etc/passwd', '/css/', '/js/app.js/..'):
            status, body = self.raw_get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b'import', body)
        self.assertEqual(self.raw_get('/js/app.js')[0], 200)
        self.assertEqual(self.raw_get('/')[0], 200)

    def test_b_area_limited_user_cannot_touch_other_areas(self):
        ac = self.ac
        ac.post('/api/users/save', {'username': 'zoe.z', 'full_name': 'Zoe Zone', 'password': 'Area-limit47', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'inventory.edit', 'areas.edit'], 'areas': ['Z1']})
        c = self.S.client()
        c.login('zoe.z', 'Area-limit47')
        inv = next(x for x in get_area(ac, 'Z2')['inventory'] if x['item'] == 'chairs')
        hostile = {'e': 'inventory', 'id': 'Z2:chairs', 'op': 'put', 'ver': inv['ver'],
                   'row': {**{k: v for k, v in inv.items() if k != 'ver'}, 'areaId': 'Z1', 'qty': 0}}
        with self.assertRaises(ApiError) as e:
            c.post('/api/commit', {'label': 'steal', 'ops': [hostile]})
        self.assertEqual(e.exception.code, 403)
        self.assertEqual(next(x for x in get_area(ac, 'Z2')['inventory'] if x['item'] == 'chairs')['qty'], 12)
        # conflicts are decided by an administrator only, never through a normal save
        with self.assertRaises(ApiError) as e:
            c.post('/api/commit', {'label': 'x', 'ops': [{'e': 'areas', 'id': 'Z2', 'op': 'del', 'resolve': True}]})
        self.assertEqual(e.exception.code, 403)
        # the recycle bin shows all areas: not for area-limited users even with the permission
        ac.post('/api/users/save', {**next(u for u in ac.get('/api/users')['users'] if u['username'] == 'zoe.z'),
                                    'perms': ['dashboard.view', 'areas.view', 'trash.restore']})
        c2 = self.S.client()
        c2.login('zoe.z', 'Area-limit47')
        with self.assertRaises(ApiError) as e:
            c2.get('/api/trash')
        self.assertEqual(e.exception.code, 403)

    def test_c_bad_file_reference_refused(self):
        with self.assertRaises(ApiError) as e:
            self.ac.post('/api/commit', {'label': 'p', 'ops': [{'e': 'photos', 'id': 'ph1', 'op': 'put',
                                                                   'row': {'areaId': 'Z1', 'src': '/files/../../x.jpg', 'caption': 'x'}}]})
        self.assertEqual(e.exception.code, 400)

    def test_d_many_wrong_logins_are_cut_short(self):
        c = self.S.client()
        for _ in range(11):
            with self.assertRaises(ApiError):
                c.login('boss', 'wrong-password-1')
        t = time.time()
        with self.assertRaises(ApiError) as e:
            c.login('boss', 'wrong-password-1')
        self.assertIn('Too many', str(e.exception.msg))
        self.assertLess(time.time() - t, 0.5)  # refused without the slow password check
        with self.assertRaises(ApiError) as e:  # a huge request before logging in is refused
            c.call('POST', '/api/auth/login', raw=b'{"username": "' + b'x' * 200000 + b'"}')
        self.assertEqual(e.exception.code, 400)

    def test_e_tools_wait_for_the_program_to_stop(self):
        import subprocess
        import sys
        tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server', 'nodectl.py')
        out = subprocess.run([sys.executable, tool, 'status'], env={**os.environ, 'BAMS_CONFIG': self.S.cfg_path},
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn('running', out.stdout)


class T36_BackupAdminPC(Base):
    """Delegation: the administrator makes another PC a backup administrator PC. It receives the administrator key at its
    next contact and can then manage people while the administrator PC is switched off; ending the role removes the key."""

    def test_backup_admin_pc(self):
        ac, pc1, pc2 = self.ac, self.clients[1], self.clients[2]
        pc1_id = self.servers[1].node_id
        with self.assertRaises(ApiError):  # only an administrator PC can hand out the role
            pc2.post('/api/devices/backup', {'id': self.servers[2].node_id, 'on': True})
        with self.assertRaises(ApiError) as e:  # before: pc1 cannot manage people
            pc1.post('/api/users/save', {'username': 'early.bird', 'full_name': 'Early Bird', 'password': 'Early-pass31', 'perms': ['dashboard.view'], 'areas': None})
        self.assertEqual(e.exception.code, 403)
        ac.post('/api/devices/backup', {'id': pc1_id, 'on': True})
        wait_until(lambda: pc1.get('/api/users')['authority'], 40, what='backup PC received the administrator key')
        self.assertTrue(next(n for n in ac.get('/api/devices')['nodes'] if n['id'] == pc1_id)['backup'])
        self.assertFalse(pc2.get('/api/users')['authority'])
        # the administrator PC is switched off: people are still managed on the backup PC
        self.servers[0].stop()
        pc1.post('/api/users/save', {'username': 'deputy.made', 'full_name': 'Made On Backup', 'password': 'Spare-key52x', 'must_change': False,
                                     'perms': ['dashboard.view', 'areas.view'], 'areas': None})
        wait_until(lambda: any(u['username'] == 'deputy.made' for u in pc2.get('/api/users')['users']), 30, what='user from backup PC on pc2')
        self.servers[2].client().login('deputy.made', 'Spare-key52x')
        self.servers[0].start()
        ac = self.relogin(0)
        self.converged()
        self.assertTrue(any(u['username'] == 'deputy.made' for u in ac.get('/api/users')['users']))
        self.assertTrue(ac.post('/api/devices/verify', {'all': True})['ok'])
        # the role ends: the key is deleted on pc1, it can no longer manage people
        ac.post('/api/devices/backup', {'id': pc1_id, 'on': False})
        wait_until(lambda: not self.clients[1].get('/api/users')['authority'], 40, what='backup role ended on pc1')
        with self.assertRaises(ApiError) as e:
            self.clients[1].post('/api/users/save', {'username': 'too.late', 'full_name': 'Too Late', 'password': 'Late-pass77', 'perms': [], 'areas': None})
        self.assertEqual(e.exception.code, 403)
        self.assertFalse(os.path.exists(os.path.join(self.servers[1].data_dir, 'node', 'authority.key')))

    def test_z_removed_while_off(self):
        """Review 2.3: a backup PC may not save the key or remove the administrator PC, and a backup PC that is removed
        while switched off deletes the key when the others tell it (it never receives its own removal)."""
        ac, pc2 = self.relogin(0), self.clients[2]
        pc2_id, admin_id = self.servers[2].node_id, self.servers[0].node_id
        ac.post('/api/devices/backup', {'id': pc2_id, 'on': True})
        wait_until(lambda: pc2.get('/api/users')['authority'], 40, what='pc2 became backup PC')
        with self.assertRaises(ApiError) as e:
            pc2.post('/api/devices/export-key', {'passphrase': 'a long passphrase 2026'})
        self.assertEqual(e.exception.code, 403)
        with self.assertRaises(ApiError):
            pc2.post('/api/devices/revoke', {'id': admin_id})
        self.assertEqual(next(n for n in ac.get('/api/devices')['nodes'] if n['id'] == admin_id)['status'], 'active')
        key = os.path.join(self.servers[2].data_dir, 'node', 'authority.key')
        self.servers[2].stop()
        ac.post('/api/devices/revoke', {'id': pc2_id})
        self.assertTrue(os.path.exists(key))
        self.servers[2].start()
        wait_until(lambda: not os.path.exists(key), 60, what='removed backup PC deleted the key')


class T37_AdminSafety(unittest.TestCase):
    """Version 2.3: second backup folder, saving the administrator key from the screen, Excel export without the
    activity log for non-administrators, sample data only on request."""

    @classmethod
    def setUpClass(cls):
        cls.S = Server('safety').start()
        cls.ac = make_authority(cls.S)
        cls.ac.post('/api/commit', {'label': 'data', 'ops': [area_op('Q1', 'Quay One')]})

    @classmethod
    def tearDownClass(cls):
        cls.S.cleanup()

    def test_second_backup_folder(self):
        ac = self.ac
        self.assertEqual(ac.get('/api/backups/folder')['dirs'], [])
        for bad in ('relative\\folder', os.path.join(self.S.data_dir, 'copies'), '\\\\fileserver\\share\\bams', '//fileserver/share/bams'):
            with self.assertRaises(ApiError) as e:
                ac.post('/api/backups/folder', {'path': bad})
            self.assertEqual(e.exception.code, 400, bad)
        usb = os.path.join(tempfile.mkdtemp(prefix='bams-usb-'), 'BAMS-Backups')
        try:
            r = ac.post('/api/backups/folder', {'path': usb})
            self.assertTrue(r['ok'], r)
            self.assertTrue(os.path.exists(os.path.join(usb, 'db', r['name'])), 'a backup is copied at once')
            with open(self.S.cfg_path, encoding='utf-8') as f:
                self.assertEqual(json.load(f)['extra_backup_dirs'], [usb])
            name = ac.post('/api/backups')['name']
            self.assertTrue(os.path.exists(os.path.join(usb, 'db', name)), 'every later backup too')
            self.assertEqual(ac.get('/api/backups/folder')['dirs'], [usb])
            ac.post('/api/backups/folder', {'path': ''})
            self.assertEqual(ac.get('/api/backups/folder')['dirs'], [])
            with open(self.S.cfg_path, encoding='utf-8') as f:
                self.assertEqual(json.load(f)['extra_backup_dirs'], [])
        finally:
            shutil.rmtree(os.path.dirname(usb), ignore_errors=True)

    def test_save_administrator_key(self):
        ac = self.ac
        self.assertFalse(ac.get('/api/devices')['key_saved'])
        with self.assertRaises(ApiError) as e:
            ac.post('/api/devices/export-key', {'passphrase': 'too short'})
        self.assertEqual(e.exception.code, 400)
        box = ac.post('/api/devices/export-key', {'passphrase': 'a long passphrase 2026'})
        with open(os.path.join(self.S.data_dir, 'node', 'authority.key')) as f:
            seed = f.read().strip()
        self.assertNotIn(seed, json.dumps(box), 'the key is never sent readable')
        import nodectl
        self.assertEqual(nodectl.unseal(box, 'a long passphrase 2026').hex(), seed)
        self.assertTrue(ac.get('/api/devices')['key_saved'])

    def test_export_activity_log_only_for_administrators(self):
        import io
        import zipfile
        ac = self.ac

        def sheets(c):
            z = zipfile.ZipFile(io.BytesIO(c.get('/api/export.xlsx')))
            return z.read('xl/workbook.xml').decode()
        self.assertIn('User Activity Log', sheets(ac))
        ac.post('/api/users/save', {'username': 'report.reader', 'full_name': 'Report Reader', 'password': 'Quarter-77x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'report.full', 'logs.activity'], 'areas': None})
        rc = self.S.client()
        rc.login('report.reader', 'Quarter-77x')
        self.assertNotIn('User Activity Log', sheets(rc))


class T38_OpenJoin(unittest.TestCase):
    """Version 2.4 (owner's request): a new PC joins with the administrator PC's address only - no code, no approval -
    gets the accounts and all data, and shares changes both ways. The administrator PC answers the network search."""

    @classmethod
    def setUpClass(cls):
        cls.A = Server('main').start()
        cls.ac = make_authority(cls.A)
        cls.ac.post('/api/commit', {'label': 'data', 'ops': [area_op('J1', 'Joined One')]})
        cls.B = Server('newpc').start()

    @classmethod
    def tearDownClass(cls):
        cls.A.cleanup()
        cls.B.cleanup()

    def test_join_with_address_only(self):
        import ssl, http.client
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        h = http.client.HTTPSConnection('127.0.0.1', self.A.sync_port, timeout=10, context=ctx)
        h.request('POST', '/sync/hello', body=b'{}', headers={'Content-Type': 'application/json', 'Content-Length': '2'})
        hello = json.loads(h.getresponse().read())
        h.close()
        self.assertTrue(hello['authority'])
        bc = self.B.client()
        r = bc.post('/api/join', {'address': self.A.sync_address, 'code': '', 'name': 'Store PC'})
        self.assertEqual(r['status'], 'approved')
        wait_until(lambda: self.B.status()['hasUsers'], 60, what='accounts on the new PC')
        bc = self.B.client()
        bc.login(*ADMIN)
        wait_until(lambda: any(a['id'] == 'J1' for a in bc.get('/api/state')['areas']), 60, what='data on the new PC')
        bc.post('/api/commit', {'label': 'from new pc', 'ops': [area_op('J2', 'Made On New PC')]})
        wait_until(lambda: any(a['id'] == 'J2' for a in self.ac.get('/api/state')['areas']), 60, what='change back on the main PC')
        names = [n['name'] for n in self.ac.get('/api/devices')['nodes']]
        self.assertIn('Store PC', names)
        with self.assertRaises(ApiError):  # a set-up PC cannot join again
            bc.post('/api/join', {'address': self.A.sync_address, 'code': '', 'name': 'Again'})

    def _sync_post(self, path, body):
        import ssl, http.client
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        h = http.client.HTTPSConnection('127.0.0.1', self.A.sync_port, timeout=10, context=ctx)
        data = json.dumps(body).encode()
        h.request('POST', path, body=data, headers={'Content-Type': 'application/json', 'Content-Length': str(len(data))})
        r = h.getresponse()
        out = (r.status, json.loads(r.read()))
        h.close()
        return out

    def test_join_answer_lost_then_asked_again(self):
        """Review 2.4: the first answer got lost - asking again with the same identity returns the same approved
        request instead of 'already registered'; a different key under that identity is refused."""
        ident = {'node': 'abcdef012345', 'name': 'Lost Answer PC', 'pub': '11' * 32, 'cert_fp': '22' * 32, 'port': '8443', 'open': True}
        st1, r1 = self._sync_post('/sync/join', ident)
        st2, r2 = self._sync_post('/sync/join', ident)
        self.assertEqual((st1, st2), (200, 200), (r1, r2))
        self.assertEqual((r1['request'], r1['secret']), (r2['request'], r2['secret']))
        st3, r3 = self._sync_post('/sync/join', {**ident, 'pub': '33' * 32})
        self.assertEqual(st3, 400, r3)


if __name__ == '__main__':
    unittest.main()


class T39_SerialNumbers(Base):
    """Version 2.5 (customer's request): every piece can carry its serial number. A piece is its own record, so two PCs
    adding pieces at the same time both keep theirs; a transfer moves the record to the other break area on every PC."""
    N = 2

    def test_serial_numbers(self):
        ac, pc1 = self.ac, self.clients[1]
        ac.post('/api/commit', {'label': 'areas', 'ops': [area_op('S1', 'Serial One'), area_op('S2', 'Serial Two')]})
        move(ac, 'S1', 'tv', 2)
        self.converged()
        piece = lambda pid, aid, serial: {'e': 'pieces', 'id': pid, 'op': 'put', 'row': {'areaId': aid, 'item': 'tv', 'serial': serial, 'date': '2026-09-29'}}
        # both PCs add a piece at the same time: both are kept everywhere
        self.unplug(1)
        ac.post('/api/commit', {'label': 'sn a', 'ops': [piece('pa000001', 'S1', 'TV-A')]})
        pc1.post('/api/commit', {'label': 'sn b', 'ops': [piece('pb000001', 'S1', 'TV-B')]})
        self.plug(1)
        self.converged()
        for c in (ac, pc1):
            self.assertEqual(sorted(p['serial'] for p in get_area(c, 'S1')['pieces']), ['TV-A', 'TV-B'])
        # a transfer on pc1 moves the record; the serial number is trimmed and required
        p = next(x for x in get_area(pc1, 'S1')['pieces'] if x['serial'] == 'TV-A')
        pc1.post('/api/commit', {'label': 'transfer', 'ops': [{'e': 'pieces', 'id': p['id'], 'op': 'put', 'ver': p['ver'],
                                                                'row': {'item': 'tv', 'serial': ' TV-A ', 'date': '2026-09-29', 'areaId': 'S2'}}]})
        self.converged()
        self.assertEqual([x['serial'] for x in get_area(ac, 'S2')['pieces']], ['TV-A'])
        with self.assertRaises(ApiError) as e:
            ac.post('/api/commit', {'label': 'empty', 'ops': [piece('pc000001', 'S1', '   ')]})
        self.assertEqual(e.exception.code, 400)
        # the permission "inventory.edit" is needed, and only for the person's own break areas
        ac.post('/api/users/save', {'username': 'serial.viewer', 'full_name': 'Serial Viewer', 'password': 'Plain-look42x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view'], 'areas': None})
        ac.post('/api/users/save', {'username': 'serial.keeper', 'full_name': 'Serial Keeper', 'password': 'Store-room42x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'inventory.edit'], 'areas': ['S1']})
        viewer, keeper = self.A.client(), self.A.client()
        viewer.login('serial.viewer', 'Plain-look42x')
        keeper.login('serial.keeper', 'Store-room42x')
        with self.assertRaises(ApiError) as e:
            viewer.post('/api/commit', {'label': 'no', 'ops': [piece('pd000001', 'S1', 'TV-D')]})
        self.assertEqual(e.exception.code, 403)
        with self.assertRaises(ApiError) as e:
            keeper.post('/api/commit', {'label': 'other area', 'ops': [piece('pe000001', 'S2', 'TV-E')]})
        self.assertEqual(e.exception.code, 403)
        keeper.post('/api/commit', {'label': 'own area', 'ops': [piece('pf000001', 'S1', 'TV-F')]})
        self.assertIn('TV-F', [x['serial'] for x in get_area(ac, 'S1')['pieces']])


class T40_AreaLogAndWork(Base):
    """Version 2.6: notes of a break area, finished work with cost / contractor / warranty. Two PCs writing notes at the
    same time keep both; cancelling on one PC and completing on another ends as done; a person who may not see costs
    never receives them (screen, change log) and cannot change or wipe them by saving."""
    N = 2

    def test_log_and_work(self):
        ac, pc1 = self.ac, self.clients[1]
        ac.post('/api/commit', {'label': 'area', 'ops': [area_op('L1', 'Log One')]})
        self.converged()
        note = lambda nid, text: {'e': 'notes', 'id': nid, 'op': 'put', 'row': {'areaId': 'L1', 'date': '2026-09-29', 'kind': 'Painting', 'text': text, 'by': 'x'}}
        self.unplug(1)
        ac.post('/api/commit', {'label': 'n1', 'ops': [note('na000001', 'Walls painted')]})
        pc1.post('/api/commit', {'label': 'n2', 'ops': [note('nb000001', 'New lamps')]})
        self.plug(1)
        self.converged()
        for c in (ac, pc1):
            self.assertEqual(sorted(n['text'] for n in get_area(c, 'L1')['notes']), ['New lamps', 'Walls painted'])
        with self.assertRaises(ApiError) as e:
            ac.post('/api/commit', {'label': 'empty', 'ops': [note('nc000001', '   ')]})
        self.assertEqual(e.exception.code, 400)

        # cost: only for people who may see it
        work = lambda wid, **kw: {'e': 'maintenance', 'id': wid, 'op': 'put', 'row': {
            'areaId': 'L1', 'date': '2026-09-20', 'details': 'Repair the door', 'status': 'Done', 'kind': 'Repair', 'assignedTo': 'Team',
            'contractor': 'Nile Doors', 'cost': 1200, **kw}}
        ac.post('/api/commit', {'label': 'w', 'ops': [work('w0000001')]})
        ac.post('/api/users/save', {'username': 'plain.desk', 'full_name': 'Plain Desk', 'password': 'Quiet-room81x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'maintenance.create', 'maintenance.complete', 'logs.view'], 'areas': None})
        ac.post('/api/users/save', {'username': 'money.desk', 'full_name': 'Money Desk', 'password': 'Green-safe62x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'maintenance.cost'], 'areas': None})
        plain, money = self.A.client(), self.A.client()
        plain.login('plain.desk', 'Quiet-room81x')
        money.login('money.desk', 'Green-safe62x')
        wk = lambda c: next(m for m in get_area(c, 'L1')['maintenance'] if m['id'] == 'w0000001')
        self.assertNotIn('cost', wk(plain))
        self.assertEqual(wk(money)['cost'], 1200)
        self.assertEqual(wk(ac)['cost'], 1200, 'administrators see costs')
        m = wk(plain)
        row = {k: v for k, v in m.items() if k != 'ver'}
        plain.post('/api/commit', {'label': 'edit', 'ops': [{'e': 'maintenance', 'id': 'w0000001', 'op': 'put', 'ver': m['ver'],
                                                              'row': {**row, 'areaId': 'L1', 'notes': 'checked', 'cost': 1}}]})
        after = wk(ac)
        self.assertEqual((after['cost'], after['notes']), (1200, 'checked'), 'saving without the right neither wipes nor changes the cost')
        log = json.dumps(plain.get('/api/audit?limit=200')['rows'])
        self.assertNotIn('1200', log)
        self.assertIn('1200', json.dumps(ac.get('/api/audit?limit=200')['rows']))

        # rights: scheduling work does not allow finishing it; completing work may update its plan
        ac.post('/api/users/save', {'username': 'only.create', 'full_name': 'Only Create', 'password': 'Red-brick-77xz', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'maintenance.create'], 'areas': None})
        ac.post('/api/users/save', {'username': 'only.done', 'full_name': 'Only Done', 'password': 'Blue-glass-58xz', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'maintenance.complete'], 'areas': None})
        creator, finisher = self.A.client(), self.A.client()
        creator.login('only.create', 'Red-brick-77xz')
        finisher.login('only.done', 'Blue-glass-58xz')
        with self.assertRaises(ApiError) as e:
            creator.post('/api/commit', {'label': 'done by a planner', 'ops': [work('w0000003', cost=None)]})
        self.assertEqual(e.exception.code, 403)
        creator.post('/api/commit', {'label': 'planned', 'ops': [work('w0000003', status='Scheduled', cost=None)]})
        finisher.post('/api/commit', {'label': 'recorded', 'ops': [work('w0000004', cost=None)]})
        ac.post('/api/commit', {'label': 'plan', 'ops': [{'e': 'plans', 'id': 'pl000009', 'op': 'put', 'row': {'areaId': 'L1', 'title': 'Door', 'status': 'Planned', 'maintId': 'w0000003'}}]})
        pl = next(p for p in get_area(finisher, 'L1')['plans'] if p['id'] == 'pl000009')
        finisher.post('/api/commit', {'label': 'plan done', 'ops': [{'e': 'plans', 'id': 'pl000009', 'op': 'put', 'ver': pl['ver'], 'row': {
            **{k: v for k, v in pl.items() if k != 'ver'}, 'areaId': 'L1', 'status': 'Done', 'doneDate': '2026-09-30'}}]})

        # cancelled here, done there: done wins everywhere
        ac.post('/api/commit', {'label': 'w2', 'ops': [work('w0000002', status='Scheduled', cost=None)]})
        self.converged()
        m1, m2 = wk(ac) and next(m for m in get_area(ac, 'L1')['maintenance'] if m['id'] == 'w0000002'), next(m for m in get_area(pc1, 'L1')['maintenance'] if m['id'] == 'w0000002')
        put = lambda m, **kw: {'e': 'maintenance', 'id': 'w0000002', 'op': 'put', 'ver': m['ver'], 'row': {**{k: v for k, v in m.items() if k != 'ver'}, 'areaId': 'L1', **kw}}
        self.unplug(1)
        ac.post('/api/commit', {'label': 'cancel', 'ops': [put(m1, status='Cancelled', notes='not needed')]})
        pc1.post('/api/commit', {'label': 'done', 'ops': [put(m2, status='Done', doneDate='2026-09-30')]})
        self.plug(1)
        self.converged()
        for c in (ac, pc1):
            self.assertEqual(next(m for m in get_area(c, 'L1')['maintenance'] if m['id'] == 'w0000002')['status'], 'Done')


class T41_UpgradeKeepsData(unittest.TestCase):
    """Version 2.6 (owner's request): after an update everything the people saved with the OLD program is there, unchanged.
    The real previous releases are started from git on a data folder, filled through their own API, stopped, and the
    current program is started on the same folder. Needs the git history (CI checks out everything)."""
    RELEASES = {'2.6.0': '2c5dc66', '2.5.0': 'a8c8c63', '2.4.0': '5f5b3ce'}

    def old_program(self, commit):
        import subprocess
        import tarfile
        import io
        dest = tempfile.mkdtemp(prefix='bams-old-')
        try:
            out = subprocess.run(['git', 'archive', commit, 'server', 'js', 'css', 'index.html', 'config.json'], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 capture_output=True, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            shutil.rmtree(dest, ignore_errors=True)
            self.skipTest('the git history of ' + commit + ' is not available')
        tarfile.open(fileobj=io.BytesIO(out)).extractall(dest)
        return dest

    def content(self, c):
        """Everything the screens show, without version counters."""
        st = c.get('/api/state')

        def clean(x):
            if isinstance(x, dict):
                return {k: clean(v) for k, v in x.items() if k != 'ver'}
            if isinstance(x, list):
                return [clean(v) for v in x]
            return x
        return clean({'areas': st['areas'], 'history': st['history'], 'itemTypes': st['itemTypes'], 'settings': st['settings']})

    def subset(self, old, new, where='state'):
        """Every old value is still there with the same value (new fields may exist, empty)."""
        if isinstance(old, dict):
            self.assertIsInstance(new, dict, where)
            for k, v in old.items():
                self.assertIn(k, new, f'{where}.{k} was lost')
                self.subset(v, new[k], f'{where}.{k}')
        elif isinstance(old, list):
            self.assertEqual(len(old), len(new), f'{where}: number of records changed')
            key = lambda x: json.dumps(x.get('id') if isinstance(x, dict) else x, sort_keys=True)
            for o, n in zip(sorted(old, key=key), sorted(new, key=key)):
                self.subset(o, n, f'{where}[{key(o)}]')
        else:
            self.assertEqual(old, new, where)

    def test_update_from_previous_releases(self):
        for version, commit in self.RELEASES.items():
            with self.subTest(version=version):
                program = self.old_program(commit)
                s = Server('upg-' + version, app=os.path.join(program, 'server', 'app.py')).start()
                try:
                    c = make_authority(s)
                    chairs = {'e': 'itemTypes', 'id': 'chairs', 'op': 'put', 'row': {'name': 'Chairs', 'short': 'Chair', 'icon': 'chair'}}
                    c.post('/api/commit', {'label': 'old data', 'ops': [chairs, area_op('U1', 'Upgrade One', building='Main', floor='Floor 2', capacity=30),
                                                                         area_op('U2', 'Upgrade Two')]})
                    move(c, 'U1', 'chairs', 12)
                    c.post('/api/commit', {'label': 'more', 'ops': [
                        {'e': 'issues', 'id': 'i1', 'op': 'put', 'row': {'areaId': 'U1', 'title': 'Loose leg', 'status': 'Open', 'priority': 'High', 'date': '2026-09-01'}},
                        {'e': 'maintenance', 'id': 'm1', 'op': 'put', 'row': {'areaId': 'U1', 'date': '2026-10-01', 'details': 'Repaint', 'status': 'Scheduled', 'assignedTo': 'Team'}},
                        {'e': 'surveys', 'id': 's1', 'op': 'put', 'row': {'areaId': 'U2', 'month': '2026-08', 'department': 'Line 1', 'percentage': 88, 'respondents': 20}},
                        {'e': 'inspections', 'id': 'n1', 'op': 'put', 'row': {'areaId': 'U2', 'date': '2026-09-02', 'by': 'Sara', 'result': 'Pass'}}]})
                    if version >= '2.5':
                        c.post('/api/commit', {'label': 'pieces', 'ops': [{'e': 'pieces', 'id': 'p1', 'op': 'put', 'row': {'areaId': 'U1', 'item': 'chairs', 'serial': 'CH-1', 'date': '2026-09-03'}}]})
                    c.post('/api/users/save', {'username': 'old.user', 'full_name': 'Old User', 'password': 'Keep-me-safe77', 'must_change': False,
                                               'perms': ['dashboard.view', 'areas.view'], 'areas': ['U1']})
                    before = self.content(c)
                    users_before = sorted(u['username'] for u in c.get('/api/users')['users'])
                    s.stop()
                    # the new program on the same data folder
                    s.app = APP
                    s.start()
                    c = s.client()
                    c.login(*ADMIN)
                    self.subset(before, self.content(c), 'after the update')
                    self.assertEqual(sorted(u['username'] for u in c.get('/api/users')['users']), users_before)
                    s.client().login('old.user', 'Keep-me-safe77')
                    info = c.get('/api/data-safety')
                    last = info['history'][0]
                    self.assertTrue(last['verified'])
                    self.assertTrue(last['snapshot'] and info['snapshots'], 'a safety copy was made before the update')
                    self.assertEqual(last['records']['Break Areas'], 2)
                    self.assertTrue(c.post('/api/data-safety/check', {})['ok'])
                    snap = os.path.join(s.data_dir, 'upgrades', last['snapshot'])
                    self.assertTrue(os.path.exists(os.path.join(snap, 'bams.db')) and os.path.exists(os.path.join(snap, 'journal.db')))
                    # the snapshot really is the old data: it opens with plain SQLite and has the areas
                    import sqlite3
                    n = sqlite3.connect(os.path.join(snap, 'bams.db')).execute('SELECT COUNT(*) FROM areas WHERE deleted=0').fetchone()[0]
                    self.assertEqual(n, 2)
                    # one more restart: nothing is updated twice
                    s.stop()
                    s.start()
                    c = s.client()
                    c.login(*ADMIN)
                    self.assertEqual(len(c.get('/api/data-safety')['snapshots']), 1)
                finally:
                    s.cleanup()
                    shutil.rmtree(program, ignore_errors=True)

    def test_data_of_a_newer_program_is_refused_and_untouched(self):
        s = Server('newer').start()
        try:
            make_authority(s)
            s.stop()
            marker = os.path.join(s.data_dir, 'program.json')
            with open(marker) as f:
                m = json.load(f)
            m.update(version='9.9.9', schema=99)
            with open(marker, 'w') as f:
                json.dump(m, f)
            files = {n: hashlib.sha256(open(os.path.join(s.data_dir, n), 'rb').read()).hexdigest() for n in ('bams.db', 'journal.db', 'auth.db')}
            with self.assertRaises(Exception):
                s.start()
            self.assertIn('newer version', open(os.path.join(s.data_dir, 'logs', 'STARTUP_PROBLEM.txt')).read())
            for n, h in files.items():
                self.assertEqual(hashlib.sha256(open(os.path.join(s.data_dir, n), 'rb').read()).hexdigest(), h, n + ' was touched')
            self.assertFalse(os.path.exists(os.path.join(s.data_dir, 'upgrades')))
        finally:
            s.cleanup()


class T42_PlansAndImport(Base):
    """2.6: future plans of a break area (done wins over dropped on two PCs, who may write them) and the Excel import
    (only for people who work with all break areas, bad files are a clear message, nothing is saved by the preview)."""
    N = 2

    def test_plans_and_import(self):
        import excel_import
        import xlsx
        ac, pc1 = self.ac, self.clients[1]
        ac.post('/api/commit', {'label': 'area', 'ops': [area_op('P1', 'Plan One')]})
        self.converged()
        plan = lambda pid, **kw: {'e': 'plans', 'id': pid, 'op': 'put', 'row': {'areaId': 'P1', 'title': 'Repaint next spring', 'priority': 'Medium', 'status': 'Planned',
                                                                               'targetDate': '2027-03-01', 'by': 'x', **kw}}
        ac.post('/api/commit', {'label': 'plan', 'ops': [plan('pl000001')]})
        with self.assertRaises(ApiError) as e:
            ac.post('/api/commit', {'label': 'empty', 'ops': [plan('pl000002', title='  ')]})
        self.assertEqual(e.exception.code, 400)
        self.converged()
        get = lambda c: next(p for p in get_area(c, 'P1')['plans'] if p['id'] == 'pl000001')
        a1, a2 = get(ac), get(pc1)
        put = lambda p, **kw: {'e': 'plans', 'id': 'pl000001', 'op': 'put', 'ver': p['ver'], 'row': {**{k: v for k, v in p.items() if k != 'ver'}, 'areaId': 'P1', **kw}}
        self.unplug(1)
        ac.post('/api/commit', {'label': 'drop', 'ops': [put(a1, status='Dropped')]})
        pc1.post('/api/commit', {'label': 'done', 'ops': [put(a2, status='Done', doneDate='2026-09-30')]})
        self.plug(1)
        self.converged()
        for c in (ac, pc1):
            self.assertEqual((get(c)['status'], get(c)['doneDate']), ('Done', '2026-09-30'))

        # who may write plans / import
        ac.post('/api/users/save', {'username': 'view.only', 'full_name': 'View Only', 'password': 'Calm-morning64', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view'], 'areas': None})
        ac.post('/api/users/save', {'username': 'area.maker', 'full_name': 'Area Maker', 'password': 'Bright-hall58x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'areas.create', 'areas.edit'], 'areas': None})
        ac.post('/api/users/save', {'username': 'one.area', 'full_name': 'One Area', 'password': 'Quiet-lane49x', 'must_change': False,
                                    'perms': ['dashboard.view', 'areas.view', 'areas.create', 'areas.edit'], 'areas': ['P1']})
        viewer, maker, limited = self.A.client(), self.A.client(), self.A.client()
        viewer.login('view.only', 'Calm-morning64')
        maker.login('area.maker', 'Bright-hall58x')
        limited.login('one.area', 'Quiet-lane49x')
        with self.assertRaises(ApiError) as e:
            viewer.post('/api/commit', {'label': 'no', 'ops': [plan('pl000003')]})
        self.assertEqual(e.exception.code, 403)
        data = xlsx.build([(n, h, r) for n, (h, r) in excel_import.TEMPLATE.items()])
        for c, code in ((viewer, 403), (limited, 403)):
            with self.assertRaises(ApiError) as e:
                c.call('POST', '/api/import/preview', raw=data, headers={'Content-Type': 'application/octet-stream'})
            self.assertEqual(e.exception.code, code)
        before = len(ac.get('/api/state')['areas'])
        res = maker.call('POST', '/api/import/preview', raw=data, headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(res['counts']['areas'], 2)
        self.assertEqual(len(ac.get('/api/state')['areas']), before, 'the preview saves nothing')
        with self.assertRaises(ApiError) as e:
            maker.call('POST', '/api/import/preview', raw=b'this is not an excel file' * 10, headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(e.exception.code, 400)
        self.assertIn('Excel', e.exception.msg)


class T43_NewPcTrap(unittest.TestCase):
    """The field report: the administrator made a user with a user name and password, the person installed the program on their
    own PC - and saw no data. A PC that is not joined is a separate system. The screens now explain it, the address is checked before
    joining, and a PC that was set up alone by mistake can be moved into the company system without losing anything."""

    def test_separate_pc_then_join_the_company_system(self):
        import glob
        A, B = Server('company').start(), Server('mistake').start()
        try:
            ac = make_authority(A)
            ac.post('/api/users/save', {'username': 'sara.m', 'full_name': 'Sara Mostafa', 'password': 'Desk-lamp-5531', 'must_change': False,
                                        'perms': ['dashboard.view', 'areas.view', 'equipment.view'], 'areas': None})
            ac.post('/api/commit', {'label': 'data', 'ops': [area_op('C1', 'Company Canteen')]})
            # the person installed the program and chose "first PC": a separate system that does not know the user
            bc = make_authority(B)
            bc.post('/api/commit', {'label': 'own', 'ops': [area_op('S1', 'Own Mistake Area')]})
            with self.assertRaises(ApiError):
                B.client().login('sara.m', 'Desk-lamp-5531')
            # only this PC alone may leave; the company PC (which will have a member) may not
            self.assertEqual(bc.get('/api/devices')['summary']['state'], 'single')
            viewer_c = B.client()
            with self.assertRaises(ApiError) as e:
                viewer_c.post('/api/node/leave', {})
            self.assertIn(e.exception.code, (401, 403), 'not without logging in')
            res = bc.post('/api/node/leave', {})
            self.assertTrue(res['restart'] and res['backup'])
            B.stop()
            B.start()
            st = B.client().get('/api/auth/status')
            self.assertFalse(st['hasUsers'], 'the PC starts empty, ready to join')
            copied = glob.glob(os.path.join(B.data_dir, 'copied-*'))
            self.assertEqual(len(copied), 1)
            self.assertTrue(os.path.exists(os.path.join(copied[0], 'bams.db')), 'its own data is kept, not deleted')
            # the join screen checks the address first
            b = B.client()
            self.assertTrue(b.post('/api/join/probe', {'address': A.sync_address})['ok'])
            with self.assertRaises(ApiError) as e:
                b.post('/api/join/probe', {'address': '127.0.0.1:1'})
            self.assertEqual(e.exception.code, 400)
            self.assertIn('administrator PC', e.exception.msg)  # (on one machine the fallback port is this PC itself: 'not the administrator PC'; elsewhere 'Nothing answers')
            with self.assertRaises(ApiError) as e:
                b.post('/api/join/probe', {'address': 'has spaces in it'})
            self.assertEqual(e.exception.code, 400)
            b.post('/api/join', {'address': A.sync_address, 'code': '', 'name': 'Sara PC'})
            wait_until(lambda: B.client().get('/api/auth/status')['hasUsers'], 40, what='accounts on the joined PC')
            c = B.client()
            c.login('sara.m', 'Desk-lamp-5531')
            wait_until(lambda: [a['name'] for a in c.get('/api/state')['areas']] == ['Company Canteen'], 40, what='company data on the joined PC')
            # now the company PC has a member and cannot be moved away by mistake
            with self.assertRaises(ApiError) as e:
                ac.post('/api/node/leave', {})
            self.assertEqual(e.exception.code, 403)
        finally:
            A.cleanup()
            B.cleanup()


def page_of(base, path='/'):
    """(status, Location, body) of one GET, without following a redirect."""
    import http.client
    from urllib.parse import urlparse
    u = urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    try:
        c.request('GET', path)
        r = c.getresponse()
        return r.status, r.getheader('Location'), r.read().decode('utf-8', 'replace')
    finally:
        c.close()


def local_post(c, path, body):
    """A POST like the browser on the PC itself sends it (with Origin)."""
    return c.call('POST', path, body, headers={'Origin': c.base})


class T44_OfficeMode(unittest.TestCase):
    """The field report after 2.6: in the office only the web address of the administrator PC can be reached (personal links work,
    "Join" never connects - the sharing port is blocked). A PC in office mode keeps no data and opens the administrator PC like a
    personal link: the person logs in there with user name and password and sees the company data."""

    def test_new_pc_uses_the_office_system(self):
        A, B = Server('office-admin').start(), Server('office-desk').start()
        try:
            ac = make_authority(A)
            ac.post('/api/users/save', {'username': 'sara.m', 'full_name': 'Sara Mostafa', 'password': 'Desk-lamp-5531', 'must_change': False,
                                        'perms': ['dashboard.view', 'areas.view', 'equipment.view'], 'areas': None})
            ac.post('/api/commit', {'label': 'data', 'ops': [area_op('C1', 'Company Canteen')]})
            b = B.client()
            # the address is checked first: the web address of the administrator PC (what a personal link uses)
            found = local_post(b, '/api/office/probe', {'address': A.base + '/k/some-personal-link'})
            self.assertEqual((found['role'], found['url']), ('authority', A.base + '/'))
            for bad, why in (('127.0.0.1:1', 'Nothing answers'), (B.base, 'this PC'), ('has spaces', 'address of the administrator PC'),
                             ('127.0.0.1:' + str(A.sync_port), 'Nothing answers')):  # the sharing port is not a web address
                with self.assertRaises(ApiError, msg=bad) as e:
                    local_post(b, '/api/office/probe', {'address': bad})
                self.assertEqual(e.exception.code, 400, bad)
                self.assertIn(why, e.exception.msg, bad)
            with self.assertRaises(ApiError) as e:  # never on a PC that is already set up
                local_post(ac, '/api/office/use', {'address': B.base})
            self.assertEqual(e.exception.code, 403)
            # review finding: a web page whose name was switched to 127.0.0.1 (DNS rebinding) or a request without the page's Origin
            # must not choose the address (it could send everybody to a fake login page)
            with self.assertRaises(ApiError) as e:
                b.post('/api/office/use', {'address': A.base})
            self.assertEqual(e.exception.code, 403, 'no Origin')
            import http.client
            c = http.client.HTTPConnection('127.0.0.1', B.port, timeout=30)
            c.request('POST', '/api/office/use', json.dumps({'address': A.base}),
                      {'Host': f'evil.example:{B.port}', 'Origin': f'http://evil.example:{B.port}', 'Content-Type': 'application/json'})
            self.assertEqual(c.getresponse().status, 403, 'DNS rebinding: Host is not this PC')
            c.close()
            r = local_post(b, '/api/office/use', {'address': A.base.split('//')[1]})
            self.assertEqual(r['url'], A.base + '/')
            with open(B.cfg_path) as f:
                self.assertEqual(json.load(f)['office_url'], A.base + '/', 'remembered in config.json of this PC')
            # the program on this PC is now only the small page that sends the browser to the administrator PC
            wait_until(lambda: page_of(B.base)[1] == A.base + '/', 20, what='office redirect on ' + B.name)
            self.assertEqual(page_of(B.base, '/api/auth/status')[0], 404, 'no system (no data) on this PC any more')
            # the person logs in on the administrator PC with user name and password and sees the company data
            s = A.client()
            s.login('sara.m', 'Desk-lamp-5531')
            self.assertEqual([a['name'] for a in s.get('/api/state')['areas']], ['Company Canteen'])
            # the administrator PC is off: a plain message with "Try again" and a way to correct the address
            A.stop()
            code, loc, body = page_of(B.base)
            self.assertEqual((code, loc), (200, None))
            self.assertIn('cannot be opened right now', body)
            self.assertIn('Try again', body)
            # a restart of the PC: the installed program starts only the small page (python server/office.py here)
            B.stop()
            B.app = os.path.join(os.path.dirname(APP), 'office.py')
            B.proc = None
            import subprocess
            import sys
            import threading
            env = dict(os.environ, BAMS_CONFIG=B.cfg_path, PYTHONUNBUFFERED='1')
            B.proc = subprocess.Popen([sys.executable, B.app, '--no-browser'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            threading.Thread(target=B._drain, args=(B.proc,), daemon=True).start()
            A.start()
            wait_until(lambda: page_of(B.base)[1] == A.base + '/', 30, what='office redirect after a restart')
            # the background start with Windows does nothing in office mode (nothing to share)
            done = subprocess.run([sys.executable, B.app, '--background'], env=env, timeout=30)
            self.assertEqual(done.returncode, 0)
        finally:
            A.cleanup()
            B.cleanup()

    def test_pc_set_up_alone_moves_to_the_office_system(self):
        A, C = Server('office-admin2').start(), Server('alone').start()
        try:
            make_authority(A)
            cc = make_authority(C)
            cc.post('/api/commit', {'label': 'own', 'ops': [area_op('S1', 'Own Mistake Area')]})
            with self.assertRaises(ApiError) as e:
                C.client().post('/api/node/office', {'address': A.base})
            self.assertIn(e.exception.code, (401, 403), 'not without logging in')
            with self.assertRaises(ApiError) as e:  # the new-PC route is closed on a PC that is set up
                local_post(cc, '/api/office/use', {'address': A.base})
            self.assertEqual(e.exception.code, 403)
            import socket as so
            alias = so.gethostbyname(so.gethostname())  # another address of this PC: it must not point to itself
            for me in (f'{alias}:{C.port}', f'127.0.0.2:{C.port}'):
                with self.assertRaises(ApiError, msg=me) as e:
                    local_post(cc, '/api/node/office?check=1', {'address': me})
                self.assertIn(e.exception.code, (400,), me)
            found = local_post(cc, '/api/node/office?check=1', {'address': A.base})  # the live check of the address while typing
            self.assertEqual(found['role'], 'authority')
            self.assertEqual(page_of(C.base, '/api/auth/status')[0], 200, 'checking does not switch')
            before = os.path.getsize(os.path.join(C.data_dir, 'bams.db'))
            r = local_post(cc, '/api/node/office', {'address': A.base})
            self.assertEqual(r['url'], A.base + '/')
            wait_until(lambda: page_of(C.base)[1] == A.base + '/', 20, what='office redirect on ' + C.name)
            self.assertTrue(os.path.getsize(os.path.join(C.data_dir, 'bams.db')) >= before, 'its own data is kept, not deleted')
            self.assertTrue(any('pre-office' in n for n in os.listdir(os.path.join(C.root, 'backups', 'db'))), 'a backup is made first')
        finally:
            A.cleanup()
            C.cleanup()

    def test_admin_pc_with_other_pcs_stays(self):
        A, B = Server('office-admin3').start(), Server('member3').start()
        try:
            ac = make_authority(A)
            pair(ac, A, B)
            with self.assertRaises(ApiError) as e:
                local_post(ac, '/api/node/office', {'address': B.base})
            self.assertEqual(e.exception.code, 403, 'a PC that shares with others must keep running the system')
        finally:
            A.cleanup()
            B.cleanup()
