import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from cctv_tracker.config import Settings
from cctv_tracker.live import LiveController
from editions.headless.app import create_app
from editions.headless.licensing import License, verify_license
from editions.headless.service import EngineService
from editions.headless.webhooks import Webhook

TOKEN = 't' * 32
AUTH = {'Authorization': 'Bearer ' + TOKEN}


def entitlement(count=2):
    return License('headless', count, datetime.now(timezone.utc) + timedelta(days=1))


def test_headless_cameras_share_one_model_instance(tmp_path,monkeypatch):
    import editions.headless.service as module
    created = []
    def factory(*args, **kwargs):
        detector = SimpleNamespace(detect=lambda jpeg: {'detections':[]})
        created.append(detector)
        return detector
    monkeypatch.setattr(module,'create_detector',factory)
    service = EngineService(Settings(database=tmp_path/'shared.sqlite3'),entitlement())
    try:
        service.add('a','rtsp://localhost/a')
        service.add('b','rtsp://localhost/b')
        assert len(created) == 1
        assert service.get('a').detector.scheduler is service.get('b').detector.scheduler
        assert service.get('a').detector.source_id != service.get('b').detector.source_id
        assert service.get('a').detector.scheduler.detector is created[0]
    finally:
        service.shutdown()


def test_signed_license_rejects_tampering_wrong_edition_and_expiry(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = tmp_path / 'vendor.pem'
    public.write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    path = tmp_path / 'license.json'
    def write(**overrides):
        values = dict(edition='headless', api_enabled=True, max_cameras=2, expires_at='2099-01-01T00:00:00Z')
        values.update(overrides)
        payload = json.dumps(values).encode()
        path.write_text(json.dumps({'payload': base64.b64encode(payload).decode(), 'signature': base64.b64encode(key.sign(payload)).decode()}))
    write()
    assert verify_license(path, public).max_cameras == 2
    original = json.loads(path.read_text())
    original['payload'] = base64.b64encode(b'{}').decode()
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError):
        verify_license(path, public)
    for invalid in ({'edition': 'enterprise'}, {'api_enabled': False}, {'max_cameras': True}, {'expires_at': '2000-01-01T00:00:00Z'}):
        write(**invalid)
        with pytest.raises(ValueError):
            verify_license(path, public)


def test_api_auth_limits_isolation_websocket_and_openapi(tmp_path):
    service = EngineService(Settings(database=tmp_path / 'headless.sqlite3'), entitlement())
    with TestClient(create_app(service, TOKEN)) as client:
        assert client.get('/api/v1/status').status_code == 401
        landing = client.get('/')
        assert landing.status_code == 200
        assert 'Hubungkan &amp; cek status' in landing.text
        assert TOKEN not in landing.text
        assert landing.headers['Cache-Control'] == 'no-store'
        assert client.get('/docs').status_code == 200
        assert client.get('/api/v1/openapi.json').status_code == 401
        assert client.get('/pilot/v1/status', headers=AUTH).status_code == 404
        for camera in ('north', 'south'):
            response = client.post('/api/v1/cameras', headers=AUTH, json={'camera_id': camera, 'url': 'rtsp://user:secret@localhost/' + camera})
            assert response.status_code == 201
            assert 'secret' not in response.text
            assert len(response.json()['camera_key']) == 64
            assert isinstance(service.get(camera), LiveController)
        assert service.get('north').settings.database != service.get('south').settings.database
        assert client.post('/api/v1/cameras', headers=AUTH, json={'camera_id': 'third', 'url': 'rtsp://localhost/third'}).status_code == 409
        assert client.post('/api/v1/cameras', headers=AUTH, json={'camera_id': '../escape', 'url': 'rtsp://localhost/a'}).status_code == 422
        assert client.get('/api/v1/cameras/missing', headers=AUTH).status_code == 404
        assert client.get('/api/v1/cameras/north/events', headers=AUTH).json() == {'items': [], 'next_cursor': 0}
        with client.websocket_connect('/api/v1/stream', headers=AUTH) as socket:
            message = socket.receive_json()
            assert len(message['cameras']) == 2
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/v1/stream'):
                pass
        schema = client.get('/api/v1/openapi.json', headers=AUTH).json()
        assert '/api/v1/cameras/{camera_id}/analytics' in schema['paths']
        assert client.delete('/api/v1/cameras/north', headers=AUTH).status_code == 204
        assert client.post('/api/v1/cameras', headers=AUTH, json={'camera_id': 'third', 'url': 'rtsp://localhost/third'}).status_code == 201


