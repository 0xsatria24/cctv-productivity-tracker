"""Local, atomic checkpoints for anonymous replay area measurements."""
import json
from pathlib import Path
from time import time


class ReplayStateStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def read(self, replay_id):
        path = self.directory / (replay_id+'.json')
        if not path.exists():
            return None
        if path.stat().st_size > 2_000_000:
            raise ValueError('Checkpoint replay terlalu besar')
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('version') != 1 or record.get('replay_id') != replay_id:
            raise ValueError('Checkpoint replay tidak valid')
        return record

    def write(self, replay_id, calibration, timeline):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (replay_id+'.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'replay_id': replay_id, 'saved_at': time(),
            'calibration': calibration, 'workstations': timeline.export_state()}, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
