"""Native adapters are optional; no model download or biometric matching."""
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
import hashlib
import json
import math

from .domain.geometry import overlap_ratio
from .domain.occupancy import State
from .tracking import TrackingRules


@dataclass(frozen=True)
class Detection:
    box: tuple[float, float, float, float]
    confidence: float
    track_id: str | None = None
    tracking_only: bool = False

    def __post_init__(self):
        if len(self.box) != 4 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.box):
            raise ValueError("Detection coordinates must be finite and normalized")
        if self.box[2] <= self.box[0] or self.box[3] <= self.box[1]:
            raise ValueError("Detection rectangle has no area")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Detection confidence must be in [0,1]")
        if type(self.tracking_only) is not bool:
            raise ValueError('tracking_only must be boolean')


def frame_detections(packet):
    public=[Detection(tuple(row['box']),row['confidence']) for row in packet['detections']]
    measured = {(row.box, row.confidence) for row in public}
    candidates=[Detection(tuple(row['box']),row['confidence'],tracking_only=True)
                for row in packet.get('tracking_candidates',[])[:128]
                if (tuple(row['box']), row['confidence']) not in measured]
    return public+candidates


class Tracker:
    """ByteTrack frame aging is stepped by elapsed time, bounded by gap reset."""

    def __init__(self, fps, gap_seconds, recovery_seconds=1, *, rules=None):
        import supervision as sv
        from supervision.tracker.byte_tracker.single_object_track import STrack
        if type(fps) is not int or not 1 <= fps <= 30 or not math.isfinite(gap_seconds) or gap_seconds <= 0:
            raise ValueError('Invalid tracker cadence or gap')
        self.sv, self.fps, self.gap_seconds = sv, fps, gap_seconds
        self.rules = rules or TrackingRules(lost_buffer_seconds=gap_seconds)
        self._strack = STrack
        self.tracker = sv.ByteTrack(frame_rate=fps, track_activation_threshold=self.rules.activation_threshold,
                                    minimum_matching_threshold=self.rules.matching_threshold,
                                    minimum_consecutive_frames=self.rules.confirmation_frames)
        self.tracker.max_time_lost = max(1, math.ceil(fps * self.rules.lost_buffer_seconds))
        self.last_time = None
        self.generation = None
        self.last_tracks = []
        self.epoch = 0
        self._tick_remainder = 0.0
        self.metrics = {}
        self.recovery_seconds = min(recovery_seconds, gap_seconds)
        self.last_measured = {}
        self.retained_ids = set()

    def _recover_recent_weak_matches(self, detections, at):
        if not self.recovery_seconds:
            return
        from supervision.tracker.byte_tracker.core import TrackState

        def iou(a, b):
            overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
            return overlap / max(1e-12, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - overlap)

        tracks = [track for track in self.tracker.tracked_tracks + self.tracker.lost_tracks if track.external_track_id > 0]
        for track in self.tracker.lost_tracks:
            if track.state != TrackState.Lost or at - self.last_measured.get(track.external_track_id, float('-inf')) > self.recovery_seconds:
                continue
            matches = [row for row in detections if .1 < row.confidence < self.tracker.track_activation_threshold and iou(track.tlbr, row.box) >= .6]
            if len(matches) == 1 and sum(iou(other.tlbr, matches[0].box) >= .3 for other in tracks) == 1:
                track.state = TrackState.Tracked

    def update(self, detections, at_seconds, generation):
        import numpy as np
        if not math.isfinite(at_seconds) or at_seconds < 0 or not generation:
            raise ValueError('Invalid tracker timestamp or generation')
        if self.last_time is not None and self.generation == generation and at_seconds <= self.last_time:
            raise ValueError("Tracker timestamps must advance")
        reset_reason = None
        if self.generation != generation or (self.last_time is not None and at_seconds - self.last_time > self.gap_seconds):
            reset_reason = 'GENERATION_CHANGED' if self.generation != generation else 'EVIDENCE_GAP'
        extra_steps = 0
        if not reset_reason and self.last_time is not None:
            elapsed_ticks = (at_seconds - self.last_time) * self.fps + self._tick_remainder
            elapsed_steps = math.floor(elapsed_ticks + 1e-8)
            extra_steps = max(0, elapsed_steps - 1)
            self._tick_remainder = max(0.0, elapsed_ticks - elapsed_steps)
            if extra_steps + 1 > self.rules.max_prediction_steps:
                reset_reason = 'PREDICTION_BUDGET'
        if reset_reason:
            self.tracker.reset()
            self.epoch += 1
            self.last_time = None
            self.last_measured.clear()
            self._tick_remainder = 0.0
            extra_steps = 0
        expired_lost = 0
        if self.last_time is not None:
            # Advance motion and age together, without fabricated empty observations.
            next_frame = self.tracker.frame_id + extra_steps + 1
            retained = [track for track in self.tracker.lost_tracks
                        if next_frame - track.frame_id <= self.tracker.max_time_lost]
            expired_lost = len(self.tracker.lost_tracks) - len(retained)
            self.tracker.lost_tracks = retained
            pool = [track for track in self.tracker.tracked_tracks if track.is_activated] + self.tracker.lost_tracks
            for _ in range(extra_steps):
                self._strack.multi_predict(pool, self.tracker.shared_kalman)
            self.tracker.frame_id += extra_steps
        for name in ('tracked_tracks', 'lost_tracks'):
            setattr(self.tracker, name, [track for track in getattr(self.tracker, name)
                    if at_seconds - self.last_measured.get(track.external_track_id, at_seconds) <= self.gap_seconds])
        self._recover_recent_weak_matches(detections, at_seconds)
        inputs = self.sv.Detections(xyxy=np.asarray([d.box for d in detections], dtype=np.float32).reshape(-1, 4),
                                    confidence=np.asarray([d.confidence for d in detections], dtype=np.float32),
                                    class_id=np.zeros(len(detections), dtype=int),
                                    data={'source_index': np.arange(len(detections), dtype=int)})
        tracked = self.tracker.update_with_detections(inputs)
        result = [Detection(d.box, d.confidence, tracking_only=d.tracking_only) for d in detections]
        self.last_tracks = []
        source_indices = tracked.data.get('source_index', np.array([], dtype=int))
        identifiers = tracked.tracker_id if tracked.tracker_id is not None else np.array([], dtype=int)
        rejected = 0
        if len(source_indices) == len(identifiers):
            source_counts = Counter(int(i) for i in source_indices)
            id_counts = Counter(int(i) for i in identifiers)
            for index, identifier in zip(source_indices, identifiers):
                match = int(index)
                if not 0 <= match < len(result) or source_counts[match] != 1 or id_counts[int(identifier)] != 1 or identifier <= 0:
                    rejected += 1
                    continue
                track_id = f"{generation}:{self.epoch}:{int(identifier)}"
                result[match] = Detection(result[match].box, result[match].confidence, track_id, result[match].tracking_only)
                self.last_tracks.append(track_id)
                self.last_measured[int(identifier)] = at_seconds
        else:
            rejected = len(identifiers)
        # Only current measured boxes are returned; predictions never create presence.
        self.last_time, self.generation = at_seconds, generation
        from supervision.tracker.byte_tracker.core import TrackState
        retained = {track.external_track_id for track in self.tracker.tracked_tracks + self.tracker.lost_tracks
                    if track.state in (TrackState.Tracked, TrackState.Lost) and track.external_track_id > 0}
        self.retained_ids = {f'{generation}:{self.epoch}:{int(identifier)}' for identifier in retained}
        self.last_measured = {key: value for key, value in self.last_measured.items() if key in retained}
        self.metrics = {'algorithm': 'ByteTrack', 'available': True, 'measured_count': len(result),
                        'matched_count': len(self.last_tracks), 'unmatched_count': len(result) - len(self.last_tracks),
                        'active_tracks': len(self.tracker.tracked_tracks), 'lost_tracks': len(self.tracker.lost_tracks),
                        'confirmed_tracks': sum(track.is_activated for track in self.tracker.tracked_tracks),
                        'tentative_tracks': sum(not track.is_activated for track in self.tracker.tracked_tracks),
                        'extra_prediction_steps': extra_steps, 'mapping_rejected': rejected,
                        'expired_lost_tracks': expired_lost,
                        'epoch': self.epoch, 'reset_reason': reset_reason}
        self.metrics.update(tracking_candidates=sum(d.tracking_only for d in result),
                            matched_tracking_candidates=sum(d.tracking_only and d.track_id is not None for d in result),
                            public_measured_count=sum(not d.tracking_only for d in result))
        return result


