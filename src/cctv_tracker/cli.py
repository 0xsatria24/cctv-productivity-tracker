import argparse
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import importlib.metadata
import json
import os
import sqlite3
import sys
from uuid import uuid4
from importlib.resources import files

from .config import Settings, app_data, load_settings, timestamp
from .logging_setup import configure_logging, redact
from .persistence import Database


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local anonymous occupancy pilot. No biometric recognition.")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--database", type=Path, help="Local SQLite file; default is outside the source/OneDrive folder")
    parser.add_argument("--log-dir", type=Path, help="Optional development log directory; production defaults to local app data")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("doctor")
    demo = commands.add_parser("demo", help="Repeatable synthetic replay in a new database on every invocation")
    demo.add_argument("--output-dir", type=Path, help="Demo database directory; defaults to local app data/demos")
    replay_cmd = commands.add_parser("replay", help="Explicit synthetic detection fixture, using real ByteTrack/domain/SQLite")
    replay_cmd.add_argument("input", type=Path)
    video = commands.add_parser("replay-video", help="Offline video file and externally supplied licensed ONNX model")
    video.add_argument("input", type=Path)
    video.add_argument("--model", type=Path, required=True)
    video.add_argument("--manifest", type=Path, required=True)
    video.add_argument("--start", required=True, help="UTC/offset-aware anchor for source video presentation time")
    video.add_argument("--provider", choices=["CPUExecutionProvider", "CUDAExecutionProvider"], default="CPUExecutionProvider")
    report = commands.add_parser("report")
    report.add_argument("--start", required=True)
    report.add_argument("--end", required=True)
    employee = commands.add_parser("employee-add")
    employee.add_argument("name")
    commands.add_parser("employees")
    commands.add_parser("workspaces")
    assignment = commands.add_parser("assign")
    assignment.add_argument("--employee", required=True)
    assignment.add_argument("--workspace", required=True)
    assignment.add_argument("--start", required=True)
    assignment.add_argument("--end", required=True, help="Explicit assignment expiry; never interpreted as observed identity")
    serve = commands.add_parser("serve-pilot", help="Authenticated, read-only loopback API")
    serve.add_argument("--port", type=int, default=8765)
    dashboard = commands.add_parser("dashboard", help="Run the integrated React dashboard with live webcam/RTSP accounting and isolated replay")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument('--detector', choices=['nanodet', 'yolox', 'yolox-openvino'], default='yolox-openvino', help='YOLOX OpenVINO: optimized quality mode; yolox: ONNX baseline; nanodet: lightweight')
    dashboard.add_argument('--openvino-device', choices=['CPU', 'GPU'], default='GPU', help='Explicit OpenVINO device; no silent fallback')
    dashboard.add_argument('--detection-profile', choices=['balanced', 'detail'], help='YOLOX detail runs full frame plus overlapping tiles; costs up to five model passes')
    dashboard.add_argument('--detection-confidence', type=float, help='YOLOX person confidence in (0,1); lower values require false-positive validation')
    dashboard.add_argument("--ui-dir", type=Path, default=Path(__file__).resolve().parents[2] / "prototype" / "dist")
    args = parser.parse_args(argv)
    logger = configure_logging(args.log_dir or app_data() / "logs")
    try:
        settings = load_settings(args.config) if args.config else Settings()
        if args.database:
            settings = replace(settings, database=args.database.expanduser().resolve())
        elif args.command == "dashboard" and not args.config:
            settings = replace(settings, database=app_data() / "dashboard-pilot.sqlite3")
        if args.command == "demo":
            from .pipeline import replay
            if args.database:
                raise ValueError("Demo always creates a fresh database; use --output-dir instead of --database")
            settings = load_settings(Path(str(files("cctv_tracker").joinpath("resources", "pilot.example.json"))))
            # Demo never replaces or mixes with a production database.
            root = args.output_dir or app_data() / "demos"
            settings = replace(settings, database=root / f"replay-{uuid4().hex}.sqlite3")
            with closing(Database(settings.database)) as database:
                result = replay(Path(str(files("cctv_tracker").joinpath("resources", "occupancy-replay.json"))), settings, database)
                emit({"database": str(settings.database), **result})
            return
        if args.command == "doctor":
            packages = {}
            for name in ("cctv-tracker", "av", "onnxruntime", "supervision", "numpy", "opencv-python", "fastapi", "uvicorn", "openvino"):
                try:
                    packages[name] = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    packages[name] = None
            try:
                import onnxruntime
                providers = onnxruntime.get_available_providers()
            except ImportError:
                providers = []
            try:
                import openvino as ov
                openvino_devices = ov.Core().available_devices
            except (ImportError, RuntimeError):
                openvino_devices = []
            emit({"python": sys.version.split()[0], "packages": packages, "sqlite": sqlite3.sqlite_version, "openvino_devices": openvino_devices,
                  "providers": providers, "identity_source": "anonymous", "face_recognition_enabled": False})
            return
        with closing(Database(settings.database)) as database:
            if args.command == "init-db":
                emit({"database": str(settings.database), "schema_version": database.conn.execute("PRAGMA user_version").fetchone()[0]})
            elif args.command == "replay":
                from .pipeline import replay
                emit(replay(args.input, settings, database))
            elif args.command == "replay-video":
                from .video_replay import replay_video
                emit(replay_video(args.input, args.manifest, args.model, settings, database, timestamp(args.start), args.provider))
            elif args.command == "report":
                emit(database.report(timestamp(args.start), timestamp(args.end)))
            elif args.command == "employee-add":
                emit({"employee_id": database.add_employee(args.name), "identity_source": "manual_registry"})
            elif args.command in {"employees", "workspaces"}:
                emit([dict(row) for row in database.conn.execute("SELECT * FROM " + args.command)])
            elif args.command == "assign":
                database.assign(args.employee, args.workspace, timestamp(args.start), timestamp(args.end))
                emit({"status": "saved", "source": "manual_assignment", "is_observed_identity": False})
        if args.command in {"serve-pilot", "dashboard"}:
            from .api import create_app
            import uvicorn
            if args.command == "dashboard":
                from .dashboard import ReplayController
                import secrets
                if not args.config:
                    settings = replace(load_settings(Path(str(files("cctv_tracker").joinpath("resources", "pilot.example.json")))), database=settings.database)
                if args.detection_profile:
                    settings = replace(settings, detection=replace(settings.detection, detail=args.detection_profile == 'detail'))
                if args.detection_confidence is not None:
                    settings = replace(settings, detection=replace(settings.detection, confidence=args.detection_confidence))
                controller = ReplayController(settings)
                token = secrets.token_urlsafe(32)
                app = create_app(settings.database, token, controller=controller, ui_dir=args.ui_dir, timezone=settings.timezone, detector_kind=args.detector, openvino_device=args.openvino_device)
                if args.detector == 'yolox-openvino':
                    print(f'Loading YOLOX-S OpenVINO {args.openvino_device}; first GPU kernel compilation may take longer, then cached.', flush=True)
                print(f"Dashboard: http://127.0.0.1:{args.port}/\nSources: live webcam / RTSP and isolated synthetic replay. Replay database: {settings.database}", flush=True)
            else:
                app = create_app(settings.database, os.environ.get("CCTV_LOCAL_TOKEN", ""))
            uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, access_log=False)
        logger.info("Command completed: %s", args.command)
    except KeyboardInterrupt:
        logger.info("Command interrupted")
        raise SystemExit(130)
    except Exception as error:
        # Native exceptions and local paths may contain secrets; do not dump tracebacks to stdout.
        logger.error("Command failed: %s: %s", type(error).__name__, redact(str(error)))
        parser.exit(1, f"{type(error).__name__}: {redact(str(error))}\n")
