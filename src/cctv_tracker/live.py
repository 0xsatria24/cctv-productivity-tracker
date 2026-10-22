"""One active live source, one accounting thread, separate live SQLite history."""
from concurrent.futures import Future
from collections import deque
from contextlib import closing
from dataclasses import asdict, replace
import copy
import json
import logging
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
import time
from uuid import uuid4

from .config import Rules, Zone
from .persistence import Database, now_us
from .pipeline import Pipeline
from .vision import Detection
from .rtsp import RtspCapture, validate_rtsp_url
from .webcam import MODEL_SHA256

SOURCES = {'WEBCAM_LIVE', 'RTSP_LIVE'}
MODEL_MANIFEST = {'license': 'Apache-2.0', 'source': 'OpenCV Zoo YOLOX 47534e27c9851bb1128ccc0102f1145e27f23f98',
                  'threshold': 0.45, 'nms_iou': 0.5, 'provider': 'CPUExecutionProvider'}


class AccountingFailure(RuntimeError):
    pass


def validate_calibration(value):
    if set(value) != {'width', 'height', 'zones', 'rules', 'camera_key'}:
        raise ValueError('Konfigurasi kalibrasi tidak lengkap')
    width, height = value['width'], value['height']
    if not isinstance(value['camera_key'], str) or len(value['camera_key']) != 64 or any(c not in '0123456789abcdef' for c in value['camera_key']):
        raise ValueError('Identitas konfigurasi kamera tidak valid')
    if type(width) is not int or type(height) is not int or not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError('Dimensi kalibrasi tidak valid')
    if not isinstance(value['zones'], list) or not 1 <= len(value['zones']) <= 16:
        raise ValueError('Kalibrasikan 1 sampai 16 zona')
    zones = tuple(Zone(**{**z, 'polygon': tuple(tuple(p) for p in z['polygon'])}) for z in value['zones'])
    if len({z.id for z in zones}) != len(zones) or any(len(z.id) > 40 or len(z.name) > 80 or not z.name.strip() or not z.exclusive_group.strip() or len(z.exclusive_group) > 40 for z in zones):
        raise ValueError('ID zona harus unik; nama maksimal 80 karakter')
    rules = Rules(**value['rules'])
    if not 0.1 <= rules.occupied_confirm_seconds <= 60 or not 0.1 <= rules.empty_confirm_seconds <= 120 or not 0.5 <= rules.max_evidence_gap_seconds <= 10:
        raise ValueError('Batas konfirmasi/gap di luar rentang live yang didukung')
    return zones, rules


