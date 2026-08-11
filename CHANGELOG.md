# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Every entry below was verified against a running system, not just a passing
build — that's a project-wide rule, not editorial flourish; see
[docs/development.md](docs/development.md) for how.

## [0.1.0] — v0.1 release

Built phase by phase (Phase 0 through Phase 9). Ingestion, synchronization,
diagnostics, and a dashboard — no perception, fusion, ML, or ground-truth
evaluation, by design (see [docs/limitations.md](docs/limitations.md)).

### Added

- **Config-driven RTSP ingestion** (`config/sensors.yaml`): one generic
  `rtsp_ingestion_node`, instantiated N times from config — no per-sensor
  code. Adding a sensor is a config entry.
- **ROS 2 Humble in Docker** (`ros` container, arm64), cross-process and
  cross-*container* DDS pub/sub verified live, not assumed.
- **Per-sensor self-reported diagnostics** (`connection_state`,
  `fps_received`, `reconnect_count`, etc.) and **global system diagnostics**
  (CPU/RAM/uptime/connected count), both on `/multisens/diagnostics`. Every
  field is real or explicitly `"unavailable"` — see
  [docs/diagnostics.md](docs/diagnostics.md).
- **Cross-sensor timestamp synchronization** (`multisens_sync`) via
  `message_filters.ApproximateTimeSynchronizer` over a lightweight
  `sensor_msgs/TimeReference` companion topic (`frame_stamp`) rather than
  the full image topic — see the throughput bug below for why. Default
  `tolerance_ms=25.0` set from measured real skew (0.2–3.5ms baseline on the
  reference setup), not guessed.
- **FastAPI backend** (`backend` container, separate from `ros`): REST +
  WebSocket bridge translating ROS diagnostics into plain JSON
  (`ros_bridge.py` is the only file that imports a ROS message type), plus
  an independent MJPEG video relay (ffmpeg `mpjpeg` muxer) that never
  touches ROS/DDS.
- **React/TypeScript/Vite/Tailwind dashboard** (`frontend` container,
  joined `docker-compose.yml` only once there was a UI to serve): live
  video panels, PHYSICAL/SIMULATED badges, sync/system health.
- **Disconnect/reconnect handling**: per-node RTSP reconnect loop, verified
  under a real single-sensor outage (not just "kill everything at once").
- **ROS process respawn** (`respawn=True` on every launch `Node`): recovers
  from a *process* crash, not just a dropped RTSP connection.
- **Backend stale-data expiry**: `/api/status` excludes any sensor/system/
  sync entry not updated in the last 5s, rather than repeating frozen data
  forever.
- **Automated tests**: frontend (Vitest), backend (pytest against a real
  `RosBridge`/FastAPI `TestClient`, no live ROS graph needed), and ROS
  pure-logic (`sensor_config.py`, `sync_logic.py` — zero rclpy imports,
  plain pytest). Deliberately not a full ROS/RTSP mock — see
  [docs/development.md](docs/development.md).
- Standing docs: `docs/architecture.md`, `docs/topics.md`,
  `docs/configuration.md`, `docs/diagnostics.md`, `docs/connector-api.md`,
  `docs/development.md`, `docs/limitations.md`.

### Fixed

Real bugs found during verification, not just features shipped clean:

- **Sync node measuring its own processing lag, not real skew.**
  Subscribing directly to `image_raw` (~900KB/frame) made
  `synchronized_group_rate_hz` sit near 0–3Hz against a true ~30Hz rate,
  with reported skew swinging 1ms–460ms — an artifact of the subscriber
  falling behind, not sensor behavior. A multi-threaded executor only
  partially helped (CPython's GIL doesn't parallelize CPU-bound
  deserialization). Fixed by adding the `frame_stamp` companion topic
  (header only, no pixels) for the sync node to subscribe to instead.
- **`message_filters` silently matching nothing.** The first attempt at
  the lightweight topic used a bare `std_msgs/Header`, which produced
  exactly 0 synchronized groups, ever, with no error —
  `ApproximateTimeSynchronizer` reads `msg.header.stamp`, which needs a
  *nested* header. Switched to `sensor_msgs/TimeReference`.
