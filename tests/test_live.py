"""Live lifecycle and accounting tests. Injected detections are explicit fixtures."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import time
import cv2
import numpy as np
import pytest

from cctv_tracker.config import Settings, Zone, Rules
from cctv_tracker.live import LiveController, validate_calibration
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.vision import Detection
from cctv_tracker.rtsp import RtspCapture, validate_rtsp_url


def profile():
    return {'width': 320, 'height': 240, 'camera_key': 'a' * 64,
            'zones': [{'id': 'desk', 'name': 'Meja uji', 'polygon': [[0, 0], [1, 0], [1, 1], [0, 1]], 'exclusive_group': 'desks'}],
            'rules': {'occupied_confirm_seconds': 0.1, 'empty_confirm_seconds': 0.1, 'max_evidence_gap_seconds': 3}}


class FixtureDetector:
    def __init__(self):
        self.rows = [{'box': [0.1, 0.1, 0.4, 0.8], 'confidence': 0.95}]
        self.width, self.height = 320, 240
        self.fail = False

    def detect(self, _):
        if self.fail:
            raise RuntimeError('Injected inference failure')
        return {'width': self.width, 'height': self.height, 'detections': [dict(d) for d in self.rows], 'count': len(self.rows), 'model': 'TEST FIXTURE', 'inference_ms': 1}


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    pytest.fail('Timed out waiting for live condition')


@pytest.fixture
def live(tmp_path):
    detector = FixtureDetector()
    controller = LiveController(Settings(database=tmp_path / 'replay.sqlite3'), detector)
    controller.save_calibration('WEBCAM_LIVE', profile())
    yield controller, detector
    controller.shutdown()
    assert not controller.thread or not controller.thread.is_alive()


def test_calibration_validation_and_camera_binding(live):
    controller, _ = live
    invalid = profile(); invalid['zones'][0]['polygon'] = [[0, 0], [1, 1], [0, 1], [1, 0]]
    with pytest.raises(ValueError):
        controller.save_calibration('WEBCAM_LIVE', invalid)
    with pytest.raises(ValueError, match='Kamera berbeda'):
        controller.start('WEBCAM_LIVE', camera_key='b' * 64)
    # Reconstruct using the original replay path, not another '-live' suffix.
    loaded = LiveController(replace(controller.settings, database=controller.settings.database.with_name('replay.sqlite3')), FixtureDetector())
    assert loaded.snapshot()['calibrations']['WEBCAM_LIVE']['revision'] == 1


def test_predicted_display_box_never_enters_measured_counts_or_zone_evidence(live):
    controller,detector=live
    session=controller.start('WEBCAM_LIVE',camera_key='a'*64)['session_id']
    wait_for(lambda:controller.snapshot()['status']=='RUNNING')
    controller.submit(b'fixture',session,1)
    time.sleep(.15)
    occupied=controller.submit(b'fixture',session,2)
    assert occupied['zones'][0]['state']=='OCCUPIED'
    detector.rows=[]
    time.sleep(.15)
    missing=controller.submit(b'fixture',session,3)
    assert missing['count']==0 and missing['detections']==[]
    assert len(missing['display_predictions'])==1
    time.sleep(.15)
    empty=controller.submit(b'fixture',session,4)
    assert empty['count']==0 and empty['zones'][0]['state']=='EMPTY'
    assert empty['display_predictions'][0]['activity']['label'] is None


def test_live_tracking_durations_gap_duplicate_stop_and_database_isolation(live):
    controller, detector = live
    session = controller.start('WEBCAM_LIVE', camera_key='a' * 64)['session_id']
    wait_for(lambda: controller.snapshot()['status'] == 'RUNNING')
    first = controller.submit(b'fixture', session, 1)
    time.sleep(0.15)
    second = controller.submit(b'fixture', session, 2)
    assert second['zones'][0]['state'] == 'OCCUPIED'
    assert first['detections'][0]['track_id'] == second['detections'][0]['track_id']
    assert first['detections'][0]['workstation_times'][0]['presence_us'] == 0
    assert second['detections'][0]['workstation_times'][0]['zone_id'] == 'desk'
    assert second['detections'][0]['workstation_times'][0]['presence_us'] > 0
    time.sleep(0.15)
    controller.submit(b'fixture', session, 3)
    with pytest.raises(ValueError, match='duplikat'):
        controller.submit(b'fixture', session, 3)
    with pytest.raises(ValueError):
        controller.start('WEBCAM_LIVE', camera_key='a' * 64)
    with pytest.raises(ValueError):
        controller.save_calibration('WEBCAM_LIVE', profile())
    wait_for(lambda: controller.snapshot()['camera_health'] == 'DEGRADED')
    with closing(Database(controller.settings.database)) as db:
        state = db.conn.execute('SELECT state FROM zone_intervals ORDER BY start_utc_us DESC LIMIT 1').fetchone()[0]
        assert state == 'UNKNOWN'
    detector.rows = []
    controller.submit(b'fixture', session, 4)
    time.sleep(0.15)
    result = controller.submit(b'fixture', session, 5)
    assert result['zones'][0]['state'] == 'EMPTY', result['zones']
    time.sleep(0.15)
    controller.submit(b'fixture', session, 6)
    controller.stop(session)
    wait_for(lambda: controller.snapshot()['status'] == 'STOPPED')
    with closing(Database(controller.settings.database)) as db:
        run = db.conn.execute('SELECT * FROM engine_runs').fetchone()
        report = db.report(run['started_utc_us'], run['ended_utc_us'], run_id=run['id'])
        row = report['workstations'][0]
        assert row['occupied_us'] > 0 and row['empty_us'] > 0 and row['unknown_us'] > 0
        assert row['eligible_us'] == row['occupied_us'] + row['empty_us'] + row['unknown_us']
        assert report['data_sources'] == ['WEBCAM_LIVE']
        assert db.conn.execute('SELECT COUNT(*) FROM event_log WHERE event_type="ENTER"').fetchone()[0] == 1
        assert db.conn.execute('SELECT COUNT(*) FROM event_log WHERE event_type="EXIT"').fetchone()[0] == 1
        assert db.conn.execute('SELECT COUNT(*) FROM track_visits').fetchone()[0] > 0

        assert db.conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not controller.settings.database.with_name('replay.sqlite3').exists()
    next_session = controller.start('WEBCAM_LIVE', camera_key='a' * 64)['session_id']
    wait_for(lambda: controller.snapshot()['status'] == 'RUNNING')
    with pytest.raises(ValueError):
        controller.submit(b'fixture', session, 7)
    with pytest.raises(ValueError):
        controller.stop(session)
    controller.stop(next_session)


def test_low_candidate_keeps_track_without_incrementing_presence(live):
    controller, detector = live
    session = controller.start('WEBCAM_LIVE', camera_key='a' * 64)['session_id']
    wait_for(lambda: controller.snapshot()['status'] == 'RUNNING')
    original = controller.submit(b'fixture', session, 1)['detections'][0]['track_id']
    measured = detector.detect(b'fixture')
    measured.update(count=0, detections=[], tracking_candidates=[{'box': [.1, .1, .4, .8], 'confidence': .2}])
    detector.detect = lambda _: dict(measured)
    result = controller.submit(b'fixture', session, 2)
    assert result['count'] == 1
    assert result['detections'][0]['track_id'] == original
    assert result['detections'][0]['confidence'] == pytest.approx(.2)
    assert result['detections'][0]['workstation_times'] == []
    assert result['zones'][0]['state'] == 'UNKNOWN'
    assert result['zones'][0]['count'] is None


def test_changed_frame_aspect_never_generates_occupied_evidence(live):
    controller, detector = live
    detector.width, detector.height = 640, 360
    session = controller.start('WEBCAM_LIVE', camera_key='a' * 64)['session_id']
    wait_for(lambda: controller.snapshot()['status'] == 'RUNNING')
    with pytest.raises(ValueError, match='Rasio'):
        controller.submit(b'fixture', session, 1)
    assert controller.snapshot()['latest'] is None
    controller.stop(session)
    wait_for(lambda: controller.snapshot()['status'] == 'STOPPED')
    with closing(Database(controller.settings.database)) as db:
        assert not db.conn.execute('SELECT 1 FROM zone_intervals WHERE state="OCCUPIED"').fetchone()


def test_inference_failure_closes_run_and_keeps_only_committed_evidence(live):
    controller, detector = live
    session = controller.start('WEBCAM_LIVE', camera_key='a' * 64)['session_id']
    wait_for(lambda: controller.snapshot()['status'] == 'RUNNING')
    controller.submit(b'fixture', session, 1)
    detector.fail = True
    with pytest.raises(RuntimeError):
        controller.submit(b'fixture', session, 2)
    wait_for(lambda: controller.snapshot()['status'] == 'FAILED')
    with closing(Database(controller.settings.database)) as db:
        assert db.conn.execute('SELECT termination_reason FROM engine_runs').fetchone()[0] == 'INTERRUPTED'
        assert not db.conn.execute('SELECT 1 FROM zone_intervals WHERE end_utc_us IS NULL').fetchone()


def test_failed_checkpoint_does_not_publish_uncommitted_detections(live, monkeypatch):
    import sqlite3
    from cctv_tracker.persistence import RunWriter
    controller, _ = live
    session = controller.start('WEBCAM_LIVE', camera_key='a' * 64)['session_id']
    wait_for(lambda: controller.snapshot()['status'] == 'RUNNING')
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('Injected disk-full fixture')
    monkeypatch.setattr(RunWriter, 'commit', fail)
    with pytest.raises(RuntimeError):
        controller.submit(b'fixture', session, 1)
    wait_for(lambda: controller.snapshot()['status'] == 'FAILED')
    assert controller.snapshot()['latest'] is None
    with closing(Database(controller.settings.database)) as db:
        assert db.conn.execute('SELECT COUNT(*) FROM event_log').fetchone()[0] == 0
        assert db.conn.execute('SELECT COUNT(*) FROM zone_intervals').fetchone()[0] == 0
        assert db.conn.execute('SELECT termination_reason FROM engine_runs').fetchone()[0] == 'INTERRUPTED'


def test_confirmed_enter_exit_and_no_double_count_with_multiple_people(tmp_path):
    zones, rules = validate_calibration(profile())
    rules = replace(rules, occupied_confirm_seconds=2, empty_confirm_seconds=2, max_evidence_gap_seconds=3)
    config = Settings(database=tmp_path / 'duration.sqlite3', zones=zones, rules=rules)
    person = Detection((0.1, 0.1, 0.3, 0.9), 0.95)
    other = Detection((0.6, 0.1, 0.9, 0.9), 0.95)
    with closing(Database(config.database)) as db:
        pipeline = Pipeline(config, db, 1_000_000, 'WEBCAM_LIVE', 'a' * 64, {}, live_events=True)
        for i, people in enumerate(([person, other], [person, other], [person, other], [person, other], [], [], [], [])):
            pipeline.feed(people, 1_000_000 + i * 1_000_000, (i + 1) * 1_000_000_000, i + 1, 'generation')
        report = pipeline.finish()
        row = report['workstations'][0]
        assert row['occupied_us'] == 2_000_000
        assert row['empty_us'] == 1_000_000
        assert row['unknown_us'] == 4_000_000
        assert db.conn.execute('SELECT COUNT(*) FROM event_log WHERE event_type="ENTER"').fetchone()[0] == 1
        assert db.conn.execute('SELECT COUNT(*) FROM event_log WHERE event_type="EXIT"').fetchone()[0] == 1


@pytest.mark.parametrize('url', ['file:///tmp/a', 'https://camera/a', 'rtsp://', 'rtsp://camera:70000/a', 'rtsp://camera/a\n'])
def test_invalid_rtsp_urls_never_launch_capture(url):
    with pytest.raises(ValueError):
        validate_rtsp_url(url)


def hanging_capture(url, mailbox, stop, open_timeout, read_timeout):
    # Simulates a native decoder that ignores cancellation.
    time.sleep(60)


def test_hung_capture_process_has_bounded_stop(tmp_path):
    capture = RtspCapture('rtsp://127.0.0.1:65534/test', Settings(database=tmp_path / 'test.sqlite3'), worker=hanging_capture)
    started = time.monotonic()
    capture.close()
    assert time.monotonic() - started < 5
    assert not capture.process.is_alive()
