"""Installed dashboard launcher shared by desktop, supervisor and service."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    path = args.config.resolve()
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if set(value) != {'database', 'model_dir', 'ui_dir', 'port', 'detector', 'device'}:
        raise ValueError('Invalid deployment configuration')
    def local(name):
        result = Path(value[name]).expanduser()
        return result.resolve() if result.is_absolute() else (path.parent / result).resolve()
    database = local('database')
    os.environ['CCTV_MODEL_DIR'] = str(local('model_dir'))
    os.environ['MPLCONFIGDIR'] = str(database.parent / 'matplotlib')
    from .cli import main as run
    run(['--database', str(database), '--log-dir', str(database.parent / 'logs'), 'dashboard',
         '--ui-dir', str(local('ui_dir')), '--port', str(value['port']), '--detector', value['detector'], '--openvino-device', value['device']])


if __name__ == '__main__':
    main()
