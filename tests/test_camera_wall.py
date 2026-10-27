from contextlib import closing
from types import SimpleNamespace
import json
import time

import pytest
from fastapi.testclient import TestClient
from cctv_tracker.api import create_app
from cctv_tracker.camera_wall import CameraWall
from cctv_tracker.config import Settings
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.persistence import Database


class TestCapture:
    __test__ = False
    instances = []

    def __init__(self, url, settings):
        self.url, self.closed = url, False
        self.process = SimpleNamespace(is_alive=lambda: not self.closed)
        self.instances.append(self)

    def read(self, timeout=0.1):
        time.sleep(0.01)
        return {'jpeg': self.url.rsplit('/', 1)[-1].encode(), 'monotonic_ns': time.perf_counter_ns(), 'generation': 'test'}

    def close(self):
        self.closed = True


def wait(predicate):
    deadline = time.perf_counter() + 4
    while not predicate():
        assert time.perf_counter() < deadline
        time.sleep(0.02)


def test_independent_previews_visibility_expiry_and_secret_redaction(tmp_path):
    TestCapture.instances = []
    wall = CameraWall(Settings(database=tmp_path / 'test.sqlite3'), capture_factory=TestCapture, lease_seconds=0.4)
    try:
        a = wall.add('Area A', 'rtsp://operator:secret@localhost/a')
        b = wall.add('Area B', 'rtsp://operator:secret@localhost/b')
        assert wall.snapshot()['cameras'][0]['health'] == 'PAUSED'
        assert not TestCapture.instances
        with pytest.raises(ValueError, match='sudah ada'):
            wall.add('Duplicate', 'rtsp://operator:secret@localhost/a')
        with pytest.raises(ValueError, match='sudah ada'):
            wall.add('Different credentials, same stream', 'rtsp://other:password@localhost:554/a')
        with pytest.raises(ValueError):
            wall.subscribe('viewer', [a['id'], a['id']])
        with pytest.raises(LookupError):
            wall.subscribe('viewer', ['missing'])
        wall.subscribe('viewer', [a['id'], b['id']])
        wait(lambda: all(c['health'] == 'ONLINE' for c in wall.snapshot()['cameras']))
        assert wall.frame(a['id'])[0] != wall.frame(b['id'])[0]
        assert len(TestCapture.instances) == 2
        metadata = json.dumps(wall.snapshot())
        assert 'secret' not in metadata and 'rtsp://' not in metadata
        assert all(not c['analysis'] and not c['recorded'] for c in wall.snapshot()['cameras'])
        wall.subscribe('viewer', [b['id']])
        wait(lambda: wall.snapshot()['cameras'][0]['health'] == 'PAUSED')
        assert wall.frame(a['id']) is None
        wait(lambda: all(c['health'] == 'PAUSED' for c in wall.snapshot()['cameras']))
        assert all(c.closed for c in TestCapture.instances)
        wall.remove(a['id'])
        assert len(wall.snapshot()['cameras']) == 1
    finally:
        wall.shutdown()


