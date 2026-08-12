# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Every entry below was verified against a running system, not just a passing
build — that's a project-wide rule, not editorial flourish; see
[docs/development.md](docs/development.md) for how.

## [0.2.0] — v0.2 evaluation core

Built phase by phase (Phase 10 through Phase 19), same discipline as
v0.1: explicit self-review checkpoints per phase, nothing merged without
running against a real container. Adds an evaluation layer entirely
inside the existing `backend` container — no new service, no v0.1
behavior changed. Full domain model, algorithm, and API reference:
[docs/evaluation.md](docs/evaluation.md).

### Added

- **Evaluation domain model** (`backend/app/domain/models.py`): `Session`,
  `Scenario`, `GroundTruth`, `Prediction`, `EvaluationResult` as plain
  Pydantic models with zero `fastapi`/`sqlite3`/`rclpy` imports.
  `GroundTruth`/`Prediction.value` is a generic dict, not a
  classification-specific field, so detection/regression can reuse the
  same shape later without a schema rewrite. `configuration_id` is
  derived from sorted `sensor_ids`, never chosen independently, which
  keeps sensor identity (`sensor_ids`) and prediction-source identity
  (`source_id`) from ever collapsing into one field.
- **SQLite persistence** behind a repository boundary
  (`backend/app/persistence/`) — plain versioned `.sql` migrations, no
  migration framework, for five tables. Backed by a named Docker volume
  (`backend-data`), survives a container rebuild.
- **Prediction/ground-truth ingestion API**: scenario/session CRUD,
  `POST .../ground-truth/batch` and `.../predictions/batch` with
  per-item partial-failure reporting (one malformed item doesn't reject
  an otherwise-valid batch), a primary-key-collision fallback for
  retried/duplicate ids.
- **Matching + classification metric engine**
  (`backend/app/domain/matching.py`, `metrics.py`): sorted two-pointer
  timestamp association within a configurable tolerance; accuracy,
  macro/micro precision/recall/F1, and a dynamically-labeled confusion
  matrix (never hardcoded to binary). An unavailable metric (zero
  denominator) is always `None`/`N/A`, never a fabricated `0.0` — the
  rule most likely to get silently violated, so it's tested at every
  layer: engine, API, and frontend formatter.
- **Evaluation API**: `POST .../evaluate` (discovers configurations from
  ingested predictions when not named explicitly, persists one
  `EvaluationResult` per configuration), `GET .../evaluation`, and
  `GET .../timeline` (per-sample correct/incorrect/missing/unmatched
  detail, computed fresh on every call rather than persisted — the
  aggregate result stays a pure aggregate).
- **Sessions and Session Detail UI** (`frontend/src/pages/`), routed with
  `react-router-dom` (the only new frontend dependency this release):
  session list with a working create-session form, scenario/
  configuration/data-coverage sections, a comparison table, a dynamic
  confusion matrix, and a lightweight timeline strip — all derived from
  real API data, nothing hardcoded.
- **Synthetic reference demo**
  (`examples/evaluation/classification-demo.json`,
  `scripts/generate_demo_data.py`, `scripts/load_demo_data.py`): 100
  deterministic ground-truth samples, three prediction configurations at
  exact-by-construction accuracies (90%/83%/87%) landing in visibly
  different bands. Every layer marks itself synthetic — API metadata,
  scenario tags, and a standing amber banner on the session detail page —
  so it can never be mistaken for a real measurement. Cross-checked by a
  backend test that independently recomputes expected accuracy from the
  raw JSON in plain Python (no `app.domain` import) against a real
  `POST /evaluate` response.
