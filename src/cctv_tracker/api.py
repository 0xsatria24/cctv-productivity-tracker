"""Authenticated local pilot API and optional same-origin dashboard."""
from contextlib import asynccontextmanager, closing, ExitStack
from pathlib import Path
import csv
import base64
import io
import secrets
import sqlite3
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .persistence import Database
from .dashboard import snapshot, report as dashboard_report


class EmployeeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: str
    workspace_id: str
    start_utc_us: int = Field(ge=0)
    end_utc_us: int = Field(gt=0)


class LiveZoneInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=64)
    exclusive_group: str = Field(default='workstations', min_length=1, max_length=40)


class LiveRulesInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    occupied_confirm_seconds: float = Field(default=2, ge=0.1, le=60)
    empty_confirm_seconds: float = Field(default=5, ge=0.1, le=120)
    max_evidence_gap_seconds: float = Field(default=3, ge=0.5, le=10)
    association_overlap: float = Field(default=0.25, gt=0, le=1)
    ambiguity_margin: float = Field(default=0.1, gt=0, le=1)
    strong_confidence: float = Field(default=0.5, gt=0, le=1)


class CalibrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal['WEBCAM_LIVE', 'RTSP_LIVE']
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)
    zones: list[LiveZoneInput] = Field(min_length=1, max_length=16)
    rules: LiveRulesInput
    camera_key: str = Field(min_length=64, max_length=64)


class LiveStartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal['WEBCAM_LIVE', 'RTSP_LIVE']
    url: str | None = Field(default=None, max_length=2048)
    preview_only: bool = False
    camera_key: str | None = Field(default=None, min_length=64, max_length=64)


class LiveStopInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=80)


class PreviewCameraInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2048)


class CameraViewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    viewer_id: str = Field(min_length=1, max_length=64)
    camera_ids: list[str] = Field(max_length=16)


class CameraRecoveryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    auto_resume: bool


class BackupPolicyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    keep_days: int = Field(ge=1, le=365)


