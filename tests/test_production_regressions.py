from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cctv_tracker.config import Settings
from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking
from cctv_tracker.sessions import SessionManager
from cctv_tracker.vision import Detection


def test_weak_tracking_does_not_advance_confirmed_last_seen():
    manager = SessionManager(Settings(), continuation_confidence=.1)
    strong = Detection((.2, .2, .4, .8), .95, 'track')
    session = manager.update([strong], 1_000_000, 0, 'g')[0][1]
    manager.update([strong], 1_200_000, 200_000_000, 'g')
    manager.update([replace(strong, confidence=.2, tracking_only=True)],
                   1_400_000, 400_000_000, 'g')
    assert session.last_seen == 1_200_000
    assert session.last_ns == 400_000_000
    assert session.accumulated_ns == 200_000_000
    snapshot = manager.snapshot(session)
    assert snapshot['observed_duration_us'] == 200_000
    assert snapshot['total_elapsed_us'] == 400_000
    assert snapshot['absence_duration_us'] == 200_000


def test_elapsed_and_absence_advance_while_observed_time_is_frozen():
    manager = SessionManager(Settings())
    person = Detection((.2, .2, .4, .8), .95)
    session = manager.update([person], 1_000_000, 0, 'g')[0][1]
    manager.update([person], 1_200_000, 200_000_000, 'g')
    manager.update([], 1_600_000, 600_000_000, 'g')
    row = manager.snapshot(session)
    assert row['first_seen_utc_us'] == 1_000_000
    assert row['last_seen_utc_us'] == 1_200_000
    assert row['observed_duration_us'] == 200_000
    assert row['total_elapsed_us'] == 600_000
    assert row['absence_duration_us'] == 400_000


def test_unassigned_low_confidence_replay_box_is_weak():
    detector = SimpleNamespace(detect=lambda _: {
        'detections': [{'box': [.2, .2, .4, .8], 'confidence': .46}]})
    packet = ReplayTracking().process(detector, b'', ReplayFrame(str(uuid4()), 0, 1, 0))
    assert packet['detections'][0]['session_id'] is None
    assert packet['detections'][0]['evidence_state'] == 'WEAK'


def test_lost_gap_option_does_not_inflate_observed_duration(tmp_path):
    from test_sessions import harness
    with harness(tmp_path, count_lost_gap=True) as (h, _):
        sid = h.prime()
        h.feed(15.2)
        result = h.return_a()
        session = h.pipeline.sessions.sessions[sid]
        assert result['detections'][0]['session_id'] == sid
        assert session.accumulated_ns == 18_200_000_000
        assert h.pipeline.sessions.snapshot(session)['observed_duration_us'] == 15_200_000


def test_replay_prediction_lifetime_is_configurable():
    from cctv_tracker.tracking import TrackingRules
    settings = replace(Settings(), tracking=TrackingRules(display_prediction_seconds=.1))
    replay, rid = ReplayTracking(settings), str(uuid4())
    detector = SimpleNamespace(detect=lambda _: {
        'detections': [{'box': [.2, .2, .4, .8], 'confidence': .95}]})
    replay.process(detector, b'', ReplayFrame(rid, 0, 1, 0))
    detector.detect = lambda _: {'detections': []}
    packet = replay.process(detector, b'', ReplayFrame(rid, 0, 2, .2))
    assert packet['display_detections'] == []


@pytest.mark.parametrize('value', [-.1, 1.1, True, float('nan')])
def test_invalid_prediction_lifetime(value):
    from cctv_tracker.tracking import TrackingRules
    with pytest.raises(ValueError):
        TrackingRules(display_prediction_seconds=value)


def test_reid_cold_start_discards_results_but_retries_warm_provider(tmp_path, monkeypatch):
    from reid_helpers import FakeExtractor, jpeg
    from test_reid_sessions import build, feed

    class ColdExtractor(FakeExtractor):
        ready = False

        def warmup(self):
            initialized = not self.ready
            self.ready = True
            return initialized

    pipeline, database = build(tmp_path, extractor=ColdExtractor())
    pipeline.reid.rules = replace(pipeline.reid.rules, max_extra_latency_ms=150)
    clock = iter([0., 1., 2., 2.01, 3., 4.])
    monkeypatch.setattr('cctv_tracker.reid.runtime.time', SimpleNamespace(perf_counter=lambda: next(clock)))
    try:
        cold = feed(pipeline, 1, frame_jpeg=jpeg())
        assert cold['reid']['status'] == 'WARMUP_BUDGET'
        assert not pipeline.reid.disabled and not pipeline.reid.gallery.entries
        warm = feed(pipeline, 2, frame_jpeg=jpeg())
        assert warm['reid']['status'] == 'SHADOW'
        assert pipeline.reid.gallery.entries
        slow = feed(pipeline, 3, frame_jpeg=jpeg())
        assert slow['reid']['status'] == 'LATENCY_BUDGET'
        assert pipeline.reid.disabled
    finally:
        pipeline.finish()
        database.close()


def test_weak_positions_cannot_confirm_zone_exit():
    from cctv_tracker.config import Zone
    settings = replace(Settings(), zones=(Zone('desk', 'Desk', ((0, 0), (.4, 0), (.4, 1), (0, 1))),))
    manager = SessionManager(settings, continuation_confidence=.1)
    person = Detection((.36, .2, .46, .8), .95, 'track')
    session = manager.update([person], 1_000_000, 0, 'g')[0][1]
    for step in range(1, 4):
        weak = Detection((.41, .2, .51, .8), .2, 'track', tracking_only=True)
        assert manager.update([weak], 1_000_000+step*200_000, step*200_000_000, 'g')[0][1] is session
    assert session.zones['desk'].inside
    assert not session.zones['desk'].observed_inside
    assert session.zones['desk'].last_seen == 1_000_000


def test_confirmed_timestamp_and_observed_duration_survive_database_reopen(tmp_path):
    import json
    from contextlib import closing
    from cctv_tracker.config import Zone
    from cctv_tracker.persistence import Database
    from cctv_tracker.pipeline import Pipeline
    settings = replace(Settings(), database=tmp_path/'durations.sqlite3',
                       zones=(Zone('desk', 'Desk', ((0, 0), (1, 0), (1, 1), (0, 1))),))
    person = Detection((.2, .2, .4, .8), .95)
    with closing(Database(settings.database)) as db:
        pipeline = Pipeline(settings, db, 1_000_000, 'SYNTHETIC_REPLAY', 'a'*64, {})
        try:
            pipeline.feed([person], 1_000_000, 0, 1, 'g')
            pipeline.feed([person], 1_200_000, 200_000_000, 2, 'g')
            packet = pipeline.feed([replace(person, confidence=.2, tracking_only=True)],
                                   1_400_000, 400_000_000, 3, 'g')
            assert packet['sessions'][0]['absence_duration_us'] == 200_000
        finally:
            pipeline.finish()
    with closing(Database(settings.database)) as db:
        row = db.conn.execute('SELECT * FROM person_sessions').fetchone()
        assert row['first_seen_utc_us'] == 1_000_000 and row['last_seen_utc_us'] == 1_200_000
        assert json.loads(row['matching_json'])['observed_duration_us'] == 200_000
        assert db.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.conn.execute('PRAGMA foreign_key_check').fetchall()
