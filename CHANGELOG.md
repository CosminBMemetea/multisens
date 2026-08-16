# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Every entry below was verified against a running system, not just a passing
build — that's a project-wide rule, not editorial flourish; see
[docs/development.md](docs/development.md) for how.

## [Unreleased]

### Added

- **Dynamic multi-instance dashboard + inference status** (v1.0-RC Phase
  4, issue #124) - five additive `SensorConfig` fields
  (`display_name`/`role`/`capabilities`/`recorded`/`derived_from_sensor_id`),
  a straight `GET /api/sensors` passthrough (no allowlist, no ROS
  diagnostics duplication needed - `modality`/`source_type`'s own
  precedent didn't actually apply here since these are genuinely static
  config the dashboard already receives directly). `derived_from_sensor_id`
  is the one with real validation: must name another declared sensor id,
  checked at ROS launch (`sensor_config.py`'s `select_usable_sensors`) -
  truthfully expresses "this simulated feed is a transform of that real
  one" (e.g. the reference config's `depth`/`thermal` from `rgb`), which
  `source_type: simulated` alone couldn't say. `SensorCard.tsx` renders
  it as "derived from `<id>`", plus a new `Inference: ACTIVE/NONE/ERROR`
  sub-block reading `GET /api/inference-connectors` (#122) and matched by
  `config.sensor_id` - kept visually and structurally separate from
  connection health, two genuinely independent state machines. `ACTIVE`
  shows the connector's `plugin_id`, a real measured predictions-per-second
  rate (new `PollRunner.predictions_per_sec` property - `total_ingested`
  over wall-clock time since the runner actually started, `None` before
  it has, never a fabricated `0.0`), and last-prediction age. `GET
  /api/inference-connectors`'s list endpoint now returns the Detail shape
  (health included) for every entry, not just Summary fields, unlike
  `/resource-collectors`'s own list endpoint - the dashboard needs health
  for every sensor's connector from one fetch. `Dashboard.tsx`'s sensor
  grid changed from a hardcoded `md:grid-cols-3` to an auto-fit layout -
  the whole point of a config-driven sensor count is that N is never
  hardcoded in the frontend either.

  9 new backend tests (1073 total: 3 for `predictions_per_sec`, 4 for the
  widened list endpoint and per-connector rate reporting, plus the ROS
  side), 3 new ROS pure-logic tests for `derived_from_sensor_id`
  validation, 6 new frontend tests (65 total: the ACTIVE/NONE/ERROR
  status mapping, the new age formatter). Live-verified through the real
  docker compose stack with a real browser screenshot (not just API
  JSON) in two scenarios: three simultaneous real RTSP-replayed sensors
  (one physical, two declaring `derived_from_sensor_id`) rendering
  correctly with the truthful `Inference: NONE` default on all three;
  and the real `ridesafe_front_rgb`/`ridesafe_rear_rgb` two-sensor
  scenario (issue #121) with issue #123's real YOLO worker attached to
  the front sensor only - the dashboard correctly showed
  `RIDESAFE_FRONT_RGB` as `Inference: ACTIVE` with a genuine model id/fps/
  age and `RIDESAFE_REAR_RGB` as `Inference: NONE`, both through the same
  generic, unmodified `SensorCard`/`Dashboard` code.

- **Reference YOLO inference worker + thin bridge PredictionConnector**
  (v1.0-RC Phase 3, issue #123) - the actual live reproduction of the
  RideSafe one-shot experiment issue #122 only built the wiring for.
  Two-process split: [`examples/plugins/reference-inference/worker/`](examples/plugins/reference-inference/worker/)
  is a standalone process (own `ultralytics`/`opencv` deps, never
  installed into the backend image) that opens its own independent RTSP
  connection, runs YOLOv8n (car/truck/bus/motorcycle at confidence 0.40,
  matching the real one-shot experiment), and serves its latest
  detection over a small local `GET /latest`/`GET /health` HTTP
  endpoint; [`multisens_reference_inference.bridge:YoloBridgeConnector`](examples/plugins/reference-inference/multisens_reference_inference/bridge.py)
  is a thin `PredictionConnector` (zero ML dependency) that polls it and
  translates the response into `Prediction` objects. Model-compatibility
  check in `configure()` (declared `modality` vs. the plugin's
  `supported_modalities`, with an explicit `allow_simulated_input`
  escape hatch). Deterministic `Prediction.id` including `session_id`
  (a deliberate departure from the issue's own phrasing - `predictions.id`
  is a single global primary key, not scoped per session, so omitting
  `session_id` would let a recorded replay looping back to the same
  timestamp in a *different* session silently drop real data rather
  than just deduping a genuine repeat).

  38 new tests across both packages (21 for the bridge plugin against a
  real local HTTP server, 17 pure-logic tests for the worker's
  box-normalization/detection-filtering/state/server modules - none of
  which need `ultralytics`/`opencv` installed). Live-verified against
  the real recorded RideSafe front-dashcam footage (not the synthetic
  simulator), looped through a local MediaMTX: a real third-party plugin
  install (`FROM multisense-backend / RUN pip install
  reference-inference`) into a temporary image, real ROS ingestion at
  ~30fps, a real session producing genuine `Prediction` rows including
  an actual `car` detection at confidence 0.63 with a correctly
  frame-clamped `bbox`, killing the worker process leaving
  `/api/health` and every session-read endpoint fully functional while
  the connector's own health correctly surfaced `FAILED`, and a fresh
  session cleanly re-arming the same connector back to `RUNNING` once
  the worker was restarted.

  This live run also surfaced (but deliberately did not fix, as
  cross-cutting shared core code) a real gap: within one *continuous*
  session, a `poll()` exception permanently latches a connector to
  `FAILED` with no automatic retry once the underlying feed recovers -
  affects `poll_connectors`/`resource_collectors`/`inference_connectors`
  alike, not just this reference pair. Tracked as issue #126.

- **Session-bound background inference wiring** (v1.0-RC Phase 2, issue
  #122) - applies issue #111's session-bound lifecycle (build at boot,
  configure/start on session `/start`, stop on `/complete` - never
  boot-bound like `poll_connectors:`, which has no session concept and
  would let a prediction from one session silently contaminate another)
  to background ML inference. No new plugin type, no new abstraction:
  `PredictionConnector` (Phase 97) already matches the need exactly -
  the intended shape is a thin bridge plugin with no ML dependency of
  its own, reading a separately-running inference worker process's
  latest output over HTTP and translating it into `Prediction` objects,
  so a native-level crash in the actual model can never take down the
  backend. New `inference_connectors:` config section (same
  `id`/`plugin`/`config`/`poll_interval_s` shape as `poll_connectors:`/
  `resource_collectors:`), new `GET /api/inference-connectors` (+`/{id}`)
  read endpoint. `PollRunner`/`insert_predictions_batch` reused
  unmodified - `PredictionConnectorInstance.poll()` already matches
  `PollRunner`'s own `poll` shape exactly.

  28 new backend tests (1067 total): config loader, manager-layer wiring
  (including the concurrent-session-conflict case and a direct real
  -database-write regression test through a real background thread),
  session-lifecycle hooks (including a test confirming resource
  collection and inference wiring stay independent of each other), and
  API-layer tests (including secret redaction). Live-verified through
  the full real `docker compose` stack: the new endpoint returns `[]`
  cleanly with no config entries, and a real session start/complete
  cycle (both #111's and #122's hooks firing together) completes with
  zero errors.

  The reference inference worker/bridge plugin themselves - the actual
  live reproduction of the RideSafe experiment - are issue #123, not
  this one; this issue is the wiring they attach to.

- **ROS sensor-id topic migration - two simultaneous same-modality live
  sensors** (v1.0-RC Phase 1, issue #121) - `rtsp_ingestion_node.py`
  published `/multisens/sensors/{modality}/image_raw`/`frame_stamp`;
  `sensor_config.py`'s launch guard hard-failed on a duplicate
  *modality*. Two RGB cameras (e.g. `ridesafe_front_rgb`/
  `ridesafe_rear_rgb`) could never be live-ingested simultaneously.
  Fixed: topics now key by `sensor_id`
  (`/multisens/sensors/{sensor_id}/...`); the launch guard now rejects a
  duplicate *id*, explicitly allowing a shared modality.
  `sync_status_node.py`/`sync_logic.py` migrated the same way
  (`_load_modalities` → `_load_sensor_ids`, `offset_ms_{modality}` →
  `offset_ms_{sensor_id}`) - confirmed via full code read that neither
  ever actually depended on "modality" as a concept, only on each
  participant having a unique key, so this was a rename, not a logic
  change. `modality` remains metadata (a `KeyValue` in diagnostics),
  never part of topic identity.

  Also fixed in the same pass: `docker-compose.yml`'s `ros` healthcheck
  hardcoded `rgb_ingestion`/`depth_ingestion`/`thermal_ingestion` node
  names - flagged as contradicting "config-driven, not hardcoded" back
  in the original v0.9.0 adversarial bug hunt, now genuinely config-driven
  (counts `_ingestion`-suffixed nodes against the sensor count in the
  mounted config, names none of them).

  Backward compatibility: the reference `rgb`/`depth`/`thermal` config
  (`id == modality`) produces byte-identical topic/node names to before -
  confirmed live, not assumed. 15 ROS-side tests (8 `sensor_config` + 7
  `sync_logic`, including two new tests: duplicate-id-still-rejected,
  same-modality-different-id-now-legal), backend suite unaffected
  (1039 passed). Live-verified through the full real `docker compose`
  stack with two genuine RTSP-replayed RideSafe cameras: both connected
  independently (`fps_received` ~30 each), `system` reported "2/2
  configured sensors connected," `sync` reported
  `offset_ms_ridesafe_front_rgb`/`offset_ms_ridesafe_rear_rgb`
  independently and "synchronized within 25ms tolerance" - and the
  reference 3-sensor config re-verified afterward to produce the exact
  same node/topic names as before the migration.

  Also fixed: `docs/development.md`'s documented ROS pure-logic test
  command included a `pip install pytest -q` step that fails outright
  (`ros:humble-ros-base` + colcon has no `pip` at all) - found while
  running this issue's own tests. `python3-pytest` is already present
  via apt (a transitive `python3-colcon-common-extensions` dependency);
  the command now matches what actually works, verified by running it
  exactly as documented.

- **Evidence Playback: per-sample GT/prediction inspection with
  multi-source overlap, agreement & disagreement** (issue #120) - the
  first real recorded-data experiment (front/rear 70mai footage) exposed
  a genuine gap: `match_by_timestamp` already computes per-sample
  GT/prediction matches internally, but `/evaluate` only ever returned
  aggregated metrics, discarding the per-sample detail. New
  `GET /sessions/{id}/evidence` endpoint joins `match_by_timestamp`'s
  results across every `(configuration_id, source_id)` pair active in a
  session for a task - one row per ground-truth sample, one column per
  source - and classifies the relationship between sources
  (`AGREE_POSITIVE`/`AGREE_NEGATIVE`/`DISAGREE`/`ONLY_ONE_SOURCE_AVAILABLE`/
  `NO_COMMON_GT_SAMPLE`) server-side, matching `/compare`'s own
  `validity: {status, reasons}` precedent - never inferred client-side.
  Never infers a combined/fused prediction: a "source" is always exactly
  one already-ingested `Prediction` stream: MultiSens evaluates a
  combined/union source when one was explicitly produced, it never
  manufactures one. `positive_label` is a required parameter, not
  defaulted - which label counts as "the event of interest" is a
  modeling decision this layer must never guess (no default, same
  posture `confidence_threshold`/`iou_threshold` already have for
  object_detection). New `SessionDetail.tsx` "Evidence Playback" section
  renders it, sources side by side per sample, with a `positive_label`
  picker that starts genuinely unselected - a real bug was caught during
  live verification where an earlier draft silently defaulted the picker
  to the alphabetically-first observed label ('absent' before
  'present'), inverting every outcome; fixed by requiring an explicit
  choice before any evidence loads, exactly the same "never guess"
  discipline the backend parameter already had, now actually held to on
  the frontend too.

Backend: 26 new tests (1039 total) - domain-layer relationship
classification plus a full API-layer suite, including a test shaped
exactly like the real recorded experiment (disjoint front/rear windows
plus an explicit union source) proving the endpoint never invents
overlap that isn't there. Frontend: `tsc`/`oxlint` clean, 53/53 vitest
unchanged. Full `docker compose build` (backend + frontend) and live
verification against the real `ridesafe-recorded-001` session: the
known front-clip false positive (frame `f_006`, confidence 0.40) is
directly visible and correctly badged FP once `positive_label=present`
is explicitly chosen, zero console errors.

### Fixed

- **Connector wrappers never self-healed after a `poll()`/`sample()`/
  `health()` exception, within one continuous session** (v1.0-RC issue
  #126, found live-verifying issue #123's own "restarting the worker
  recovers independently" acceptance bar). `_PollConnectorInstance`
  (`poll_connectors:`/`inference_connectors:`), `ResourceCollectorInstance`
  (`resource_collectors:`), and `ConnectorInstance` (`SensorConnector`,
  `/api/connectors`) all shared the identical pattern: any exception from
  `poll()`/`sample()`/`health()` moved the connector to `FAILED`, and
  `FAILED` was then permanently excluded from ever calling the plugin
  again - a worker restarting for a routine deploy, an
  OOM-kill-and-supervisor-restart, or any other transient outage
  silently and permanently ended that connector's contribution to the
  *current* session. Only a brand new session's `configure()`+`start()`
  ever re-armed it (confirmed working, live, before this fix - the gap
  was specifically mid-session recovery).

  Fixed by introducing `DEGRADED` as a genuinely retryable state,
  distinct from `FAILED`: a `poll()`/`sample()`/`health()` exception now
  moves to `DEGRADED`, and a `DEGRADED` connector keeps being called
  every cycle, flipping back to `RUNNING` the instant a call succeeds.
  `FAILED` is unchanged for `configure()`/`start()`/`stop()` failures -
  those remain terminal until an explicit fresh `start()`. A second,
  related bug surfaced by the very first live-verification attempt of
  this fix: `health()`'s success path blindly forced `RUNNING` just
  because the call itself didn't raise, discarding a plugin's own
  legitimate non-raising `DEGRADED` self-report (e.g. the reference YOLO
  bridge plugin's own `poll()`-failure tracking) - fixed to adopt
  whichever of `RUNNING`/`DEGRADED` the plugin actually reports. Also
  fixed the reference bridge plugin itself (issue #123): its `poll()`
  let a worker-down exception propagate without first recording it into
  its own `_last_error`, so its *own* `health()` never learned about the
  failure and kept reporting `RUNNING` right up until the wrapper fix
  above would otherwise have adopted that stale, over-optimistic report.

  15 new/updated backend tests across the three wrapper test files
  (self-heal round-trips, plus a dedicated test proving a plugin's own
  non-raising `DEGRADED` report is adopted rather than overridden), one
  new bridge-plugin test. Live-verified through the real docker compose
  stack exactly the way issue #123 itself was: a real session, a real
  YOLO worker process killed mid-session (connector correctly showed
  `DEGRADED` with the real `urlopen` error, predictions stopped), then
  restarted *without touching the session* - the connector self-healed
  to `RUNNING` and predictions resumed, `total_predictions` climbing
  within the same, uninterrupted session throughout.

## [0.9.1] — Adversarial bug hunt & live resource collection

Three confirmed bugs found by a live adversarial audit of the released
v0.9.0 (issues #108-#110), fixed same-night with regression tests and a
full docker rebuild + live re-verification against the fixed release.
A fourth, related finding (issue #111 - `ResourceCollector` plugins and
the pre-existing v0.7 built-in collector are likewise never wired into
any live collection trigger) was deliberately deferred, not fixed: it
needs a real design decision about when/how collection is triggered,
not a same-night smallest-fix patch.

### Fixed

- **Sessions page showed a fabricated, ever-growing duration for
  sessions that were never started** (BUG-001, #108) -
  `formatDuration()` fell back to `Date.now()` whenever `ended_at` was
  `null` regardless of session status; every one of the 26 demo
  sessions shipped with v0.9.0 (all `status: created`) displayed a
  large, fabricated, wall-clock-derived duration instead of "no elapsed
  time to report." Now gated on `status === 'running'`; `created`/
  `failed` sessions render `—`.
- **`/sessions/{id}/start` and `/complete` had no state-transition
  guard** (BUG-002, #109) - any transition from any state silently
  succeeded, including a second `/complete` call silently re-stamping
  `ended_at` with a new, later timestamp, destroying the true
  completion time. Now an explicit state machine: `created -> running`/
  `running -> completed` are the only real transitions; same-state
  re-calls are idempotent no-ops (never re-stamping `ended_at`);
  `completed -> *` and `created -> complete` are a clean `409`.
- **`PollRunner` was never instantiated - installed Prediction/
  GroundTruth connector plugins never actually polled** (BUG-003, #110)
  - Phase 97 built and tested `PollRunner`/`PredictionConnectorInstance`/
  `GroundTruthConnectorInstance` in isolation, but nothing in the
  running application ever called them; a plugin of either type would
  discover as `AVAILABLE` and sit inert forever. Fixed with a new
  `poll_connectors:` config section and
  `build_poll_runners()`/`stop_poll_runners()`
  (`app/plugins/manager.py`), the same config-driven wiring discipline
  `build_connector_instances()` already established. Directly falsified
  the v0.9.0 README's own extensibility claim for 2 of 5 plugin types -
  claim now true.

Backend: 24 new tests (930 → 950). Frontend: 6 new tests (47 → 53),
`tsc`/`oxlint` clean throughout. Full `docker compose build` (backend +
frontend) + live re-verification of all three fixes against the
rebuilt containers.

A second, independently-reported batch of five confirmed bugs in
`POST /api/profiles/{id}/tradeoffs` (issues #112-#116), critiqued against
the actual code before fixing, then fixed with regression tests and a
second full rebuild + live re-verification.

- **Resource-only configurations (real resource evidence, no decision
  evidence) were silently excluded from `resource_comparison` and the
  Pareto front** (BUG-005/006, #112/#113) - both were built from a list
  (`tradeoffs`) only ever populated for decision-evaluated
  configurations, even though the same response's own `configurations`
  array already reported resource evidence for them (a Phase 76
  guarantee this endpoint's own comparison/Pareto logic didn't fully
  carry through). `resource_comparison` 422'd with a misleading "has no
  evidence in this analysis" for a configuration the response itself
  showed evidence for. Fixed by appending a `ConfigurationTradeoff` for
  every resource-only configuration too (`policy_status: PolicyStatus |
  None`, widened from non-optional - neither downstream consumer ever
  reads that field).
- **`resource_constraints` silently produced zero results if its metric
  wasn't also in `resource_metrics`** (BUG-007, #114) - no error, not
  even an `na` entry, just an empty `constraint_results` list. Fixed
  with a validator requiring every constraint metric to already be
  requested, matching the existing `pareto_dimensions` rule.
- **Unrequested resource metrics could corrupt `platform_id`/
  comparability metadata** (BUG-008, #115) - `platform_id` and the
  representative metadata were derived from *every* observation for a
  configuration before `resource_metrics` narrowed anything, so an
  unrequested metric recorded under a different platform could force
  `platform_id` to `'unknown'` or leak the wrong resolution/target_fps
  into comparability warnings. Fixed by filtering to requested metrics
  first.
- **Plugin-added resource metrics were invisible in the frontend**
  (BUG-009, #116) - the backend's `SUPPORTED_RESOURCE_METRICS` is
  dynamically extensible via a `RESOURCE_COLLECTOR` plugin, but the
  frontend hardcoded the original six built-in metrics and never
  requested anything else. Fixed with a new read-only
  `GET /api/resource-metrics` endpoint, fetched dynamically by the
  Resources tab instead of a hardcoded constant.

Backend: 9 new tests (957 total). Frontend: `tsc`/`oxlint` clean, 53/53
vitest unchanged (the fix is hook/wiring-level, consistent with this
project's existing test-coverage boundary of pure functions only - live
Playwright verification against the real RideSafe demo profile stands
in for component-level coverage here, same as every other UI change
this project has shipped). Full `docker compose build` + live
re-verification of the Resources tab with real CPU/RAM/network/latency
data, zero console errors.

A third, independently-reported batch of two confirmed bugs in the
plugin-discovery/connector infrastructure (issues #117/#118), each
verified against the real code with a direct reproduction before
fixing.

- **Duplicate `plugin_id` did not roll back `EVALUATOR_REGISTRY`/
  `SUPPORTED_RESOURCE_METRICS` side effects** (BUG-010, #117) -
  `register_evaluator()`/`register_resource_metrics()` mutate these two
  global namespaces as a side effect of processing a single entry
  point, *before* a same-`plugin_id` collision from a later entry point
  is even known. When the collision was detected, both `PluginRecord`s
  were correctly marked `LOAD_FAILED` ("neither is used"), but the
  first plugin's `evaluator_type`/resource metric silently stayed live
  and dispatchable through `/api/evaluation`/`/api/resource-metrics`
  anyway - reproduced directly: `EVALUATOR_REGISTRY` still held the
  invalidated plugin's instance by identity. Fixed with
  `_rollback_registration_side_effects()`, called from the
  duplicate-detection branch: an exact, identity-checked removal for
  evaluators (`evaluator_type` is an exclusive namespace, so this is
  unambiguous); for resource metrics, removes only what the invalidated
  plugin newly introduced, never a metric another still-`AVAILABLE`
  plugin also declares, and never one of the six permanent built-ins
  (metrics are explicitly allowed to be shared across collectors,
  unlike `evaluator_type`). Explicitly excludes built-ins from rollback
  altogether - an early version of this fix, caught by its own
  regression test, incorrectly deleted a built-in evaluator's registry
  entry because a built-in's `instance` is shared by identity with its
  `EVALUATOR_REGISTRY` entry.
- **`PollRunner`'s background thread died silently on a database
  connect/insert failure** (BUG-011, #118) - `poll_once()` already
  caught the connector's own `poll()` exceptions, but a
  `self._connect()` or `insert_batch_with_partial_failure(...)` failure
  (e.g. `sqlite3.OperationalError: database is locked`, a realistic
  condition under SQLite's concurrent-writer model this same codebase
  already exercises) propagated straight out of `poll_once()` and
  killed the daemon thread with no error recorded - silently
  re-introducing BUG-003 (#110) on the very first transient DB hiccup,
  just less visibly. Fixed by wrapping both calls in the same
  catch-record-`last_error`-and-continue discipline `poll()` itself
  already had.

Backend: 8 new tests (965 total) - including one that drives a real
background thread through an injected DB failure and proves it keeps
polling and successfully ingests on a later cycle, not just that
`poll_once()` in isolation doesn't raise. Both reproduced directly
against the running code before being fixed; both fixes re-verified
with a full `docker compose build backend` and a live plugin-discovery
check against the rebuilt container (`plugin discovery: 4 available, 0
incompatible, 0 load_failed, 0 disabled`).

The fourth finding deferred above (issue #111) is now closed: live,
session-bound resource collection.

### Added

- **Live resource collection, session-bound** (#111) - `ResourceCollectorInstance`
  (Phase 99) and the pre-existing v0.7 built-in collector
  (`SystemMetricsWindow`/`collect_sensor_metrics`) had no live trigger
  anywhere in the running application; every resource observation ever
  shipped came from an offline batch generator, never a real collector.
  Fixed session-bound, not process-bound: `POST /sessions/{id}/start`
  now configures and starts every `resource_collectors:`-configured
  collector, each with its own background sampling loop;
  `POST /sessions/{id}/complete` stops them. No new runner class -
  `ResourceCollectorInstance.sample()` already matches `PollRunner`'s
  `poll` callback shape exactly, so this reuses `PollRunner` unmodified,
  inheriting BUG-011's DB-failure survival fix directly. A new built-in
  adapter (`multisens.builtin.resource.system-metrics`,
  `app/plugins/builtin_resource_collector.py`) wraps the existing,
  unchanged v0.7 collection code behind the same plugin interface an
  external `RESOURCE_COLLECTOR` plugin uses - one lifecycle model, not
  two. New config: `resource_collectors:` (mirrors `poll_connectors:`)
  and a declared top-level `platform_id:`. New read-only
  `GET /api/resource-collectors` (+`/{id}`) and an Integrations-page
  table, matching `/api/connectors`'s existing posture. A collector
  already attached to one session is never silently double-attached to
  a second, concurrently-running one - `configure()`'s own
  already-RUNNING guard makes that safe, and session `/start` never
  fails because of it. See
  [docs/resources.md#live-collection-v091-issue-111](docs/resources.md)
  and [docs/plugin-sdk.md](docs/plugin-sdk.md) for the full design,
  including the explicit limits (backend restart does not resume
  collection; `configuration_id` derivation assumes today's
  one-sensor-per-modality live architecture, documented in
  `docs/limitations.md`, not solved for the general case).

Backend: 43 new tests (1008 total) across five new/extended files -
built-in adapter (17), manager wiring including a concurrent-session
conflict test and a direct DB-write regression test (12), config
loaders (8), session-lifecycle wiring including a real REST-API-level
end-to-end test (6). Frontend: `tsc`/`oxlint` clean, 53/53 vitest
unchanged (UI/wiring-level change, same established test-coverage
boundary as BUG-009). Full `docker compose build --no-cache` (all three
images) + live verification: a real session's `/start` genuinely
produces persisted resource-observation rows via the background thread
(not a batch POST), visible through the existing read API, the
Integrations page's new table, and the Resources tab's trade-off view;
`/complete` stops collection cleanly.

## [0.9.0] — Plugin SDK & external integration framework

Built phase by phase (Phase 92 through Phase 106), same discipline as
v0.1-v0.8: a full architecture review before any code (a 40-question
review plus a mandatory paper-design test - hypothetical `robot_lidar`/
`robot_imu` connectors using only the SDK, proving zero core imports
needed - reviewed and approved before Phase 92 implementation began),
explicit self-review checkpoints per phase, nothing merged without
running against a real container. Introduces a small, closed **plugin
SDK** (`sdk/` - the independently installable `multisens_sdk` package)
so a new sensor, prediction/ground-truth source, evaluator, or
resource-telemetry integration can be added by installing a Python
package and restarting - the same "add a capability without editing
core" shift v0.8 already made for evaluators, generalized to every
extensibility surface. Full domain model, trust model, and API
reference: [docs/plugin-sdk.md](docs/plugin-sdk.md) /
[docs/connector-api.md](docs/connector-api.md).

**Plugins are trusted local software, not sandboxed** - stated
explicitly and repeatedly (README, docs/plugin-sdk.md, a startup log
line whenever any non-built-in plugin loads), verified concretely in
Phase 105 rather than only documented.

### Added (v0.9 plugin SDK)

- **`multisens_sdk` package** (Phase 93): the canonical wire-shape
  models (`GroundTruth`/`Prediction`/`EvaluationResult`/
  `ResourceObservation`/`MetricValue`/etc.) relocated from `backend/`,
  moved not rewritten - `backend/app/domain/{models,matching,
  evaluator_output,resources}.py` became thin re-export shims, proven
  identical via `X is SdkX` checks and the full pre-existing 730-test
  suite passing unchanged. Five typed `Protocol` contracts
  (`SensorConnector`/`PredictionConnector`/`GroundTruthConnector`/
  `EvaluatorPlugin`/`ResourceCollector`), `PluginDescriptor`/
  `PluginType`/`MULTISENS_PLUGIN_API_VERSION`, `ConnectorState`/
  `ConnectorHealth`/`SensorSample`. A real packaging bug found and fixed
  before shipping: the base image's system pip silently mis-resolved
  the SDK's PEP 621 metadata; fixed by upgrading pip as the Dockerfile's
  first step.
- **Discovery & registry** (Phase 94): `discover_plugins()` via
  `importlib.metadata.entry_points(group="multisens.plugins")` - never
  directory scanning, never a blind import. Entry-point name must equal
  `descriptor().plugin_id` (lets `plugins.disabled` suppress a plugin
  *before* its code is ever imported). `PluginStatus`
  (`AVAILABLE`/`INCOMPATIBLE`/`LOAD_FAILED`/`DISABLED`) tracked
  separately from runtime `ConnectorState`. Duplicate `plugin_id`s
  reject both sides deterministically; every call into plugin code is
  individually guarded so one broken plugin never stops discovery of
  the next.
- **`SensorConnector` runtime wrapper** (Phase 95): `ConnectorInstance` -
  mutating calls (`configure`/`start`/`stop`) raise a clean exception
  and move state to `FAILED` first; observational calls (`health`/
  `sample`) never raise. Idempotent `start()`/`stop()`, a 65,536-byte
  small-payload cap on `sample()`, and the `*_env` secret-reference
  convention (`password_env: CAMERA_PASSWORD`, resolved from
  `os.environ` at connect time only, never persisted or echoed).
- **Built-in RTSP adapter** (Phase 96): `multisens.builtin.sensor.rtsp` -
  descriptor-only over the existing, completely unchanged v0.1
  ingestion pipeline; `health()` maps from `RosBridge.snapshot()`,
  `sample()` always `None` (video stays data-plane). The flagship "one
  connector implementation, many independent sensor instances"
  demonstration: `ridesafe_front_rgb`/`ridesafe_rear_rgb` sharing one
  plugin while staying fully independent.
- **Prediction + GroundTruth connectors** (Phase 97): pull-based
  `PredictionConnectorInstance`/`GroundTruthConnectorInstance` plus
  `PollRunner`, a background thread forwarding through the same
  `repository.insert_batch_with_partial_failure` the REST batch
  endpoints already use - a connector is a code-driven way to call an
  endpoint that already exists, never a second ingestion mechanism.
- **External evaluator plugins** (Phase 98): `register_evaluator()` -
  `EVALUATOR_REGISTRY` becomes genuinely extensible at runtime.
  `evaluator_type` is a namespace separate from `plugin_id`, checked
  independently; a collision rejects only the later registrant, a
  built-in never silently overridden. Full acceptance bar proven: a
  test-only external evaluator flows through `/evaluate` ->
  `EvaluationResult` -> `/coverage` -> `/compare`, zero core edits
  beyond registry wiring.
- **External resource-collector plugins** (Phase 99):
  `register_resource_metrics()` - `SUPPORTED_RESOURCE_METRICS` becomes
  extensible, all-or-nothing per plugin. `ResourceCollectorInstance`
  follows the same lifecycle discipline as every other connector
  wrapper.
- **Contract test kit** (Phase 100): `multisens_sdk.testing` (opt-in
  `[testing]` extra) - framework-agnostic `assert_valid_plugin_descriptor`/
  `assert_connector_lifecycle`/`assert_health_contract`/
  `assert_evaluator_output_shape`/`assert_evaluator_deterministic`/
  `assert_resource_observation_shape`, each proven against both a
  passing fake and a deliberately-broken one.
- **Reference external plugin** (Phase 101):
  `examples/plugins/environment-sensor/` - a real, independently
  installable package proving two plugin categories (a synthetic
  temperature/humidity `SensorConnector`, a synthetic
  `ResourceCollector` metric) with one small package. The actual
  clean-room test: installed into a genuinely clean Python virtualenv
  with zero MultiSens tooling, its own 14-test suite passed with zero
  `backend.app`/`frontend`/`ros2_ws` imports anywhere.
- **Integrations API + UI** (Phase 102): five read-only routes
  (`GET /api/plugins`, `/api/plugins/{id}`, `/api/plugins/{id}/capabilities`,
  `/api/connectors`, `/api/connectors/{sensor_id}`) - no
  install/uninstall/start/stop endpoint anywhere. `app/plugins/manager.py`'s
  `build_connector_instances()` finally executes the `config/sensors.yaml`
  `connector:` block Phase 95 only documented, one fresh connector
  object per sensor id via a new `PluginRecord.factory` field.
  `redact_secrets()` scrubs any `password`/`token`/`secret`/`key`-shaped
  dict key from every response. New `/integrations` frontend page.
- **RideSafe/PropertyWatch validation** (Phase 103): a dedicated test
  proves all five existing public demo sensor identities
  (`ridesafe_front_rgb`/`ridesafe_rear_rgb`,
  `property_entrance_rgb`/`property_storage_rgb`/`property_indoor_rgb`)
  get independent `ConnectorInstance` objects from one plugin - via a
  temp config, deliberately never the repo's own live
  `config/sensors.yaml` (would surface them on the Dashboard and
  collide with ROS ingestion's one-sensor-per-modality live-ingestion
  limit). Not a new live-video claim.
- **Robot/drone extensibility validation** (Phase 104): the
  architecture review's own `robot_lidar`/`robot_imu` paper design,
  built for real as two test-only plugins - proves connector
  registration/routing for a LiDAR/IMU-shaped sensor type, explicitly
  never point-cloud geometry or IMU signal semantic understanding.
- **Robustness & security review** (Phase 105): 13 new tests closing a
  lifecycle-failure coverage gap, a testability refactor
  (`stop_connector_instances()`), a trust-model exercise (a plugin
  reading environment variables directly and writing to the filesystem
  runs completely normally - no more, no less permissive than
  documented), and a pinned secret-redaction scope boundary. A
  security-honesty grep pass across every `sandbox`/`isolat`/`secure`
  mention found and fixed two real documentation-accuracy gaps (see
  Fixed, below).

### Fixed (v0.9)

- **Trust-model disclosure claimed to be "stated in the README" when it
  wasn't** (Phase 105) - `README.md` had zero mention of the
  no-sandboxing disclosure `docs/plugin-sdk.md`'s Trust model section
  said it carried. Fixed by adding it as a new "What MultiSens is NOT"
  bullet, making the existing claim true.
- **Stale cross-reference in docs/plugin-sdk.md** (Phase 105) - the
  Phase 97 section still said config-driven connector wiring "is not
  yet built," true when written, false since Phase 102 shipped it.
  Corrected to point at the real implementation.
- **A Phase 94 test fixture broke when Phase 99's registry hook started
  calling `available_metrics()` unconditionally for
  `RESOURCE_COLLECTOR`-typed plugins** - caught by the full regression
  run before committing, fixed by adding the method to the shared fake.

### Known limitations (v0.9)

- No true process isolation - in-process exception guarding only (a
  discovery-time or runtime-method exception never crashes the process
  or affects another plugin); no seccomp, no separate OS user, no
  per-plugin container isolation. See
  [docs/plugin-sdk.md#trust-model](docs/plugin-sdk.md#trust-model).
- Exact-match-only plugin API-version compatibility, no range matching.
- No plugin configuration-editing UI and no connector start/stop
  mutation API - config changes require a restart, same as v0.1's
  sensor config.
- No first-class LiDAR/point-cloud/IMU schemas in core - `data_type` is
  an open string core never semantically interprets.
- `redact_secrets()` redacts dict keys only; `health.message` is free
  text from a plugin's own exception and is deliberately never
  pattern-redacted.
- `multisens_sdk`'s ARM64/Jetson compatibility is reviewed (pure Python
  + `pydantic`, no native deps), not tested against real hardware - none
  was reachable in this development environment.
- Backend: 200 new tests (730 → 930). Frontend: unchanged (47/47),
  `tsc`/`oxlint` clean throughout - v0.9 added one new page
  (`/integrations`) with no new pure-function logic requiring its own
  unit test.

## [0.8.0] — multi-task evaluation & robotics/drone readiness

Built phase by phase (Phase 78 through Phase 90), same discipline as
v0.1-v0.7: a strong architecture review before any code (the master
prompt's own specification challenged explicitly, several proposals
rejected - no `TaskDefinition` registry entity, no AP/mAP, no Hungarian
assignment, no vector regression, no relative/percentage error - each
with a documented reason), explicit self-review checkpoints per phase,
nothing merged without running against a real container. Generalizes the
v0.2 evaluation layer beyond classification: a small, closed `Evaluator`
protocol plus a static registry, two new evaluators (object detection,
scalar regression), full backward compatibility for every pre-v0.8
classification workflow (proven, not assumed), and three new reference
demos - two extending the existing RideSafe/PropertyWatch personal-camera
stories, one introducing the first generic robotics-ready example.
**Every other layer (comparison, coverage, decision, trade-offs) needed
zero engine changes** - all four were already evaluator-blind by
construction, proven end to end with a single mixed-task profile. Full
domain model, algorithm, and API reference: [docs/evaluators.md](docs/evaluators.md) /
[docs/detection-evaluation.md](docs/detection-evaluation.md) /
[docs/regression-evaluation.md](docs/regression-evaluation.md).

This release also includes a forward-looking public-language cleanup
completed ahead of the v0.8 phases proper: retires the last
cabin-themed demo content and trims generic regulatory-framework
disclaimers project-wide - no functionality changes except renaming/
retheming demo fixtures.

### Changed (public-language cleanup)

- **Retired the "Generic Cabin Safety Demo" (v0.4/v0.5's flagship
  requirement-profile/coverage demo), rethemed to "Generic Sensor
  Evaluation Lab."** All numbers (accuracies, pass/fail pattern,
  coverage percentages) stay bit-identical - only names changed:
  `examples/profiles/cabin-safety-demo.json`/`cabin-safety-demo-data.json`
  → `sensor-lab-demo.json`/`sensor-lab-demo-data.json`; requirement
  groups `Alertness`/`Occupancy`/`Eyewear Robustness` →
  `Baseline Detection`/`Strict Accuracy`/`Weather Robustness`
  (`Visibility Robustness` was already neutral, unchanged); the third
  condition dimension `eyewear` (`none`/`glasses`) → `weather`
  (`clear`/`rain`), including the requirement/session descriptions that
  used to reference "occupant wearing glasses." `scripts/
  generate_profile_demo_data.py`/`load_profile_demo_data.py`,
  `backend/tests/test_profile_demo.py`, `examples/profiles/README.md`,
  `docs/profiles.md`, `docs/condition-explorer.md`,
  `docs/decision-support.md`, and `README.md` updated to match; all 5
  independent-verification tests re-pass with unchanged expected values,
  confirming the retheme changed nothing but names.
- **Renamed the v0.2 evaluation demo's scenario id** (`synthetic-cabin-demo`
  → `synthetic-classification-demo`, `examples/evaluation/classification-demo.json`) -
  it never had cabin-specific content, "cabin" was only ever an arbitrary
  id string.
- **Trimmed regulatory-framework-naming disclaimers** ("not NCAP," "not a
  DMS/OMS scheme," etc.) from `README.md`, `docs/profiles.md`,
  `docs/limitations.md`, and the frontend's synthetic-data banner
  (`ProfileDetail.tsx`) - MultiSens's "no built-in domain-specific
  framework logic" statement stands on its own without naming outside
  schemes just to disclaim them. Design-rationale uses of "regulatory-
  looking" that don't name a specific outside framework (`decision.py`,
  `DecisionPanel.tsx`, `docs/decision-support.md` - explaining why
  `DecisionPolicy` has no default) are unchanged; they were never a
  disclaimer to begin with.

### Added (v0.8 evaluator layer)

- **Generic `Evaluator` protocol + `EvaluatorOutput`**
  (`backend/app/domain/evaluators.py`/`evaluator_output.py`, Phase 78):
  `evaluate(match_result, parameters) -> EvaluatorOutput`, frame-level
  counts (`sample_count`/`matched_samples`/`unmatched_predictions`/
  `unmatched_ground_truth`) meaning the same thing for every evaluator,
  `metrics: dict[str, float | None]`, optional evaluator-specific
  `details`. `EVALUATOR_REGISTRY` started **empty** - only ever holds
  fully-working entries, populated one evaluator at a time as each
  became real. New migration `0005_evaluation_result_evaluator_type.sql`
  (`evaluator_type TEXT NOT NULL DEFAULT 'classification'`, nullable
  `details TEXT`) - every pre-v0.8 row auto-becomes classification, zero
  backfill needed.
- **`ClassificationEvaluator`** (Phase 79): wraps the existing v0.2
  `evaluate_classification` byte-for-byte, registered as
  `EVALUATOR_REGISTRY['classification']`. `/evaluate`'s `evaluator_type`
  field defaults to `'classification'` - every pre-v0.8 caller keeps
  working unchanged; an unrecognized `evaluator_type` is always a clean
  `422`, never a silent fallback.
- **Object detection domain model** (`backend/app/domain/detection.py`,
  Phase 80-82): normalized `[0.0, 1.0]` top-left `x`/`y`/`width`/`height`
  bbox convention (always valid by construction), `parse_detections`/
  `parse_ground_truth_objects`, `compute_iou`, greedy per-frame object
  matching (sorted by descending IoU, deterministic tie-break by
  `(gt_index, detection_index)` - explicitly not Hungarian assignment,
  this codebase's first numerical dependency would have been for it),
  label filtering before IoU (a wrong-label detection is both a miss and
  a false positive, never partial credit), IoU threshold gating candidacy
  (not just a post-hoc label). `DetectionParameters`
  (`confidence_threshold`/`iou_threshold`, both **required, no default**).
  Session-level precision/recall/F1/mean-matched-IoU plus a per-class
  breakdown in `details`. **No AP/mAP anywhere** - grep-verified by a
  dedicated test. `DetectionEvaluator` registered only once `evaluate()`
  was complete and tested (Phase 82), not when the schema/matching code
  first existed (Phase 80-81) - the registry's own "only working
  entries" rule applied to itself.
- **Scalar regression domain model** (`backend/app/domain/regression.py`,
  Phase 83): `{"value": float, "unit": str}` schema on both sides, a
  vector `value` rejected with a dedicated clear message, per-pair and
  cross-sample unit-mismatch checks (both raise, never silently drop or
  average incompatible quantities - the same rule v0.7's
  `compute_resource_metric_summary` already applies to mixed-unit
  resource observations). MAE/RMSE/bias/median-absolute-error.
  Deliberately deferred, not silently dropped: relative/percentage error,
  vector regression - both grep-verified absent.
- **Full API integration** (Phase 84): `EvaluateRequest.evaluator_type`/
  `parameters`; `CompareRequest.parameters` threaded to the common-set
  re-evaluation (fixes a real bug - `/compare` used to crash any
  `object_detection` comparison with an unhandled `500`, since the
  common-set path unconditionally called `evaluate(match_result, {})`
  and detection has no default thresholds; now a clean `422` if omitted);
  `/timeline` explicitly checks `evaluator_type` before extraction,
  returning a dedicated message for a non-classification result instead
  of an accidental one from inside `extract_label`.
- **Mixed-task integration proof** (Phase 85): a single profile with
  classification + object_detection + regression requirements on the
  same two configurations, run end to end through `/coverage`,
  `/decision-analysis`, `/tradeoffs`, and `/compare` - zero production
  code changed to make it work, confirming `coverage.py`/`analysis.py`/
  `decision.py`/`resources.py` were already evaluator-blind.
- **Multi-task frontend** (Phase 86): `EvaluationResult` discriminated
  union keyed on `evaluator_type` (`frontend/src/types.ts`, no `any`
  anywhere), evaluator-aware summary columns
  (`evaluationColumns.ts`), a per-class breakdown view for detection and
  a unit note for regression (`EvaluationPanel.tsx`), a fully generic
  `ComparisonMetricTable`/leaderboard driven by whatever metric keys a
  comparison actually has (no more hardcoded F1/Recall columns). Real
  gap found and fixed: the Evaluation panel used to fetch `/timeline`
  unconditionally for every evaluator type, surfacing Phase 84's new 422
  as a page-level error banner for detection/regression sessions -
  fixed by gating the fetch on `isClassificationResult`.
- **Three new reference demos, each independently re-derived and
  cross-checked against the live API** (Phase 87-89): **RideSafe
  Detection** (`front_scene_object_detection`/
  `rear_scene_object_detection`, front camera F1 0.80 vs. rear F1 0.57);
  **PropertyWatch Detection** (entrance/storage/indoor, F1 0.821/0.667/
  0.529); **Robot/Drone Sensing** - the first generic robotics-ready
  reference example (`robot_front_rgb`/`sim_depth`/`sim_range`,
  synthetic, not added to `config/sensors.yaml`), `obstacle_detection`
  (camera F1 0.757 vs. depth-derived F1 0.611) and `distance_estimation`
  (a dedicated range sensor MAE 0.06 m vs. a depth-camera estimate MAE
  0.30 m) as task profiles over the same two generic evaluators, no new
  evaluator-specific logic. Explicitly never an autonomous navigation,
  drone control, or flight safety system - a dedicated overclaim scan
  enforces it. Kept clearly distinct in name/theme from the unrelated,
  older "Generic Sensor Evaluation Lab."
- **v0.8 robustness pass** (Phase 90): 11 dedicated tests at the real
  HTTP API level - malformed detection/regression values reach
  `/evaluate` as a clean `422`, unknown `evaluator_type` fails
  atomically (zero partial writes), all-N/A metrics flow through
  `/compare` without a crash, a full evaluate+compare round trip using
  zero v0.8 request fields anywhere still matches pre-v0.8 behavior
  exactly, empty detections on both sides never crash, and regression's
  common-set semantics (one matched pair is one sample, no frame-vs-object
  nuance) are pinned down explicitly. No genuine defects found - the
  whole v0.8 evaluator/comparison layer already held up.
- **New docs**: [docs/evaluators.md](docs/evaluators.md),
  [docs/detection-evaluation.md](docs/detection-evaluation.md),
  [docs/regression-evaluation.md](docs/regression-evaluation.md).
  Updated: `docs/evaluation.md` (evaluator_type/details on
  `EvaluationResult`, classification-only claim corrected),
  `docs/comparison.md` (generic metric deltas across evaluator types,
  evaluator-type-mismatch invalidity), `docs/decision-support.md`/
  `docs/profiles.md` (evaluator-blind evidence lookup noted),
  `docs/provenance.md` (evaluator identity as a fifth provenance
  dimension, new demo test files), `docs/limitations.md` (classification-
  only limitation resolved, new v0.8 scope boundaries added), `README.md`
  (quick-start sections for all three new demos, Roadmap, Documentation).

### Fixed (v0.8)

- **`/compare` crashed with an unhandled `500` for two `object_detection`
  configurations** (Phase 84) - the common-set re-evaluation always
  called `evaluate(match_result, {})`, and `object_detection` has no
  default `confidence_threshold`/`iou_threshold`. Fixed by threading
  `CompareRequest.parameters` through to the common-set call, wrapped in
  the same `ValueError -> 422` handling `/evaluate` already had.
- **A circular import between `evaluators.py` and the new
  `detection.py`** (Phase 82) - both needed each other's types. Fixed by
  extracting `Evaluator`/`EvaluatorOutput` into a new, minimal
  `evaluator_output.py` imported one-directionally by both, re-exported
  from `evaluators.py` for backward compatibility.
- **A robotics demo construction bug caught before shipping** (Phase 89)
  - an early draft of the Robot/Drone Sensing dataset emitted a duplicate
  ground-truth row per sensor for the shared `obstacle_detection` task,
  which would have silently doubled false-negative counts once evaluated
  through the real API. Caught by the demo's own independent-verification
  test before the data file was ever committed; fixed by sharing one
  ground-truth set per task, predictions varying only per sensor/config.

### Known limitations (v0.8)

- No `TaskDefinition` registry - `evaluator_type` is stated explicitly
  per `/evaluate` call, never remembered against a task name.
- No AP/mAP, no cross-frame object tracking, no segmentation masks, no
  oriented/rotated bounding boxes, no pixel-coordinate bbox input mode.
- No relative/percentage regression error, no vector regression.
- `/timeline` remains classification-only - a label-vs-label strip has
  no detection/regression analogue.
- The Evaluation panel's "Run Evaluation" button always calls
  `/evaluate` with no `evaluator_type`/`parameters` (defaults to
  classification) - fine for every shipped demo (results are
  pre-evaluated via each loader script's own API calls with the correct
  parameters), but running it live against a fresh detection/regression
  session from the browser would `422`. A parameters-input UI for
  `/evaluate`/`/compare` is a documented follow-up, not built in v0.8.
- Backend: 151 new tests (579 → 730). Frontend: 7 new tests (40 → 47),
  `tsc`/`oxlint` clean throughout.

## [0.7.0] — v0.7 resource observation & deployment trade-offs

Built phase by phase (Phase 64 through Phase 76), same discipline as
v0.1-v0.6: a 30-question architecture review *before* any code (plus an
explicit employer-independence verification, given this release's
public reference demos), explicit self-review checkpoints per phase,
nothing merged without running against a real container. Adds a
resource-observation layer with explicit provenance, joined with v0.6's
already-decided policy evidence into a trade-off/comparability/
constraint/generalized-Pareto layer — **never re-decides
`PASS`/`FAIL`/`N/A` or `PolicyStatus`**, never merges decision and
resource evidence into one score. No v0.1-v0.6 behavior changed. Full
domain model, algorithm, and API reference:
[docs/resources.md](docs/resources.md) /
[docs/deployment-tradeoffs.md](docs/deployment-tradeoffs.md).

This release also retires cabin/occupant-monitoring-style examples going
forward, replacing them with two independent personal-camera demo
families built around the author's own consumer hardware — see "Added"
below and [docs/provenance.md](docs/provenance.md) for the cross-cutting
evidence-honesty discipline this and every other layer share.

### Added

- **Resource domain foundation** (`backend/app/domain/resources.py`,
  Phase 64-65): `ResourceObservation` (pydantic, like `GroundTruth`/
  `Prediction` — persisted/ingested evidence, not a computed artifact)
  with `ResourceQuality` (`measured`/`declared`/`estimated`/
  `unavailable` — `value is None` iff `quality == 'unavailable'`,
  enforced both directions) and `SUPPORTED_RESOURCE_METRICS` (the
  reviewed six: `cpu_percent`, `memory_mb`, `network_receive_mbps`,
  `network_transmit_mbps`, `fps`, `pipeline_latency_ms` — GPU/power/
  temperature/storage-write explicitly excluded, no hardware to verify
  them against). `ExecutionPlatform` + `UNKNOWN_PLATFORM_ID` (an
  unresolved platform is never comparable, even to itself). New
  migration `0004_resource_observations.sql`;
  `insert_resource_observations_batch`/`list_resource_observations`
  follow the exact batch-insert/filtered-query pattern `predictions`
  already uses.
- **Resource collection** (`backend/app/resource_collector.py`, Phase
  66): `SystemMetricsWindow` (`cpu_percent`/`memory_mb`/
  `network_receive_mbps`/`network_transmit_mbps` via the same `psutil`
  primitives `system_diagnostics_node` already uses, bound to an
  explicit `start()`/`end()` window instead of a permanent background
  loop) and `collect_sensor_metrics` (`fps`/`pipeline_latency_ms` — a
  pure translation of already-published `fps_received`/
  `publish_latency_ms` diagnostics, not a new measurement). Never
  fabricates a value: a zero-duration window's network rate and a
  sensor absent from the diagnostics snapshot both report explicit
  `unavailable` rows. Measured collector overhead documented directly
  in the module: ~0.27ms per `start()`/`end()` pair.
- **Resource summaries** (Phase 67): `ResourceMetricSummary`
  (mean/median/p95/min/max/sample_count/unit/quality) and
  `compute_resource_metric_summary` — pure aggregation over
  already-persisted rows, `None` (never a fabricated zero) for an empty
  or all-`unavailable` population, raises on mismatched units rather
  than silently averaging incompatible quantities.
  `ConfigurationResourceProfile` — `validity`
  (`complete`/`partial`/`unavailable`) derived from how many requested
  metrics have real evidence; `measurement_window` honestly spans the
  full range across contributing rows, gaps included.
- **Trade-off engine** (Phase 68-69): `ConfigurationTradeoff` +
  `build_configuration_tradeoff` — pure composition joining v0.6's
  `ConfigurationDecision` with an optional `ConfigurationResourceProfile`.
  `check_comparability` — platform/resolution/target-FPS match, plus
  same-order-of-magnitude measurement duration (10x heuristic bound);
  `comparable` and `warnings` always travel together, never one without
  the other. `compute_resource_delta` — observed-only wording ("+5.1
  Mbps," never "caused"), grep-verified by a dedicated non-causal-
  language test. Resource constraints reuse `AcceptanceCriterion`
  directly (`ACCEPTANCE_OPERATORS` promoted from coverage.py's private
  `_OPERATORS`, zero behavior change) — `evaluate_resource_constraint`
  reports `na` (never `fail`) for an unmeasured metric.
  `evaluate_resource_qualification` — a direct 3-state map
  (`qualifies`/`does_not_qualify`/`undetermined`), deliberately **not**
  `evaluate_policy`'s best/worst-case N/A-resolution bounding, since a
  missing resource measurement has no "will resolve later" property.
  `find_pareto_front_general`/`dominates_general` — a mechanical
  generalization of decision.py's fixed 3-dimension Pareto to an
  arbitrary caller-chosen dimension dict, proven equivalent to the
  original on every scenario decision.py's own suite covers. No
  `overall_efficiency_score`/`deployment_score`/any combined number
  anywhere — grep-verified as an actual field definition, not a
  docstring mention.
- **Resource + trade-off API** (`backend/app/api/sessions.py` /
  `profiles.py`, Phase 70): `POST /{id}/resource-observations/batch` +
  `GET /{id}/resource-observations` (loose-dict/partial-failure pattern,
  identical to ground-truth/predictions). `POST /{id}/tradeoffs` — joins
  v0.6 decision evidence with v0.7 resource evidence, reusing
  `_resolve_configuration_ids`/`_compute_requirement_results_by_configuration`
  exactly like `/coverage`/`/analysis`/`/decision-analysis`; takes one
  required `session_id` (resource evidence is inherently
  single-session-scoped), validates `resource_metrics`/
  `resource_constraints`/`pareto_dimensions` against the supported
  vocabulary, and carries an optional nested `resource_comparison`
  section (same "`gap_analysis` on `/decision-analysis`" pattern).
- **Resource UI + trade-off UI** (`ProfileDetail.tsx`'s new Resources
  tab, Phase 71-72): `ResourcesPanel.tsx` — session picker, per-
  configuration resource table, drill-down (mean/median/p95/min/max,
  quality+platform badge, an inline-SVG time-series chart, contributing-
  observations list). `ResourceQualityBadge.tsx` —
  `MEASURED`/`DECLARED`/`ESTIMATED`/`UNAVAILABLE`/`MIXED`.
  `QualificationBadge.tsx` — the v0.7 counterpart to
  `PolicyStatusBadge`. `ResourceConstraintForm`/`QualificationTable`/
  `ResourceComparisonSection`/`ResourceParetoSection` — reuse the
  Decision tab's own acceptance-criterion form shape, render backend-
  computed qualification directly (never recomputed client-side), and
  keep comparability warnings always visible alongside the numbers they
  qualify.
- **`ResourceMetricSummary.quality` gap found and fixed while building
  the UI** (Phase 71): the original Phase 67 shape had no way to report
  which quality tier(s) actually contributed to a computed mean — added
  `'mixed'` so a badge can never misrepresent a part-`declared` value as
  plainly "MEASURED."
- **RideSafe demo** (Phase 73): 70mai front/rear dashcams, framed
  strictly as *ride monitoring and incident evidence* — never safety-
  certification, driver-monitoring, or occupant-monitoring. Two
  sessions (day/night), three configurations, four requirements, plus
  synthetic resource data telling a "two cameras share some overhead"
  story. Its day-only Resources-tab view honestly shows `undetermined`
  policy status for every configuration (it can't see the
  night-conditioned requirements) even though coverage percentages
  still differ — documented, not a bug.
- **PropertyWatch demo** (Phase 74): a generic multi-camera property
  monitoring setup — home, garage, workshop, storage space, or small
  warehouse, never one hardcoded building type, no surveillance-
  identification or face-recognition. Three nested configurations
  (entrance-only → +storage → +storage+indoor), one task per camera
  position (a camera-less area is genuinely N/A, never a fabricated
  fail), a "roughly linear per added camera" resource story, and a
  genuine 3-point Pareto staircase — the flagship "is the third camera
  worth its resource load" worked example. Caught and fixed a real
  pre-shipping bug in its own generator script: `entrance`/`storage`/
  `indoor` sensor ids are not alphabetically pre-ordered (unlike
  RideSafe's `front`/`rear`), so building `configuration_id` from
  insertion order would have silently produced the wrong id.
- **Jetson / cross-platform validation reviewed and explicitly deferred**
  (Phase 75, issue #76, closed): no Jetson Orin or any second machine
  was reachable in the environment this release was built in — confirmed
  via SSH/hostname resolution, not assumed. No cross-platform numbers
  fabricated to fill the gap. `ExecutionPlatform` gained zero
  Jetson/NVIDIA-specific fields either way, per the issue's own
  out-of-scope note.
- **Resource-layer robustness pass** (Phase 76, issue #77):
  `test_resource_robustness.py`, 13 dedicated tests — missing metrics,
  a failed measurement, a partial time series, inconsistent platform
  metadata, cross-platform comparison, invalid/mixed units, a genuine
  zero value, resource evidence with no coverage result and vice versa,
  a synthetic/physical mixture, all-N/A constraints, and two malformed
  `/tradeoffs` request shapes.
- **136 new backend tests** (443 → 579) across every phase above. **10
  new frontend vitest tests** (34 → 40, `format.ts`'s
  `formatResourceValue`, Phase 71) — the Resources/trade-off UI itself
  was live-verified via Playwright against the real running stack at
  every phase instead, same convention as v0.5/v0.6.
- `docs/resources.md` (new), `docs/deployment-tradeoffs.md` (new),
  `docs/provenance.md` (new); `README.md`, `docs/decision-support.md`,
  `docs/limitations.md` updated for the resource/trade-off layer.

### Fixed

Two real defects, both caught by writing this release's own Phase 76
robustness tests before shipping — the same "a failing test exposes it,
then the minimal fix closes it" discipline as v0.6's `evaluate_policy`
completeness fix:

- **Mixed units for the same metric/configuration crashed `/tradeoffs`
  with an unhandled `500`.** `unit` is a deliberately open string at
  ingestion, so nothing stopped two rows for one metric from disagreeing
  — `compute_resource_metric_summary`'s own `ValueError` was never
  caught in the API handler. Now a clean `422` naming the offending
  configuration.
- **Resource evidence was silently dropped for a configuration with no
  coverage result.** A `configuration_id` that only ever appears in
  resource observations (never in any prediction, so no decision
  evidence exists) had its `resource_profile` unconditionally reported
  as `null` when explicitly requested — even though real resource rows
  existed for it. Decision and resource evidence are independent axes;
  fixed by extracting `_fetch_configuration_resource_profile`, now
  shared by both the decision-evidence loop and the no-evidence loop.

### Known limitations

Only six resource metrics are supported (no GPU/power/temperature/
storage-write — no hardware to verify them against in this release's
environment); a `ResourceObservation`'s `unit` is fully open at
ingestion, not validated against the supported-metric table;
`measurement_window` is never cross-checked against a session's own
evaluation-evidence timespan; resource evidence is measured from inside
whichever container the collector runs in (same Docker-Desktop-VM
caveat v0.1's diagnostics already carries, now extended to network
metrics); cross-platform comparability has only been exercised against
one real platform (Jetson validation explicitly deferred, issue #76);
the generalized Pareto front is O(n²), same bound as v0.6's fixed
version; and `TradeoffResponse` is never persisted (recomputed fresh
every call). Full list: [docs/limitations.md](docs/limitations.md).

## [0.6.0] — v0.6 decision support & minimum sufficient sensor set

Built phase by phase (Phase 53 through Phase 62), same discipline as
v0.1-v0.5: a 25-question architecture review *before* any code, explicit
self-review checkpoints per phase, nothing merged without running
against a real container. Adds a policy-driven decision layer on top of
v0.4's already-computed `RequirementResult`/`AggregateCoverage` evidence
— **never re-decides `PASS`/`FAIL`/`N/A`**, never re-implements v0.5's
condition matching/grouping. No v0.1-v0.5 behavior changed. Full domain
model, algorithm, and API reference:
[docs/decision-support.md](docs/decision-support.md).

### Added

- **`DecisionPolicy`/`PolicyStatus` foundation** (`backend/app/domain/decision.py`,
  Phase 53): `DecisionPolicy` (`minimum_requirement_coverage`,
  `minimum_evidence_completeness`, `mandatory_requirements_must_pass`,
  `objective`) — no default on any field, an omitted policy is always
  `422`, never silently applied. `PolicyStatus`
  (`sufficient`/`insufficient`/`undetermined`) — never a binary good/bad.
  Phase 57 (sensor-identity/ROS migration) reviewed and explicitly
  deferred in the same architecture review: `Prediction.sensor_ids` was
  already a free-form `list[str]` with zero ROS/modality coupling, so
  `front_rgb`/`rear_rgb` needed no new identity model to be separable
  configuration members.
- **Policy/minimality/dominance engine** (Phase 54):
  `evaluate_policy` — completeness checked against the population's
  *real* N/A count (never hypothetically resolved, since it can only
  improve as N/A resolves — a shortfall is always `undetermined`, never
  `insufficient`); coverage/mandatory-pass bounded via best-case/worst-
  case N/A-resolution hypotheticals. `find_minimal_sufficient_sets` —
  strict set-inclusion minimality (`frozenset` proper-subset check), not
  sensor-count sorting; returns every tied minimal configuration, sorted
  deterministically. `find_dominated_configurations`/`find_pareto_front`
  — `A` dominates `B` iff same-or-fewer sensors, same-or-better coverage
  *and* completeness, strictly better in ≥1 dimension; `None` treated as
  strictly worse than any real value, two `None`s tie; O(n²) pairwise,
  bounded by evaluated-configuration count, never a generated power set.
- **Requirement gap engine** (Phase 55): `compute_requirement_transitions`
  — four separately-exposed categories (`fail_to_pass`/`na_to_pass`/
  `pass_to_fail`/`pass_to_na`), never collapsed into one delta; raises on
  a mismatched requirement population rather than diffing a meaningless
  comparison. `compute_condition_gap_summary` — reuses v0.5's
  `group_by_condition` per side, then subtracts bucket-by-bucket, no
  grouping logic duplicated. `find_direct_removals` — scoped wording only
  ("removable without violating the current policy" /
  "policy-critical within this configuration"), `NO EVIDENCE` (both
  `configuration_id`/`policy_status` `None`) for a removal never
  evaluated, never estimated. `analyze_sensor_addition` — composes
  added/removed sensor ids (reusing v0.3's `classify_relationship`
  set-difference directly), coverage/completeness deltas, transitions,
  and both configurations' policy status into one structured result —
  deliberately many small fields, never a single `importance_score`.
- **Decision API** (`backend/app/api/profiles.py`, Phase 56):
  `POST /{profile_id}/decision-analysis` — one consolidated endpoint, not
  a second `/gap-analysis` route; `gap_analysis` is an optional nested
  request/response section reusing `/coverage`/`/analysis`'s exact
  evidence-gathering helpers. A named-but-never-evaluated
  `configuration_id` reports `policy_status: null` with empty
  `sensor_ids` — `NO EVIDENCE`, never silently dropped. A
  `gap_analysis.baseline_configuration_id`/`candidate_configuration_id`
  naming a configuration with no evidence in this analysis is `422`
  (nothing real to compare); the removal sweep instead reports each
  removal, `NO EVIDENCE` and all. `repo.get_sensor_ids_for_configuration`
  added — fetches sensor ids from a representative persisted prediction,
  never reverse-parses the `configuration_id` string itself.
- **Decision UI** (`ProfileDetail.tsx`'s new Decision tab, Phase 58-60):
  `DecisionPanel.tsx` — an editable policy form (objective shown but
  disabled, since only `minimize_sensor_count` exists), the condition
  facet filters reused from v0.5, and a per-configuration summary table.
  `PolicyStatusBadge.tsx` — four states, `sufficient`/`insufficient`/
  `undetermined`/`null` (rendered "No evidence"), always distinguishing
  "policy not met" from "never evaluated." `MinimalSufficientSets` — one
  card per tied minimal configuration, each showing exactly which policy
  criteria it met and why, never narrowed to one. `ParetoFront` — the
  non-dominated trade-off table shown prominently, dominated
  configurations collapsed underneath and labeled `Dominated`, never
  "bad." `GapAnalysisSection` — baseline/candidate pickers (populated
  only from already-evaluated configurations), a sensor-removal-sweep
  checkbox, the four transition counts as clickable buttons opening a
  drill-down built from the candidate's own `requirement_results` —
  reusing `CellDrillDown`/`RequirementDrillDown` verbatim, never a new
  requirement detail renderer. `SensorChips` renders a `SourceTypeBadge`
  only when a sensor id has a matching `config/sensors.yaml` entry,
  otherwise the id alone with no badge — graceful degradation, never an
  error.
- **Front/rear camera synthetic decision demo** (Phase 61):
  "Generic Exterior Sensing Decision Demo" — a second, genuinely
  different synthetic profile/dataset from the cabin-safety demo, not a
  variant squeezed into it. Four reference sensor ids (`front_rgb`,
  `rear_rgb`, `sim_thermal`, `sim_depth`), four accuracy requirements
  (50%/70%/85%/97%), eight configurations — hand-verified (independently,
  via plain-Python re-derivation with zero `app.domain.decision` imports)
  to produce exactly one minimal sufficient configuration
  (`cfg-front_rgb-rear_rgb-sim_thermal`) and a clean four-point Pareto
  trade-off curve. `front_rgb`/`rear_rgb`/`sim_thermal`/`sim_depth`
  deliberately **not** added to `config/sensors.yaml` — doing so would
  trip the one-sensor-per-modality live-ingestion launch guard
  (`front_rgb`/`rear_rgb` share modality `rgb`;
  `sim_thermal`/`sim_depth` would collide with the already-live
  `thermal`/`depth` entries) — `SensorChips`' graceful no-badge fallback
  covers display instead. A standing "SYNTHETIC DECISION DEMO" banner on
  the Decision tab, gated on the profile's own
  `metadata.synthetic: true`. `scripts/load_decision_demo_data.py` added,
  ending its summary with a `/decision-analysis` call (policy status,
  minimal set, Pareto front) rather than `/coverage`.
- **54 new backend tests** (389 → 443) — the `DecisionPolicy`/
  `PolicyStatus` contract, `evaluate_policy`'s every branch (including
  the completeness-is-always-undetermined case), minimality/dominance
  (subset exclusion, multi-way ties, `None`-handling), the gap engine
  (transitions, condition deltas, direct removals, sensor-addition
  composition), the `/decision-analysis` API's wiring and malformed-
  request handling, the synthetic demo's independent verification, and a
  dedicated Phase 62 robustness pass (a zero-sufficient-configuration
  set, an every-configuration-sufficient set, a three-way disjoint
  minimal-set tie, non-subset identical-coverage dominance, a
  removal-sweep `NO EVIDENCE` case, an N/A-heavy configuration landing
  `undetermined` through the real pipeline, a mandatory-requirement
  failure forcing `insufficient` through the real pipeline, a legacy
  v0.4/v0.5-conditioned profile working unchanged against
  decision-analysis, and two more malformed-request shapes). **No new
  frontend unit tests this release** — the Decision tab's UI was
  live-verified via Playwright against the real running stack at every
  phase instead, same convention as v0.5; frontend suite stays 34/34.
- `docs/decision-support.md` (new); `README.md`, `docs/profiles.md`,
  `docs/coverage.md`, `docs/condition-explorer.md`, `docs/comparison.md`,
  `docs/limitations.md` updated for the decision-support layer.

### Fixed

One real bug, caught by this project's own before-it-ships discipline (a
failing test written to lock in the intended semantics) before the phase
that introduced it was committed:

- **`evaluate_policy`'s initial draft bounded evidence completeness the
  same best-case/worst-case way as coverage.** Because "every N/A
  resolved" always means completeness = 1.0 in *both* hypotheticals, the
  `minimum_evidence_completeness` threshold could never actually fire —
  a 5-pass/0-fail/5-na aggregate against a 0.5/0.95 policy incorrectly
  returned `sufficient` instead of `undetermined`. Fixed by checking
  completeness against the population's real, current N/A count
  directly, before any best/worst-case branching — documented
  permanently as a code comment on `PolicyStatus` itself so the
  reasoning survives past the commit that fixed it.

### Known limitations

`DecisionPolicy.objective` supports only `minimize_sensor_count` (no
cost/power/latency objective exists yet), `mandatory_requirements_must_pass`
is an all-or-nothing population flag rather than a per-requirement scoped
list (`Requirement` still has no `mandatory` field), dominance/Pareto
computation is O(n²) bounded by evaluated-configuration count,
`DecisionAnalysisResponse` is never persisted (recomputed fresh every
call), and sensor-identity/ROS migration for live simultaneous dual-
camera *viewing* remains deferred and unchanged from before v0.6 — this
release's decision-support feature never needed it. Full list:
[docs/limitations.md](docs/limitations.md).

## [0.5.0] — v0.5 condition explorer & evidence analysis

Built phase by phase (Phase 42 through Phase 51), same discipline as
v0.1-v0.4: a 22-question architecture review *before* any code, explicit
self-review checkpoints per phase, nothing merged without running
against a real container. Adds a pure analysis/exploration layer on top
of v0.4's already-computed `RequirementResult`/`GroupCoverage` evidence
— **never re-decides `PASS`/`FAIL`/`N/A`**, only filters, groups,
cross-tabulates, and explains what v0.4 already decided. No v0.1-v0.4
behavior changed; two v0.4.0-tagged files (`evidence.py`, `coverage.py`)
were touched only for behavior-preserving helper extraction, each
re-verified against the full existing test suite plus a live curl check
against real persisted data before and after. Full domain model,
algorithm, and API reference:
[docs/condition-explorer.md](docs/condition-explorer.md).

### Added

- **Filter/facet engine** (`backend/app/domain/analysis.py`):
  `AnalysisFilter` (conditions/group_id/task/status, flat AND-ed
  predicates — no query DSL), `discover_facets` (one pass over
  `profile.requirements[*].conditions`, no evidence needed), and
  `filter_requirement_ids`/`filter_results` — filtering is over a
  requirement's *own declared conditions*, never a resolved session's
  metadata. Missing condition key always excludes, never wildcards.
  Reuses v0.4's exact type-sensitive subset-match rule, extracted from
  `evidence.py`'s private `_values_match`/`matches_conditions` into
  public `values_match`/`conditions_are_subset` (Phase 43) rather than
  reimplementing the bool/int-collision guard a second time.
- **Aggregation + grouping** (Phase 44): `AggregateCoverage` and
  `aggregate_requirement_results` reuse `coverage.py`'s exact
  `status_counts`/`coverage_and_completeness` formulas (promoted to
  public) so a filtered summary can never silently disagree with v0.4's
  own arithmetic. `group_by_condition` (1D breakdown) and
  `cross_tabulate` (2D cross-tab) — a result missing a grouped condition
  key is excluded, never lumped into an "unknown" bucket.
  `failure_breakdown`/`top_failing_groups` reuse the identical recursive
  group-tree walk `compute_configuration_coverage` uses
  (`aggregate_group_tree`, extracted without the "exactly one result per
  requirement" invariant, which doesn't apply to arbitrary filtered
  subsets). `classify_na_reason`/`na_breakdown` pattern-match the real
  free-text reason strings `evidence.py`/`coverage.py` already produce
  — a deliberate, explicitly-stated coupling, guarded by a mandatory
  cross-layer test that constructs every real N/A scenario through the
  actual `select_evidence`/`evaluate_requirement` functions, not
  hand-typed strings.
- **Analysis API** (`backend/app/api/profiles.py`, Phase 45+48):
  `GET /{profile_id}/facets`, `POST /{profile_id}/analysis` — one
  consolidated endpoint (not four separate routes); `group_by`'s length
  (0/1/2) selects filtered-summary/breakdown/cross-tab shape. Reuses
  `/coverage`'s exact evidence-gathering helpers
  (`_resolve_sessions`/`_resolve_configuration_ids`/
  `_compute_requirement_results_by_configuration`, extracted so neither
  route duplicates the other). Each `ConfigurationAnalysis` also carries
  `failure_root` and `na_breakdown`, scoped to the same filtered
  population as everything else on the response. `GET
  /sessions/{id}/profile-usage` (Phase 45) — reverse lookup defined as
  *candidacy* (reuses `matches_conditions` directly), not resolution: a
  session that lost an ambiguity contest still shows up, since "could
  this be evidence" is a different question than "is this the resolved
  evidence."
- **Explorer UI** (`ProfileDetail.tsx` restructured into
  Coverage/Explorer/Failures/Evidence tabs, Phase 46-49): Coverage's
  existing matrix logic moved under a tab unchanged, live-verified
  byte-identical to its pre-v0.5 behavior. `ExplorerPanel.tsx` — dynamic
  filter controls built from `GET .../facets` (no hardcoded condition
  names anywhere), a filtered configuration summary table, a condition
  breakdown section, and a 2D cross-tab section, each fetching via a
  shared `hooks/useAnalysis.ts`. Filter/tab state lives in
  `useSearchParams`, URL-addressable
  (`?tab=explorer&illumination=night&status=fail`), same pattern
  `Comparison.tsx` established. `components/ConditionCrossTab.tsx` — a
  generic row×column grid, reused verbatim for both the single-
  configuration cross-tab and the configuration×condition-value
  "heatmap"; every cell shows its requirement-count denominator (`n=X`)
  always visible, never hover-only. `components/CellDrillDown.tsx` —
  single-match cells reuse `RequirementDrillDown` directly, multi-match
  cells get a plain selectable list, never a second bespoke detail view.
- **Failure + N/A explorer** (Phase 48): `FailuresPanel.tsx` — total
  failure count, a top-failing-groups list, and a failing-requirements
  list. `NABreakdownPanel.tsx` — `na_breakdown` split into "experiment
  never performed" (`no_matching_evidence`) versus "evaluation gap"
  (`ambiguous_evidence`/`missing_metric`/`other`), per the master
  prompt's own framing of why that distinction matters. Every list row
  shows its evidence quality (`matched_samples`/`sample_count`/
  `coverage`) directly alongside its `StatusBadge`, always visible — no
  derived "LIMITED EVIDENCE" badge or threshold, per the architecture
  review's explicit rejection of one.
- **Evidence traceability** (Phase 49): `RequirementDrillDown` enhanced
  to render the full Profile → Group → Requirement → Conditions →
  Evidence → Session → Scenario → Configuration → Prediction source →
  Evaluation result → Sample counts → Acceptance criteria → Result
  chain — real scenario/session *names* (not raw ids, resolved via the
  same `GET /api/scenarios`/`GET /api/sessions/{id}` calls
  `SessionDetail.tsx` already made) and a link to the session's own
  page. Zero new backend fields — every field was already on
  `RequirementResult`/`EvidenceReference`. `SessionDetail.tsx` gained a
  "Used by profiles" section calling `GET .../profile-usage`, listing
  each matching profile and the specific requirement *names* referencing
  this session; zero matches renders a clean explanatory message, not an
  error.
- **Multidimensional synthetic demo** (Phase 50): `cabin-safety-demo.json`
  / `cabin-safety-demo-data.json` extended **in place** (not a second
  profile) with a third condition dimension, `eyewear` (none/glasses) —
  2 new sessions, 2 new requirements, a new "Eyewear Robustness" group.
  Deliberately not a full Cartesian product with `occlusion`. The
  original 4 sessions' ground truth/predictions are byte-identical to
  before — only metadata gained a key. Glasses accuracy targets tell a
  clean story: a mild uniform tax on every configuration except thermal,
  which flips from `pass` to `fail` at night under the *same* threshold
  — a condition dimension changing an outcome, not just a number.
  `scripts/generate_profile_demo_data.py` verified byte-identical across
  runs; `test_profile_demo.py`'s independent verification now covers all
  40 requirement×configuration cells (was 30).
- **80 new backend tests** (309 → 389) — filter/facet engine,
  aggregation/grouping, the analysis API, the failure/N/A explorer, the
  extended synthetic demo's independent verification, and a dedicated
  Phase 51 robustness pass (a zero-condition-dimension profile, an
  undeclared-condition-key filter, mixed boolean/string condition
  values, a 2000-requirement profile's responsiveness, an ordinary
  v0.4-only profile, missing `Session.metadata`, and four `/analysis`
  malformed-request shapes). **No new frontend unit tests this release**
  — v0.5's page-level UI was live-verified via Playwright against the
  real running stack at every phase instead, matching this project's
  existing convention that only pure functions (`format.ts`,
  `groupTree.ts`) get `vitest` coverage; frontend suite stays 34/34.
- `docs/condition-explorer.md` (new); `docs/profiles.md`,
  `docs/coverage.md`, `docs/comparison.md`, `docs/evaluation.md`,
  `README.md`, `docs/limitations.md` updated for the condition-
  exploration layer.

### Fixed

Three real bugs, each caught by this project's own live-verification
discipline (Playwright against the real running stack, or a mandatory
cross-layer test) before the phase that introduced them was committed —
listed here because the catching mechanism is the actual guard, and a
future contributor should be able to see it worked, not just that the
code looks right in hindsight:

- **`classify_na_reason`'s initial rule table** assumed the multi-
  prediction-source ambiguity message contained the word "ambiguous" —
  it doesn't (only the multi-session case does). Caught immediately by
  the mandatory cross-layer test, which constructs the scenario via real
  `select_evidence` calls rather than hand-typed strings.
- **`ConditionCrossTab`'s column headers** showed only the dimension
  name (e.g. "OCCLUSION") spanning every column, with no per-column
  value label ("none"/"partial") underneath — cells were visually
  indistinguishable by column. Caught via a live screenshot during
  Phase 47 verification; fixed by adding a second header row.
- **The Failures tab's top-failing-groups list** included the synthetic
  group-tree aggregation root (`group_id: null`) as if it were a real
  named group. Caught via live hand-verification against the Cabin
  Safety Demo during Phase 48; fixed by excluding `group_id === null`,
  the same exclusion `CoverageMatrix.tsx` already applied.

### Known limitations

`/analysis`'s `group_by` supports at most 2 dimensions (no simultaneous
3+-dimension cross-tab), `classify_na_reason` is coupled to
`evidence.py`/`coverage.py`'s exact free-text reason strings, filter/tab
state lives only in the URL (no saved/named presets), `AnalysisResponse`
is never persisted (recomputed fresh every call, same decision as
`RequirementResult`), reverse session lookup is candidacy — not
resolution, and not a full dependency-graph visualization. Full list:
[docs/limitations.md](docs/limitations.md).

## [0.4.0] — v0.4 requirement profiles & coverage

Built phase by phase (Phase 30 through Phase 40), same discipline as
v0.1-v0.3: an architecture review and 24-question self-review *before*
any code, explicit self-review checkpoints per phase, nothing merged
without running against a real container. Adds a requirement-profile
layer entirely inside the existing `backend` container, consuming v0.2's
`EvaluationResult`s and reusing v0.3's exact multi-source-ambiguity rule
rather than rewriting either — no v0.1/v0.2/v0.3 behavior changed. Full
domain model, algorithm, and API reference:
[docs/profiles.md](docs/profiles.md) / [docs/coverage.md](docs/coverage.md).

### Added

- **Profile domain model** (`backend/app/domain/profiles.py`):
  `EvaluationProfile`, `RequirementGroup` (adjacency-list hierarchy,
  arbitrary depth), `Requirement`, `AcceptanceCriterion`. Conditions are
  an open `dict[str, str | float | bool]` — never a fixed column set —
  proven by tests using domain-unrelated condition keys alongside the
  spec's own examples with zero code differences. No `mandatory`/
  `weight` field (neither has an aggregation semantic defined yet — an
  unused field would invite premature use). `validate_profile` collects
  every structural problem (duplicate ids, dangling references, parent-
  group cycles, blank tasks, non-finite thresholds, an empty profile) in
  one pass, never fails fast.
- **Profile persistence + API** (`backend/app/api/profiles.py`,
  migration `0003_profiles.sql`): one JSON document per profile, not
  normalized into group/requirement tables — a profile is always read
  whole, never queried partially. `POST /api/profiles` (two-layer
  validation — Pydantic structural checks, then `validate_profile` for
  cross-field problems — either both pass or nothing persists; 409 on
  duplicate id), `GET /api/profiles`, `GET /api/profiles/{id}`. No
  update, no delete — profiles are immutable; a changed profile is a new
  id/version.
- **Evidence selection** (`backend/app/domain/evidence.py`): a
  requirement's condition map matches a session iff every key is present
  in `Session.metadata` with an exactly equal, type-sensitive value
  (Python's `1 == True` explicitly guarded against). Zero or multiple
  matching sessions is always `N/A` with a reason — never a silent pick.
  Reuses v0.3's exact prediction-source-ambiguity rule for the
  single-session-multiple-sources case. An explicit `EvidenceBinding`
  overrides discovery (and condition matching) entirely — request-scoped
  only, never persisted.
- **Acceptance engine** (`backend/app/domain/coverage.py`): all five
  operators; `"coverage"` resolves from the same `ComparisonMetrics`
  v0.3 already computes, not a second formula; an unresolvable metric is
  always `na`, never `fail`. Requirement-level status priority: `na` (no
  evidence) → `na` (any unresolvable criterion, even with everything
  else passing — deliberately stricter than "AND over only the known
  criteria") → `fail` (any failed criterion) → `pass`.
- **Coverage engine**: recursive leaf-count group aggregation via the
  group tree's adjacency list — a group's counts are its own
  requirements' counts plus the sum of its children's, never an average
  of child percentages (proven by a dedicated test: a 1-requirement
  100%-coverage group and a 10-requirement 10%-coverage group aggregate
  to ~18.2%, not the naive ~55% average). `requirement_coverage` =
  pass/(pass+fail); `evidence_completeness` = (pass+fail)/total — both
  `None`, never a fabricated 0, when their denominator is 0. No
  profile-level `PASS`/`FAIL`/`INCOMPLETE` status anywhere — raw counts
  and both percentages only, at every level.
- **Profile UI** (`frontend/src/pages/Profiles.tsx`,
  `ProfileDetail.tsx`): list with JSON-paste import (validation errors
  render as one bullet per problem — fixed a real bug during
  verification where two errors were rendering as one malformed run-on
  line), a read-only arbitrary-depth hierarchy tree
  (`frontend/src/groupTree.ts`).
- **Coverage Matrix UI** (`components/CoverageMatrix.tsx`): configurations
  as columns, the requirement tree as rows, `PASS`/`FAIL`/`N/A` cells via
  a new `StatusBadge`. Group summary rows always show raw counts
  alongside *both* coverage percentages together — never one alone.
  Collapsing a group hides its descendants but keeps its own summary
  row visible; search hides only groups with zero matching descendants.
- **Evidence drill-down** (`components/RequirementDrillDown.tsx`): the
  first modal in this codebase. Sourced entirely from fields already on
  `RequirementResult` — no second backend call. Shows the requirement,
  an explicit "why it failed"/"why N/A" reasons block whenever status
  isn't `pass`, the full evidence reference, and every criterion's
  observed/threshold/status — a `PASS`/`FAIL`/`N/A` badge is never shown
  without also showing why.
- **Synthetic reference profile** ("Generic Cabin Safety Demo" —
  deliberately not NCAP or any regulatory framework):
  `examples/profiles/cabin-safety-demo.json` +
  `cabin-safety-demo-data.json`, four sessions (one per
  `illumination`×`occlusion` combination), five configurations, six
  requirements across three groups, every accuracy exact by
  construction. Targets deliberately give each configuration a
  genuinely different pass/fail pattern: `rgb` 1/6 (17%), `depth` 2/6
  (33%), `thermal` 3/6 (50%), `rgb+thermal` 4/6 (67%),
  `rgb+depth+thermal` 6/6 (100%). Independently verified — all 30
  requirement×configuration cells recomputed in plain Python without
  importing any production coverage code, cross-checked against the real
  API, same rigor as the v0.2/v0.3 demo guards.
- **137 new backend tests** (172 → 309), **10 new frontend tests** (24 →
  34) — profile models/validation, persistence/API, evidence selection,
  acceptance engine, coverage aggregation, UI, drill-down, the synthetic
  demo, and a dedicated robustness pass (malformed profiles at the API
  layer, ambiguous prediction sources, unknown metrics, partial evidence
  mixing resolved and N/A requirements in one call, a legacy pre-v0.4
  session with empty `Session.metadata` degrading to N/A cleanly, and
  two profile versions coexisting independently).
- `docs/profiles.md`, `docs/coverage.md` (new); `docs/evaluation.md`,
  `docs/comparison.md`, `README.md`, `docs/limitations.md` updated for
  the requirement-profile layer.

### Fixed

- **Profile import validation errors rendered as one malformed run-on
  bullet** instead of one bullet per problem (`"duplicate group id
  'g1',profile has no requirements"`, no space, single `<li>`) — caused
  by re-splitting an already array-stringified error message on `", "`
  instead of reading the parsed JSON `detail` array directly. Found
  during Playwright verification, fixed with a dedicated fetch in the
  import form that preserves the structured error list.

### Known limitations

Conditions are flat scalars only (no nested condition maps), no
weighted/mandatory-requirement aggregation, `RequirementResult`s are
never persisted (recomputed fresh on every `/coverage` call), an
unfiltered `/coverage` call can surface unrelated configurations from
other standing demo data as all-N/A (correct discovery behavior, but
visually noisy — use `session_ids`/the frontend checkboxes to scope it),
no condition-exploration UI yet (the metadata a later release would need
already exists). Full list: [docs/limitations.md](docs/limitations.md).

## [0.3.0] — v0.3 configuration comparison

Built phase by phase (Phase 20 through Phase 28), same discipline as
v0.1/v0.2: explicit self-review checkpoints per phase, nothing merged
without running against a real container. Adds a comparison layer
entirely inside the existing `backend` container, consuming v0.2's
already-persisted `EvaluationResult`s rather than rewriting anything —
no v0.1/v0.2 behavior changed. Full domain model, algorithm, and API
reference: [docs/comparison.md](docs/comparison.md).

### Added

- **Comparison domain model** (`backend/app/domain/models.py`):
  `PairwiseComparison`, `ComparisonValidity`, `ComparisonSide`,
  `ComparisonMetrics`, `MetricDelta`. `reported` and `common_set` share
  one `ComparisonSide` shape and are always both computed together — no
  caller-selected mode. `ComparisonValidity` enforces its own invariant
  at construction (`status != 'valid'` requires a non-empty `reasons`),
  so a silently-flagged-but-unexplained warning can't happen even by
  omission. `baseline_source_id`/`candidate_source_id` were added after
  an expanded self-review found the original shape resolved a source
  internally but never carried it onto the output, breaking full
  evidence traceability. No `Experiment` entity (a comparison request's
  own fields already are what one would hold) and no persistence
  (recomputed fresh from already-persisted evidence on every call) —
  both decisions recorded directly in the module docstring.
- **Comparison engine** (`backend/app/domain/comparison.py`): pure
  functions, zero `fastapi`/`sqlite3`/`rclpy` imports.
  `classify_relationship` (`direct_addition`/`direct_removal`/`general`
  via plain `sensor_ids` set difference, never a `configuration_id`
  string parse); `compute_metric_delta` (absolute/relative, `None` on
  either missing input or a zero baseline — never a `ZeroDivisionError`);
  common-set intersection by `GroundTruth.id` on already-matched pairs
  (deliberately not a re-run of `match_by_timestamp` on a subset, which
  isn't guaranteed to reproduce the original match); `assess_validity`
  (invalid on zero common samples or self-comparison, warning on a low
  common-sample count or large coverage difference — both thresholds
  heuristic and documented as such).
- **Comparison API** (`backend/app/api/comparison.py`): `GET
  .../configurations` (sensor_ids, distinct source_ids, nullable sample
  counts before evaluation), `POST .../compare` (one derivation route —
  `mode`, a separate `/ablation`, and an `/evaluate`-then-`/coverage`
  split were all considered and rejected). A configuration with more
  than one distinct prediction source for a task is a hard 422 listing
  every available source — never a guess, never a silent average.
- **Ablation as a comparison view, not a separate concept.** Baseline =
  the full configuration; the frontend filters the same `/compare`
  response by `relationship == 'direct_removal'`. Zero new domain code,
  zero new endpoint — proven by a dedicated test asserting `GET
  .../ablation` is a 404.
- **Comparison UI** (`frontend/src/pages/Comparison.tsx`): session/task/
  baseline pickers round-tripped through URL search params (so Session
  Detail's "Compare configurations →" link, shown only when ≥2
  configurations have results, can pre-fill state); a configuration
  comparison table; Sensor Addition, Ablation, and General Comparison
  card sections sharing a `ComparisonMetricTable` component; a metric
  selector sorting all three sections by delta magnitude. Three
  deliberately distinct formatters (`formatDelta`/`formatDeltaPp`/
  `formatRelativeDelta`) keep absolute deltas, percentage-point deltas,
  and relative-percentage deltas — three different quantities — from
  ever being confused at a call site, the exact mistake the v0.3
  specification warned against.
- **Expanded synthetic demo** (`scripts/generate_demo_data.py`,
  `examples/evaluation/classification-demo.json`): grown from three
  single-sensor configurations to all seven non-empty subsets of `{rgb,
  depth, thermal}`, accuracy targets forming a clean lattice (single <
  pair < all three) so every comparison in the demo is `VALID` by
  construction and no sensor removal ever "helps." Cross-checked by a
  test that hand-verifies the three direct-removal-from-full accuracy
  deltas (−7pp/−4pp/−2pp) through the real `/compare` API.
- **172 new backend tests**, **24 new frontend tests** — comparison
  models, engine, API, ablation-reuse, UI, expanded-demo, and a
  dedicated robustness pass (zero-ground-truth tasks, the N/A/no-
  divide-by-zero path through the real API, five malformed-request
  shapes, and a legacy pre-v0.3 single-configuration session comparing
  cleanly — proving v0.3 added no migration or field an old session
  would be missing).
- `docs/comparison.md` (new); `docs/evaluation.md`, `README.md`,
  `docs/limitations.md` updated for the comparison layer.

### Fixed

- **Self-comparison wasn't actually rejected.** The Phase 20 architecture
  review specified that comparing a configuration against itself must
  always be `invalid`, but Phase 21's engine never implemented the
  check — found while building the API layer on top of it, fixed at
  the correct layer (`compare_configurations`) with both a domain-level
  and an API-level regression test.
- **Float-precision test failures** (`(1.0 - 0.8) * 100 ==
  19.999999999999996`, not `20.0`) — fixed with `pytest.approx` on
  computed values; exact-equality assertions on raw literal values were
  left as-is since those round-trip exactly through JSON.

### Known limitations

No matched-label-set-divergence or reported-vs-common-set-divergence
validity checks (both documented gaps, not silent omissions), a
comparison spans exactly one session, no comparison history (recomputed
fresh, nothing persisted). Full list:
[docs/limitations.md](docs/limitations.md).

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
