from contextlib import closing
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import numpy as np
import pytest
import onnx
from onnx import TensorProto, helper

from cctv_tracker.config import load_settings, timestamp
from cctv_tracker.persistence import Database
from cctv_tracker.pipeline import replay
from cctv_tracker.video_replay import replay_video
from cctv_tracker.vision import OnnxDetector
from cctv_tracker.logging_setup import configure_logging, redact

ROOT = Path(__file__).resolve().parents[1]


def model_fixture(folder, rows=None):
    """Constant ONNX output tests adapter plumbing, not detector accuracy."""
    rows = rows or [[[8, 8, 24, 24, 0.95, 0]]]
    array = np.asarray(rows, dtype=np.float32)
    graph = helper.make_graph([helper.make_node("Constant", [], ["detections"], value=helper.make_tensor("boxes", TensorProto.FLOAT, array.shape, array.flatten()))],
                              "synthetic_fixture", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 32, 32])],
                              [helper.make_tensor_value_info("detections", TensorProto.FLOAT, list(array.shape))])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    model_path = folder / "synthetic.onnx"
    onnx.save(model, model_path)
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps({"sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(), "license": "local synthetic fixture", "source": "generated plumbing test", "input_size": 32,
                                         "output_format": "xyxy_score_class", "person_class_ids": [0]}))
    return model_path, manifest_path


def test_actual_onnx_session_inverse_letterbox_and_class_filter(tmp_path):
    model, manifest = model_fixture(tmp_path, [[[8, 8, 24, 24, 0.95, 0], [0, 0, 8, 8, 0.99, 2]]])
    detector = OnnxDetector(model, manifest)
    rows = detector.detect(np.zeros((16, 32, 3), dtype=np.uint8))
    assert len(rows) == 1
    assert rows[0].box == pytest.approx((0.25, 0, 0.75, 1))
    assert detector.provider == "CPUExecutionProvider"


def test_model_hash_and_unsupported_parser_fail_before_detection(tmp_path):
    model, manifest = model_fixture(tmp_path)
    raw = json.loads(manifest.read_text())
    raw["sha256"] = "0" * 64
    manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="checksum"):
        OnnxDetector(model, manifest)
    raw["sha256"] = hashlib.sha256(model.read_bytes()).hexdigest()
    raw["output_format"] = "guess"
    manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="parser"):
        OnnxDetector(model, manifest)


def test_actual_pyav_decode_onnx_tracking_zone_and_sqlite_pipeline(tmp_path):
    import av
    model, manifest = model_fixture(tmp_path, [[[4, 8, 12, 24, 0.95, 0]]])
    video = tmp_path / "synthetic.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("mpeg4", rate=5)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(20):
            frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), dtype=np.uint8), format="bgr24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    config = replace(load_settings(ROOT / "config/pilot.example.json"), database=tmp_path / "video.sqlite3")
    with closing(Database(config.database)) as db:
        result = replay_video(video, manifest, model, config, db, timestamp("2026-10-12T09:00:00+07:00"), source="SYNTHETIC_VIDEO_TEST")
        assert result["data_sources"] == ["SYNTHETIC_VIDEO_TEST"]
        row = result["workstations"][0]
        assert row["occupied_us"] == 1_800_000
        assert row["unknown_us"] == 2_000_000
        assert row["observed_employee_id"] is None


def test_read_only_pilot_api_requires_token_and_validates_range(tmp_path):
    from fastapi.testclient import TestClient
    from cctv_tracker.api import create_app
    path = tmp_path / "api.sqlite3"
    config = replace(load_settings(ROOT / "config/pilot.example.json"), database=path)
    with closing(Database(path)) as db:
        result = replay(ROOT / "tests/fixtures/occupancy-replay.json", config, db)
    client = TestClient(create_app(path, "a" * 32))
    assert client.get("/pilot/v1/status").status_code == 401
    headers = {"Authorization": "Bearer " + "a" * 32}
    assert client.get("/pilot/v1/status", headers=headers).json()["face_recognition_enabled"] is False
    assert client.get("/pilot/v1/reports", params={"start_utc_us": 2, "end_utc_us": 1}, headers=headers).status_code == 422
    assert client.get("/pilot/v1/reports", params={"start_utc_us": result["start_utc_us"], "end_utc_us": result["end_utc_us"]}, headers=headers).json()["workstations"][0]["observed_employee_id"] is None


def test_logging_redacts_credentials_in_message_and_exception(tmp_path):
    logger = configure_logging(tmp_path)
    try:
        raise RuntimeError("rtsp://operator:secret@camera.local/live?token=value password=private")
    except RuntimeError:
        logger.exception("Connection failed")
    for handler in logger.handlers:
        handler.flush()
    output = (tmp_path / "engine.log").read_text()
    assert "operator:secret" not in output
    assert "private" not in output
    assert "camera.local" not in output
    assert "[REDACTED" in output
