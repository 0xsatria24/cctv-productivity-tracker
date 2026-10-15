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
        assert client.get('/pilot/v1/status', headers=headers).json()['runs'] == []
        assert client.get('/pilot/v1/status?dataset=live', headers=headers).json()['runs'] == []
        assert client.delete(f'/pilot/v1/camera-wall/cameras/{camera}', headers=headers).status_code == 200
        assert client.get(f'/pilot/v1/camera-wall/cameras/{camera}/frame.jpg', headers=headers).status_code == 404
