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
        # without a proof signed with the old password's key nothing is accepted - not even for one's own account
        self.assertEqual([r['status'] for r in acc], ['rejected', 'rejected', 'rejected'])
        self.assertIn('proof', acc[1]['note'])

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


class ReviewFindingsTest(unittest.TestCase):
    """Regression tests for the independent review findings."""

    def setUp(self):
        self.c = Cluster(3)
        self.a, self.b, self.x = self.c.peers

    def tearDown(self):
        self.c.close()

    def area(self, peer, aid):
        return next((x for x in peer.state()['areas'] if x['id'] == aid), None)

    def put(self, peer, aid, ver=None, **row):
        return peer.commit('t', [{'e': 'areas', 'id': aid, 'op': 'put', 'ver': ver, 'row': {'name': aid, **row}}])

    def test_local_save_between_receive_and_fold(self):
        """A change received (journal) but not yet folded must not count as 'seen' by a local save."""
        self.put(self.a, 'r')
        self.c.converge()
        ra, rb = self.area(self.a, 'r'), self.area(self.b, 'r')
        self.put(self.a, 'r', ra['ver'], lastInspection='2026-02-01', nextInspection='2026-03-01')
        recs, _ = self.a.journal.changes_since(self.b.journal.vv())
        self.b.journal.receive(recs, 'a')              # arrives, not folded yet
        self.put(self.b, 'r', rb['ver'], lastInspection='2026-09-01', nextInspection='2026-10-01')
        self.b.store.fold_pending()
        self.c.converge()
        fps = self.c.fingerprints()
        self.assertEqual(len(set(fps)), 1)
        for p in self.c.peers:
            self.assertEqual(self.area(p, 'r')['lastInspection'], '2026-09-01')
            self.assertIn(('r', 'conflict'), {(k['id'], k['kind']) for k in p.store.conflicts()})

    def test_impossible_change_is_refused_everywhere_and_sync_continues(self):
        with self.b.journal.lock:
            rec = self.b.journal.build('data', [{'e': 'inventory', 'id': 'q', 'op': 'insert', 's': {'item': 'x'}, 'n': {'qty': 10 ** 30}}])
            self.b.journal.append_local(rec)
        self.put(self.b, 'after-bad')
        self.c.converge()
        for p in self.c.peers:
            self.assertIsNotNone(self.area(p, 'after-bad'))
        self.assertEqual(self.a.journal.conn.execute("SELECT status FROM changes WHERE id=?", (rec['env']['id'],)).fetchone()[0], 'rejected')

    def test_follower_fields_travel_with_leader(self):
        self.put(self.a, 'f', inspectedBy='Ann', lastInspection='2026-01-01')
        self.c.converge()
        fa, fb = self.area(self.a, 'f'), self.area(self.b, 'f')
        self.put(self.a, 'f', fa['ver'], inspectedBy='Ann', lastInspection='2026-09-20')   # inspectedBy unchanged
        self.put(self.b, 'f', fb['ver'], inspectedBy='Bob', lastInspection='2026-09-10')
        self.c.converge()
        for p in self.c.peers:
            x = self.area(p, 'f')
            self.assertEqual((x['lastInspection'], x['inspectedBy']), ('2026-09-20', 'Ann'))

    def test_row_kept_after_weak_restore_delete_does_not_vanish_on_edit(self):
        import sqlite3 as sq
        self.put(self.a, 'w')
        self.c.converge()
        # a backup without 'w' is restored on A while B edits 'w'
        bk = os.path.join(self.c.root, 'bk.db')
        sq.connect(bk).execute('CREATE TABLE areas (id TEXT, deleted INTEGER, name TEXT)').connection.commit()
        wb = self.area(self.b, 'w')
        self.a.store.restore_from(bk, 'u', 'ip', 'restore')
        self.put(self.b, 'w', wb['ver'], description='edited on B')
        self.c.converge()
        self.assertIsNotNone(self.area(self.a, 'w'))
        w = self.area(self.x, 'w')
        self.put(self.x, 'w', w['ver'], description='edited later on X')
        self.c.converge()
        for p in self.c.peers:
            self.assertEqual(self.area(p, 'w')['description'], 'edited later on X')

    def test_fingerprint_cache_follows_flag_changes(self):
        self.put(self.a, 'g')
        self.c.converge()
        ga, gb = self.area(self.a, 'g'), self.area(self.b, 'g')
        self.put(self.a, 'g', ga['ver'], description='A')
        self.put(self.b, 'g', gb['ver'], description='B')
        self.c.converge()
        for p in self.c.peers:
            cached = p.store.fingerprint()
            p.store._fp = (None, None)
            self.assertEqual(cached, p.store.fingerprint())


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
            # 'b' was only in the tables, not in the restored journal: it is kept and saved again as a new change
            self.assertIn('b', {a['id'] for a in s.store.state()['areas']})
            self.assertTrue(any('"b"' in r[0] for r in s.journal.conn.execute("SELECT body FROM changes WHERE kind='data'")))
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


