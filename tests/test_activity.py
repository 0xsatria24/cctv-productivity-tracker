import cv2
import numpy as np
import pytest

from cctv_tracker.activity import TrackActivity
from cctv_tracker.performance import AdaptiveRate, Performance
from cctv_tracker.shared_capture import SharedPreviewCapture


def scene(x=100, camera_shift=0):
    rng = np.random.default_rng(11)
    gray = rng.integers(35,80,(240,320),dtype=np.uint8)
    texture = rng.integers(110,240,(100,50),dtype=np.uint8)
    gray[60:160,x:x+50] = texture
    if camera_shift:
        gray = cv2.warpAffine(gray,np.float32([[1,0,camera_shift],[0,1,0]]),(320,240))
    return cv2.imencode('.jpg',gray)[1].tobytes()


def detection(x=100, confidence=.9):
    return {'track_id':'camera:1','box':[x/320,60/240,(x+50)/320,160/240],'confidence':confidence,'workstation_times':[]}


def test_idle_after_confirmation_then_motion_working_and_stationary_hysteresis():
    activity = TrackActivity(idle_seconds=2,working_seconds=.4)
    row = None
    for i in range(14):
        row = detection()
        activity.annotate(scene(),[row],i*200_000_000,'camera')
    assert row['activity']['label'] == 'Idle'
    for i in range(1,6):
        row = detection(100+i*4)
        activity.annotate(scene(100+i*4),[row],(13+i)*200_000_000,'camera')
    assert row['activity']['label'] == 'Working'
    first_elapsed = row['activity']['tracked_elapsed_us']
    for i in range(1,4):
        row = detection(120,.2)  # Weak matched observations retain the display timer.
        activity.annotate(scene(120),[row],(18+i)*200_000_000,'camera')
    assert row['activity']['label'] == 'Working'
    assert row['activity']['tracked_elapsed_us'] > first_elapsed
    assert row['workstation_times'] == []


def test_camera_motion_is_not_worker_motion_and_occlusion_never_becomes_idle():
    activity = TrackActivity(idle_seconds=2)
    for i in range(15):
        shift = i % 4
        row = detection(100+shift)
        activity.annotate(scene(camera_shift=shift),[row],i*200_000_000,'camera')
    assert row['activity']['label'] == 'Idle'
    activity.annotate(scene(),[],3_000_000_000,'camera')
    row = detection()
    activity.annotate(scene(),[row],3_200_000_000,'camera')
    assert row['activity']['label'] is None
    assert row['activity']['tracked_elapsed_us'] == 3_200_000
    row = detection()
    activity.annotate(scene(),[row],7_000_000_000,'new-source')
    assert row['activity']['tracked_elapsed_us'] == 0


def test_featureless_or_missing_person_does_not_create_rest_label():
    activity = TrackActivity(idle_seconds=2)
    blank = cv2.imencode('.jpg',np.zeros((240,320),np.uint8))[1].tobytes()
    for i in range(20):
        row = detection()
        activity.annotate(blank,[row],i*200_000_000,'camera')
    assert row['activity']['label'] is None


def test_motion_can_be_disabled_without_disabling_the_track_timer():
    activity = TrackActivity(enabled=False)
    for at in (0,1_000_000_000,2_000_000_000):
        row = detection()
        activity.annotate(b'not decoded when disabled',[row],at,'camera')
    assert row['activity']['tracked_elapsed_us'] == 2_000_000
    assert row['activity']['label'] is None


def test_timer_uses_tracker_lifecycle_instead_of_expiring_a_retained_id():
    activity = TrackActivity(enabled=False,gap_seconds=3)
    row = detection()
    activity.annotate(b'', [row],0,'camera',{'camera:1'})
    for i in range(1,10):
        activity.annotate(b'',[],i*500_000_000,'camera',{'camera:1'})
    row = detection()
    activity.annotate(b'',[row],5_000_000_000,'camera',{'camera:1'})
    assert row['activity']['tracked_elapsed_us'] == 5_000_000
    activity.annotate(b'',[],5_500_000_000,'camera',set())
    assert not activity.tracks


def test_smoothing_reduces_static_jitter_without_delaying_fast_motion():
    activity = TrackActivity(smoothing_ms=80)
    raw, smooth = [],[]
    for i in range(30):
        x = .1 + (.001 if i%2 else -.001)
        row = {'track_id':'x','box':[x,.1,x+.2,.8],'confidence':.9}
        activity._annotate_states([row],i*.2,'camera',{'x':.01})
        if i > 2:
            raw.append(x);smooth.append(row['display_box'][0])
    assert np.std(smooth) < np.std(raw)
    row = {'track_id':'x','box':[.6,.1,.8,.8],'confidence':.9}
    activity._annotate_states([row],6,'camera',{'x':1})
    assert row['display_box'] == pytest.approx(row['box'])


def test_performance_memory_bounded_and_adaptive_cooldown_disable():
    performance = Performance(limit=8)
    for i in range(20):
        performance.record(detector_ms=i,optional=None)
    assert len(performance.rows) == 8
    assert performance.snapshot()['stages']['detector_ms']['p99'] == 19
    rate = AdaptiveRate(5,1,True)
    for i in range(10):
        rate.observe(.5,10+i*.1)
    assert rate.fps == 4
    rate.observe(.5,12)
    assert rate.fps == 4
    rate.observe(.5,16)
    assert rate.fps == 3
    disabled = AdaptiveRate(5,1,False)
    for i in range(100):
        disabled.observe(10,i,cpu_percent=99,available_mb=1)
    assert disabled.fps == 5


def test_shared_subscriber_never_returns_a_frame_before_its_session_anchor():
    from threading import Event
    from types import SimpleNamespace
    import time
    item = {'jpeg':b'old','monotonic_ns':time.perf_counter_ns(),'generation':'camera'}
    preview = SimpleNamespace(_thread=SimpleNamespace(is_alive=lambda:True),_stop=Event(),capture_snapshot=lambda:item)
    subscriber = SharedPreviewCapture(preview)
    assert subscriber.read(timeout=.001) is None
    item = {'jpeg':b'new','monotonic_ns':time.perf_counter_ns(),'generation':'camera'}
    assert subscriber.read(timeout=.01)['jpeg'] == b'new'
    subscriber.close()
    assert not preview._stop.is_set()
