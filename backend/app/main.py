"""MultiSens backend: the browser-facing API boundary.

REST for config/sensor list and one-shot status; WebSocket for live
status/diagnostics/sync (pushed from the ROS bridge's translated snapshot,
never a raw ROS message); a per-sensor MJPEG endpoint for video, entirely
independent of ROS (see video_relay.py for why).
"""
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import load_sensors
from app.ros_bridge import RosBridge
from app.video_relay import mjpeg_stream

WS_PUSH_INTERVAL_SEC = 0.5

app = FastAPI(title='MultiSens Backend')
bridge = RosBridge()


@app.on_event('startup')
def on_startup():
    bridge.start()


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/sensors')
def sensors():
    return load_sensors()


@app.get('/api/status')
def status():
    return bridge.snapshot()


@app.get('/api/sensors/{sensor_id}/stream.mjpeg')
def sensor_stream(sensor_id: str):
    sensors_by_id = {s['id']: s for s in load_sensors()}
    if sensor_id not in sensors_by_id:
        return JSONResponse(status_code=404, content={'error': f"unknown sensor '{sensor_id}'"})
    return StreamingResponse(
        mjpeg_stream(sensors_by_id[sensor_id]['url']),
        media_type='multipart/x-mixed-replace; boundary=ffmpeg',
    )


@app.websocket('/ws/status')
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(bridge.snapshot())
            await asyncio.sleep(WS_PUSH_INTERVAL_SEC)
    except WebSocketDisconnect:
        pass
