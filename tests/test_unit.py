"""Unit tests: crypto, journal rules (chain, forks, duplicates, gaps, authority), fold rules, node identity safety."""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from cluster import Cluster, Peer, enroll_op  # noqa: F401 (sets sys.path)
import ed25519  # noqa: E402
import tlscert  # noqa: E402
from journal import canonical, chash  # noqa: E402
from node import Node  # noqa: E402
from store import Conflict  # noqa: E402

RFC8032 = [
    ('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60', 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', '',
     'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'),
    ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb', '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c', '72',
     '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00'),
    ('c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7', 'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025', 'af82',
     '6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a'),
]


class CryptoTest(unittest.TestCase):
    def test_rfc8032_vectors(self):
        for sk, pk, msg, sig in RFC8032:
            sk, pk, msg, sig = map(bytes.fromhex, (sk, pk, msg, sig))
            self.assertEqual(ed25519.public_key(sk), pk)
            self.assertEqual(ed25519.sign(sk, msg), sig)
            self.assertTrue(ed25519.verify(pk, msg, sig))

    def test_rejects_tampering(self):
        sk = ed25519.generate()
        pk = ed25519.public_key(sk)
        sig = ed25519.sign(sk, b'hello')
        self.assertFalse(ed25519.verify(pk, b'hellO', sig))
        for i in (0, 31, 32, 63):
            bad = bytearray(sig)
            bad[i] ^= 1
            self.assertFalse(ed25519.verify(pk, b'hello', bytes(bad)))
        self.assertFalse(ed25519.verify(pk, b'hello', b'\x00' * 64))
        self.assertFalse(ed25519.verify(b'\x01' * 32, b'hello', sig))

    def test_certificate_handshake(self):
        import socket
        import ssl
        import threading
        seed = ed25519.generate()
        cert, key, fp = tlscert.make_cert(seed, 'x', 7)
        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, 'c'), 'w').write(cert)
            open(os.path.join(d, 'k'), 'w').write(key)
            sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            sctx.load_cert_chain(os.path.join(d, 'c'), os.path.join(d, 'k'))
            srv = socket.socket()
            srv.bind(('127.0.0.1', 0))
            srv.listen(1)

            def serve():
                s, _ = srv.accept()
                t = sctx.wrap_socket(s, server_side=True)
                t.sendall(b'ok')
                t.close()
            threading.Thread(target=serve, daemon=True).start()
            cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            cctx.check_hostname = False
            cctx.verify_mode = ssl.CERT_NONE
            t = cctx.wrap_socket(socket.create_connection(srv.getsockname()))
            self.assertEqual(tlscert.fingerprint_der(t.getpeercert(True)), fp)
            self.assertEqual(t.recv(2), b'ok')
            self.assertIn(t.version(), ('TLSv1.3', 'TLSv1.2'))
            t.close()
        finally:
            shutil.rmtree(d)