def associate(detections, zones, rules, position=None):
    if position is not None and position.mode != 'bbox_overlap':
        return associate_positions(detections, zones, rules, position)
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
            elif detection.tracking_only or detection.confidence < rules.strong_confidence:
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


def associate_positions(detections, zones, rules, calibration):
    from .positioning import contains, edge_distance, floor_polygon, measured_position
    occupants = {z.id: [] for z in zones}
    uncertain = set()
    polygons = {z.id: floor_polygon(z.polygon, calibration) if calibration.mode == 'homography' else z.polygon for z in zones}
    margin = calibration.floor_boundary_margin_m if calibration.mode == 'homography' else calibration.image_boundary_margin
    for detection in detections:
        position = measured_position(detection, calibration)
        if not position['available']:
            uncertain.update(z.id for z in zones if overlap_ratio(detection.box, z.polygon) > 0)
            continue
        point = position['floor_m'] if calibration.mode == 'homography' else position['anchor']
        for group in {z.exclusive_group for z in zones}:
            candidates = [(z, edge_distance(point, polygons[z.id])) for z in zones
                          if z.exclusive_group == group and (contains(point, polygons[z.id]) or edge_distance(point, polygons[z.id]) <= margin)]
            if len(candidates) == 1 and candidates[0][1] > margin and detection.confidence >= rules.strong_confidence and not detection.tracking_only:
                occupants[candidates[0][0].id].append(detection)
            else:
                uncertain.update(z.id for z, _ in candidates)
    return {z.id: (State.OCCUPIED, None if z.id in uncertain else len(occupants[z.id]), None) if occupants[z.id]
            else (State.UNKNOWN, None, 'ZONE_AMBIGUOUS') if z.id in uncertain
            else (State.EMPTY, 0, None) for z in zones}


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
