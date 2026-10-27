"""Local, ephemeral webcam inference. Frames never enter the replay database."""
from pathlib import Path
import hashlib
import threading
import time
import os

MODEL_PATH = Path(os.environ.get('CCTV_MODEL_DIR', Path(__file__).resolve().parents[2] / 'models')) / "webcam-yolox.onnx"
# Filled from the pinned OpenCV Zoo LFS object, checked before loading.
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"


class WebcamDetector:
    def __init__(self, model_path=MODEL_PATH):
        self.path = model_path
        self.lock = threading.Lock()
        self.session = None
        self.sha = MODEL_SHA256
        self.manifest = {'license': 'Apache-2.0', 'source': 'OpenCV Zoo YOLOX 47534e27c9851bb1128ccc0102f1145e27f23f98', 'threshold': 0.45, 'tracking_candidate_threshold': 0.1, 'nms_iou': 0.5, 'provider': 'CPUExecutionProvider'}
        self.runtime_label = 'YOLOX · CPU'

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
            scale = min(640 / w, 640 / h)
            resized = cv2.resize(frame, (int(w * scale), int(h * scale)))
            padded = np.full((640, 640, 3), 114, dtype=np.uint8)
            padded[:resized.shape[0], :resized.shape[1]] = resized
            blob = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32)
            prepared = time.perf_counter()
            predictions = self._infer(blob)
            inferred = time.perf_counter()
            scores = predictions[:, 4] * predictions[:, 5]  # COCO person class 0
            valid = (scores >= self.manifest['tracking_candidate_threshold']) & (predictions[:, 5:].argmax(axis=1) == 0)
            p = predictions[valid]
            scores = scores[valid]
            centers = (p[:, :2] + self.grid[valid]) * self.strides[valid]
            sizes = np.exp(np.clip(p[:, 2:4], -20, 20)) * self.strides[valid]
            boxes = np.concatenate((centers - sizes / 2, sizes), axis=1) / scale
            keep = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.manifest['tracking_candidate_threshold'], 0.5)
            candidates = []
            for i in np.asarray(keep).reshape(-1):
                x, y, bw, bh = boxes[i]
                box = np.clip([x / w, y / h, (x + bw) / w, (y + bh) / h], 0, 1).tolist()
                if box[2] > box[0] and box[3] > box[1]:
                    candidates.append({"box": box, "confidence": round(float(scores[i]), 3)})
            detections = [row for row in candidates if row['confidence'] >= self.manifest['threshold']]
            return {"model": self.runtime_label, "source": "WEBCAM_LIVE", "detections": detections,
                    "tracking_candidates": candidates,
                    "count": len(detections), "width": w, "height": h,
                    "preprocess_ms": round((prepared-started)*1000,2), "runtime_ms": round((inferred-prepared)*1000,2),
                    "postprocess_ms": round((time.perf_counter()-inferred)*1000,2),
                    "inference_ms": round((time.perf_counter() - started) * 1000), "recorded": False}
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
