# multisens-worker-kit

Small, dependency-free toolkit shared by [MultiSens](https://github.com/CosminBMemetea/multisens)
reference inference worker processes - the standalone OS processes a
`PredictionConnector` bridge polls over HTTP (see
`docs/plugin-sdk.md` in the main repository, and the `reference-inference*`
example plugins). Not a MultiSens plugin itself: no `entry_points`, never
installed into the backend image, and not depended on by any
`PredictionConnector` bridge - only by worker processes.

## The protocol

Every worker built on this package serves two endpoints from a
`multisens_worker_kit.state.SharedState` (a lock-guarded "latest finished
frame" snapshot, updated by the worker's own capture/inference loop):

- `GET /latest` -> `{"sensor_id": ..., "frame_timestamp_ms": ... | null, "detections": [...]}`
- `GET /health` -> `{"status": "ok" | "starting", "sensor_id": ..., "frames_processed": ..., "last_frame_age_s": ... | null, "last_error": ... | null}`

`frame_timestamp_ms` is `null` and `status` is `"starting"` until the
first frame has actually been processed - never a fabricated zero.

## Usage

```python
from multisens_worker_kit.state import SharedState
from multisens_worker_kit.server import serve
from multisens_worker_kit.log import make_logger

log = make_logger('my_worker')
state = SharedState(sensor_id='my_sensor')
# ... a capture/inference thread calls state.record_frame(...)/record_error(...) ...
server = serve(state, host='0.0.0.0', port=9300)
server.serve_forever()
```

## Why this exists

The reference YOLO and emotion workers had byte-identical `state.py`/
`server.py`/`log.py` (only docstrings differed) - deliberately
duplicated rather than shared, on the reasoning that each worker should
be a genuinely standalone, independently-installable process. That
reasoning holds at two workers; it's exactly the "one plugin per model
won't scale" problem, applied to the worker side, once a third worker
enters the picture. This package is dependency-free and doesn't touch
model code, so depending on it doesn't compromise a worker's standalone
process isolation - the same reasoning that already makes `multisens-sdk`
a shared dependency of every bridge without anyone calling that a
violation of plugin independence.
