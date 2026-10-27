"""Versioned machine integration API. No dashboard routes or imports."""
import asyncio
from contextlib import asynccontextmanager
import secrets

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool


class CameraInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    camera_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')
    url: str = Field(min_length=1, max_length=2048)


class Calibration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)
    camera_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    zones: list[dict] = Field(min_length=1, max_length=16)
    rules: dict
    position: dict | None = None


def create_app(service, token, *, webhook=None):
    if len(token) < 32:
        raise ValueError('CCTV_HEADLESS_TOKEN must contain at least 32 characters')

    @asynccontextmanager
    async def lifespan(app):
        async def monitor():
            while True:
                try:
                    service.license.check()
                except ValueError:
                    await run_in_threadpool(service.shutdown)
                await asyncio.sleep(1)
        task = asyncio.create_task(monitor())
        delivery = asyncio.create_task(webhook.run(service)) if webhook else None
        try:
            yield
        finally:
            for pending in (task, delivery):
                if pending:
                    pending.cancel()
            await asyncio.gather(*(p for p in (task, delivery) if p), return_exceptions=True)
            await run_in_threadpool(service.shutdown)

    app = FastAPI(title='CCTV Headless Engine', version='1.0.0', docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def authenticated(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(401, 'Unauthorized')
        try:
            service.license.check()
        except ValueError:
            raise HTTPException(403, 'License expired') from None

    auth = [Depends(authenticated)]

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    @app.get('/docs', response_class=HTMLResponse, include_in_schema=False)
    def connection_help():
        from importlib.resources import files
        return HTMLResponse(files('editions.headless').joinpath('connect.html').read_text(encoding='utf-8'), headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({'detail': 'Camera not found'}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        # Avoid reflecting RTSP credentials or native errors to external clients.
        return JSONResponse({'detail': 'Invalid configuration, state, or license limit'}, status_code=409)

    @app.get('/api/v1/openapi.json', dependencies=auth)
    def openapi():
        return app.openapi()

    @app.get('/api/v1/status', dependencies=auth)
    def status():
        return {'edition': 'headless', 'max_cameras': service.license.max_cameras,
                'cameras': service.all_status(), 'scheduler': service.scheduling_snapshot(),
                'onvif': False, 'processed_rtsp_output': False}

    @app.get('/api/v1/cameras', dependencies=auth)
    def cameras():
        return service.all_status()

    @app.post('/api/v1/cameras', status_code=201, dependencies=auth)
    def add_camera(values: CameraInput):
        return service.add(values.camera_id, values.url)

    @app.get('/api/v1/cameras/{camera_id}', dependencies=auth)
    def camera(camera_id: str):
        return service.status(camera_id)

    @app.delete('/api/v1/cameras/{camera_id}', status_code=204, dependencies=auth)
    def delete_camera(camera_id: str):
        service.remove(camera_id)

    @app.put('/api/v1/cameras/{camera_id}/analytics', dependencies=auth)
    def analytics(camera_id: str, values: Calibration):
        try:
            return service.get(camera_id).save_calibration('RTSP_LIVE', values.model_dump())
        except (TypeError, KeyError):
            raise HTTPException(422, 'Invalid calibration') from None

    @app.post('/api/v1/cameras/{camera_id}/start', status_code=202, dependencies=auth)
    def start(camera_id: str, preview_only: bool = False):
        return service.start(camera_id, preview_only)

    @app.post('/api/v1/cameras/{camera_id}/stop', dependencies=auth)
    def stop(camera_id: str):
        return service.get(camera_id).stop()

    @app.get('/api/v1/cameras/{camera_id}/events', dependencies=auth)
    def events(camera_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
        rows = service.events(camera_id, after, limit)
        return {'items': rows, 'next_cursor': rows[-1]['seq'] if rows else after}

    @app.websocket('/api/v1/stream')
    async def stream(socket: WebSocket):
        supplied = socket.headers.get('authorization', '')
        if not secrets.compare_digest(supplied, 'Bearer ' + token):
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            # Latest metadata snapshots, bounded at 5 Hz; durable events use REST cursors.
            while True:
                service.license.check()
                await asyncio.wait_for(socket.send_json({'type': 'camera_metadata', 'cameras': service.all_status()}), timeout=5)
                await asyncio.sleep(0.2)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except ValueError:
            await socket.close(code=1008)

    return app
