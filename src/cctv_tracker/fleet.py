"""Persistent multi-camera dashboard orchestration over the shared live engine."""
from contextlib import closing
from dataclasses import replace
import copy
from pathlib import Path
import re
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from .camera_wall import CameraWall, PreviewCamera
from .live import LiveController
from .persistence import Database
from .rtsp import RtspCapture, validate_rtsp_url, rtsp_camera_key
from .secure_store import SecureStore

from .inference import FairDetector, InferenceScheduler
from .shared_capture import SharedPreviewCapture

ACTIVE = {'STARTING', 'RUNNING', 'STOPPING'}


class ManagedCamera:
    def __init__(self, record, settings, detector, wanted, capture_factory):
        self.record = record
        self.id, self.name = record['id'], record['name']
        self.fingerprint = rtsp_camera_key(record['url'])
        self.engine = LiveController(replace(settings, database=settings.database.parent / (self.id + '.sqlite3')), detector, capture_factory=lambda url, config: SharedPreviewCapture(self.preview))
        self.preview = PreviewCamera(self.name, record['url'], settings, wanted, capture_factory=capture_factory)
        self.preview.id = self.id
        self.failures, self.retry_at, self.healthy_since = 0, 0, None

    def start(self):
        self.preview.start()

    def snapshot(self):
        state = self.engine.snapshot()
        active = state['status'] in ACTIVE
        result = self.preview.snapshot()
        result.update(managed=True, auto_resume=self.record['auto_resume'], desired=self.record['desired'],
                      analysis=active and not state.get('preview_only', False), recorded=active and not state.get('preview_only', False),
                      engine=state, restart_attempts=self.failures, recovery_exhausted=self.failures >= 5)
        if active or state['status'] == 'FAILED':
            result.update(health=state['camera_health'], error=state['error'], frame_seq=state['processed'])
        return result

    def frame(self):
        if self.engine.snapshot()['status'] in ACTIVE:
            pair = self.engine.preview_snapshot()
            if pair:
                return pair['jpeg'], pair['utc_ms'], pair['sequence']
            return None
        return self.preview.frame()

    def stop(self):
        self.preview.stop()
        self.engine.stop()

    def join(self, timeout=12):
        self.preview.join(timeout)
        self.engine.shutdown()
        if self.engine.thread and self.engine.thread.is_alive():
            raise RuntimeError('Camera engine has not stopped; no data files were replaced')


