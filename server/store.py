"""SQLite storage for the Break Area Management System.

Design rules (data must never be lost):
  * Every change arrives as one "commit" and is applied in ONE transaction -
    either all of it is saved or none of it.
  * Rows are never physically deleted. A delete only marks the row
    (deleted=1 + who/when/which transaction) so it can be restored.
  * Every row carries a version number. A change based on an old version is
    rejected (someone else changed it first) instead of silently overwriting.
  * Every change becomes one signed changeset in the change journal
    (journal.py, data/journal.db) and is appended to a monthly JSON-lines file in
    data/logs. Both are never touched by a restore.
  * The rows are a deterministic fold of the journal (replica.py), so every PC that
    has received the same changes shows exactly the same data.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime

import replica
from journal import canonical

T, I, R, B, J = 'text', 'int', 'real', 'bool', 'json'

# entity -> (table, sheet title, [(js key, column, kind, Excel header)])
ENTITIES = {
    'settings': ('settings', 'Settings', [('value', 'value', J, 'Value')]),
    'itemTypes': ('item_types', 'Item Types', [
        ('name', 'name', T, 'Name'), ('short', 'short_name', T, 'Singular'), ('icon', 'icon', T, 'Icon')]),
    'areas': ('areas', 'Break Areas', [
        ('name', 'name', T, 'Break Area'), ('location', 'location', T, 'Location'), ('building', 'building', T, 'Building'),
        ('floor', 'floor', T, 'Floor'), ('startDate', 'start_date', T, 'Start Date'), ('size', 'size_m2', R, 'Area Size (m2)'),
        ('capacity', 'capacity', I, 'Capacity'), ('responsible', 'responsible', T, 'Responsible'), ('status', 'status', T, 'Status'),
        ('active', 'active', B, 'Operational'), ('description', 'description', T, 'Description'),
        ('lastInspection', 'last_inspection', T, 'Last Inspection'), ('nextInspection', 'next_inspection', T, 'Next Inspection'),
        ('inspectedBy', 'inspected_by', T, 'Inspected By')]),
    'inventory': ('inventory', 'Inventory', [
        ('areaId', 'area_id', T, 'Area ID'), ('item', 'item', T, 'Item'), ('qty', 'qty', I, 'Quantity'),
        ('condition', 'condition', T, 'Condition'), ('note', 'note', T, 'Notes')]),
    'surveys': ('surveys', 'Satisfaction Surveys', [
        ('areaId', 'area_id', T, 'Area ID'), ('month', 'month', T, 'Month'), ('department', 'department', T, 'Department'),
        ('percentage', 'percentage', R, 'Satisfaction %'), ('respondents', 'respondents', I, 'Respondents'),
        ('notes', 'notes', T, 'Notes'), ('by', 'entered_by', T, 'Entered By')]),
    'photos': ('photos', 'Photos', [
        ('areaId', 'area_id', T, 'Area ID'), ('caption', 'caption', T, 'Caption'), ('category', 'category', T, 'Category'),
        ('date', 'date', T, 'Date'), ('main', 'is_main', B, 'Main Photo'), ('src', 'src', T, 'File'), ('thumb', 'thumb', T, 'Thumbnail'),
        ('variant', 'variant', T, 'Placeholder'), ('seed', 'seed', T, 'Placeholder Seed')]),
    'docs': ('documents', 'Documents', [
        ('areaId', 'area_id', T, 'Area ID'), ('name', 'name', T, 'File Name'), ('caption', 'caption', T, 'Title'),
        ('size', 'size_bytes', I, 'Size (bytes)'), ('type', 'mime_type', T, 'Type'), ('date', 'date', T, 'Date'), ('src', 'src', T, 'File')]),
    'issues': ('issues', 'Issues', [
        ('areaId', 'area_id', T, 'Area ID'), ('date', 'date', T, 'Reported'), ('title', 'title', T, 'Issue'), ('item', 'item', T, 'Item'),
        ('priority', 'priority', T, 'Priority'), ('status', 'status', T, 'Status'), ('closedDate', 'closed_date', T, 'Closed'),
        ('reportedBy', 'reported_by', T, 'Reported By'), ('details', 'details', T, 'Details')]),
    'issueLog': ('issue_log', 'Issue Follow-ups', [
        ('issueId', 'issue_id', T, 'Issue ID'), ('date', 'date', T, 'Date'), ('by', 'by_user', T, 'By'), ('text', 'text', T, 'Note')]),
    'maintenance': ('maintenance', 'Maintenance', [
        ('areaId', 'area_id', T, 'Area ID'), ('date', 'date', T, 'Planned Date'), ('item', 'item', T, 'Item'),
        ('assignedTo', 'assigned_to', T, 'Assigned To'), ('details', 'details', T, 'Work'), ('status', 'status', T, 'Status'),
        ('doneDate', 'done_date', T, 'Done Date'), ('notes', 'notes', T, 'Notes')]),
    'inspections': ('inspections', 'Inspections', [
        ('areaId', 'area_id', T, 'Area ID'), ('date', 'date', T, 'Date'), ('by', 'by_user', T, 'Inspected By'),
        ('result', 'result', T, 'Result'), ('notes', 'notes', T, 'Notes')]),
    'history': ('history', 'Transactions', [
        ('seq', 'seq', I, 'Seq'), ('areaId', 'area_id', T, 'Area ID'), ('date', 'date', T, 'Date'), ('item', 'item', T, 'Item'),
        ('action', 'action', T, 'Action'), ('prev', 'prev_qty', I, 'Previous Qty'), ('next', 'new_qty', I, 'New Qty'),
        ('details', 'details', T, 'Details'), ('by', 'by_user', T, 'Updated By')]),
}
AREA_CHILDREN = ['inventory', 'photos', 'docs', 'issues', 'maintenance', 'inspections', 'surveys']

# Merge rules for changes made at the same time on two PCs (see DISTRIBUTED_SYNC_ARCHITECTURE.md, conflict matrix).
COUNTERS = {'inventory': {'qty'}}  # every movement is a delta: +5 on one PC and -2 on another give +3
RESOLVERS = {
    'areas': {'lastInspection': 'max', 'nextInspection': 'max', 'inspectedBy': 'follow:lastInspection'},
    'maintenance': {'status': 'rank:Scheduled,In Progress,Done', 'doneDate': 'follow:status', 'notes': 'follow:status'},
}
SPECS = {e: {'table': t, 'fields': [(js, col, kind) for js, col, kind, _ in f], 'counters': COUNTERS.get(e, set()),
             'resolvers': RESOLVERS.get(e, {})} for e, (t, _, f) in ENTITIES.items()}


class Conflict(Exception):
    pass


class BadRequest(Exception):
    pass


def now():
    return datetime.now().isoformat(timespec='seconds')


def _coerce(kind, v):
    if v is None or v == '' and kind in (I, R):
        return None
    if kind == I:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    if kind == R:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if kind == B:
        return 1 if v else 0
    if kind == J:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v)


def _out(kind, v):
    if v is None:
        return None
    if kind == B:
        return bool(v)
    if kind == J:
        return json.loads(v)
    if kind == R and float(v).is_integer():
        return int(v)
    return v


class Store:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, 'bams.db')
        self.log_dir = os.path.join(data_dir, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.journal = None
        self.folder = None
        self.conn = self._open()
        self._fp = (None, None)

    def attach(self, journal):
        """Connects the change journal. From now on every save goes through it."""
        self.journal = journal
        self.folder = replica.BusinessFolder(self.conn, SPECS, journal.deps_of, _coerce)

    # ------------------------------------------------------------ setup
    def _open(self):
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA busy_timeout=10000')
        ok = conn.execute('PRAGMA quick_check').fetchone()[0]
        if ok != 'ok':
            raise RuntimeError(f'Database file is damaged ({ok}). Restore the latest file from the backups folder.')
        self._migrate(conn)
        return conn

    def reopen(self):
        with self.lock:
            self.conn.close()
            self.conn = self._open()
            if self.journal:
                self.folder = replica.BusinessFolder(self.conn, SPECS, self.journal.deps_of, _coerce)

    def _migrate(self, conn):
        meta = 'id TEXT PRIMARY KEY, ver INTEGER NOT NULL DEFAULT 1, created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT, ' \
               'deleted INTEGER NOT NULL DEFAULT 0, deleted_at TEXT, deleted_by TEXT, deleted_txn TEXT'
        for table, _, fields in ENTITIES.values():
            conn.execute(f'CREATE TABLE IF NOT EXISTS {table} ({meta})')
            have = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
            for _, col, kind, _ in fields:
                if col not in have:
                    sql_type = {I: 'INTEGER', R: 'REAL', B: 'INTEGER'}.get(kind, 'TEXT')
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {sql_type}')
            if any(f[0] == 'areaId' for f in fields):
                conn.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_area ON {table}(area_id)')
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, ts TEXT, user TEXT, ip TEXT, label TEXT, changes INTEGER);
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, txn TEXT, user TEXT, ip TEXT, label TEXT,
                entity TEXT, entity_id TEXT, area_id TEXT, op TEXT, changes TEXT, before TEXT, after TEXT);
            CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);
            CREATE INDEX IF NOT EXISTS ix_audit_area ON audit_log(area_id);
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, ip TEXT, type TEXT, action TEXT,
                target TEXT, page TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity_log(ts);
            INSERT OR IGNORE INTO meta VALUES ('data_version', '0');
        ''')
        replica.install(conn)

    # ------------------------------------------------------------ helpers
    def version(self):
        with self.lock:
            return int(self.conn.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()[0])

    @staticmethod
    def _row_js(entity, r):
        _, _, fields = ENTITIES[entity]
        d = {'id': r['id']}
        for js, col, kind, _ in fields:
            v = _out(kind, r[col])
            if v is not None:
                d[js] = v
        d['ver'] = r['ver']
        return d

    def _audit_file(self, entries):
        if not entries:
            return
        path = os.path.join(self.log_dir, f'audit-{datetime.now():%Y-%m}.jsonl')
        with open(path, 'a', encoding='utf-8') as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def _area_of(self, entity, row):
        if entity == 'areas':
            return row.get('id')
        if entity == 'issueLog':
            r = self.conn.execute('SELECT area_id FROM issues WHERE id=?', (row.get('issueId'),)).fetchone()
            return r[0] if r else None
        return row.get('areaId')

    # ------------------------------------------------------------ read
    def state(self, areas=None, surveys=True):
        """Everything the page needs. areas: only these break area ids (None = all); surveys=False leaves out the survey results."""
        with self.lock:
            rows = {}
            for e, (table, _, _) in ENTITIES.items():
                rows[e] = [self._row_js(e, r) for r in self.conn.execute(f'SELECT * FROM {table} WHERE deleted=0 ORDER BY rowid')]
            settings = {r['id']: r.get('value') for r in rows['settings']}
            settings_ver = {r['id']: r['ver'] for r in rows['settings']}
            allowed = None if areas is None else set(areas)
            if not surveys:
                rows['surveys'] = []
            areas = sorted((a for a in rows['areas'] if allowed is None or a['id'] in allowed), key=lambda a: (a.get('name') or '').lower())
            by_id = {}
            for a in areas:
                for c in AREA_CHILDREN:
                    a[c] = []
                by_id[a['id']] = a
            logs = {}
            for l in rows['issueLog']:
                logs.setdefault(l.pop('issueId', None), []).append(l)
            for c in AREA_CHILDREN:
                for r in rows[c]:
                    a = by_id.get(r.pop('areaId', None))
                    if a is None:
                        continue
                    if c == 'issues':
                        r['log'] = logs.get(r['id'], [])
                    a[c].append(r)
            history = [h for h in rows['history'] if h.get('areaId') in by_id]
            initialized = self.conn.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone() is not None
            return {'settings': settings, 'settingsVer': settings_ver, 'itemTypes': rows['itemTypes'], 'areas': areas, 'history': history,
                    'initialized': initialized,
                    'version': int(self.conn.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()[0])}

    # ------------------------------------------------------------ write
    def commit(self, user, ip, label, ops, force=False, guard=None, user_id='', kind='data'):
        """guard(changes, force) is called with the changes before they are saved; raising an exception cancels all of them.
        The accepted changes become one changeset: folded into the tables, appended to the journal, then committed."""
        if not isinstance(ops, list) or not ops:
            raise BadRequest('Nothing to save')
        if self.journal is None:
            raise RuntimeError('The change journal is not ready')
        rec, appended = None, False
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
                audit, rops = [], []
                for op in ops:
                    a, r = self._plan(c, op, force)
                    if a:
                        audit.append(a)
                    if r:
                        rops.append(r)
                if guard:
                    guard(audit, force)
                if not rops:
                    c.execute('ROLLBACK')
                    return {'txn': None, 'version': self.version(), 'changes': 0}
                with self.journal.lock:
                    rec = self.journal.build(kind, rops, actor=user, actor_id=user_id, ip=ip, label=label)
                    before = len(self.folder.problems)
                    self.folder.fold(rec['env'], 'ok')
                    if len(self.folder.problems) != before:
                        raise BadRequest('This change could not be saved: ' + self.folder.problems[-1])
                    self._bump(c)
                    self.journal.append_local(rec)
                    appended = True
                c.execute('COMMIT')
            except Exception:
                try:
                    c.execute('ROLLBACK')
                except sqlite3.OperationalError:
                    pass
                if not appended:
                    raise
                self.fold_pending()  # the change is safely in the journal - apply it again from there
            version = self.version()
        self.journal._notify([rec])
        env = rec['env']
        self._audit_file([{'ts': env['ts'], 'txn': env['id'], 'node': env['node'], 'user': user, 'ip': ip, 'label': label,
                           **{k: a[k] for k in ('entity', 'id', 'op', 'changes')}} for a in audit])
        return {'txn': env['id'], 'version': version, 'changes': len(audit)}

    def _bump(self, c):
        c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='data_version'")

    def _plan(self, c, op, force):
        """Checks one change against the current row and turns it into (audit entry, journal op)."""
        entity, rid, kind = op.get('e'), op.get('id'), op.get('op')
        if entity not in ENTITIES or not isinstance(rid, str) or not rid or len(rid) > 120:
            raise BadRequest(f'Invalid change: {entity}/{rid}')
        table, title, fields = ENTITIES[entity]
        counters = COUNTERS.get(entity, set())
        names = [js for js, _, _, _ in fields]
        cur = c.execute(f'SELECT * FROM {table} WHERE id=?', (rid,)).fetchone()
        before = self._row_js(entity, cur) if cur and not cur['deleted'] else None
        what = f'{title[:-1] if title.endswith("s") else title} "{(before or op.get("row") or {}).get("name") or rid}"'

        if before and not force and op.get('ver') != cur['ver']:
            raise Conflict(f'{what} was changed by {cur["updated_by"] or "another user"} at {cur["updated_at"]}. '
                           'The screen has been refreshed - please repeat your change.')
        if cur and cur['deleted'] and not force and op.get('ver') is not None:
            raise Conflict(f'{what} was deleted by {cur["deleted_by"] or "another user"} at {cur["deleted_at"]}. '
                           'It can be restored from Settings > Recycle Bin.')

        if kind == 'del':
            if not before:
                if op.get('resolve') and cur:  # confirm a delete again (conflict: edited on another PC while deleted)
                    b = self._row_js(entity, cur)
                    b.pop('ver', None)
                    return None, {'e': entity, 'id': rid, 'op': 'delete', 'x': True, 'a': self._area_of(entity, b), 'b': b, 'noaudit': True}
                return None, None
            before.pop('ver', None)
            area = self._area_of(entity, before)
            return ({'entity': entity, 'id': rid, 'op': 'delete', 'area': area, 'changes': {}, 'before': before, 'after': None},
                    {'e': entity, 'id': rid, 'op': 'delete', 'x': True, 'a': area, 'b': before})

        if kind != 'put' or not isinstance(op.get('row'), dict):
            raise BadRequest(f'Invalid change: {entity}/{rid}')
        row = op['row']
        if entity == 'surveys':
            p = _coerce(R, row.get('percentage'))
            if p is None or not 0 <= p <= 100:
                raise BadRequest('Satisfaction percentage must be between 0 and 100')
            if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', str(row.get('month') or '')):
                raise BadRequest('Survey month is required (YYYY-MM)')
        vals = {col: _coerce(kind_, row.get(js)) for js, col, kind_, _ in fields}
        after = {'id': rid, **{js: _out(k, vals[col]) for js, col, k, _ in fields if vals[col] is not None}}
        area = self._area_of(entity, after)
        if before:
            b = {k: v for k, v in before.items() if k != 'ver'}
            changes = {k: [b.get(k), after.get(k)] for k in set(b) | set(after) if b.get(k) != after.get(k)}
            touch = [f for f in (op.get('resolve') or []) if f in names and f not in counters]
            if not changes and not touch:
                return None, None
            s = {k: after.get(k) for k in list(changes) + touch if k in names and k not in counters}
            n = {k: (after.get(k) or 0) - (b.get(k) or 0) for k in changes if k in counters}
            rop = {'e': entity, 'id': rid, 'op': 'update', 's': s, 'a': area, 'c': changes}
            if n:
                rop['n'] = n
            if not changes:
                rop['noaudit'] = True
                return None, rop
            return {'entity': entity, 'id': rid, 'op': 'update', 'area': area, 'changes': changes, 'before': b, 'after': after}, rop
        if cur:  # previously deleted row that is being re-created
            old = self._row_js(entity, cur)
            s = {js: after.get(js) for js in names if js not in counters}
            n = {k: (after.get(k) or 0) - (old.get(k) or 0) for k in counters}
        else:
            s = {js: v for js, v in after.items() if js != 'id' and js not in counters}
            n = {k: after.get(k) or 0 for k in counters}
        rop = {'e': entity, 'id': rid, 'op': 'insert', 's': s, 'x': False, 'a': area, 'r': after}
        n = {k: v for k, v in n.items() if v}
        if n:
            rop['n'] = n
        return {'entity': entity, 'id': rid, 'op': 'insert', 'area': area, 'changes': {}, 'before': None, 'after': after}, rop

    def fold_pending(self, limit=2000):
        """Applies every journal changeset not yet in the tables (after a crash, or received from another PC).
        Returns the number of changesets folded."""
        total = 0
        while True:
            with self.lock:
                items = self.journal.iter_after(replica.markers(self.conn), limit)
                if not items:
                    return total
                c = self.conn
                c.execute('BEGIN IMMEDIATE')
                try:
                    changed = False
                    for env, status in items:
                        changed |= self.folder.fold(env, status)
                    if changed:
                        self._bump(c)
                    c.execute('COMMIT')
                except Exception:
                    c.execute('ROLLBACK')
                    raise
                total += len(items)

    def restore_from(self, path, user, ip, label, user_id=''):
        """Brings the data back to the state of a backup file WITHOUT rolling back history: the differences
        become one 'restore' changeset. It is weak: real changes made at the same time on other PCs win over it."""
        src = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        src.row_factory = sqlite3.Row
        ops = []
        try:
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            with self.lock:
                for e, (table, _, fields) in ENTITIES.items():
                    backup = {}
                    if table in tables:
                        cols = {r[1] for r in src.execute(f'PRAGMA table_info({table})')}
                        for r in src.execute(f'SELECT * FROM {table}'):
                            if not ('deleted' in cols and r['deleted']):
                                d = {'id': r['id']}
                                for js, col, kind, _ in fields:
                                    v = _out(kind, r[col]) if col in cols else None
                                    if v is not None:
                                        d[js] = v
                                backup[r['id']] = d
                    current = {r['id'] for r in self.conn.execute(f'SELECT id FROM {table} WHERE deleted=0')}
                    for rid in sorted(set(backup) | current):
                        if rid in backup:
                            ops.append({'e': e, 'id': rid, 'op': 'put', 'row': backup[rid]})
                        else:
                            ops.append({'e': e, 'id': rid, 'op': 'del'})
        finally:
            src.close()
        if not ops:
            return {'txn': None, 'changes': 0, 'version': self.version()}
        return self.commit(user, ip, label, ops, force=True, user_id=user_id, kind='restore')

    def mark_initialized(self):
        with self.lock:
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('initialized', ?)", (now(),))

    def claim_first_run(self):
        """True for exactly one caller, only on a brand-new database: that caller loads the sample data.
        Later (e.g. after the user deletes all sample data) it is always False. A PC that joined another
        administrator PC is marked initialized when it joins, so it never loads sample data."""
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
                done = c.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()
                has_data = c.execute('SELECT COUNT(*) FROM areas').fetchone()[0] > 0
                if not done:
                    c.execute("INSERT INTO meta VALUES ('initialized', ?)", (now(),))
                c.execute('COMMIT')
            except Exception:
                c.execute('ROLLBACK')
                raise
            return not done and not has_data

    # ------------------------------------------------------------ recycle bin
    def trash(self):
        with self.lock:
            groups = {}
            for e, (table, title, _) in ENTITIES.items():
                for r in self.conn.execute(f'SELECT * FROM {table} WHERE deleted=1 AND deleted_txn IS NOT NULL ORDER BY rowid'):
                    g = groups.setdefault(r['deleted_txn'], {'txn': r['deleted_txn'], 'ts': r['deleted_at'], 'user': r['deleted_by'], 'items': {}, 'names': []})
                    g['items'][title] = g['items'].get(title, 0) + 1
                    if e in ('areas', 'photos', 'docs', 'issues', 'surveys', 'itemTypes', 'maintenance'):
                        js = self._row_js(e, r)
                        g['names'].append(js.get('name') or js.get('title') or js.get('caption') or js.get('month') or js.get('details') or r['id'])
            for g in groups.values():
                g['label'] = self._txn_label(g['txn'])
                g['names'] = g['names'][:6]
            return sorted(groups.values(), key=lambda g: g['ts'] or '', reverse=True)

    def restore_txn(self, user, ip, txn):
        ops = []
        with self.lock:
            for e, (table, _, _) in ENTITIES.items():
                for r in self.conn.execute(f'SELECT * FROM {table} WHERE deleted=1 AND deleted_txn=?', (txn,)):
                    row = self._row_js(e, r)
                    ops.append({'e': e, 'id': r['id'], 'op': 'put', 'row': row})
            t = [self._txn_label(txn)]
        if not ops:
            raise BadRequest('Nothing to restore')
        return self.commit(user, ip, 'Restore deleted: ' + (t[0] or txn), ops, force=True)

    def _txn_label(self, txn):
        t = self.conn.execute('SELECT label FROM transactions WHERE id=?', (txn,)).fetchone()  # saved before the upgrade
        if t:
            return t[0]
        d = self.journal.describe(txn=txn) if self.journal else None
        return d['label'] if d else ''

    # ------------------------------------------------------------ logs (kept in the journal: never restored, all PCs)
    def log_activity(self, user, ip, events):
        self.journal.log_activity(user, ip, events[:500])

    def query_log(self, kind, q='', user='', typ='', area='', frm='', to='', limit=200, offset=0, areas=None, node=''):
        if kind == 'activity':
            self.journal.flush_activity()
        return self.journal.query('audit' if kind == 'audit' else 'activity', q, user, typ, area, frm, to, node, limit, offset, areas)

    # ------------------------------------------------------------ conflicts and convergence
    def conflicts(self):
        """Everything two PCs did at the same time that a person should look at. Identical on every PC."""
        titles = {spec['table']: (e, ENTITIES[e][1]) for e, spec in SPECS.items()}
        out = []
        with self.lock:
            flags = self.conn.execute('SELECT * FROM sync_flags ORDER BY tbl, rid, kind').fetchall()
            for f in flags:
                entity, title = titles.get(f['tbl'], (f['tbl'], f['tbl']))
                r = self.conn.execute(f'SELECT * FROM {f["tbl"]} WHERE id=?', (f['rid'],)).fetchone()
                row = self._row_js(entity, r) if r else {'id': f['rid']}
                detail = json.loads(f['detail'])
                item = {'entity': entity, 'title': title, 'id': f['rid'], 'kind': f['kind'], 'deleted': bool(r and r['deleted']),
                        'name': row.get('name') or row.get('title') or row.get('caption') or row.get('item') or row.get('details') or f['rid'],
                        'area': self._area_of(entity, row) if r else None, 'row': row, 'detail': detail}
                out.append(item)
            dup = self.conn.execute('SELECT area_id, month, department, COUNT(*) n, GROUP_CONCAT(id) ids FROM surveys WHERE deleted=0 '
                                    'GROUP BY area_id, month, department HAVING n > 1').fetchall()
            for d in dup:
                out.append({'entity': 'surveys', 'title': 'Satisfaction Surveys', 'id': d['ids'].split(',')[0], 'kind': 'duplicate',
                            'area': d['area_id'], 'name': f'{d["month"]} {d["department"] or ""}'.strip(), 'deleted': False,
                            'detail': {'ids': d['ids'].split(','), 'count': d['n']}})
        return out

    def fingerprint(self):
        """SHA-256 over the complete business data (without local counters). Equal on PCs that agree."""
        with self.lock:
            v = self.version()
            if self._fp[0] == v:
                return self._fp[1]
            h = hashlib.sha256()
            for e in sorted(ENTITIES):
                table = ENTITIES[e][0]
                for r in self.conn.execute(f'SELECT * FROM {table} ORDER BY id'):
                    d = dict(r)
                    d.pop('ver', None)
                    h.update(canonical([table, d]).encode('utf-8'))
            for r in self.conn.execute('SELECT * FROM sync_flags ORDER BY tbl, rid, kind'):
                h.update(canonical(['flag', *r]).encode('utf-8'))
            self._fp = (v, h.hexdigest())
            return self._fp[1]

    # ------------------------------------------------------------ export
    def export_sheets(self):
        with self.lock:
            c = self.conn
            areas = {r['id']: r['name'] for r in c.execute('SELECT id, name FROM areas')}
            items = {r['id']: r['name'] for r in c.execute('SELECT id, name FROM item_types')}
            items.update({'area': 'Break Area', 'Initial Setup': 'Initial Setup'})
            sheets, deleted = [], []
            order = ['areas', 'surveys', 'inventory', 'history', 'issues', 'issueLog', 'maintenance', 'inspections', 'photos', 'docs', 'itemTypes', 'settings']
            for e in order:
                table, title, fields = ENTITIES[e]
                head = ['ID']
                for js, _, _, label in fields:
                    head += ['Break Area'] if js == 'areaId' else [label]
                head += ['Created', 'Created By', 'Last Changed', 'Changed By']
                rows = []
                for r in c.execute(f'SELECT * FROM {table} ORDER BY rowid'):
                    if r['deleted']:
                        deleted.append([title, r['id'], areas.get(r['area_id']) if 'area_id' in r.keys() else '',
                                        str(self._row_js(e, r))[:500], r['deleted_at'], r['deleted_by']])
                        continue
                    out = [r['id']]
                    for js, col, kind, _ in fields:
                        v = _out(kind, r[col])
                        if js == 'areaId':
                            v = areas.get(v, v)
                        elif js == 'item':
                            v = items.get(v, v)
                        elif kind == J:
                            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        out.append(v)
                    out += [r['created_at'], r['created_by'], r['updated_at'], r['updated_by']]
                    rows.append(out)
                sheets.append((title, head, rows))

            # Satisfaction pivot: one row per area, one column per month (average of departments)
            piv = {}
            for r in c.execute('SELECT area_id, month, AVG(percentage) p FROM surveys WHERE deleted=0 GROUP BY area_id, month'):
                piv.setdefault(r['area_id'], {})[r['month']] = round(r['p'], 1)
            months = sorted({m for v in piv.values() for m in v})
            prow = [[areas.get(a, a)] + [piv[a].get(m) for m in months] for a in sorted(piv, key=lambda x: areas.get(x, x))]
            sheets.insert(1, ('Satisfaction by Month', ['Break Area'] + months, prow))

            sheets.append(('Deleted Records', ['Table', 'ID', 'Break Area', 'Record', 'Deleted At', 'Deleted By'], deleted))
        j = self.journal
        j.flush_activity()
        with j.lock:
            names = {r['id']: r['name'] for r in j.conn.execute('SELECT id, name FROM nodes')}
            sheets.append(('Data Changes Log', ['#', 'Time', 'User', 'PC', 'IP', 'Action', 'Table', 'Record ID', 'Break Area', 'Operation', 'Changes'],
                           [[r['id'], r['ts'], r['user'], names.get(r['node'], r['node']), r['ip'], r['label'], r['entity'], r['entity_id'],
                             areas.get(r['area_id'], r['area_id']), r['op'], r['changes'] if r['op'] == 'update' else (r['after'] or r['before'])]
                            for r in j.conn.execute("SELECT * FROM audit WHERE entity != 'users' ORDER BY ts, id")]))
            sheets.append(('User Activity Log', ['#', 'Time', 'User', 'PC', 'IP', 'Type', 'Action', 'Target', 'Page', 'Detail'],
                           [[r['id'], r['ts'], r['user'], names.get(r['node'], r['node']), r['ip'], r['type'], r['action'], r['target'], r['page'], r['detail']]
                            for r in j.conn.execute('SELECT * FROM activity ORDER BY ts, id')]))
        return sheets

    def counts(self):
        with self.lock:
            return {title: self.conn.execute(f'SELECT COUNT(*) FROM {table} WHERE deleted=0').fetchone()[0]
                    for table, title, _ in ENTITIES.values()}
