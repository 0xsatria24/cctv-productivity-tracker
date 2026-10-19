"""Loop local videos as localhost-only RTSP replay sources for dashboard testing."""
import argparse
from fractions import Fraction
from pathlib import Path
import socket
import subprocess
from threading import Event, Thread
import time

import av


def publish(path, url, stop, failures):
    try:
        with av.open(url, 'w', format='rtsp', options={'rtsp_transport': 'tcp'}) as output:
            stream = output.add_stream('libx264', rate=24)
            stream.width, stream.height, stream.pix_fmt = 960, 540, 'yuv420p'
            stream.bit_rate = 900_000
            stream.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'g': '24', 'bf': '0'}
            index = 0
            deadline = time.perf_counter()
            while not stop.is_set():
                with av.open(str(path)) as source:
                    origin = None
                    last_sample = -1
                    for frame in source.decode(video=0):
                        if stop.is_set():
                            break
                        timestamp = float(frame.time or 0)
                        if origin is None:
                            origin = timestamp
                        sample = int((timestamp - origin) * 24 + 0.001)
                        if sample <= last_sample:
                            continue
                        last_sample = sample
                        if stop.wait(max(0, deadline - time.perf_counter())):
                            break
                        frame = frame.reformat(width=960, height=540, format='yuv420p')
                        frame.pts, frame.time_base = index, Fraction(1, 24)
                        for packet in stream.encode(frame):
                            output.mux(packet)
                        index += 1
                        deadline += 1 / 24
            for packet in stream.encode():
                output.mux(packet)
    except Exception as error:
        failures.append(f'{path.name}: {error}')
        stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8856)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('videos', type=Path, nargs='+')
    args = parser.parse_args()
    for path in [args.server, *args.videos]:
        if not path.is_file():
            parser.error(f'File not found: {path}')
    with socket.socket() as check:
        check.bind(('127.0.0.1', args.port))
    args.runtime.mkdir(parents=True, exist_ok=True)
    config = args.runtime / 'mediamtx.yml'
    config.write_text(f'logLevel: warn\nrtspAddress: 127.0.0.1:{args.port}\nrtspTransports: [tcp]\nrtmp: no\nhls: no\nwebrtc: no\nsrt: no\nmoq: no\npaths:\n' + ''.join(f'  replay{i}:\n    source: publisher\n' for i in range(1, len(args.videos) + 1)))
    server = subprocess.Popen([str(args.server.resolve()), str(config.resolve())], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    stop, threads, failures = Event(), [], []
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(('127.0.0.1', args.port), timeout=.5):
                    break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Local replay server failed to start')
                time.sleep(.1)
        for i, path in enumerate(args.videos, 1):
            url = f'rtsp://127.0.0.1:{args.port}/replay{i}'
            thread = Thread(target=publish, args=(path, url, stop, failures), daemon=True)
            thread.start()
            threads.append(thread)
            print(f'LOCAL VIDEO REPLAY (LOOP): {url} | {path.name}', flush=True)
        while not stop.wait(1):
            if (args.runtime / 'stop.signal').exists():
                stop.set()
            if server.poll() is not None:
                raise RuntimeError('Local replay server exited')
        if failures:
            raise RuntimeError('; '.join(failures))
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
            server.kill()
            server.wait(timeout=3)


if __name__ == '__main__':
    main()
