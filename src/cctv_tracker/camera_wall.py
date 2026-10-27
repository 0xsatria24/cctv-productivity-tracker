"""On-demand multi-camera previews. No detector, accounting or stored images."""
from threading import Event, Lock, Thread
import time
from uuid import uuid4

from .rtsp import RtspCapture, validate_rtsp_url, rtsp_camera_key


class PreviewCamera:
    def __init__(self, name, url, settings, wanted, *, capture_factory=RtspCapture):
        self.id, self.name = uuid4().hex, name
        self.fingerprint = rtsp_camera_key(url)
        self._url, self._settings, self._wanted = url, settings, wanted
        self._capture_factory = capture_factory
        self._lock, self._stop = Lock(), Event()
        self._jpeg, self._at, self._utc = None, 0, None
        self._health, self._error, self._seq = 'PAUSED', '', 0
        self._item = None
        self._thread = Thread(target=self._run, daemon=True, name=f'preview-{self.id[:8]}')

    def start(self):
        self._thread.start()

    def _clear(self, health, error=''):
        with self._lock:
            self._jpeg, self._at, self._utc = None, 0, None
            self._item = None
            self._health, self._error = health, error

    def _run(self):
        capture, retry_at, attempts = None, 0, 0
        opened_at, last_progress, last_frame_ns = 0, None, -1
        try:
            while not self._stop.is_set():
                if not self._wanted(self.id):
                    if capture:
                        capture.close(); capture = None
                    self._clear('PAUSED'); attempts = 0; retry_at = 0
                    self._stop.wait(0.2)
                    continue
                if not capture:
                    if time.perf_counter() < retry_at:
                        self._stop.wait(0.1); continue
                    self._clear('CONNECTING' if not attempts else 'RECONNECTING')
                    try:
                        capture = self._capture_factory(self._url, self._settings)
                        opened_at, last_progress, last_frame_ns = time.perf_counter(), None, -1
                    except Exception:
                        attempts += 1; retry_at = time.perf_counter() + min(8, 2 ** attempts)
                        self._clear('RECONNECTING', 'RTSP belum dapat dibaca; periksa koneksi kamera.')
                        continue
                item = capture.read(timeout=0.1)
                if item and item.get('jpeg'):
                    age = (time.perf_counter_ns() - item['monotonic_ns']) / 1e9
                    if 0 <= age <= 2.5 and item['monotonic_ns'] > last_frame_ns:
                        last_progress, last_frame_ns = time.perf_counter(), item['monotonic_ns']
                        with self._lock:
                            self._jpeg, self._at = item['jpeg'], item['monotonic_ns']
                            self._item = item
                            self._utc = time.time() - age
                            self._health, self._error = 'ONLINE', ''
                            self._seq += 1
                        attempts = 0
                deadline = (opened_at + self._settings.open_timeout_seconds + self._settings.read_timeout_seconds
                            if last_progress is None else last_progress + self._settings.read_timeout_seconds)
                if (item and item.get('error')) or not capture.process.is_alive() or time.perf_counter() > deadline:
                    capture.close(); capture = None
                    attempts += 1; retry_at = time.perf_counter() + min(8, 2 ** attempts)
                    self._clear('RECONNECTING', 'RTSP terputus; mencoba menghubungkan kembali.')
                elif self._at and (time.perf_counter_ns() - self._at) / 1e9 > 2.5:
                    self._clear('STALLED', 'Belum menerima frame baru.')
        finally:
            if capture:
                capture.close()
            self._clear('PAUSED')

    def snapshot(self):
        with self._lock:
            fresh = bool(self._jpeg and 0 <= (time.perf_counter_ns() - self._at) / 1e9 <= 2.5)
            return {'id': self.id, 'name': self.name, 'source': 'RTSP_PREVIEW', 'camera_key': self.fingerprint,
                    'health': self._health if fresh or self._health != 'ONLINE' else 'STALLED',
                    'error': self._error, 'frame_seq': self._seq,
                    'frame_utc_ms': round(self._utc * 1000) if fresh else None,
                    'analysis': False, 'recorded': False}

    def frame(self):
        with self._lock:
            if self._jpeg and 0 <= (time.perf_counter_ns() - self._at) / 1e9 <= 2.5:
                return self._jpeg, round(self._utc * 1000), self._seq

    def capture_snapshot(self):
        with self._lock:
            if self._item and 0 <= (time.perf_counter_ns()-self._at)/1e9 <= 2.5:
                return self._item

    def stop(self):
        self._stop.set()

    def join(self, timeout=6):
        self._thread.join(timeout=timeout)


