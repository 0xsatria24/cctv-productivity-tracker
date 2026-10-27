"""Browser integration fixture. No physical device, network camera or production data."""
from contextlib import closing
from pathlib import Path
import time
from types import SimpleNamespace


def main():
    import cv2
    import numpy as np
    from cctv_tracker.api import create_app
    from cctv_tracker.config import Settings
    from cctv_tracker.dashboard import ReplayController
    from cctv_tracker.persistence import Database
    from cctv_tracker.supervisor import run_server
    import cctv_tracker.engine as engine
    import cctv_tracker.fleet as fleet_module
    class Detector:
        session = True
        runtime_label = 'SYNTHETIC BROWSER FIXTURE'
        manifest = {'source': 'synthetic fixture', 'license': 'local test'}
        sha = 'e' * 64
        def detect(self, jpeg):
            return {'width': 320, 'height': 240, 'count': 1, 'detections': [{'box': [.2,.2,.6,.9], 'confidence': .95}], 'model': self.runtime_label, 'inference_ms': 1}
    class Capture:
        def __init__(self, url, settings):
            self.started, self.closed = time.perf_counter(), False
            self.process = SimpleNamespace(is_alive=lambda: not self.closed)
            frame = np.zeros((240,320,3),np.uint8)
            cv2.rectangle(frame,(64,48),(192,216),(80,120,100),2)
            cv2.putText(frame,'SYNTHETIC TEST',(12,26),cv2.FONT_HERSHEY_SIMPLEX,.5,(220,220,220),1)
            self.jpeg = cv2.imencode('.jpg',frame)[1].tobytes()
        def read(self, timeout=.1):
            time.sleep(.1)
            return {'jpeg':self.jpeg,'monotonic_ns':time.perf_counter_ns(),'generation':str(self.started)}
        def close(self):
            self.closed=True
    original = fleet_module.CameraFleet
    fleet_module.CameraFleet = lambda settings, detector: original(settings,detector,capture_factory=Capture)
    engine.create_detector = lambda *args, **kwargs: Detector()
    root = Path(__file__).resolve().parents[1]
    settings = Settings(database=root/'runtime/fleet-browser-fixture.sqlite3')
    with closing(Database(settings.database)):
        pass
    app = create_app(settings.database,'f'*32,controller=ReplayController(settings),ui_dir=root/'prototype/dist',detector_kind='yolox')
    run_server(app,host='127.0.0.1',port=8771,access_log=False)


if __name__=='__main__':
    main()
