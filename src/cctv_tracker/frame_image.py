"""Same frame-to-model JPEG transformation for live capture and offline evaluation."""


def encode_frame(frame):
    import cv2
    if frame.is_corrupt:
        raise ValueError('Corrupt decoded frame is not observation evidence')
    if not frame.width or not frame.height or frame.width * frame.height > 4096 * 2160:
        raise ValueError('Unsupported frame size')
    scale = min(1, 640 / max(frame.width, frame.height))
    width, height = max(1, round(frame.width * scale)), max(1, round(frame.height * scale))
    image = frame.reformat(width=width, height=height, format='bgr24').to_ndarray()
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise ValueError('JPEG encoding failed')
    return encoded.tobytes(), width, height
