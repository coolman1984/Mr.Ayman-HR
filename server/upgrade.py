"""Keeps every user's data safe when the program is updated.

The installer only replaces the program; the data (%ProgramData%\\BAMS\\data) stays. This module makes sure the new
program shows exactly the data the old one had, and that a problem is found at once instead of months later:

  before the data files are opened
    1. data/program.json says which program version and data model wrote the data last;
    2. data written by a NEWER program: refuse to start, touch nothing (DataFromNewerVersion);
    3. version changed: a verified snapshot of bams.db, auth.db and journal.db goes to data/upgrades/<time>_<from>_to_<to>/
       (the start is stopped if the snapshot cannot be made), and a fingerprint of every table is taken;
  right after the files are opened (new columns are added by the stores)
    4. every old row must still have exactly the same values in its old columns, no row lost, SQLite integrity ok
       (UpgradeVerificationFailed otherwise: the program does not start, the snapshot has the untouched data);
  when the system is up
    5. the history (journal.db) must still contain every old change, unchanged;
    6. migration steps (MIGRATIONS) that are not yet recorded run once, each recorded in program.json;
    7. program.json is written: what was updated, when, from which snapshot, how many records were checked.

MIGRATIONS is the place for changes that rewrite data. A step is (id, text, function(system), touches) where touches are
the tables whose rows the step may change (they only have to keep their row count); everything else must stay identical.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime

MARKER = 'program.json'
SNAP_DIR = 'upgrades'
KEEP_SNAPSHOTS = 10
DB_FILES = ('bams.db', 'auth.db', 'journal.db')
SKIP_TABLES = ('meta', 'sessions')  # sessions come and go; meta holds counters; sync_* are rebuilt from the history
APPEND_ONLY = ('changes', 'audit', 'activity', 'security')  # journal.db tables whose old rows must never change
# a change keeps its content for ever; only its bookkeeping (status, note, via) may move when changes are folded or received
IMMUTABLE = {'changes': ['lsn', 'origin', 'cseq', 'id', 'node', 'hlc', 'kind', 'body', 'hash', 'sig', 'asig']}

MIGRATIONS = []  # [(id, text, function(system), touches)] - see the module text


class DataFromNewerVersion(Exception):
    pass


class UpgradeVerificationFailed(Exception):
    pass


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', str(v or ''))[:3]) or (0,)


def now():
    return datetime.now().isoformat(timespec='seconds')


def _tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            if r[0] not in SKIP_TABLES and not r[0].startswith('sync_')]


def _digest(conn, table, cols, upto=None):
    h, n = hashlib.sha256(), 0
    where = f' WHERE rowid<={int(upto)}' if upto is not None else ''
    q = 'SELECT ' + ', '.join(f'"{c}"' for c in cols) + f' FROM "{table}"{where} ORDER BY rowid'
    for row in conn.execute(q):
        h.update(repr(tuple(row)).encode('utf-8', 'replace'))  # tuple(): a connection with sqlite3.Row rows must give the same digest
        n += 1
    return n, h.hexdigest()


def fingerprint(path):
    """{table: {cols, n, max, digest}} of a database file (every table except the rebuilt and short-lived ones)."""
    conn = sqlite3.connect(path)
    try:
        out = {}
        for t in _tables(conn):
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
            if os.path.basename(path) == 'journal.db' and t in IMMUTABLE:
                cols = [c for c in IMMUTABLE[t] if c in cols]
            top = conn.execute(f'SELECT COALESCE(MAX(rowid), 0) FROM "{t}"').fetchone()[0]
            n, d = _digest(conn, t, cols)
            out[t] = {'cols': cols, 'n': n, 'max': top, 'digest': d}
        return out
    finally:
        conn.close()


def integrity(path):
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute('PRAGMA integrity_check')]
    finally:
        conn.close()


def snapshot_db(src, dst):
    """A consistent copy (the SQLite backup API also takes what is still in the write-ahead log), verified by reading it again."""
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    bad = [m for m in integrity(dst) if m != 'ok']
    if bad:
        raise UpgradeVerificationFailed(f'The safety copy of {os.path.basename(src)} is damaged: {bad[0]}')
    a, b = fingerprint(src), fingerprint(dst)
    if a != b:
        raise UpgradeVerificationFailed(f'The safety copy of {os.path.basename(src)} differs from the original')


class Upgrade:
    def __init__(self, data_dir, version, schema, log=print):
        self.data_dir, self.version, self.schema, self.log = data_dir, version, schema, log
        self.path = os.path.join(data_dir, MARKER)
        self.marker = self._read()
        self.before_prints = {}
        self.record = None
        self.snapshot = None

    # ------------------------------------------------------------ marker
    def _read(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                m = json.load(f)
            return m if isinstance(m, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.marker, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def has_data(self):
        return any(os.path.exists(os.path.join(self.data_dir, n)) for n in DB_FILES)

    # ------------------------------------------------------------ 1. before the files are opened
    def before(self):
        m = self.marker
        if m.get('schema') and int(m['schema']) > self.schema:
            raise DataFromNewerVersion(
                f'This data was saved by a newer version of the program ({m.get("version", "?")}). This program is version {self.version} '
                'and cannot read it safely. Nothing was changed. Please install the newest version of the program.')
        if not self.has_data() or m.get('version') == self.version:
            return None
        old = m.get('version') or 'earlier than 2.6'
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name = f'{stamp}_{re.sub(r"[^0-9A-Za-z.]+", "-", old)}_to_{self.version}'
        folder = os.path.join(self.data_dir, SNAP_DIR, name)
        os.makedirs(folder, exist_ok=True)
        try:
            for f in DB_FILES:
                src = os.path.join(self.data_dir, f)
                if os.path.exists(src):
                    snapshot_db(src, os.path.join(folder, f))
                    self.before_prints[f] = fingerprint(src)
            with open(os.path.join(folder, 'info.json'), 'w', encoding='utf-8') as f:
                json.dump({'from': old, 'to': self.version, 'created': now(), 'files': [n for n in DB_FILES if os.path.exists(os.path.join(folder, n))]}, f)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        self.snapshot = name
        self._prune()
        self.log(f'Program updated from {old} to {self.version}: safety copy of the data in {os.path.join(SNAP_DIR, name)}')
        return name

    def _prune(self):
        root = os.path.join(self.data_dir, SNAP_DIR)
        names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
        for n in names[:-KEEP_SNAPSHOTS]:
            shutil.rmtree(os.path.join(root, n), ignore_errors=True)

    # ------------------------------------------------------------ 4. right after the stores opened the files
    def after_tables(self, touches=()):
        """bams.db and auth.db: the stores may only have ADDED columns. Every old row keeps its values."""
        if not self.snapshot:
            return
        skip = set(touches) | {t for _, _, _, tt in MIGRATIONS for t in tt}
        for f in ('bams.db', 'auth.db'):
            old = self.before_prints.get(f)
            if not old:
                continue
            path = os.path.join(self.data_dir, f)
            bad = [m for m in integrity(path) if m != 'ok']
            if bad:
                raise UpgradeVerificationFailed(f'{f} is not healthy after the update: {bad[0]}. Your data before the update is in {SNAP_DIR}/{self.snapshot}.')
            conn = sqlite3.connect(path)
            try:
                have = set(_tables(conn))
                for t, o in old.items():
                    if t not in have:
                        raise UpgradeVerificationFailed(f'{f}: table {t} is missing after the update (data before the update: {SNAP_DIR}/{self.snapshot}).')
                    n, d = _digest(conn, t, o['cols'])
                    if n < o['n']:
                        raise UpgradeVerificationFailed(f'{f}: {o["n"] - n} record(s) of {t} are missing after the update (data before the update: {SNAP_DIR}/{self.snapshot}).')
                    if t not in skip and (n != o['n'] or d != o['digest']):
                        raise UpgradeVerificationFailed(f'{f}: records of {t} changed during the update (data before the update: {SNAP_DIR}/{self.snapshot}).')
            finally:
                conn.close()

    # ------------------------------------------------------------ 5-7. the system is up
    def finish(self, system, history_kept=True):
        """The history must still hold every old change; run pending migration steps; write program.json."""
        counts = {}
        if self.snapshot and history_kept:
            old = self.before_prints.get('journal.db') or {}
            conn = system.journal.conn
            with system.journal.lock:
                for t in APPEND_ONLY:
                    o = old.get(t)
                    if not o:
                        continue
                    n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    same = _digest(conn, t, o['cols'], upto=o['max'])
                    if n < o['n'] or same != (o['n'], o['digest']):
                        raise UpgradeVerificationFailed(f'The history ({t}) changed during the update (data before the update: {SNAP_DIR}/{self.snapshot}).')
        applied = list(self.marker.get('migrations') or [])
        ran = []
        for mid, text, fn, _touches in MIGRATIONS:
            if mid in applied:
                continue
            self.log(f'Data migration {mid}: {text}')
            fn(system)
            applied.append(mid)
            ran.append(mid)
        try:
            counts = system.store.counts()
        except Exception:  # noqa: BLE001 - the report is nice to have, never a reason to stop
            counts = {}
        m = self.marker
        history = list(m.get('history') or [])
        if self.snapshot or not m.get('version'):
            history.append({'from': (m.get('version') or ('earlier than 2.6' if self.snapshot else None)), 'to': self.version, 'at': now(),
                            'snapshot': self.snapshot, 'verified': bool(self.snapshot), 'migrations': ran, 'records': counts})
        self.marker = {'version': self.version, 'schema': self.schema, 'first_seen': m.get('first_seen') or now(), 'updated': now(),
                       'migrations': applied, 'history': history[-50:]}
        self._write()

    # ------------------------------------------------------------ for the screens and tools
    def info(self):
        m = self._read() or self.marker
        snaps = []
        root = os.path.join(self.data_dir, SNAP_DIR)
        if os.path.isdir(root):
            for n in sorted(os.listdir(root), reverse=True):
                p = os.path.join(root, n)
                if os.path.isdir(p):
                    size = sum(os.path.getsize(os.path.join(p, f)) for f in os.listdir(p))
                    snaps.append({'name': n, 'size': size})
        return {'version': m.get('version'), 'schema': m.get('schema'), 'first_seen': m.get('first_seen'), 'history': (m.get('history') or [])[-5:][::-1],
                'snapshots': snaps}


def check_now(system):
    """'Check my data now': integrity of the three databases and every hash / chain link / signature of the history."""
    problems = []
    for name, conn in (('bams.db', system.store.conn), ('auth.db', system.auth.conn), ('journal.db', system.journal.conn)):
        try:
            bad = [r[0] for r in conn.execute('PRAGMA integrity_check') if r[0] != 'ok']
        except sqlite3.Error as e:
            bad = [str(e)]
        problems += [f'{name}: {b}' for b in bad]
    rep = system.journal.verify(all_signatures=False)
    if not rep.get('ok'):
        problems += list(rep.get('problems') or ['the history did not verify'])[:20]
    return {'ok': not problems, 'problems': problems, 'checked_changes': rep.get('checked'), 'records': system.store.counts(), 'at': now()}
