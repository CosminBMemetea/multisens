# MultiSens

Open-source, vendor-neutral platform for ingesting, synchronizing, and
visualizing heterogeneous sensor streams (RGB, depth, thermal, and beyond),
with an eye toward later perception evaluation, sensor ablation, and
ground-truth comparison. Built to work identically whether a stream comes
from a webcam-based simulator, a real sensor, or an OEM gateway — no
vendor-specific or dataset-specific code lives in this repo.

## Status: what's actually running vs. what's designed but not built

| Phase | What it delivers | Status |
|---|---|---|
| 0 — Environment & architecture | Container topology, ROS message strategy, video/control-plane split reviewed and decided | ✅ Done |
| 1 — ROS graph boots in Docker | `ros` container builds on `ros:humble-ros-base` (arm64), boots a two-node graph, cross-process DDS pub/sub verified live (not just node discovery — actual message delivery watched via `ros2 topic echo`) | ✅ Done |
| 2 — RGB RTSP → ROS image topic | One real sensor, real frames | ✅ Done |
| 3 — Generalize ingestion (RGB+depth+thermal from config) | One node type, N instances from `config/sensors.yaml`, no per-sensor code | ✅ Done |
| 4 — Diagnostics | Per-sensor self-reported diagnostics + global system diagnostics, both real | ✅ Done |
| 5 — Synchronization | Real cross-sensor skew measurement, missing/stale detection | ✅ Done |
| 6 — Backend API/bridge | REST + WebSocket bridge, independent MJPEG video relay, separate container | ✅ Done |
| 7 — Web dashboard | Live React dashboard, three video panels, sync/system health, frontend container joins compose | ✅ Done |
| 8 — Robustness (disconnect/reconnect) | — | ⬜ Not started |
| 9 — Docs & v0.1 release | — | ⬜ Not started |

