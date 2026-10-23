"""Image-quality and postprocessing policy shared by YOLOX runtimes."""
from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class DetectionTuning:
    confidence: float = 0.45
    nms_iou: float = 0.5
    detail: bool = False
    tile_overlap: float = 0.5
    tracking_confidence: float = 0.1

    def __post_init__(self):
        for key in ('confidence', 'nms_iou', 'tracking_confidence'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f'{key} must be finite and between 0 and 1')
        if not .1 <= self.tracking_confidence <= self.confidence:
            raise ValueError('tracking_confidence must be in [0.1, confidence] for ByteTrack')
        if type(self.detail) is not bool:
            raise ValueError('detail must be boolean')
        if isinstance(self.tile_overlap, bool) or not isinstance(self.tile_overlap, (int, float)) or not math.isfinite(self.tile_overlap) or not 0.1 <= self.tile_overlap <= 0.5:
            raise ValueError('tile_overlap must be between 0.1 and 0.5')


def detection_regions(width, height, tuning):
    """Always retain the full frame so large people need not fit inside a tile."""
    regions = [(0, 0, width, height)]
    if tuning.detail and min(width, height) >= 128:
        tw = math.ceil(width / (2 - tuning.tile_overlap))
        th = math.ceil(height / (2 - tuning.tile_overlap))
        for y in (0, height - th):
            for x in (0, width - tw):
                region = (x, y, x + tw, y + th)
                if region not in regions:
                    regions.append(region)
    return regions


def preprocess_yolox(frame):
    import cv2
    import numpy as np
    height, width = frame.shape[:2]
    scale = min(640 / width, 640 / height)
    resized = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))))
    padded = np.full((640, 640, 3), 114, dtype=np.uint8)
    padded[:resized.shape[0], :resized.shape[1]] = resized
    return cv2.cvtColor(padded, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32), scale


def decode_people(predictions, grid, strides, scale, region, frame_size, tuning, *, include_tracking=False):
    import numpy as np
    predictions = np.asarray(predictions)
    if predictions.shape != (len(grid), 85):
        raise ValueError('Kontrak output YOLOX tidak sesuai')
    with np.errstate(over='ignore', invalid='ignore'):
        scores = predictions[:, 4] * predictions[:, 5]
    threshold = tuning.tracking_confidence if include_tracking else tuning.confidence
    valid = np.isfinite(predictions).all(axis=1) & np.isfinite(scores) & (scores >= threshold) & (predictions[:, 5:].argmax(axis=1) == 0)
    p, scores = predictions[valid], scores[valid]
    centers = (p[:, :2] + grid[valid]) * strides[valid]
    sizes = np.exp(np.clip(p[:, 2:4], -20, 20)) * strides[valid]
    boxes = np.concatenate((centers - sizes / 2, centers + sizes / 2), axis=1) / scale
    x0, y0, x1, y1 = region
    width, height = frame_size
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, x1 - x0)
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, y1 - y0)
    valid = np.isfinite(boxes).all(axis=1) & (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    if region != (0, 0, width, height):
        # Cut bodies at internal tile edges must not replace a complete full-frame box.
        guard = max(4, 0.03 * min(x1 - x0, y1 - y0))
        if x0 > 0:
            valid &= boxes[:, 0] > guard
        if y0 > 0:
            valid &= boxes[:, 1] > guard
        if x1 < width:
            valid &= boxes[:, 2] < x1 - x0 - guard
        if y1 < height:
            valid &= boxes[:, 3] < y1 - y0 - guard
    boxes = boxes[valid] + np.array([x0, y0, x0, y0])
    return boxes, scores[valid]


def suppress_people(boxes, scores, frame_size, tuning, *, full_frame_count=None, round_scores=True):
    import cv2
    import numpy as np
    if not len(boxes):
        return []
    boxes, scores = np.asarray(boxes), np.asarray(scores)
    if full_frame_count:
        base = boxes[:full_frame_count].copy()
        base[:, 2:] -= base[:, :2]
        selected = cv2.dnn.NMSBoxes(base.tolist(), scores[:full_frame_count].tolist(), tuning.confidence, tuning.nms_iou)
        selected = np.asarray(selected).reshape(-1)
        keep = selected.tolist()
        anchors = boxes[selected]
        areas = np.prod(anchors[:, 2:] - anchors[:, :2], axis=1)
        for i in range(full_frame_count, len(boxes)):
            intersection = np.prod(np.maximum(0, np.minimum(anchors[:, 2:], boxes[i, 2:]) - np.maximum(anchors[:, :2], boxes[i, :2])), axis=1)
            area = np.prod(boxes[i, 2:] - boxes[i, :2])
            # A cropped body part can have low IoU despite belonging to the same person.
            if not np.any(intersection / np.minimum(areas, area) >= 0.6):
                keep.append(i)
        boxes, scores = boxes[keep], scores[keep]
    xywh = boxes.copy()
    xywh[:, 2:] -= xywh[:, :2]
    keep = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), tuning.confidence, tuning.nms_iou)
    width, height = frame_size
    return [{'box': (boxes[i] / [width, height, width, height]).tolist(),
             'confidence': round(float(scores[i]), 3) if round_scores else float(scores[i])}
            for i in np.asarray(keep).reshape(-1)]


def split_people(boxes, scores, frame_size, tuning, *, full_frame_count=0):
    """Keep the public detector path unchanged; low candidates have a separate budget."""
    import numpy as np
    from .domain.geometry import overlap_ratio
    boxes=np.asarray(boxes,dtype=float).reshape(-1,4)
    scores=np.asarray(scores,dtype=np.float32)
    public_mask=scores>=tuning.confidence
    public=suppress_people(boxes[public_mask],scores[public_mask],frame_size,tuning,
                           full_frame_count=int(public_mask[:full_frame_count].sum()) if tuning.detail else None)
    low=(scores>=tuning.tracking_confidence)&~public_mask
    indices=np.flatnonzero(low)
    if len(indices)>1024:
        indices=np.sort(indices[np.argsort(-scores[indices],kind='stable')[:1024]])
    candidates=suppress_people(boxes[indices],scores[indices],frame_size,
                               replace(tuning,confidence=tuning.tracking_confidence),
                               full_frame_count=int((indices<full_frame_count).sum()) if tuning.detail else None,
                               round_scores=False)
    def separate(row):
        box=row['box']
        for accepted in public:
            other=accepted['box']
            polygon=((other[0],other[1]),(other[2],other[1]),(other[2],other[3]),(other[0],other[3]))
            reverse=((box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3]))
            if max(overlap_ratio(box,polygon),overlap_ratio(other,reverse))>=.6:
                return False
        return True
    candidates=[row for row in sorted(candidates,key=lambda row:row['confidence'],reverse=True) if separate(row)]
    return public,candidates[:128]
