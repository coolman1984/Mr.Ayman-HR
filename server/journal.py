"""The change journal (data/journal.db): the permanent, append-only history of every PC.

Every saved action on any PC becomes one *changeset* (like a git commit):
  * numbered per origin without gaps (cseq 1, 2, 3, ...),
  * chained: it contains the SHA-256 of the previous changeset of the same origin,
  * signed with the Ed25519 key of the PC that made it (admin changes additionally
    with the administrator key),
  * stamped with a hybrid logical clock and the version vector ("deps") of what
    that PC had already seen.

The journal is the source of truth: the business tables (bams.db) and the user
table (auth.db) are rebuilt from it by a deterministic fold (replica.py). Its log
views (data changes, user activity, security events of *all* PCs) never go back in
time: a backup restore does not touch this file.

Changes arriving from other PCs are only accepted in order (per origin exactly
cseq = last + 1), when everything they depend on is already here (causal delivery),
when their hash chain continues ours and when the signatures are valid. Receiving
the same changeset any number of times has no effect.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime

import ed25519

ZERO = '0' * 64
VERSION = 1
DATA_KINDS = ('data', 'restore', 'bootstrap')
KINDS = DATA_KINDS + ('admin', 'account', 'log')
PRIORITY = {'restore': 0, 'data': 1, 'bootstrap': 1, 'account': 2, 'admin': 3}
ACCOUNT_FIELDS = {'pw_hash', 'must_change', 'pw_changed_at'}
ADMIN_ENTITIES = {'users', 'nodes', 'userCommands'}
MAX_CLOCK_AHEAD_MS = 60 * 60 * 1000  # a PC more than 1 hour ahead gets a warning and cannot drag our clock


def now():
    return datetime.now().isoformat(timespec='seconds')


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def chash(body):
    return hashlib.sha256(b'BAMS-CS1\n' + body.encode('utf-8')).hexdigest()


def dominates(deps, origin, cseq, e_origin, e_cseq):
    """True when the changeset (origin, cseq) with version vector deps had already seen (e_origin, e_cseq)."""
    if origin == e_origin:
        return cseq > e_cseq
    return deps.get(e_origin, 0) >= e_cseq


class HLC:
    """Hybrid logical clock: milliseconds << 16 | counter. Never goes backwards."""

    def __init__(self, last=0):
        self.last = last
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            self.last = max(self.last + 1, int(time.time() * 1000) << 16)
            return self.last

    def observe(self, remote):
        """Returns False when the remote clock is far ahead (it is then not adopted)."""
        if (remote >> 16) > time.time() * 1000 + MAX_CLOCK_AHEAD_MS:
            return False
        with self.lock:
            if remote > self.last:
                self.last = remote
        return True


class Journal:
    def __init__(self, data_dir, node, business=(), log=None):
        self.path = os.path.join(data_dir, 'journal.db')
        self.node = node
        self.business = set(business)
        self.log = log or (lambda msg: None)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA busy_timeout=10000')
        ok = self.conn.execute('PRAGMA quick_check').fetchone()[0]
        if ok != 'ok':
            raise RuntimeError(f'The change journal (journal.db) is damaged ({ok}). See DISTRIBUTED_SYNC_ARCHITECTURE.md, disaster recovery.')
        self._schema()
        self.heads = {r['origin']: (r['cseq'], r['hash'], r['node']) for r in self.conn.execute('SELECT * FROM heads')}
        last = self.conn.execute('SELECT MAX(hlc) FROM changes WHERE node=?', (node.id,)).fetchone()[0] if node.exists else 0
        self.clock = HLC(last or 0)
        self._deps_cache = {}
        self._activity = []  # buffered user activity, written as one changeset every minute
        self.listeners = []  # called after new changesets were appended: fn(list of envs)

    def _schema(self):
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS changes (
                lsn INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT NOT NULL, cseq INTEGER NOT NULL, id TEXT NOT NULL,
                node TEXT NOT NULL, hlc INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL,
                sig TEXT NOT NULL, asig TEXT, status TEXT NOT NULL DEFAULT 'ok', note TEXT, received_at TEXT, via TEXT,
                UNIQUE(origin, cseq));
            CREATE TABLE IF NOT EXISTS heads (origin TEXT PRIMARY KEY, node TEXT NOT NULL, cseq INTEGER NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, name TEXT, pub TEXT, cert_fp TEXT, address TEXT, status TEXT, role TEXT,
                enrolled_at TEXT, enrolled_by TEXT, revoked_at TEXT, revoked_by TEXT, updated_at TEXT, updated_by TEXT,
                revoked_change TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, lsn INTEGER, origin TEXT, cseq INTEGER, node TEXT, kind TEXT, ts TEXT,
                txn TEXT, user TEXT, user_id TEXT, ip TEXT, label TEXT, entity TEXT, entity_id TEXT, area_id TEXT, op TEXT,
                changes TEXT, before TEXT, after TEXT);
            CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit(ts);
            CREATE INDEX IF NOT EXISTS ix_audit_area ON audit(area_id);
            CREATE INDEX IF NOT EXISTS ix_audit_oc ON audit(origin, cseq);
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT, lsn INTEGER, origin TEXT, cseq INTEGER, node TEXT, ts TEXT, user TEXT,
                ip TEXT, type TEXT, action TEXT, target TEXT, page TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity(ts);
            CREATE INDEX IF NOT EXISTS ix_activity_oc ON activity(origin, cseq);
            CREATE TABLE IF NOT EXISTS security (
                id INTEGER PRIMARY KEY AUTOINCREMENT, lsn INTEGER, origin TEXT, cseq INTEGER, node TEXT, ts TEXT, user TEXT,
                ip TEXT, event TEXT, target TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS ix_security_ts ON security(ts);
            CREATE INDEX IF NOT EXISTS ix_security_oc ON security(origin, cseq);
            CREATE TABLE IF NOT EXISTS alerts (
                key TEXT PRIMARY KEY, kind TEXT, severity TEXT, node TEXT, detail TEXT, first_ts TEXT, last_ts TEXT,
                count INTEGER DEFAULT 1, acked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sync_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, peer TEXT, event TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS peer_state (node TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS invites (
                id TEXT PRIMARY KEY, secret_hash TEXT, created_at TEXT, expires_at TEXT, used_at TEXT, created_by TEXT);
            CREATE TABLE IF NOT EXISTS join_requests (
                id TEXT PRIMARY KEY, invite_id TEXT, node_id TEXT, name TEXT, pub TEXT, cert_fp TEXT, address TEXT, ip TEXT,
                confirm TEXT, status TEXT, created_at TEXT, decided_at TEXT, decided_by TEXT, secret TEXT);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        ''')
        if 'revoked_change' not in {r[1] for r in self.conn.execute('PRAGMA table_info(nodes)')}:
            self.conn.execute('ALTER TABLE nodes ADD COLUMN revoked_change TEXT')

    # ------------------------------------------------------------ small helpers
    def vv(self):
        with self.lock:
            return {o: h[0] for o, h in self.heads.items()}

    def vv_hashes(self):
        with self.lock:
            return {o: [h[0], h[1]] for o, h in self.heads.items()}

    def meta(self, key, default=None):
        r = self.conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_meta(self, key, value):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

    def roster(self):
        with self.lock:
            return {r['id']: dict(r) for r in self.conn.execute('SELECT * FROM nodes')}

    def hash_at(self, origin, cseq):
        r = self.conn.execute('SELECT hash FROM changes WHERE origin=? AND cseq=?', (origin, cseq)).fetchone()
        return r[0] if r else None

    def deps_of(self, origin, cseq):
        key = (origin, cseq)
        d = self._deps_cache.get(key)
        if d is None:
            r = self.conn.execute('SELECT body FROM changes WHERE origin=? AND cseq=?', (origin, cseq)).fetchone()
            d = json.loads(r[0])['deps'] if r else {}
            if len(self._deps_cache) > 20000:
                self._deps_cache.clear()
            self._deps_cache[key] = d
        return d

    def alert(self, kind, detail, node='', severity='error', key=None):
        key = key or f'{kind}|{node}|{detail[:120]}'
        ts = now()
        with self.lock:
            cur = self.conn.execute('UPDATE alerts SET last_ts=?, count=count+1, acked=0 WHERE key=?', (ts, key)).rowcount
            if not cur:
                self.conn.execute('INSERT INTO alerts (key,kind,severity,node,detail,first_ts,last_ts) VALUES (?,?,?,?,?,?,?)',
                                  (key, kind, severity, node, detail[:2000], ts, ts))
        self.log(f'ALERT {kind} {node}: {detail}')

    def alerts(self, include_acked=False):
        with self.lock:
            q = 'SELECT * FROM alerts' + ('' if include_acked else ' WHERE acked=0') + ' ORDER BY last_ts DESC'
            return [dict(r) for r in self.conn.execute(q)]

    def ack_alert(self, key):
        with self.lock:
            self.conn.execute('UPDATE alerts SET acked=1 WHERE key=?', (key,))

    # ------------------------------------------------------------ writing our own changesets
    def build(self, kind, ops, actor='', actor_id='', ip='', label='', authority=False, ts=None):
        """A new signed changeset of this PC. The caller must hold self.lock until append()."""
        assert kind in KINDS
        origin = self.node.replica
        cseq, prev, _ = self.heads.get(origin, (0, ZERO, None))
        env = {'v': VERSION, 'id': uuid.uuid4().hex, 'origin': origin, 'node': self.node.id, 'cseq': cseq + 1,
               'hlc': self.clock.now(), 'deps': self.vv(), 'kind': kind, 'ts': ts or now(), 'actor': str(actor or '')[:120],
               'actor_id': str(actor_id or ''), 'ip': str(ip or '')[:60], 'label': str(label or '')[:200], 'ops': ops, 'prev': prev}
        body = canonical(env)
        h = chash(body)
        rec = {'env': json.loads(body), 'body': body, 'hash': h, 'sig': self.node.sign(bytes.fromhex(h)).hex(),
               'asig': self.node.sign_authority(bytes.fromhex(h)).hex() if authority else None, 'status': 'ok', 'note': None}
        return rec

    def append_local(self, rec):
        self._append([rec], via=None)
        self.node.record_written(rec['env']['origin'], rec['env']['cseq'])

    def write(self, kind, ops, **kw):
        """Build and append one changeset (for changes that do not touch bams.db)."""
        with self.lock:
            rec = self.build(kind, ops, **kw)
            self.append_local(rec)
        self._notify([rec])
        return rec

    def _notify(self, recs):
        for fn in self.listeners:
            try:
                fn(recs)
            except Exception as e:  # a listener must never break saving
                self.log(f'journal listener failed: {e}')

    # ------------------------------------------------------------ user activity / security events
    def log_security(self, user, ip, event, target='', detail='', ts=None):
        row = {'t': 'security', 'ts': ts or now(), 'user': str(user)[:120], 'ip': ip or '', 'event': str(event)[:40],
               'target': str(target or '')[:200], 'detail': str(detail or '')[:4000]}
        self.write('log', [row], actor=user, ip=ip, label='Security: ' + row['event'])

    def log_activity(self, user, ip, events):
        with self.lock:
            for e in events:
                self._activity.append({'t': 'activity', 'ts': str(e.get('ts') or now())[:19], 'user': str(e.get('user') or user)[:80],
                                       'ip': ip or '', 'type': str(e.get('type') or '')[:30], 'action': str(e.get('action') or '')[:120],
                                       'target': str(e.get('target') or '')[:200], 'page': str(e.get('page') or '')[:120],
                                       'detail': str(e.get('detail') or '')[:2000]})
            full = len(self._activity) >= 200
        if full:
            self.flush_activity()

    def flush_activity(self):
        with self.lock:
            if not self._activity or not self.node.exists:
                return
            events, self._activity = self._activity, []
            self.write('log', events, actor=events[0]['user'], ip=events[0]['ip'], label=f'User activity ({len(events)})')

    # ------------------------------------------------------------ appending (local and received)
    def _append(self, recs, via):
        """Stores changesets, their log view rows and roster changes in ONE transaction."""
        ts = now()
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
                for r in recs:
                    env = r['env']
                    cur = c.execute('INSERT INTO changes (origin,cseq,id,node,hlc,kind,body,hash,sig,asig,status,note,received_at,via) '
                                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                    (env['origin'], env['cseq'], env['id'], env['node'], env['hlc'], env['kind'], r['body'], r['hash'],
                                     r['sig'], r['asig'], r['status'], r['note'], ts, via))
                    lsn = cur.lastrowid
                    c.execute('INSERT OR REPLACE INTO heads VALUES (?,?,?,?)', (env['origin'], env['node'], env['cseq'], r['hash']))
                    for table, row in self.view_rows(env, r['status']):
                        cols = list(row)
                        c.execute(f'INSERT INTO {table} (lsn,{",".join(cols)}) VALUES (?,{",".join("?" * len(cols))})', (lsn, *row.values()))
                    if r['status'] == 'ok' and env['kind'] == 'admin':
                        self._fold_roster(c, env)
                c.execute('COMMIT')
            except Exception:
                c.execute('ROLLBACK')
                self.heads = {x['origin']: (x['cseq'], x['hash'], x['node']) for x in c.execute('SELECT * FROM heads')}
                raise
            for r in recs:
                env = r['env']
                self.heads[env['origin']] = (env['cseq'], r['hash'], env['node'])

    @staticmethod
    def _fold_roster(c, env):
        for op in env['ops']:
            if op.get('e') != 'nodes' or not isinstance(op.get('s'), dict):
                continue
            s = {k: v for k, v in op['s'].items() if k in ('name', 'pub', 'cert_fp', 'address', 'status', 'role', 'enrolled_at',
                                                             'enrolled_by', 'revoked_at', 'revoked_by')}
            if not c.execute('SELECT 1 FROM nodes WHERE id=?', (op['id'],)).fetchone():
                c.execute('INSERT INTO nodes (id) VALUES (?)', (op['id'],))
            if s.get('status') == 'revoked':
                s['revoked_change'] = f'{env["origin"]}#{env["cseq"]}'  # changes that had seen this are refused (see _consider)
            if s:
                c.execute(f'UPDATE nodes SET {", ".join(k + "=?" for k in s)}, updated_at=?, updated_by=? WHERE id=?',
                          (*[str(v) if v is not None else None for v in s.values()], env['ts'], env['actor'], op['id']))

    @staticmethod
    def view_rows(env, status='ok'):
        """The log rows (audit / activity / security) a changeset contributes. Deterministic."""
        base = {'origin': env['origin'], 'cseq': env['cseq'], 'node': env['node']}
        out = []
        if status != 'ok':
            out.append(('security', {**base, 'ts': env['ts'], 'user': env['actor'], 'ip': env['ip'], 'event': 'change-rejected',
                                     'target': env['kind'], 'detail': f'Change {env["origin"]}#{env["cseq"]} was rejected: {status}'}))
            return out
        if env['kind'] == 'log':
            for e in env['ops']:
                if e.get('t') == 'security':
                    out.append(('security', {**base, **{k: e.get(k) for k in ('ts', 'user', 'ip', 'event', 'target', 'detail')}}))
                elif e.get('t') == 'activity':
                    out.append(('activity', {**base, **{k: e.get(k) for k in ('ts', 'user', 'ip', 'type', 'action', 'target', 'page', 'detail')}}))
                elif e.get('t') == 'audit':  # data changes saved before the upgrade to the multi-PC version
                    out.append(('audit', {**base, 'kind': 'imported', **{k: e.get(k) for k in (
                        'ts', 'txn', 'user', 'ip', 'label', 'entity', 'entity_id', 'area_id', 'op', 'changes', 'before', 'after')}, 'user_id': ''}))
            return out
        for op in env['ops']:
            if not isinstance(op, dict) or op.get('noaudit'):
                continue
            red = (lambda d: d) if op.get('e') != 'users' else _redact
            kind = op.get('op') or 'update'
            out.append(('audit', {**base, 'kind': env['kind'], 'ts': env['ts'], 'txn': env['id'], 'user': env['actor'],
                                  'user_id': env['actor_id'], 'ip': env['ip'], 'label': env['label'], 'entity': op.get('e'),
                                  'entity_id': op.get('id'), 'area_id': op.get('a'), 'op': kind,
                                  'changes': canonical(red(op.get('c') or {})),
                                  'before': canonical(red(op['b'])) if op.get('b') else None,
                                  'after': canonical(red(op['r'])) if op.get('r') else None}))
        return out

    # ------------------------------------------------------------ receiving from other PCs
    def receive(self, records, via=''):
        """Validates and stores changesets from another PC. Returns (accepted records, deferred count, problems)."""
        accepted, problems = [], []
        with self.lock:
            heads = {o: (h[0], h[1]) for o, h in self.heads.items()}
            roster = {n['id']: n for n in self.roster().values()}
            batch_hash = {}
            blocked = set()
            pending = []
            for raw in records:
                try:
                    body = raw['b']
                    env = json.loads(body)
                    if canonical(env) != body:
                        raise ValueError('not in canonical form')
                    origin, cseq, node = env['origin'], env['cseq'], env['node']
                    if not isinstance(origin, str) or not isinstance(cseq, int) or not isinstance(node, str) or not origin.startswith(node + '-'):
                        raise ValueError('bad origin')
                except (KeyError, TypeError, ValueError) as e:
                    problems.append(f'unreadable change from {via}: {e}')
                    self.alert('bad-data', f'Unreadable change received from {via}: {e}', via)
                    break
                pending.append((raw, env, body, chash(body)))
            # several passes, so changes that arrive in any order within one delivery are still taken in the right order
            progress = True
            while progress and pending:
                progress, waiting = False, []
                for item in pending:
                    verdict = self._consider(item, heads, roster, batch_hash, blocked, accepted, problems, via)
                    if verdict == 'wait':
                        waiting.append(item)
                    elif verdict == 'accept':
                        progress = True
                pending = waiting
            deferred = len(pending) + sum(1 for x in problems if x.startswith('version'))
            if accepted:
                self._append(accepted, via)
        if accepted:
            self._notify(accepted)
        return accepted, deferred, problems

    def _consider(self, item, heads, roster, batch_hash, blocked, accepted, problems, via):
        """One received changeset: 'accept', 'drop' (duplicate or refused) or 'wait' (something it needs is missing)."""
        raw, env, body, h = item
        origin, cseq, node = env['origin'], env['cseq'], env['node']
        if origin in blocked:
            return 'drop'
        if env.get('v') != VERSION:
            blocked.add(origin)
            problems.append(f'version {origin}')
            self.alert('version', f'A change from PC {node} needs a newer version of this program.', node, 'warning', key=f'version|{node}')
            return 'drop'
        have, have_hash = heads.get(origin, (0, ZERO))
        if cseq <= have:
            known = batch_hash.get((origin, cseq)) or self.hash_at(origin, cseq)
            if known != h:
                blocked.add(origin)
                problems.append(f'fork {origin}#{cseq}')
                self.alert('fork', f'PC {node} has two different histories (change #{cseq}). Its data folder may have been '
                           'copied to another PC or edited.', node, key=f'fork|{origin}')
            return 'drop'
        if cseq != have + 1:
            return 'wait'
        if env.get('prev') != have_hash:
            blocked.add(origin)
            problems.append(f'chain {origin}#{cseq}')
            self.alert('fork', f'The history of PC {node} does not continue the copy stored here (change #{cseq}).', node, key=f'fork|{origin}')
            return 'drop'
        deps = env.get('deps') or {}
        if not isinstance(deps, dict) or any(not isinstance(c, int) or heads.get(o, (0,))[0] < c for o, c in deps.items() if o != origin):
            return 'wait'
        n = roster.get(node)
        if (not n or not n.get('pub')) and env.get('kind') == 'admin' and self._check(env, raw, h) == 'ok':
            # the administrator PC's own first change enrols itself: trust the key it carries
            n = next(({'id': node, **op['s']} for op in env['ops'] if isinstance(op, dict) and op.get('e') == 'nodes'
                      and op.get('id') == node and isinstance(op.get('s'), dict) and op['s'].get('pub')), n)
        if not n or not n.get('pub'):
            return 'wait'
        if not ed25519.verify(bytes.fromhex(n['pub']), bytes.fromhex(h), _unhex(raw.get('s'))):
            blocked.add(origin)
            problems.append(f'signature {origin}#{cseq}')
            self.alert('signature', f'A change said to come from PC {n.get("name") or node} has an invalid signature '
                       f'(received from {via}).', node, key=f'signature|{origin}|{via}')
            return 'drop'
        status = self._check(env, raw, h)
        rc = n.get('revoked_change') if n.get('status') == 'revoked' else None
        if status == 'ok' and rc:
            r_origin, _, r_cseq = rc.rpartition('#')
            if deps.get(r_origin, 0) >= int(r_cseq):  # made by a removed PC after it knew it was removed
                status = 'made by a removed PC after it was removed'
        if status != 'ok':
            self.alert('rejected', f'A change from PC {n.get("name") or node} was refused: {status}', node)
        accepted.append({'env': env, 'body': body, 'hash': h, 'sig': raw.get('s'), 'asig': raw.get('a'),
                         'status': 'ok' if status == 'ok' else 'rejected', 'note': None if status == 'ok' else status})
        heads[origin] = (cseq, h)
        batch_hash[(origin, cseq)] = h
        if status == 'ok' and env['kind'] == 'admin':
            for op in env['ops']:
                if isinstance(op, dict) and op.get('e') == 'nodes' and isinstance(op.get('s'), dict):
                    r = roster.setdefault(op.get('id'), {'id': op.get('id')})
                    r.update(op['s'])
                    if op['s'].get('status') == 'revoked':
                        r['revoked_change'] = f'{origin}#{cseq}'
        if isinstance(env.get('hlc'), int) and not self.clock.observe(env['hlc']):
            self.alert('clock', f'The clock of PC {n.get("name") or node} is more than one hour ahead. Please correct its date '
                       'and time.', node, 'warning', key=f'clock|{node}')
        return 'accept'

    def _check(self, env, raw, h):
        """Rules every PC applies identically, so all PCs accept or refuse the same changes."""
        kind, ops = env.get('kind'), env.get('ops')
        if kind not in KINDS or not isinstance(ops, list):
            return 'unknown kind of change'
        if kind == 'admin':
            pub = self.node.authority_pub
            if not pub or not raw.get('a') or not ed25519.verify(pub, bytes.fromhex(h), _unhex(raw['a'])):
                return 'not signed by the administrator PC'
            return 'ok'
        if kind == 'account':
            for op in ops:
                s = op.get('s') if isinstance(op, dict) else None
                if (op.get('e') != 'users' or op.get('id') != env.get('actor_id') or not isinstance(s, dict) or not s
                        or set(s) - ACCOUNT_FIELDS or s.get('must_change') not in (None, False) or op.get('x') is not None or op.get('n')):
                    return 'a user may only change their own password'
            return 'ok'
        if kind == 'log':
            return 'ok' if all(isinstance(e, dict) and e.get('t') in ('activity', 'security', 'audit') for e in ops) else 'bad log entry'
        for op in ops:
            if not isinstance(op, dict) or op.get('e') not in self.business:
                return 'data change touches something that is not business data'
        return 'ok'

    # ------------------------------------------------------------ serving other PCs
    def changes_since(self, have, max_bytes=2_000_000, max_count=2000):
        """Changesets the other PC lacks (in our journal order = a causal order). Returns (records, more)."""
        with self.lock:
            need = {o: have.get(o, 0) for o, h in self.heads.items() if h[0] > have.get(o, 0)}
            if not need:
                return [], False
            start = None
            for o, c in need.items():
                r = self.conn.execute('SELECT lsn FROM changes WHERE origin=? AND cseq=?', (o, c + 1)).fetchone()
                if r and (start is None or r[0] < start):
                    start = r[0]
            if start is None:
                return [], False
            out, size = [], 0
            for r in self.conn.execute('SELECT origin, cseq, body, sig, asig FROM changes WHERE lsn>=? ORDER BY lsn', (start,)):
                if r['origin'] not in need or r['cseq'] <= need[r['origin']]:
                    continue
                rec = {'b': r['body'], 's': r['sig']}
                if r['asig']:
                    rec['a'] = r['asig']
                if out and (size + len(r['body']) > max_bytes or len(out) >= max_count):
                    return out, True
                out.append(rec)
                size += len(r['body']) + 200
            return out, False

    def pending_for(self, other_vv):
        """How many changesets another PC (with version vector other_vv) is missing."""
        with self.lock:
            return sum(max(0, h[0] - other_vv.get(o, 0)) for o, h in self.heads.items())

    def check_heads(self, other):
        """Compares another PC's head hashes with ours. Returns the origins where the histories differ."""
        bad = []
        with self.lock:
            for o, (c, h) in other.items():
                mine = self.heads.get(o)
                if not mine:
                    continue
                if c <= mine[0]:
                    local = mine[1] if c == mine[0] else self.hash_at(o, c)
                    if local and local != h:
                        bad.append(o)
        return bad

    # ------------------------------------------------------------ reading changesets for the fold
    def iter_after(self, markers, limit=None):
        """(env, status) of the changesets beyond the fold markers {origin: cseq}, in journal order."""
        with self.lock:
            need = {o: markers.get(o, 0) for o, h in self.heads.items() if h[0] > markers.get(o, 0)}
            if not need:
                return []
            start = None
            for o, c in need.items():
                r = self.conn.execute('SELECT lsn FROM changes WHERE origin=? AND cseq=?', (o, c + 1)).fetchone()
                if r and (start is None or r[0] < start):
                    start = r[0]
            rows = self.conn.execute('SELECT body, status FROM changes WHERE lsn>=? ORDER BY lsn', (start or 0,)).fetchall()
        out = []
        for r in rows:
            env = json.loads(r['body'])
            if env['origin'] in need and env['cseq'] > need[env['origin']]:
                out.append((env, r['status']))
                if limit and len(out) >= limit:
                    break
        return out

    def describe(self, origin=None, cseq=None, txn=None):
        """Who/when/where of a changeset (for conflict and recycle bin screens)."""
        with self.lock:
            if txn:
                r = self.conn.execute('SELECT body FROM changes WHERE id=?', (txn,)).fetchone()
            else:
                r = self.conn.execute('SELECT body FROM changes WHERE origin=? AND cseq=?', (origin, cseq)).fetchone()
            if not r:
                return None
            env = json.loads(r[0])
            n = self.conn.execute('SELECT name FROM nodes WHERE id=?', (env['node'],)).fetchone()
        return {'actor': env['actor'], 'ts': env['ts'], 'label': env['label'], 'node': env['node'], 'node_name': n[0] if n else env['node'],
                'kind': env['kind'], 'id': env['id']}

    # ------------------------------------------------------------ integrity verification
    def verify(self, all_signatures=False):
        """Recomputes every hash, every chain link, the log views and the signatures of every head
        (all signatures when all_signatures). Returns a report; problems also become alerts."""
        started = time.time()
        problems, checked = [], 0
        with self.lock:
            roster = self.roster()
            heads = dict(self.heads)
            origins = [r[0] for r in self.conn.execute('SELECT DISTINCT origin FROM changes')]
            for o in set(origins) | set(heads):
                prev, expect, last = ZERO, 1, None
                for r in self.conn.execute('SELECT * FROM changes WHERE origin=? ORDER BY cseq', (o,)):
                    checked += 1
                    where = f'{o}#{r["cseq"]}'
                    if r['cseq'] != expect:
                        problems.append(f'{where}: change #{expect} is missing')
                        expect = r['cseq']
                    expect += 1
                    try:
                        env = json.loads(r['body'])
                    except ValueError:
                        problems.append(f'{where}: unreadable')
                        continue
                    if chash(r['body']) != r['hash']:
                        problems.append(f'{where}: content was changed after it was saved')
                    if env.get('prev') != prev or env.get('origin') != o or env.get('cseq') != r['cseq']:
                        problems.append(f'{where}: chain broken')
                    prev = r['hash']
                    last = r
                    n = roster.get(r['node'])
                    if all_signatures and n and n.get('pub') and not ed25519.verify(bytes.fromhex(n['pub']), bytes.fromhex(r['hash']), bytes.fromhex(r['sig'])):
                        problems.append(f'{where}: invalid signature')
                    if r['kind'] == 'admin' and r['status'] == 'ok':
                        pub = self.node.authority_pub
                        if not pub or not r['asig'] or not ed25519.verify(pub, bytes.fromhex(r['hash']), bytes.fromhex(r['asig'])):
                            problems.append(f'{where}: administrator signature invalid')
                    problems.extend(self._verify_views(r['lsn'], env, r['status'], where))
                h = heads.get(o)
                if last is None or not h or h[0] != last['cseq'] or h[1] != last['hash']:
                    problems.append(f'{o}: stored head does not match the history')
                elif not all_signatures:
                    n = roster.get(last['node'])
                    if n and n.get('pub') and not ed25519.verify(bytes.fromhex(n['pub']), bytes.fromhex(last['hash']), bytes.fromhex(last['sig'])):
                        problems.append(f'{o}#{last["cseq"]}: invalid signature')
            for t in ('audit', 'activity', 'security'):
                orphan = self.conn.execute(f'SELECT COUNT(*) FROM {t} WHERE lsn NOT IN (SELECT lsn FROM changes)').fetchone()[0]
                if orphan:
                    problems.append(f'{orphan} {t} log entries do not belong to any saved change (inserted afterwards)')
        report = {'ts': now(), 'checked': checked, 'ok': not problems, 'problems': problems[:200], 'problemCount': len(problems),
                  'seconds': round(time.time() - started, 2), 'signatures': 'all' if all_signatures else 'latest per PC'}
        self.set_meta('last_verify', report)
        if problems:
            self.alert('integrity', f'History check found {len(problems)} problem(s), e.g. {problems[0]}', self.node.id, key='integrity|local')
        return report

    def _verify_views(self, lsn, env, status, where):
        expect = {'audit': [], 'activity': [], 'security': []}
        for table, row in self.view_rows(env, status):
            expect[table].append(row)
        out = []
        for table, rows in expect.items():
            have = [dict(r) for r in self.conn.execute(f'SELECT * FROM {table} WHERE lsn=? ORDER BY id', (lsn,))]
            if len(have) != len(rows):
                out.append(f'{where}: {table} log has {len(have)} entries instead of {len(rows)}')
                continue
            for a, b in zip(have, rows):
                if any(a.get(k) != v for k, v in b.items()):
                    out.append(f'{where}: a {table} log entry was edited')
                    break
        return out

    # ------------------------------------------------------------ log queries (monitoring)
    def query(self, table, q='', user='', typ='', area='', frm='', to='', node='', limit=200, offset=0, areas=None):
        cols = {'audit': ['label', 'entity', 'entity_id', 'changes', 'before', 'after'], 'activity': ['action', 'target', 'page', 'detail'],
                'security': ['target', 'detail', 'user']}[table]
        where, args = [], []
        if areas is not None and table == 'audit':
            where.append(f'area_id IN ({",".join("?" * len(areas)) or "NULL"})')
            args += list(areas)
        if q:
            where.append('(' + ' OR '.join(f'{c} LIKE ?' for c in cols) + ')')
            args += [f'%{q}%'] * len(cols)
        if user:
            where.append('user=?'); args.append(user)
        if typ:
            where.append({'audit': 'op', 'activity': 'type', 'security': 'event'}[table] + '=?'); args.append(typ)
        if area and table == 'audit':
            where.append('area_id=?'); args.append(area)
        if node:
            where.append('node=?'); args.append(node)
        if frm:
            where.append('ts>=?'); args.append(frm)
        if to:
            where.append('ts<=?'); args.append(to + 'T23:59:59')
        w = ('WHERE ' + ' AND '.join(where)) if where else ''
        with self.lock:
            names = {r['id']: r['name'] for r in self.conn.execute('SELECT id, name FROM nodes')}
            total = self.conn.execute(f'SELECT COUNT(*) FROM {table} {w}', args).fetchone()[0]
            rows = [dict(r) for r in self.conn.execute(f'SELECT * FROM {table} {w} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?',
                                                       (*args, int(limit), int(offset)))]
            users = [r[0] for r in self.conn.execute(f'SELECT DISTINCT user FROM {table} ORDER BY user')]
        for r in rows:
            r['node_name'] = names.get(r['node'], r['node'])
        return {'total': total, 'rows': rows, 'users': users, 'nodes': [{'id': k, 'name': v} for k, v in names.items()]}

    def sync_log(self, peer, event, detail):
        with self.lock:
            self.conn.execute('INSERT INTO sync_log (ts, peer, event, detail) VALUES (?,?,?,?)', (now(), peer, event, canonical(detail)))
            if int(time.time()) % 50 == 0:
                self.conn.execute('DELETE FROM sync_log WHERE id < (SELECT MAX(id) - 5000 FROM sync_log)')

    def peer_state(self):
        with self.lock:
            return {r['node']: json.loads(r['data']) for r in self.conn.execute('SELECT * FROM peer_state')}

    def set_peer_state(self, node, data):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO peer_state VALUES (?,?)', (node, canonical(data)))

    def stats(self):
        with self.lock:
            return {'changes': self.conn.execute('SELECT COUNT(*) FROM changes').fetchone()[0],
                    'rejected': self.conn.execute("SELECT COUNT(*) FROM changes WHERE status!='ok'").fetchone()[0],
                    'origins': len(self.heads)}


def env_hash(env):
    return chash(canonical(env))


def _unhex(s):
    try:
        return bytes.fromhex(s) if isinstance(s, str) else b''
    except ValueError:
        return b''


def _redact(d):
    if not isinstance(d, dict):
        return d
    out = dict(d)
    if 'pw_hash' in out:
        v = out['pw_hash']
        out['pw_hash'] = ['(password)', '(new password)'] if isinstance(v, list) else '(password set)'
    return out