def test_authenticated_preview_api_never_writes_observations(tmp_path, monkeypatch):
    import cctv_tracker.fleet as module
    original = module.CameraFleet
    monkeypatch.setattr(module, 'CameraFleet', lambda settings, detector: original(settings, detector, capture_factory=TestCapture))
    path = tmp_path / 'api.sqlite3'
    with closing(Database(path)):
        pass
    controller = ReplayController(Settings(database=path))
    headers = {'Authorization': 'Bearer ' + 't' * 32}
    with TestClient(create_app(path, 't' * 32, controller=controller)) as client:
        assert client.get('/pilot/v1/camera-wall').status_code == 401
        values = {'name': 'Test camera', 'url': 'rtsp://user:secret@localhost/test'}
        assert client.post('/pilot/v1/camera-wall/cameras', json=values, headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/pilot/v1/camera-wall/cameras', json={**values, 'url': 'https://example.com'}, headers=headers).status_code == 422
        response = client.post('/pilot/v1/camera-wall/cameras', json=values, headers=headers)
        assert response.status_code == 201 and 'secret' not in response.text
        camera = response.json()['id']
        assert client.post('/pilot/v1/camera-wall/view', json={'viewer_id': 'test', 'camera_ids': [camera]}, headers=headers).status_code == 200
        wait(lambda: client.get('/pilot/v1/camera-wall', headers=headers).json()['cameras'][0]['health'] == 'ONLINE')
        image = client.get(f'/pilot/v1/camera-wall/cameras/{camera}/frame.jpg', headers=headers)
        assert image.status_code == 200 and image.headers['X-Frame-Time'] and image.headers['X-Frame-Sequence']
        smooth = client.get(f'/pilot/v1/camera-wall/cameras/{camera}/observation?smooth=true', headers=headers)
        assert smooth.status_code == 200
        assert smooth.json()['observation'] is None
        assert smooth.json()['jpeg']  # Preview stays available independently of inference.
        assert client.get('/pilot/v1/status', headers=headers).json()['runs'] == []
        assert client.get('/pilot/v1/status?dataset=live', headers=headers).json()['runs'] == []
        assert client.delete(f'/pilot/v1/camera-wall/cameras/{camera}', headers=headers).status_code == 200
        assert client.get(f'/pilot/v1/camera-wall/cameras/{camera}/frame.jpg', headers=headers).status_code == 404


def test_live_start_resolves_registered_source_without_exposing_credentials(tmp_path, monkeypatch):
    from cctv_tracker.live import LiveController
    calls = []

    def start(self, source, url=None, *, preview_only=False, camera_key=None):
        calls.append((source, url, preview_only))
        return {'status': 'STARTING', 'source': source, 'preview_only': preview_only}

    monkeypatch.setattr(LiveController, 'start', start)
    path = tmp_path / 'source-bridge.sqlite3'
    with closing(Database(path)):
        pass
    controller = ReplayController(Settings(database=path))
    headers = {'Authorization': 'Bearer ' + 't' * 32}
    with TestClient(create_app(path, 't' * 32, controller=controller)) as client:
        url = 'rtsp://operator:private-password@localhost/source'
        camera = client.post('/pilot/v1/camera-wall/cameras', json={'name': 'Source bridge', 'url': url}, headers=headers).json()
        request = {'source': 'RTSP_LIVE', 'camera_id': camera['id'], 'preview_only': True}
        assert client.post('/pilot/v1/live/start', json=request).status_code == 401
        response = client.post('/pilot/v1/live/start', json=request, headers=headers)
        assert response.status_code == 202
        assert calls == [('RTSP_LIVE', url, True)]
        assert 'private-password' not in response.text
        assert 'rtsp://' not in client.get('/pilot/v1/camera-wall', headers=headers).text
        assert client.post('/pilot/v1/live/start', json={**request, 'url': url}, headers=headers).status_code == 422
        assert client.post('/pilot/v1/live/start', json={**request, 'source': 'WEBCAM_LIVE'}, headers=headers).status_code == 422
        client.delete(f"/pilot/v1/camera-wall/cameras/{camera['id']}", headers=headers)
        assert client.post('/pilot/v1/live/start', json=request, headers=headers).status_code == 404
        assert len(calls) == 1


@pytest.mark.parametrize('first_frame', [False, True])
def test_alive_but_stalled_decoder_is_closed_and_reconnected(tmp_path, first_frame):
    class StalledCapture(TestCapture):
        instances = []

        def __init__(self, url, settings):
            super().__init__(url, settings)
            self.sent = False

        def read(self, timeout=.1):
            time.sleep(.01)
            if first_frame and not self.sent:
                self.sent = True
                return {'jpeg': b'frame', 'monotonic_ns': time.perf_counter_ns(), 'generation': 'g'}
            return None

    wall = CameraWall(Settings(database=tmp_path/'stall.sqlite3',
                               open_timeout_seconds=.05, read_timeout_seconds=.05),
                      capture_factory=StalledCapture, lease_seconds=10)
    try:
        camera = wall.add('Stalled source', 'rtsp://localhost/stalled')
        wall.subscribe('viewer', [camera['id']])
        wait(lambda: len(StalledCapture.instances) >= 2)
        assert StalledCapture.instances[0].closed
        assert wall.frame(camera['id']) is None or first_frame
    finally:
        wall.shutdown()
    assert all(c.closed for c in StalledCapture.instances)
