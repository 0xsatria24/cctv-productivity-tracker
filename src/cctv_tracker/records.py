"""Optional report exports and segmented preview video, isolated from accounting."""
from contextlib import closing
import csv
from datetime import datetime, timezone
from fractions import Fraction
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from .persistence import Database
from .secure_store import atomic_write

DEFAULT_POLICY = {'data_enabled': False, 'data_interval_seconds': 60,
                  'video_enabled': False, 'video_segment_seconds': 60, 'max_storage_mb': 5120}
MIN_FREE_BYTES = 256 * 1024 * 1024


def storage_usage(root):
    total = 0
    for path in root.rglob('*'):
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            # A transfer SQLite journal can disappear while the writer commits.
            continue
    return total


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY):
        raise ValueError('Konfigurasi auto-save tidak lengkap')
    if any(type(value[k]) is not bool for k in ('data_enabled', 'video_enabled')):
        raise ValueError('Status auto-save harus on atau off')
    for key in ('data_interval_seconds', 'video_segment_seconds'):
        if type(value[key]) is not int or not 5 <= value[key] <= 3600:
            raise ValueError('Interval harus 5 sampai 3600 detik')
    if type(value['max_storage_mb']) is not int or not 512 <= value['max_storage_mb'] <= 1048576:
        raise ValueError('Batas penyimpanan harus 512 sampai 1048576 MB')
    return dict(value)


class VideoClip:
    def __init__(self, root, source, name, jpeg, mono, utc, duration):
        import av
        self.id, self.source, self.name = uuid4().hex, source, name
        self.started, self.utc, self.duration = mono, utc, duration
        self.last, self.frames, self.gaps = None, 0, 0
        self.path = root / (self.id + '.partial.mp4')
        self.container = av.open(str(self.path), 'w', format='mp4', options={'movflags': 'frag_keyframe+empty_moov+default_base_moof'})
        self.stream = None
        try:
            frame = self.decode(jpeg)
            self.width, self.height = frame.width, frame.height
            self.stream = self.container.add_stream('libx264', rate=5)
            self.stream.width, self.stream.height = self.width, self.height
            self.stream.pix_fmt = 'yuv420p'
            self.stream.time_base = Fraction(1, 1000)
            self.stream.codec_context.time_base = Fraction(1, 1000)
            self.stream.options = {'preset': 'ultrafast', 'crf': '23', 'tune': 'zerolatency', 'g': '5', 'bf': '0', 'threads': '1'}
            self.write(frame, mono)
        except Exception:
            self.container.close()
            raise

    @staticmethod
    def decode(jpeg):
        import av
        with av.open(io.BytesIO(jpeg), format='mjpeg') as image:
            frame = next(image.decode(video=0))
        # H.264 yuv420p needs even dimensions; pad at most one source pixel.
        return frame.reformat(width=frame.width + frame.width % 2, height=frame.height + frame.height % 2, format='yuv420p')

    def write(self, frame, mono):
        if (frame.width, frame.height) != (self.width, self.height):
            raise ValueError('Frame dimensions changed')
        if self.last is not None and mono <= self.last:
            return
        if self.last is not None and mono - self.last > .6:
            self.gaps += 1
        frame.pts = round((mono - self.started) * 1000)
        frame.time_base = Fraction(1, 1000)
        for packet in self.stream.encode(frame):
            self.container.mux(packet)
        self.last, self.frames = mono, self.frames + 1

    def finish(self):
        try:
            for packet in self.stream.encode():
                self.container.mux(packet)
        finally:
            self.container.close()
        destination = self.path.with_name(self.id + '.mp4')
        self.path.replace(destination)
        return destination, {'id': self.id, 'kind': 'video', 'source_id': self.source, 'camera_name': self.name,
            'created_at': self.utc, 'end_at': self.utc + max(0, self.last - self.started),
            'frames': self.frames, 'gaps': self.gaps, 'width': self.width, 'height': self.height,
            'format': 'H264_MP4', 'quality': 'monitoring_preview_max_5fps', 'audio': False}


