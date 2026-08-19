# emotion-worker

A sibling reference inference worker to `yolo_worker`
(`examples/plugins/reference-inference/worker/`), demonstrating that
MultiSens's background-inference architecture is genuinely
model-agnostic. Same shape: a standalone process, deliberately **not**
a MultiSens plugin, opens its own independent RTSP connection to one
sensor, serves its latest detection over a small local HTTP endpoint.

**Not a driver-monitoring system, not an NCAP/DMS compliance claim, not
a clinical or psychological assessment of emotion** - a pretrained
model's classification, wired through the exact same architecture as
the RideSafe vehicle-detection demo, for architecture demonstration
only.

**Pipeline**: OpenCV's bundled Haar cascade face detector (ships with
`opencv-python` itself, no separate download) finds the largest face in
frame, then the [`emotion-ferplus`](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus)
ONNX model (Microsoft/ONNX Model Zoo, 8-class, 64x64 grayscale input)
classifies it via `onnxruntime` on CPU. Confidence threshold 0.40, same
default as the vehicle-detection demo, for direct comparability.

## Install and run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m emotion_worker \
  --rtsp-url rtsp://host.docker.internal:8554/emotion_demo_face \
  --sensor-id emotion_demo_face_rgb \
  --port 9200
```

CLI flags (`python3 -m emotion_worker --help`):

| Flag | Default | Meaning |
|---|---|---|
| `--rtsp-url` | *(required)* | Same RTSP source the ROS ingestion node reads |
| `--sensor-id` | *(required)* | Reported in `/latest`/`/health` - match a `config/sensors.yaml` entry id |
| `--host` | `0.0.0.0` | HTTP bind address |
| `--port` | `9200` | HTTP bind port - the bridge plugin's `worker_url` must point here |
| `--model` | bundled `emotion-ferplus-8.onnx` | Any `emotion-ferplus`-compatible ONNX weights path |
| `--confidence-threshold` | `0.40` | Matches the vehicle-detection reference demo's own default |

## HTTP contract

Identical shape to `yolo_worker`'s own contract - `detections` is a
0-or-1-length list (at most one face classified per frame; this is a
single-subject reference demo, not a multi-face system).

**`GET /latest`**

```json
{
  "sensor_id": "emotion_demo_face_rgb",
  "frame_timestamp_ms": 1734294821123.456,
  "detections": [
    {"label": "happiness", "confidence": 0.85, "bbox": {"x": 0.30, "y": 0.20, "width": 0.30, "height": 0.40}}
  ]
}
```

`frame_timestamp_ms` is this worker's own wall-clock reading at
frame-read time - not a true RTSP/source capture timestamp, same
honesty tier as `yolo_worker`'s own contract. `bbox` is normalized to
`[0, 1]` and clamped to the frame.

**`GET /health`**

```json
{"status": "ok", "sensor_id": "emotion_demo_face_rgb", "frames_processed": 812, "last_frame_age_s": 0.31, "last_error": null}
```

## Process isolation, verified

Same isolation guarantee as `yolo_worker`: killing this process leaves
the MultiSens backend, Sessions, and Dashboard completely unaffected -
the bridge plugin's `poll()` simply starts raising until the worker is
reachable again. Restarting this process recovers independently - no
backend restart needed.

## Test without opencv/onnxruntime installed

`detections.py`/`state.py`/`server.py` have zero dependency on `cv2`/
`onnxruntime` (only `capture.py` and `__main__.py` import them):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[testing]
pytest tests/
```