Tracked as GitHub issues, one per phase — see [Issues](https://github.com/CosminBMemetea/multisens/issues)
for what's open vs. closed right now; this table is a snapshot, the issue
tracker is the live source of truth.

No CI is configured yet. Nothing here has been claimed as verified without
actually running it — see each phase's closing issue comment for exactly
what was checked and how.

## Architecture, in brief

- **ROS 2 Humble** is the internal metadata/synchronization/diagnostics layer.
  It never carries pixels to the browser — DDS-transporting raw video across
  containers at 30fps would be real CPU load on the 8GB-class machines this
  targets. ROS's job is timing, identity, and health, not video delivery.
- **RTSP is the integration boundary.** One generic, configuration-driven
  ingestion component — never three hardcoded sensor implementations. Adding
  a fourth sensor is a `config/sensors.yaml` entry, not a code change.
- **Video reaches the browser independently of ROS**: the backend opens its
  own RTSP connection (same config, same URLs) and relays MJPEG over HTTP —
  simple, no signaling/ICE complexity, and the video path works even if ROS
  is down. Measured evidence this is the right call, not just a guess: a
  generic `rclpy` subscriber to a single 640x480 `bgr8` image topic
  (~900KB/frame) could not keep up with the true 30fps publish rate in this
  setup — publish-side stayed a steady 30fps throughout, the drop was on a
  second, independent subscriber trying to consume the same raw stream.
- **No custom ROS messages.** `sensor_msgs/Image`, `sensor_msgs/CameraInfo`,
  and `diagnostic_msgs/DiagnosticArray` cover everything needed for v0.1;
  `DiagnosticArray`'s `KeyValue` list carries modality/source_type/fps/offset
  fields that don't have a dedicated standard message field.
- **PHYSICAL vs. SIMULATED is a hard distinction, always labeled.** The
  reference sensor simulator ([`rtspmultistream`](https://github.com/CosminBMemetea/multirtsp))
  produces one real RGB feed from a webcam and two synthetic depth/thermal
  visualizations derived from it via FFmpeg's `pseudocolor` filter — those are
  never presented as physical depth or temperature measurements, in the ROS
  graph, diagnostics, or UI.

Full phase-by-phase development log lives in the issue tracker; each closed
issue documents what was actually verified for that phase, not just what was
attempted.

## Running Phase 7 (current)

Start the sensor simulator on the host first (separate repo:
[`multirtsp`](https://github.com/CosminBMemetea/multirtsp)):

```bash
mediamtx ./mediamtx.yml     # from the multirtsp checkout
./stream_macos.sh           # from the multirtsp checkout
```

Then:

```bash
docker compose build
docker compose up -d
docker compose ps               # ros, backend, and frontend should all show "healthy"
open http://localhost:8080      # the dashboard
```

`docker compose down` stops all three cleanly (~8s, verified).

`ingestion.launch.py` reads `config/sensors.yaml` (mounted read-only into the
container) and instantiates one `rtsp_ingestion_node` per entry — the node
itself didn't need to change from Phase 2, since sensor identity was already
fully parameterized. Verified end to end, not just "three topics exist":
pulled a real frame from each of `/multisens/sensors/{rgb,depth,thermal}/image_raw`
and scored colorfulness (mean `|R-G|+|G-B|+|R-B|` per pixel) — rgb scored 36
(a face against a mostly neutral wall), depth scored 372 and thermal scored
334 (the `pseudocolor` `turbo`/`heat` presets are visibly, measurably applied,
not passthrough grayscale). `source_type` was read back via `ros2 param get`
for all three nodes and matches config exactly (`physical` for rgb,
`simulated` for depth/thermal). The launch file also validates the config
before launching anything: two sensors declaring the same modality (which
would silently collide on the same topic) is a hard launch-time error, tested
directly by feeding it a broken config.

Depth/thermal reconnect behavior (killing the simulator) was covered
end-to-end for rgb in Phase 2's node — same code path, not re-verified per
modality here since it's the same node type.

The Phase 1/2 launch files (`phase1_graph.launch.py`, `phase2_rgb.launch.py`)
are still in the package, unused by the container's default entrypoint —
harmless historical artifacts, not dead weight worth deleting yet.

### Diagnostics (Phase 4)

Every `rtsp_ingestion_node` self-publishes its own status on
`/multisens/diagnostics` (`diagnostic_msgs/DiagnosticArray`, one
`DiagnosticStatus` per publish) every second: `connection_state`,
`fps_received`, `fps_expected` (from the new optional `expected_fps` field in
`config/sensors.yaml`), `resolution`, `encoding`, `frames_received`,
`last_frame_age_ms`, `reconnect_count`, `publish_latency_ms`, `source_type`,
`modality`. `frames_dropped` is always reported as `"unavailable"` rather than
a fabricated `0` — OpenCV's FFmpeg backend doesn't expose RTP-level loss
stats through a simple API, and claiming zero drops would be a metric this
system hasn't actually measured.

Per-sensor diagnostics are self-reported rather than computed by a separate
node watching the image topics, on purpose: only the ingestion node itself
genuinely knows `connection_state`, `reconnect_count`, and true
resolution/encoding — a passive external subscriber could only guess at
those from message arrival gaps, which the "don't fabricate metrics" rule
in this project rules out.

A separate `multisens_diagnostics` package/node publishes *global*
diagnostics on the same topic every 2s — `cpu_percent`, `memory_percent`,
`uptime_sec`, `connected_sensor_count`, `total_sensor_count`, and
`sync_health` (`"unavailable"`, honestly — Phase 5 doesn't exist yet, so
there is nothing to measure). This is separate because no single sensor owns
host resource usage or "how many sensors are connected total." Note:
`cpu_percent`/`memory_percent` are read via `psutil` from inside the
container on Docker Desktop for Mac, which reflects the Linux VM's overall
view, not a cgroup-isolated per-container figure — a real, honestly-labeled
measurement, just not perfectly scoped; worth revisiting if this ever runs
under a container runtime with proper cgroup accounting.

Verified end to end, including a bug this caught: the system node's first
version subscribed to the same `/multisens/diagnostics` topic it publishes
to, so it received its own "system" status back and miscounted it as a 4th
connected sensor (`connected_sensor_count: 4` with `total_sensor_count: 3`
— caught by actually reading the field values, not just checking the topic
existed). Fixed by only counting hardware_ids that are actual configured
sensors. After the fix: killed the RTSP source, confirmed all three sensors
flip to `connection_state: disconnected` / diagnostic level `ERROR`,
`fps_received: 0.0`, and `last_frame_age_ms` growing correctly, while
`system` correctly reports `0/3 configured sensors connected`. Restarted the
source and confirmed full recovery with `reconnect_count` incrementing to
`1` on all three nodes and `system` back to `3/3`.

### Synchronization (Phase 5)

`multisens_sync` publishes `diagnostic_msgs/DiagnosticArray` on
`/multisens/sync/status` every second: per-sensor `offset_ms_{modality}`
(each sensor's timestamp offset from the group's mean), `max_skew_ms`,
`synchronized_group_rate_hz`, `missing_sensors`, `stale_sensors`, and the
configured `tolerance_ms`. Uses `message_filters.ApproximateTimeSynchronizer`
— ROS's standard mechanism for matching messages across topics by timestamp
proximity — instead of hand-rolled frame-matching logic. Compares each
sensor's ROS *publish* timestamp, not a source capture timestamp, since
RTSP/H.264 doesn't reliably provide one across independently read streams.

Two real bugs found and fixed during verification, both by actually reading
the numbers rather than trusting the implementation looked right:

1. Subscribing directly to the `image_raw` topics (~900KB/frame) made
   `synchronized_group_rate_hz` sit near 0-3Hz against a true ~30Hz sensor
   rate, with matched skew swinging wildly (1ms to 460ms) — an artifact of
   the sync node's own processing lag, not real sensor skew. Adding a
   multi-threaded executor only partially helped, because CPython's GIL
   means threads don't parallelize CPU-bound message deserialization. Fixed
   properly: `rtsp_ingestion_node` now also publishes `sensor_msgs/TimeReference`
   on a new `/multisens/sensors/{modality}/frame_stamp` topic — same header,
   no pixel payload — and the sync node subscribes to that instead.
2. First attempt at the lightweight topic used a bare `std_msgs/Header`,
   which produced exactly 0 synchronized groups, ever, with no error.
   `message_filters`' synchronizers read `msg.header.stamp` internally,
   which needs a message with a *nested* header — a bare `Header` only has
   `.stamp` directly. Switched to `sensor_msgs/TimeReference`, a small
   standard message that does carry a real header.

After both fixes: `synchronized_group_rate_hz` sits at a genuine ~30Hz, and
measured `max_skew_ms` across repeated samples was consistently 0.2-3.5ms
(tighter than the illustrative 7ms figure sometimes used as a rule of thumb
for this kind of setup) — expected, since all three streams originate from
one physical camera and one `ffmpeg` process. The default `tolerance_ms`
(25.0) was set from that measurement, not guessed: roughly 7-100x the
observed baseline jitter, tight enough to mean something, loose enough not
to false-positive on normal variation. Verified failure handling too: killed
the RTSP source and confirmed `stale_sensors: rgb,depth,thermal`, level
`ERROR`, `synchronized_group_rate_hz: 0.0`, and every offset/skew field
explicitly `"unavailable"` rather than displaying stale numbers; restarted
the source and confirmed full recovery (skew settled back to ~0.1ms).

`system_diagnostics_node`'s `sync_health` field (previously a standing
`"unavailable"` placeholder, since Phase 5 didn't exist when Phase 4 was
built) now subscribes to `/multisens/sync/status` and reports the real
current level (`ok`/`warn`/`error`) instead.

`/multisens/sync/frames` (actual grouped/republished synchronized frame
bundles, as opposed to status about synchronization) remains out of scope
for v0.1, as originally planned.

### Backend API/bridge (Phase 6)

New `backend` service — a genuinely separate container from `ros`, per the
Phase 0 topology decision. FastAPI app with an embedded `rclpy` node running
in a background thread (kept off the async event loop, since `rclpy.spin()`
blocks). REST:

- `GET /api/health` — plain liveness check
- `GET /api/sensors` — the parsed `config/sensors.yaml`
- `GET /api/status` — current diagnostics/sync snapshot as translated JSON
- `GET /api/sensors/{id}/stream.mjpeg` — live MJPEG video for one sensor

WebSocket `/ws/status` pushes the same translated snapshot every 500ms.
"Translated" is the operative word: `ros_bridge.py` is the only place in the
backend that imports a ROS message type — `DiagnosticStatus`/`KeyValue` get
flattened into a plain dict there, once, and every REST/WebSocket handler
only ever touches that plain dict. The browser (once Phase 7 exists) will
never see a ROS message shape.

Video is a completely separate path from ROS, exactly as designed in Phase 0:
`video_relay.py` opens its own RTSP connection directly (verified against a
live stream before writing any server code) using ffmpeg's `mpjpeg` muxer,
which natively produces a correctly-framed `multipart/x-mixed-replace`
stream — proxied to the HTTP client as raw bytes, no manual JPEG
frame-boundary parsing. One ffmpeg subprocess per connected client, started
on request and terminated on disconnect; verified no orphaned processes
accumulate across repeated requests. Not fanned out across multiple
simultaneous viewers of the same sensor — acceptable for a single-dashboard
v0.1, documented as a known limit rather than silently scaling badly.

Two things resolved for real in this phase, not just designed for:

- **The `ROS_DOMAIN_ID`/`RMW_IMPLEMENTATION` duplication** flagged back in
  Phase 1 (hardcoded separately in `ros2_ws/Dockerfile` and
  `docker-compose.yml`) is now genuinely fixed: both live once, in a
  repo-root `.env` file, referenced by both `ros` and `backend` via
  `${VAR}` substitution in `docker-compose.yml`. The `ros2_ws/Dockerfile`'s
  hardcoded `ENV` lines were removed.
- **Cross-*container* DDS discovery**, deferred all the way from the Phase 0
  review (Phase 1 only proved DDS worked *within* one container) — verified
  for real here: `backend`'s `rclpy` node, running in an entirely separate
  container, correctly discovers and receives `/multisens/diagnostics` and
  `/multisens/sync/status` from the `ros` container. `curl localhost:8000/api/status`
  returns live per-sensor and sync data with no special DDS configuration
  beyond the already-shared `ROS_DOMAIN_ID`/`RMW_IMPLEMENTATION`.

Also verified directly: the WebSocket pushes live-updating data (checked via
a scripted client, not just "the endpoint exists"); the MJPEG endpoint
returns correct headers (`multipart/x-mixed-replace; boundary=ffmpeg`) and
real JPEG frame bytes; requesting a nonexistent sensor's stream returns a
clean `404` instead of a crash; `backend` correctly waits for `ros` to be
healthy before starting (`depends_on: condition: service_healthy`).

### Web dashboard (Phase 7)

React + TypeScript + Vite + Tailwind, built and served via nginx in its own
`frontend` container — the frontend joining `docker-compose.yml` for the
first time, exactly as agreed back in Phase 0 (deliberately not carried as
an empty container through Phases 1-6). Dark technical dashboard per the
original design brief: top bar with a LIVE indicator tied to the WebSocket's
actual connection state, a three-panel sensor grid (video + name + modality
+ PHYSICAL/SIMULATED badge + FPS + resolution + connection state + last-frame
age + reconnect count + latency), a sync health panel, and a system health
panel. Only the Dashboard page exists, as scoped for v0.1 - no other nav
items.

All calls happen from the browser directly to the backend's host-published
port (`http://localhost:8000`), not container-to-container - the frontend
container only ever serves static files, so there's no proxy configuration
or build-time coupling between the two containers. Added CORS
(`allow_origins=["*"]`) to the backend for this: a deliberate choice for a
local-only v0.1 dev tool with no auth or cookies, not something to carry
into any future deployment reachable from beyond localhost.

Verified with real browser automation (Playwright driving headless
Chromium), not just "the build succeeded" - screenshotted the dashboard
against the live stack multiple times through this phase, including:

- A clean `docker compose up` from scratch, all three services reaching
  `healthy` in the correct dependency order.
- Real video rendering in all three panels (not placeholders) - confirmed
  via `img.naturalWidth`/`naturalHeight`/`.complete` in the page, then
  visually: RGB shows the actual webcam feed, depth and thermal show their
  distinct `turbo`/`heat` pseudocolor renderings.
- **A genuine disconnect/reconnect cycle reflected correctly in the UI**:
  killed the simulator's capture process and confirmed all three cards
  flip to `DISCONNECTED` with a `NO SIGNAL` placeholder (not a broken-image
  icon - the `<img>` tag is only mounted when `connection_state ===
  "connected"`), `fps: 0.0`, growing `last frame` age, sync panel flips to
  `ERROR` with every offset explicitly `unavailable`, and system health
  correctly reports `0/3` connected. Restarted the simulator and confirmed
  full recovery, with `reconnects: 1` visible on every sensor card - an
  honest count of what actually happened during this test session, not a
  static zero.

Two real bugs found from that failure-state screenshot, not from reading the
diff:

1. **A transient but real startup race**: right after a clean `docker compose
   up`, one snapshot showed `SYSTEM HEALTH: WARN, connected 0/3` while every
   individual sensor card already showed `CONNECTED`. Traced this to real
   DDS-discovery timing across the `ros` → `backend` container boundary -
   `system_diagnostics_node` genuinely hadn't received any per-sensor OK
   status yet at that instant. Confirmed via direct `curl` that it
   self-corrects within seconds as discovery completes. Concluded this is
   *correct* behavior, not a bug to suppress: showing a brief, accurate WARN
   during real startup is exactly what this project's "never silently drop
   diagnostics problems" principle calls for - hiding it would be the
   actual bug.
2. **A real rendering bug**: the disconnected-state screenshot showed sync
   offsets as literally `"unavailablems"` - string-concatenating the
   `"unavailable"` sentinel value with a hardcoded `"ms"` suffix, because the
   original code only checked JS truthiness (`"unavailable"` is a non-empty,
   truthy string) rather than checking for that specific sentinel. Same bug
   existed in three places (`SyncHealthPanel`'s offsets and max skew,
   `SensorCard`'s last-frame-age and latency). Fixed once with a shared
   `formatMs()` helper (`frontend/src/format.ts`) instead of patching each
   call site separately, then re-verified against a real disconnected state
   that it now renders `unavailable` correctly, with no unit suffix.

Also observed and *not* fixed, because it isn't a bug: `fps_received`
briefly read 99-111 (well over the declared 30fps) in one snapshot taken
seconds after a fresh page load spawned three new concurrent MJPEG relay
connections to the same RTSP source the ROS ingestion nodes were already
reading - the same backlog-catch-up burst pattern already documented in
Phase 2, confirmed here to settle back to ~30fps within a few seconds via
direct polling. Real, measured, transient, self-correcting - not clamped or
hidden.

## Requirements

- Docker Desktop (tested with 6GB RAM / 7 CPU allocated to the VM)
- For local sensor simulation: [`rtspmultistream`](https://github.com/CosminBMemetea/multirtsp)
  (separate repo — the RTSP endpoints are the integration boundary; this repo
  has no dependency on how they're produced)
- Nothing else on the host — the frontend builds entirely inside its Docker
  multi-stage build (Node only exists in the intermediate build stage, not
  the final nginx image). Node/npm locally is only useful for faster
  iteration (`cd frontend && npm run dev`), never required for `docker
  compose up`.

## License

Apache-2.0 — see [LICENSE](LICENSE).
