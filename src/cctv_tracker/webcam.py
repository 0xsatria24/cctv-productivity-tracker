"""Local, ephemeral webcam inference. Frames never enter the replay database."""
from pathlib import Path
import hashlib
import threading
import time
import os
from .person_detection import DetectionTuning, detection_regions, preprocess_yolox, decode_people, split_people

MODEL_PATH = Path(os.environ.get('CCTV_MODEL_DIR', Path(__file__).resolve().parents[2] / 'models')) / "webcam-yolox.onnx"
# Filled from the pinned OpenCV Zoo LFS object, checked before loading.
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"


class WebcamDetector:
    def __init__(self, model_path=MODEL_PATH, *, tuning=None):
        self.path = model_path
        self.lock = threading.Lock()
        self.session = None
        self.sha = MODEL_SHA256
        self.tuning = tuning or DetectionTuning()
        self.manifest = {'license': 'Apache-2.0', 'source': 'OpenCV Zoo YOLOX 47534e27c9851bb1128ccc0102f1145e27f23f98', 'threshold': 0.45, 'nms_iou': 0.5, 'provider': 'CPUExecutionProvider'}
        self.runtime_label = 'YOLOX · CPU'
        self.manifest.update(threshold=self.tuning.confidence, nms_iou=self.tuning.nms_iou,
                             tracking_candidate_threshold=self.tuning.tracking_confidence, tracking_candidate_limit=128,
                             tracking_proposal_limit=1024,
                             detail=self.tuning.detail, tile_overlap=self.tuning.tile_overlap,
                             preprocessing='rgb-top-left-letterbox-640', postprocessing='person-separated-confidence-v3')

    def _load_backend(self):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.path), sess_options=options, providers=['CPUExecutionProvider'])
        self.session.disable_fallback()

    def _infer(self, blob):
        return self.session.run(None, {self.session.get_inputs()[0].name: blob})[0][0]

    def detect(self, jpeg: bytes):
        import cv2
        import numpy as np
        started = time.perf_counter()
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("Engine sibuk; frame berikutnya akan dicoba kembali")
        try:
            if self.session is None:
                if not self.path.is_file():
                    raise FileNotFoundError("Model belum tersedia. Jalankan python scripts/setup_webcam_model.py")
                if hashlib.sha256(self.path.read_bytes()).hexdigest() != MODEL_SHA256:
                    raise RuntimeError("Checksum model tidak sesuai. Jalankan ulang setup model webcam.")
                self._load_backend()
                grids, strides = [], []
                for stride in (8, 16, 32):
                    x, y = np.meshgrid(np.arange(640 // stride), np.arange(640 // stride))
                    grid = np.stack((x, y), axis=-1).reshape(-1, 2)
                    grids.append(grid)
                    strides.append(np.full((len(grid), 1), stride))
                self.grid = np.concatenate(grids)
                self.strides = np.concatenate(strides)
            # Header dimensions are validated by the endpoint before decoding.
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("JPEG tidak dapat dibaca")
            h, w = frame.shape[:2]
            boxes, scores = [], []
            full_frame_count = 0
            regions = detection_regions(w, h, self.tuning)
            for region in regions:
                x0, y0, x1, y1 = region
                blob, scale = preprocess_yolox(frame[y0:y1, x0:x1])
                decoded, confidence = decode_people(self._infer(blob), self.grid, self.strides, scale, region, (w, h), self.tuning, include_tracking=True)
                boxes.extend(decoded.tolist())
                scores.extend(confidence.tolist())
                if region == (0, 0, w, h):
                    full_frame_count = len(boxes)
            detections, candidates = split_people(boxes, scores, (w, h), self.tuning, full_frame_count=full_frame_count)
            return {"model": self.runtime_label, "source": "WEBCAM_LIVE", "detections": detections,
                    "tracking_candidates": candidates, "tracking_candidate_count": len(candidates),
                    "count": len(detections), "width": w, "height": h,
                    "inference_ms": round((time.perf_counter() - started) * 1000), "recorded": False,
                    "model_passes": len(regions), "detection_profile": 'detail' if self.tuning.detail else 'balanced'}
        finally:
            self.lock.release()


def jpeg_dimensions(data: bytes):
    """Read JPEG SOF before allocating decoded pixels; reject other image formats."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Frame harus berupa JPEG")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 255:
            break
        while pos < len(data) and data[pos] == 255:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xD9, 0xDA):
            break
        length = int.from_bytes(data[pos:pos + 2], "big")
        if length < 2 or pos + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2):
            if length < 8:
                break
            h = int.from_bytes(data[pos + 3:pos + 5], "big")
            w = int.from_bytes(data[pos + 5:pos + 7], "big")
            if 0 < w <= 1280 and 0 < h <= 1280 and w * h <= 1280 * 720:
                return w, h
            raise ValueError("Frame maksimal 1280 × 720 piksel; gunakan downscale browser")
        pos += length
    raise ValueError("Header JPEG tidak valid")
