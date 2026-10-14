"""Lightweight CPU detector adapted from the Apache-2.0 OpenCV Zoo decoder."""
from pathlib import Path
import hashlib
import time
from .webcam import WebcamDetector, MODEL_PATH

NANO_PATH = MODEL_PATH.with_name('webcam-nanodet.onnx')
NANO_SHA256 = '4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186'


class NanoDetDetector(WebcamDetector):
    def __init__(self, model_path=NANO_PATH):
        super().__init__(model_path)
        self.sha = NANO_SHA256
        self.runtime_label = 'NanoDet · CPU'
        self.manifest = {'license': 'Apache-2.0', 'source': 'OpenCV Zoo NanoDet 47534e27c9851bb1128ccc0102f1145e27f23f98', 'threshold': 0.45, 'nms_iou': 0.5, 'provider': 'CPUExecutionProvider'}

    def detect(self, jpeg):
        import cv2
        import numpy as np
        import onnxruntime as ort
        started = time.perf_counter()
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('Engine sibuk; frame berikutnya akan dicoba kembali')
        try:
            if self.session is None:
                if not self.path.is_file():
                    raise FileNotFoundError('Model NanoDet belum tersedia; jalankan python scripts/setup_webcam_model.py --model nanodet')
                if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.sha:
                    raise RuntimeError('Checksum NanoDet tidak sesuai; jalankan ulang setup model')
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                options.log_severity_level = 3
                self.session = ort.InferenceSession(str(self.path), sess_options=options, providers=['CPUExecutionProvider'])
                self.session.disable_fallback()
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError('JPEG tidak dapat dibaca')
            h, w = frame.shape[:2]
            scale = min(416 / w, 416 / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            left, top = (416 - nw) // 2, (416 - nh) // 2
            resized = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (nw, nh), interpolation=cv2.INTER_AREA)
            padded = np.zeros((416, 416, 3), dtype=np.float32)
            padded[top:top + nh, left:left + nw] = resized
            padded = (padded - np.array([103.53, 116.28, 123.675], np.float32)) / np.array([57.375, 57.12, 58.395], np.float32)
            outputs = self.session.run(None, {self.session.get_inputs()[0].name: padded.transpose(2, 0, 1)[None]})
            classes = {o.shape[1]: o[0] for o in outputs if o.shape[-1] == 80}
            regressions = {o.shape[1]: o[0] for o in outputs if o.shape[-1] == 32}
            boxes, scores = [], []
            for stride in (8, 16, 32):
                side = 416 // stride
                cls, reg = classes[side * side], regressions[side * side]
                valid = (cls[:, 0] >= 0.45) & (cls.argmax(axis=1) == 0)
                if not valid.any():
                    continue
                x, y = np.meshgrid(np.arange(side), np.arange(side))
                anchors = np.stack((x, y), axis=-1).reshape(-1, 2)[valid] * stride + (stride - 1) / 2
                logits = reg[valid].reshape(-1, 4, 8)
                probability = np.exp(logits - logits.max(axis=2, keepdims=True))
                probability /= probability.sum(axis=2, keepdims=True)
                distances = (probability * np.arange(8)).sum(axis=2) * stride
                xy1, xy2 = anchors - distances[:, :2], anchors + distances[:, 2:]
                xy1 = np.clip(xy1, 0, 416); xy2 = np.clip(xy2, 0, 416)
                xy1 = (xy1 - [left, top]) * [w / nw, h / nh]
                xy2 = (xy2 - [left, top]) * [w / nw, h / nh]
                boxes.extend(np.concatenate((xy1, xy2 - xy1), axis=1).tolist())
                scores.extend(cls[valid, 0].tolist())
            keep = cv2.dnn.NMSBoxes(boxes, scores, 0.45, 0.5)
            detections = []
            for i in np.asarray(keep).reshape(-1):
                x, y, bw, bh = boxes[i]
                box = np.clip([x / w, y / h, (x + bw) / w, (y + bh) / h], 0, 1).tolist()
                if box[2] > box[0] and box[3] > box[1]:
                    detections.append({'box': box, 'confidence': round(float(scores[i]), 3)})
            return {'model': 'NanoDet · CPU', 'source': 'WEBCAM_LIVE', 'detections': detections, 'count': len(detections), 'width': w, 'height': h, 'inference_ms': round((time.perf_counter() - started) * 1000), 'recorded': False}
        finally:
            self.lock.release()
