"""Authenticated local pilot API and optional same-origin dashboard."""
from contextlib import asynccontextmanager, closing
from pathlib import Path
import csv
import io
import secrets
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field

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


def create_app(database: Path, token: str, *, controller=None, ui_dir: Path | None = None, timezone="Asia/Jakarta"):
    if len(token) < 32:
        raise ValueError("Pilot API requires a local token of at least 32 characters")

    @asynccontextmanager
    async def lifespan(app):
        yield
        if controller:
            controller.shutdown()

    app = FastAPI(title="CCTV local pilot API", version="0.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", *([] if ui_dir else ["testserver"])])
    bearer = HTTPBearer(auto_error=False)

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
    def status():
        with closing(Database(database, migrate=False)) as db, db.conn:
            db.conn.execute("BEGIN")
            return snapshot(db, controller, timezone)

    def query(start_utc_us, end_utc_us, run_id, workspace_id):
        try:
            with closing(Database(database, migrate=False)) as db, db.conn:
                db.conn.execute("BEGIN")
                return dashboard_report(db, start_utc_us, end_utc_us, run_id, workspace_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid report range") from None
        except LookupError:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan") from None

    @app.get("/pilot/v1/reports", dependencies=[Depends(authenticate)])
    def reports(start_utc_us: int | None = None, end_utc_us: int | None = None, run_id: str | None = None, workspace_id: str | None = None):
        return query(start_utc_us, end_utc_us, run_id, workspace_id)

    @app.get("/pilot/v1/export.csv", dependencies=[Depends(authenticate)])
    def export(start_utc_us: int | None = None, end_utc_us: int | None = None, run_id: str | None = None, workspace_id: str | None = None):
        result = query(start_utc_us, end_utc_us, run_id, workspace_id)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
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
    def employee(values: EmployeeInput):
        require_controller()
        try:
            with closing(Database(database, migrate=False)) as db:
                return {"id": db.add_employee(values.display_name), "source": "manual_registry"}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/pilot/v1/assignments", status_code=201, dependencies=[Depends(authenticate)])
    def assignment(values: AssignmentInput):
        require_controller()
        if values.end_utc_us <= values.start_utc_us:
            raise HTTPException(status_code=422, detail="Akhir assignment harus setelah mulai")
        try:
            with closing(Database(database, migrate=False)) as db:
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
