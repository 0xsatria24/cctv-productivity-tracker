"""Verified SQLite snapshots and offline, recoverable restore transactions."""
import argparse
from contextlib import closing, ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from threading import Event, Lock, Thread
import time
from uuid import uuid4

from .lease import EngineLease
from .persistence import Database
from .secure_store import atomic_write, SecureStore

ID = re.compile(r'[0-9]{8}T[0-9]{6}-[0-9a-f]{12}')


def app_lock_path(database):
    return Path(database).with_suffix('.service')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_database(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Backup database integrity check failed')
        if db.execute('PRAGMA user_version').fetchone()[0] != 3:
            raise ValueError('Backup schema does not match this release')
        # Verify the complete installed migration chain without mutating the backup.
        from importlib.resources import files
        checks = dict(db.execute('SELECT version,sha256 FROM runtime_migration_checksums'))
        for i, name in enumerate(('001_initial.sql', '002_assignments.sql', '003_live.sql'), 1):
            if checks.get(i) != hashlib.sha256(files('cctv_tracker').joinpath('resources', name).read_text(encoding='utf-8').encode()).hexdigest():
                raise ValueError('Backup migration checksum mismatch')


class BackupManager:
    def __init__(self, database, fleet=None):
        self.database = Path(database).resolve()
        self.fleet = fleet
        self.fleet_root = self.database.parent / (self.database.stem + '-fleet')
        self.root = self.database.parent / (self.database.stem + '-backups')
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = self.root / 'restore-pending.json'
        self.receipt = self.root / 'restore-receipt.json'
        self.policy_path = self.root / 'policy.json'
        self.status_path = self.root / 'status.json'
        self.lock, self.stop_event = Lock(), Event()
        self.thread = None
        self.manual = None
        self.request_lock = Lock()
        self.policy = json.loads(self.policy_path.read_text()) if self.policy_path.exists() else {'enabled': True, 'interval_hours': 24, 'keep_days': 30}
        self.state = json.loads(self.status_path.read_text()) if self.status_path.exists() else {'last_success': None, 'last_error': None}

    def members(self):
        items = {'replay.sqlite3': self.database, 'primary-live.sqlite3': self.database.with_name(self.database.stem + '-live.sqlite3')}
        if self.fleet_root.exists():
            for path in self.fleet_root.iterdir():
                if re.fullmatch(r'[0-9a-f]{32}-live\.sqlite3', path.name) or path.name in {'cameras.protected', 'cameras.key'}:
                    items['fleet/' + path.name] = path
        return {key: value for key, value in items.items() if value.is_file()}

    def target(self, name):
        if name == 'replay.sqlite3':
            return self.database
        if name == 'primary-live.sqlite3':
            return self.database.with_name(self.database.stem + '-live.sqlite3')
        if re.fullmatch(r'fleet/([0-9a-f]{32}-live\.sqlite3|cameras\.protected|cameras\.key)', name):
            return self.fleet_root / name.split('/')[1]
        raise ValueError('Unsupported backup member')

    def _status(self, **values):
        self.state.update(values)
        atomic_write(self.status_path, json.dumps(self.state).encode())

    def create(self, *, reason='manual'):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Backup sedang berjalan')
        backup_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-') + uuid4().hex[:12]
        staging = self.root / ('.partial-' + backup_id)
        try:
            staging.mkdir()
            manifest = {'version': 1, 'id': backup_id, 'created_at': time.time(), 'reason': reason,
                        'consistency': 'independent SQLite snapshots; no cross-camera transaction', 'files': {}}
            with ExitStack() as stack:
                if self.fleet:
                    stack.enter_context(self.fleet._lock)
                members = self.members()
                config_bytes = {name: source.read_bytes() for name, source in members.items() if not name.endswith('.sqlite3')}
            for name, source in members.items():
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if name.endswith('.sqlite3'):
                    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as original, closing(sqlite3.connect(destination)) as copy:
                        deadline = time.monotonic() + 60
                        def progress(status, remaining, total):
                            if time.monotonic() > deadline:
                                raise TimeoutError('Backup exceeded time limit')
                        original.backup(copy, pages=256, progress=progress, sleep=0.02)
                        copy.execute('PRAGMA journal_mode=DELETE')
                    verify_database(destination.resolve())
                else:
                    destination.write_bytes(config_bytes[name])
                    destination.chmod(0o600)
                manifest['files'][name] = {'sha256': digest(destination), 'bytes': destination.stat().st_size, 'snapshot_at': time.time()}
            if not manifest['files']:
                raise ValueError('Tidak ada database untuk dicadangkan')
            atomic_write(staging / 'manifest.json', json.dumps(manifest, indent=2).encode())
            staging.rename(self.root / backup_id)
            self._status(last_success=time.time(), last_error=None, last_id=backup_id)
            self.prune()
            return manifest
        except Exception:
            self._status(last_error='Backup gagal. Periksa ruang disk dan akses penyimpanan.')
            raise
        finally:
            self.lock.release()

    def verify(self, backup_id):
        if not ID.fullmatch(backup_id):
            raise ValueError('Invalid backup ID')
        root = self.root / backup_id
        value = json.loads((root / 'manifest.json').read_text())
        if value.get('version') != 1 or value.get('id') != backup_id or not value.get('files'):
            raise ValueError('Invalid backup manifest')
        for name, metadata in value['files'].items():
            self.target(name)
            source = root / name
            if source.is_symlink() or not source.is_file() or digest(source) != metadata['sha256']:
                raise ValueError('Backup checksum mismatch')
            if name.endswith('.sqlite3'):
                verify_database(source.resolve())
        return value

    def list(self):
        rows = []
        for path in sorted(self.root.iterdir(), reverse=True):
            if ID.fullmatch(path.name) and path.is_dir() and (path / 'manifest.json').is_file():
                try:
                    manifest = json.loads((path / 'manifest.json').read_text())
                    rows.append({'id': path.name, 'created_at': manifest['created_at'], 'reason': manifest['reason'],
                                 'bytes': sum(f['bytes'] for f in manifest['files'].values())})
                except (ValueError, KeyError):
                    continue
        return rows

    def prune(self):
        # Only finalized application-owned snapshots, keeping at least the newest two.
        if self.journal.exists():
            return
        for row in self.list()[2:]:
            if row['created_at'] < time.time() - self.policy['keep_days'] * 86400 and row['reason'] != 'pre-restore':
                directory = self.root / row['id']
                if directory.resolve().parent == self.root.resolve() and not directory.is_symlink():
                    shutil.rmtree(directory)

    def configure(self, enabled, keep_days):
        if type(enabled) is not bool or type(keep_days) is not int or not 1 <= keep_days <= 365:
            raise ValueError('Invalid backup policy')
        with self.lock:
            self.policy = {'enabled': enabled, 'interval_hours': 24, 'keep_days': keep_days}
            atomic_write(self.policy_path, json.dumps(self.policy).encode())
        return self.status()

    def status(self):
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        return {'policy': self.policy, 'state': self.state, 'busy': self.lock.locked() or bool(self.manual and self.manual.is_alive()), 'backups': self.list(),
                'restore_command': f'& {quote(sys.executable)} -m cctv_tracker.maintenance --database {quote(self.database)} restore',
                'restore_pending': self.journal.exists(),
                'restore_receipt': json.loads(self.receipt.read_text()) if self.receipt.exists() else None}

    def request_backup(self):
        with self.request_lock:
            if self.lock.locked() or self.manual and self.manual.is_alive():
                raise ValueError('Backup masih berjalan')
            def run():
                try:
                    self.create()
                except Exception:
                    pass
            self.manual = Thread(target=run, daemon=False, name='manual-backup')
            self.manual.start()
            return {'status': 'QUEUED'}

    def startup(self):
        self.thread = Thread(target=self._run, daemon=True, name='daily-backup')
        self.thread.start()

    def _run(self):
        while not self.stop_event.wait(30):
            if self.policy['enabled'] and time.time() - (self.state['last_success'] or 0) >= 86400:
                try:
                    self.create(reason='scheduled')
                except Exception:
                    pass

    def shutdown(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=65)
        if self.manual:
            self.manual.join(timeout=65)

    def restore(self, backup_id):
        """Offline only. A durable journal blocks app startup after partial restore."""
        manifest = self.verify(backup_id)
        root = self.root / backup_id
        if 'fleet/cameras.protected' in manifest['files']:
            from .fleet import CameraFleet
            # Decode before changing anything. DPAPI restores require the same OS account.
            value = SecureStore(root / 'fleet/cameras.protected').decode((root / 'fleet/cameras.protected').read_bytes())
            CameraFleet._validate_records(value)
            for row in value['cameras']:
                if f"fleet/{row['id']}-live.sqlite3" not in manifest['files']:
                    raise ValueError('Backup is missing a camera database')
        with ExitStack() as stack:
            stack.callback((lease := EngineLease(app_lock_path(self.database))).close)
            paths = set(self.members().values()) | {self.target(name) for name in manifest['files']}
            for path in sorted(paths):
                if path.suffix == '.sqlite3':
                    path.parent.mkdir(parents=True, exist_ok=True)
                    stack.callback(EngineLease(path).close)
            if self.journal.exists():
                transaction = json.loads(self.journal.read_text())
                if transaction['backup_id'] != backup_id:
                    raise ValueError('Resume the pending restore before selecting another backup')
            else:
                safety = self.create(reason='pre-restore')
                transaction = {'backup_id': backup_id, 'safety_backup_id': safety['id'], 'started_at': time.time()}
                atomic_write(self.journal, json.dumps(transaction).encode())
            for name in manifest['files']:
                target = self.target(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                if name.endswith('.sqlite3'):
                    with closing(sqlite3.connect((root / name).as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as destination:
                        source.backup(destination)
                    verify_database(target.resolve())
                else:
                    atomic_write(target, (root / name).read_bytes())
            # Restoring a snapshot predating the fleet must also restore the empty catalog.
            if 'fleet/cameras.protected' not in manifest['files'] and (self.fleet_root / 'cameras.protected').exists():
                SecureStore(self.fleet_root / 'cameras.protected').save({'version': 1, 'cameras': []})
            result = {**transaction, 'completed_at': time.time(), 'verified': True}
            atomic_write(self.receipt, json.dumps(result).encode())
            self.journal.unlink()
            return result


def main():
    parser = argparse.ArgumentParser(description='Verified backup and offline restore for the dashboard edition')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('command', choices=['backup', 'list', 'verify', 'restore'])
    parser.add_argument('--backup-id')
    args = parser.parse_args()
    manager = BackupManager(args.database)
    try:
        if args.command in {'verify', 'restore'} and not args.backup_id:
            parser.error('--backup-id is required')
        result = manager.create() if args.command == 'backup' else manager.list() if args.command == 'list' else getattr(manager, args.command)(args.backup_id)
        print(json.dumps(result, indent=2))
    except Exception as error:
        parser.exit(1, f'{type(error).__name__}: maintenance failed; stop the application before restore and check the backup/account.\n')


if __name__ == '__main__':
    main()
