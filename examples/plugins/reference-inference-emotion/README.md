# multisens-reference-inference-emotion

A sibling reference live-inference pair to `reference-inference` (the
RideSafe YOLOv8n vehicle-detection one), demonstrating the exact same
two-process architecture wired to a completely different model and
sensor. **Not a driver-monitoring system, not an NCAP/DMS compliance
claim, not a clinical or psychological assessment of emotion** - a
pretrained model's classification, for architecture demonstration only.

```
        RTSP source                 MultiSens backend process
        (live webcam)                        |
             |                                |
             v                                |
  +------------------------+   HTTP    +------+---------------------+
  | worker/ (own process)   | <-------- | multisens_reference_       |
  | opencv + onnxruntime    | GET       | inference_emotion.bridge:  |
  | face detect + FER+      |  /latest  | EmotionBridgeConnector      |
  | 8-class @ conf 0.40     |           | (zero ML dependency)        |
  +------------------------+           +-----------------------------+
```

**Why two processes, not one plugin:** identical reasoning to the
sibling package - a native-level crash inside opencv/onnxruntime must
never take down the REST API/Sessions/Evaluation/Dashboard. The worker
is the only thing that can crash that way; restarting it recovers
independently, no backend restart needed.

## What this proves

`multisens_reference_inference_emotion/bridge.py` imports **only**
`multisens_sdk`, `urllib.request`/`json`/`time`, and the standard
library (see `tests/test_boundary.py`) - never `cv2` or `onnxruntime`.
Combined with the sibling `reference-inference` package, this is the
concrete demonstration that MultiSens's `PredictionConnector`
architecture is genuinely model- and sensor-agnostic: everything from
the session lifecycle down through the evaluator and Evidence Playback
needed **zero changes** to support a completely different task.

## Run the worker

Against a live webcam sensor already ingesting (e.g.
`emotion_demo_face_rgb` from `config/sensors.yaml`):

```bash
cd examples/plugins/reference-inference-emotion/worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m emotion_worker --rtsp-url rtsp://host.docker.internal:8554/emotion_demo_face --sensor-id emotion_demo_face_rgb --port 9200
```

`GET http://localhost:9200/latest` and `GET http://localhost:9200/health`
are now live. See `worker/README.md` for the full CLI reference.

## Install and configure the bridge plugin

```bash
pip install ./sdk
pip install ./examples/plugins/reference-inference-emotion
```

Then, in `config/sensors.yaml`:

```yaml
inference_connectors:
  - id: emotion_demo_detector
    plugin: multisens.reference.inference.emotion_bridge
    config:
      sensor_id: emotion_demo_face_rgb
      modality: rgb
      worker_url: http://localhost:9200
      task: facial_emotion    # optional - defaults to 'facial_emotion'
      timeout_s: 2.0
      stale_after_s: 5.0
    poll_interval_s: 1.0
```

Same staleness-vs-errors discipline as the sibling bridge (issue #127) -
see its own README for the full explanation, unchanged here.

## Develop and test the bridge plugin standalone

```bash
cd examples/plugins/reference-inference-emotion
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../sdk
pip install -e .[testing]
pytest tests/
```
