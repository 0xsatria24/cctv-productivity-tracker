"""Replay media-time and transport regression tests with supplied detections."""
from uuid import uuid4

import pytest

from cctv_tracker.replay_tracking import ReplayConflict, ReplayFrame, ReplayTracking


class Detector:
    def __init__(self):
        self.rows, self.calls = [], 0

    def detect(self, _jpeg):
        self.calls += 1
        return {'detections': self.rows, 'inference_ms': 1, 'recorded': True}


def moving(t):
    x = .05 + .02 * t
    return {'box': [x, .35, x + .1, .6], 'confidence': .95}


def test_weak_frame_keeps_continuous_replay_session_but_does_not_charge_time():
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    def feed(seq, confidence):
        detector.rows = [{**moving(0), 'confidence': confidence}]
        return replay.process(detector, b'', ReplayFrame(replay_id, 0, seq, (seq-1)*.2))
    first = feed(1,.95)['detections'][0]['session_id']
    assert feed(2,.95)['detections'][0]['accumulated_duration_us'] == 200_000
    weak = feed(3,.47)['detections'][0]
    assert weak['session_id'] == first and weak['evidence_state'] == 'WEAK'
    assert weak['accumulated_duration_us'] == 200_000
    strong = feed(4,.95)['detections'][0]
    assert strong['session_id'] == first and strong['accumulated_duration_us'] == 200_000
    assert feed(5,.95)['detections'][0]['accumulated_duration_us'] == 400_000


def test_weak_frames_cannot_start_or_keep_identity_alive_indefinitely():
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    detector.rows = [{**moving(0), 'confidence': .47}]
    assert replay.process(detector,b'',ReplayFrame(replay_id,0,1,0))['detections'][0]['session_id'] is None
    detector.rows = [moving(0)]
    first = replay.process(detector,b'',ReplayFrame(replay_id,0,2,.2))['detections'][0]['session_id']
    detector.rows = [{**moving(0), 'confidence': .47}]
    for seq in range(3,10):
        replay.process(detector,b'',ReplayFrame(replay_id,0,seq,(seq-1)*.2))
    assert replay.streams[replay_id].sessions.sessions[first].status == 'LOST'


def test_visual_hold_expires_without_counting_or_recovering_presence():
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    detector.rows = [moving(0)]
    first = replay.process(detector,b'',ReplayFrame(replay_id,0,1,0))
    detector.rows = []
    lost = replay.process(detector,b'',ReplayFrame(replay_id,0,2,.2))
    assert lost['count'] == 0 and lost['detections'] == []
    held = lost['display_detections'][0]
    assert held['session_id'] == first['detections'][0]['session_id']
    assert not held['measured'] and held['accumulated_duration_us'] == 0
    assert lost['sessions'][0]['status'] == 'LOST'
    assert replay.process(detector,b'',ReplayFrame(replay_id,0,3,.6))['display_detections'] == []
    assert replay.process(detector,b'',ReplayFrame(replay_id,1,4,0))['display_detections'] == []


def test_visual_hold_does_not_duplicate_a_new_measured_person():
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    detector.rows = [moving(0)]
    replay.process(detector,b'',ReplayFrame(replay_id,0,1,0))
    replay.process(detector,b'',ReplayFrame(replay_id,0,2,.2))
    detector.rows = [{**moving(0), 'box': [.05,.35,.2,.6]}]
    packet = replay.process(detector,b'',ReplayFrame(replay_id,0,3,.4))
    assert len(packet['display_detections']) == len(packet['detections']) == 1


def test_reid_shadow_gallery_isolated_by_file_and_seek_and_stale_frames():
    from dataclasses import replace
    from cctv_tracker.config import Settings
    from cctv_tracker.reid.config import ReIdRules
    from reid_helpers import FakeExtractor, jpeg

    extractor = FakeExtractor()
    settings = replace(Settings(), reid=ReIdRules(mode='shadow', manifest_path='injected', max_extra_latency_ms=60000))
    replay = ReplayTracking(settings, reid_extractor=extractor)
    detector, first, second = Detector(), str(uuid4()), str(uuid4())
    detector.rows = [{'box': [.1, .1, .25, .8], 'confidence': .95}]
    image = jpeg()
    initial = replay.process(detector, image, ReplayFrame(first, 0, 1, 1))
    assert initial['reid']['status'] == 'SHADOW' and initial['reid']['gallery_sessions'] == 1
    replay.process(detector, image, ReplayFrame(first, 0, 2, 1.4))
    original = initial['detections'][0]['session_id']
    assert len(replay.streams[first].reid.gallery.entries[original]) == 2
    other = replay.process(detector, image, ReplayFrame(second, 0, 1, 1))
    assert other['detections'][0]['session_id'] != original
    assert original not in replay.streams[second].reid.gallery.entries
    calls = extractor.calls
    with pytest.raises(ReplayConflict):
        replay.process(detector, image, ReplayFrame(first, 0, 2, 1.4))
    assert extractor.calls == calls
    restarted = replay.process(detector, image, ReplayFrame(first, 1, 3, 0))
    assert original not in replay.streams[first].reid.gallery.entries
    assert restarted['reid']['gallery_sessions'] == 1
    assert not restarted['recorded'] and not restarted['duration_accounting']


