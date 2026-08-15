# multisens-reference-inference

The v1.0-RC (issue #123) reference live-inference pair: a genuinely
separate **inference worker** process that owns the actual model, and a
**thin bridge plugin** (this package) that polls it and turns its
output into canonical `Prediction` rows MultiSens ingests exactly like
any other connector.

```
        RTSP source                 MultiSens backend process
             |                              |
             v                              |
  +----------------------+   HTTP    +------+-------------------+
  | worker/ (own process)| <-------- | multisens_reference_      |
  | ultralytics + cv2     | GET      | inference.bridge:         |
  | YOLOv8n car/truck/bus/|  /latest | YoloBridgeConnector        |
  | motorcycle @ conf 0.40|          | (zero ML dependency)       |
  +----------------------+          +----------------------------+
```

**Why two processes, not one plugin:** a native-level crash inside
torch/ultralytics/opencv must never take down the REST API/Sessions/
Evaluation/Dashboard (v1.0-RC architecture review). The worker is the
only thing that can crash that way, and killing it leaves the backend,
Sessions, and Dashboard completely unaffected - restarting it recovers
independently, with no backend restart needed.

## What this proves

`multisens_reference_inference/bridge.py` imports **only**
`multisens_sdk`, `urllib.request`/`json`/`time`, and the standard
library - see `tests/test_boundary.py` for the automated check. It
never imports `cv2` or `ultralytics`.

## Run the worker

From a MultiSens checkout, against a real sensor already ingesting
(e.g. `ridesafe_front_rgb` from `config/sensors.yaml`):

```bash
cd examples/plugins/reference-inference/worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m yolo_worker --rtsp-url rtsp://host.docker.internal:8554/ridesafe_front_rgb --sensor-id ridesafe_front_rgb --port 9100
```

`GET http://localhost:9100/latest` and `GET http://localhost:9100/health`
are now live. See `worker/README.md` for the full CLI reference.

## Install and configure the bridge plugin

```bash
pip install ./sdk
pip install ./examples/plugins/reference-inference
```

Then, in `config/sensors.yaml`:

```yaml
inference_connectors:
  - id: vehicles_front
    plugin: multisens.reference.inference.yolo_bridge
    config:
      sensor_id: ridesafe_front_rgb
      modality: rgb           # must match this sensor's own declared modality
      worker_url: http://localhost:9100
      task: vehicle_detection # optional - defaults to 'vehicle_detection'
    poll_interval_s: 1.0
```

Restart the backend (`docker compose restart backend`, or rebuild if
installing into the image) - starting a session now starts this
connector too (v1.0-RC issue #122's session-bound wiring), and
`GET /api/inference-connectors` shows it.

## Develop and test the bridge plugin standalone

No MultiSens checkout, Docker, or ROS required - only Python and pip
(and no `ultralytics`/`cv2` either - the bridge never imports them):

```bash
cd examples/plugins/reference-inference
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../sdk
pip install -e .[testing]
pytest tests/
```
