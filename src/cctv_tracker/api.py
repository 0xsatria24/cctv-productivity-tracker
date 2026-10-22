"""Authenticated local pilot API and optional same-origin dashboard."""
from contextlib import asynccontextmanager, closing
from pathlib import Path
import csv
import io
import secrets
import sqlite3
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Query
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
    camera_id: str | None = Field(default=None, min_length=1, max_length=80)
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


def create_app(database: Path, token: str, *, controller=None, ui_dir: Path | None = None, timezone="Asia/Jakarta", detector_kind='yolox', openvino_device='GPU'):
    if len(token) < 32:
        raise ValueError("Pilot API requires a local token of at least 32 characters")

    @asynccontextmanager
    async def lifespan(app):
        if detector_kind == 'yolox-openvino':
            import cv2
            import numpy as np
            await run_in_threadpool(webcam_detector.detect, cv2.imencode('.jpg', np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes())
        yield
        if camera_wall:
            camera_wall.shutdown()
        if live:
            live.shutdown()
        if controller:
            controller.shutdown()

    app = FastAPI(title="CCTV local pilot API", version="0.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", *([] if ui_dir else ["testserver"])])
    bearer = HTTPBearer(auto_error=False)
    from .webcam import jpeg_dimensions
    from .engine import create_detector, create_live_engine
    webcam_detector = create_detector(detector_kind, openvino_device)
    live = create_live_engine(controller.settings, webcam_detector) if controller and hasattr(controller, 'settings') else None
    from .camera_wall import CameraWall
    camera_wall = CameraWall(controller.settings) if live else None

    def database_for(dataset):
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

    @app.get("/pilot/v1/status", dependencies=[Depends(authenticate)])
    def status(dataset: Literal['replay', 'live'] = 'replay'):
        with closing(Database(database_for(dataset), migrate=False)) as db, db.conn:
            db.conn.execute("BEGIN")
            result = snapshot(db, controller, timezone)
            result.update(dataset=dataset, live=live.snapshot() if live else None, live_capture_available=bool(live))
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
            url = values.url
            if values.camera_id:
                if values.source != 'RTSP_LIVE' or values.url:
                    raise HTTPException(status_code=422, detail='Pilih satu sumber RTSP dari daftar kamera.')
                url = require_wall().source_url(values.camera_id)
            return live.start(values.source, url, preview_only=values.preview_only, camera_key=values.camera_key)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
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
    def live_preview(frame_seq: int | None = Query(None, ge=1), run_id: str | None = Query(None, max_length=64)):
        frame = live.preview_frame(frame_seq, run_id) if live else None
        if not frame:
            raise HTTPException(status_code=404, detail='Frame live belum tersedia atau stale')
        return Response(frame[0], media_type='image/jpeg', headers=frame[1])

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

    def query(start_utc_us, end_utc_us, run_id, workspace_id, dataset):
        try:
            with closing(Database(database_for(dataset), migrate=False)) as db, db.conn:
                db.conn.execute("BEGIN")
                return dashboard_report(db, start_utc_us, end_utc_us, run_id, workspace_id, timezone=timezone)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid report range") from None
        except LookupError:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan") from None

    @app.get("/pilot/v1/reports", dependencies=[Depends(authenticate)])
    def reports(start_utc_us: int | None = None, end_utc_us: int | None = None, run_id: str | None = None, workspace_id: str | None = None, dataset: Literal['replay', 'live'] = 'replay'):
        return query(start_utc_us, end_utc_us, run_id, workspace_id, dataset)

    @app.get("/pilot/v1/export.csv", dependencies=[Depends(authenticate)])
    def export(start_utc_us: int | None = None, end_utc_us: int | None = None, run_id: str | None = None, workspace_id: str | None = None, dataset: Literal['replay', 'live'] = 'replay', daily: bool = False):
        result = query(start_utc_us, end_utc_us, run_id, workspace_id, dataset)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        if daily:
            writer.writerow(["CCTV DAILY", "timezone=" + timezone, "identity_source=anonymous", "basis=monitoring_window", "schedule_applied=false", "sources=" + ",".join(result["data_sources"])])
            fields = ["date", "workspace_id", "workspace", "occupied_us", "empty_us", "unknown_us", "eligible_us", "coverage", "utilization", "first_seen_utc_us", "last_seen_utc_us", "start_utc_us", "end_utc_us", "provisional", "partial_day"]
            writer.writerow(fields)
            for row in result["daily"]:
                writer.writerow([("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value) for value in (row[key] for key in fields)])
            return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="cctv-daily-report.csv"'})
        writer.writerow(["CCTV ENGINE", "identity_source=anonymous", "sources=" + ",".join(result["data_sources"]), "basis=monitoring_window", "schedule_applied=false"])
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
    def employee(values: EmployeeInput, dataset: Literal['replay', 'live'] = 'replay'):
        require_controller()
        try:
            with closing(Database(database_for(dataset), migrate=False)) as db:
                return {"id": db.add_employee(values.display_name), "source": "manual_registry"}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/pilot/v1/assignments", status_code=201, dependencies=[Depends(authenticate)])
    def assignment(values: AssignmentInput, dataset: Literal['replay', 'live'] = 'replay'):
        require_controller()
        if values.end_utc_us <= values.start_utc_us:
            raise HTTPException(status_code=422, detail="Akhir assignment harus setelah mulai")
        try:
            with closing(Database(database_for(dataset), migrate=False)) as db:
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