- **System diagnostics double-counting itself.** `system_diagnostics_node`
  subscribed to the same topic it publishes to, received its own "system"
  status back, and briefly reported `connected_sensor_count: 4` against a
  `total_sensor_count: 3`. Fixed by filtering to known sensor hardware_ids
  only.
- **Backend showing a dead sensor as alive forever.** With an ingestion
  node's *process* killed (not just its RTSP source), `/api/status` kept
  reporting it `"connected"` with a frozen-fresh `fps_received` — nothing
  was ever going to arrive to correct it, and `ros_bridge.py` was the one
  place that hadn't replicated the staleness-watchdog pattern already used
  in `system_diagnostics_node`/`sync_status_node`. Fixed with a 5s
  staleness expiry in `RosBridge.snapshot()`.
- **No recovery path for a process-level crash.** A killed ingestion node
  stayed dead forever — its own reconnect loop only covers the RTSP
  *connection* dying, not its own process dying. Fixed with `respawn=True`
  on every launch `Node` (ROS 2 launch's own mechanism).
- **Frontend rendering `"unavailablems"`.** Sync offsets and per-sensor
  latency/last-frame-age fields string-concatenated the `"unavailable"`
  sentinel with a hardcoded `"ms"` suffix, because the original code only
  checked JS truthiness. Fixed once with a shared `formatMs()` helper.
- **`ROS_DOMAIN_ID`/`RMW_IMPLEMENTATION` duplication.** Previously hardcoded
  separately in `ros2_ws/Dockerfile` and `docker-compose.yml`. Single-sourced
  in a repo-root `.env`, referenced by both services.
- **Dead historical launch files and placeholder nodes** (`phase1_graph.launch.py`,
  `phase2_rgb.launch.py`, `placeholder_talker.py`, `placeholder_listener.py`)
  removed during the v0.1 release audit — kept during development as
  harmless artifacts, not appropriate to ship.
- **Simulator-specific default baked into a "generic" node.**
  `rtsp_ingestion_node`'s `rtsp_url` parameter defaulted to
  `rtsp://host.docker.internal:8554/rgb` — a host- and simulator-specific
  value with no business being a default in a node meant to work with any
  RTSP source. Now required explicitly, fails clearly if missing.
- **`ros2_ws` image shipping build-only tooling.** `python3-colcon-common-extensions`
  (needed to *build* the workspace, not to run it) was present in the final
  image. Converted to a multi-stage build; the runtime stage never installs
  it. Also dropped `--symlink-install` for the production build — a
  self-contained `install/` is more correct for a distributed image than
  symlinks pointing back into a `src/` tree the final image no longer ships.
  Measured, not assumed: this made almost no difference to final image size
  (490,318,679 → 490,321,039 bytes, effectively unchanged) — the image's
  real weight is `ros-humble-cv-bridge`'s opencv-dev dependency chain, a
  genuine runtime need, not colcon tooling. Kept for correctness (no
  dangling-symlink risk in a shipped image, cleaner build/runtime
  separation), reported honestly as not a size win.
- **Frontend sensor list never retried.** `GET /api/sensors` was fetched
  once on mount; if the backend wasn't ready yet at page load, the
  dashboard would show "failed to load" forever without a manual reload,
  even though the WebSocket itself reconnects fine. Now refetches whenever
  the WebSocket (re)connects.
- **`video_relay.py` subprocess lifecycle hardening.** Added `stdin=DEVNULL`
  and explicit `stdout.close()` on the ffmpeg subprocess — not a known bug,
  but tightens a real gap found during the release audit.
- **Deprecated FastAPI startup hook.** `@app.on_event('startup')` replaced
  with the `lifespan` context manager, which also now calls
  `rclpy.shutdown()` on backend shutdown (previously nothing did).
- **TypeScript `strict` mode was never actually enabled** in the default
  Vite-generated `tsconfig.app.json` — the code happened to already be
  strict-clean, so turning it on was a zero-cost gap closure, not a fix
  requiring code changes.

### Known limitations

See [docs/limitations.md](docs/limitations.md) for the full, current list —
scope boundaries, environment-specific assumptions, and honestly-reported
gaps (no CI, soak testing is real but time-bounded, single-dashboard-user
scale only).
