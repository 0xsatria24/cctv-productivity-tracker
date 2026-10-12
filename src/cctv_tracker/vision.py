"""Native adapters are optional; no model download or biometric matching."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math

from .domain.geometry import overlap_ratio
from .domain.occupancy import State


@dataclass(frozen=True)
class Detection:
    box: tuple[float, float, float, float]
    confidence: float
    track_id: str | None = None

    def __post_init__(self):
        if len(self.box) != 4 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.box):
            raise ValueError("Detection coordinates must be finite and normalized")
        if self.box[2] <= self.box[0] or self.box[3] <= self.box[1]:
            raise ValueError("Detection rectangle has no area")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Detection confidence must be in [0,1]")


class Tracker:
    """ByteTrack frame aging is stepped by elapsed time, bounded by gap reset."""

    def __init__(self, fps, gap_seconds):
        import supervision as sv
        self.sv, self.fps, self.gap_seconds = sv, fps, gap_seconds
        self.tracker = sv.ByteTrack(frame_rate=fps, track_activation_threshold=0.25, lost_track_buffer=30)
        self.last_time = None
        self.generation = None
        self.last_tracks = []

    def update(self, detections, at_seconds, generation):
        import numpy as np
        if self.generation != generation or (self.last_time is not None and at_seconds - self.last_time > self.gap_seconds):
            self.tracker.reset()
            self.last_time = None
        if self.last_time is not None and at_seconds <= self.last_time:
            raise ValueError("Tracker timestamps must advance")
        empty = self.sv.Detections.empty()
        if self.last_time is not None:
            ticks = max(0, round((at_seconds - self.last_time) * self.fps) - 1)
            for _ in range(ticks):
                self.tracker.update_with_detections(empty)
        inputs = self.sv.Detections(xyxy=np.asarray([d.box for d in detections], dtype=np.float32).reshape(-1, 4),
                                    confidence=np.asarray([d.confidence for d in detections], dtype=np.float32),
                                    class_id=np.zeros(len(detections), dtype=int))
        tracked = self.tracker.update_with_detections(inputs)
        result = list(detections)
        self.last_tracks = []
        for box, confidence, identifier in zip(tracked.xyxy, tracked.confidence, tracked.tracker_id):
            match = next((i for i, d in enumerate(result) if tuple(box) == tuple(np.asarray(d.box, dtype=np.float32))), None)
            if match is not None:
                track_id = f"{generation}:{int(identifier)}"
                result[match] = Detection(result[match].box, float(confidence), track_id)
                self.last_tracks.append(track_id)
        # Only current measured boxes are returned; predictions never create presence.
        self.last_time, self.generation = at_seconds, generation
        return result


def associate(detections, zones, rules):
    occupants = {z.id: [] for z in zones}
    uncertain = set()
    for detection in detections:
        candidates = [(z, overlap_ratio(detection.box, z.polygon)) for z in zones]
        groups = {z.exclusive_group for z in zones}
        for group in groups:
            matches = sorted(((z, score) for z, score in candidates if z.exclusive_group == group and score >= rules.association_overlap), key=lambda x: x[1], reverse=True)
            if not matches:
                continue
            if len(matches) > 1 and matches[0][1] - matches[1][1] <= rules.ambiguity_margin:
                uncertain.update(z.id for z, score in matches if matches[0][1] - score <= rules.ambiguity_margin)
            elif detection.confidence < rules.strong_confidence:
                uncertain.add(matches[0][0].id)
            else:
                occupants[matches[0][0].id].append(detection)
    result = {}
    for zone in zones:
        count = len(occupants[zone.id])
        if count:
            result[zone.id] = (State.OCCUPIED, None if zone.id in uncertain else count, None)
        elif zone.id in uncertain:
            result[zone.id] = (State.UNKNOWN, None, "ZONE_AMBIGUOUS")
        else:
            result[zone.id] = (State.EMPTY, 0, None)
    return result


class OnnxDetector:
    def __init__(self, model: Path, manifest_path: Path, provider="CPUExecutionProvider"):
        import onnxruntime as ort
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        allowed = {"sha256", "license", "source", "input_size", "output_format", "person_class_ids", "confidence", "nms_iou"}
        if set(self.manifest) - allowed or not {"sha256", "license", "source", "input_size", "output_format", "person_class_ids"} <= set(self.manifest):
            raise ValueError("Incomplete or unsupported model manifest")
        with model.open("rb") as artifact:
            self.sha = hashlib.file_digest(artifact, "sha256").hexdigest()
        if self.sha != self.manifest["sha256"] or not self.manifest["license"].strip():
            raise ValueError("Model checksum or license metadata invalid")
        if provider not in {"CPUExecutionProvider", "CUDAExecutionProvider"} or provider not in ort.get_available_providers():
            raise ValueError("Requested inference provider unavailable; no silent fallback")
        if self.manifest["output_format"] not in {"xyxy_score_class", "yolo_raw"}:
            raise ValueError("Unsupported detector output parser")
        self.size = self.manifest["input_size"]
        if not isinstance(self.size, int) or not 32 <= self.size <= 2048:
            raise ValueError("Invalid model input size")
        self.person_ids = self.manifest["person_class_ids"]
        if not isinstance(self.person_ids, list) or not self.person_ids or any(not isinstance(i, int) or i < 0 for i in self.person_ids):
            raise ValueError("Invalid person class manifest")
        for key, default in (("confidence", 0.1), ("nms_iou", 0.5)):
            if not 0 < self.manifest.get(key, default) < 1:
                raise ValueError("Detector thresholds must be in (0,1)")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(model), sess_options=options, providers=[provider])
        self.session.disable_fallback()
        actual = self.session.get_providers()
        if not actual or actual[0] != provider:
            raise ValueError("Requested provider did not initialize")
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].type != "tensor(float)" or len(inputs[0].shape) != 4:
            raise ValueError("Only one float32 NCHW model input is supported")
        for expected, dimension in zip((1, 3, self.size, self.size), inputs[0].shape):
            if isinstance(dimension, int) and expected != dimension:
                raise ValueError("Manifest and model input dimensions differ")
        self.input_name = inputs[0].name
        self.provider = provider

    def detect(self, image):
        import cv2
        import numpy as np
        height, width = image.shape[:2]
        scale = min(self.size / width, self.size / height)
        resized_w, resized_h = round(width * scale), round(height * scale)
        left, top = (self.size - resized_w) // 2, (self.size - resized_h) // 2
        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        canvas[top:top + resized_h, left:left + resized_w] = cv2.resize(image, (resized_w, resized_h))
        tensor = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        output = self.session.run(None, {self.input_name: tensor})[0]
        if output.ndim != 3 or output.shape[0] != 1 or not np.isfinite(output).all():
            raise ValueError("Invalid detector output envelope")
        rows = output[0]
        if self.manifest["output_format"] == "yolo_raw":
            if rows.shape[0] < 5 or rows.shape[0] > 1024:
                raise ValueError("Expected [1,4+classes,anchors] model output")
            rows = rows.T
            if max(self.person_ids) >= rows.shape[1] - 4:
                raise ValueError("Person class IDs exceed the raw model class count")
            classes = rows[:, 4:].argmax(axis=1)
            scores = rows[:, 4:].max(axis=1)
            boxes = np.column_stack((rows[:, 0] - rows[:, 2] / 2, rows[:, 1] - rows[:, 3] / 2,
                                     rows[:, 0] + rows[:, 2] / 2, rows[:, 1] + rows[:, 3] / 2))
        else:
            if rows.shape[1] != 6:
                raise ValueError("Expected [1,N,6] detector output")
            boxes, scores, classes = rows[:, :4], rows[:, 4], rows[:, 5]
        if np.any(scores < 0) or np.any(scores > 1) or np.any(classes < 0) or np.any(classes != np.floor(classes)):
            raise ValueError("Detector returned invalid confidence or class IDs")
        selected = np.isin(classes, self.person_ids) & (scores >= self.manifest.get("confidence", 0.1))
        boxes, scores = boxes[selected], scores[selected]
        normalized = []
        for box in boxes:
            box = box.copy()
            box[[0, 2]] = (box[[0, 2]] - left) / (resized_w / width) / width
            box[[1, 3]] = (box[[1, 3]] - top) / (resized_h / height) / height
            normalized.append(np.clip(box, 0, 1))
        normalized = np.asarray(normalized).reshape(-1, 4)
        picked = []
        # Class-filtered NMS in native OpenCV, keeping low scores for tracking.
        xywh = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in normalized]
        for index in np.asarray(cv2.dnn.NMSBoxes(xywh, scores.tolist(), self.manifest.get("confidence", 0.1), self.manifest.get("nms_iou", 0.5))).flatten():
            box = normalized[int(index)]
            if box[2] > box[0] and box[3] > box[1]:
                picked.append(Detection(tuple(float(v) for v in box), float(scores[int(index)])))
        return picked