class JournalRulesTest(unittest.TestCase):
    def setUp(self):
        self.c = Cluster(3)
        self.a, self.b, self.x = self.c.peers

    def tearDown(self):
        self.c.close()

    def area(self, peer, aid, **kw):
        return peer.commit('t', [{'e': 'areas', 'id': aid, 'op': 'put', 'row': {'name': aid, **kw}}])

    def test_duplicates_and_out_of_order(self):
        for i in range(5):
            self.area(self.a, f'a{i}')
        recs, _ = self.a.journal.changes_since(self.b.journal.vv())
        fp_before = self.b.store.fingerprint()
        acc, deferred, _ = self.b.receive(recs[2:])  # the first ones are missing: everything waits
        self.assertEqual((len(acc), deferred), (0, len(recs) - 2))
        acc, deferred, _ = self.b.receive(list(reversed(recs)))  # complete but newest first: put in order and taken
        self.assertEqual((len(acc), deferred), (len(recs), 0))
        for _ in range(6):
            self.b.receive(list(reversed(recs)) + recs)  # duplicates in every delivery
        self.assertEqual(self.b.store.fingerprint(), self.a.store.fingerprint())
        self.assertNotEqual(fp_before, self.b.store.fingerprint())
        n = self.b.journal.stats()['changes']
        self.b.receive(recs * 10)
        self.assertEqual(self.b.journal.stats()['changes'], n, 'receiving again changes nothing')

    def test_forged_admin_change_rejected_everywhere(self):
        # pc1 (not the administrator PC) makes itself an administrator with its own key
        evil = self.b.journal.build('data', [], actor='x')  # noqa: F841 - only to reserve nothing
        env_ops = [{'e': 'users', 'id': 'u-evil', 'op': 'insert',
                    's': {'username': 'evil', 'full_name': 'Evil', 'pw_hash': 'x', 'perms': ['users.manage'], 'active': True}}]
        with self.b.journal.lock:
            rec = self.b.journal.build('admin', env_ops, actor='evil')  # no authority key: signed only by pc1
            rec['asig'] = rec['sig']  # pretend
            self.b.journal.append_local(rec)
        acc, _, _ = self.c.deliver(self.b, self.a)
        self.assertEqual([r['status'] for r in acc], ['rejected'])
        self.assertTrue(any(al['kind'] == 'rejected' for al in self.a.journal.alerts()))
        # the chain continues: later honest changes from pc1 still arrive
        self.area(self.b, 'after')
        self.c.converge()
        self.assertIn('after', {x['id'] for x in self.a.state()['areas']})

    def test_account_change_only_own_password(self):
        with self.b.journal.lock:
            rec = self.b.journal.build('account', [{'e': 'users', 'id': 'someone-else', 'op': 'update', 's': {'pw_hash': 'x'}}], actor_id='me')
            self.b.journal.append_local(rec)
            ok = self.b.journal.build('account', [{'e': 'users', 'id': 'me', 'op': 'update', 's': {'pw_hash': 'y', 'must_change': False}}], actor_id='me')
            self.b.journal.append_local(ok)
            perms = self.b.journal.build('account', [{'e': 'users', 'id': 'me', 'op': 'update', 's': {'perms': ['users.manage']}}], actor_id='me')
            self.b.journal.append_local(perms)
        acc, _, _ = self.c.deliver(self.b, self.a)
        self.assertEqual([r['status'] for r in acc], ['rejected', 'ok', 'rejected'])

    def test_data_change_cannot_touch_accounts(self):
        with self.b.journal.lock:
            rec = self.b.journal.build('data', [{'e': 'nodes', 'id': 'n', 'op': 'insert', 's': {'pub': 'aa'}}])
            self.b.journal.append_local(rec)
        acc, _, _ = self.c.deliver(self.b, self.a)
        self.assertEqual(acc[0]['status'], 'rejected')

    def test_bad_signature_refused(self):
        self.area(self.b, 'sig')
        recs, _ = self.b.journal.changes_since(self.a.journal.vv())
        forged = [dict(r) for r in recs]
        env = json.loads(forged[-1]['b'])
        env['label'] = 'changed by a relay'
        forged[-1]['b'] = canonical(env)
        acc, _, problems = self.a.receive(forged)
        self.assertEqual(len(acc), len(recs) - 1)
        self.assertTrue(problems)
        self.assertTrue(any(al['kind'] == 'signature' for al in self.a.journal.alerts()))

    def test_fork_detected(self):
        self.area(self.b, 'f1')
        self.c.converge()
        # simulate a copied data folder: same identity writes a different change with the same number
        with self.b.journal.lock:
            cseq, h, node = self.b.journal.heads[self.b.node.replica]
            rec = self.b.journal.build('data', [{'e': 'areas', 'id': 'x', 'op': 'insert', 's': {'name': 'x'}}])
        env = dict(rec['env'])
        env['cseq'] = cseq
        env['prev'] = self.b.journal.hash_at(self.b.node.replica, cseq - 1) if cseq > 1 else '0' * 64
        body = canonical(env)
        h2 = chash(body)
        forged = {'b': body, 's': self.b.node.sign(bytes.fromhex(h2)).hex()}
        self.a.receive([forged])
        self.assertTrue(any(al['kind'] == 'fork' for al in self.a.journal.alerts()))

    def test_gap_waits_and_causal_order(self):
        self.area(self.a, 'g1')
        self.c.deliver(self.a, self.b)
        a1 = next(x for x in self.b.state()['areas'] if x['id'] == 'g1')
        self.b.commit('edit', [{'e': 'areas', 'id': 'g1', 'op': 'put', 'ver': a1['ver'], 'row': {'name': 'g1', 'description': 'by b'}}])
        # x receives b's edit before a's insert: it must wait (deps), then apply both
        recs_b, _ = self.b.journal.changes_since(self.x.journal.vv())
        only_b = [r for r in recs_b if json.loads(r['b'])['origin'] == self.b.node.replica]
        acc, deferred, _ = self.x.receive(only_b)
        self.assertEqual(len(acc), 0)
        self.assertEqual(deferred, 1)
        self.c.converge()
        self.assertEqual(next(x for x in self.x.state()['areas'] if x['id'] == 'g1')['description'], 'by b')