class LiveController:
    def __init__(self, settings, detector, *, capture_factory=RtspCapture):
        self.settings = replace(settings, database=settings.database.with_name(settings.database.stem + '-live.sqlite3'), zones=())
        self.detector, self.capture_factory = detector, capture_factory
        self.lock, self.command_lock, self.stop_event = Lock(), Lock(), Event()
        self.frames = Queue(maxsize=1)
        self.thread = None
        self.profiles = {}
        self.last_submitted = 0
        self.preview = None
        self.preview_history = deque(maxlen=8)
        self.state = {'status': 'IDLE', 'source': None, 'session_id': None, 'run_id': None, 'camera_health': 'OFFLINE', 'processed': 0, 'error': None, 'latest': None}
        with closing(Database(self.settings.database)) as db:
            for row in db.conn.execute('SELECT * FROM live_calibrations'):
                configuration = json.loads(row['configuration_json'])
                validate_calibration(configuration)
                self.profiles[row['source_kind']] = {**configuration, 'revision': row['revision']}

    def snapshot(self):
        with self.lock:
            value = copy.deepcopy(self.state)
            value['calibrations'] = copy.deepcopy(self.profiles)
        latest = value.get('latest')
        if latest and (time.perf_counter_ns() - latest['processed_monotonic_ns']) / 1e9 > 3:
            value['latest'] = None
        return value

    def _update(self, **values):
        with self.lock:
            self.state.update(values)

    def save_calibration(self, source, configuration):
        if source not in SOURCES:
            raise ValueError('Sumber live tidak valid')
        validate_calibration(configuration)
        with self.command_lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Hentikan pencatatan sebelum mengubah kalibrasi')
            revision = self.profiles.get(source, {}).get('revision', 0) + 1
            with closing(Database(self.settings.database)) as db, db.transaction() as conn:
                conn.execute('INSERT INTO live_calibrations VALUES(?,?,?,?) ON CONFLICT(source_kind) DO UPDATE SET revision=excluded.revision,configuration_json=excluded.configuration_json,saved_utc_us=excluded.saved_utc_us',
                             (source, revision, json.dumps(configuration), now_us()))
            with self.lock:
                self.profiles[source] = {**configuration, 'revision': revision}
        return self.snapshot()

    def start(self, source, url=None, *, preview_only=False, camera_key=None):
        if source not in SOURCES:
            raise ValueError('Sumber live tidak valid')
        if source == 'RTSP_LIVE':
            url = validate_rtsp_url(url or '')
            from hashlib import sha256
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            camera_key = sha256(f'{parsed.scheme}://{parsed.hostname}:{parsed.port or 554}{parsed.path}?{parsed.query}'.encode()).hexdigest()
        with self.command_lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Satu sesi live masih berjalan; hentikan sebelum memulai sesi lain')
            profile = self.profiles.get(source)
            if not profile and not preview_only:
                raise ValueError('Simpan kalibrasi zona untuk sumber ini terlebih dahulu')
            if not preview_only and camera_key != profile['camera_key']:
                raise ValueError('Kamera berbeda dari kalibrasi tersimpan. Kalibrasikan kamera ini terlebih dahulu')
            zones, rules = validate_calibration({k: v for k, v in profile.items() if k != 'revision'}) if profile else ((), Rules(max_evidence_gap_seconds=3))
            camera_id = self.settings.camera_id if self.settings.camera_id != 'camera-1' else source.lower() + '-primary'
            config = replace(self.settings, camera_id=camera_id, zones=zones, rules=rules,
                             inference_fps=5, frame_stale_seconds=rules.max_evidence_gap_seconds)
            session = str(uuid4())
            self.stop_event.clear()
            self.last_submitted = 0
            self.preview = None
            self.preview_history.clear()
            self._update(status='STARTING', source=source, session_id=session, run_id=None, camera_health='RECONNECTING', processed=0, error=None, latest=None, preview_only=preview_only, camera_key=camera_key)
            self.thread = Thread(target=self._run, args=(config, profile, source, session, url, preview_only), name='live-occupancy', daemon=False)
            self.thread.start()
        return self.snapshot()

    def stop(self, session=None):
        with self.command_lock:
            current = self.snapshot()
            if session and session != current['session_id']:
                raise ValueError('Sesi telah berubah; stop lama diabaikan')
            self.stop_event.set()
            if self.thread and self.thread.is_alive():
                self._update(status='STOPPING')
        return self.snapshot()

    def shutdown(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=12)

    def submit(self, jpeg, session, sequence):
        with self.command_lock:
            state = self.snapshot()
            if state['status'] != 'RUNNING' or state['source'] != 'WEBCAM_LIVE' or session != state['session_id']:
                raise ValueError('Sesi webcam tidak aktif atau sudah berubah')
            if sequence <= self.last_submitted:
                raise ValueError('Frame duplikat atau tidak berurutan')
            future = Future()
            try:
                self.frames.put_nowait({'jpeg': jpeg, 'future': future, 'monotonic_ns': time.perf_counter_ns(), 'generation': session})
            except Full:
                raise BlockingIOError('Engine sibuk; kirim frame baru setelah respons diterima') from None
            self.last_submitted = sequence
        return future.result(timeout=10)

    def preview_jpeg(self):
        frame = self.preview_frame()
        return frame[0] if frame else None

    def preview_frame(self, frame_seq=None, run_id=None):
        with self.lock:
            value = (next((frame for frame in reversed(self.preview_history)
                           if frame[2]['X-Frame-Sequence'] == str(frame_seq)
                           and (run_id is None or frame[2]['X-Run-Id'] == run_id)), None)
                     if frame_seq is not None else self.preview)
        if not value or time.perf_counter_ns() - value[0] > 3e9:
            return None
        return value[1], value[2]

    def _run(self, config, profile, source, session, url, preview_only):
        pipeline, capture, db = None, None, None
        seq, last_mono, last_valid, generation = 0, 0, time.perf_counter(), session
        retry_at, attempts = 0.0, 0
        try:
            # Verify/load the same licensed model before creating a monitoring run.
            import cv2
            import numpy as np
            warmup = cv2.imencode('.jpg', np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes()
            for attempt in range(20):
                try:
                    self.detector.detect(warmup)
                    break
                except BlockingIOError:
                    if self.stop_event.wait(0.2) or attempt == 19:
                        raise
            db = Database(config.database)
            anchor_mono, anchor_utc = time.perf_counter_ns(), now_us()
            if not preview_only:
                pipeline = Pipeline(config, db, anchor_utc, source, getattr(self.detector, 'sha', MODEL_SHA256), {**getattr(self.detector, 'manifest', MODEL_MANIFEST), 'calibration_revision': profile['revision'], 'calibration_width': profile['width'], 'calibration_height': profile['height']}, live_events=True)
            self._update(status='RUNNING', run_id=pipeline.writer.run_id if pipeline else None)

            def account(detections, mono, unavailable=None):
                nonlocal seq, last_mono
                if mono <= last_mono:
                    raise ValueError('Frame terlalu lama; tidak menjadi bukti pencatatan')
                seq += 1
                # Anchor UTC once; elapsed durations follow the server monotonic clock.
                try:
                    result = pipeline.feed(detections, anchor_utc + (mono - anchor_mono) // 1000, mono, seq, generation, unavailable) if pipeline else {}
                except Exception as error:
                    raise AccountingFailure('Accounting stopped at committed checkpoint') from error
                last_mono = mono
                return result

            while not self.stop_event.is_set():
                item = None
                if source == 'WEBCAM_LIVE':
                    try:
                        item = self.frames.get(timeout=0.2)
                    except Empty:
                        pass
                else:
                    if capture is None and time.perf_counter() >= retry_at:
                        capture = self.capture_factory(url, config)
                        self._update(camera_health='RECONNECTING')
                    if capture:
                        item = capture.read(timeout=0.2)
                        if (item and item.get('error')) or not capture.process.is_alive() or time.perf_counter() - max(capture.started, last_valid) > config.open_timeout_seconds + config.read_timeout_seconds:
                            capture.close(); capture = None
                            attempts += 1
                            retry_at = time.perf_counter() + min(8, 2 ** min(attempts, 3))
                            self._update(camera_health='RECONNECTING', error='RTSP terputus; mencoba sambung kembali', latest=None)
                            item = None
                    else:
                        self.stop_event.wait(0.2)
                future = item.get('future') if item else None
                try:
                    if item:
                        generation = item['generation']
                        mono = item['monotonic_ns']
                        if mono <= last_mono or time.perf_counter_ns() - mono > config.frame_stale_seconds * 1e9:
                            raise ValueError('Frame stale; kirim frame terbaru')
                        result = self.detector.detect(item['jpeg'])
                        if not preview_only and abs(result['width'] / result['height'] - profile['width'] / profile['height']) > 0.02:
                            raise ValueError('Rasio frame berubah. Hentikan sesi dan kalibrasikan ulang zona')
                        if time.perf_counter_ns() - mono > config.frame_stale_seconds * 1e9:
                            raise ValueError('Inferensi terlalu lambat; hasil tidak menjadi bukti')
                        if self.stop_event.is_set():
                            raise ValueError('Sesi telah berhenti; hasil inferensi diabaikan')
                        accounting = account([Detection(tuple(d['box']), d['confidence']) for d in result['detections']], mono)
                        last_valid = mono / 1e9; attempts = 0
                        result.update(accounting)
                        result.update(source=source, recorded=not preview_only, processed_monotonic_ns=time.perf_counter_ns())
                        with self.lock:
                            self.preview = (time.perf_counter_ns(), item['jpeg'],
                                            {'X-Frame-Sequence': str(accounting.get('frame_seq', '')),
                                             'X-Run-Id': str(accounting.get('run_id', '')),
                                             'X-Mapping-Version': str(accounting.get('mapping_version', ''))})
                            self.preview_history.append(self.preview)
                            self.state.update(camera_health='ONLINE', error=None, processed=self.state['processed'] + 1, latest=result)
                        if future and not future.done():
                            future.set_result(result)
                except (ValueError, BlockingIOError) as error:
                    self._update(camera_health='DEGRADED', error=str(error), latest=None)
                    if future and not future.done():
                        future.set_exception(error)
                except Exception:
                    if future and not future.done():
                        future.set_exception(RuntimeError('Engine gagal memproses frame; periksa status sesi'))
                    raise
                if time.perf_counter() - last_valid > config.frame_stale_seconds:
                    account([], time.perf_counter_ns(), 'FRAME_STALE' if source == 'WEBCAM_LIVE' else 'CAMERA_OFFLINE')
                    self._update(camera_health='DEGRADED' if source == 'WEBCAM_LIVE' else 'RECONNECTING', latest=None)
                    # Webcam disappears with the browser; finish after a bounded idle window.
                    if source == 'WEBCAM_LIVE' and time.perf_counter() - last_valid > 15:
                        break
                self.stop_event.wait(0.02)
            account([], max(time.perf_counter_ns(), last_mono + 1), 'ENGINE_STOPPED')
            if pipeline:
                pipeline.finish('STOPPED' if self.stop_event.is_set() else 'SOURCE_TIMEOUT')
            pipeline = None
            self._update(camera_health='OFFLINE', latest=None)
        except Exception as error:
            logging.getLogger('cctv_tracker').error('Live engine failed: %s', type(error).__name__)
            if pipeline:
                try:
                    pipeline.finish('INTERRUPTED')
                except Exception:
                    pipeline.lease.close()
            self._update(status='FAILED', camera_health='OFFLINE', latest=None, error='Engine live gagal. Periksa model, disk, atau log; hanya checkpoint committed yang dipakai.')
        finally:
            if db:
                db.close()
            if capture:
                capture.close()
            while True:
                try:
                    queued = self.frames.get_nowait()
                    if not queued['future'].done():
                        queued['future'].set_exception(ValueError('Sesi telah berhenti'))
                except Empty:
                    break
            with self.lock:
                self.preview = None
                self.preview_history.clear()
                if self.state['status'] != 'FAILED':
                    self.state.update(status='STOPPED', camera_health='OFFLINE', latest=None)
