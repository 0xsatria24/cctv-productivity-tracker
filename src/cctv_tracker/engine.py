"""Shared construction boundary for every product edition (no UI imports)."""
def create_detector(kind='yolox', device='CPU', model_path=None):
    from .webcam import WebcamDetector
    from .nanodet import NanoDetDetector
    from .openvino_yolox import OpenVinoYoloX
    classes = {'yolox': WebcamDetector, 'nanodet': NanoDetDetector, 'yolox-openvino': OpenVinoYoloX}
    if kind not in classes:
        raise ValueError('Detector tidak didukung')
    kwargs = {'model_path': model_path} if model_path else {}
    if kind == 'yolox-openvino':
        kwargs['device'] = device
    return classes[kind](**kwargs)


def create_live_engine(settings, detector):
    from .live import LiveController
    return LiveController(settings, detector)
