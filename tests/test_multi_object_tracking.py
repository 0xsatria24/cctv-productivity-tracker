"""Real ByteTrack with synthetic detections; no field accuracy claims."""
from contextlib import closing
from dataclasses import replace
import json

import numpy as np
import pytest

from cctv_tracker.config import Settings, Zone, load_settings
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.sessions import SessionManager
from cctv_tracker.tracking import TrackingRules
from cctv_tracker.vision import Detection, Tracker


def person(x, y=.1, confidence=.95):
    return Detection((x, y, x + .08, y + .2), confidence)


def test_two_moving_people_keep_separate_ids_across_slow_inference():
    tracker = Tracker(5, 1)
    original = None
    for at in (0, .2, .4, .6, .8, 1.6, 1.8, 2):
        measured = [person(.05 + .08 * at), person(.55 + .08 * at, .6)]
        rows = tracker.update(measured, at, 'camera')
        ids = [row.track_id for row in rows]
        original = original or ids
        assert ids == original and len(set(ids)) == 2
        assert [row.box for row in rows] == [row.box for row in measured]
        if at == 1.6:
            assert tracker.metrics['extra_prediction_steps'] == 3


def test_source_indices_survive_output_reordering_and_smoothed_backend_boxes(monkeypatch):
    tracker = Tracker(5, 1)
    def backend(inputs):
        output = inputs[[1, 0]]
        output.xyxy = output.xyxy + .001
        output.tracker_id = np.array([20, 10])
        return output
    monkeypatch.setattr(tracker.tracker, 'update_with_detections', backend)
    measured = [person(.1), person(.6)]
    rows = tracker.update(measured, 0, 'camera')
    assert [row.track_id for row in rows] == ['camera:1:10', 'camera:1:20']
    assert [row.box for row in rows] == [row.box for row in measured]


@pytest.mark.parametrize('duplicate_source', [True, False])
def test_duplicate_backend_binding_is_rejected_on_both_sides(monkeypatch, duplicate_source):
    tracker = Tracker(5, 1)
    def backend(inputs):
        output = inputs[[0, 0]] if duplicate_source else inputs
        output.tracker_id = np.array([10, 20] if duplicate_source else [10, 10])
        return output
    monkeypatch.setattr(tracker.tracker, 'update_with_detections', backend)
    rows = tracker.update([person(.1), person(.6)], 0, 'camera')
    assert all(row.track_id is None for row in rows)
    assert tracker.metrics['mapping_rejected'] == 2


def test_real_low_confidence_association_can_keep_raw_id_without_new_session():
    tracker = Tracker(5, 1)
    first = tracker.update([person(.2)], 0, 'camera')[0].track_id
    weak = tracker.update([person(.2, confidence=.2)], .2, 'camera')[0]
    assert weak.track_id == first and weak.confidence == .2
    manager = SessionManager(Settings())
    assert manager.update([weak], 200_000, 200_000_000, 'camera')[0][1] is None
    assert manager.sessions == {} and manager.metrics['weak_session_rejected'] == 1


def test_missing_measurements_do_not_return_prediction_boxes_and_reset_cannot_reuse_id():
    tracker = Tracker(5, 1)
    original = tracker.update([person(.2)], 0, 'camera')[0].track_id
    assert tracker.update([], .2, 'camera') == []
    assert tracker.metrics['measured_count'] == tracker.metrics['matched_count'] == 0
    assert tracker.update([person(.2)], 2, 'camera')[0].track_id != original
    assert tracker.metrics['reset_reason'] == 'EVIDENCE_GAP'
    before = tracker.epoch
    tracker.update([person(.2)], 2.2, 'new-generation')
    assert tracker.epoch == before + 1


def test_fractional_elapsed_ticks_are_carried_and_prediction_work_is_bounded():
    tracker = Tracker(5, 2)
    for at in (0, .3, .6, .9, 1.2):
        tracker.update([person(.2)], at, 'camera')
    assert tracker.tracker.frame_id == 7
    tracker = Tracker(5, 2, rules=TrackingRules(max_prediction_steps=2))
    original = tracker.update([person(.2)], 0, 'camera')[0].track_id
    after = tracker.update([person(.2)], .8, 'camera')[0].track_id
    assert after != original
    assert tracker.metrics['reset_reason'] == 'PREDICTION_BUDGET'


