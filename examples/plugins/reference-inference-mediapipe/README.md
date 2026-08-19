# multisens-reference-inference-mediapipe

A third sibling reference live-inference pair, alongside
`reference-inference` (YOLOv8n vehicle detection) and
`reference-inference-emotion` (FER+ facial emotion), demonstrating the
exact same two-process architecture wired to a third, independently-
developed model family: MediaPipe face detection.

```
        RTSP source                 MultiSens backend process
        (live webcam)                        |
             |                                |
             v                                |
  +------------------------+   HTTP    +------+---------------------+
  | worker/ (own process)   | <-------- | multisens_reference_       |
  | opencv + mediapipe      | GET       | inference_mediapipe.bridge:|
  | face detect (multi)     |  /latest  | MediaPipeBridgeConnector    |
  | blaze_face_short_range  |           | (zero ML dependency)        |
  +------------------------+           +-----------------------------+
```

**Why two processes, not one plugin:** identical reasoning to the
sibling packages - a native-level crash inside opencv/mediapipe must
never take down the REST API/Sessions/Evaluation/Dashboard. The worker
is the only thing that can crash that way; restarting it recovers
independently, no backend restart needed.

## What this proves

`multisens_reference_inference_mediapipe/bridge.py` imports **only**
`multisens_sdk`, `urllib.request`/`json`/`time`, and the standard
library (see `tests/test_boundary.py`) - never `cv2` or `mediapipe`.
Combined with the two sibling packages, this is the concrete
demonstration that MultiSens's `PredictionConnector` architecture
generalizes to a *third*, independently-developed model family with
**zero core changes** - and that this worker's own code needed no
duplicated `state.py`/`server.py`/`log.py` at all, thanks to
`worker-kit/` (issue #141).

It also proves **multiple independent inference producers on one
sensor**: this bridge and the emotion bridge can both be wired to the
same RGB sensor at once (see `config/sensors.yaml`'s own
`inference_connectors:` list) - two completely separate `PollRunner`
threads, two completely separate worker processes, neither aware the
other exists.

## A real environment finding

`mediapipe==1.0.1` crashes on this project's own reference macOS/Apple
Silicon development machine - see `worker/README.md` and
`worker/mediapipe_worker/capture.py`'s own module docstring for the
full reproduction. `worker/requirements.txt` pins `mediapipe==0.10.21`
instead.

## Run the worker

Against a live webcam sensor already ingesting (e.g. `laptop_rgb` from
`config/sensors.yaml`) - see `worker/README.md` for the model download
step:

```bash
cd examples/plugins/reference-inference-mediapipe/worker
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../../worker-kit
pip install -r requirements.txt
python3 -m mediapipe_worker \
  --rtsp-url rtsp://host.docker.internal:8554/laptop_rgb \
  --sensor-id laptop_rgb \
  --model mediapipe_worker/model/blaze_face_short_range.tflite \
  --port 9400
```

`GET http://localhost:9400/latest` and `GET http://localhost:9400/health`
are now live. See `worker/README.md` for the full CLI reference.

## Install and configure the bridge plugin

```bash
pip install ./sdk
pip install ./examples/plugins/reference-inference-mediapipe
```

Then, in `config/sensors.yaml`:

```yaml
inference_connectors:
  - id: laptop_rgb_face_detector
    plugin: multisens.reference.inference.mediapipe_bridge
    config:
      sensor_id: laptop_rgb
      modality: rgb
      worker_url: http://localhost:9400
      task: face_detection    # optional - defaults to 'face_detection'
      timeout_s: 2.0
      stale_after_s: 5.0
    poll_interval_s: 1.0
```

Same staleness-vs-errors discipline as the sibling bridges (issue #127)
- see their own READMEs for the full explanation, unchanged here.

## Develop and test the bridge plugin standalone

```bash
cd examples/plugins/reference-inference-mediapipe
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../sdk
pip install -e .[testing]
pytest tests/
```
