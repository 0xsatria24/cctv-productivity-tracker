from dataclasses import replace
from threading import Event
from uuid import uuid4

from cctv_tracker.config import Settings
from cctv_tracker.reid.config import ReIdRules
from cctv_tracker.replay_tracking import ReplayFrame, ReplayTracking
from reid_helpers import FakeExtractor, jpeg
from test_replay_tracking import Detector, moving


class BlockingExtractor(FakeExtractor):
    def __init__(self):
        super().__init__()
        self.entered, self.release = Event(), Event()

    def extract(self, samples):
        self.entered.set()
        assert self.release.wait(5)
        return super().extract(samples)


def test_slow_reid_never_blocks_boxes_or_queues_frames_and_seek_discards_old_work():
    extractor = BlockingExtractor()
    settings = replace(Settings(), reid=ReIdRules(mode='shadow', manifest_path='injected'))
    replay = ReplayTracking(settings, reid_extractor=extractor, background_reid=True)
    detector, rid, image = Detector(), str(uuid4()), jpeg()
    detector.rows = [moving(0)]
    first = replay.process(detector, image, ReplayFrame(rid, 0, 1, 0))
    assert first['count'] == 1 and first['reid']['status'] == 'PROCESSING'
    assert extractor.entered.wait(2)
    pending = replay.streams[rid].reid_pending
    try:
        for seq in range(2, 8):
            packet = replay.process(detector, image, ReplayFrame(rid, 0, seq, seq*.2))
            assert packet['count'] == 1
            assert replay.streams[rid].reid_pending is pending
        packet = replay.process(detector, image, ReplayFrame(rid, 1, 8, 0))
        assert packet['count'] == 1
        assert replay.streams[rid].reid_pending is None
        assert not replay.streams[rid].reid.gallery.entries
    finally:
        extractor.release.set()
        pending.result(timeout=5)
    assert not replay.streams[rid].reid.gallery.entries


def test_weak_tracked_box_stays_visible_without_charging_time():
    class Candidates(Detector):
        weak = False
        def detect(self, jpeg):
            row = {**moving(0), 'confidence': .95 if not self.weak else .3}
            return {'detections': [] if self.weak else [row],
                    'tracking_candidates': [row] if self.weak else [], 'inference_ms': 1}
    replay, detector, rid = ReplayTracking(), Candidates(), str(uuid4())
    for seq in (1, 2):
        first = replay.process(detector, b'', ReplayFrame(rid, 0, seq, (seq-1)*.2))
    detector.weak = True
    packet = replay.process(detector, b'', ReplayFrame(rid, 0, 3, .4))
    assert packet['count'] == 0
    weak = [row for row in packet['display_detections'] if row['evidence_state'] == 'WEAK']
    assert len(weak) == 1 and weak[0]['measured']
    assert weak[0]['accumulated_duration_us'] == first['detections'][0]['accumulated_duration_us']


def test_background_active_recovery_preserves_timer_and_rejects_old_mapping():
    rules = ReIdRules(mode='active', manifest_path='injected', recovery_policy='short_occlusion',
                     max_extra_latency_ms=60000, sample_interval_seconds=.2, confirm_seconds=.4)
    replay = ReplayTracking(replace(Settings(), reid=rules), reid_extractor=FakeExtractor(), background_reid=True)
    detector, rid, image = Detector(), str(uuid4()), jpeg()
    original = None
    recovered = False
    for seq in range(1, 22):
        at = round((seq-1)*.2, 1)
        detector.rows = [] if 1.2 <= at <= 1.4 else [{'box': [.2,.1,.4,.8], 'confidence': .95}]
        packet = replay.process(detector, image, ReplayFrame(rid, 0, seq, at))
        if original is None:
            original = packet['detections'][0]['session_id']
        if packet['session_metrics'].get('reid_recovered'):
            recovered = True
            assert packet['detections'][0]['session_id'] == original
            assert packet['detections'][0]['accumulated_duration_us'] <= round((at-.6)*1e6)
        pending = replay.streams[rid].reid_pending
        if pending:
            pending.result(timeout=5)
    assert recovered
    assert packet['session_metrics']['reid_recovered'] == 1
