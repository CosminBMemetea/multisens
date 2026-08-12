"""MultiSens backend: the browser-facing API boundary.

REST for config/sensor list and one-shot status; WebSocket for live
status/diagnostics/sync (pushed from the ROS bridge's translated snapshot,
never a raw ROS message); a per-sensor MJPEG endpoint for video, entirely
independent of ROS (see video_relay.py for why).
"""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.config import load_sensors
from app.persistence import db as db_module
from app.ros_bridge import RosBridge
from app.video_relay import mjpeg_stream

WS_PUSH_INTERVAL_SEC = 0.5

bridge = RosBridge()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bridge.start()
    # Opens the evaluation DB and applies any pending migration. No route
    # uses it yet (that's Phase 12) - wiring it into startup now means a
    # real path/permission/migration problem surfaces at container boot,
    # not silently on the first evaluation-API call in a later phase.
    app.state.db = db_module.connect(db_module.get_db_path())
    yield
    app.state.db.close()
    bridge.shutdown()


app = FastAPI(title='MultiSens Backend', lifespan=lifespan)

# Frontend and backend are separate containers/ports (browser reaches both
# via host-published ports), so REST calls from the dashboard are
# cross-origin. Wide open is a deliberate choice for v0.1: this is a
# local-only dev tool with no auth and no cookies/credentials involved, so
# there's nothing a permissive origin list actually exposes. Revisit before
# this is ever reachable from anywhere but localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['GET'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/api/sensors')
def sensors() -> list[dict]:
    return load_sensors()


@app.get('/api/status')
def status() -> dict:
    return bridge.snapshot()


@app.get('/api/sensors/{sensor_id}/stream.mjpeg')
def sensor_stream(sensor_id: str) -> Response:
    sensors_by_id = {s['id']: s for s in load_sensors()}
    if sensor_id not in sensors_by_id:
        return JSONResponse(status_code=404, content={'error': f"unknown sensor '{sensor_id}'"})
    return StreamingResponse(
        mjpeg_stream(sensors_by_id[sensor_id]['url']),
        media_type='multipart/x-mixed-replace; boundary=ffmpeg',
    )


@app.websocket('/ws/status')
async def ws_status(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(bridge.snapshot())
            await asyncio.sleep(WS_PUSH_INTERVAL_SEC)
    except WebSocketDisconnect:
        pass
