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

from app.api.comparison import router as comparison_router
from app.api.evaluation import router as evaluation_router
from app.api.plugins import router as plugins_router
from app.api.profiles import router as profiles_router
from app.api.scenarios import router as scenarios_router
from app.api.sessions import router as sessions_router
from app.config import load_disabled_plugin_ids, load_sensors
from app.persistence import db as db_module
from app.plugins import state as plugin_state
from app.plugins.manager import build_connector_instances
from app.plugins.registry import PluginStatus, discover_plugins
from app.ros_bridge import RosBridge
from app.video_relay import mjpeg_stream

WS_PUSH_INTERVAL_SEC = 0.5

bridge = RosBridge()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    bridge.start()
    # Opens the evaluation DB just to apply any pending migration, then
    # closes it - request handlers open their own short-lived connection
    # (see app/api/deps.py) rather than sharing this one. Still means a
    # real path/permission/migration problem surfaces at container boot,
    # not on the first evaluation-API call.
    db_module.connect(db_module.get_db_path()).close()

    plugin_state.plugin_registry = discover_plugins(disabled_plugin_ids=load_disabled_plugin_ids(), ros_bridge=bridge)
    by_status = {status: 0 for status in PluginStatus}
    for record in plugin_state.plugin_registry.records.values():
        by_status[record.status] += 1
    # print(), not the logging module - this project has no logging
    # subsystem anywhere else; print() is the established convention for
    # an operator-visible startup diagnostic (see ros2_ws's own
    # sensor_config.py). Per-plugin non-AVAILABLE reasons are already
    # printed individually by registry.py's own discovery code.
    print(
        f'plugin discovery: {by_status[PluginStatus.AVAILABLE]} available, '
        f'{by_status[PluginStatus.INCOMPATIBLE]} incompatible, '
        f'{by_status[PluginStatus.LOAD_FAILED]} load_failed, '
        f'{by_status[PluginStatus.DISABLED]} disabled'
    )
    # Trusted-code model, not sandboxed - stated at every load, not just
    # in docs, so it's visible in the container's own boot log. See
    # docs/plugin-sdk.md#trust-model.
    third_party = [r for r in plugin_state.plugin_registry.available() if r.distribution_name != 'multisens']
    if third_party:
        print(
            f'loaded {len(third_party)} third-party plugin(s) '
            f'({", ".join(r.plugin_id for r in third_party)}) - trusted-code model, '
            f'see docs/plugin-sdk.md#trust-model'
        )

    # config-driven connector wiring (v0.9, Phase 102) - see
    # app/plugins/manager.py's own module docstring for why this only
    # ever runs once, here, and never through a mutation API.
    plugin_state.connector_instances = build_connector_instances(load_sensors(), plugin_state.plugin_registry)

    yield
    for instance in plugin_state.connector_instances.values():
        try:
            instance.stop()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code, must never block shutdown
            print(f"connector shutdown: sensor '{instance.sensor_id}' failed to stop cleanly: {e}")
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
    allow_methods=['GET', 'POST'],
    allow_headers=['*'],
)

app.include_router(scenarios_router)
app.include_router(sessions_router)
app.include_router(evaluation_router)
app.include_router(comparison_router)
app.include_router(profiles_router)
app.include_router(plugins_router)


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
