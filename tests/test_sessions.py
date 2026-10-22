"""Deterministic detection fixtures, not camera/ReID accuracy claims."""
from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from cctv_tracker.config import Settings, SessionRules, Rules, Zone, load_settings
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import Pipeline
from cctv_tracker.sessions import SessionManager
from cctv_tracker.vision import Detection, Tracker


def person(x, track='A', y=0.35):
    return Detection((x, y, x + 0.10, y + 0.25), 0.95, track)


def moving_a(t, track='A'):
    return person(0.05 + 0.02 * t, track)


def settings(path, **session_values):
    return Settings(database=path, zones=(Zone('desk', 'Desk', ((0, 0), (1, 0), (1, 1), (0, 1))),),
                    sessions=SessionRules(**session_values))


class SuppliedTracks:
    def update(self, detections, *_):
        return detections


class Harness:
    def __init__(self, pipeline):
        self.pipeline, self.sequence = pipeline, 0
        self.ownership = {}
        self.identity_switches = 0
        self.false_merges = 0
        self.identities = {}

    def feed(self, t, rows=(), generation='camera', unavailable=None, labels=()):
        self.sequence += 1
        result = self.pipeline.feed(rows, 1_000_000 + round(t * 1e6), round(t * 1e9), self.sequence, generation, unavailable)
        for row, label in zip(result['detections'], labels):
            sid = row['session_id']
            if sid in self.ownership and self.ownership[sid] != label:
                self.identity_switches += 1
                self.false_merges += 1
            self.ownership[sid] = label
            self.identities.setdefault(label, set()).add(sid)
        return result

    def prime(self):
        result = None
        for step in range(76):
            t = step / 5
            result = self.feed(t, [moving_a(t)], labels=['A'])
        return result['detections'][0]['session_id']

    def return_a(self, others=()):
        result = None
        for t in (18, 18.1, 18.2):
            result = self.feed(t, [*others, moving_a(t, 'changed')], labels=[*(['B'] * len(others)), 'A'])
        return result


@contextmanager
def harness(tmp_path, **session_values):
    config = settings(tmp_path / 'sessions.sqlite3', **session_values)
    db = Database(config.database)
    pipeline = Pipeline(config, db, 1_000_000, 'SYNTHETIC_REPLAY', 'a' * 64, {})
    pipeline.tracker = SuppliedTracks()
    try:
        yield Harness(pipeline), db
    finally:
        pipeline.finish()
        db.close()


@pytest.mark.parametrize('count_gap, expected', [(False, 15.2), (True, 18.2)])
def test_fifteen_seconds_then_three_second_loss_recovers_without_reset(tmp_path, count_gap, expected):
    with harness(tmp_path, count_lost_gap=count_gap) as (h, db):
        original = h.prime()
        lost = h.feed(15.2)
        assert lost['detections'] == []
        assert lost['sessions'][0]['status'] == 'LOST'
        assert lost['sessions'][0]['accumulated_duration_us'] == 15_000_000
        first_return = h.feed(18, [moving_a(18, 'changed')])
        temporary = first_return['detections'][0]
        assert temporary['session_id'] != original
        assert temporary['accumulated_duration_us'] == 0
        h.feed(18.1, [moving_a(18.1, 'changed')])
        row = h.feed(18.2, [moving_a(18.2, 'changed')])['detections'][0]
        assert row['session_id'] == original
        assert row['first_seen_utc_us'] == 1_000_000
        assert row['accumulated_duration_us'] == pytest.approx(expected * 1e6, abs=1)
        assert row['workstation_times'][0]['presence_us'] == pytest.approx(expected * 1e6, abs=1)
        persisted = db.conn.execute('SELECT * FROM person_sessions WHERE session_id=?', (original,)).fetchone()
        assert persisted['accumulated_duration_us'] == row['accumulated_duration_us']
        assert json.loads(persisted['zone_times_json'])['desk']['presence_us'] == row['workstation_times'][0]['presence_us']
        provisional = db.conn.execute('SELECT * FROM person_sessions WHERE session_id=?', (temporary['session_id'],)).fetchone()
        assert provisional['status'] == 'EXPIRED' and provisional['merged_into'] == original
        assert provisional['accumulated_duration_us'] == 0
        assert db.conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_tracker_id_change_on_continuous_motion_keeps_session(tmp_path):
    with harness(tmp_path) as (h, _):
        sid = h.prime()
        old_lifecycle = h.pipeline.latest['detections'][0]['track_lifecycle']
        row = h.feed(15.2, [moving_a(15.2, 'other-id')])['detections'][0]
        assert row['session_id'] == sid
        assert row['track_lifecycle'] != old_lifecycle
        assert row['accumulated_duration_us'] == 15_200_000


