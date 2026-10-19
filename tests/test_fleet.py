"""Concurrent real tracking/accounting with explicitly injected camera/model input."""
from contextlib import closing
import json
import time
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cctv_tracker.config import Settings
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.fleet import CameraFleet, FairDetector
from cctv_tracker.persistence import Database
from test_live import FixtureDetector, profile, wait_for


class Capture:
    failed = set()
    def __init__(self, url, settings):
        self.url, self.started, self.closed = url, time.perf_counter(), False
        self.process = SimpleNamespace(is_alive=lambda: not self.closed)
    def read(self, timeout=0.1):
        time.sleep(0.04)
        if self.url in self.failed:
            return {'error': 'injected transport outage'}
        return {'jpeg': b'fixture', 'monotonic_ns': time.perf_counter_ns(), 'generation': str(self.started)}
    def close(self):
        self.closed = True


def setup_camera(fleet, name):
    row = fleet.add(name, f'rtsp://operator:do-not-leak@localhost/{name}')
    value = profile(); value['camera_key'] = row['camera_key']; value['rules']['max_evidence_gap_seconds'] = 0.5
    fleet.calibrate(row['id'], value)
    return row['id']


def test_active_analysis_and_preview_share_one_capture_without_a_viewer(tmp_path):
    captures = []
    def factory(url, settings):
        capture = Capture(url, settings)
        captures.append(capture)
        return capture
    fleet = CameraFleet(Settings(database=tmp_path / 'shared.sqlite3'), FairDetector(FixtureDetector()), capture_factory=factory)
    try:
        camera_id = setup_camera(fleet,'shared')
        fleet.start_analysis(camera_id)
        camera = fleet.get(camera_id)
        wait_for(lambda: camera.engine.snapshot()['processed'] > 5)
        assert len(captures) == 1
        assert camera.preview.capture_snapshot()['jpeg'] == b'fixture'
        assert camera.engine.preview_snapshot()['jpeg'] == b'fixture'
        # Closing an inference subscriber must not close the preview owner.
        reader = camera.engine.capture_factory('',fleet.settings)
        reader.close()
        assert not captures[0].closed
        assert camera.engine.snapshot()['latest']['detections'][0]['activity']['tracked_elapsed_us'] > 0
    finally:
        fleet.shutdown()
    assert all(c.closed for c in captures)


def test_archive_active_camera_releases_registry_lock_and_preserves_history(tmp_path):
    fleet = CameraFleet(Settings(database=tmp_path / 'replay.sqlite3'), FairDetector(FixtureDetector()), capture_factory=Capture)
    try:
        camera_id = setup_camera(fleet, 'archive-active')
        camera = fleet.get(camera_id)
        fleet.subscribe('archive-test', [camera_id])
        fleet.start_analysis(camera_id)
        wait_for(lambda: camera.engine.snapshot()['processed'] > 3)
        original_join = camera.join
        inspected = Event()
        def join_without_registry_lock():
            # Model a preview worker already waiting in _wanted at shutdown.
            def inspect():
                fleet.snapshot()
                inspected.set()
            worker = Thread(target=inspect, daemon=True)
            worker.start()
            assert inspected.wait(1), 'Archive held registry lock while joining workers'
            with pytest.raises(ValueError, match='diarsipkan'):
                fleet.start_analysis(camera_id)
            with pytest.raises(ValueError, match='diarsipkan'):
                fleet.remove(camera_id)
            original_join()
            worker.join(timeout=1)
        camera.join = join_without_registry_lock
        started = time.perf_counter()
        fleet.remove(camera_id)
        assert time.perf_counter() - started < 5
        assert not camera.preview._thread.is_alive()
        assert not camera.engine.thread.is_alive()
        assert not fleet.snapshot()['cameras']
        assert next(c for c in fleet.catalog() if c['id'] == camera_id)['archived']
        with closing(Database(fleet.database(camera_id))) as db:
            assert db.conn.execute('SELECT COUNT(*) FROM zone_intervals').fetchone()[0] > 0
            assert db.conn.execute('SELECT COUNT(*) FROM zone_intervals WHERE end_utc_us IS NULL').fetchone()[0] == 0
    finally:
        fleet.shutdown()


