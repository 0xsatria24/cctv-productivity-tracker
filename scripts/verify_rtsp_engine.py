"""Opt-in localhost RTSP smoke test; requires the separately launched test server.

No physical camera is opened. Frames are a labeled synthetic test source.
"""
from contextlib import closing
import argparse
from fractions import Fraction
from pathlib import Path
from threading import Event, Thread
import json
import time
import av
import cv2
import numpy as np

from cctv_tracker.config import Settings
from cctv_tracker.live import LiveController
from cctv_tracker.persistence import Database
from cctv_tracker.nanodet import NanoDetDetector
from cctv_tracker.openvino_yolox import OpenVinoYoloX

ROOT = Path(__file__).resolve().parents[1]
URL = 'rtsp://127.0.0.1:8854/pilot'


def publish(stop):
    with av.open(URL, mode='w', format='rtsp', options={'rtsp_transport': 'tcp'}) as container:
        stream = container.add_stream('libx264', rate=10)
        stream.width, stream.height, stream.pix_fmt = 320, 240, 'yuv420p'
        stream.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'g': '10', 'bf': '0'}
        i = 0
        while not stop.is_set():
            # Animated rectangle is explicitly not person evidence.
            image = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.rectangle(image, (i % 220, 80), (i % 220 + 60, 170), (120, 120, 120), -1)
            frame = av.VideoFrame.from_ndarray(image, format='bgr24')
            frame.pts, frame.time_base = i, Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
            i += 1
            stop.wait(0.1)
        for packet in stream.encode():
            container.mux(packet)


def wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise RuntimeError('RTSP verification timed out')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--detector', choices=['nanodet', 'yolox-openvino'], default='yolox-openvino')
    parser.add_argument('--openvino-device', choices=['CPU', 'GPU'], default='GPU')
    args = parser.parse_args()
    root = ROOT / 'runtime' / 'rtsp-verification'
    root.mkdir(parents=True, exist_ok=True)
    path = root / f'test-{time.time_ns()}.sqlite3'
    detector = OpenVinoYoloX(device=args.openvino_device) if args.detector == 'yolox-openvino' else NanoDetDetector()
    controller = LiveController(Settings(database=path), detector)
    stop = Event()
    publisher = Thread(target=publish, args=(stop,), daemon=True)
    publisher.start()
    try:
        state = controller.start('RTSP_LIVE', URL, preview_only=True)
        wait(lambda: controller.snapshot()['camera_health'] == 'ONLINE')
        state = controller.snapshot()
        assert state['latest']['count'] == 0 and state['run_id'] is None
        controller.stop(state['session_id'])
        wait(lambda: controller.snapshot()['status'] == 'STOPPED')
        controller.save_calibration('RTSP_LIVE', {'camera_key': state['camera_key'], 'width': 320, 'height': 240,
            'zones': [{'id': 'test-desk', 'name': 'Synthetic RTSP test area', 'polygon': [[0, 0], [1, 0], [1, 1], [0, 1]]}],
            'rules': {'occupied_confirm_seconds': 1, 'empty_confirm_seconds': 1, 'max_evidence_gap_seconds': 3}})
        session = controller.start('RTSP_LIVE', URL)['session_id']
        wait(lambda: controller.snapshot().get('latest') and controller.snapshot()['latest']['zones'][0]['state'] == 'EMPTY')
        time.sleep(1)
        # Drop the actual publisher, verify offline accounting, then reconnect.
        stop.set(); publisher.join(timeout=5)
        wait(lambda: controller.snapshot()['camera_health'] == 'RECONNECTING')
        time.sleep(3.5)
        stop = Event(); publisher = Thread(target=publish, args=(stop,), daemon=True); publisher.start()
        wait(lambda: controller.snapshot().get('latest') and controller.snapshot()['latest']['zones'][0]['state'] == 'EMPTY')
        controller.stop(session)
        wait(lambda: controller.snapshot()['status'] == 'STOPPED')
        with closing(Database(controller.settings.database)) as db:
            run = db.conn.execute('SELECT * FROM engine_runs').fetchone()
            result = db.report(run['started_utc_us'], run['ended_utc_us'], run_id=run['id'])
            row = result['workstations'][0]
            assert row['empty_us'] > 0 and row['unknown_us'] > 0 and row['occupied_us'] == 0
            assert db.conn.execute('SELECT COUNT(*) FROM camera_generations').fetchone()[0] >= 2
            assert db.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.conn.execute('PRAGMA foreign_key_check').fetchall() == []
            print(json.dumps({'source': 'SYNTHETIC_RTSP_TEST', 'database': str(controller.settings.database), 'reconnect_verified': True, 'report': result}, indent=2))
    finally:
        stop.set(); publisher.join(timeout=5); controller.shutdown()


if __name__ == '__main__':
    main()
