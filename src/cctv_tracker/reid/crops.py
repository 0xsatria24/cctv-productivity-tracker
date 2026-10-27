import math
from .types import AppearanceSample, SampleRef


def overlap_fraction(box, other):
    intersection = max(0, min(box[2], other[2])-max(box[0], other[0])) * max(0, min(box[3], other[3])-max(box[1], other[1]))
    return intersection / min((box[2]-box[0])*(box[3]-box[1]), (other[2]-other[0])*(other[3]-other[1]))


def make_crops(jpeg, detections, token, rules):
    import cv2
    import numpy as np
    from ..webcam import jpeg_dimensions
    jpeg_dimensions(jpeg)
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Invalid ReID frame')
    height, width = image.shape[:2]
    samples, rejected = [], []
    # Rotate priority so dense frames do not permanently exclude later detections.
    offset = (token.frame_seq * rules.max_crops_per_frame) % max(1, len(detections))
    indices = list(range(len(detections)))
    indices = indices[offset:] + indices[:offset]
    for index in indices:
        detection = detections[index]
        x1, y1, x2, y2 = detection.box
        left, top = math.floor(x1*width), math.floor(y1*height)
        right, bottom = math.ceil(x2*width), math.ceil(y2*height)
        reason = None
        if detection.tracking_only or detection.confidence < rules.min_confidence:
            reason = 'LOW_CONFIDENCE'
        elif right-left < rules.min_width or bottom-top < rules.min_height:
            reason = 'CROP_TOO_SMALL'
        elif left <= 1 or top <= 1 or right >= width-1 or bottom >= height-1:
            reason = 'FRAME_EDGE'
        elif not 0.2 <= (right-left)/(bottom-top) <= 0.85:
            reason = 'PARTIAL_BODY_SHAPE'
        elif any(overlap_fraction(detection.box, other.box) > rules.max_overlap for j, other in enumerate(detections) if j != index and not other.tracking_only):
            reason = 'CROWD_OVERLAP'
        if reason:
            rejected.append({'detection_index': index, 'reason': reason})
            continue
        if len(samples) >= rules.max_crops_per_frame:
            rejected.append({'detection_index': index, 'reason': 'CROP_BUDGET'})
            continue
        crop = image[top:bottom, left:right]
        blur = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        if blur < rules.min_blur_score:
            rejected.append({'detection_index': index, 'reason': 'CROP_BLURRY'})
            continue
        samples.append(AppearanceSample(SampleRef(token, index, tuple(detection.box), blur, detection.confidence), crop.copy()))
    return samples, rejected
