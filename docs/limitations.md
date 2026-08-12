# Known Limitations

The single authoritative list. Everything here is a deliberate scope
boundary or an honestly-reported gap - not a hidden defect. If something
below sounds like it should be fixed, it probably should be, in a later
release, not silently worked around now.

## Scope boundaries (by design, not oversight)

- **No perception, no ML inference, no sensor fusion, no causal or
  statistical claims, no NCAP/DMS/OMS-specific logic.** v0.1 was
  ingestion, synchronization, diagnostics, and visualization; v0.2 added
  ground-truth evaluation (classification only - see below); v0.3 added
  configuration comparison (see below) - never a claim about *why* two
  configurations differ, only *that* they measured differently. See the
  project's own original scope statement in the README.
- **Comparison validity does not check matched-label-set divergence.**
  Two configurations whose matched samples span different label sets
  (e.g. one config's matched set never saw the "absent" class) would
  currently not be flagged - this would need confusion-matrix data
  `ComparisonMetrics` doesn't carry. A documented gap, not a silent
  omission - see [comparison.md](comparison.md#comparison-validity).
- **Comparison validity does not check reported-vs-common-set
  divergence.** No threshold has been justified yet for how much a
  reported-mode delta may differ from the common-set-mode delta before
  it's worth flagging - deferred rather than adding an
  under-justified number.
- **A comparison spans exactly one session.** `/compare` never spans
  multiple sessions even if a caller wanted to compare "this
  configuration in session A" against "that configuration in session B"
  - both sides are always evaluated within the same session/task.
- **No comparison history.** Like `/evaluate`, `/compare` recomputes
  fresh on every call and persists nothing - there is no way to see how
  a comparison's numbers looked before underlying evaluation data
  changed, only the current state.
- **`min_common_sample_count` (default 20) and
  `coverage_warning_threshold_pp` (default 5.0) are heuristic, not
  evidence-based** - same honesty treatment as `tolerance_ms`'s default
  (see [comparison.md](comparison.md#comparison-validity)).
- **Evaluation is classification-only (v0.2).** `GroundTruth`/
  `Prediction.value` are intentionally generic dicts (see
  [evaluation.md](evaluation.md#task-values-generic-by-design)), but the
  only metric engine that exists is `evaluate_classification`. Detection/
  regression would be new code beside it, not a schema change - but that
  code doesn't exist yet.
- **`tolerance_ms` for evaluation matching is not evidence-based**, unlike
  the ROS/DDS sync tolerance (see
  [architecture.md](architecture.md#synchronization-measured-not-guessed)).
  Ground truth and predictions can come from entirely different systems
  with no shared clock, so there's no equivalent "real skew" to measure -
  the API default (`100.0`ms) is a starting point to tune per scenario.
- **`/evaluate` is synchronous** - runs on the request thread, no
  background job/queue. Fine at "a few thousand events, single dashboard
  user" scale; would need rework before it could handle much more without
  risking an HTTP timeout.
- **No evaluation result history.** Re-running `/evaluate` for the same
  `(session, configuration, task)` overwrites the previous
  `EvaluationResult` - there is no way to compare "this run" against "the
  run before I changed the model," only the latest.
- **No file-import API endpoint.** Loading
  `examples/evaluation/classification-demo.json` is four ordinary REST
  calls via a script (`scripts/load_demo_data.py`), not a dedicated
  import route - deferred deliberately until a second example file
  actually needs one (see [evaluation.md](evaluation.md#import-format-format_version-10)).
- **One sensor per modality.** Topics are keyed by modality
  (`/multisens/sensors/rgb/image_raw`), not by sensor ID. Two cameras
  sharing a modality collide on the same topic - guarded against with a
  hard, tested launch-time error, not silently broken, but genuinely not
  supported.
- **RTSP only.** `config/sensors.yaml`'s `transport` field exists for
  future extension, but only `"rtsp"` does anything; other values are
  skipped with a logged warning.
- **`/multisens/sync/frames`** (actual grouped/republished synchronized
  frame bundles, as opposed to status *about* synchronization) does not
  exist. Only sync *status* is published.
- **No `sensor_msgs/CameraInfo` data.** The topic contract reserves
  `/multisens/sensors/{modality}/info` for it, but no calibration data
  exists for the simulated reference sensors, and none is fabricated -
  this is unpopulated, not broken.
- **MJPEG relay is one ffmpeg subprocess per connected HTTP client**, not
  fanned out across multiple simultaneous viewers of the same sensor. Each
  browser tab opens its own RTSP connection through the backend. Fine for a
  single dashboard; would need a shared-broadcast redesign for multiple
  concurrent viewers.
- **CORS is wide open** (`allow_origins=["*"]`) on the backend - correct for
  a local-only v0.1 tool with no auth or cookies, wrong for anything
  reachable beyond localhost.
- **No authentication anywhere.**

## Environment-specific assumptions

- **`host.docker.internal`** in the reference `config/sensors.yaml` is a
  Docker-Desktop-for-Mac convenience (confirmed to reach even a
  loopback-bound host service - not guaranteed on other Docker networking
  setups). Portable to Linux/Jetson by changing config values, not code -
  see [architecture.md](architecture.md#portability).
- **`cpu_percent`/`memory_percent`** in system diagnostics are read via
  `psutil` from inside the `ros` container; on Docker Desktop for Mac this
  reflects the Linux VM's overall resource view, not a cgroup-isolated
  per-container figure.
- Developed and verified only on Apple Silicon (M2, 8GB target). Base
  images (`ros:humble-ros-base`) are confirmed multi-arch (arm64/v8
  manifest present), and no code path is architecture-specific - but
  x86_64/Jetson has not been run, only reasoned about.

## Honestly-reported, not yet resolved

- **No CI.** Every "verified" claim in this project's history means someone
  ran it manually and checked the actual output - there is no automated
  regression suite wired into GitHub, so nothing prevents a future change
  from silently breaking something already proven to work once.
- **Memory soak testing is real but time-limited.** See the README's
  soak-test entries for exact sample counts, durations, and any observed
  trends - a short soak can rule out a fast leak, not a slow one. Treat any
  "no leak observed" statement as scoped to the duration actually tested,
  not as a permanent guarantee.
- **No load testing beyond a single dashboard user.** Concurrent-viewer
  behavior for the MJPEG relay (see above) is understood architecturally,
  not measured under real concurrent load. The same applies to the
  evaluation SQLite database (v0.2+): each request opens its own
  connection (`check_same_thread=False`, WAL mode), which is correct for
  sequential per-request access, but genuinely concurrent writes under
  real multi-user load have not been measured, only reasoned about.
- **Frontend has no error boundary** for unexpected render exceptions -
  network/data-shape errors are handled (see `docs/diagnostics.md` and the
  dashboard's own `NO SIGNAL`/`WARN` states), but a genuine React render
  crash would currently blank the page rather than show a fallback UI.

## What would likely break first

- **More sensors (untested beyond 3):** nothing in the architecture assumes
  exactly three, but resource usage (CPU for N ffmpeg decode/encode paths,
  DDS traffic for N image topics) has only been measured at N=3 on one
  machine. Expect to hit host CPU limits before hitting a code limit.
- **Higher resolution (untested beyond 640x480):** the "large image message
  defeats a generic ROS subscriber" problem (see
  [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video))
  gets worse, not better, at 1080p - `image_raw` traffic is already at the
  edge of what a naive subscriber can keep up with at 640x480/30fps.
