"""Deterministic randomized convergence: partitions, concurrent edits, duplicate, reordered and truncated
delivery; after the network heals every PC must have exactly the same data (same fingerprint)."""
import json
import random
import unittest

from cluster import Cluster, random_action
from store import Conflict


def run_scenario(seed, nodes=4, steps=160):
    rnd = random.Random(seed)
    c = Cluster(nodes)
    try:
        for step in range(steps):
            p = rnd.choice(c.peers)
            try:
                random_action(p, rnd)
            except Conflict:
                pass
            r = rnd.random()
            if r < 0.35:  # partial, messy exchange between two random PCs
                a, b = rnd.sample(c.peers, 2)
                c.deliver(a, b, max_count=rnd.choice([None, 1, 2, 5]), shuffle=rnd if rnd.random() < 0.3 else None,
                          duplicate=rnd.random() < 0.3)
            elif r < 0.40:  # a sub-group heals
                c.converge(rnd.sample(c.peers, rnd.randint(2, nodes)))
        c.converge()
        fps = c.fingerprints()
        report = [p.journal.verify(all_signatures=True) for p in c.peers]
        conflicts = [json.dumps([{**x, 'row': {k: v for k, v in (x.get('row') or {}).items() if k != 'ver'}} for x in p.store.conflicts()], sort_keys=True)
                     for p in c.peers]
        return c, fps, report, conflicts
    except Exception:
        c.close()
        raise


class ConvergenceTest(unittest.TestCase):
    def test_random_seeds(self):
        for seed in (1, 2, 3, 7, 42, 1234):
            with self.subTest(seed=seed):
                c, fps, report, conflicts = run_scenario(seed)
                try:
                    self.assertEqual(len(set(fps)), 1, f'seed {seed}: PCs disagree')
                    self.assertTrue(all(r['ok'] for r in report), report)
                    self.assertEqual(len(set(conflicts)), 1, 'conflict lists differ between PCs')
                    for p in c.peers:
                        self.assertEqual(p.store.folder.problems, [])
                    # inventory quantity = sum of every movement ever made (nothing overwritten)
                    self.assert_counters(c)
                finally:
                    c.close()

    def assert_counters(self, c):
        totals = {}
        p = c.peers[0]
        for env, status in p.journal.iter_after({}):
            if status != 'ok':
                continue
            for op in env['ops']:
                if isinstance(op, dict) and op.get('e') == 'inventory':
                    totals[op['id']] = totals.get(op['id'], 0) + (op.get('n') or {}).get('qty', 0)
        rows = {r['id']: r['qty'] for r in p.store.conn.execute('SELECT id, qty FROM inventory')}
        for rid, total in totals.items():
            self.assertEqual(rows.get(rid) or 0, total, rid)


if __name__ == '__main__':
    unittest.main()
