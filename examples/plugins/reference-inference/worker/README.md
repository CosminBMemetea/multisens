# yolo-worker

The v1.0-RC (issue #123) reference inference worker: a standalone
process, deliberately **not** a MultiSens plugin (no `entry_points`,
never installed into the backend image). Opens its own independent
RTSP connection to one sensor - the same "N independent readers of one
RTSP source" pattern `backend/app/video_relay.py` and
`ros2_ws`'s `rtsp_ingestion_node` already establish - runs YOLOv8n
(car/truck/bus/motorcycle, confidence threshold 0.40, matching the real
one-shot RideSafe experiment this reproduces live), and serves its
latest detection over a small local HTTP endpoint.

## Install and run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../../worker-kit  # multisens-worker-kit (issue #141) - local path, not on PyPI
pip install -r requirements.txt
python3 -m yolo_worker \
  --rtsp-url rtsp://host.docker.internal:8554/ridesafe_front_rgb \
  --sensor-id ridesafe_front_rgb \
  --port 9100
```

CLI flags (`python3 -m yolo_worker --help`):

| Flag | Default | Meaning |
|---|---|---|
| `--rtsp-url` | *(required)* | Same RTSP source the ROS ingestion node reads |
| `--sensor-id` | *(required)* | Reported in `/latest`/`/health` - match a `config/sensors.yaml` entry id |
| `--host` | `0.0.0.0` | HTTP bind address |
| `--port` | `9100` | HTTP bind port - the bridge plugin's `worker_url` must point here |
| `--model` | `yolov8n.pt` | Any ultralytics-compatible weights path/name |
| `--confidence-threshold` | `0.40` | Matches the real RideSafe one-shot experiment |

## HTTP contract

**`GET /latest`**

```json
{
  "sensor_id": "ridesafe_front_rgb",
  "frame_timestamp_ms": 1734294821123.456,
  "detections": [
    {"label": "car", "confidence": 0.87, "bbox": {"x": 0.12, "y": 0.34, "width": 0.20, "height": 0.15}}
  ]
}
```

`frame_timestamp_ms` is this worker's own wall-clock reading at
frame-read time - not a true RTSP/source capture timestamp. Documented
at the same honesty tier `docs/topics.md` already holds ROS's
`frame_stamp` to (issue #123) - no better timestamp exists anywhere in
this pipeline to inherit. `bbox` is already normalized to `[0, 1]` and
clamped to the frame - the exact shape
`backend/app/domain/detection.py`'s `BoundingBox` requires.

**`GET /health`**

```json
{"status": "ok", "sensor_id": "ridesafe_front_rgb", "frames_processed": 812, "last_frame_age_s": 0.31, "last_error": null}
```

`status` is `"starting"` until the first frame has been processed, then
`"ok"` - this worker never distinguishes further states of its own; the
bridge plugin's own `health()` (backend-facing) derives `DEGRADED`/
`FAILED` from HTTP reachability and response shape, not from this field.

## Process isolation, verified

Killing this process (`Ctrl+C`, `kill`, or a crash inside
torch/ultralytics/opencv) leaves the MultiSens backend, Sessions, and
Dashboard completely unaffected - the bridge plugin's `poll()` simply
starts raising until the worker is reachable again (isolated by
`PredictionConnectorInstance._poll_raw()`, backend-side). Restarting
this process recovers independently - no backend restart needed.

## Test without ultralytics/opencv installed

`detections.py`/`state.py`/`server.py` have zero dependency on `cv2`/
`ultralytics` (only `capture.py` and `__main__.py` import them) - the
pure-logic test suite runs without `requirements.txt` installed at all:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../../worker-kit  # multisens-worker-kit - local path, not on PyPI
pip install -e .[testing]
pytest tests/
```
