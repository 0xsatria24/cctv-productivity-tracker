"""Same licensed YOLOX weights and decoder, accelerated by OpenVINO."""
from pathlib import Path
from .webcam import WebcamDetector, MODEL_PATH


class OpenVinoYoloX(WebcamDetector):
    def __init__(self, model_path=MODEL_PATH, *, device='CPU', threads=4, cache_dir=None, tuning=None):
        super().__init__(model_path, tuning=tuning)
        if device not in {'CPU', 'GPU'}:
            raise ValueError('Perangkat OpenVINO harus CPU atau GPU; tidak ada fallback otomatis')
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError('Thread OpenVINO harus 1 sampai 16')
        self.device, self.threads = device, threads
        self.cache_dir = Path(cache_dir) if cache_dir else self.path.parent / 'openvino-cache'
        self.runtime_label = f'YOLOX-S · OpenVINO {device}'
        self.manifest.update(provider='OpenVINO', requested_device=device, precision='f32', performance_hint='LATENCY')

    def _load_backend(self):
        try:
            import openvino as ov
        except ImportError:
            raise RuntimeError('OpenVINO belum terpasang; install project extra [openvino]') from None
        core = ov.Core()
        if self.device not in core.available_devices:
            raise RuntimeError(f'OpenVINO {self.device} tidak tersedia; periksa driver atau pilih CPU secara eksplisit')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        model = core.read_model(str(self.path))
        if len(model.inputs) != 1 or list(model.input(0).shape) != [1, 3, 640, 640] or len(model.outputs) != 1 or list(model.output(0).shape) != [1, 8400, 85]:
            raise RuntimeError('Kontrak input/output YOLOX tidak sesuai')
        config = {'PERFORMANCE_HINT': 'LATENCY', 'INFERENCE_PRECISION_HINT': ov.Type.f32,
                  'NUM_STREAMS': ov.properties.streams.Num(1), 'CACHE_DIR': str(self.cache_dir.resolve())}
        if self.device == 'CPU':
            config['INFERENCE_NUM_THREADS'] = self.threads
        compiled = core.compile_model(model, self.device, config)
        actual = list(compiled.get_property('EXECUTION_DEVICES'))
        if not actual or any(d.split('.')[0] != self.device for d in actual):
            raise RuntimeError('OpenVINO tidak menjalankan perangkat yang diminta')
        self.request = compiled.create_infer_request()
        self.session = compiled
        self.manifest.update(runtime_version=ov.__version__, execution_devices=actual,
                             device_name=core.get_property(self.device, 'FULL_DEVICE_NAME'),
                             threads=self.threads if self.device == 'CPU' else None)

    def _infer(self, blob):
        # Called only under the shared detector lock. Output is decoded before reuse.
        self.request.infer({self.session.input(0): blob})
        return self.request.get_output_tensor(0).data[0]