class RecordingManager:
    """One bounded background writer. Does not change durable engine commits."""
    def __init__(self, database, live=None, fleet=None, *, timezone_name='Asia/Jakarta', clock=time.perf_counter, wall_clock=time.time):
        self.database = Path(database).resolve()
        self.root = self.database.parent / (self.database.stem + '-records')
        self.root.mkdir(parents=True, exist_ok=True)
        self.live, self.fleet, self.timezone = live, fleet, timezone_name
        self.clock, self.wall_clock = clock, wall_clock
        self.policy_path = self.root / 'policy.json'
        self.policy = validate_policy(json.loads(self.policy_path.read_text())) if self.policy_path.exists() else dict(DEFAULT_POLICY)
        self.catalog = self.root / 'catalog.sqlite3'
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, kind TEXT, metadata TEXT, bytes INTEGER)')
            db.execute('CREATE INDEX IF NOT EXISTS artifact_kind ON artifacts(kind)')
        self.lock, self.stop_event = RLock(), Event()
        self.thread, self.webcam = None, None
        self.clips, self.seen, self.last_exports, self.errors = {}, {}, {}, {}
        self.next_data = self.clock() + self.policy['data_interval_seconds']
        self.last_data, self.last_video = None, None
        with self._db() as db:
            for kind, attribute in (('data', 'last_data'), ('video', 'last_video')):
                row = db.execute('SELECT metadata FROM artifacts WHERE kind=? ORDER BY rowid DESC LIMIT 1', (kind,)).fetchone()
                if row:
                    setattr(self, attribute, json.loads(row[0])['created_at'])
        self.storage_bytes = storage_usage(self.root)
        self.next_storage_check = 0
        from .record_destinations import DestinationManager
        self.destinations = DestinationManager(self.root)

    def _db(self):
        return closing(sqlite3.connect(self.catalog, timeout=5))

    def _publish(self, path, metadata):
        metadata['bytes'] = path.stat().st_size
        atomic_write(self.root / (metadata['id'] + '.json'), json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode())
        with self._db() as db, db:
            db.execute('INSERT INTO artifacts VALUES(?,?,?,?)', (metadata['id'], metadata['kind'], json.dumps(metadata), metadata['bytes']))
        self.storage_bytes += metadata['bytes']
        try:
            self.destinations.enqueue(metadata['id'], self._artifact_files(metadata))
            self.errors.pop('upload-queue', None)
        except Exception:
            self.errors['upload-queue'] = 'File lokal tersimpan, tetapi belum masuk antrean upload. Gunakan Antrekan 50 file terbaru setelah penyimpanan pulih.'

    @staticmethod
    def _artifact_files(metadata):
        identifier = metadata['id']
        extensions = ('.report.json', '.csv', '.json') if metadata['kind'] == 'data' else ('.mp4', '.json')
        return [identifier + suffix for suffix in extensions]

    def enqueue_recent(self):
        config = self.destinations.status()['config']
        if not config['enabled'] or config['kind'] == 'local':
            raise ValueError('Simpan dan aktifkan tujuan cloud/server terlebih dahulu')
        with self._db() as db:
            recent = [json.loads(r[0]) for r in db.execute('SELECT metadata FROM artifacts ORDER BY rowid DESC LIMIT 50')]
        count = 0
        for metadata in recent:
            filenames = [f for f in self._artifact_files(metadata) if (self.root / f).is_file()]
            count += self.destinations.enqueue(metadata['id'], filenames) or 0
        return {'queued_files': count, 'records_checked': len(recent)}

    def configure(self, value):
        value = validate_policy(value)
        with self.lock:
            atomic_write(self.policy_path, json.dumps(value).encode())
            previous, self.policy = self.policy, value
            if previous['video_segment_seconds'] != value['video_segment_seconds'] or not value['video_enabled']:
                for source in list(self.clips):
                    self._finish(source)
            if previous['data_enabled'] != value['data_enabled'] or previous['data_interval_seconds'] != value['data_interval_seconds']:
                self.next_data = self.clock() + value['data_interval_seconds']
            if previous['video_enabled'] != value['video_enabled']:
                self.seen.clear()
                self.webcam = None
            if not value['video_enabled'] and self.fleet:
                self.fleet.subscribe('recording-service', [])
        return self.status()

    def submit_webcam(self, jpeg):
        # Keep only the latest frame; capture/inference never waits for encoding.
        if self.policy['video_enabled']:
            self.webcam = (bytes(jpeg), self.clock(), self.wall_clock())

    def _sources(self):
        rows = []
        if self.live:
            state = self.live.snapshot()
            rows.append({'id': 'primary', 'name': 'Webcam / RTSP utama', 'database': self.live.settings.database})
            if state.get('source') == 'RTSP_LIVE' and state['status'] == 'RUNNING':
                pair = self.live.preview_snapshot()
                if pair:
                    rows[-1]['frame'] = (pair['jpeg'], pair['monotonic_ns'] / 1e9, pair['utc_ms'] / 1000)
        if self.webcam:
            rows.append({'id': 'webcam', 'name': 'Webcam lokal', 'frame': self.webcam})
        if self.fleet:
            with self.fleet._lock:
                cameras = list(self.fleet._cameras.values())
            self.fleet.subscribe('recording-service', [c.id for c in cameras] if self.policy['video_enabled'] else [])
            for camera in cameras:
                row = {'id': camera.id, 'name': camera.name, 'database': camera.engine.settings.database}
                pair = camera.engine.preview_snapshot() if camera.engine.snapshot()['status'] == 'RUNNING' else None
                if pair:
                    row['frame'] = (pair['jpeg'], pair['monotonic_ns'] / 1e9, pair['utc_ms'] / 1000)
                else:
                    frame = camera.preview.frame()
                    if frame:
                        jpeg, utc_ms, sequence = frame
                        row['frame'] = (jpeg, self.clock() - max(0, self.wall_clock() - utc_ms / 1000), utc_ms / 1000)
                        row['frame_key'] = ('preview', sequence)
                rows.append(row)
        return rows

    def _capacity(self):
        now = self.clock()
        if now >= self.next_storage_check:
            self.storage_bytes = storage_usage(self.root)
            self.next_storage_check = now + 2
        if self.storage_bytes >= self.policy['max_storage_mb'] * 1048576 or shutil.disk_usage(self.root).free < MIN_FREE_BYTES:
            raise OSError('Batas penyimpanan tercapai atau ruang disk tersisa kurang dari 256 MB. Pindahkan file atau ubah batas penyimpanan.')

    def _finish(self, source):
        clip = self.clips.pop(source, None)
        if clip:
            try:
                path, metadata = clip.finish()
                self._publish(path, metadata)
                self.last_video = self.wall_clock()
            except Exception:
                self.errors[source] = 'Potongan video belum dapat diselesaikan. Periksa ruang disk dan akses folder record.'

    def _video(self, row, now):
        source, frame = row['id'], row.get('frame')
        clip = self.clips.get(source)
        if clip and (now - clip.started >= clip.duration or now - clip.last > 2):
            self._finish(source)
            clip = None
        if not frame or now - frame[1] > 2 or frame[1] > now + .1:
            return
        key = row.get('frame_key', frame[1])
        if self.seen.get(source) == key:
            return
        self.seen[source] = key
        self._capacity()
        if clip:
            decoded = VideoClip.decode(frame[0])
            if (decoded.width, decoded.height) != (clip.width, clip.height):
                self._finish(source)
                clip = None
            else:
                clip.write(decoded, frame[1])
        if not clip:
            self.clips[source] = VideoClip(self.root, source, row['name'], *frame, self.policy['video_segment_seconds'])
        self.errors.pop(source, None)

    def _data(self, row):
        from .dashboard import report
        if not row.get('database'):
            return
        with closing(Database(row['database'], migrate=False)) as db, db.conn:
            db.conn.execute('BEGIN')
            latest = db.conn.execute('SELECT id FROM engine_runs ORDER BY started_utc_us DESC LIMIT 1').fetchone()
            if not latest:
                return
            watermark = db.conn.execute('SELECT COALESCE(MAX(seq),0) FROM event_log').fetchone()[0]
            if self.last_exports.get(row['id']) == watermark:
                return
            value = report(db, run_id=latest['id'])
        self._capacity()
        identifier = uuid4().hex
        metadata = {'id': identifier, 'kind': 'data', 'source_id': row['id'], 'camera_name': row['name'],
                    'created_at': self.wall_clock(), 'format': 'JSON_CSV', 'run_id': latest['id'], 'committed_event_seq': watermark}
        payload = {'version': 1, 'timezone': self.timezone, 'identity_source': 'anonymous', **metadata, 'report': value}
        atomic_write(self.root / (identifier + '.report.json'), json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['camera_id', row['id'], 'timezone', self.timezone, 'run_id', latest['id'], 'start_utc_us', value['start_utc_us'], 'end_utc_us', value['end_utc_us']])
        columns = ['workspace_id', 'workspace', 'occupied_us', 'empty_us', 'unknown_us', 'eligible_us', 'utilization', 'coverage']
        writer.writerow(columns)
        for workspace in value['workstations']:
            safe = dict(workspace)
            if safe['workspace'].lstrip().startswith(('=', '+', '-', '@')):
                safe['workspace'] = "'" + safe['workspace']
            writer.writerow([safe[k] for k in columns])
        path = self.root / (identifier + '.csv')
        atomic_write(path, buffer.getvalue().encode('utf-8-sig'))
        self._publish(path, metadata)
        self.last_exports[row['id']] = watermark
        self.last_data = self.wall_clock()

    def tick(self):
        with self.lock:
            now, rows = self.clock(), self._sources()
            active = {row['id'] for row in rows}
            for source in list(self.clips):
                if not self.policy['video_enabled'] or source not in active:
                    self._finish(source)
            for row in rows:
                if self.policy['video_enabled']:
                    try:
                        self._video(row, now)
                    except Exception as error:
                        self._finish(row['id'])
                        self.errors[row['id']] = str(error) if isinstance(error, OSError) else 'Perekaman video gagal; periksa codec dan folder penyimpanan.'
            if self.policy['data_enabled'] and now >= self.next_data:
                self.next_data = now + self.policy['data_interval_seconds']
                for row in rows:
                    try:
                        self._data(row)
                        self.errors.pop('data:' + row['id'], None)
                    except Exception as error:
                        self.errors['data:' + row['id']] = str(error) if isinstance(error, OSError) else 'Auto-save laporan gagal; periksa database dan penyimpanan.'

    def startup(self):
        self.destinations.startup()
        self.thread = Thread(target=self._run, daemon=False, name='optional-record-writer')
        self.thread.start()

    def _run(self):
        while not self.stop_event.wait(.2):
            try:
                self.tick()
                with self.lock:
                    self.errors.pop('service', None)
            except Exception:
                with self.lock:
                    self.errors['service'] = 'Layanan auto-save terganggu. Periksa kamera dan folder penyimpanan.'

    def shutdown(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        with self.lock:
            for source in list(self.clips):
                self._finish(source)
            if self.fleet:
                self.fleet.subscribe('recording-service', [])
        self.destinations.shutdown()

    def status(self):
        with self.lock:
            with self._db() as db:
                files = [json.loads(r[0]) for r in db.execute('SELECT metadata FROM artifacts ORDER BY rowid DESC LIMIT 50')]
            return {'policy': dict(self.policy), 'folder': str(self.root), 'files': files,
                    'active_videos': [{'source_id': c.source, 'camera_name': c.name, 'frames': c.frames, 'started_at': c.utc} for c in self.clips.values()],
                    'errors': dict(self.errors), 'last_data_at': self.last_data, 'last_video_at': self.last_video,
                    'quality': 'monitoring_preview_max_5fps', 'storage_bytes': self.storage_bytes,
                    'unfinished_files': max(0, sum(1 for _ in self.root.glob('*.partial.mp4')) - len(self.clips))}

    def artifact(self, identifier, format):
        if not re.fullmatch('[0-9a-f]{32}', identifier):
            raise LookupError('File tidak ditemukan')
        with self._db() as db:
            row = db.execute('SELECT kind FROM artifacts WHERE id=?', (identifier,)).fetchone()
        allowed = {'data': {'json': '.report.json', 'csv': '.csv'}, 'video': {'mp4': '.mp4'}}
        suffix = allowed.get(row[0] if row else '', {}).get(format)
        if not suffix:
            raise LookupError('File tidak ditemukan')
        path = self.root / (identifier + suffix)
        if path.is_symlink() or not path.is_file():
            raise LookupError('File tidak ditemukan')
        return path
