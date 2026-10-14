"""Optional local three-camera test rig. Synthetic video only, no physical device."""
from fractions import Fraction
from pathlib import Path
from threading import Event, Thread
import socket
import subprocess
import time
import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def publish(number, stop):
    av.logging.set_level(av.logging.PANIC)
    with av.open(f'rtsp://127.0.0.1:8854/wall{number}', mode='w', format='rtsp', options={'rtsp_transport': 'tcp'}) as container:
        stream = container.add_stream('libx264', rate=10)
        stream.width, stream.height, stream.pix_fmt = 640, 360, 'yuv420p'
        stream.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'g': '10', 'bf': '0'}
        index = 0
        while not stop.is_set():
            image = np.full((360, 640, 3), (24 + number * 8, 32, 22), dtype=np.uint8)
            for x in range(40, 640, 100):
                cv2.rectangle(image, (x, 145), (x + 65, 255), (70, 80, 75), 2)
            cv2.rectangle(image, (index * 4 % 560, 290), (index * 4 % 560 + 50, 330), (120, 170, 140), -1)
            cv2.putText(image, f'SYNTHETIC TEST CAMERA {number}', (24, 46), cv2.FONT_HERSHEY_SIMPLEX, .7, (180, 210, 190), 1)
            cv2.putText(image, f'Frame {index} | NO PHYSICAL CCTV', (24, 80), cv2.FONT_HERSHEY_SIMPLEX, .5, (160, 170, 165), 1)
            frame = av.VideoFrame.from_ndarray(image, format='bgr24')
            frame.pts, frame.time_base = index, Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
            index += 1; stop.wait(.1)
        for packet in stream.encode():
            container.mux(packet)


def main():
    binary = ROOT / 'runtime/rtsp-test-server/mediamtx.exe'
    if not binary.exists():
        raise RuntimeError('Install the optional MediaMTX test binary described in LIVE-ENGINE.md')
    with socket.socket() as check:
        check.bind(('127.0.0.1', 8854))  # Never terminate or reuse another server on this port.
    config = binary.parent / 'wall-test.yml'
    config.write_text('logLevel: warn\nrtspAddress: 127.0.0.1:8854\nrtspTransports: [tcp]\nrtmp: no\nhls: no\nwebrtc: no\nsrt: no\nmoq: no\npaths:\n  wall1:\n    source: publisher\n  wall2:\n    source: publisher\n  wall3:\n    source: publisher\n')
    server = subprocess.Popen([str(binary), str(config)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    stop, threads = Event(), []
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(('127.0.0.1', 8854), timeout=.5):
                    break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Synthetic RTSP test server failed to start')
                time.sleep(.1)
        for number in (1, 2, 3):
            thread = Thread(target=publish, args=(number, stop), daemon=True)
            thread.start(); threads.append(thread)
        print('SYNTHETIC TEST ONLY: three independent localhost RTSP streams at /wall1, /wall2, /wall3. Ctrl+C stops the owned test server.', flush=True)
        while not stop.wait(1):
            if server.poll() is not None or any(not t.is_alive() for t in threads):
                raise RuntimeError('Synthetic test publisher stopped')
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=3)
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait(timeout=3)


if __name__ == '__main__':
    main()
