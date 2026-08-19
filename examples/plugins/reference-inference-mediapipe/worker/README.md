# mediapipe-worker

A third sibling reference inference worker, alongside `yolo_worker`
(`examples/plugins/reference-inference/worker/`) and `emotion_worker`
(`examples/plugins/reference-inference-emotion/worker/`) - proof that
MultiSens's background-inference architecture generalizes to a third,
independently-developed model family with zero core changes. Same
shape: a standalone process, deliberately **not** a MultiSens plugin,
opens its own independent RTSP connection to one sensor, serves its
latest detection over a small local HTTP endpoint.

Unlike its two siblings, this package has no local `state.py`/
`server.py`/`log.py` at all - it depends directly on
`multisens-worker-kit` (issue #141) from the start, the concrete payoff
of extracting that shared toolkit before adding a third model family.

**Pipeline**: MediaPipe Tasks API `FaceDetector`
([`blaze_face_short_range`](https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite),
Google's own pretrained model bundle) - multi-face, unlike the emotion
worker's deliberate single-face scope. Detection only, no classification
- a face's *emotion* is a completely separate model (`emotion_worker`),
never conflated here.

## A real environment finding (issue #142)

`mediapipe==1.0.1` (latest at time of writing) crashes with a fatal
`Check failed: service_ Service is unavailable` inside
`TensorsToDetectionsCalculator` on this project's own reference
development machine (macOS/Apple Silicon) - reproduced twice, including
with the CPU delegate explicitly forced, so it is not a GPU-opt-out
problem. `requirements.txt` pins `mediapipe==0.10.21` instead, verified
working end to end before this package was written. See
`mediapipe_worker/capture.py`'s own module docstring for the full
reproduction notes.

## Install and run

The `.tflite` model is never committed or auto-downloaded - same "don't
commit model weights" convention as `yolov8n.pt`/`emotion-ferplus-8.onnx`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../../worker-kit  # multisens-worker-kit (issue #141) - local path, not on PyPI
pip install -r requirements.txt
curl -sL -o mediapipe_worker/model/blaze_face_short_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite
python3 -m mediapipe_worker \
  --rtsp-url rtsp://host.docker.internal:8554/laptop_rgb \
  --sensor-id laptop_rgb \
  --model mediapipe_worker/model/blaze_face_short_range.tflite \
  --port 9400
```

CLI flags (`python3 -m mediapipe_worker --help`):

| Flag | Default | Meaning |
|---|---|---|
| `--rtsp-url` | *(required)* | Same RTSP source the ROS ingestion node reads |
| `--sensor-id` | *(required)* | Reported in `/latest`/`/health` - match a `config/sensors.yaml` entry id |
| `--host` | `0.0.0.0` | HTTP bind address |
| `--port` | `9400` | HTTP bind port - the bridge plugin's `worker_url` must point here |
| `--model` | *(required)* | Path to `blaze_face_short_range.tflite` - no bundled default |
| `--confidence-threshold` | `0.50` | MediaPipe's own default detection-score threshold |
| `--target-inference-fps` | `10.0` | Caps the detect rate - `0` disables the cap |

## HTTP contract

Identical shape to `yolo_worker`'s/`emotion_worker`'s own contract -
`detections` here can have more than one entry (multi-face), unlike
`emotion_worker`'s 0-or-1.

**`GET /latest`**

```json
{
  "sensor_id": "laptop_rgb",
  "frame_timestamp_ms": 1734294821123.456,
  "detections": [
    {"label": "face", "confidence": 0.91, "bbox": {"x": 0.32, "y": 0.27, "width": 0.34, "height": 0.45}}
  ]
}
```

`frame_timestamp_ms` is this worker's own wall-clock reading at
frame-read time - not a true RTSP/source capture timestamp, same
honesty tier as the sibling workers' own contract. `bbox` is normalized
to `[0, 1]` and clamped to the frame.

**`GET /health`**

```json
{"status": "ok", "sensor_id": "laptop_rgb", "frames_processed": 812, "last_frame_age_s": 0.31, "last_error": null}
```

## Process isolation, verified

Same isolation guarantee as the sibling workers: killing this process
leaves the MultiSens backend, Sessions, Dashboard, and any other
inference connector on the same sensor (YOLO, emotion) completely
unaffected - the bridge plugin's `poll()` simply starts raising until
the worker is reachable again. Restarting this process recovers
independently - no backend restart, no other worker restart needed.

## Test without opencv/mediapipe installed

`detections.py` has zero dependency on `cv2`/`mediapipe` (only
`capture.py`/`__main__.py` import them):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../../worker-kit  # multisens-worker-kit - local path, not on PyPI
pip install -e .[testing]
pytest tests/
```
