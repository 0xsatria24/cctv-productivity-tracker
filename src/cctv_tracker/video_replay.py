from pathlib import Path
import math

from .pipeline import Pipeline
from .vision import OnnxDetector


def replay_video(path: Path, manifest: Path, model: Path, settings, database, start, provider="CPUExecutionProvider", *, source="LOCAL_VIDEO_REPLAY"):
    """Offline file replay uses presentation time, never processing speed as duration."""
    import av
    if not path.is_file():
        raise ValueError("Video replay requires a local file")
    detector = OnnxDetector(model, manifest, provider)
    pipeline = Pipeline(settings, database, start, source, detector.sha, detector.manifest)
    origin = None
    next_sample = 0.0
    sequence = 0
    try:
        with av.open(str(path), timeout=(settings.open_timeout_seconds, settings.read_timeout_seconds)) as container:
            if not container.streams.video:
                raise ValueError("File has no video stream")
            for frame in container.decode(video=0):
                if frame.time is None or not math.isfinite(frame.time):
                    raise ValueError("Replay requires finite presentation timestamps")
                if origin is None:
                    origin = frame.time
                elapsed = frame.time - origin
                if elapsed + 1e-8 < next_sample:
                    continue
                sequence += 1
                next_sample = elapsed + 1 / settings.inference_fps
                detections = detector.detect(frame.to_ndarray(format="bgr24"))
                pipeline.feed(detections, start + round(elapsed * 1_000_000), round(elapsed * 1e9), sequence, "local-video-1")
        if sequence == 0:
            raise ValueError("No decodable video frames")
    except BaseException:
        pipeline.finish("INTERRUPTED")
        raise
    return {"run_id": pipeline.writer.run_id, "provider": detector.provider, **pipeline.finish()}