def test_b_at_a_last_position_and_reused_id_cannot_inherit_a(tmp_path):
    with harness(tmp_path) as (h, _):
        a = h.prime()
        h.feed(15.2)
        for t in (15.4, 15.6, 15.8, 16, 16.2):
            result = h.feed(t, [moving_a(15, 'A')], labels=['B'])
            row = result['detections'][0]
            assert row['session_id'] != a
            assert row['first_seen_utc_us'] == 16_400_000
            assert row['accumulated_duration_us'] == round((t - 15.4) * 1e6)
        assert h.identity_switches == h.false_merges == 0


def test_b_starting_at_a_last_box_then_matching_direction_and_speed_stays_separate(tmp_path):
    with harness(tmp_path) as (h, _):
        a = h.prime()
        h.feed(15.2)
        for t in (15.4, 15.6, 15.8, 16, 16.2):
            b = person(0.35 + 0.02 * (t - 15.4), 'A')
            row = h.feed(t, [b], labels=['B'])['detections'][0]
            assert row['session_id'] != a
            assert row['accumulated_duration_us'] == round((t - 15.4) * 1e6)
        assert h.false_merges == h.identity_switches == 0


def test_a_returns_while_b_stays_separate(tmp_path):
    with harness(tmp_path) as (h, db):
        a = h.prime()
        h.feed(15.2)
        b_detection = moving_a(15, 'A')
        b = h.feed(15.4, [b_detection], labels=['B'])['detections'][0]['session_id']
        for step in range(78, 90):
            h.feed(step / 5, [b_detection], labels=['B'])
        result = h.return_a([b_detection])
        assert [d['session_id'] for d in result['detections']] == [b, a]
        assert result['detections'][0]['accumulated_duration_us'] == 2_800_000
        assert result['detections'][1]['accumulated_duration_us'] == 15_200_000
        assert h.identity_switches == h.false_merges == 0
        active = db.conn.execute("SELECT session_id,track_lifecycle FROM person_sessions WHERE status='ACTIVE'").fetchall()
        assert len(active) == len({row['track_lifecycle'] for row in active}) == 2


def test_swapped_tracker_ids_follow_geometry_and_preserve_boxes(tmp_path):
    with harness(tmp_path) as (h, db):
        first = h.feed(0, [person(0.1, '1'), person(0.7, '2')])['detections']
        for i in range(1, 11):
            result = h.feed(i / 5, [person(0.1, '2'), person(0.7, '1')])
            assert [d['session_id'] for d in result['detections']] == [d['session_id'] for d in first]
            assert [d['box'] for d in result['detections']] == [person(0.1).box, person(0.7).box]
        assert db.conn.execute("SELECT COUNT(*) FROM person_sessions WHERE status='ACTIVE'").fetchone()[0] == 2


def test_crossing_and_full_occlusion_split_instead_of_switching(tmp_path):
    with harness(tmp_path) as (h, _):
        initial = None
        for step in range(16):
            t = step / 4
            result = h.feed(t, [person(0.1 + 0.08 * t, '1'), person(0.7 - 0.08 * t, '2')], labels=['A', 'B'])
            if initial is None:
                initial = {row['session_id'] for row in result['detections']}
        assert not initial.intersection(row['session_id'] for row in result['detections'])
        assert h.identity_switches == h.false_merges == 0
        for step in range(16, 27):
            t = step / 4
            result = h.feed(t, [person(0.1 + 0.08 * t, '2'), person(0.7 - 0.08 * t, '1')], labels=['A', 'B'])
        assert h.identity_switches == h.false_merges == 0
        assert len(h.identities['A']) > 1  # Deliberate fragmentation at unresolvable crossing.


def test_similar_stationary_people_do_not_recover_from_position_or_id(tmp_path):
    with harness(tmp_path) as (h, _):
        first = None
        for i in range(11):
            result = h.feed(i / 5, [person(0.3)])
            first = first or result['detections'][0]['session_id']
        h.feed(2.2)
        for t in (2.4, 2.6, 2.8):
            row = h.feed(t, [person(0.3)])['detections'][0]
            assert row['session_id'] != first
        assert h.pipeline.sessions.metrics['rejected_insufficient_evidence'] > 0


