"""End-to-end scenarios with real server processes (see TASKS.md for the numbered list).
Each PC is a separate process with its own data folder and ports; some connections go through a
TCP proxy that the test can cut to simulate network failures."""
import hashlib
import json
import os
import sqlite3
import time
import unittest

from harness import ADMIN, ApiError, Server, TcpProxy, make_authority, pair, wait_until


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
        v.get('/api/audit')  # the data-changes log stays available with logs.view

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

    def test_g_revoke(self):
        """Removing a PC: it cannot sync any more; its earlier work stays."""
        ac = self.ac
        self.clients[2].post('/api/commit', {'label': 'before revoke', 'ops': [area_op('RV', 'Before revoke')]})
        self.converged()
        ac.post('/api/devices/revoke', {'id': self.servers[2].node_id})
        wait_until(lambda: any(a['kind'] == 'revoked' for a in self.clients[2].get('/api/devices')['alerts']), 30, what='revocation seen')
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
        """22-23. Upload on one PC; the other copies it, verified by SHA-256, also after an interrupted transfer."""
        data = os.urandom(900_000)
        self.proxies[0].cut_after = 300_000  # downloads from the administrator PC break after 300 kB
        up = self.ac.call('POST', '/api/upload?name=big.jpg', raw=data, headers={'Content-Type': 'application/octet-stream'})
        self.assertTrue(up['src'].startswith('/files/cas/'))
        self.ac.post('/api/commit', {'label': 'photo', 'ops': [area_op('P1', 'Photo area'),
                                                              {'e': 'photos', 'id': 'ph1', 'op': 'put', 'row': {'areaId': 'P1', 'src': up['src'], 'main': True}}]})
        wait_until(lambda: get_area(self.clients[1], 'P1'), 30, what='photo row')
        ph = self.clients[1].call('GET', up['src'])
        self.assertIn(b'<svg', ph, 'while the file is missing a placeholder is shown')
        part_dir = os.path.join(self.servers[1].data_dir, 'uploads', '.incoming')
        wait_until(lambda: os.path.isdir(part_dir) and os.listdir(part_dir), 30, what='partial file')
        final = os.path.join(self.servers[1].data_dir, 'uploads', 'cas', os.path.basename(up['src']))
        self.assertFalse(os.path.exists(final), 'a partial file must never be visible as the real file')
        self.proxies[0].cut_after = None
        wait_until(lambda: self.clients[1].call('GET', up['src']) == data, 60, what='file copied')
        self.assertEqual(hashlib.sha256(open(final, 'rb').read()).hexdigest(), os.path.basename(up['src']).split('.')[0])
        self.assertEqual(os.listdir(part_dir), [])
        log = open(os.path.join(self.servers[1].data_dir, 'logs', time.strftime('sync-%Y-%m.jsonl'))).read()
        self.assertIn('"result": "interrupted"', log)

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


if __name__ == '__main__':
    unittest.main()