class CameraWall:
    """URLs remain in memory; visible-camera leases expire after browser departure."""
    def __init__(self, settings, *, capture_factory=RtspCapture, lease_seconds=12):
        self.settings, self.capture_factory = settings, capture_factory
        self.lease_seconds = lease_seconds
        self._lock, self._cameras, self._viewers = Lock(), {}, {}

    def _wanted(self, camera_id):
        with self._lock:
            now = time.perf_counter()
            self._viewers = {k: v for k, v in self._viewers.items() if v[0] > now}
            return any(camera_id in ids for _, ids in self._viewers.values())

    def add(self, name, url):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('Nama kamera wajib diisi, maksimal 80 karakter.')
        url = validate_rtsp_url(url)
        fingerprint = rtsp_camera_key(url)
        with self._lock:
            if len(self._cameras) >= 16:
                raise ValueError('Maksimal 16 kamera preview per sesi aplikasi.')
            if any(c.fingerprint == fingerprint for c in self._cameras.values()):
                raise ValueError('Sumber RTSP ini sudah ada di daftar kamera.')
            camera = PreviewCamera(name, url, self.settings, self._wanted, capture_factory=self.capture_factory)
            self._cameras[camera.id] = camera
            camera.start()
        return camera.snapshot()

    def subscribe(self, viewer_id, ids):
        if len(ids) != len(set(ids)):
            raise ValueError('Kamera tidak boleh tampil dua kali dalam satu grid.')
        with self._lock:
            if set(ids) - self._cameras.keys():
                raise LookupError('Kamera tidak ditemukan. Muat ulang daftar kamera.')
            if ids:
                if viewer_id not in self._viewers and len(self._viewers) >= 64:
                    now = time.perf_counter()
                    self._viewers = {k: v for k, v in self._viewers.items() if v[0] > now}
                    if len(self._viewers) >= 64:
                        raise ValueError('Terlalu banyak tampilan kamera aktif.')
                self._viewers[viewer_id] = (time.perf_counter() + self.lease_seconds, set(ids))
            else:
                self._viewers.pop(viewer_id, None)

    def snapshot(self):
        with self._lock:
            cameras = list(self._cameras.values())
        return {'cameras': [c.snapshot() for c in cameras], 'capacity': 16, 'persistent': False}

    def frame(self, camera_id):
        with self._lock:
            camera = self._cameras.get(camera_id)
        return camera.frame() if camera else None

    def source_url(self, camera_id):
        with self._lock:
            camera = self._cameras.get(camera_id)
            if not camera:
                raise LookupError('Kamera tidak ditemukan. Tambahkan kembali sumber kamera.')
            return camera._url

    def remove(self, camera_id):
        with self._lock:
            camera = self._cameras.pop(camera_id, None)
        if not camera:
            raise LookupError('Kamera tidak ditemukan.')
        camera.stop(); camera.join()

    def shutdown(self):
        with self._lock:
            cameras = list(self._cameras.values())
            self._cameras.clear(); self._viewers.clear()
        for camera in cameras:
            camera.stop()
        deadline = time.perf_counter() + 7
        for camera in cameras:
            camera.join(max(0, deadline - time.perf_counter()))
