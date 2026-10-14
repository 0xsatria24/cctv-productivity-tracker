from contextlib import closing
from pathlib import Path
import time
import cv2
import numpy as np
from fastapi.testclient import TestClient

from cctv_tracker.api import create_app
from cctv_tracker.config import Settings
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.persistence import Database


def test_authenticated_live_calibration_frame_report_csv_and_registry(tmp_path, monkeypatch):
    # Explicit detector transport fixture. Real ONNX inference is tested separately.
    from cctv_tracker.webcam import WebcamDetector
    monkeypatch.setattr(WebcamDetector, 'detect', lambda self, data: {'width': 320, 'height': 240, 'detections': [], 'count': 0, 'model': 'TEST FIXTURE', 'inference_ms': 1})
    path = tmp_path / 'api.sqlite3'
    with closing(Database(path)):
        pass
    replay = ReplayController(Settings(database=path))
    token = 't' * 32
    headers = {'Authorization': 'Bearer ' + token}
    profile = {'source': 'WEBCAM_LIVE', 'width': 320, 'height': 240, 'camera_key': 'a' * 64,
               'zones': [{'id': 'desk', 'name': 'Meja API', 'polygon': [[0, 0], [1, 0], [1, 1], [0, 1]]}],
               'rules': {'occupied_confirm_seconds': 0.1, 'empty_confirm_seconds': 0.1, 'max_evidence_gap_seconds': 3}}
    with TestClient(create_app(path, token, controller=replay)) as client:
        assert client.get('/pilot/v1/live').status_code == 401
        assert client.post('/pilot/v1/live/calibration', json=profile).status_code == 401
        assert client.post('/pilot/v1/live/calibration', json=profile, headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/pilot/v1/live/calibration', json=profile, headers=headers).status_code == 200
        assert client.post('/pilot/v1/live/start', json={'source': 'WEBCAM_LIVE', 'camera_key': 'b' * 64}, headers=headers).status_code == 409
        response = client.post('/pilot/v1/live/start', json={'source': 'WEBCAM_LIVE', 'camera_key': 'a' * 64}, headers=headers)
        assert response.status_code == 202
        session = response.json()['session_id']
        deadline = time.monotonic() + 30
        while client.get('/pilot/v1/live', headers=headers).json()['status'] != 'RUNNING':
            assert client.get('/pilot/v1/live', headers=headers).json()['status'] != 'FAILED'
            assert time.monotonic() < deadline
            time.sleep(0.02)
        frame_headers = {**headers, 'Content-Type': 'image/jpeg', 'X-Live-Session': session}
        jpeg = cv2.imencode('.jpg', np.zeros((240, 320, 3), dtype=np.uint8))[1].tobytes()
        for seq in range(1, 4):
            result = client.post('/pilot/v1/webcam/frame', content=jpeg, headers={**frame_headers, 'X-Frame-Sequence': str(seq)})
            assert result.status_code == 200, result.json()
            assert result.json()['recorded'] is True
            time.sleep(0.15)
        assert client.post('/pilot/v1/webcam/frame', content=jpeg, headers={**frame_headers, 'X-Frame-Sequence': '3'}).status_code == 422
        assert client.get('/pilot/v1/live/preview.jpg', headers=headers).status_code == 200
        report = client.get('/pilot/v1/reports?dataset=live', headers=headers).json()
        assert report['data_sources'] == ['WEBCAM_LIVE']
        assert report['workstations'][0]['empty_us'] > 0
        assert report['workstations'][0]['observed_employee_id'] is None
        assert client.get('/pilot/v1/status', headers=headers).json()['runs'] == []
        assert len(client.get('/pilot/v1/status?dataset=live', headers=headers).json()['runs']) == 1
        assert 'WEBCAM_LIVE' in client.get('/pilot/v1/export.csv?dataset=live', headers=headers).text
        employee = client.post('/pilot/v1/employees?dataset=live', json={'display_name': 'Karyawan API'}, headers=headers).json()['id']
        workspace = report['workstations'][0]['workspace_id']
        values = {'employee_id': employee, 'workspace_id': workspace, 'start_utc_us': report['start_utc_us'], 'end_utc_us': report['start_utc_us'] + 3_600_000_000}
        assert client.post('/pilot/v1/assignments?dataset=live', json=values, headers=headers).status_code == 201
        assert client.get('/pilot/v1/reports?dataset=live', headers=headers).json()['workstations'][0]['assignment_is_observed_identity'] is False
        assert client.post('/pilot/v1/live/stop', json={'session_id': 'old-session'}, headers=headers).status_code == 409
        assert client.post('/pilot/v1/live/stop', json={'session_id': session}, headers=headers).status_code == 200
        deadline = time.monotonic() + 8
        while client.get('/pilot/v1/live', headers=headers).json()['status'] != 'STOPPED':
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert client.get('/pilot/v1/live/preview.jpg', headers=headers).status_code == 404
        assert client.get('/pilot/v1/status?dataset=invalid', headers=headers).status_code == 422
