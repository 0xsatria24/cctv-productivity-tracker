"""Concurrency fixtures exercise arbitration, not camera/model accuracy."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time

import pytest

from cctv_tracker.inference import InferenceScheduler, SchedulingRules


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, 'Scheduler condition did not become true'
        time.sleep(0.002)


class Detector:
    def __init__(self, *, hold=False):
        self.entered, self.release = Event(), Event()
        if not hold:
            self.release.set()
        self.lock = Lock()
        self.calls, self.concurrent, self.high_water = [], 0, 0

    def detect(self, data):
        with self.lock:
            self.concurrent += 1
            self.high_water = max(self.high_water, self.concurrent)
            self.calls.append(data)
        try:
            self.entered.set()
            assert self.release.wait(5), 'Test gate was not released'
            if data == b'invalid':
                raise ValueError('Invalid fixture frame')
            return {'marker': data.decode(), 'detections': [], 'count': 0}
        finally:
            with self.lock:
                self.concurrent -= 1


def test_fifo_per_camera_prevents_flood_and_serializes_one_model():
    raw = Detector(hold=True)
    scheduler = InferenceScheduler(raw)
    lanes = [scheduler.bind(camera) for camera in ('A', 'B', 'C')]
    with ThreadPoolExecutor(max_workers=3) as pool:
        a = pool.submit(lanes[0].detect, b'A')
        assert raw.entered.wait(2)
        b = pool.submit(lanes[1].detect, b'B')
        until(lambda: scheduler.snapshot()['pending'] == 1)
        c = pool.submit(lanes[2].detect, b'C')
        until(lambda: scheduler.snapshot()['pending'] == 2)
        try:
            for _ in range(20):
                with pytest.raises(BlockingIOError):
                    lanes[0].detect(b'flood')
        finally:
            raw.release.set()
        assert [f.result()['scheduler']['source_id'] for f in (a, b, c)] == ['A', 'B', 'C']
    assert raw.calls == [b'A', b'B', b'C']
    assert raw.high_water == 1
    assert scheduler.snapshot()['rejected'] == 20
    assert scheduler.snapshot()['completed'] == 3


def test_capacity_and_deadlines_bound_backlog_without_empty_results():
    raw = Detector(hold=True)
    scheduler = InferenceScheduler(raw, SchedulingRules(queue_capacity=1, max_streams=3, max_wait_seconds=0.1))
    a, b, c = (scheduler.bind(key) for key in ('A', 'B', 'C'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(a.detect, b'A')
        assert raw.entered.wait(2)
        waiting = pool.submit(b.detect, b'B')
        until(lambda: scheduler.snapshot()['pending'] == 1)
        try:
            with pytest.raises(BlockingIOError):
                c.detect(b'C')
            with pytest.raises(BlockingIOError, match='batas waktu'):
                waiting.result(timeout=2)
            assert raw.calls == [b'A']
            assert scheduler.snapshot()['pending'] == 0
        finally:
            raw.release.set()
        running.result()
    assert c.detect(b'C')['marker'] == 'C'
    assert scheduler.snapshot()['expired'] == 1


def test_fps_cooldown_does_not_hold_turn_for_other_camera():
    raw = Detector()
    scheduler = InferenceScheduler(raw)
    a, b = scheduler.bind('A', max_fps=5), scheduler.bind('B')
    a.detect(b'A-first')
    with ThreadPoolExecutor(max_workers=2) as pool:
        again = pool.submit(a.detect, b'A-second')
        until(lambda: scheduler.snapshot()['pending'] == 1)
        other = pool.submit(b.detect, b'B')
        assert other.result()['marker'] == 'B'
        again.result()
    assert raw.calls == [b'A-first', b'B', b'A-second']


def test_refresh_runs_only_after_turn_and_carries_new_generation():
    raw = Detector(hold=True)
    scheduler = InferenceScheduler(raw)
    refreshed = Event()
    old = {'jpeg': b'old', 'monotonic_ns': time.perf_counter_ns(), 'generation': 'old'}
    def refresh():
        refreshed.set()
        return {'jpeg': b'new', 'monotonic_ns': time.perf_counter_ns(), 'generation': 'new'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(scheduler.bind('A').detect, b'A')
        assert raw.entered.wait(2)
        second = pool.submit(scheduler.bind('B').detect_latest, old, refresh, 1)
        until(lambda: scheduler.snapshot()['pending'] == 1)
        assert not refreshed.is_set()
        raw.release.set()
        first.result()
        result, selected = second.result()
    assert result['marker'] == 'new'
    assert selected['generation'] == 'new'
    assert raw.calls == [b'A', b'new']
    assert scheduler.snapshot()['refreshed'] == 1


def test_stale_and_future_frames_and_inference_overruns_never_return_evidence():
    raw = Detector()
    lane = InferenceScheduler(raw).bind('camera')
    for at in (time.perf_counter_ns()-2_000_000_000, time.perf_counter_ns()+2_000_000_000):
        with pytest.raises(ValueError, match='stale'):
            lane.detect_latest({'jpeg': b'stale', 'monotonic_ns': at}, None, 0.1)
    assert raw.calls == []
    raw.release.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        frame = {'jpeg': b'slow', 'monotonic_ns': time.perf_counter_ns()}
        future = pool.submit(lane.detect_latest, frame, None, 0.05)
        assert raw.entered.wait(2)
        time.sleep(0.08)
        raw.release.set()
        with pytest.raises(ValueError, match='umur frame'):
            future.result()


@pytest.mark.parametrize('cancel', ['session', 'lane', 'scheduler'])
def test_cancel_releases_pending_and_suppresses_stopped_results(cancel):
    raw = Detector(hold=True)
    scheduler = InferenceScheduler(raw)
    a, b = scheduler.bind('A'), scheduler.bind('B')
    stop = Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(a.detect, b'A')
        assert raw.entered.wait(2)
        waiting = pool.submit(b.detect_latest, {'jpeg': b'B', 'monotonic_ns': time.perf_counter_ns()}, None, 1, stop_event=stop)
        until(lambda: scheduler.snapshot()['pending'] == 1)
        if cancel == 'session':
            stop.set()
        elif cancel == 'lane':
            b.close()
        else:
            scheduler.close(timeout=0)
        try:
            with pytest.raises(BlockingIOError, match='dibatalkan'):
                waiting.result(timeout=2)
        finally:
            raw.release.set()
        if cancel == 'scheduler':
            with pytest.raises(BlockingIOError):
                active.result()
        else:
            active.result()
    assert raw.calls == [b'A']
    assert scheduler.snapshot()['pending'] == 0


def test_detector_exception_releases_turn_and_closed_lane_cannot_reenter():
    raw = Detector()
    scheduler = InferenceScheduler(raw)
    a, b = scheduler.bind('A'), scheduler.bind('B')
    with pytest.raises(ValueError, match='Invalid fixture'):
        a.detect(b'invalid')
    assert b.detect(b'B')['marker'] == 'B'
    a.close()
    with pytest.raises(BlockingIOError):
        a.detect(b'A')
    assert scheduler.snapshot()['failed'] == 1


def test_stream_metrics_are_bounded_and_eviction_does_not_evict_active_sources():
    scheduler = InferenceScheduler(Detector(), SchedulingRules(queue_capacity=1, max_streams=2))
    for i in range(100):
        scheduler.bind(str(i)).detect(b'frame')
    status = scheduler.snapshot()
    assert len(status['streams']) == 2
    assert status['completed'] == 100
    assert '99' in status['streams']


@pytest.mark.parametrize('kwargs', [{'queue_capacity': 0}, {'queue_capacity': True}, {'max_streams': 1},
    {'max_wait_seconds': 0}, {'max_wait_seconds': float('inf')}, {'max_wait_seconds': 31}, {'max_wait_seconds': True}])
def test_invalid_scheduler_limits_rejected(kwargs):
    with pytest.raises(ValueError):
        SchedulingRules(**kwargs)


def test_four_camera_accounting_shares_model_and_stalled_capture_does_not_block(tmp_path, monkeypatch):
    from contextlib import closing
    from dataclasses import replace
    from types import SimpleNamespace
    from test_live import FixtureDetector, profile, wait_for
    from test_headless import entitlement
    import editions.headless.service as module
    from cctv_tracker.config import Settings
    from cctv_tracker.live import LiveController
    from cctv_tracker.persistence import Database
    from cctv_tracker.rtsp import rtsp_camera_key

    class SharedDetector(FixtureDetector):
        def __init__(self):
            super().__init__()
            self.concurrent, self.high_water, self.total = 0, 0, 0
            self.lock = Lock()
        def detect(self, jpeg):
            with self.lock:
                self.concurrent += 1
                self.high_water = max(self.high_water, self.concurrent)
                self.total += 1
            try:
                time.sleep(0.015)
                return super().detect(jpeg)
            finally:
                with self.lock:
                    self.concurrent -= 1

    class Capture:
        def __init__(self, url, settings):
            self.camera, self.started, self.sequence = settings.camera_id, time.perf_counter(), 0
            self.process = SimpleNamespace(is_alive=lambda: True)
        def read(self, timeout):
            if timeout:
                time.sleep(0.015)
            self.sequence += 1
            if self.camera == 'stalled' and self.sequence > 4:
                return None
            return {'jpeg': b'fixture', 'generation': self.camera, 'monotonic_ns': time.perf_counter_ns()}
        def close(self):
            pass

    created = []
    def create(*args, **kwargs):
        created.append(SharedDetector())
        return created[-1]
    monkeypatch.setattr(module, 'create_detector', create)
    monkeypatch.setattr(module, 'create_live_engine', lambda settings, detector: LiveController(settings, detector, capture_factory=Capture))
    service = module.EngineService(Settings(database=tmp_path / 'headless.sqlite3'), entitlement(4))
    try:
        for name in ('one', 'two', 'three', 'stalled'):
            url = 'rtsp://localhost/' + name
            service.add(name, url)
            calibration = profile()
            calibration['camera_key'] = rtsp_camera_key(url)
            calibration['rules']['max_evidence_gap_seconds'] = 0.5
            service.get(name).save_calibration('RTSP_LIVE', calibration)
            service.start(name)
        wait_for(lambda: all(service.status(key)['processed'] >= 7 for key in ('one', 'two', 'three')))
        wait_for(lambda: service.status('stalled')['latest'] is None)
        assert len(created) == 1
        assert created[0].high_water == 1
        identities = set()
        for key in ('one', 'two', 'three'):
            state = service.status(key)
            assert set(state['scheduler']['streams']) == {'camera:' + key}
            assert state['latest']['scheduler']['source_id'] == 'camera:' + key
            assert state['latest']['zones'][0]['state'] == 'OCCUPIED'
            for session in state['latest']['sessions']:
                assert session['camera_id'] == key
                assert session['session_id'] not in identities
                identities.add(session['session_id'])
        assert service.scheduling_snapshot()['streams']['camera:stalled']['completed'] >= 1
        # A stalled camera cannot create a false EMPTY observation.
        with closing(Database(service.get('stalled').settings.database, migrate=False)) as db:
            assert db.conn.execute("SELECT COUNT(*) FROM zone_intervals WHERE state='EMPTY'").fetchone()[0] == 0
        service.remove('stalled')
        service.add('replacement', 'rtsp://localhost/replacement')
        assert len(created) == 1
    finally:
        service.shutdown()
    assert service.scheduling_snapshot()['closed']
    assert all(not engine.thread or not engine.thread.is_alive() for _, engine in service.cameras.values())


def test_concurrent_replay_and_webcam_requests_share_scheduler_without_cross_binding(tmp_path, monkeypatch):
    from uuid import uuid4
    import cv2
    import numpy as np
    from fastapi.testclient import TestClient
    from cctv_tracker.api import create_app
    from cctv_tracker.config import Settings
    from cctv_tracker.dashboard import ReplayController
    from cctv_tracker.persistence import Database
    from cctv_tracker.webcam import WebcamDetector
    raw = Detector()
    def detect(self, jpeg):
        result = raw.detect(b'fixture')
        return {**result, 'width': 320, 'height': 240, 'recorded': False}
    monkeypatch.setattr(WebcamDetector, 'detect', detect)
    config = Settings(database=tmp_path / 'api.sqlite3')
    db = Database(config.database)
    db.close()
    app = create_app(config.database, 't'*32, controller=ReplayController(config))
    jpeg = cv2.imencode('.jpg', np.zeros((240, 320, 3), dtype=np.uint8))[1].tobytes()
    headers = {'Authorization': 'Bearer ' + 't'*32, 'Content-Type': 'image/jpeg'}
    ids = [str(uuid4()) for _ in range(4)]
    with TestClient(app) as client:
        def replay(replay_id):
            return client.post('/pilot/v1/replay/frame', content=jpeg, headers={**headers,
                'X-Replay-Id': replay_id, 'X-Replay-Generation': '0', 'X-Replay-Sequence': '1', 'X-Replay-Time': '0'})
        with ThreadPoolExecutor(max_workers=5) as pool:
            requests = [pool.submit(replay, key) for key in ids]
            webcam = pool.submit(client.post, '/pilot/v1/webcam/frame', content=jpeg, headers=headers)
            for replay_id, future in zip(ids, requests):
                response = future.result()
                assert response.status_code == 200, response.text
                result = response.json()
                assert result['replay_id'] == replay_id
                assert result['scheduler']['source_id'] == 'replay:' + replay_id
                assert result['recorded'] is False and result['duration_accounting'] is False
            assert webcam.result().json()['scheduler']['source_id'] == 'webcam-preview'
        assert raw.high_water == 1
        assert app.state.inference_scheduler.snapshot()['completed'] == 5
        status = client.get('/pilot/v1/status', headers=headers).json()
        assert status['scheduler']['policy'] == 'fifo-per-source'
        assert status['live']['processed'] == 0
    assert app.state.inference_scheduler.snapshot()['closed']