class FoldRulesTest(unittest.TestCase):
    def setUp(self):
        self.c = Cluster(2)
        self.a, self.b = self.c.peers

    def tearDown(self):
        self.c.close()

    def get(self, peer, entity, rid):
        st = peer.state()
        if entity == 'areas':
            return next((x for x in st['areas'] if x['id'] == rid), None)
        return next((x for a in st['areas'] for x in a[entity] if x['id'] == rid), None)

    def put(self, peer, entity, rid, ver=None, **row):
        return peer.commit('t', [{'e': entity, 'id': rid, 'op': 'put', 'ver': ver, 'row': row}])

    def test_inspection_dates_latest_wins(self):
        self.put(self.a, 'areas', 'i', name='i')
        self.c.converge()
        a0, b0 = self.get(self.a, 'areas', 'i'), self.get(self.b, 'areas', 'i')
        self.put(self.a, 'areas', 'i', a0['ver'], name='i', lastInspection='2026-09-20', nextInspection='2026-10-20', inspectedBy='A')
        self.put(self.b, 'areas', 'i', b0['ver'], name='i', lastInspection='2026-09-10', nextInspection='2026-10-10', inspectedBy='B')
        self.c.converge()
        for p in self.c.peers:
            x = self.get(p, 'areas', 'i')
            self.assertEqual((x['lastInspection'], x['nextInspection'], x['inspectedBy']), ('2026-09-20', '2026-10-20', 'A'))

    def test_maintenance_done_wins(self):
        self.put(self.a, 'areas', 'm', name='m')
        self.put(self.a, 'maintenance', 'm1', areaId='m', status='Scheduled', details='x')
        self.c.converge()
        ma, mb = self.get(self.a, 'maintenance', 'm1'), self.get(self.b, 'maintenance', 'm1')
        self.put(self.b, 'maintenance', 'm1', mb['ver'], areaId='m', status='Done', details='x', notes='fixed', doneDate='2026-09-26')
        self.put(self.a, 'maintenance', 'm1', ma['ver'], areaId='m', status='In Progress', details='x', notes='started')
        self.c.converge()
        for p in self.c.peers:
            x = self.get(p, 'maintenance', 'm1')
            self.assertEqual((x['status'], x.get('notes'), x.get('doneDate')), ('Done', 'fixed', '2026-09-26'))

    def test_negative_stock_flagged(self):
        self.put(self.a, 'areas', 'n', name='n')
        self.put(self.a, 'inventory', 'n:tv', areaId='n', item='tv', qty=2)
        self.c.converge()
        ia, ib = self.get(self.a, 'inventory', 'n:tv'), self.get(self.b, 'inventory', 'n:tv')
        self.put(self.a, 'inventory', 'n:tv', ia['ver'], areaId='n', item='tv', qty=0)
        self.put(self.b, 'inventory', 'n:tv', ib['ver'], areaId='n', item='tv', qty=0)
        self.c.converge()
        self.assertEqual(self.get(self.a, 'inventory', 'n:tv')['qty'], -2)
        self.assertIn('negative', {x['kind'] for x in self.a.store.conflicts()})

    def test_no_resurrection_by_old_edit(self):
        self.put(self.a, 'areas', 'z', name='z')
        self.c.converge()
        za, zb = self.get(self.a, 'areas', 'z'), self.get(self.b, 'areas', 'z')
        self.a.commit('del', [{'e': 'areas', 'id': 'z', 'op': 'del', 'ver': za['ver']}])
        self.put(self.b, 'areas', 'z', zb['ver'], name='z', description='offline edit')
        self.c.converge()
        for p in self.c.peers:
            self.assertIsNone(self.get(p, 'areas', 'z'))
        # recycle bin restore brings it back including the offline edit
        txn = self.a.store.trash()[0]['txn']
        self.a.store.restore_txn('u', 'ip', txn)
        self.c.converge()
        self.assertEqual(self.get(self.b, 'areas', 'z')['description'], 'offline edit')

    def test_optimistic_version_still_protects_local_edits(self):
        self.put(self.a, 'areas', 'v', name='v')
        v = self.get(self.a, 'areas', 'v')
        self.put(self.a, 'areas', 'v', v['ver'], name='v2')
        with self.assertRaises(Conflict):
            self.put(self.a, 'areas', 'v', v['ver'], name='v3')


