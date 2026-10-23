from pathlib import Path
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from cctv_tracker.api import create_app
from cctv_tracker.webcam import WebcamDetector, jpeg_dimensions, MODEL_PATH


def jpeg(w=640, h=360):
    return cv2.imencode('.jpg', np.zeros((h, w, 3), dtype=np.uint8))[1].tobytes()


def test_frame_header_rejects_invalid_or_oversized_before_decode():
    assert jpeg_dimensions(jpeg()) == (640, 360)
    for data in (b'', b'not jpeg', jpeg(1281, 100), jpeg(1000, 1000)):
        with pytest.raises(ValueError):
            jpeg_dimensions(data)


def test_frame_endpoint_auth_validation_and_ephemeral_result(tmp_path, monkeypatch):
    # Injected detector tests API transport only, not model accuracy.
    monkeypatch.setattr(WebcamDetector, 'detect', lambda self, data: {'count': 0, 'detections': [], 'recorded': False})
    client = TestClient(create_app(tmp_path / 'unused.sqlite3', 't' * 32, controller=object()))
    path = '/pilot/v1/webcam/frame'
    headers = {'Authorization': 'Bearer ' + 't' * 32, 'Content-Type': 'image/jpeg'}
    assert client.post(path, content=jpeg()).status_code == 401
    assert client.post(path, content=jpeg(), headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
    assert client.post(path, content=jpeg(), headers={**headers, 'Content-Type': 'image/png'}).status_code == 415
    assert client.post(path, content=b'x' * 1_000_001, headers=headers).status_code == 413
    assert client.post(path, content=jpeg(1300, 100), headers=headers).status_code == 422
    response = client.post(path, content=jpeg(), headers=headers)
    assert response.status_code == 200
    assert response.json()['recorded'] is False
    assert not (tmp_path / 'unused.sqlite3').exists()


def test_replay_detection_is_authenticated_and_never_uses_live_accounting(tmp_path, monkeypatch):
    monkeypatch.setattr(WebcamDetector, 'detect', lambda self, data: {'count': 1, 'detections': [{'box':[.1,.1,.2,.3],'confidence':.9}], 'recorded': True})
    path = tmp_path / 'unused-replay.sqlite3'
    client = TestClient(create_app(path, 't' * 32, controller=object()))
    headers = {'Authorization':'Bearer ' + 't'*32,'Content-Type':'image/jpeg'}
    assert client.get('/pilot/v1/replay/status').status_code == 401
    assert client.get('/pilot/v1/replay/status',headers=headers).json()['available']
    assert client.post('/pilot/v1/replay/frame',content=jpeg()).status_code == 401
    assert client.post('/pilot/v1/replay/frame',content=jpeg(),headers={**headers,'Origin':'https://evil.example'}).status_code == 403
    response = client.post('/pilot/v1/replay/frame',content=jpeg(),headers={**headers,'x-live-session':'not-a-live-session','x-frame-sequence':'1'})
    assert response.status_code == 200
    packet=response.json()
    assert packet['count']==1 and packet['source']=='LOCAL_VIDEO_REPLAY'
    assert not packet['recorded'] and not packet['tracking_supported'] and not packet['duration_accounting']
    assert not path.exists()


def test_busy_and_missing_model_are_actionable(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / 'unused.sqlite3', 't' * 32, controller=object()))
    headers = {'Authorization': 'Bearer ' + 't' * 32, 'Content-Type': 'image/jpeg'}
    def busy(self, data):
        raise BlockingIOError('busy')
    monkeypatch.setattr(WebcamDetector, 'detect', busy)
    assert client.post('/pilot/v1/webcam/frame', content=jpeg(), headers=headers).status_code == 429
    def missing(self, data):
        raise FileNotFoundError('setup model')
    monkeypatch.setattr(WebcamDetector, 'detect', missing)
    response = client.post('/pilot/v1/webcam/frame', content=jpeg(), headers=headers)
    assert response.status_code == 503
    assert response.json()['detail'] == 'setup model'


def test_replay_session_envelope_times_frames_without_live_accounting(tmp_path, monkeypatch):
    from uuid import uuid4
    monkeypatch.setattr(WebcamDetector, 'detect', lambda self, data: {
        'count': 1, 'detections': [{'box': [.1, .1, .2, .3], 'confidence': .9}], 'recorded': True})
    database = tmp_path / 'unused.sqlite3'
    client = TestClient(create_app(database, 't' * 32, controller=object()))
    headers = {'Authorization': 'Bearer ' + 't' * 32, 'Content-Type': 'image/jpeg',
               'x-replay-id': str(uuid4()), 'x-replay-generation': '0',
               'x-replay-sequence': '1', 'x-replay-time': '0', 'x-live-session': 'ignored'}
    endpoint = '/pilot/v1/replay/frame'
    first = client.post(endpoint, content=jpeg(), headers=headers)
    assert first.status_code == 200
    next_headers = {**headers, 'x-replay-sequence': '2', 'x-replay-time': '.5'}
    second = client.post(endpoint, content=jpeg(), headers=next_headers).json()
    assert second['detections'][0]['session_id'] == first.json()['detections'][0]['session_id']
    assert second['detections'][0]['accumulated_duration_us'] == 500_000
    assert second['tracking_supported'] and not second['duration_accounting'] and not second['recorded']
    assert client.post(endpoint, content=jpeg(), headers=next_headers).status_code == 409
    assert client.post(endpoint, content=jpeg(), headers={**headers, 'x-replay-time': 'nan'}).status_code == 422
    assert not database.exists()


@pytest.mark.skipif(not MODEL_PATH.exists(), reason='Optional real model; run setup_webcam_model.py')
def test_real_model_on_blank_frame_and_lock():
    detector = WebcamDetector()
    result = detector.detect(jpeg())
    assert result['count'] == 0
    assert result['source'] == 'WEBCAM_LIVE'
    assert result['inference_ms'] > 0
    with detector.lock, pytest.raises(BlockingIOError):
        detector.detect(jpeg())
