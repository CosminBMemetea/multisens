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
from app.config import (
    load_disabled_plugin_ids,
    load_inference_connectors,
    load_poll_connectors,
    load_resource_collectors,
    load_sensors,
)
from app.domain.resources import SUPPORTED_RESOURCE_METRICS
from app.persistence import db as db_module
from app.plugins import state as plugin_state
from app.plugins.manager import (
    build_connector_instances,
    build_inference_connector_instances,
    build_poll_runners,
    build_resource_collector_instances,
    stop_connector_instances,
    stop_inference_connectors,
    stop_poll_runners,
    stop_resource_collection,
)
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
    # Same for prediction/ground-truth poll connectors (v0.9 bug hunt,
    # issue #110) - previously never wired at all, so an installed
    # plugin of either type would discover as AVAILABLE and then never
    # actually poll anything.
    plugin_state.poll_runners = build_poll_runners(load_poll_connectors(), plugin_state.plugin_registry)
    # Resource collectors are constructed here (v0.9.1, issue #111) but
    # deliberately never configured/started - unlike poll_runners above,
    # they're session-bound, not process-bound. api/sessions.py's
    # start_session/complete_session configure/start/stop them per
    # session; see app/plugins/manager.py's own module docstring.
    plugin_state.resource_collectors = build_resource_collector_instances(
        load_resource_collectors(), plugin_state.plugin_registry,
    )
    # Same session-bound-not-process-bound construction for background
    # inference (v1.0-RC, issue #122) - see manager.py's own module
    # docstring for why this mirrors resource collectors, not poll_runners.
    plugin_state.inference_connectors = build_inference_connector_instances(
        load_inference_connectors(), plugin_state.plugin_registry,
    )

    yield
    stop_poll_runners(plugin_state.poll_runners)
    stop_connector_instances(plugin_state.connector_instances)
    # Any session still RUNNING at shutdown has live collection attached -
    # stop every one of them (never just the most recent), same "no
    # orphan background threads" requirement as poll_runners above. The
    # Session rows themselves are untouched here (still 'running' in the
    # database) - see docs/resources.md's own restart-semantics note:
    # collection does not claim continuity across backend downtime.
    for runners in plugin_state.resource_collection_runners.values():
        stop_resource_collection(runners)
    plugin_state.resource_collection_runners = {}
    for runners in plugin_state.inference_connector_runners.values():
        stop_inference_connectors(runners)
    plugin_state.inference_connector_runners = {}
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


@app.get('/api/resource-metrics')
def resource_metrics() -> list[str]:
    """The current, possibly plugin-extended, `SUPPORTED_RESOURCE_METRICS`
    vocabulary (v0.9 bug hunt, issue #116) - read-only, matching
    /api/plugins's own registry-visibility pattern. Lets the frontend
    request whatever this running backend actually supports instead of
    hardcoding the original six built-in metrics, which would silently
    exclude anything a `RESOURCE_COLLECTOR` plugin adds at discovery
    time (app/domain/resources.py's own register_resource_metrics())."""
    return sorted(SUPPORTED_RESOURCE_METRICS)


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