class Review231Test(unittest.TestCase):
    """Automatic review after 2.3.0: PC changes signed on two PCs (administrator + backup) end the same everywhere,
    and network drives are refused for the second backup folder."""

    def roster_after(self, envs):
        from journal import Journal
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, pub TEXT, cert_fp TEXT, address TEXT, status TEXT, role TEXT, '
                  'enrolled_at TEXT, enrolled_by TEXT, revoked_at TEXT, revoked_by TEXT, updated_at TEXT, updated_by TEXT, '
                  'revoked_change TEXT, vers TEXT)')
        for env in envs:
            Journal._fold_roster(c, env)
        return {k: v for k, v in dict(c.execute('SELECT * FROM nodes WHERE id=?', ('pc3',)).fetchone()).items()
                if k not in ('vers', 'updated_at', 'updated_by')}

    def test_roster_same_in_any_order(self):
        def env(origin, cseq, hlc, s):
            return {'origin': origin, 'cseq': cseq, 'hlc': hlc, 'ts': '2026-09-27T10:00:00', 'actor': 'Admin',
                    'ops': [{'e': 'nodes', 'id': 'pc3', 'op': 'update', 's': s}]}
        base = env('admin', 1, 100, {'name': 'Store', 'address': '10.0.0.3:8443', 'status': 'active', 'role': 'member'})
        a = env('admin', 2, 205, {'name': 'Store room', 'address': '10.0.0.30:8443'})
        b = env('backup', 7, 210, {'name': 'Stock PC', 'role': 'backup'})
        r = env('backup', 8, 150, {'status': 'revoked', 'revoked_at': 'x', 'revoked_by': 'Deputy'})
        one = self.roster_after([base, a, b, r])
        self.assertEqual(one, self.roster_after([base, r, b, a]))
        self.assertEqual(one, self.roster_after([b, r, a, base]))
        self.assertEqual((one['name'], one['address'], one['role'], one['status']), ('Stock PC', '10.0.0.30:8443', 'backup', 'revoked'))
        late = env('admin', 3, 999, {'status': 'active'})  # a removal is final
        self.assertEqual(self.roster_after([base, r, late])['status'], 'revoked')
        # the same PC removed on two PCs at the same time: same result in both orders, both removals remembered
        r2 = env('admin', 4, 140, {'status': 'revoked', 'revoked_at': 'y', 'revoked_by': 'Admin'})
        x, y = self.roster_after([base, r, r2]), self.roster_after([base, r2, r])
        self.assertEqual(x, y)
        self.assertEqual((x['revoked_by'], x['revoked_change']), ('Admin', 'admin#4 backup#8'))

    def test_upgrade_rebuilds_the_pc_list(self):
        """A 2.3.0 database has no field versions: the PC list is folded again from the history once."""
        from journal import Journal
        from store import ENTITIES
        cl = Cluster(2)
        try:
            a = cl.peers[0]
            pc1 = cl.peers[1].node.id
            a.journal.write('admin', [{'e': 'nodes', 'id': pc1, 'op': 'update', 'noaudit': True, 's': {'name': 'Store room'}}],
                            actor='admin', label='rename', authority=True)
            a.journal.conn.execute("UPDATE nodes SET name='wrong', vers=NULL")
            a.journal.conn.execute('ALTER TABLE nodes DROP COLUMN vers')
            a.journal.conn.close()
            j = Journal(a.dir, a.node, ENTITIES.keys())
            self.assertEqual(j.roster()[pc1]['name'], 'Store room')
            self.assertTrue(j.roster()[pc1]['vers'])
            j.conn.close()
        finally:
            shutil.rmtree(cl.root, ignore_errors=True)

    def test_network_folders_refused(self):
        import backup
        self.assertTrue(backup.network_folder('\\\\fileserver\\share'))
        self.assertTrue(backup.network_folder('//fileserver/share'))
        self.assertTrue(backup.network_folder('Z:\\BAMS', drive_type=lambda root: backup.DRIVE_REMOTE))
        self.assertFalse(backup.network_folder('E:\\BAMS', drive_type=lambda root: 2))  # USB drive
        self.assertFalse(backup.network_folder('/media/usb/BAMS'))