def test_expiration_finalizes_at_last_seen_without_counting_unrecovered_gap(tmp_path):
    with harness(tmp_path, count_lost_gap=True) as (h, db):
        a = h.prime()
        h.feed(15.2)
        h.feed(25)
        assert a not in h.pipeline.sessions.sessions
        row = db.conn.execute('SELECT * FROM person_sessions WHERE session_id=?', (a,)).fetchone()
        assert row['status'] == 'EXPIRED'
        assert row['last_seen_utc_us'] == 16_000_000
        assert row['accumulated_duration_us'] == 15_000_000
        new = h.feed(25.2, [moving_a(25.2)])['detections'][0]
        assert new['session_id'] != a and new['accumulated_duration_us'] == 0


def test_ambiguous_recovery_refuses_best_and_second_best_tie(tmp_path):
    with harness(tmp_path) as (h, _):
        # Two separated paths predict the same position after loss.
        for i in range(11):
            t = i / 5
            h.feed(t, [person(0.1 + 0.03 * t, '1'), person(0.34 - 0.03 * t, '2')])
        h.feed(2.2)
        old = {s.session_id for s in h.pipeline.sessions.sessions.values()}
        for t in (4, 4.1, 4.2):
            result = h.feed(t, [person(0.22 + 0.03 * (t - 4), '3')])
            assert result['detections'][0]['session_id'] not in old
        assert h.pipeline.sessions.metrics['rejected_ambiguous'] > 0


def test_variable_fps_skips_stale_results_clock_jump_and_camera_reconnect(tmp_path):
    with harness(tmp_path, count_lost_gap=True) as (h, db):
        sid = h.feed(0, [person(0.2)])['detections'][0]['session_id']
        for t in (0.13, 0.7, 1.2):
            row = h.feed(t, [person(0.2)])['detections'][0]
        assert row['accumulated_duration_us'] == 1_200_000
        watermark = h.pipeline.writer.seq
        late = h.pipeline.feed([person(0.8)], 1_600_000, 600_000_000, 100, 'camera')
        assert late['ignored'] and late['detections'] == []
        duplicate = h.pipeline.feed([person(0.8)], 3_000_000, 2_000_000_000, h.sequence, 'camera')
        assert duplicate['ignored'] and h.pipeline.writer.seq == watermark
        # Calendar rollback has no effect on the monotonic timer.
        corrected = h.pipeline.feed([person(0.2)], 100, 1_400_000_000, h.sequence + 1, 'camera')
        h.sequence += 1
        assert corrected['detections'][0]['accumulated_duration_us'] == 1_400_000
        h.feed(1.6, unavailable='CAMERA_OFFLINE')
        row = h.feed(2, [person(0.2)], generation='reconnected')['detections'][0]
        assert row['session_id'] != sid and row['accumulated_duration_us'] == 0
        late = h.pipeline.feed([person(0.2)], 2_800_000, 1_800_000_000, 999, 'camera')
        assert late['ignored']
        retired = h.pipeline.feed([person(0.8)], 3_200_000, 2_200_000_000, 1000, 'camera')
        assert retired['ignored']
        stale_mapping = h.pipeline.feed([person(0.8)], 3_200_000, 2_200_000_000, 1000, 'reconnected', mapping_version=0)
        assert stale_mapping['ignored']
        assert db.conn.execute('SELECT accumulated_duration_us FROM person_sessions WHERE session_id=?', (sid,)).fetchone()[0] == 1_400_000


def test_missed_detection_does_not_prove_roi_exit(tmp_path):
    config = replace(settings(tmp_path / 'unused.sqlite3'), zones=(Zone('desk', 'Desk', ((0, 0), (0.5, 0), (0.5, 1), (0, 1))),))
    manager = SessionManager(config)
    for i in range(6):
        binding = manager.update([person(0.39, '1')], i * 200_000, i * 200_000_000, 'camera')[0][1]
        manager.checkpoint()
    sid = binding.session_id
    manager.update([], 1_200_000, 1_200_000_000, 'camera')
    assert manager.sessions[sid].status == 'LOST'
    assert manager.sessions[sid].zones['desk'].inside
    assert manager.sessions[sid].zones['desk'].duration_ns == 1_000_000_000
    # Consistent visible motion outside a zone eventually proves exit.
    manager = SessionManager(config)
    for i, x in enumerate((0.39, 0.43, 0.47, 0.51, 0.53, 0.55)):
        binding = manager.update([person(x, '1')], i * 200_000, i * 200_000_000, 'camera')[0][1]
        manager.checkpoint()
    assert not binding.zones['desk'].inside