- **108 new backend tests**, **13 new frontend tests** (all pure-function
  or API-level — no ROS/RTSP mocking needed for any of it, same
  philosophy as v0.1's test suite).
- `docs/evaluation.md` (new); `docs/architecture.md`,
  `docs/configuration.md`, `docs/limitations.md` updated for the
  evaluation layer.

### Fixed

Real bugs found during verification, not just features shipped clean —
several caught specifically because of this project's rule that nothing
ships without running against a real container or a real browser, not
just passing `tsc`/pytest:

- **Cross-thread SQLite crash under real concurrent requests.** A single
  connection shared via `app.state` (the first design) raised
  `sqlite3.ProgrammingError: SQLite objects created in a thread can only
  be used in that same thread` — FastAPI's sync generator dependencies
  are not guaranteed to run on the same worker thread as the endpoint
  body using the connection they yield. `TestClient`'s synchronous
  single-portal dispatch never reproduced this; a live browser hitting a
  real running server did. Fixed with a fresh connection per request
  (`check_same_thread=False`, safe since a connection is still only ever
  used by one request at a time) plus a deterministic regression test
  using a real thread directly, not relying on FastAPI's own scheduling
  to trigger the failure.
- **Missing SPA fallback in nginx.** Direct navigation to `/sessions` (a
  client-side route added this release) 404'd in the production build —
  confirmed via `curl` before and after. Fixed with
  `try_files ... /index.html` in a dedicated `frontend/nginx.conf`.
- **Latent IPv6 healthcheck bug in nginx**, surfaced (not caused) by
  adding that same `nginx.conf`: `wget http://localhost:80` failed with
  `Connection refused` because nginx never binds `[::]:80`, and
  BusyBox's resolver picked the `::1` `/etc/hosts` entry first. Confirmed
  this predates this release entirely — the *unmodified* stock
  `nginx:alpine` config reproduces it identically — rather than being
  introduced by the new config. Fixed with a dual-stack `listen`.
- **`EvaluationPanel`'s task selector got permanently stuck on `""`.**
  `useState(tasks[0] ?? "")` only read the `tasks` prop once, before the
  parent page's async ground-truth fetch had populated it. Fixed with a
  `useEffect` that resyncs the selected task whenever `tasks` changes.
- **`repository.py`'s `EvaluationResult` was missing `tolerance_ms`** in
  the first cut of the schema — a result's matched/unmatched split isn't
  reproducible or auditable without recording what tolerance produced
  it. Added before any real data depended on the old shape (migration
  `0002`).
- **A hand-computed test expectation was wrong, not the code.** Writing
  `test_precision_undefined_for_never_predicted_class`, a manually
  worked-out macro-precision value missed counting cross-class false
  positives. The test failed; the expectation got corrected, not the
  implementation — recorded here because it's a real example of a test
  catching the test author, not just the code.
- **`CHANGELOG.md` was missing a `[0.1.1]` entry** despite that release's
  own notes saying "full details: CHANGELOG.md" — added retroactively
  below, discovered while preparing this entry.

### Known limitations

Classification-only, `tolerance_ms` not evidence-based (no shared clock
to measure against, unlike the ROS sync default), synchronous
`/evaluate` with no result history, no file-import API endpoint. Full
list: [docs/limitations.md](docs/limitations.md).

## [0.1.1] — release hardening

No new product functionality — a full audit-and-hardening pass on top of
v0.1.0, verified against the same "run it for real, don't just claim it"
rule as everything else in this project.

### Fixed

- Dead historical launch files and orphaned placeholder nodes removed.
- `rtsp_ingestion_node`'s `rtsp_url` no longer defaults to a
  simulator-specific host — required explicitly now, fails clearly if
  missing.
- Subprocess lifecycle hardening in the MJPEG relay (`stdin=DEVNULL`,
  explicit `stdout.close()`).
- FastAPI backend: replaced the deprecated `@app.on_event('startup')`
  with `lifespan`, added graceful `rclpy.shutdown()` on backend shutdown
  (previously nothing called it).
- Multi-stage `ros2_ws` Docker build — measured, not assumed: negligible
  image-size impact (the real weight is `cv_bridge`'s opencv-dev
  dependency chain, not build tooling), kept for the correctness win
  (no dangling-symlink risk in a shipped image) rather than a size win.
- Frontend sensor list now retries whenever the WebSocket (re)connects,
  not just once on page load.
- `frontend/tsconfig.app.json`: TypeScript `strict` mode was never
  actually enabled in the default Vite-generated config — the code was
  already clean, so turning it on was a zero-cost gap closure.

### Added

- 32 new automated tests across frontend (Vitest), backend (pytest), and
  ROS pure-logic modules (`sensor_config.py`, `sync_logic.py` — zero
  `rclpy` imports, plain pytest) — deliberately not mocking the entire
  ROS/RTSP world; see [docs/development.md](docs/development.md).
- Real 30-minute memory soak test: no monotonic growth trend observed in
  `ros`, `backend`, or `frontend` containers, across an injected full
  RTSP outage/recovery and an injected ingestion-process kill/recovery.
- New docs: `docs/configuration.md`, `docs/diagnostics.md`,
  `docs/development.md`, `docs/limitations.md`;
  `docs/architecture.md`'s diagram redone with explicit labeled
  transport planes.
- README rewritten to a clean pitch/architecture/quick-start structure;
  the detailed phase-by-phase v0.1 development history moved into this
  file.

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
