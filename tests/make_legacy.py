"""Builds a data folder exactly like version 1 (single server) produced it, using the version-1 code from git
(`git show 104e5a5:server/...`). Used by the upgrade tests."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1 = '104e5a5'  # last commit before the multi-PC version


def legacy_modules(dest):
    os.makedirs(dest, exist_ok=True)
    for f in ('store', 'auth', 'backup'):
        src = subprocess.run(['git', '-C', ROOT, 'show', f'{V1}:server/{f}.py'], capture_output=True, check=True, text=True).stdout
        with open(os.path.join(dest, f'v1_{f}.py'), 'w', encoding='utf-8') as fh:
            fh.write(src.replace('from store import', 'from v1_store import'))


def build(data_dir):
    """A v1 installation with an administrator, a data-entry user, sample-like data, a deleted area, uploads and logs."""
    code = tempfile.mkdtemp(prefix='bams-v1code-')
    legacy_modules(code)
    script = r'''
import os, sys, json
sys.path.insert(0, sys.argv[1])
from v1_store import Store
from v1_auth import Auth, ROLES
d = sys.argv[2]
s = Store(d); a = Auth(d, {})
a.setup('ayman', 'Ayman Essam', 'Secret-pass1', '127.0.0.1')
admin = a._user(a.conn.execute("SELECT * FROM users WHERE username='ayman'").fetchone())
a.save_user(admin, '127.0.0.1', {'username': 'sara', 'full_name': 'Sara Mostafa', 'perms': ROLES['Data Entry'], 'password': 'Other-pass2', 'must_change': False})
a.login('ayman', 'bad-password', '10.0.0.5') if False else None
try: a.login('sara', 'wrong-password1', '10.0.0.7')
except Exception: pass
up = os.path.join(d, 'uploads', '2026-09'); os.makedirs(up, exist_ok=True)
open(os.path.join(up, 'abc123.jpg'), 'wb').write(b'\xff\xd8\xff' + os.urandom(3000))
open(os.path.join(up, 'doc1.pdf'), 'wb').write(b'%PDF-1.4 ' + os.urandom(2000))
ops = [{'e': 'settings', 'id': 'systemName', 'op': 'put', 'row': {'value': 'BAMS Test'}},
       {'e': 'settings', 'id': 'locations', 'op': 'put', 'row': {'value': ['Production', 'Admin']}},
       {'e': 'itemTypes', 'id': 'chairs', 'op': 'put', 'row': {'name': 'Chairs', 'short': 'Chair', 'icon': 'chair'}}]
for i in range(1, 6):
    aid = 'ba%02d' % i
    ops += [{'e': 'areas', 'id': aid, 'op': 'put', 'row': {'name': 'Break Area %02d' % i, 'location': 'Production', 'status': 'Good', 'capacity': 20 + i, 'size': 60.5}},
            {'e': 'inventory', 'id': aid + ':chairs', 'op': 'put', 'row': {'areaId': aid, 'item': 'chairs', 'qty': 10 * i, 'condition': 'Good'}},
            {'e': 'surveys', 'id': aid + 's1', 'op': 'put', 'row': {'areaId': aid, 'month': '2026-08', 'department': 'Line 1', 'percentage': 80 + i}},
            {'e': 'issues', 'id': aid + 'is', 'op': 'put', 'row': {'areaId': aid, 'title': 'Broken chair', 'status': 'Open'}},
            {'e': 'issueLog', 'id': aid + 'is:0', 'op': 'put', 'row': {'issueId': aid + 'is', 'text': 'reported', 'by': 'x', 'date': '2026-09-01'}},
            {'e': 'history', 'id': 'h%d' % i, 'op': 'put', 'row': {'areaId': aid, 'item': 'chairs', 'action': 'Added', 'prev': 0, 'next': 10 * i, 'seq': i}}]
ops += [{'e': 'photos', 'id': 'ba01p1', 'op': 'put', 'row': {'areaId': 'ba01', 'caption': 'Seating', 'src': '/files/2026-09/abc123.jpg', 'main': True}},
        {'e': 'docs', 'id': 'ba01d1', 'op': 'put', 'row': {'areaId': 'ba01', 'name': 'plan.pdf', 'src': '/files/2026-09/doc1.pdf', 'size': 2009}}]
s.commit('Ayman Essam (ayman)', '127.0.0.1', 'Load data', ops)
st = s.state()
a5 = [x for x in st['areas'] if x['id'] == 'ba05'][0]
s.commit('Ayman Essam (ayman)', '127.0.0.1', 'Delete break area 05', [{'e': 'areas', 'id': 'ba05', 'op': 'del', 'ver': a5['ver']}])
a1 = [x for x in st['areas'] if x['id'] == 'ba01'][0]
s.commit('Sara Mostafa (sara)', '10.0.0.7', 'Edit', [{'e': 'areas', 'id': 'ba01', 'op': 'put', 'ver': a1['ver'], 'row': {**{k: v for k, v in a1.items() if not isinstance(v, list) and k != 'ver'}, 'status': 'Need Maintenance'}}])
s.log_activity('Sara Mostafa (sara)', '10.0.0.7', [{'type': 'click', 'action': 'open', 'target': 'x'}])
s.claim_first_run()
print(json.dumps(s.counts()))
'''
    out = subprocess.run([sys.executable, '-c', script, code, data_dir], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


if __name__ == '__main__':
    print(build(sys.argv[1]))
