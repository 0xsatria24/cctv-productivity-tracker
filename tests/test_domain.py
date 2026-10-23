from dataclasses import replace
import pytest

from cctv_tracker.config import Rules, Zone, load_settings, timestamp
from cctv_tracker.domain.geometry import overlap_ratio
from cctv_tracker.domain.occupancy import Observation, State, ZoneAccumulator, summarize
from cctv_tracker.vision import Detection, Tracker, associate


def observation(second, state=State.OCCUPIED, count=1, *, seq=None, generation="camera-1", reason=None):
    return Observation(round(second * 1e6), round(second * 1e9), seq or round(second * 5) + 1, generation, state, count, reason)


def test_confirmation_never_backdates_and_count_does_not_multiply_presence():
    zone = ZoneAccumulator(0, Rules())
    for i in range(21):
        zone.feed(observation(i / 5, count=2 if i >= 12 else 1))
    result = summarize(zone.snapshot(), 0, 4_000_000)
    assert result["occupied_us"] == 2_000_000
    assert result["unknown_us"] == 2_000_000
    assert result["utilization"] == 1
    assert len([r for r in zone.snapshot() if r.state == State.OCCUPIED]) == 2


def test_gap_stops_at_last_evidence_and_requires_new_confirmation():
    zone = ZoneAccumulator(0, Rules())
    for i in range(16):
        zone.feed(observation(i / 5))
    zone.feed(observation(10))
    zone.feed(observation(10.2))
    result = summarize(zone.snapshot(), 0, 10_200_000)
    assert result["occupied_us"] == 1_000_000
    assert result["unknown_us"] == 9_200_000
    assert zone.current.state == State.UNKNOWN


def test_first_contradictory_frame_does_not_charge_the_previous_state():
    zone=ZoneAccumulator(0,Rules())
    for i in range(16):
        zone.feed(observation(i/5))
    zone.feed(observation(3.2,State.EMPTY,0))
    result=summarize(zone.snapshot(),0,3_200_000)
    assert result['occupied_us']==1_000_000
    assert result['unknown_us']==2_200_000
    assert zone.current.state==State.UNKNOWN


def test_unavailable_and_generation_change_never_become_empty():
    zone = ZoneAccumulator(0, Rules())
    for i in range(16):
        zone.feed(observation(i / 5))
    zone.feed(observation(3.2, State.UNKNOWN, None, reason="CAMERA_OFFLINE"))
    assert zone.current.start == 3_000_000
    zone.feed(observation(3.4, generation="camera-2", seq=1))
    assert zone.current.state == State.UNKNOWN
    assert summarize(zone.snapshot(), 0, 3_400_000)["empty_us"] == 0


def test_empty_requires_five_seconds_of_valid_confirmation():
    zone = ZoneAccumulator(0, Rules())
    for i in range(31):
        zone.feed(observation(i / 5, State.EMPTY, 0))
    result = summarize(zone.snapshot(), 0, 6_000_000)
    assert result["empty_us"] == 1_000_000
    assert result["unknown_us"] == 5_000_000


def test_reject_duplicate_and_clock_rollback():
    zone = ZoneAccumulator(0, Rules())
    zone.feed(observation(0))
    with pytest.raises(ValueError, match="Duplicate"):
        zone.feed(observation(0))
    zone.feed(observation(0.2))
    with pytest.raises(ValueError, match="Clock"):
        zone.feed(observation(0.1, seq=3))


def test_zero_denominator_and_query_tail_remain_unknown():
    zone = ZoneAccumulator(0, Rules())
    zone.feed(observation(0))
    result = summarize(zone.snapshot(), 0, 10_000_000)
    assert result == {"eligible_us": 10_000_000, "occupied_us": 0, "empty_us": 0, "unknown_us": 10_000_000, "utilization": None, "coverage": 0}


def test_polygon_rejects_self_intersection_and_nonfinite_points():
    with pytest.raises(ValueError):
        Zone("a", "a", ((0, 0), (1, 1), (0, 1), (1, 0)))
    with pytest.raises(ValueError):
        Zone("a", "a", ((0, 0), (float("nan"), 1), (1, 0)))
    assert overlap_ratio((0.25, 0.25, 0.75, 0.75), ((0, 0), (0.5, 0), (0.5, 1), (0, 1))) == 0.5


def test_adjacent_zone_tie_is_unknown_not_double_counted():
    zones = (Zone("a", "a", ((0, 0), (0.5, 0), (0.5, 1), (0, 1))),
             Zone("b", "b", ((0.5, 0), (1, 0), (1, 1), (0.5, 1))))
    result = associate([Detection((0.4, 0.2, 0.6, 0.8), 0.95)], zones, Rules())
    assert all(row[0] == State.UNKNOWN for row in result.values())
    result = associate([Detection((0.1, 0.2, 0.4, 0.8), 0.2)], zones, Rules())
    assert result["a"][0] == State.UNKNOWN
    assert result["b"][0] == State.EMPTY


def test_untracked_fresh_detection_still_provides_presence():
    zone = Zone("a", "a", ((0, 0), (1, 0), (1, 1), (0, 1)))
    result = associate([Detection((0.1, 0.1, 0.3, 0.5), 0.95)], (zone,), Rules())
    assert result["a"] == (State.OCCUPIED, 1, None)


def test_bytetrack_ids_are_anonymous_and_predictions_not_evidence():
    tracker = Tracker(5, 1)
    detection = Detection((0.1, 0.1, 0.4, 0.8), 0.95)
    initial = tracker.update([detection], 0, "generation-1")
    following = tracker.update([detection], 0.2, "generation-1")
    assert initial[0].track_id == following[0].track_id
    assert following[0].track_id.startswith("generation-1:")
    assert tracker.update([], 0.4, "generation-1") == []
    assert tracker.update([detection], 5, "generation-2")[0].track_id.startswith("generation-2:")


def test_slow_inference_confirms_new_tracks_without_fabricated_empty_frames():
    tracker = Tracker(5, 3)
    detection = Detection((0.1, 0.1, 0.4, 0.8), 0.95)
    assert tracker.update([], 0, 'camera') == []
    # A person enters after startup; actual samples arrive at 2.5 FPS.
    tracker.update([detection], 0.4, 'camera')
    confirmed = tracker.update([detection], 0.8, 'camera')[0].track_id
    assert confirmed is not None
    for at in (1.2, 1.6, 2.0):
        assert tracker.update([detection], at, 'camera')[0].track_id == confirmed
    assert tracker.update([], 2.4, 'camera') == []


def test_unknown_settings_and_naive_timestamps_fail(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"secret_password":"value"}')
    with pytest.raises(ValueError, match="Unsupported"):
        load_settings(path)
    with pytest.raises(ValueError, match="timezone"):
        timestamp("2026-10-12T09:00:00")


def test_unknown_reason_history_is_not_rewritten_by_reconfirmation():
    zone = ZoneAccumulator(0, Rules())
    for i in range(16):
        zone.feed(observation(i / 5))
    zone.feed(observation(3.2, State.UNKNOWN, None, reason="CAMERA_OFFLINE"))
    zone.feed(observation(3.4, State.UNKNOWN, None, reason="CAMERA_OFFLINE"))
    zone.feed(observation(3.6))
    assert any(row.reason == "CAMERA_OFFLINE" and row.start == 3_000_000 and row.until == 3_600_000 for row in zone.snapshot())
    assert zone.current.reason == "PENDING_CONFIRMATION"
    assert zone.current.start == 3_600_000
