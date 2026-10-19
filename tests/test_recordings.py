from contextlib import closing
import json
from types import SimpleNamespace

import av
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cctv_tracker.config import Rules, Settings, Zone
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.records import DEFAULT_POLICY, RecordingManager, validate_policy
from cctv_tracker.vision import Detection
from test_live import FixtureDetector


class Clock:
    value = 1000.
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


def jpeg(color=80, width=320):
    image = np.full((240, width, 3), color, np.uint8)
    return cv2.imencode('.jpg', image)[1].tobytes()


def test_video_rotation_decodable_timestamps_disable_and_restart(tmp_path):
    clock = Clock()
    manager = RecordingManager(tmp_path / 'site.sqlite3', clock=clock, wall_clock=clock)
    manager.submit_webcam(jpeg())
    manager.tick()
    assert not manager.status()['files'] and manager.webcam is None
    policy = {**DEFAULT_POLICY, 'video_enabled': True, 'video_segment_seconds': 5}
    manager.configure(policy)
    for i in range(54):
        clock.advance(.2)
        manager.submit_webcam(jpeg(20 + i * 3, width=321))
        manager.tick()
    assert len(manager.status()['files']) == 2
    assert manager.status()['active_videos'][0]['frames'] > 0
    manager.configure({**policy, 'video_enabled': False})
    files = manager.status()['files']
    assert len(files) == 3 and not manager.status()['active_videos']
    assert not manager.status()['errors']
    for item in files:
        with av.open(str(manager.artifact(item['id'], 'mp4'))) as container:
            frames = list(container.decode(video=0))
        assert len(frames) == item['frames']
        assert frames[0].width == 322 and frames[0].height == 240
        times = [float(f.pts * f.time_base) for f in frames]
        assert times == sorted(set(times))
        assert times[-1] < 5.1
        if len(frames) > 2:
            assert float(frames[-1].to_ndarray().mean()) > float(frames[0].to_ndarray().mean())
    clock.advance(10)
    manager.submit_webcam(jpeg()); manager.tick()
    assert len(manager.status()['files']) == 3
    restored = RecordingManager(tmp_path / 'site.sqlite3', clock=clock, wall_clock=clock)
    assert restored.policy['video_enabled'] is False and len(restored.status()['files']) == 3
    with pytest.raises(LookupError):
        restored.artifact('../policy', 'json')
    with pytest.raises(LookupError):
        restored.artifact(files[0]['id'], 'json')


def test_source_loss_does_not_repeat_stale_frames_and_disk_bound_is_visible(tmp_path, monkeypatch):
    clock = Clock()
    manager = RecordingManager(tmp_path / 'site.sqlite3', clock=clock, wall_clock=clock)
    manager.configure({**DEFAULT_POLICY, 'video_enabled': True})
    manager.submit_webcam(jpeg()); manager.tick()
    clock.advance(1); manager.tick()
    assert manager.status()['active_videos'][0]['frames'] == 1
    clock.advance(2); manager.tick()
    assert not manager.status()['active_videos'] and manager.status()['files'][0]['frames'] == 1
    import cctv_tracker.records as module
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    manager.submit_webcam(jpeg()); manager.tick()
    assert '256 MB' in manager.status()['errors']['webcam']
    assert not manager.status()['active_videos']
    manager.shutdown()


def test_data_schedule_uses_committed_report_and_skips_unchanged_records(tmp_path):
    clock = Clock()
    path = tmp_path / 'site.sqlite3'
    settings = Settings(database=path, zones=(Zone('desk', '=Desk', ((0,0),(1,0),(1,1),(0,1))),), rules=Rules(.1,.1,.5))
    live = SimpleNamespace(settings=settings, snapshot=lambda: {'status': 'IDLE'})
    manager = RecordingManager(path, live, clock=clock, wall_clock=clock)
    with closing(Database(path)) as db:
        pipeline = Pipeline(settings, db, 1000000, 'SYNTHETIC_REPLAY', 'f' * 64, {})
        for i in range(6):
            pipeline.feed([Detection((.2,.2,.5,.8), .95)], 1000000+i*200000, i*200000000, i+1, 'test')
        manager.configure({**DEFAULT_POLICY, 'data_enabled': True, 'data_interval_seconds': 5})
        clock.advance(4); manager.tick()
        assert not manager.status()['files']
        clock.advance(1); manager.tick()
        item = manager.status()['files'][0]
        value = json.loads(manager.artifact(item['id'], 'json').read_text())
        report = value['report']['workstations'][0]
        assert report['occupied_us'] + report['empty_us'] + report['unknown_us'] == report['eligible_us']
        assert report['occupied_us'] > 0 and value['identity_source'] == 'anonymous'
        assert "'=Desk" in manager.artifact(item['id'], 'csv').read_text(encoding='utf-8-sig')
        clock.advance(5); manager.tick()
        assert len(manager.status()['files']) == 1
        manager.configure({**manager.policy, 'data_enabled': False})
        pipeline.feed([], 2300000, 1300000000, 7, 'test')
        clock.advance(5); manager.tick()
        assert len(manager.status()['files']) == 1
        pipeline.finish()
    manager.shutdown()


@pytest.mark.parametrize('key,value', [('video_segment_seconds', 0), ('data_interval_seconds', 3601), ('data_interval_seconds', 5.5), ('video_enabled', 'true'), ('max_storage_mb', 0)])
def test_policy_rejects_invalid_values(key, value):
    with pytest.raises(ValueError):
        validate_policy({**DEFAULT_POLICY, key: value})


def test_recording_api_auth_policy_persistence_and_file_allowlist(tmp_path, monkeypatch):
    from cctv_tracker.api import create_app
    import cctv_tracker.engine as module
    detector = FixtureDetector(); detector.runtime_label = 'SYNTHETIC'; detector.session = True; detector.manifest = {}
    monkeypatch.setattr(module, 'create_detector', lambda *args: detector)
    settings = Settings(database=tmp_path / 'app.sqlite3')
    with closing(Database(settings.database)):
        pass
    with TestClient(create_app(settings.database, 't'*40, controller=ReplayController(settings))) as client:
        auth = {'Authorization': 'Bearer ' + 't'*40}
        assert client.get('/pilot/v1/recordings').status_code == 401
        assert client.post('/pilot/v1/recordings/policy', headers=auth, json={**DEFAULT_POLICY, 'data_interval_seconds': True}).status_code == 422
        assert client.post('/pilot/v1/recordings/policy', headers={**auth,'Origin':'https://external.example'}, json=DEFAULT_POLICY).status_code == 403
        response = client.post('/pilot/v1/recordings/policy', headers=auth, json={**DEFAULT_POLICY, 'data_enabled': True, 'data_interval_seconds': 5})
        assert response.status_code == 200 and response.json()['policy']['data_enabled']
        assert client.get('/pilot/v1/recordings/files/' + 'a'*32 + '/mp4', headers=auth).status_code == 404
        assert client.get('/pilot/v1/recordings/files/' + 'a'*32 + '/exe', headers=auth).status_code == 422
    restored = RecordingManager(settings.database)
    assert restored.policy['data_interval_seconds'] == 5 and restored.policy['data_enabled']
