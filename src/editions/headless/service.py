"""Multi-camera orchestration; capture, inference and accounting stay shared."""
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from threading import RLock

from cctv_tracker.engine import create_detector, create_live_engine
from cctv_tracker.persistence import Database
from cctv_tracker.rtsp import validate_rtsp_url, rtsp_camera_key


class EngineService:
    def __init__(self, settings, license, *, detector='yolox', device='CPU', model_path=None):
        self.settings, self.license = settings, license
        self.detector_options = (detector, device, model_path)
        self.cameras = {}
        self.lock = RLock()

    def add(self, camera_id, url):
        with self.lock:
            self.license.check()
            if camera_id in self.cameras:
                raise ValueError('Camera already registered')
            if len(self.cameras) >= self.license.max_cameras:
                raise ValueError('Licensed camera limit reached')
            url = validate_rtsp_url(url)
            settings = replace(self.settings, camera_id=camera_id, database=self.settings.database.parent / (sha256(camera_id.encode()).hexdigest() + '.sqlite3'))
            engine = create_live_engine(settings, create_detector(*self.detector_options))
            self.cameras[camera_id] = (url, engine)
            return self.status(camera_id)

    def get(self, camera_id):
        try:
            return self.cameras[camera_id][1]
        except KeyError:
            raise KeyError('Camera not found') from None

    def status(self, camera_id):
        with self.lock:
            return {'camera_id': camera_id, 'camera_key': rtsp_camera_key(self.cameras[camera_id][0]), **self.get(camera_id).snapshot()}

    def all_status(self):
        with self.lock:
            return [self.status(key) for key in self.cameras]

    def start(self, camera_id, preview_only=False):
        with self.lock:
            self.license.check()
            engine = self.get(camera_id)
            return engine.start('RTSP_LIVE', self.cameras[camera_id][0], preview_only=preview_only)

    def remove(self, camera_id):
        with self.lock:
            engine = self.get(camera_id)
            engine.shutdown()
            if engine.thread and engine.thread.is_alive():
                raise ValueError('Camera is still stopping; retry later')
            del self.cameras[camera_id]

    def events(self, camera_id, after=0, limit=100):
        with closing(Database(self.get(camera_id).settings.database, migrate=False)) as db:
            rows = db.conn.execute('SELECT * FROM event_log WHERE seq > ? ORDER BY seq LIMIT ?', (after, limit))
            return [{'camera_id': camera_id, **dict(row)} for row in rows]

    def shutdown(self):
        with self.lock:
            for _, engine in self.cameras.values():
                engine.shutdown()
