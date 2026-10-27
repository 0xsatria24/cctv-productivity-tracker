"""Same frame-to-model JPEG transformation for live capture and offline evaluation."""
import math


def capture_dimensions(width, height):
    scale = min(1, 1280 / max(width, height), math.sqrt((1280 * 720) / (width * height)))
    return max(1, int(width * scale)), max(1, int(height * scale))


def encode_frame(frame):
    import cv2
    if frame.is_corrupt:
        raise ValueError('Corrupt decoded frame is not observation evidence')
    if not frame.width or not frame.height or frame.width * frame.height > 4096 * 2160:
        raise ValueError('Unsupported frame size')
    width, height = capture_dimensions(frame.width, frame.height)
    image = frame.reformat(width=width, height=height, format='bgr24').to_ndarray()
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError('JPEG encoding failed')
    return encoded.tobytes(), width, height
