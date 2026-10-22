import argparse
from dataclasses import replace
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Standalone CCTV Headless Engine')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--license', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True, help='Vendor public key; protect with administrator-only write permissions')
    args = parser.parse_args(argv)
    # Supervision imports plotting helpers; force a noninteractive backend.
    os.environ['MPLBACKEND'] = 'Agg'
    from cctv_tracker.config import Settings, SessionRules, app_data
    from .licensing import verify_license
    from .service import EngineService
    from .app import create_app
    from .webhooks import Webhook
    import uvicorn
    service = None
    lease = None
    try:
        license = verify_license(args.license, args.public_key)
        values = json.loads(args.config.read_text(encoding='utf-8'))
        allowed = {'data_dir', 'detector', 'device', 'model_path', 'port', 'cameras', 'webhook_url', 'sessions'}
        if set(values) - allowed:
            raise ValueError('Unknown headless configuration fields')
        root = Path(values.get('data_dir', app_data() / 'headless')).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        from cctv_tracker.lease import EngineLease
        lease = EngineLease(root / 'headless.sqlite3')
        service = EngineService(replace(Settings(), database=root / 'headless.sqlite3', sessions=SessionRules(**values.get('sessions', {}))), license,
                                detector=values.get('detector', 'yolox'), device=values.get('device', 'CPU'),
                                model_path=Path(values['model_path']).resolve() if values.get('model_path') else None)
        webhook = Webhook(values['webhook_url'], os.environ.get('CCTV_WEBHOOK_SECRET', ''), root / 'webhook-cursors.json') if values.get('webhook_url') else None
        app = create_app(service, os.environ.get('CCTV_HEADLESS_TOKEN', ''), webhook=webhook)
        from .app import CameraInput
        for raw in values.get('cameras', []):
            camera = CameraInput.model_validate({k: v for k, v in raw.items() if k != 'autostart'})
            service.add(camera.camera_id, camera.url)
            if raw.get('autostart', False):
                service.start(camera.camera_id)
        from cctv_tracker.supervisor import run_server
        run_server(app, host='127.0.0.1', port=values.get('port', 8766), workers=1, access_log=False)
    except (ValueError, OSError, RuntimeError) as error:
        # Do not print validation errors containing camera URLs/credentials.
        parser.exit(1, f'Headless startup failed ({type(error).__name__}); check config, license and model paths.\n')
    finally:
        if service:
            service.shutdown()
        if lease:
            lease.close()


if __name__ == '__main__':
    main()
