from pathlib import Path
import importlib.util
import cv2
import numpy as np
import pytest
from cctv_tracker.webcam import WebcamDetector, MODEL_PATH, MODEL_SHA256
from cctv_tracker.openvino_yolox import OpenVinoYoloX
from cctv_tracker.person_detection import DetectionTuning

INSTALLED = importlib.util.find_spec('openvino') is not None and MODEL_PATH.exists()


def test_device_validation_and_bad_checksum_do_not_load_model(tmp_path):
    for device in ('AUTO', 'NPU', 'HETERO:GPU,CPU'):
        with pytest.raises(ValueError):
            OpenVinoYoloX(device=device)
    with pytest.raises(ValueError):
        OpenVinoYoloX(threads=0)
    path = tmp_path / 'invalid.onnx'; path.write_bytes(b'bad weights')
    detector = OpenVinoYoloX(path)
    with pytest.raises(RuntimeError, match='Checksum'):
        detector.detect(b'jpeg')
    assert detector.session is None


@pytest.mark.skipif(not INSTALLED, reason='Optional OpenVINO runtime/model')
def test_cpu_fp32_uses_same_weights_and_measured_detection_contract(tmp_path):
    detector = OpenVinoYoloX(cache_dir=tmp_path / 'cache')
    for width, height in ((640, 360), (240, 480)):
        jpeg = cv2.imencode('.jpg', np.zeros((height, width, 3), np.uint8))[1].tobytes()
        result = detector.detect(jpeg)
        assert result['count'] == 0 and result['detections'] == []
        assert (result['width'], result['height']) == (width, height)
        assert result['model'] == 'YOLOX-S · OpenVINO CPU'
    assert detector.sha == MODEL_SHA256
    assert detector.manifest['execution_devices'] == ['CPU']
    assert detector.manifest['precision'] == 'f32'
    with detector.lock, pytest.raises(BlockingIOError):
        detector.detect(jpeg)


@pytest.mark.skipif(not INSTALLED or not (MODEL_PATH.parent / 'person-test.png').exists(), reason='Optional public person sample')
def test_cpu_same_person_boxes_and_confidence_as_onnx(tmp_path):
    image = cv2.imread(str(MODEL_PATH.parent / 'person-test.png'))
    jpeg = cv2.imencode('.jpg', image)[1].tobytes()
    reference = WebcamDetector().detect(jpeg)
    actual = OpenVinoYoloX(cache_dir=tmp_path / 'cache').detect(jpeg)
    assert reference['count'] == actual['count'] == 2
    # Same shared preprocessor and decoder, tolerance only for floating-point kernels.
    reference_boxes = sorted(reference['detections'], key=lambda d: d['box'][0])
    actual_boxes = sorted(actual['detections'], key=lambda d: d['box'][0])
    for ref, got in zip(reference_boxes, actual_boxes):
        assert got['box'] == pytest.approx(ref['box'], abs=1e-5)
        assert got['confidence'] == pytest.approx(ref['confidence'], abs=0.001)


@pytest.mark.skipif(importlib.util.find_spec('openvino') is None, reason='Optional OpenVINO runtime')
def test_missing_requested_device_never_falls_back(monkeypatch):
    import openvino as ov
    class MissingGpu:
        available_devices = ['CPU']
    monkeypatch.setattr(ov, 'Core', MissingGpu)
    detector = OpenVinoYoloX(device='GPU')
    with pytest.raises(RuntimeError, match='GPU tidak tersedia'):
        detector._load_backend()
    assert detector.session is None


@pytest.mark.skipif(not INSTALLED or not (MODEL_PATH.parent / 'person-test.png').exists(), reason='Optional public person sample')
def test_detail_keeps_two_people_without_duplicate_body_parts(tmp_path):
    image = cv2.imread(str(MODEL_PATH.parent / 'person-test.png'))
    jpeg = cv2.imencode('.jpg', image)[1].tobytes()
    detector = OpenVinoYoloX(cache_dir=tmp_path / 'cache', tuning=DetectionTuning(detail=True))
    result = detector.detect(jpeg)
    assert result['count'] == 2
    assert result['model_passes'] == 5 and result['detection_profile'] == 'detail'
    blank = detector.detect(cv2.imencode('.jpg', np.zeros((480, 640, 3), np.uint8))[1].tobytes())
    assert blank['count'] == 0
