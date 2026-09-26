"""In-process multi-PC test helpers: several complete nodes (journal + store + auth) in temporary
folders that exchange changesets by direct function calls - no network, fully controllable."""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'server'))

from journal import Journal  # noqa: E402
from node import Node  # noqa: E402
from store import ENTITIES, Store  # noqa: E402


class Peer:
    def __init__(self, root, name):
        self.dir = os.path.join(root, name)
        os.makedirs(self.dir, exist_ok=True)
        self.node = Node(self.dir).create(name)
        self.journal = Journal(self.dir, self.node, ENTITIES.keys())
        self.store = Store(self.dir)
        self.store.attach(self.journal)
        self.name = name

    def commit(self, label, ops, **kw):
        return self.store.commit('user@' + self.name, '127.0.0.1', label, ops, **kw)

    def state(self):
        return self.store.state()

    def receive(self, records, via='test'):
        acc, deferred, problems = self.journal.receive(records, via)
        self.store.fold_pending()
        return acc, deferred, problems

    def close(self):
        self.journal.conn.close()
        self.store.conn.close()


def enroll_op(n):
    return {'e': 'nodes', 'id': n.id, 'op': 'insert',
            'noaudit': True, 's': {'name': n.name, 'pub': n.pub.hex(), 'cert_fp': n.cert_fp, 'status': 'active', 'address': ''}}


class Cluster:
    def __init__(self, n=3, root=None):
        self.root = root or tempfile.mkdtemp(prefix='bams-cluster-')
        self.peers = [Peer(self.root, f'pc{i}') for i in range(n)]
        auth = self.peers[0]
        auth.node.become_authority()
        for p in self.peers[1:]:
            p.node.join(auth.node.info['cluster_id'], auth.node.info['authority_pub'], auth.node.id)
        auth.journal.write('admin', [enroll_op(p.node) for p in self.peers], actor='admin', label='enrol', authority=True)
        self.converge()

    def deliver(self, src, dst, max_count=None, shuffle=None, duplicate=False):
        recs, _ = src.journal.changes_since(dst.journal.vv(), max_count=max_count or 2000)
        if max_count:
            recs = recs[:max_count]
        if shuffle is not None:
            recs = list(recs)
            shuffle.shuffle(recs)
        if duplicate:
            recs = recs + recs
        return dst.receive(recs, via=src.name)

    def converge(self, peers=None, rounds=50):
        peers = peers or self.peers
        for _ in range(rounds):
            moved = 0
            for a in peers:
                for b in peers:
                    if a is not b:
                        moved += len(self.deliver(a, b)[0])
            if not moved:
                return
        raise AssertionError('no convergence after many rounds')

    def fingerprints(self, peers=None):
        return [p.store.fingerprint() for p in (peers or self.peers)]

    def close(self):
        for p in self.peers:
            p.close()
        shutil.rmtree(self.root, ignore_errors=True)


# ------------------------------------------------------------ random user behaviour (like the web page)
ITEMS = ['chairs', 'tables', 'tv', 'water']


def row_of(obj):
    return {k: v for k, v in obj.items() if k != 'ver'}


