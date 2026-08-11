# Known Limitations (v0.1)

The single authoritative list. Everything here is a deliberate scope
boundary or an honestly-reported gap - not a hidden defect. If something
below sounds like it should be fixed, it probably should be, in v0.2+, not
silently worked around now.

## Scope boundaries (by design, not oversight)

- **No perception, no ML inference, no fusion, no ground-truth evaluation,
  no ablation analysis, no NCAP/DMS/OMS-specific logic.** v0.1 is
  ingestion, synchronization, diagnostics, and visualization only - see the
  project's own original scope statement in the README.
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
  not measured under real concurrent load.
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