def test_state_history_and_duplicate_track_ids_are_bounded(tmp_path):
    manager = SessionManager(settings(tmp_path / 'unused.sqlite3', max_sessions=6))
    for i in range(1000):
        rows = manager.update([person(0.1, 'reuse'), person(0.7, 'reuse')], i * 2_000_000, i * 2_000_000_000, 'camera')
        assert len(manager.sessions) <= 6
        assert len({s.track_lifecycle for _, s in rows if s}) == len([s for _, s in rows if s])
        assert all(s.track_id is None for _, s in rows if s)
        assert all(len(s.history) <= 8 for s in manager.sessions.values())
        manager.checkpoint()
        assert manager.dirty == {} and manager.events == []


def test_bytetrack_reset_cannot_reuse_full_track_key():
    tracker = Tracker(5, 1)
    first = tracker.update([person(0.1)], 0, 'camera')[0].track_id
    after_reset = tracker.update([person(0.1)], 2, 'camera')[0].track_id
    assert first is not None and after_reset is not None and first != after_reset


def test_real_bytetrack_gap_reset_still_recovers_application_session(tmp_path):
    with harness(tmp_path) as (h, _):
        h.pipeline.tracker = Tracker(5, 1)
        sid = h.prime()
        old_track = h.pipeline.latest['detections'][0]['track_id']
        h.feed(15.2)
        returned = h.return_a()['detections'][0]
        assert returned['track_id'] != old_track
        assert returned['session_id'] == sid
        assert returned['accumulated_duration_us'] == 15_200_000


def test_visible_exit_and_weak_detections_cannot_recover(tmp_path):
    manager = SessionManager(settings(tmp_path / 'unused.sqlite3'))
    for step in range(6):
        t = step / 5
        old = manager.update([person(0.80 + 0.1 * t)], round(t * 1e6), round(t * 1e9), 'camera')[0][1]
        manager.checkpoint()
    manager.update([], 1_200_000, 1_200_000_000, 'camera')
    for t in (1.3, 1.5, 1.7):
        row = manager.update([person(0.9 - 0.1 * (t - 1))], round(t * 1e6), round(t * 1e9), 'camera')[0][1]
        assert row.session_id != old.session_id
        manager.checkpoint()
    with harness(tmp_path) as (h, _):
        sid = h.prime()
        h.feed(15.2)
        for t in (18, 18.1, 18.2):
            weak = replace(moving_a(t), confidence=0.2)
            assert h.feed(t, [weak])['detections'][0]['session_id'] != sid


def test_retention_does_not_extend_identity_recovery_window(tmp_path):
    with harness(tmp_path, motion_recovery_seconds=0.5) as (h, _):
        sid = h.prime()
        h.feed(15.2)
        result = h.return_a()
        assert result['detections'][0]['session_id'] != sid
        assert h.pipeline.sessions.sessions[sid].status == 'LOST'


def test_all_active_capacity_never_steals_an_existing_session(tmp_path):
    manager = SessionManager(settings(tmp_path / 'unused.sqlite3', max_sessions=2))
    rows = manager.update([person(0.1), person(0.4), person(0.7)], 0, 0, 'camera')
    assert [s is None for _, s in rows] == [False, False, True]
    assert len(manager.sessions) == 2
    assert manager.metrics['capacity_rejected'] == 1


def test_session_configuration_load_and_validation(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'sessions': {'count_lost_gap': True, 'grace_period_seconds': 12}}))
    assert load_settings(path).sessions.count_lost_gap
    assert load_settings(path).sessions.grace_period_seconds == 12
    for values in ({'grace_period_seconds': -1}, {'motion_recovery_seconds': 20}, {'history_size': 0},
                   {'count_lost_gap': 'false'}, {'minimum_match_score': float('nan')}):
        with pytest.raises(ValueError):
            SessionRules(**values)


def test_session_upsert_and_checkpoint_are_atomic(tmp_path):
    with harness(tmp_path) as (h, db):
        sid = h.feed(0, [person(0.2)])['detections'][0]['session_id']
        db.conn.execute("CREATE TRIGGER reject_session_update BEFORE UPDATE ON person_sessions BEGIN SELECT RAISE(ABORT,'injected disk failure'); END")
        watermark = h.pipeline.writer.seq
        with pytest.raises(Exception, match='injected disk failure'):
            h.feed(0.2, [person(0.2)])
        assert h.pipeline.writer.seq == watermark
        assert db.conn.execute('SELECT MAX(producer_seq) FROM event_log').fetchone()[0] == watermark
        assert db.conn.execute('SELECT accumulated_duration_us FROM person_sessions WHERE session_id=?', (sid,)).fetchone()[0] == 0
        db.conn.execute('DROP TRIGGER reject_session_update')
