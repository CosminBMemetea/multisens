# Known Limitations

The single authoritative list. Everything here is a deliberate scope
boundary or an honestly-reported gap - not a hidden defect. If something
below sounds like it should be fixed, it probably should be, in a later
release, not silently worked around now.

## Scope boundaries (by design, not oversight)

- **No built-in ML inference, no sensor fusion, no causal or statistical
  claims, no built-in domain-specific compliance logic.**
  v0.1 was
  ingestion, synchronization, diagnostics, and visualization; v0.2 added
  ground-truth evaluation (classification only through v0.7 - see below);
  v0.3 added
  configuration comparison (see below) - never a claim about *why* two
  configurations differ, only *that* they measured differently; v0.4
  added requirement profiles/coverage (see below) - a `PASS`/`FAIL`/
  `N/A` judgment against caller-defined acceptance criteria, never a
  compliance or certification claim; v0.5 added condition exploration
  (see below) - filtering, grouping, and cross-tabulating that same
  judgment by condition, explicitly never a causal or statistical claim
  about what a condition *caused*; v0.6 added decision support (see
  below) - judging a configuration's already-computed coverage against
  an explicit, caller-supplied policy, explicitly never a causal claim
  and never a universal sensor-importance score; v0.8 added object
  detection and scalar regression evaluators (see below) - no tracking,
  segmentation, pose, or AP/mAP, and still no perception/inference *built
  into the core platform* (MultiSens evaluates predictions, it never
  produced them - through v0.9.1). See the project's own original scope
  statement in the README.
  **v1.0-RC (issue #123) adds an optional, external reference
  implementation** - a standalone YOLOv8n inference worker plus a thin
  `PredictionConnector` bridge plugin, process-isolated from the core
  backend (a crash in the model can never take down the REST API). This
  doesn't change the scope boundary above: the core platform still
  produces zero predictions itself; the reference worker is opt-in
  example code an operator runs and wires in via config, exactly like any
  other third-party plugin, never something the backend depends on or
  ships enabled by default.
  **Since v1.0.0, unreleased (issues #136/#141/#142/#143): now three**
  independently-developed reference workers (YOLOv8n, FER+ emotion,
  MediaPipe face detection), sharing a small extracted toolkit
  (`multisens-worker-kit`) but each its own OS process - and any number
  of them can target the same sensor simultaneously (config-only, no
  core change), live-verified with all three plus a fourth on a second
  sensor at once, each failing and recovering independently. The scope
  boundary itself is unchanged: still zero built-in inference, still
  opt-in example code, still never something the backend depends on.
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
- **Requirement conditions are flat scalars only.** `Requirement.
  conditions` is `dict[str, str | float | bool]`, not an arbitrary
  nested structure - every example this project has needed fits a flat
  map, and a nested one would need an ambiguous recursive-subset
  matching rule for no demonstrated benefit. Inherited directly by
  v0.5's facet discovery/filtering, which reads the exact same field.
  See [profiles.md](profiles.md#conditions-open-by-design-non-negotiable).
- **No profile-level `PASS`/`FAIL`/`INCOMPLETE` status.** Only raw
  pass/fail/N/A counts and the two coverage percentages, at every group
  level including the root - a single rolled-up status was deliberately
  rejected as exactly the kind of nuance-hiding shortcut this layer's
  design works to avoid. See
  [coverage.md](coverage.md#no-profile-level-status).
- **No per-requirement weighted or mandatory-requirement aggregation.**
  `Requirement`/`RequirementGroup` carry no `weight`/`mandatory` field -
  neither has an aggregation semantic defined yet, and an unused field
  would invite premature use before one exists. v0.6's
  `mandatory_requirements_must_pass` is a population-wide boolean ("every
  requirement in the filtered population must pass"), not a scoped list
  of specific mandatory requirements - the more general per-requirement
  version remains additive migration territory for a later release, not
  built here because nothing in v0.6's own scope demonstrates the need
  for it yet. See
  [decision-support.md](decision-support.md#decisionpolicy-has-no-default-ever).
- **`RequirementResult`/`ConfigurationCoverage` are never persisted.**
  Recomputed fresh on every `/coverage` call from already-persisted
  evidence, same "recompute, don't persist" decision v0.3 made for
  `PairwiseComparison`.
- **An unfiltered `/coverage` call can surface unrelated
  configurations.** Discovery searches every session in the database
  for the profile's task(s) unless `session_ids`/`configuration_ids` is
  given - correctly reported as all-`N/A` for a profile's requirements
  when the discovered configuration has no evidence matching this
  profile's own conditions, but visually noisy if other standing demo
  data shares the database. See
  [coverage.md](coverage.md#api-surface).
- **`/analysis`'s `group_by` supports at most 2 dimensions.** A
  simultaneous 3+-dimension cross-tab doesn't exist - the frontend's
  configuration×condition "heatmap" and the 2D cross-tab together cover
  the demonstrated need; a third simultaneous axis has no UI shape
  defined yet. See
  [condition-explorer.md](condition-explorer.md#grouping-and-cross-tabulation).
- **`classify_na_reason` is coupled to `evidence.py`/`coverage.py`'s
  exact free-text reason strings**, not a structured field on
  `RequirementResult` - a deliberate choice (avoids redesigning a tagged
  v0.4.0 file without a concrete defect) with a real fragility: if either
  module's wording ever changes, the classification table must be
  updated in lockstep. Guarded by a dedicated cross-layer test, not
  invisible. See
  [condition-explorer.md](condition-explorer.md#failure-and-na-exploration).
- **Explorer/Failures/Evidence filter and tab state lives only in the
  URL.** No saved/named filter presets, no server-side persistence of a
  particular exploration view - closing the tab loses it unless the URL
  itself was bookmarked or shared.
- **`AnalysisResponse` is never persisted** - same "recompute, don't
  persist" decision as `RequirementResult`/`ConfigurationCoverage`
  above, extended to the v0.5 layer. Every `/analysis` call recomputes
  fresh.
- **Reverse session lookup (`/profile-usage`) is candidacy, not
  resolution, and not a dependency graph.** It lists every profile
  requirement a session's metadata could serve as evidence for, not
  which one it's *currently* resolved as evidence for - and it stops at
  one hop (session → matching requirements), never a full
  requirement/session/profile dependency-graph visualization, which the
  v0.5 master prompt explicitly rejected as unneeded for this project's
  scale.
- **`DecisionPolicy.objective` supports only `minimize_sensor_count`.**
  Cost/power/latency objectives are architected for (an additive
  `Literal` extension) but not implemented - v0.6 has no reliable
  hardware-characteristic data to build them on yet. See
  [decision-support.md](decision-support.md#decisionpolicy-has-no-default-ever).
- **Dominance/Pareto computation is O(n²) pairwise**, with no
  optimization library - fine at the realistic scale here since
  configuration count is bounded by *evaluated evidence*, never a
  generated power set, but genuinely quadratic if that assumption ever
  stops holding.
- **`DecisionAnalysisResponse` is never persisted** - same "recompute,
  don't persist" decision as `RequirementResult`/`AnalysisResponse`
  above, extended to the v0.6 layer. Every `/decision-analysis` call
  recomputes fresh.
- **`SUPPORTED_RESOURCE_METRICS` (v0.7) is exactly six metrics** -
  `cpu_percent`, `memory_mb`, `network_receive_mbps`,
  `network_transmit_mbps`, `fps`, `pipeline_latency_ms`. No GPU, power,
  temperature, or storage-write collector exists - no discrete-GPU
  passthrough and no Jetson exist in the environment this release was
  built in, so shipping those now would mean code no one can exercise or
  verify. See [resources.md](resources.md#supported_resource_metrics-the-reviewed-six).
- **A `ResourceObservation`'s `unit` is a fully open string at
  ingestion**, not validated against `SUPPORTED_RESOURCE_METRICS`'s own
  unit mapping - same open-vocabulary posture as `metric` itself. A
  mismatched unit for the same metric/configuration is only caught later,
  at read time (`/tradeoffs` returns a clean `422`), not rejected at
  ingestion. See
  [deployment-tradeoffs.md](deployment-tradeoffs.md#a-mismatched-unit-is-caught-at-read-time-not-ingestion).
- **A resource observation's `measurement_window` is never cross-checked
  against a session's own evaluation-evidence timespan.** A session with
  500 seconds of ground-truth/prediction evidence can carry a resource
  observation window covering only a few seconds of that, and nothing in
  the resource layer flags the mismatch - `Session` alone is the scoping
  entity, with no separate measurement-run concept (v0.7 architecture
  review). See
  [resources.md](resources.md#session-not-a-new-resourcemeasurementrun-entity).
- **v0.7's generalized Pareto front is O(n²) pairwise**, same bound and
  same justification as v0.6's fixed-dimension version above.
- **`TradeoffResponse` is never persisted** - same "recompute, don't
  persist" decision as every prior analysis layer's response shape.
  Every `/tradeoffs` call recomputes fresh.
- **`metric` lookup is limited to what `ComparisonMetrics` already
  exposes** (`accuracy`, `precision_macro`, `recall_macro`, `f1_macro`,
  `precision_micro`, `recall_micro`, `f1_micro`, the synthetic
  `coverage` key) - no custom-metric registration.
- **`min_common_sample_count` (default 20) and
  `coverage_warning_threshold_pp` (default 5.0) are heuristic, not
  evidence-based** - same honesty treatment as `tolerance_ms`'s default
  (see [comparison.md](comparison.md#comparison-validity)).
- **Evaluation was classification-only through v0.7; v0.8 added object
  detection and scalar regression** as new evaluators beside
  `evaluate_classification` - exactly the "new code, not a schema change"
  path [evaluation.md](evaluation.md#task-values-generic-by-design)
  always anticipated. See [evaluators.md](evaluators.md) for the generic
  interface and [detection-evaluation.md](detection-evaluation.md)/
  [regression-evaluation.md](regression-evaluation.md) for each
  evaluator's own scope boundaries (no AP/mAP, no cross-frame object
  tracking, no segmentation masks, no oriented bounding boxes, no
  relative/percentage error, no vector regression - all deliberate v0.8
  deferrals, not oversights). No `TaskDefinition` registry exists -
  `evaluator_type` is stated explicitly per `/evaluate` call, not
  remembered against a task name (see
  [evaluators.md](evaluators.md#evaluator_type-on-evaluationresult-explicit-per-call-not-a-registry-entity)).
  `/timeline` remains classification-only - a label-vs-label strip has no
  detection/regression analogue.
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
- ~~One sensor per modality, for live ingestion~~ **Resolved, v1.0-RC
  (issue #121).** Topics are now keyed by sensor `id`
  (`/multisens/sensors/{id}/image_raw`), not modality - two cameras
  sharing a modality (e.g. two RGB cameras) no longer collide; the
  launch-time guard now rejects a duplicate `id` instead. Live-verified
  with two simultaneous real RTSP-replayed RGB cameras
  (`ridesafe_front_rgb`/`ridesafe_rear_rgb`) through the full real
  `docker compose` stack: both connected independently, `sync_status`
  reported both by id and confirmed "synchronized within 25ms tolerance,"
  and the reference `rgb`/`depth`/`thermal` config (where `id == modality`)
  produces byte-identical topic/node names to before - confirmed, not
  assumed. See
  [decision-support.md](decision-support.md#sensor-instance-identity-not-modality)
  for the evaluation-layer side of this, which was already unaffected
  (issue #58, closed) even before this fix.
- **RTSP only.** `config/sensors.yaml`'s `transport` field exists for
  future extension, but only `"rtsp"` does anything; other values are
  skipped with a logged warning.
- **`/multisens/sync/frames`** (actual grouped/republished synchronized
  frame bundles, as opposed to status *about* synchronization) does not
  exist. Only sync *status* is published.
- **No `sensor_msgs/CameraInfo` data.** The topic contract reserves
  `/multisens/sensors/{sensor_id}/info` for it, but no calibration data
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
- **v0.9's Plugin SDK provides in-process failure isolation only, never
  true sandboxing.** A plugin executes with the full permissions of the
  backend process (filesystem, network, environment variables,
  everything) - no seccomp, no separate OS user, no per-plugin container
  isolation. What v0.9 does catch: a discovery-time or runtime-method
  exception in plugin code, converted to `LOAD_FAILED`/`FAILED` and never
  propagated to crash the process or affect another plugin. What it
  cannot catch: a plugin that blocks forever synchronously, a
  native-extension segfault, a thread/file-descriptor leak, or anything
  done deliberately with the process's own permissions. See
  [plugin-sdk.md#trust-model](plugin-sdk.md#trust-model) and
  [plugin-sdk.md#failure-isolation---achievable-and-not](plugin-sdk.md#failure-isolation---achievable-and-not).
- **Exact-match-only plugin API-version compatibility.** A plugin
  declaring any `api_version` other than the exact string MultiSens
  provides is `INCOMPATIBLE` - no range matching, no forward/backward
  compatibility guessing.
- **No plugin configuration-editing UI, and no connector start/stop
  mutation API.** A connector's config (`config/sensors.yaml`'s
  `connector:` block) only ever changes by editing the file and
  restarting the container - `/api/plugins`/`/api/connectors`
  (Phase 102) are read-only observability, matching v0.1's own sensor
  config precedent.
- **No first-class LiDAR/point-cloud/IMU schemas in core.** A
  `SensorSample.data_type` is an open string core never semantically
  interprets - "can register a connector for LiDAR/IMU-shaped data"
  (proven, Phase 104) is never conflated with "core understands
  point-cloud geometry or IMU signal semantics" (not built, not
  claimed).

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
- **v0.7's resource collector (`app/resource_collector.py`) measures from
  inside the `backend` container instead** - the same Docker-Desktop-VM
  caveat above applies, now extended for the first time to
  `network_receive_mbps`/`network_transmit_mbps` too: readings are
  host-interface-wide, not per-RTSP-stream, so if multiple sensors share
  one interface (as they do in the reference setup), a single
  configuration's "network Mbps" really means "total host network
  activity during the window." See
  [resources.md](resources.md#collection-appresource_collectorpy).
- Developed and verified only on Apple Silicon (M2, 8GB target). Base
  images (`ros:humble-ros-base`) are confirmed multi-arch (arm64/v8
  manifest present), and no code path is architecture-specific - but
  x86_64/Jetson has not been run, only reasoned about.
- **v0.7 resource trade-offs ([deployment-tradeoffs.md](deployment-tradeoffs.md#comparability-four-independent-rules))
  have only ever been measured on one machine/platform.**
  `ExecutionPlatform` and the `platform_id`-based comparability warning
  in `backend/app/domain/resources.py` were built to support comparing
  observations across genuinely different machines, but no second
  platform's data has actually been captured to exercise that path.
  Reviewed for v0.7 and explicitly deferred (issue #76, closed): no
  Jetson Orin (or any second machine) was reachable in the environment
  this release was built in, and no cross-platform numbers are
  fabricated to fill the gap. The domain model gained zero
  Jetson/NVIDIA-specific fields either way - a GPU metric, if ever
  collected, is just another entry in the open `metric` vocabulary.
- **v0.9's `multisens_sdk` package is ARM64/Jetson-*reviewed*, not
  tested.** The design (pure Python + `pydantic`, no native dependencies
  anywhere in the SDK) was checked for architecture-specific risk and
  found to have none - but no Jetson or other ARM64 hardware was
  reachable in this development environment to actually run it on, the
  same honest deferral as the resource-trade-offs cross-platform gap
  above.

## Honestly-reported, not yet resolved

- **No CI.** Every "verified" claim in this project's history means someone
  ran it manually and checked the actual output - there is no automated
  regression suite wired into GitHub, so nothing prevents a future change
  from silently breaking something already proven to work once.
- **Memory soak testing is real but time-limited.** See
  [CHANGELOG.md](../CHANGELOG.md)'s `[0.1.1]` entry for the actual
  30-minute soak test record (fixed while writing this section - it
  previously pointed at "the README's soak-test entries," which don't
  exist; the README defers all limitations detail to this file, and this
  file's own reference was circular) - a short soak can rule out a fast
  leak, not a slow one. Treat any "no leak observed" statement as scoped
  to the duration actually tested, not as a permanent guarantee.
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
- **Live resource collection does not resume across a backend restart**
  (v0.9.1, issue #111). `plugin_state` is in-memory only; a `Session`
  left `running` when the backend restarts stays `running` in the
  database (no auto-transition) but has no live collector reattached -
  no observations are fabricated to paper over the gap, and any
  collection resumed after restart starts a fresh measurement window
  rather than claiming continuity across the downtime. See
  [resources.md#live-collection-v091-issue-111](resources.md#live-collection-v091-issue-111).
- **Live resource collection's `configuration_id` assumes exactly one
  active sensor per modality** (v0.9.1, issue #111) - it's derived from
  `config/sensors.yaml`'s current sensor set, which is only unambiguous
  under the live one-sensor-per-modality architecture
  ([connector-api.md](connector-api.md)'s own documented v0.1 limit,
  still current). Offline/batch-uploaded resource evidence is
  unaffected and can still span multiple configurations per session, as
  the RideSafe reference dataset does. This assumption does not survive
  a future multi-sensor-per-modality live-ingestion design and must be
  revisited then - not solved here.
- **A resource collector can only be attached to one session at a time**
  (v0.9.1, issue #111) - if two `Session`s are `running` concurrently, a
  second session's `/start` still succeeds, but a collector already
  attached to the first session simply isn't started for the second;
  `GET /api/resource-collectors`'s `session_id` field shows which
  session (if any) currently owns each collector. No queueing, no
  automatic handoff.
- **Live-collected `platform_id` is a declared config value
  (`platform_id:` in `config/sensors.yaml`), never auto-detected** -
  falls back to `unknown` if omitted, same "declared, never guessed"
  posture `ExecutionPlatform` has always had.

## Live-verified: failure/recovery + multi-sensor matrix (v1.0-RC, issue #125)

Every claim below was exercised against the real docker compose stack on
the reference dev machine (Apple Silicon M2, 6GB/7-CPU Docker Desktop
allocation) - a real process killed with `kill -9`, not a simulated
fault, matching this project's standing rule that every "verified" claim
means someone ran it and checked the actual output.

**Detector-failure test (kill only the inference worker mid-session)**:
passed. `ridesafe_front_rgb` stayed `CONNECTED` throughout at its normal
~30fps, its video kept streaming to the dashboard, its inference
connector correctly surfaced `DEGRADED`/`Inference: ERROR` with the real
`urlopen` network error - and restarting the worker process, without
touching the session, self-healed the connector back to `RUNNING` with
predictions resuming (issue #126's own fix, exercised end to end here
rather than just at the wrapper-unit-test level).

**Sensor-failure test (kill only one RTSP publisher)**: passed, with one
honest nuance found along the way. Killing `ridesafe_front_rgb`'s own
RTSP source: that sensor's `connection_state` correctly settled to
`disconnected` (fps dropped to 0), the other three sensors
(`ridesafe_rear_rgb`/`depth`/`thermal`) stayed fully `connected` at their
normal fps with zero new reconnects, and the worker reading that same
now-dead source correctly reported its own `last_error` ("could not open
RTSP stream"). Restarting the publisher recovered both the ROS ingestion
node and the independent worker process, with zero manual intervention
to either.

  - **Nuance 1 - a brief transient window right at failure onset.** In
    one run, `ridesafe_front_rgb` was briefly absent from `/api/status`
    entirely (rather than present-and-`disconnected`) for a few seconds
    immediately after the kill, before stabilizing to a reliable
    `disconnected` reading for the remainder of the outage. Root cause:
    `ros_bridge.py`'s `STALE_AFTER_SEC = 5.0` expiry and the first
    disconnected-state diagnostics message landing close to that same
    window - a boundary-timing artifact of the existing staleness
    design, not a persistent flapping bug (confirmed stable for the rest
    of a multi-minute outage). Bounded and understood, not filed as a
    tracked issue.
  - **Nuance 2 - the inference connector's `state` field didn't reflect
    a stale-but-still-responding input.** While the RTSP source was
    down, the worker's own `/latest` HTTP endpoint kept responding
    successfully (just serving its last-known frame's unchanged
    timestamp) - so the bridge plugin's `poll()` kept succeeding
    (correctly returning `[]` per its own "same frame, nothing new"
    dedup), and the connector's `state`/`health.state` stayed `running`
    throughout the entire outage. `total_predictions` correctly stopped
    climbing (the honest signal), but an operator glancing only at the
    top-level `ACTIVE`/`NONE`/`ERROR` badge would see `ACTIVE` for a
    feed that had been silently stale for minutes. **Fixed in issue
    #127**: the bridge now tracks time since the last frame that
    genuinely *advanced* (not time since the last poll attempt) and
    reports `DEGRADED` once that exceeds a configurable `stale_after_s`
    (default 5s) - live-verified with the same kill-the-RTSP-source
    procedure: the dashboard correctly showed `Inference: ERROR` with a
    real, growing staleness age (confirmed past 80s in one run) once the
    threshold was crossed, and recovered to `Inference: ACTIVE` the
    moment the source came back and a genuinely new frame arrived.

**Multi-sensor test matrix**: all four combinations passed, through the
same generic, unmodified `SensorCard`/`Dashboard`/ingestion code - no
special-casing found or needed for any of them.

| Combo | Sensors | Result |
|---|---|---|
| A | 1 physical RGB (`ridesafe_front_rgb`) | Passed - subset of combo D below, isolated by inspection |
| B | RGB + simulated thermal + simulated depth (both `derived_from_sensor_id: ridesafe_front_rgb`) | Passed - subset of combo D below |
| C | 2 same-modality physical RGB (`ridesafe_front_rgb`/`ridesafe_rear_rgb`) | Passed - subset of combo D below |
| D | All four simultaneously, plus a live YOLO inference connector on the front sensor | Passed - the full stack actually deployed and screenshotted |

Combo D was the one actually deployed; A/B/C are each a strict subset of
what was running in D, and nothing in the codebase branches on *which*
sensors are present or how many - so D running correctly is itself the
evidence for A/B/C, not an assumption standing in for separately
re-deploying each one.

**Resource measurement, honestly attributed** (captured during combo D,
steady state, one inference connector active):

| What | Value | Source / attribution |
|---|---|---|
| Sensor fps (each of 4) | ~28-30 (target 30) | `GET /api/status`, self-reported per `rtsp_ingestion_node` - **measured**, per-sensor |
| Inference rate | ~0.3-1.0 predictions/sec | `PollRunner.predictions_per_sec` (issue #124) - **measured**, per-connector, real wall-clock/count |
| `ros` container CPU | ~760-780% (of a multi-core budget; Docker's per-container % is not core-normalized) | `docker stats` - **measured**, whole-container, not per-topic/per-sensor |
| `ros` container memory | ~585-590 MiB | `docker stats` - **measured**, whole-container |
| `backend` container CPU/mem | ~6% / ~67 MiB | `docker stats` - **measured**, whole-container |
| System-wide CPU/RAM (`system_diagnostics_node`) | 67-99% / 25-32% | `psutil` inside the `ros` container - **measured**, but whole-VM (Docker Desktop for Mac), not per-process - same caveat this file already documents for v0.7's resource collector, above |
| YOLO worker process (host, not containerized) | 39-78% CPU, ~130-170 MB RSS | `ps -o pcpu,rss` on the worker's own PID - **measured**, genuinely per-process (the one number in this table that *is* attributable to the model itself, not a whole-container/whole-VM figure) |
| `mediamtx` (host, dev-only simulator infra) | ~9-11% CPU, ~36 MB RSS | `ps` - **measured**, per-process |
| RTSP re-stream `ffmpeg` processes (`-c copy`, host) | ~0.4-2.4% CPU each, ~9 MB RSS each | `ps` - **measured**, per-process |

The one number worth calling out by contrast: **whole-system CPU
(67-99%) is not the same claim as "YOLO inference costs 67-99% CPU."**
The YOLO worker's own measured share (39-78%, alone) is a large but
partial contributor - the other consumers are 4 simultaneous RTSP
decode/re-encode paths, DDS/ROS message passing for 4 image topics, and
the MJPEG browser relay, all running on the same 7-CPU Docker Desktop
allocation. No resource-quality tier from `docs/resources.md`
(`measured`/`declared`/`estimated`/`unavailable`) was stretched to imply
more precision than `docker stats`/`psutil`/`ps` actually provide -
every figure above is `measured` at the granularity its own tool
reports, nothing finer-grained is claimed.

## What would likely break first

- **More sensors: now measured at N=4, not just N=3** (v1.0-RC, issue
  #125 - see the multi-sensor test matrix above for the exact
  configuration and numbers). Nothing in the architecture assumes a
  fixed sensor count, and this confirms it - but resource usage (CPU for
  N RTSP decode/encode paths, DDS traffic for N image topics) climbs
  steeply: the reference dev machine hit ~97-99% whole-VM CPU at N=4
  (2 physical + 2 derived, one of them running live YOLO inference).
  Still untested beyond N=4, and still only on one machine/one
  architecture (Apple Silicon M2). Expect to hit host CPU limits well
  before hitting a code limit.
- **Higher resolution (untested beyond 640x480):** the "large image message
  defeats a generic ROS subscriber" problem (see
  [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video))
  gets worse, not better, at 1080p - `image_raw` traffic is already at the
  edge of what a naive subscriber can keep up with at 640x480/30fps.