def test_replay_timer_recovers_after_three_second_loss_using_media_time(tmp_path):
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    sequence = 0

    def feed(t, rows):
        nonlocal sequence
        sequence += 1
        detector.rows = rows
        return replay.process(detector, b'jpeg', ReplayFrame(replay_id, 0, sequence, t))

    for step in range(76):
        packet = feed(step / 5, [moving(step / 5)])
    original = packet['detections'][0]['session_id']
    assert packet['detections'][0]['accumulated_duration_us'] == 15_000_000
    lost = feed(15.2, [])
    assert lost['detections'] == []
    assert lost['sessions'][0]['status'] == 'LOST'
    assert lost['sessions'][0]['accumulated_duration_us'] == 15_000_000
    for t in (18, 18.1, 18.2):
        recovered = feed(t, [moving(t)])
    row = recovered['detections'][0]
    assert row['session_id'] == original
    assert row['accumulated_duration_us'] == pytest.approx(15_200_000, abs=1)
    assert not row['recovery_pending']
    assert recovered['duration_basis'] == 'observed_media_time'
    assert recovered['tracking_supported'] and not recovered['recorded'] and not recovered['duration_accounting']
    assert list(tmp_path.iterdir()) == []


def test_files_and_seek_generations_have_separate_timers_and_reject_late_frames():
    replay, detector = ReplayTracking(), Detector()
    first, second = str(uuid4()), str(uuid4())
    detector.rows = [moving(0)]
    initial = replay.process(detector, b'', ReplayFrame(first, 0, 1, 4))
    continued = replay.process(detector, b'', ReplayFrame(first, 0, 2, 4.5))
    assert continued['detections'][0]['accumulated_duration_us'] == 500_000
    # Time spent paused is absent from the media timeline and cannot inflate time.
    other = replay.process(detector, b'', ReplayFrame(second, 0, 1, 4.5))
    assert other['detections'][0]['session_id'] != initial['detections'][0]['session_id']
    assert other['detections'][0]['accumulated_duration_us'] == 0
    restarted = replay.process(detector, b'', ReplayFrame(first, 1, 3, 0))
    assert restarted['detections'][0]['session_id'] != initial['detections'][0]['session_id']
    assert restarted['detections'][0]['accumulated_duration_us'] == 0
    calls = detector.calls
    for frame in (ReplayFrame(first, 0, 4, 5), ReplayFrame(first, 1, 3, .2), ReplayFrame(first, 1, 4, 0)):
        with pytest.raises(ReplayConflict):
            replay.process(detector, b'', frame)
    assert detector.calls == calls
    assert replay.process(detector, b'', ReplayFrame(first, 1, 4, .2))['detections'][0]['accumulated_duration_us'] == 200_000


def test_stationary_replacement_cannot_inherit_lost_person_timer():
    replay, detector, replay_id = ReplayTracking(), Detector(), str(uuid4())
    detector.rows = [moving(0)]
    for sequence in range(1, 7):
        packet = replay.process(detector, b'', ReplayFrame(replay_id, 0, sequence, sequence / 5))
    original = packet['detections'][0]['session_id']
    detector.rows = []
    replay.process(detector, b'', ReplayFrame(replay_id, 0, 7, 1.4))
    detector.rows = [moving(0)]
    for sequence in range(8, 12):
        packet = replay.process(detector, b'', ReplayFrame(replay_id, 0, sequence, sequence / 5))
    assert packet['detections'][0]['session_id'] != original
    retained = next(session for session in packet['sessions'] if session['session_id'] == original)
    assert retained['status'] == 'LOST' and retained['accumulated_duration_us'] == 1_000_000


def test_stream_capacity_and_busy_frames_do_not_reset_existing_session():
    replay, detector, replay_id = ReplayTracking(capacity=1), Detector(), str(uuid4())
    detector.rows = [moving(0)]
    packet = replay.process(detector, b'', ReplayFrame(replay_id, 0, 1, 0))
    with pytest.raises(BlockingIOError):
        replay.process(detector, b'', ReplayFrame(str(uuid4()), 0, 1, 0))
    with replay.streams[replay_id].lock, pytest.raises(BlockingIOError):
        replay.process(detector, b'', ReplayFrame(replay_id, 0, 2, .2))
    continued = replay.process(detector, b'', ReplayFrame(replay_id, 0, 2, .2))
    assert continued['detections'][0]['session_id'] == packet['detections'][0]['session_id']


@pytest.mark.parametrize('field,value', [('x-replay-id', 'bad'), ('x-replay-time', 'nan'),
                                        ('x-replay-time', '-1'), ('x-replay-generation', '-1'),
                                        ('x-replay-sequence', '0'), ('x-replay-sequence', '1.5')])
def test_invalid_replay_envelope(field, value):
    headers = {'x-replay-id': str(uuid4()), 'x-replay-generation': '0',
               'x-replay-sequence': '1', 'x-replay-time': '0'}
    with pytest.raises(ValueError):
        ReplayFrame.from_headers({**headers, field: value})
    with pytest.raises(ValueError):
        ReplayFrame.from_headers({'x-replay-id': str(uuid4())})
    assert ReplayFrame.from_headers({}) is None
