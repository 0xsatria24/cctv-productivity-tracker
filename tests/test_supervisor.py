import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time

from cctv_tracker.supervisor import supervise


def test_crashed_child_restarts_then_exits_without_infinite_loop(tmp_path):
    marker = tmp_path / 'count.txt'
    child = tmp_path / 'child.py'
    child.write_text("import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nn=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\ntime.sleep(.2)\nsys.exit(1 if n==0 else 0)\n")
    assert supervise([sys.executable, str(child), str(marker)], tmp_path / 'supervisor', interval=.05, stop_grace=1) == 0
    assert marker.read_text() == '2'
    state = json.loads((tmp_path / 'supervisor/supervisor-status.json').read_text())
    assert state['state'] == 'STOPPED' and state['restarts'] == 1


def test_exhaustion_is_bounded_and_stop_is_cooperative(tmp_path):
    assert supervise([sys.executable, '-c', 'import time; time.sleep(.2); raise SystemExit(3)'], tmp_path / 'failed', max_restarts=0, interval=.05) == 1
    assert json.loads((tmp_path / 'failed/supervisor-status.json').read_text())['state'] == 'FAILED'
    child = tmp_path / 'wait.py'
    child.write_text("import os,pathlib,time\np=pathlib.Path(os.environ['CCTV_STOP_FILE'])\nwhile not p.exists():time.sleep(.05)\n")
    stop = Event()
    result = []
    thread = Thread(target=lambda: result.append(supervise([sys.executable, str(child)], tmp_path / 'stop', stop=stop, interval=.05)))
    thread.start()
    deadline = time.monotonic() + 5
    while not (tmp_path / 'stop/supervisor-status.json').exists():
        assert time.monotonic() < deadline
        time.sleep(.02)
    stop.set(); thread.join(timeout=6)
    assert result == [0]
