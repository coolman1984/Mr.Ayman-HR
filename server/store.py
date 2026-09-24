"""SQLite storage for the Break Area Management System.

Design rules (data must never be lost):
  * Every change arrives as one "commit" and is applied in ONE transaction -
    either all of it is saved or none of it.
  * Rows are never physically deleted. A delete only marks the row
    (deleted=1 + who/when/which transaction) so it can be restored.
  * Every row carries a version number. A change based on an old version is
    rejected (someone else changed it first) instead of silently overwriting.
  * Every change is written to the audit_log table AND appended to a monthly
    JSON-lines file in data/logs that is never touched by a restore.
"""
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime

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
        return json.dumps(v, ensure_ascii=False)
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
        self.conn = self._open()

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
    def state(self):
        with self.lock:
            rows = {}
            for e, (table, _, _) in ENTITIES.items():
                rows[e] = [self._row_js(e, r) for r in self.conn.execute(f'SELECT * FROM {table} WHERE deleted=0 ORDER BY rowid')]
            settings = {r['id']: r.get('value') for r in rows['settings']}
            settings_ver = {r['id']: r['ver'] for r in rows['settings']}
            areas = sorted(rows['areas'], key=lambda a: (a.get('name') or '').lower())
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
    def commit(self, user, ip, label, ops, force=False):
        if not isinstance(ops, list) or not ops:
            raise BadRequest('Nothing to save')
        txn, ts = uuid.uuid4().hex[:12], now()
        audit = []
        with self.lock:
            c = self.conn
            c.execute('BEGIN IMMEDIATE')
            try:
                for op in ops:
                    audit.append(self._apply(c, op, txn, ts, user, force))
                audit = [a for a in audit if a]
                c.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?)', (txn, ts, user, ip, label, len(audit)))
                for a in audit:
                    c.execute('INSERT INTO audit_log (ts,txn,user,ip,label,entity,entity_id,area_id,op,changes,before,after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                              (ts, txn, user, ip, label, a['entity'], a['id'], a['area'], a['op'],
                               json.dumps(a['changes'], ensure_ascii=False),
                               json.dumps(a['before'], ensure_ascii=False) if a['before'] else None,
                               json.dumps(a['after'], ensure_ascii=False) if a['after'] else None))
                c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='data_version'")
                c.execute('COMMIT')
            except Exception:
                c.execute('ROLLBACK')
                raise
            version = int(c.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()[0])
        self._audit_file([{'ts': ts, 'txn': txn, 'user': user, 'ip': ip, 'label': label, **{k: a[k] for k in ('entity', 'id', 'op', 'changes')}} for a in audit])
        return {'txn': txn, 'version': version, 'changes': len(audit)}

    def _apply(self, c, op, txn, ts, user, force):
        entity, rid, kind = op.get('e'), op.get('id'), op.get('op')
        if entity not in ENTITIES or not isinstance(rid, str) or not rid or len(rid) > 120:
            raise BadRequest(f'Invalid change: {entity}/{rid}')
        table, title, fields = ENTITIES[entity]
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
                return None
            c.execute(f'UPDATE {table} SET deleted=1, deleted_at=?, deleted_by=?, deleted_txn=?, ver=ver+1 WHERE id=?', (ts, user, txn, rid))
            before.pop('ver', None)
            return {'entity': entity, 'id': rid, 'op': 'delete', 'area': self._area_of(entity, before), 'changes': {}, 'before': before, 'after': None}

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
        if before:
            b = {k: v for k, v in before.items() if k != 'ver'}
            changes = {k: [b.get(k), after.get(k)] for k in set(b) | set(after) if b.get(k) != after.get(k)}
            if not changes:
                return None
            sets = ', '.join(f'{col}=?' for col in vals)
            c.execute(f'UPDATE {table} SET {sets}, ver=ver+1, updated_at=?, updated_by=? WHERE id=?', (*vals.values(), ts, user, rid))
            return {'entity': entity, 'id': rid, 'op': 'update', 'area': self._area_of(entity, after), 'changes': changes, 'before': b, 'after': after}
        if cur:  # previously deleted row that is being re-created
            sets = ', '.join(f'{col}=?' for col in vals)
            c.execute(f'UPDATE {table} SET {sets}, ver=ver+1, deleted=0, deleted_at=NULL, deleted_by=NULL, deleted_txn=NULL, '
                      f'updated_at=?, updated_by=? WHERE id=?', (*vals.values(), ts, user, rid))
        else:
            cols = ', '.join(vals)
            c.execute(f'INSERT INTO {table} (id, {cols}, ver, created_at, created_by, updated_at, updated_by) VALUES (?, {", ".join("?" * len(vals))}, 1, ?, ?, ?, ?)',
                      (rid, *vals.values(), ts, user, ts, user))
        return {'entity': entity, 'id': rid, 'op': 'insert', 'area': self._area_of(entity, after), 'changes': {}, 'before': None, 'after': after}

    def claim_first_run(self):
        """True for exactly one caller, only on a brand-new database: that caller loads the sample data.
        Later (e.g. after the user deletes all sample data) it is always False."""
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
                t = self.conn.execute('SELECT label FROM transactions WHERE id=?', (g['txn'],)).fetchone()
                g['label'] = t[0] if t else ''
                g['names'] = g['names'][:6]
            return sorted(groups.values(), key=lambda g: g['ts'] or '', reverse=True)

    def restore_txn(self, user, ip, txn):
        ops = []
        with self.lock:
            for e, (table, _, _) in ENTITIES.items():
                for r in self.conn.execute(f'SELECT * FROM {table} WHERE deleted=1 AND deleted_txn=?', (txn,)):
                    row = self._row_js(e, r)
                    ops.append({'e': e, 'id': r['id'], 'op': 'put', 'row': row})
            t = self.conn.execute('SELECT label FROM transactions WHERE id=?', (txn,)).fetchone()
        if not ops:
            raise BadRequest('Nothing to restore')
        return self.commit(user, ip, 'Restore deleted: ' + (t[0] if t else txn), ops, force=True)

    # ------------------------------------------------------------ logs
    def log_activity(self, user, ip, events):
        ts = now()
        with self.lock:
            self.conn.executemany('INSERT INTO activity_log (ts,user,ip,type,action,target,page,detail) VALUES (?,?,?,?,?,?,?,?)',
                                  [(str(e.get('ts') or ts)[:19], str(e.get('user') or user)[:80], ip, str(e.get('type') or '')[:30],
                                    str(e.get('action') or '')[:120], str(e.get('target') or '')[:200], str(e.get('page') or '')[:120],
                                    str(e.get('detail') or '')[:2000]) for e in events[:500]])

    def query_log(self, kind, q='', user='', typ='', area='', frm='', to='', limit=200, offset=0):
        table = 'audit_log' if kind == 'audit' else 'activity_log'
        where, args = [], []
        if q:
            cols = ['label', 'entity', 'entity_id', 'changes', 'before', 'after'] if kind == 'audit' else ['action', 'target', 'page', 'detail']
            where.append('(' + ' OR '.join(f'{c} LIKE ?' for c in cols) + ')')
            args += [f'%{q}%'] * len(cols)
        if user:
            where.append('user=?'); args.append(user)
        if typ:
            where.append(('op' if kind == 'audit' else 'type') + '=?'); args.append(typ)
        if area and kind == 'audit':
            where.append('area_id=?'); args.append(area)
        if frm:
            where.append('ts>=?'); args.append(frm)
        if to:
            where.append('ts<=?'); args.append(to + 'T23:59:59')
        w = ('WHERE ' + ' AND '.join(where)) if where else ''
        with self.lock:
            total = self.conn.execute(f'SELECT COUNT(*) FROM {table} {w}', args).fetchone()[0]
            rows = [dict(r) for r in self.conn.execute(f'SELECT * FROM {table} {w} ORDER BY id DESC LIMIT ? OFFSET ?', (*args, int(limit), int(offset)))]
            users = [r[0] for r in self.conn.execute(f'SELECT DISTINCT user FROM {table} ORDER BY user')]
        return {'total': total, 'rows': rows, 'users': users}

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
            sheets.append(('Data Changes Log', ['#', 'Time', 'User', 'IP', 'Action', 'Table', 'Record ID', 'Break Area', 'Operation', 'Changes'],
                           [[r['id'], r['ts'], r['user'], r['ip'], r['label'], r['entity'], r['entity_id'], areas.get(r['area_id'], r['area_id']), r['op'],
                             r['changes'] if r['op'] == 'update' else (r['after'] or r['before'])]
                            for r in c.execute('SELECT * FROM audit_log ORDER BY id')]))
            sheets.append(('User Activity Log', ['#', 'Time', 'User', 'IP', 'Type', 'Action', 'Target', 'Page', 'Detail'],
                           [[r['id'], r['ts'], r['user'], r['ip'], r['type'], r['action'], r['target'], r['page'], r['detail']]
                            for r in c.execute('SELECT * FROM activity_log ORDER BY id')]))
        return sheets

    def counts(self):
        with self.lock:
            return {title: self.conn.execute(f'SELECT COUNT(*) FROM {table} WHERE deleted=0').fetchone()[0]
                    for table, title, _ in ENTITIES.values()}