class QuietPcTest(unittest.TestCase):
    """The administrator PC warns about a PC that has not shared its data for several days (once a day), not about others."""

    def test_quiet_pc_warning(self):
        import types
        from datetime import datetime, timedelta
        import sync
        old = (datetime.now() - timedelta(days=5)).isoformat(timespec='seconds')
        new = datetime.now().isoformat(timespec='seconds')
        alerts = []
        status = {'b': {'last_seen': old}, 'c': {'last_seen': new}, 'd': {'last_seen': old}}
        meta = {}
        fake = types.SimpleNamespace(
            QUIET_DAYS=3, node=types.SimpleNamespace(id='a'), peer_status=lambda pid: status.get(pid, {}),
            journal=types.SimpleNamespace(alert=lambda *a, **k: alerts.append((a, k)), meta=lambda k, d=None: meta.get(k, d),
                                          set_meta=lambda k, v: meta.__setitem__(k, v), roster=lambda: {
                'a': {'status': 'active', 'name': 'Admin'}, 'b': {'status': 'active', 'name': 'Store PC'},
                'c': {'status': 'active', 'name': 'HR PC'}, 'd': {'status': 'revoked', 'name': 'Old PC'}}))
        sync.SyncService._quiet_pcs(fake)
        sync.SyncService._quiet_pcs(fake)  # the same day: not again (also after a restart: remembered in the journal)
        self.assertEqual(len(alerts), 1)
        self.assertIn('Store PC', alerts[0][0][1])
        self.assertEqual(alerts[0][1]['key'], 'quiet|b')


class SecondReviewTest(unittest.TestCase):
    """Regressions of the second whole-code review."""

    def test_saved_change_survives_a_failing_note_file(self):
        root = tempfile.mkdtemp()
        try:
            p = Peer(root, 'pc')

            def broken(*a, **k):
                raise OSError('disk full')
            p.node.record_written = broken
            real_alert = p.journal.alert

            def alert_also_fails(*a, **k):
                real_alert(*a, **k)
                raise sqlite3.OperationalError('disk full')
            p.journal.alert = alert_also_fails
            p.commit('add', [{'e': 'areas', 'id': 'A1', 'op': 'put', 'row': {'id': 'A1', 'name': 'One'}}])  # must not raise
            self.assertEqual([a['name'] for a in p.state()['areas']], ['One'])
            self.assertTrue(any(a['kind'] == 'disk' for a in p.journal.alerts()))
            p.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_fold_all_keeps_going(self):
        import types
        import sync
        calls = []

        class Bad:
            def fold_pending(self):
                calls.append('bad')
                raise sqlite3.OperationalError('database is locked')

        class Good:
            def fold_pending(self):
                calls.append('good')
        fake = types.SimpleNamespace(auth=Bad(), store=Good(), log=lambda m: calls.append('log'))
        sync.SyncService.fold_all(fake)
        self.assertEqual(calls, ['bad', 'log', 'good'])

    def test_future_clock_is_not_kept(self):
        import time as _t
        import journal
        c = journal.HLC(0)
        far = int((_t.time() + 30 * 86400) * 1000) << 16
        root = tempfile.mkdtemp()
        try:
            p = Peer(root, 'pc')
            p.commit('x', [{'e': 'areas', 'id': 'A1', 'op': 'put', 'row': {'id': 'A1', 'name': 'One'}}])
            p.journal.conn.execute('UPDATE changes SET hlc=?', (far,))
            p.journal.conn.commit() if p.journal.conn.in_transaction else None
            j2 = journal.Journal(p.dir, p.node, p.journal.business)
            self.assertLess(j2.clock.last >> 16, (_t.time() + 2 * 3600) * 1000)
            j2.conn.close()
            p.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertTrue(c.now() > 0)
