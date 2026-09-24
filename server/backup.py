"""Backups for the SQLite database and the uploaded files.

  * A consistent copy of the database is taken with SQLite's online backup API
    and verified with an integrity check before it is kept.
  * Uploaded photos/documents are never changed or deleted by the app, so they
    are mirrored incrementally (only new files are copied).
  * Every backup is also copied to each "extra_backup_dirs" folder from
    config.json (e.g. a network drive) when that folder is reachable.
  * The user accounts (auth.db) are copied next to each backup as auth_<time>.db.
    A restore never touches them, so it cannot bring back a deleted user or an
    old password.
  * Only automatic backups are pruned (oldest first); manual, pre-import and
    pre-restore backups are kept forever.
"""
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime

AUTO_KINDS = ('auto', 'startup')
NAME_RE = re.compile(r'^bams_\d{8}_\d{6}_[a-z-]+\.db$')


class Backups:
    def __init__(self, store, uploads_dir, backup_dir, extra_dirs=(), keep_auto=200, interval_hours=6, log=print, auth=None):
        self.store = store
        self.auth = auth
        self.uploads_dir = uploads_dir
        self.dir = backup_dir
        self.extra = [d for d in extra_dirs if d]
        self.keep_auto = keep_auto
        self.interval = max(0.25, float(interval_hours)) * 3600
        self.log = log
        self.last_error = ''
        self.last_version = None
        self.last_time = 0
        os.makedirs(os.path.join(self.dir, 'db'), exist_ok=True)

    # ------------------------------------------------------------ create
    def create(self, kind='manual'):
        name = f'bams_{datetime.now():%Y%m%d_%H%M%S}_{kind}.db'
        dest = os.path.join(self.dir, 'db', name)
        tmp = dest + '.tmp'
        with self.store.lock:
            version = self.store.version()
            target = sqlite3.connect(tmp)
            try:
                self.store.conn.backup(target)
            finally:
                target.close()
        chk = sqlite3.connect(tmp)
        try:
            result = chk.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            chk.close()
        if result != 'ok':
            os.remove(tmp)
            raise RuntimeError('Backup failed the integrity check: ' + result)
        os.replace(tmp, dest)
        auth_copy = None
        if self.auth:
            auth_copy = os.path.join(self.dir, 'db', 'auth' + name[4:])
            self.auth.backup_to(auth_copy)
        self._mirror_uploads(os.path.join(self.dir, 'uploads'))
        self.last_version, self.last_time = version, time.time()

        errors = []
        for extra in self.extra:
            try:
                os.makedirs(os.path.join(extra, 'db'), exist_ok=True)
                shutil.copy2(dest, os.path.join(extra, 'db', name))
                if auth_copy:
                    shutil.copy2(auth_copy, os.path.join(extra, 'db', os.path.basename(auth_copy)))
                self._mirror_uploads(os.path.join(extra, 'uploads'))
            except OSError as e:
                errors.append(f'{extra}: {e}')
        self.last_error = '; '.join(errors)
        if errors:
            self.log('Extra backup copy failed: ' + self.last_error)
        self._prune()
        self.log(f'Backup created: {name}')
        return name

    def _mirror_uploads(self, target):
        for root, _, files in os.walk(self.uploads_dir):
            rel = os.path.relpath(root, self.uploads_dir)
            out = os.path.join(target, rel)
            for f in files:
                d = os.path.join(out, f)
                if not os.path.exists(d):
                    os.makedirs(out, exist_ok=True)
                    shutil.copy2(os.path.join(root, f), d)

    def _prune(self):
        autos = [b for b in self.list() if b['kind'] in AUTO_KINDS]
        for b in autos[self.keep_auto:]:
            for n in (b['name'], 'auth' + b['name'][4:]):
                try:
                    os.remove(os.path.join(self.dir, 'db', n))
                except OSError:
                    pass

    # ------------------------------------------------------------ list / restore
    def list(self):
        out = []
        folder = os.path.join(self.dir, 'db')
        for n in os.listdir(folder):
            if NAME_RE.match(n):
                st = os.stat(os.path.join(folder, n))
                out.append({'name': n, 'size': st.st_size, 'kind': n[:-3].split('_', 3)[3],
                            'time': datetime.strptime(n[5:20], '%Y%m%d_%H%M%S').isoformat(timespec='seconds')})
        return sorted(out, key=lambda b: b['name'], reverse=True)

    def restore(self, name):
        if not NAME_RE.match(name or ''):
            raise ValueError('Unknown backup')
        src_path = os.path.join(self.dir, 'db', name)
        if not os.path.exists(src_path):
            raise ValueError('Backup file not found')
        src = sqlite3.connect(src_path)
        try:
            if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('That backup file is damaged - choose another one')
            safety = self.create('pre-restore')
            with self.store.lock:
                src.backup(self.store.conn)
                self.store.conn.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1000000 WHERE key='data_version'")
        finally:
            src.close()
        self.store.reopen()
        return safety

    # ------------------------------------------------------------ scheduler
    def start(self):
        def loop():
            while True:
                time.sleep(600)
                try:
                    if self.store.version() != self.last_version and time.time() - self.last_time >= self.interval:
                        self.create('auto')
                except Exception as e:  # never let the scheduler die
                    self.last_error = str(e)
                    self.log('Automatic backup failed: ' + str(e))
        threading.Thread(target=loop, daemon=True, name='backup').start()
