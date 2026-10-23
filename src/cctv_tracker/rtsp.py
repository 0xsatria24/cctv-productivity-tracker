"""Isolated RTSP decoding with a one-frame mailbox and bounded process shutdown."""
import multiprocessing as mp
from queue import Empty, Full
import time
import math
from urllib.parse import urlsplit
from uuid import uuid4
from hashlib import sha256


def validate_rtsp_url(value):
    try:
        url = urlsplit(value)
        if len(value) > 2048 or url.scheme not in ('rtsp', 'rtsps') or not url.hostname or url.fragment or any(c.isspace() for c in value):
            raise ValueError()
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError('Masukkan URL rtsp:// atau rtsps:// dengan host dan port yang valid') from None
    return value


def rtsp_camera_key(url):
    parsed = urlsplit(validate_rtsp_url(url))
    return sha256(f'{parsed.scheme}://{parsed.hostname}:{parsed.port or 554}{parsed.path}?{parsed.query}'.encode()).hexdigest()


def _latest(mailbox, item):
    try:
        mailbox.put_nowait(item)
    except Full:
        try:
            mailbox.get_nowait()
        except Empty:
            pass
        try:
            mailbox.put_nowait(item)
        except Full:
            pass


def capture_dimensions(width, height):
    scale = min(1, 1280 / max(width, height), math.sqrt((1280 * 720) / (width * height)))
    return max(1, int(width * scale)), max(1, int(height * scale))


def capture_worker(url, mailbox, stop, open_timeout, read_timeout):
    import av
    import cv2
    # Native FFmpeg diagnostics may include credentials. Return only fixed errors.
    av.logging.set_level(av.logging.PANIC)
    generation = uuid4().hex
    try:
        with av.open(url, format='rtsp', options={'rtsp_transport': 'tcp', 'fflags': 'nobuffer', 'flags': 'low_delay'}, timeout=(open_timeout, read_timeout)) as container:
            if not container.streams.video:
                raise ValueError('No video')
            previous_pts, sampled = None, 0.0
            for frame in container.decode(video=0):
                if stop.is_set():
                    break
                # Repeated source PTS is not new evidence. A backwards PTS starts a generation.
                if frame.pts is not None and previous_pts is not None:
                    if frame.pts == previous_pts:
                        continue
                    if frame.pts < previous_pts:
                        generation = uuid4().hex
                previous_pts = frame.pts
                captured = time.perf_counter_ns()
                if captured / 1e9 - sampled < 0.25:
                    continue
                sampled = captured / 1e9
                if frame.width * frame.height > 4096 * 2160:
                    raise ValueError('Unsupported frame size')
                width, height = capture_dimensions(frame.width, frame.height)
                image = frame.reformat(width=width, height=height, format='bgr24').to_ndarray()
                success, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if success:
                    _latest(mailbox, {'jpeg': encoded.tobytes(), 'monotonic_ns': captured, 'generation': generation})
    except Exception:
        _latest(mailbox, {'error': 'RTSP tidak dapat dibaca; periksa jaringan, URL, kredensial dan codec'})
    finally:
        # No feeder join that could hang if the parent is shutting down.
        mailbox.cancel_join_thread()


class RtspCapture:
    def __init__(self, url, settings, *, worker=capture_worker):
        self.context = mp.get_context('spawn')
        self.mailbox = self.context.Queue(maxsize=1)
        self.stop_event = self.context.Event()
        self.process = self.context.Process(target=worker, args=(url, self.mailbox, self.stop_event, settings.open_timeout_seconds, settings.read_timeout_seconds), daemon=True)
        self.process.start()
        self.started = time.perf_counter()

    def read(self, timeout=0.2):
        try:
            item = self.mailbox.get(timeout=timeout)
            # If the feeder supplied another frame, choose the latest one.
            while True:
                try:
                    item = self.mailbox.get_nowait()
                except Empty:
                    return item
        except Empty:
            return None

    def close(self):
        self.stop_event.set()
        self.process.join(timeout=0.5)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=2)
        self.mailbox.close()
        self.mailbox.cancel_join_thread()