def test_multi_camera_uses_real_shared_accounting_with_synthetic_capture(tmp_path, monkeypatch):
    from test_live import FixtureDetector, profile, wait_for
    import editions.headless.service as module
    class Capture:
        def __init__(self, url, settings):
            self.started = time.perf_counter()
            self.process = SimpleNamespace(is_alive=lambda: True)
        def read(self, timeout):
            time.sleep(0.03)
            return {'jpeg': b'synthetic', 'monotonic_ns': time.perf_counter_ns(), 'generation': 'fixture'}
        def close(self):
            pass
    monkeypatch.setattr(module, 'create_detector', lambda *args, **kwargs: FixtureDetector())
    monkeypatch.setattr(module, 'create_live_engine', lambda settings, detector: LiveController(settings, detector, capture_factory=Capture))
    service = EngineService(Settings(database=tmp_path / 'headless.sqlite3'), entitlement())
    with TestClient(create_app(service, TOKEN)) as client:
        for camera in ('one', 'two'):
            state = client.post('/api/v1/cameras', headers=AUTH, json={'camera_id': camera, 'url': 'rtsp://localhost/' + camera}).json()
            calibration = profile(); calibration['camera_key'] = state['camera_key']
            assert client.put(f'/api/v1/cameras/{camera}/analytics', headers=AUTH, json=calibration).status_code == 200
            assert client.post(f'/api/v1/cameras/{camera}/start', headers=AUTH).status_code == 202
        wait_for(lambda: all(s['processed'] >= 6 for s in service.all_status()))
        for camera in ('one', 'two'):
            snapshot = service.status(camera)['latest']
            assert snapshot['sessions'][0]['camera_id'] == camera
            events = client.get(f'/api/v1/cameras/{camera}/events', headers=AUTH).json()
            assert any(e['event_type'] == 'ENTER' for e in events['items'])
            assert all(e['camera_id'] == camera for e in events['items'])
            cursor = events['next_cursor']
            assert all(e['seq'] > cursor for e in service.events(camera, cursor))
    assert all(not engine.thread.is_alive() for _, engine in service.cameras.values())


def test_headless_import_does_not_load_ui():
    result = subprocess.run([sys.executable, '-c', "import sys; import editions.headless.app, editions.headless.service; assert not any(n.startswith(('PySide', 'PyQt', 'tkinter', 'cctv_tracker.api', 'cctv_tracker.dashboard')) for n in sys.modules)"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_webhook_signature_retry_and_persistent_cursor(tmp_path):
    hook = Webhook('https://receiver.example/events', 's' * 32, tmp_path / 'cursor.json')
    event = {'event_id': 'id-1', 'seq': 7}
    requests = []
    def handler(request):
        requests.append(request)
        signature = hmac.new(b's' * 32, request.content, hashlib.sha256).hexdigest()
        assert request.headers['X-CCTV-Signature'] == 'sha256=' + signature
        return httpx.Response(503 if len(requests) == 1 else 200)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await hook.deliver(client, 'one', [event])
            assert hook.cursors == {}
            await hook.deliver(client, 'one', [event])
    asyncio.run(run())
    assert Webhook(hook.url, 's' * 32, hook.path).cursors == {'one': 7}


def test_expired_license_denies_api(tmp_path):
    license = License('headless', 1, datetime(2000, 1, 1, tzinfo=timezone.utc))
    service = EngineService(Settings(database=tmp_path / 'headless.sqlite3'), license)
    with TestClient(create_app(service, TOKEN)) as client:
        assert client.get('/api/v1/status', headers=AUTH).status_code == 403


def test_python_sdk_over_http(tmp_path):
    import importlib.util
    from pathlib import Path
    import socket
    from threading import Thread
    import uvicorn
    from test_live import wait_for
    spec = importlib.util.spec_from_file_location('headless_sdk', Path(__file__).parents[1] / 'sdk/python/headless_client.py')
    sdk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sdk)
    service = EngineService(Settings(database=tmp_path / 'headless.sqlite3'), entitlement())
    server = uvicorn.Server(uvicorn.Config(create_app(service, TOKEN), log_level='error'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        thread = Thread(target=server.run, kwargs={'sockets': [listener]})
        thread.start()
        try:
            wait_for(lambda: server.started)
            client = sdk.HeadlessClient(TOKEN, f'http://127.0.0.1:{listener.getsockname()[1]}')
            assert client.status()['edition'] == 'headless'
            assert client.add_camera('sdk', 'rtsp://localhost/sdk')['camera_id'] == 'sdk'
            assert client.events('sdk')['items'] == []
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