def test_expired_lost_track_cannot_reassociate_before_backend_cleanup():
    tracker = Tracker(5, 2, rules=TrackingRules(lost_buffer_seconds=.4))
    original = tracker.update([person(.2)], 0, 'camera')[0].track_id
    tracker.update([], .2, 'camera')
    returned = tracker.update([person(.2)], 1, 'camera')[0]
    assert returned.track_id != original
    assert tracker.metrics['expired_lost_tracks'] == 1


def test_invalid_time_does_not_mutate_tracker_state():
    tracker = Tracker(5, 1)
    tracker.update([person(.2)], 1, 'camera')
    state = tracker.tracker.frame_id, tracker.epoch, tracker.last_time
    for at in (float('nan'), float('inf'), -1, .9, 1):
        with pytest.raises(ValueError):
            tracker.update([person(.2)], at, 'camera')
        assert (tracker.tracker.frame_id, tracker.epoch, tracker.last_time) == state


@pytest.mark.parametrize('values', [
    {'activation_threshold': .95}, {'matching_threshold': float('nan')},
    {'activation_threshold': True}, {'lost_buffer_seconds': 0},
    {'confirmation_frames': 0}, {'confirmation_frames': 1.5}, {'max_prediction_steps': 0},
])
def test_invalid_tracking_policy_rejected(values):
    with pytest.raises(ValueError):
        TrackingRules(**values)


def test_tracking_config_and_policy_are_persisted_per_run(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{"tracking":{"lost_buffer_seconds":2,"confirmation_frames":2}}')
    config = load_settings(path)
    assert config.tracking.lost_buffer_seconds == 2
    tracker = Tracker(5, 1, rules=config.tracking)
    assert tracker.tracker.max_time_lost == 10
    assert tracker.tracker.minimum_consecutive_frames == 2
    config = replace(config, database=tmp_path / 'tracking.sqlite3', zones=(Zone('area', 'Area', ((0,0),(1,0),(1,1),(0,1))),))
    with closing(Database(config.database)) as db:
        pipeline = Pipeline(config, db, 1_000_000, 'SYNTHETIC_REPLAY', 'a' * 64, {})
        try:
            result = pipeline.feed([person(.2)], 1_000_000, 0, 1, 'camera')
            assert result['tracking']['algorithm'] == 'ByteTrack'
            unavailable = pipeline.feed([], 1_200_000, 200_000_000, 2, 'camera', 'FRAME_STALE')
            assert unavailable['tracking']['available'] is False
            assert unavailable['tracking']['reason'] == 'FRAME_STALE'
            manifest = json.loads(db.conn.execute('SELECT runtime_manifest_json FROM engine_runs').fetchone()[0])
            assert manifest['tracking_policy']['lost_buffer_seconds'] == 2
        finally:
            pipeline.finish()


def test_crowd_bindings_are_one_to_one_under_reordered_input():
    tracker = Tracker(5, 1)
    measured = [Detection((.02 + col * .12, .02 + row * .24, .09 + col * .12, .20 + row * .24), .95)
                for row in range(4) for col in range(8)]
    original = {}
    for frame in range(12):
        rows = measured if frame % 2 == 0 else list(reversed(measured))
        result = tracker.update(rows, frame * .2, 'crowd')
        assert len(result) == len({d.track_id for d in result}) == 32
        for detection in result:
            original.setdefault(detection.box, detection.track_id)
            assert detection.track_id == original[detection.box]


def test_crossing_with_real_bytetrack_never_transfers_application_session_between_people(tmp_path):
    config = Settings(database=tmp_path / 'crossing.sqlite3', zones=(Zone('area', 'Area', ((0,0),(1,0),(1,1),(0,1))),))
    owners = {}
    with closing(Database(config.database)) as db:
        pipeline = Pipeline(config, db, 1_000_000, 'SYNTHETIC_REPLAY', 'a' * 64, {})
        try:
            for step in range(41):
                at = step / 5
                labeled = [('A', person(.15 + .05 * at)), ('B', person(.65 - .05 * at))]
                if step % 2:
                    labeled.reverse()
                result = pipeline.feed([d for _, d in labeled], 1_000_000 + round(at * 1e6), round(at * 1e9), step + 1, 'camera')
                session_ids = [d['session_id'] for d in result['detections']]
                assert len(set(session_ids)) == 2
                for (label, _), row in zip(labeled, result['detections']):
                    sid = row['session_id']
                    owners.setdefault(sid, label)
                    assert owners[sid] == label
        finally:
            pipeline.finish()