def random_action(peer, rnd):
    """One plausible user action on this PC, built from its current state like js/app.js does."""
    st = peer.state()
    areas = st['areas']
    k = rnd.random()
    uid = lambda: '%08x' % rnd.getrandbits(32)  # noqa: E731
    if not areas or k < 0.08:
        aid = 'a' + uid()
        return peer.commit('add area', [{'e': 'areas', 'id': aid, 'op': 'put', 'row': {'name': 'Area ' + aid, 'status': 'Good', 'location': 'Production'}},
                                        {'e': 'inventory', 'id': f'{aid}:chairs', 'op': 'put', 'row': {'areaId': aid, 'item': 'chairs', 'qty': rnd.randint(0, 30)}}])
    a = rnd.choice(areas)
    if k < 0.30:  # inventory movement (+ transaction record)
        item = rnd.choice(ITEMS)
        e = next((x for x in a['inventory'] if x['item'] == item), None)
        prev = e.get('qty', 0) if e else 0
        nxt = max(0, prev + rnd.randint(-5, 8))
        ops = [{'e': 'inventory', 'id': f'{a["id"]}:{item}', 'op': 'put', 'ver': e['ver'] if e else None,
                'row': {**(row_of(e) if e else {}), 'areaId': a['id'], 'item': item, 'qty': nxt, 'condition': rnd.choice(['Good', 'Need Repair'])}},
               {'e': 'history', 'id': 'h' + uid(), 'op': 'put', 'row': {'areaId': a['id'], 'item': item, 'action': 'Added', 'prev': prev, 'next': nxt, 'date': '2026-09-01'}}]
        return peer.commit('move', ops)
    if k < 0.50:  # edit fields of the area
        field = rnd.choice(['name', 'status', 'description', 'responsible', 'capacity'])
        val = {'capacity': rnd.randint(1, 99), 'status': rnd.choice(['Good', 'Need Maintenance', 'Under Update'])}.get(field, f'{field}-{uid()}')
        return peer.commit('edit area', [{'e': 'areas', 'id': a['id'], 'op': 'put', 'ver': a['ver'], 'row': {**{x: y for x, y in row_of(a).items() if not isinstance(y, list)}, field: val}}])
    if k < 0.58:  # record an inspection (moves lastInspection)
        d = f'2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}'
        return peer.commit('inspection', [{'e': 'inspections', 'id': 'i' + uid(), 'op': 'put', 'row': {'areaId': a['id'], 'date': d, 'result': 'Pass'}},
                                          {'e': 'areas', 'id': a['id'], 'op': 'put', 'ver': a['ver'],
                                           'row': {**{x: y for x, y in row_of(a).items() if not isinstance(y, list)}, 'lastInspection': d, 'nextInspection': d, 'inspectedBy': peer.name}}])
    if k < 0.66:  # issue + follow up
        if a['issues'] and rnd.random() < 0.6:
            i = rnd.choice(a['issues'])
            return peer.commit('follow up', [{'e': 'issueLog', 'id': 'l' + uid(), 'op': 'put', 'row': {'issueId': i['id'], 'text': 'note', 'date': '2026-09-02'}},
                                             {'e': 'issues', 'id': i['id'], 'op': 'put', 'ver': i['ver'],
                                              'row': {**{x: y for x, y in row_of(i).items() if x != 'log'}, 'areaId': a['id'], 'status': rnd.choice(['Open', 'In Progress', 'Closed'])}}])
        return peer.commit('issue', [{'e': 'issues', 'id': 'is' + uid(), 'op': 'put', 'row': {'areaId': a['id'], 'title': 'broken', 'status': 'Open'}}])
    if k < 0.72:  # maintenance schedule / complete
        if a['maintenance'] and rnd.random() < 0.6:
            m = rnd.choice(a['maintenance'])
            return peer.commit('maint', [{'e': 'maintenance', 'id': m['id'], 'op': 'put', 'ver': m['ver'],
                                          'row': {**row_of(m), 'areaId': a['id'], 'status': rnd.choice(['Done', 'In Progress']), 'notes': uid()}}])
        return peer.commit('maint', [{'e': 'maintenance', 'id': 'm' + uid(), 'op': 'put', 'row': {'areaId': a['id'], 'status': 'Scheduled', 'details': 'x'}}])
    if k < 0.78:  # survey
        return peer.commit('survey', [{'e': 'surveys', 'id': 's' + uid(), 'op': 'put',
                                       'row': {'areaId': a['id'], 'month': f'2026-0{rnd.randint(1, 9)}', 'department': 'Line 1', 'percentage': rnd.randint(40, 99)}}])
    if k < 0.83:  # settings
        return peer.commit('settings', [{'e': 'settings', 'id': rnd.choice(['factory', 'satisfactionTarget']), 'op': 'put', 'row': {'value': uid()}}], force=True)
    if k < 0.87 and a['inventory']:  # delete an inventory item
        e = rnd.choice(a['inventory'])
        return peer.commit('del inv', [{'e': 'inventory', 'id': e['id'], 'op': 'del', 'ver': e['ver']}])
    if k < 0.91:  # delete a whole area
        return peer.commit('del area', [{'e': 'areas', 'id': a['id'], 'op': 'del', 'ver': a['ver']}])
    if k < 0.95:  # recycle bin restore
        trash = peer.store.trash()
        if trash:
            return peer.store.restore_txn('user@' + peer.name, '127.0.0.1', rnd.choice(trash)['txn'])
        return None
    # photo main flag switch
    if a['photos'] and rnd.random() < 0.5:
        pick = rnd.choice(a['photos'])['id']
        return peer.commit('main', [{'e': 'photos', 'id': p['id'], 'op': 'put', 'ver': p['ver'], 'row': {**row_of(p), 'areaId': a['id'], 'main': p['id'] == pick}}
                                    for p in a['photos']])
    return peer.commit('photo', [{'e': 'photos', 'id': 'p' + uid(), 'op': 'put', 'row': {'areaId': a['id'], 'caption': 'x', 'main': not a['photos']}}])