def test_multi_camera_persistence_recovery_independent_gaps_and_archive(tmp_path):
    settings = Settings(database=tmp_path / 'replay.sqlite3')
    fleet = CameraFleet(settings, FairDetector(FixtureDetector()), capture_factory=Capture)
    try:
        a, b = setup_camera(fleet, 'north'), setup_camera(fleet, 'south')
        fleet.configure(a, True)
        fleet.start_analysis(a); fleet.start_analysis(b)
        wait_for(lambda: all(fleet.get(i).engine.snapshot()['processed'] > 4 for i in (a, b)))
        assert fleet.get(a).engine.settings.database != fleet.get(b).engine.settings.database
        Capture.failed.add(fleet.get(a).record['url'])
        wait_for(lambda: fleet.get(a).engine.snapshot()['latest'] is None)
        before = fleet.get(b).engine.snapshot()['processed']
        wait_for(lambda: fleet.get(b).engine.snapshot()['processed'] > before + 4)
        time.sleep(0.6)
        with closing(Database(fleet.database(a))) as db:
            assert db.conn.execute('SELECT state FROM zone_intervals ORDER BY start_utc_us DESC LIMIT 1').fetchone()[0] == 'UNKNOWN'
        pair = fleet.get(b).engine.preview_snapshot()
        assert pair['observation']['recorded'] and pair['sequence'] > 0
        payload = json.dumps(fleet.snapshot())
        assert 'do-not-leak' not in payload and 'rtsp://' not in payload
        assert b'do-not-leak' not in fleet.store.path.read_bytes()
    finally:
        Capture.failed.clear()
        fleet.shutdown()
    restored = CameraFleet(settings, FairDetector(FixtureDetector()), capture_factory=Capture)
    try:
        restored.startup()
        assert len(restored.catalog()) == 2
        wait_for(lambda: restored.get(a).engine.snapshot()['status'] == 'RUNNING')
        assert restored.get(b).engine.snapshot()['status'] == 'IDLE'  # no opt-in, no auto-start
        assert restored.get(a).engine.profiles['RTSP_LIVE']['revision'] == 1
        restored.stop_analysis(a)
        wait_for(lambda: restored.get(a).engine.snapshot()['status'] == 'STOPPED')
        time.sleep(0.7)
        assert restored.get(a).engine.snapshot()['status'] == 'STOPPED'
        restored.remove(b)
        assert restored.database(b).is_file()
        assert next(c for c in restored.catalog() if c['id'] == b)['archived']
    finally:
        restored.shutdown()


def test_multi_api_auth_camera_report_and_backup(tmp_path, monkeypatch):
    import cctv_tracker.fleet as module
    import cctv_tracker.engine as construction
    from cctv_tracker.api import create_app
    original = module.CameraFleet
    monkeypatch.setattr(module, 'CameraFleet', lambda settings, detector: original(settings, detector, capture_factory=Capture))
    detector = FixtureDetector(); detector.runtime_label = 'SYNTHETIC'; detector.session = True; detector.manifest = {}
    monkeypatch.setattr(construction, 'create_detector', lambda *args: detector)
    path = tmp_path / 'api.sqlite3'
    with closing(Database(path)):
        pass
    auth = {'Authorization': 'Bearer ' + 't' * 32}
    with TestClient(create_app(path, 't' * 32, controller=ReplayController(Settings(database=path)))) as client:
        ids = []
        for name in ('north', 'south'):
            response = client.post('/pilot/v1/camera-wall/cameras', headers=auth, json={'name': name, 'url': f'rtsp://user:secret@localhost/{name}'})
            assert response.status_code == 201, response.text
            camera = response.json(); ids.append(camera['id'])
            value = profile(); value.update(source='RTSP_LIVE', camera_key=camera['camera_key'])
            assert client.post(f"/pilot/v1/camera-wall/cameras/{camera['id']}/calibration", headers=auth, json=value).status_code == 200
            assert client.post(f"/pilot/v1/camera-wall/cameras/{camera['id']}/start", headers=auth).status_code == 202
        wait_for(lambda: all(c['engine']['processed'] > 4 for c in client.get('/pilot/v1/camera-wall', headers=auth).json()['cameras']))
        for camera in ids:
            query = f'dataset=live&camera_id={camera}'
            report = client.get('/pilot/v1/reports?' + query, headers=auth).json()
            assert report['workstations'][0]['occupied_us'] > 0
            assert client.get('/pilot/v1/status?' + query, headers=auth).json()['selected_camera_id'] == camera
            assert camera in client.get('/pilot/v1/export.csv?' + query, headers=auth).text
            assert client.get(f'/pilot/v1/camera-wall/cameras/{camera}/observation').status_code == 401
            assert client.get(f'/pilot/v1/camera-wall/cameras/{camera}/observation', headers=auth).json()['observation']['recorded']
        assert client.get('/pilot/v1/reports?dataset=live&camera_id=../../private', headers=auth).status_code == 404
        assert client.post('/pilot/v1/maintenance/backup').status_code == 401
        assert client.post('/pilot/v1/maintenance/backup', headers=auth).status_code == 202
        wait_for(lambda: client.get('/pilot/v1/maintenance', headers=auth).json()['backups'])
        backup_id = client.get('/pilot/v1/maintenance', headers=auth).json()['backups'][0]['id']
        assert client.post(f'/pilot/v1/maintenance/backups/{backup_id}/verify', headers=auth).json()['verified']