class NodeSafetyTest(unittest.TestCase):
    def test_copied_folder_detected(self):
        d = tempfile.mkdtemp()
        try:
            os.environ['BAMS_MACHINE_ID'] = 'pc-one'
            Node(d).create('one')
            self.assertFalse(Node(d).moved)
            os.environ['BAMS_MACHINE_ID'] = 'pc-two'
            self.assertTrue(Node(d).moved)
        finally:
            os.environ.pop('BAMS_MACHINE_ID', None)
            shutil.rmtree(d)

    def test_rolled_back_journal_gets_new_epoch(self):
        from system import System
        d = tempfile.mkdtemp()
        try:
            s = System(d, {}, os.path.join(d, 'uploads'), os.path.join(d, 'bk'), log=lambda m: None)
            s.auth.setup('boss', 'The Boss', 'Strong-pass1', '127.0.0.1')
            s.store.commit('u', 'ip', 'a', [{'e': 'areas', 'id': 'a', 'op': 'put', 'row': {'name': 'a'}}])
            name = s.backups.create('manual')
            replica = s.node.replica
            s.store.commit('u', 'ip', 'b', [{'e': 'areas', 'id': 'b', 'op': 'put', 'row': {'name': 'b'}}])
            s.close()
            shutil.copy(os.path.join(d, 'bk', 'db', 'journal' + name[4:]), os.path.join(d, 'journal.db'))
            for suffix in ('-wal', '-shm'):
                if os.path.exists(os.path.join(d, 'journal.db' + suffix)):
                    os.remove(os.path.join(d, 'journal.db' + suffix))
            s = System(d, {}, os.path.join(d, 'uploads'), os.path.join(d, 'bk'), log=lambda m: None)
            self.assertNotEqual(s.node.replica, replica)
            self.assertTrue(any(a['kind'] == 'rollback' for a in s.journal.alerts()))
            s.store.commit('u', 'ip', 'c', [{'e': 'areas', 'id': 'c', 'op': 'put', 'row': {'name': 'c'}}])
            self.assertTrue(s.journal.verify(True)['ok'])
            s.close()
        finally:
            shutil.rmtree(d)

    def test_interrupted_upgrade_is_repeated(self):
        from make_legacy import build
        import system as sysmod
        d = tempfile.mkdtemp()
        try:
            build(d)
            with sqlite3.connect(os.path.join(d, 'bams.db')) as db:
                before = db.execute('SELECT id, name, deleted FROM areas ORDER BY id').fetchall()
            orig = sysmod.System._boot_logs
            sysmod.System._boot_logs = lambda self: (_ for _ in ()).throw(RuntimeError('power cut'))
            with self.assertRaises(RuntimeError):
                sysmod.System(d, {}, os.path.join(d, 'uploads'), os.path.join(d, 'bk'), log=lambda m: None)
            sysmod.System._boot_logs = orig
            s = sysmod.System(d, {}, os.path.join(d, 'uploads'), os.path.join(d, 'bk'), log=lambda m: None)
            self.assertEqual([tuple(r) for r in s.store.conn.execute('SELECT id, name, deleted FROM areas ORDER BY id')], [tuple(r) for r in before])
            self.assertTrue(s.journal.verify(True)['ok'])
            self.assertTrue(any(f.startswith('journal.incomplete-') for f in os.listdir(d)))
            s.close()
        finally:
            shutil.rmtree(d)


class ToolsTest(unittest.TestCase):
    def test_rebuild_gives_identical_data(self):
        """Disaster recovery: bams.db re-created from the history is exactly the same data."""
        import subprocess
        import sys
        from make_legacy import build
        d = tempfile.mkdtemp()
        try:
            data = os.path.join(d, 'data')
            build(data)
            cfg = os.path.join(d, 'config.json')
            json.dump({'data_dir': data, 'backup_dir': os.path.join(d, 'bk')}, open(cfg, 'w'))
            env = dict(os.environ, BAMS_CONFIG=cfg)
            tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server', 'nodectl.py')
            fp1 = subprocess.run([sys.executable, tool, 'status'], env=env, capture_output=True, text=True).stdout.split('fingerprint:')[1].strip()
            out = subprocess.run([sys.executable, tool, 'rebuild'], env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            fp2 = subprocess.run([sys.executable, tool, 'status'], env=env, capture_output=True, text=True).stdout.split('fingerprint:')[1].strip()
            self.assertEqual(fp1, fp2)
            self.assertEqual(subprocess.run([sys.executable, tool, 'verify'], env=env, capture_output=True).returncode, 0)
        finally:
            shutil.rmtree(d)

    def test_key_export_protection(self):
        import nodectl
        secret = os.urandom(32)
        box = nodectl.seal(secret, 'a long passphrase 1', {'cluster': 'c'})
        self.assertEqual(nodectl.unseal(box, 'a long passphrase 1'), secret)
        with self.assertRaises(ValueError):
            nodectl.unseal(box, 'a long passphrase 2')
        box['ct'] = ('00' if box['ct'][:2] != '00' else '11') + box['ct'][2:]
        with self.assertRaises(ValueError):
            nodectl.unseal(box, 'a long passphrase 1')


if __name__ == '__main__':
    unittest.main()
