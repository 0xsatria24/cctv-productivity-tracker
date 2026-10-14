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


@pytest.mark.skipif(not MODEL_PATH.exists(), reason='Optional real model; run setup_webcam_model.py')
def test_real_model_on_blank_frame_and_lock():
    detector = WebcamDetector()
    result = detector.detect(jpeg())
    assert result['count'] == 0
    assert result['source'] == 'WEBCAM_LIVE'
    assert result['inference_ms'] > 0
    with detector.lock, pytest.raises(BlockingIOError):
        detector.detect(jpeg())
