"""Isolated RTSP decoding with a one-frame mailbox and bounded process shutdown."""
import multiprocessing as mp
from queue import Empty, Full
import time
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


def capture_worker(url, mailbox, stop, open_timeout, read_timeout, capture_fps=24, native_threads=1):
    import av
    import cv2
    from .frame_image import encode_frame
    cv2.setNumThreads(native_threads)
    # Native FFmpeg diagnostics may include credentials. Return only fixed errors.
    av.logging.set_level(av.logging.PANIC)
    generation = uuid4().hex
    try:
        with av.open(url, format='rtsp', options={'rtsp_transport': 'tcp', 'fflags': 'nobuffer', 'flags': 'low_delay'}, timeout=(open_timeout, read_timeout)) as container:
            if not container.streams.video:
                raise ValueError('No video')
            container.streams.video[0].codec_context.thread_count = native_threads
            previous_pts, sampled, decoded, encoded_count, corrupt_dropped = None, 0.0, 0, 0, 0
            for frame in container.decode(video=0):
                if stop.is_set():
                    break
                decoded += 1
                if frame.is_corrupt:
                    corrupt_dropped += 1
                    continue  # Damaged decoded pixels are not observation evidence.
                # Repeated source PTS is not new evidence. A backwards PTS starts a generation.
                if frame.pts is not None and previous_pts is not None:
                    if frame.pts == previous_pts:
                        continue
                    if frame.pts < previous_pts:
                        generation = uuid4().hex
                previous_pts = frame.pts
                captured = time.perf_counter_ns()
                if int(captured / 1e9 * capture_fps) <= sampled:
                    continue
                sampled = int(captured / 1e9 * capture_fps)
                jpeg, _, _ = encode_frame(frame)
                encoded_count += 1
                _latest(mailbox, {'jpeg': jpeg, 'monotonic_ns': captured, 'generation': generation,
                                 'capture_metrics':{'decoded':decoded,'sampled':encoded_count,'sample_skipped':decoded-encoded_count-corrupt_dropped,'corrupt_dropped':corrupt_dropped},
                                 'source_pts_ns':round(float(frame.time)*1e9) if frame.time is not None else None})
    except Exception:
        _latest(mailbox, {'error': 'RTSP tidak dapat dibaca; periksa jaringan, URL, kredensial dan codec'})
    finally:
        # No feeder join that could hang if the parent is shutting down.
        mailbox.cancel_join_thread()


class RtspCapture:
    def __init__(self, url, settings, *, worker=capture_worker):
        self.context = mp.get_context('spawn')
        self.mailbox = self.context.Queue(maxsize=settings.capture_queue_size)
        self.stop_event = self.context.Event()
        args = (url, self.mailbox, self.stop_event, settings.open_timeout_seconds, settings.read_timeout_seconds)
        if worker is capture_worker:
            args += (settings.capture_fps,settings.native_threads)
        self.process = self.context.Process(target=worker, args=args, daemon=True)
        self.process.start()
        self.started = time.perf_counter()
        self.last_sampled, self.mailbox_dropped, self.delivered = 0, 0, 0

    def read(self, timeout=0.2):
        try:
            item = self.mailbox.get(timeout=timeout)
            # If the feeder supplied another frame, choose the latest one.
            while True:
                try:
                    item = self.mailbox.get_nowait()
                except Empty:
                    if item.get('capture_metrics'):
                        metrics = item['capture_metrics']
                        self.mailbox_dropped += max(0,metrics['sampled']-self.last_sampled-1)
                        self.last_sampled = metrics['sampled']
                        self.delivered += 1
                        metrics.update(mailbox_dropped=self.mailbox_dropped,delivered=self.delivered)
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
