"""Durable, optional copies of finalized records to NAS folders and cloud remotes."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from threading import Event, Lock, Thread
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .secure_store import SecureStore

DEFAULT_DESTINATION = {'enabled': False, 'kind': 'local', 'folder': '', 'remote': '',
    'prefix': 'CCTV', 'endpoint': '', 'bucket': '', 'region': 'us-east-1', 'provider': 'Other',
    'access_key': '', 'secret_key': '', 'session_token': ''}
SECRET_FIELDS = ('access_key', 'secret_key', 'session_token')
ARTIFACT_FILE = re.compile(r'[0-9a-f]{32}(?:\.report\.json|\.csv|\.json|\.mp4)')


def validate_destination(value, record_root, previous=None):
    if set(value) != set(DEFAULT_DESTINATION) or type(value['enabled']) is not bool:
        raise ValueError('Konfigurasi tujuan penyimpanan tidak lengkap')
    value = dict(value)
    if value['kind'] not in {'local', 'folder', 'rclone', 's3'}:
        raise ValueError('Jenis tujuan penyimpanan tidak didukung')
    if any(not isinstance(v, str) or len(v) > (8192 if k in SECRET_FIELDS else 2048) or any(ord(c) < 32 for c in v) for k,v in value.items() if k != 'enabled'):
        raise ValueError('Nilai tujuan penyimpanan tidak valid')
    prefix = value['prefix'].replace('\\', '/')
    if prefix.startswith('/') or any(p in {'.', '..'} for p in prefix.split('/')) or ':' in prefix:
        raise ValueError('Gunakan subfolder relatif tanpa titik traversal atau tanda titik dua')
    value['prefix'] = prefix.strip('/')
    if value['kind'] == 'local':
        return dict(DEFAULT_DESTINATION)
    if value['kind'] == 'folder':
        path = Path(value['folder']).expanduser()
        if not path.is_absolute():
            raise ValueError('Isi path folder absolut atau share NAS, misalnya D:\\CCTV atau \\\\NAS\\CCTV')
        root, target = Path(record_root).absolute(), path.absolute()
        if target == root or root in target.parents or target in root.parents:
            raise ValueError('Pilih folder tujuan di luar folder record dan direktori induknya')
        value['folder'] = str(target)
    elif value['kind'] == 'rclone':
        value['remote'] = value['remote'].removesuffix(':')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_. -]{0,99}', value['remote']):
            raise ValueError('Isi nama remote rclone yang sudah dikonfigurasi, tanpa path atau tanda titik dua')
    else:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value['bucket']):
            raise ValueError('Nama bucket S3 tidak valid')
        if value['provider'] not in {'AWS', 'Other', 'Minio', 'Cloudflare', 'Wasabi', 'DigitalOcean'}:
            raise ValueError('Provider S3 tidak didukung; gunakan Other untuk layanan kompatibel')
        if value['endpoint']:
            parsed = urlsplit(value['endpoint'])
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
                raise ValueError('Endpoint harus http(s)://host[:port], tanpa kredensial, query, atau path')
            try:
                parsed.port
            except ValueError:
                raise ValueError('Port endpoint tidak valid') from None
        elif value['provider'] != 'AWS':
            raise ValueError('Isi endpoint API S3 untuk provider ini')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value['region']):
            raise ValueError('Region S3 tidak valid')
        identity = ('kind','endpoint','bucket','region','provider')
        if previous and all(previous[k] == value[k] for k in identity):
            changed = any(value[k] and value[k] != previous[k] for k in ('access_key','secret_key'))
            for key in SECRET_FIELDS:
                if key != 'session_token' or not changed:
                    value[key] = value[key] or previous[key]
        if not value['access_key'] or not value['secret_key']:
            raise ValueError('Isi access key dan secret key S3; perubahan koneksi memerlukan kredensial kembali')
    if value['kind'] != 's3':
        for key in SECRET_FIELDS:
            value[key] = ''
    return value


class TransferFailure(RuntimeError):
    pass


def rclone_path():
    executable = 'rclone.exe' if os.name == 'nt' else 'rclone'
    candidates = [os.environ.get('CCTV_RCLONE_PATH'), shutil.which('rclone'),
        str(Path(sys.executable).parent.parent.parent / 'tools' / executable),
        str(Path(__file__).resolve().parents[2] / 'runtime/tools/rclone' / executable)]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


class StorageAdapter:
    def __init__(self, config):
        self.config = config

    def _command(self, *arguments, env=None, timeout=90):
        binary = rclone_path()
        if not binary:
            raise TransferFailure('rclone belum terpasang. Jalankan python scripts/setup_storage_transport.py atau pasang rclone di PATH.')
        try:
            process = subprocess.run([binary, *arguments, '--ask-password=false'], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired:
            raise TransferFailure('Transfer melewati batas waktu; antrean akan dicoba kembali.') from None
        if process.returncode:
            # Native diagnostics can contain secrets; never forward them to API/logs.
            raise TransferFailure('Transfer gagal. Periksa koneksi, izin, kredensial, kuota, dan konfigurasi remote.')
        return process.stdout.decode('utf-8')

    def _remote(self, key):
        config = self.config
        suffix = '/'.join(p for p in (config['prefix'], key) if p)
        if config['kind'] == 'rclone':
            return config['remote'] + ':' + suffix, None
        env = {**os.environ}
        options = {'TYPE':'s3', 'PROVIDER':config['provider'], 'ENV_AUTH':'false',
            'ACCESS_KEY_ID':config['access_key'], 'SECRET_ACCESS_KEY':config['secret_key'],
            'SESSION_TOKEN':config['session_token'], 'REGION':config['region'], 'ENDPOINT':config['endpoint'],
            'FORCE_PATH_STYLE':'true', 'NO_CHECK_BUCKET':'true'}
        env.update({'RCLONE_CONFIG_CCTVTRANSFER_' + k: v for k,v in options.items()})
        return 'cctvtransfer:' + config['bucket'] + '/' + suffix, env

    def _folder_target(self, key):
        root = Path(self.config['folder']).resolve()
        target = (root / self.config['prefix'] / key).resolve()
        if root not in target.parents:
            raise TransferFailure('Path tujuan tidak berada dalam folder yang dipilih')
        return target

    def put(self, source, key):
        source = Path(source)
        if any(p in {'.','..'} for p in key.split('/')) or key.startswith('/') or '\\' in key or ':' in key:
            raise TransferFailure('Nama file tujuan tidak valid')
        if self.config['kind'] == 'folder':
            target = self._folder_target(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.' + uuid4().hex + '.partial')
            try:
                with source.open('rb') as original, temporary.open('xb') as copy:
                    shutil.copyfileobj(original, copy, length=1024*1024)
                    copy.flush(); os.fsync(copy.fileno())
                if source.stat().st_size != temporary.stat().st_size or self._hash(source) != self._hash(temporary):
                    raise TransferFailure('Verifikasi file server lokal gagal')
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return
        target, env = self._remote(key)
        self._command('copyto', str(source), target, '--checksum', '--retries', '1', '--low-level-retries', '1',
            '--contimeout', '10s', '--timeout', '30s', '--transfers', '1', '--buffer-size', '4M', '--multi-thread-streams', '0',
            env=env, timeout=max(90,min(3600,source.stat().st_size/131072+60)))
        stat = json.loads(self._command('lsjson', target, '--stat', env=env, timeout=30))
        if stat.get('IsDir') or stat.get('Size') != source.stat().st_size:
            raise TransferFailure('Ukuran file di cloud belum terverifikasi')

    @staticmethod
    def _hash(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def probe(self, root):
        name = 'cctv-connection-test-' + uuid4().hex + '.txt'
        source = Path(root) / name
        source.write_text('CCTV storage connection check\n')
        written = False
        try:
            self.put(source, name); written = True
        finally:
            source.unlink(missing_ok=True)
            if written:
                if self.config['kind'] == 'folder':
                    self._folder_target(name).unlink()
                else:
                    target, env = self._remote(name)
                    self._command('deletefile', target, env=env, timeout=30)

    def remotes(self):
        value = json.loads(self._command('listremotes', '--json', timeout=10))
        rows = value.get('remotes', []) if isinstance(value, dict) else value
        normalized = [{k.lower():v for k,v in row.items()} for row in rows]
        return [{'name': str(row.get('name', '')).removesuffix(':'), 'type': row.get('type','')} for row in normalized]


class DestinationManager:
    def __init__(self, record_root, *, adapter_factory=StorageAdapter, clock=time.time):
        self.root = Path(record_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_root = self.root / 'transfer'
        self.state_root.mkdir(exist_ok=True)
        self.store = SecureStore(self.state_root / 'destination.protected')
        stored = self.store.decode(self.store.path.read_bytes()) if self.store.path.exists() else DEFAULT_DESTINATION
        self.config = validate_destination(stored, self.root)
        self.adapter_factory, self.clock = adapter_factory, clock
        self.database = self.state_root / 'queue.sqlite3'
        self.lock, self.stop_event = Lock(), Event()
        self.thread, self.test_thread = None, None
        self.test_state = {'state':'IDLE','message':'Belum diuji'}
        self.test_token = None
        self.test_destination = None
        with self._db() as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS uploads(id INTEGER PRIMARY KEY, destination TEXT, artifact_id TEXT,
                filename TEXT, state TEXT, attempts INTEGER DEFAULT 0, next_at REAL DEFAULT 0, error TEXT,
                completed_at REAL, UNIQUE(destination,filename))''')
            db.execute('CREATE INDEX IF NOT EXISTS upload_ready ON uploads(destination,state,next_at)')
            db.execute("UPDATE uploads SET state='RETRY',next_at=0 WHERE state='UPLOADING'")

    def _db(self):
        return closing(sqlite3.connect(self.database, timeout=5))

    @staticmethod
    def identity(config):
        return hashlib.sha256(json.dumps({k:v for k,v in config.items() if k != 'enabled'},sort_keys=True).encode()).hexdigest()

    def prepare(self, value):
        with self.lock:
            return validate_destination(value, self.root, self.config)

    def configure(self, value):
        config = self.prepare(value)
        with self.lock:
            self.store.save(config)
            self.config = config
            if self.test_destination != self.identity(config):
                self.test_token = None
                self.test_destination = None
                self.test_state = {'state':'IDLE','message':'Konfigurasi berubah; uji koneksi untuk memeriksa tujuan.'}
        return self.status()

    def enqueue(self, identifier, filenames):
        with self.lock:
            config = dict(self.config)
        if not config['enabled'] or config['kind'] == 'local':
            return
        destination = self.identity(config)
        with self._db() as db, db:
            before = db.total_changes
            for filename in filenames:
                if not ARTIFACT_FILE.fullmatch(filename) or not filename.startswith(identifier + '.'):
                    raise ValueError('Hanya file record selesai yang dapat dikirim')
                db.execute("INSERT OR IGNORE INTO uploads(destination,artifact_id,filename,state) VALUES(?,?,?,'PENDING')", (destination,identifier,filename))
            return db.total_changes - before

    def process_one(self):
        with self.lock:
            config = dict(self.config)
        if not config['enabled'] or config['kind'] == 'local':
            return False
        destination = self.identity(config)
        with self._db() as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM uploads WHERE destination=? AND state IN ('PENDING','RETRY') AND next_at<=? ORDER BY id LIMIT 1", (destination,self.clock())).fetchone()
            if not row:
                return False
            db.execute("UPDATE uploads SET state='UPLOADING',attempts=attempts+1 WHERE id=?", (row['id'],))
        try:
            source = self.root / row['filename']
            if not ARTIFACT_FILE.fullmatch(row['filename']) or source.is_symlink() or not source.is_file():
                raise TransferFailure('File lokal hilang atau sudah dipindahkan. Unggahan belum dapat dilakukan.')
            key = row['artifact_id'] + '/' + row['filename']
            self.adapter_factory(config).put(source, key)
            with self._db() as db, db:
                db.execute("UPDATE uploads SET state='COMPLETED',completed_at=?,error=NULL WHERE id=?", (self.clock(),row['id']))
        except Exception as error:
            attempts = row['attempts'] + 1
            message = str(error) if isinstance(error, TransferFailure) else 'Upload gagal. Periksa koneksi dan izin tujuan; file lokal tetap tersimpan.'
            with self._db() as db, db:
                db.execute('UPDATE uploads SET state=?,next_at=?,error=? WHERE id=?',
                    ('FAILED' if attempts >= 8 else 'RETRY',self.clock()+min(300,5*2**(attempts-1)),message,row['id']))
        return True

    def retry(self):
        with self.lock:
            if not self.config['enabled'] or self.config['kind'] == 'local':
                raise ValueError('Simpan dan aktifkan tujuan cloud/server terlebih dahulu')
            destination = self.identity(self.config)
        with self._db() as db, db:
            db.execute("UPDATE uploads SET state='PENDING',attempts=0,next_at=0,error=NULL WHERE destination=? AND state IN ('FAILED','RETRY')", (destination,))
        return self.status()

    def test(self, value):
        config = self.prepare(value)
        if config['kind'] == 'local':
            with self.lock:
                self.test_state = {'state':'COMPLETED','message':'File disimpan di folder lokal aplikasi.'}
                return dict(self.test_state)
        with self.lock:
            if self.test_thread and self.test_thread.is_alive():
                raise ValueError('Uji koneksi masih berjalan')
            self.test_state = {'state':'RUNNING','message':'Membuat, memverifikasi, lalu menghapus file uji pada tujuan.'}
            token = self.test_token = uuid4().hex
            self.test_destination = self.identity(config)
            def run():
                try:
                    self.adapter_factory(config).probe(self.state_root)
                    result = {'state':'COMPLETED','message':'Koneksi berhasil: file uji ditulis, diverifikasi, lalu dihapus.'}
                except Exception as error:
                    result = {'state':'FAILED','message':str(error) if isinstance(error,TransferFailure) else 'Uji koneksi gagal. Periksa path, izin, kredensial dan koneksi.'}
                with self.lock:
                    if self.test_token == token:
                        self.test_state = result
            self.test_thread = Thread(target=run,daemon=True,name='record-destination-probe')
            self.test_thread.start()
        return {'state':'RUNNING'}

    def discover(self):
        return {'available':bool(rclone_path()),'remotes':StorageAdapter(DEFAULT_DESTINATION).remotes() if rclone_path() else []}

    def startup(self):
        def run():
            while not self.stop_event.wait(.5):
                try:
                    self.process_one()
                except Exception:
                    # Accounting and capture stay independent of storage outages.
                    continue
        self.thread = Thread(target=run,daemon=True,name='record-destination-upload')
        self.thread.start()

    def shutdown(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def status(self):
        with self.lock:
            config, test = dict(self.config), dict(self.test_state)
        destination = self.identity(config)
        flags = {key:bool(config.pop(key)) for key in SECRET_FIELDS}
        with self._db() as db:
            counts = dict(db.execute('SELECT state,COUNT(*) FROM uploads WHERE destination=? GROUP BY state',(destination,)))
            paused = db.execute("SELECT COUNT(*) FROM uploads WHERE destination<>? AND state<>'COMPLETED'",(destination,)).fetchone()[0]
            db.row_factory = sqlite3.Row
            recent = [dict(r) for r in db.execute('SELECT id,filename,state,attempts,error,completed_at FROM uploads WHERE destination=? ORDER BY id DESC LIMIT 10',(destination,))]
        binary = rclone_path()
        setup = '& ' + "'" + binary.replace("'", "''") + "' config" if binary and os.name == 'nt' else 'rclone config'
        return {'config':config,'secrets_configured':flags,'counts':counts,'paused_other_destination':paused,
            'recent':recent,'test':test,'rclone_available':bool(binary),'setup_command':setup,'local_staging':str(self.root)}