def create_app(database: Path, token: str, *, controller=None, ui_dir: Path | None = None, timezone="Asia/Jakarta", detector_kind='yolox', openvino_device='GPU'):
    if len(token) < 32:
        raise ValueError("Pilot API requires a local token of at least 32 characters")
    from .maintenance import BackupManager
    backups = BackupManager(database)
    if backups.journal.exists():
        raise RuntimeError('Restore belum selesai. Jalankan ulang restore dengan backup ID yang sama.')

    @asynccontextmanager
    async def lifespan(app):
        from .lease import EngineLease
        from .maintenance import app_lock_path
        lease = None
        try:
            lease = EngineLease(app_lock_path(database))
            if backups.journal.exists():
                raise RuntimeError('Restore belum selesai. Jalankan ulang restore dengan backup ID yang sama.')
            if detector_kind == 'yolox-openvino':
                import cv2
                import numpy as np
                await run_in_threadpool(webcam_detector.detect, cv2.imencode('.jpg', np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes())
            if camera_wall:
                camera_wall.startup()
            if controller:
                backups.startup()
            yield
        finally:
            with ExitStack() as cleanup:
                if lease:
                    cleanup.callback(lease.close)
                if controller:
                    cleanup.callback(controller.shutdown)
                if live:
                    cleanup.callback(live.shutdown)
                if camera_wall:
                    cleanup.callback(camera_wall.shutdown)
                cleanup.callback(backups.shutdown)

    app = FastAPI(title="CCTV local pilot API", version="0.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", *([] if ui_dir else ["testserver"])])
    bearer = HTTPBearer(auto_error=False)
    from .webcam import jpeg_dimensions
    from .engine import create_detector, create_live_engine
    from .fleet import CameraFleet, FairDetector
    webcam_detector = FairDetector(create_detector(detector_kind, openvino_device))
    live = create_live_engine(controller.settings, webcam_detector) if controller and hasattr(controller, 'settings') else None
    camera_wall = CameraFleet(controller.settings, webcam_detector) if live else None
    backups.fleet = camera_wall

    def database_for(dataset, camera_id=None):
        if camera_id:
            if dataset != 'live' or not camera_wall:
                raise HTTPException(status_code=422, detail='Pilih sumber Kamera live untuk laporan CCTV')
            try:
                return camera_wall.database(camera_id)
            except LookupError:
                raise HTTPException(status_code=404, detail='Kamera tidak ditemukan') from None
        if dataset == 'live':
            if not live:
                raise HTTPException(status_code=409, detail='Engine live tidak tersedia pada mode ini')
            return live.settings.database
        return database

    def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        supplied = credentials.credentials if credentials else request.cookies.get("cctv_session", "") if ui_dir else ""
        if not supplied or not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers['host']}"
            if (origin and origin != expected) or (not credentials and origin != expected):
                raise HTTPException(status_code=403, detail="Origin rejected")

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/pilot/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get('/health')
    def health():
        states = ([live.snapshot()] if live else []) + ([c['engine'] for c in camera_wall.snapshot()['cameras']] if camera_wall else [])
        if any(s.get('unresponsive') for s in states):
            raise HTTPException(status_code=503, detail='Worker unresponsive')
        return {'status': 'ok'}

    @app.get("/pilot/v1/status", dependencies=[Depends(authenticate)])
    def status(dataset: Literal['replay', 'live'] = 'replay', camera_id: str | None = None):
        with closing(Database(database_for(dataset, camera_id), migrate=False)) as db, db.conn:
            db.conn.execute("BEGIN")
            result = snapshot(db, controller, timezone)
            result.update(dataset=dataset, live=live.snapshot() if live else None, live_capture_available=bool(live))
            result['camera_catalog'] = camera_wall.catalog() if camera_wall else []
            result['selected_camera_id'] = camera_id
            result['fleet'] = camera_wall.snapshot() if camera_wall else None
            if camera_id:
                try:
                    result['live'] = camera_wall.get(camera_id).engine.snapshot()
                except LookupError:
                    result['live'] = None
            result['detector'] = {'model': webcam_detector.runtime_label, 'ready': webcam_detector.session is not None, 'runtime': dict(webcam_detector.manifest)}
            if dataset == 'live':
                result['mode'] = 'integrated_live_pilot'
            return result

    @app.post("/pilot/v1/webcam/frame", dependencies=[Depends(authenticate)])
    async def webcam_frame(request: Request):
        if not controller:
            raise HTTPException(status_code=409, detail="Jalankan dashboard untuk memakai engine webcam")
        if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise HTTPException(status_code=415, detail="Frame harus berupa image/jpeg")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 1_000_000:
                raise HTTPException(status_code=413, detail="Frame terlalu besar")
            body.extend(chunk)
        try:
            jpeg_dimensions(body)
            session = request.headers.get('x-live-session')
            if session:
                if not live:
                    raise HTTPException(status_code=409, detail='Engine live tidak tersedia')
                sequence = request.headers.get('x-frame-sequence', '')
                if not sequence.isdecimal() or len(sequence) > 10 or int(sequence) < 1 or len(session) > 80:
                    raise HTTPException(status_code=422, detail='Envelope frame tidak valid')
                return await run_in_threadpool(live.submit, bytes(body), session, int(sequence))
            if live and live.snapshot()['status'] in {'STARTING', 'RUNNING', 'STOPPING'}:
                raise HTTPException(status_code=409, detail='Sesi live sedang memakai engine. Hentikan sesi tersebut atau kirim frame dengan session ID yang aktif.')
            return await run_in_threadpool(webcam_detector.detect, bytes(body))
        except BlockingIOError as error:
            raise HTTPException(status_code=429, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except (FileNotFoundError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except Exception:
            raise HTTPException(status_code=503, detail="Inferensi webcam gagal; periksa model dan runtime Python") from None

    @app.get('/pilot/v1/live', dependencies=[Depends(authenticate)])
    def live_status():
        if not live:
            raise HTTPException(status_code=409, detail='Jalankan dashboard untuk engine live')
        return live.snapshot()

    @app.post('/pilot/v1/live/calibration', dependencies=[Depends(authenticate)])
    def calibration(values: CalibrationInput):
        if not live:
            raise HTTPException(status_code=409, detail='Engine live tidak tersedia')
        try:
            value = values.model_dump()
            source = value.pop('source')
            return live.save_calibration(source, value)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(status_code=422, detail='Kalibrasi tidak valid atau sesi masih aktif. Gunakan polygon sederhana, ID unik, dan aturan dalam batas yang didukung.') from None

    @app.post('/pilot/v1/live/start', status_code=202, dependencies=[Depends(authenticate)])
    def live_start(values: LiveStartInput):
        if not live:
            raise HTTPException(status_code=409, detail='Engine live tidak tersedia')
        try:
            if values.source == 'RTSP_LIVE' and camera_wall:
                from .rtsp import rtsp_camera_key
                if any(c.fingerprint == rtsp_camera_key(values.url or '') and c.engine.snapshot()['status'] in {'STARTING', 'RUNNING', 'STOPPING'} for c in camera_wall._cameras.values()):
                    raise ValueError('Kamera ini sudah dianalisis pada grid multi-kamera')
            return live.start(values.source, values.url, preview_only=values.preview_only, camera_key=values.camera_key)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post('/pilot/v1/live/stop', dependencies=[Depends(authenticate)])
    def live_stop(values: LiveStopInput):
        if not live:
            raise HTTPException(status_code=409, detail='Engine live tidak tersedia')
        try:
            return live.stop(values.session_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.get('/pilot/v1/live/preview.jpg', dependencies=[Depends(authenticate)])
    def live_preview():
        frame = live.preview_jpeg() if live else None
        if not frame:
            raise HTTPException(status_code=404, detail='Frame live belum tersedia atau stale')
        return Response(frame, media_type='image/jpeg')

    def require_wall():
        if not camera_wall:
            raise HTTPException(status_code=409, detail='Jalankan dashboard untuk preview beberapa kamera')
        return camera_wall

    @app.get('/pilot/v1/camera-wall', dependencies=[Depends(authenticate)])
    def wall_status():
        return require_wall().snapshot()

    @app.post('/pilot/v1/camera-wall/cameras', status_code=201, dependencies=[Depends(authenticate)])
    def wall_add(values: PreviewCameraInput):
        try:
            return require_wall().add(values.name, values.url)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.delete('/pilot/v1/camera-wall/cameras/{camera_id}', dependencies=[Depends(authenticate)])
    def wall_remove(camera_id: str):
        try:
            require_wall().remove(camera_id)
            return {'removed': camera_id}
        except LookupError:
            raise HTTPException(status_code=404, detail='Kamera tidak ditemukan') from None

    def managed_action(camera_id, action):
        try:
            require_wall().get(camera_id)
            return action()
        except LookupError:
            raise HTTPException(status_code=404, detail='Kamera tidak ditemukan') from None
        except (ValueError, RuntimeError):
            raise HTTPException(status_code=409, detail='Perintah belum dapat dijalankan. Periksa sesi kamera, kalibrasi, dan penyimpanan.') from None

    @app.post('/pilot/v1/camera-wall/cameras/{camera_id}/calibration', dependencies=[Depends(authenticate)])
    def wall_calibrate(camera_id: str, values: CalibrationInput):
        if values.source != 'RTSP_LIVE':
            raise HTTPException(status_code=422, detail='Sumber harus RTSP')
        value = values.model_dump(exclude={'source'})
        return managed_action(camera_id, lambda: require_wall().calibrate(camera_id, value))

    @app.post('/pilot/v1/camera-wall/cameras/{camera_id}/start', status_code=202, dependencies=[Depends(authenticate)])
    def wall_start(camera_id: str):
        camera = managed_action(camera_id, lambda: require_wall().get(camera_id))
        primary = live.snapshot()
        if primary['status'] in {'STARTING', 'RUNNING', 'STOPPING'} and primary.get('camera_key') == camera.fingerprint:
            raise HTTPException(status_code=409, detail='Hentikan sesi RTSP utama sebelum memulai kamera ini di grid')
        return managed_action(camera_id, lambda: require_wall().start_analysis(camera_id))

    @app.post('/pilot/v1/camera-wall/cameras/{camera_id}/stop', dependencies=[Depends(authenticate)])
    def wall_stop(camera_id: str):
        return managed_action(camera_id, lambda: require_wall().stop_analysis(camera_id))

    @app.post('/pilot/v1/camera-wall/cameras/{camera_id}/recovery', dependencies=[Depends(authenticate)])
    def wall_recovery(camera_id: str, values: CameraRecoveryInput):
        return managed_action(camera_id, lambda: require_wall().configure(camera_id, values.auto_resume))

    @app.get('/pilot/v1/camera-wall/cameras/{camera_id}/observation', dependencies=[Depends(authenticate)])
    def wall_observation(camera_id: str):
        camera = managed_action(camera_id, lambda: require_wall().get(camera_id))
        pair = camera.engine.preview_snapshot()
        if not pair:
            raise HTTPException(status_code=404, detail='Frame analisis baru belum tersedia')
        return {**pair, 'jpeg': base64.b64encode(pair['jpeg']).decode('ascii')}

    @app.post('/pilot/v1/camera-wall/view', dependencies=[Depends(authenticate)])
    def wall_view(values: CameraViewInput):
        try:
            require_wall().subscribe(values.viewer_id, values.camera_ids)
            return {'subscribed': values.camera_ids}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None

    @app.get('/pilot/v1/camera-wall/cameras/{camera_id}/frame.jpg', dependencies=[Depends(authenticate)])
    def wall_frame(camera_id: str):
        frame = require_wall().frame(camera_id)
        if not frame:
            raise HTTPException(status_code=404, detail='Frame baru belum tersedia')
        jpeg, utc_ms, seq = frame
        return Response(jpeg, media_type='image/jpeg', headers={'X-Frame-Time': str(utc_ms), 'X-Frame-Sequence': str(seq)})

    def query(start_utc_us, end_utc_us, run_id, workspace_id, dataset, camera_id=None):
        try:
            with closing(Database(database_for(dataset, camera_id), migrate=False)) as db, db.conn:
                db.conn.execute("BEGIN")
                return dashboard_report(db, start_utc_us, end_utc_us, run_id, workspace_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid report range") from None
        except LookupError:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan") from None

    @app.get("/pilot/v1/reports", dependencies=[Depends(authenticate)])
    def reports(start_utc_us: int | None = None, end_utc_us: int | None = None, run_id: str | None = None, workspace_id: str | None = None, dataset: Literal['replay', 'live'] = 'replay', camera_id: str | None = None):
        return query(start_utc_us, end_utc_us, run_id, workspace_id, dataset, camera_id)

    @app.get("/pilot/v1/export.csv", dependencies=[Depends(authenticate)])
    def export(start_utc_us: int | None = None, end_utc_us: int | None = None, run_id: str | None = None, workspace_id: str | None = None, dataset: Literal['replay', 'live'] = 'replay', camera_id: str | None = None):
        result = query(start_utc_us, end_utc_us, run_id, workspace_id, dataset, camera_id)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["CCTV ENGINE", "identity_source=anonymous", "sources=" + ",".join(result["data_sources"]), "basis=monitoring_window", "schedule_applied=false"])
        writer.writerow(['camera_id', camera_id or 'primary', 'timezone', timezone, 'start_utc_us', result['start_utc_us'], 'end_utc_us', result['end_utc_us']])
        writer.writerow(["workspace_id", "workspace", "occupied_us", "empty_us", "unknown_us", "eligible_us", "utilization", "coverage"])
        for row in result["workstations"]:
            name = row["workspace"]
            if name.lstrip().startswith(("=", "+", "-", "@")):
                name = "'" + name
            writer.writerow([row["workspace_id"], name, *[row[k] for k in ("occupied_us", "empty_us", "unknown_us", "eligible_us", "utilization", "coverage")]])
        return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="cctv-engine-report.csv"'})

    def require_controller():
        if not controller:
            raise HTTPException(status_code=409, detail="API ini hanya baca; jalankan command dashboard untuk replay")

    @app.get('/pilot/v1/maintenance', dependencies=[Depends(authenticate)])
    def maintenance_status():
        return backups.status()

    @app.post('/pilot/v1/maintenance/backup', status_code=202, dependencies=[Depends(authenticate)])
    def maintenance_backup():
        require_controller()
        try:
            return backups.request_backup()
        except ValueError:
            raise HTTPException(status_code=409, detail='Backup masih berjalan') from None

    @app.post('/pilot/v1/maintenance/policy', dependencies=[Depends(authenticate)])
    def maintenance_policy(values: BackupPolicyInput):
        require_controller()
        return backups.configure(values.enabled, values.keep_days)

    @app.post('/pilot/v1/maintenance/backups/{backup_id}/verify', dependencies=[Depends(authenticate)])
    def maintenance_verify(backup_id: str):
        try:
            value = backups.verify(backup_id)
            return {'id': value['id'], 'verified': True, 'files': len(value['files'])}
        except Exception:
            raise HTTPException(status_code=422, detail='Verifikasi backup gagal; berkas rusak, hilang, atau tidak sesuai versi aplikasi') from None

    @app.post("/pilot/v1/replay", status_code=202, dependencies=[Depends(authenticate)])
    def start_replay():
        require_controller()
        try:
            return controller.start()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/pilot/v1/replay/stop", dependencies=[Depends(authenticate)])
    def stop_replay():
        require_controller()
        return controller.stop()

    @app.post("/pilot/v1/employees", status_code=201, dependencies=[Depends(authenticate)])
    def employee(values: EmployeeInput, dataset: Literal['replay', 'live'] = 'replay', camera_id: str | None = None):
        require_controller()
        try:
            with closing(Database(database_for(dataset, camera_id), migrate=False)) as db:
                return {"id": db.add_employee(values.display_name), "source": "manual_registry"}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/pilot/v1/assignments", status_code=201, dependencies=[Depends(authenticate)])
    def assignment(values: AssignmentInput, dataset: Literal['replay', 'live'] = 'replay', camera_id: str | None = None):
        require_controller()
        if values.end_utc_us <= values.start_utc_us:
            raise HTTPException(status_code=422, detail="Akhir assignment harus setelah mulai")
        try:
            with closing(Database(database_for(dataset, camera_id), migrate=False)) as db:
                db.assign(values.employee_id, values.workspace_id, values.start_utc_us, values.end_utc_us)
            return {"status": "saved", "source": "manual_assignment", "is_observed_identity": False}
        except (ValueError, sqlite3.IntegrityError):
            raise HTTPException(status_code=409, detail="Assignment tidak valid atau bertabrakan dengan assignment yang tersimpan") from None

    if ui_dir:
        if not (ui_dir / "index.html").is_file():
            raise ValueError("Dashboard build belum tersedia; jalankan npm.cmd run build di prototype")
        app.mount("/assets", StaticFiles(directory=ui_dir / "assets"), name="dashboard-assets")

        @app.get("/", response_class=HTMLResponse)
        def index(request: Request):
            origin = request.headers.get("origin")
            direct_navigation = request.headers.get("sec-fetch-mode") == "navigate" and request.headers.get("sec-fetch-dest") == "document"
            if (request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} and not direct_navigation) or (origin and origin != f"{request.url.scheme}://{request.headers['host']}"):
                raise HTTPException(status_code=403, detail="Open the dashboard directly on loopback")
            html = (ui_dir / "index.html").read_text(encoding="utf-8").replace("<head>", "<head><script>window.__CCTV_ENGINE__=true;</script>", 1)
            response = HTMLResponse(html, headers={"Cache-Control": "no-store"})
            response.set_cookie("cctv_session", token, httponly=True, samesite="strict", path="/pilot/")
            return response

    return app
