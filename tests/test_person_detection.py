from contextlib import contextmanager
from queue import Queue
from threading import Event

import av
import cv2
import numpy as np
import pytest

from cctv_tracker.config import load_settings
from cctv_tracker.engine import create_detector
from cctv_tracker.person_detection import DetectionTuning, detection_regions, preprocess_yolox, decode_people, suppress_people
from cctv_tracker.rtsp import capture_dimensions, capture_worker


@pytest.mark.parametrize('values', [
    {'confidence': 0}, {'confidence': float('nan')}, {'confidence': True},
    {'nms_iou': 1}, {'nms_iou': '0.5'}, {'detail': 1},
    {'tile_overlap': 0}, {'tile_overlap': float('inf')},
])
def test_invalid_tuning_rejected(values):
    with pytest.raises(ValueError):
        DetectionTuning(**values)


def test_profile_configuration_reaches_both_backends_and_legacy_config_loads(tmp_path):
    tuning = DetectionTuning(detail=True, confidence=.4)
    for kind in ('yolox', 'yolox-openvino'):
        detector = create_detector(kind, tuning=tuning)
        assert detector.tuning == tuning
        assert detector.manifest['detail'] and detector.manifest['threshold'] == .4
    with pytest.raises(ValueError, match='hanya didukung YOLOX'):
        create_detector('nanodet', tuning=tuning)
    file = tmp_path / 'settings.json'
    file.write_text('{"detection":{"detail":true,"confidence":0.4}}')
    assert load_settings(file).detection == tuning
    file.write_text('{}')
    assert load_settings(file).detection == DetectionTuning()


def test_detail_covers_frame_with_overlapping_regions_and_bounded_passes():
    regions = detection_regions(1280, 720, DetectionTuning(detail=True))
    assert regions[0] == (0, 0, 1280, 720) and len(regions) == 5
    assert regions[1][2] > regions[2][0]
    assert regions[1][3] > regions[3][1]
    assert detection_regions(1280, 720, DetectionTuning()) == regions[:1]
    assert len(detection_regions(100, 100, DetectionTuning(detail=True))) == 1


def test_preprocessing_preserves_rgb_contract_and_handles_extreme_aspect_ratio():
    frame = np.full((1, 1280, 3), [10, 20, 30], np.uint8)
    blob, scale = preprocess_yolox(frame)
    assert blob.shape == (1, 3, 640, 640) and scale == .5
    assert blob[0, :, 0, 0].tolist() == [30, 20, 10]
    assert blob[0, :, 639, 639].tolist() == [114, 114, 114]


def prediction(box, confidence=.9):
    x1, y1, x2, y2 = box
    result = np.zeros((1, 85), np.float32)
    result[0, :4] = [(x1 + x2) / 2, (y1 + y2) / 2, np.log(x2 - x1), np.log(y2 - y1)]
    result[0, 4:6] = [1, confidence]
    return result


def decode(p, region=(0, 0, 400, 400), size=(400, 400)):
    return decode_people(p, np.zeros((1, 2)), np.ones((1, 1)), 1, region, size, DetectionTuning())


def test_crop_coordinates_remap_to_original_frame_and_cut_bodies_are_rejected():
    boxes, scores = decode(prediction([20, 30, 120, 200]), (100, 100, 400, 400), (600, 600))
    assert boxes[0] == pytest.approx([120, 130, 220, 300])
    assert scores[0] == pytest.approx(.9)
    assert not len(decode(prediction([0, 20, 100, 200]), (100, 100, 400, 400), (600, 600))[0])
    # A person at the real image boundary is valid; only internal tile seams reject.
    assert len(decode(prediction([0, 20, 100, 200]))[0]) == 1


def test_padding_false_boxes_nan_and_nonperson_predictions_never_become_detections():
    assert not len(decode(prediction([450, 20, 600, 200]))[0])
    bad = prediction([20, 30, 120, 200]); bad[0, 0] = np.nan
    assert not len(decode(bad)[0])
    other = prediction([20, 30, 120, 200]); other[0, 6] = 1
    assert not len(decode(other)[0])


def test_full_body_wins_over_high_confidence_tile_fragment_and_distant_person_survives():
    boxes = [[10, 10, 110, 210], [20, 20, 100, 120], [220, 30, 260, 150], [221, 31, 261, 151]]
    rows = suppress_people(boxes, [.8, .95, .9, .7], (400, 400), DetectionTuning(detail=True), full_frame_count=1)
    assert len(rows) == 2
    assert any(row['box'] == pytest.approx([.025, .025, .275, .525]) for row in rows)


@pytest.mark.parametrize('size', [(3840, 2160), (1920, 1080), (1080, 1920), (640, 480), (4096, 2160)])
def test_capture_preserves_aspect_ratio_without_upscaling_and_bounds_payload(size):
    width, height = capture_dimensions(*size)
    assert max(width, height) <= 1280 and width * height <= 1280 * 720
    assert width <= size[0] and height <= size[1]
    assert width / height == pytest.approx(size[0] / size[1], abs=.003)


def test_capture_keeps_720p_detail_and_latest_frame_envelope(monkeypatch):
    frame = av.VideoFrame.from_ndarray(np.zeros((720, 1280, 3), np.uint8), format='bgr24')
    frame.pts = 1
    class Container:
        streams = type('Streams', (), {'video': [object()]})()
        def decode(self, **kwargs):
            yield frame
    @contextmanager
    def opened(*args, **kwargs):
        yield Container()
    class Mailbox(Queue):
        def cancel_join_thread(self):
            pass
    monkeypatch.setattr(av, 'open', opened)
    mailbox = Mailbox(maxsize=1)
    capture_worker('rtsp://local/test', mailbox, Event(), 1, 1)
    item = mailbox.get_nowait()
    decoded = cv2.imdecode(np.frombuffer(item['jpeg'], np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (720, 1280)
    assert item['generation'] and item['monotonic_ns'] > 0