class CameraFleet(CameraWall):
    def source_url(self, camera_id):
        with self._lock:
            camera = self._cameras.get(camera_id)
            if camera is None:
                raise LookupError('Kamera tidak ditemukan')
            return camera.record['url']

    def __init__(self, settings, detector, *, capture_factory=RtspCapture, lease_seconds=12, scheduler=None):
        super().__init__(settings, capture_factory=capture_factory, lease_seconds=lease_seconds)
        self.root = settings.database.parent / (settings.database.stem + '-fleet')
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = replace(settings, database=self.root / 'fleet.sqlite3')
        self.detector = detector
        self.scheduler = scheduler or (detector if isinstance(detector, InferenceScheduler) else None)
        self._lock = RLock()
        self._removing = set()
        self.store = SecureStore(self.root / 'cameras.protected')
        self.records = self.store.load()
        self._validate_records(self.records)
        self._stop = Event()
        self._supervisor = None
        for row in self.records['cameras']:
            if not row.get('archived'):
                self._construct(row)

    @staticmethod
    def _validate_records(value):
        if value.get('version') != 1 or not isinstance(value.get('cameras'), list):
            raise ValueError('Unsupported camera registry')
        ids = set()
        for row in value['cameras']:
            if not re.fullmatch('[0-9a-f]{32}', row['id']) or row['id'] in ids:
                raise ValueError('Invalid camera ID')
            ids.add(row['id'])
            validate_rtsp_url(row['url'])
            if not row['name'].strip() or len(row['name']) > 80:
                raise ValueError('Invalid camera name')
        if sum(not r.get('archived') for r in value['cameras']) > 16:
            raise ValueError('Too many cameras')

    def _construct(self, row):
        detector = self.scheduler.bind('fleet:' + row['id'], max_fps=self.settings.inference_fps) if self.scheduler else self.detector
        camera = ManagedCamera(row, self.settings, detector, self._wanted, self.capture_factory)
        self._cameras[camera.id] = camera
        camera.start()
        return camera

    def startup(self):
        self._supervisor = Thread(target=self._recover, daemon=True, name='camera-recovery')
        self._supervisor.start()

    def _wanted(self, camera_id):
        with self._lock:
            camera = self._cameras.get(camera_id)
            if camera and camera.engine.snapshot()['status'] in ACTIVE:
                return True
            return super()._wanted(camera_id)

    def add(self, name, url):
        name, url = name.strip(), validate_rtsp_url(url)
        if not name or len(name) > 80:
            raise ValueError('Nama kamera wajib diisi, maksimal 80 karakter.')
        with self._lock:
            if len(self._cameras) >= 16:
                raise ValueError('Maksimal 16 kamera; kapasitas analisis bergantung perangkat.')
            if any(c.fingerprint == rtsp_camera_key(url) for c in self._cameras.values()):
                raise ValueError('Sumber RTSP ini sudah ada di daftar kamera.')
            row = {'id': uuid4().hex, 'name': name, 'url': url, 'auto_resume': False, 'desired': False, 'archived': False}
            updated = copy.deepcopy(self.records)
            updated['cameras'].append(row)
            detector = self.scheduler.bind('fleet:' + row['id'], max_fps=self.settings.inference_fps) if self.scheduler else self.detector
            camera = ManagedCamera(row, self.settings, detector, self._wanted, self.capture_factory)
            self.store.save(updated)
            self.records = updated
            self._cameras[camera.id] = camera
            camera.start()
            # Rebind existing record references after copy-on-write.
            self._rebind()
            return camera.snapshot()

    def _rebind(self):
        for row in self.records['cameras']:
            if row['id'] in self._cameras:
                self._cameras[row['id']].record = row

    def get(self, camera_id):
        with self._lock:
            if camera_id not in self._cameras:
                raise LookupError('Kamera tidak ditemukan')
            return self._cameras[camera_id]

    def _save_flags(self, camera, **values):
        updated = copy.deepcopy(self.records)
        next(row for row in updated['cameras'] if row['id'] == camera.id).update(values)
        self.store.save(updated)
        self.records = updated
        self._rebind()

    def configure(self, camera_id, auto_resume):
        with self._lock:
            camera = self.get(camera_id)
            self._save_flags(camera, auto_resume=auto_resume)
            return camera.snapshot()

    def calibrate(self, camera_id, value):
        with self._lock:
            camera = self.get(camera_id)
            if value['camera_key'] != camera.fingerprint:
                raise ValueError('Kalibrasi tidak sesuai kamera')
            camera.engine.save_calibration('RTSP_LIVE', value)
            return camera.snapshot()

    def start_analysis(self, camera_id):
        with self._lock:
            camera = self.get(camera_id)
            if camera.record.get('archived') or camera_id in self._removing:
                raise ValueError('Kamera sedang diarsipkan')
            if camera.engine.snapshot()['status'] in ACTIVE:
                raise ValueError('Kamera masih aktif atau sedang berhenti')
            if not camera.engine.profiles.get('RTSP_LIVE'):
                raise ValueError('Simpan kalibrasi zona terlebih dahulu')
            self._save_flags(camera, desired=True)
            camera.failures, camera.retry_at = 0, 0
            try:
                camera.engine.start('RTSP_LIVE', camera.record['url'])
            except Exception:
                self._save_flags(camera, desired=False)
                raise
            return camera.snapshot()

    def stop_analysis(self, camera_id):
        with self._lock:
            camera = self.get(camera_id)
            self._save_flags(camera, desired=False)
            camera.engine.stop()
            return camera.snapshot()

    def _recover(self):
        while not self._stop.wait(0.5):
            with self._lock:
                for camera in self._cameras.values():
                    state, now = camera.engine.snapshot(), time.monotonic()
                    if state['status'] == 'RUNNING' and state['camera_health'] == 'ONLINE':
                        camera.healthy_since = camera.healthy_since or now
                        if now - camera.healthy_since >= 60:
                            camera.failures = 0
                    else:
                        camera.healthy_since = None
                    if not (camera.record['desired'] and camera.record['auto_resume']) or state['status'] in ACTIVE:
                        continue
                    if camera.engine.thread and camera.engine.thread.is_alive():
                        continue
                    if camera.failures >= 5 or now < camera.retry_at:
                        continue
                    camera.failures += 1
                    camera.retry_at = now + min(60, 2 ** camera.failures)
                    try:
                        camera.engine.start('RTSP_LIVE', camera.record['url'])
                    except Exception:
                        # Public error remains generic; URLs never enter logs/status.
                        camera.engine._update(status='FAILED', error='Pemulihan kamera gagal; periksa kalibrasi, model, atau disk.')

    def database(self, camera_id):
        with self._lock:
            if not any(r['id'] == camera_id for r in self.records['cameras']):
                raise LookupError('Kamera tidak ditemukan')
            return self.root / (camera_id + '-live.sqlite3')

    def catalog(self):
        with self._lock:
            return [{'id': r['id'], 'name': r['name'], 'archived': r.get('archived', False)} for r in self.records['cameras']]

    def snapshot(self):
        with self._lock:
            return {'cameras': [c.snapshot() for c in self._cameras.values()], 'capacity': 16, 'persistent': True}

    def remove(self, camera_id):
        with self._lock:
            camera = self.get(camera_id)
            if camera_id in self._removing:
                raise ValueError('Kamera sedang diarsipkan')
            self._save_flags(camera, desired=False, archived=True)
            self._removing.add(camera_id)
            camera.stop()
        # The preview worker acquires this registry lock via _wanted(). Joining
        # while holding it stalls shutdown and exceeds the browser timeout.
        try:
            camera.join()
            with self._lock:
                if self._cameras.get(camera_id) is camera:
                    del self._cameras[camera_id]
        finally:
            with self._lock:
                self._removing.discard(camera_id)

    def shutdown(self):
        self._stop.set()
        if self._supervisor:
            self._supervisor.join(timeout=3)
        super().shutdown()
