"""Bounded restart supervisor with process-tree ownership and cooperative stop."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event, Thread
import time
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

from .lease import EngineLease
from .secure_store import atomic_write


class ProcessJob:
    """Close on Windows kills only this supervisor's child process tree."""
    def __init__(self, process):
        self.process, self.handle = process, None
        if os.name != 'nt':
            return
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong), ('flags', wintypes.DWORD),
                        ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = Extended(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            if self.handle:
                self.kernel.CloseHandle(self.handle)
            self.handle = None
            process.terminate(); process.wait(timeout=10)
            raise RuntimeError('Cannot establish process-tree ownership')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif os.name != 'nt':
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def healthy(url):
    try:
        # Ignore proxy environment variables for local health checks.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def supervise(command, state_dir, *, health_url=None, stop=None, max_restarts=5, startup_grace=120, interval=2, stop_grace=20):
    if not command:
        raise ValueError('Child command required')
    if health_url:
        url = urlsplit(health_url)
        if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost'} or url.username or url.password:
            raise ValueError('Health URL must be unauthenticated loopback HTTP')
    root = Path(state_dir).resolve(); root.mkdir(parents=True, exist_ok=True)
    stop = stop or Event()
    lease = EngineLease(root / 'supervisor')
    restarts = 0
    def status(**values):
        atomic_write(root / 'supervisor-status.json', json.dumps({'updated_at': time.time(), 'restarts': restarts, **values}).encode())
    try:
        # Never mistake an existing unrelated server for the child being supervised.
        if health_url and healthy(health_url):
            raise RuntimeError('The requested application port is already serving HTTP')
        while not stop.is_set():
            stop_file = root / ('stop-' + uuid4().hex)
            env = {**os.environ, 'CCTV_STOP_FILE': str(stop_file)}
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                       start_new_session=os.name != 'nt')
            job = ProcessJob(process)
            started, failures, reason = time.monotonic(), 0, 'child_exited'
            try:
                status(state='STARTING', child_pid=process.pid)
                while process.poll() is None and not stop.wait(interval):
                    if health_url:
                        if healthy(health_url):
                            failures = 0
                            status(state='RUNNING', child_pid=process.pid)
                        elif time.monotonic() - started >= startup_grace:
                            failures += 1
                            if failures >= 3:
                                reason = 'health_timeout'
                                break
                    if time.monotonic() - started >= 300 and failures == 0:
                        restarts = 0
                if stop.is_set():
                    reason = 'requested_stop'
                if process.poll() is None:
                    atomic_write(stop_file, b'stop')
                    try:
                        process.wait(timeout=stop_grace)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                job.close()
                process.wait(timeout=10)
                stop_file.unlink(missing_ok=True)
            if stop.is_set() or process.returncode == 0 and reason == 'child_exited':
                status(state='STOPPED', reason=reason, exit_code=process.returncode)
                return 0
            if restarts >= max_restarts:
                status(state='FAILED', reason=reason, exit_code=process.returncode)
                return 1
            restarts += 1
            delay = min(60, 2 ** restarts)
            status(state='RESTARTING', reason=reason, delay_seconds=delay)
            stop.wait(delay)
        status(state='STOPPED', reason='requested_stop')
        return 0
    finally:
        lease.close()


def run_server(app, **kwargs):
    """Uvicorn with a private supervisor-owned stop signal; no shutdown HTTP route."""
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, **kwargs))
    finished = Event()
    signal_path = os.environ.get('CCTV_STOP_FILE')
    def watch():
        while not finished.wait(0.2):
            if Path(signal_path).exists():
                server.should_exit = True
                return
    watcher = Thread(target=watch, daemon=True) if signal_path else None
    if watcher:
        watcher.start()
    try:
        server.run()
        if not server.started:
            raise RuntimeError('HTTP server did not start')
    finally:
        finished.set()
        if watcher:
            watcher.join(timeout=1)


def main():
    parser = argparse.ArgumentParser(description='Supervise one local CCTV application process tree')
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--health-url')
    parser.add_argument('--max-restarts', type=int, default=5, choices=range(0, 21))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    stop = Event()
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    raise SystemExit(supervise(command, args.state_dir, health_url=args.health_url, max_restarts=args.max_restarts, stop=stop))


if __name__ == '__main__':
    main()
