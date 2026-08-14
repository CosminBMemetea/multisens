# Plugin SDK & External Integration Framework (v0.9)

**Status: in progress (Phase 92 architecture review approved; Phases
93-102 - the SDK package, discovery/registry, the SensorConnector
runtime wrapper, the built-in RTSP adapter, the Prediction/GroundTruth
connector wrappers, external evaluator plugins, external
resource-collector plugins, the contract test kit, the reference
external plugin, and the read-only integrations API/UI - shipped; Phases
103-106 not yet built).**

## Integrations API & UI (Phase 102 - shipped)

Config-driven connector wiring finally executes what
[`config/sensors.yaml` extension](#configsensorsyaml-extension) (Phase
95) only documented: `app/plugins/manager.py`'s `build_connector_instances()`
reads every sensor's optional `connector:` block at startup, resolves
its named `plugin_id` against the registry, and constructs one
`ConnectorInstance` per sensor id - never a shared object across two
sensor ids naming the same plugin. That last guarantee needed a new
`PluginRecord.factory` field (a zero-arg "make me a fresh one"
callable, alongside the existing singleton `.instance`): built-in
evaluators default to reusing their singleton (unchanged v0.8
behavior), the built-in RTSP connector and any externally discovered
connector-shaped plugin each get a real fresh-object factory. A sensor
naming an unknown/incompatible/wrong-typed plugin, or whose `configure()`/
`start()` fails, is never dropped silently - it's still reachable through
the API below in its honest (`stopped`/`failed`) state, with the reason
printed at startup.

Five read-only routes (`app/api/plugins.py`), no mutation endpoint
anywhere in this router - installing/enabling a plugin and wiring a
connector both stay restart-time file changes, matching the master
prompt's explicit boundary:

```
GET  /api/plugins
GET  /api/plugins/{plugin_id}
GET  /api/plugins/{plugin_id}/capabilities
GET  /api/connectors
GET  /api/connectors/{sensor_id}
```

Every response passes through `redact_secrets()` (`app/plugins/secrets.py`)
before it leaves the process - any dict key matching `password`/`token`/
`secret`/`key` (case-insensitive, so `password_env`/`api_key`/`auth_token`
are all caught the same way as a literal `password`) is replaced with
`***REDACTED***`, applied to plugin `capabilities`, connector `config`,
and connector `health.details` alike, recursively through nested dicts
and lists.

One new frontend page, `/integrations` - an "Installed Plugins" table
and a "Connector Instances" table, reusing the existing `LevelBadge`
component for status/state color-coding. Deliberately not a duplicate of
the Dashboard's own sensor-health view: this table is the connector
*plugin's* own lifecycle state (`stopped`/`starting`/`running`/
`degraded`/`failed`), not the frame-level video diagnostics the
Dashboard already shows for the same sensor id. No install/browse/
download affordance anywhere on the page - the empty states say "No
plugins discovered" / "No connector instances configured," never invite
a click that doesn't exist.

Verified live, twice: against the real `docker compose` backend (one
real `connector:` block wired to the built-in RTSP plugin for the `rgb`
sensor, `state: running`, real `health` reflecting the actual RTSP
connection status) and against a throwaway image with Phase 101's
`multisens-example-environment-sensor` `pip install`ed on top (all 6
plugins - 3 built-in evaluators, the built-in RTSP connector, and both
example plugins - listed correctly). Both the Vite dev build and the
production nginx-served build loaded `/integrations` with zero console
errors.

## Reference plugin (Phase 101 - shipped) - the actual clean-room test

[`examples/plugins/environment-sensor/`](../examples/plugins/environment-sensor/)
is a real, independently installable package
(`multisens-example-environment-sensor`) shipping two plugins:
`multisens.example.sensor.environment-sensor` (a deterministic synthetic
temperature/humidity `SensorConnector` - proof MultiSens plugin
extensibility is not camera-specific) and
`multisens.example.resource.synthetic-metric` (a deterministic
`ResourceCollector` metric). Every value either produces is generated
from a fixed pattern, labeled `SYNTHETIC SAMPLE SOURCE` - never a real
measurement.

**This is the actual test of the SDK boundary, not just an assertion of
one**: installed into a genuinely clean Python 3.11 virtualenv (no
Docker, no ROS, no MultiSens checkout beyond these two directories) via
plain `pip install ./sdk && pip install ./examples/plugins/environment-sensor`,
its own 14-test suite (`tests/test_boundary.py`'s AST-based import check
plus `tests/test_environment_sensor.py`'s full descriptor/configure/
start/sample/health/stop/failure walkthrough, using only
`multisens_sdk.testing`'s contract helpers) passed with zero
`backend.app`/`frontend`/`ros2_ws` imports anywhere. `importlib.metadata.entry_points(group="multisens.plugins")`
found both plugins correctly in that same clean environment. Rebuilding
a real MultiSens backend image with this plugin `pip install`ed on top
(the exact `RUN pip install my-plugin` pattern this document's own
[Packaging](#packaging) section documents) produced a real startup log
`plugin discovery: 5 available` - the three built-ins plus both example
plugins, discovered through `discover_plugins()`'s real, unmodified code
path, zero core changes needed for either plugin to work.

## Contract test kit (Phase 100 - shipped)

`multisens_sdk.testing` (opt-in via `pip install multisens-sdk[testing]`
- `pytest` never becomes a forced runtime dependency of every plugin):
plain, framework-agnostic `assert*` functions a plugin author can call
from `pytest`, `unittest`, or a bare script -
`assert_valid_plugin_descriptor`, `assert_health_contract`,
`assert_connector_lifecycle` (generic across
`SensorConnector`/`PredictionConnector`/`GroundTruthConnector`/
`ResourceCollector` - the caller supplies a zero-arg `configure`
closure, the one signature difference the helper can't paper over),
`assert_metric_descriptors_valid`, `assert_evaluator_output_shape`,
`assert_evaluator_deterministic`, and `assert_resource_observation_shape`.

Every helper is proven correct before any external author relies on it -
28 dedicated tests, each helper exercised against both a passing fake
and a deliberately-broken one (a connector that never reports `RUNNING`
after `start()`, a fabricated non-numeric metric value, nondeterministic
`evaluate()` output, an out-of-range `last_sample_age_s`, ...), so a
real bug in the helper itself would have been caught here, not by the
first external plugin author to hit it.

## External resource-collector plugins (Phase 99 - shipped)

`SUPPORTED_RESOURCE_METRICS` (`app/domain/resources.py`) is genuinely
extensible now, the same pattern `EVALUATOR_REGISTRY` got in Phase 98: a
`RESOURCE_COLLECTOR`-type plugin's own `available_metrics()` are unioned
in via `register_resource_metrics()` as part of the same
`discover_plugins()` pass - a new metric name (`gpu_percent`, say)
becomes valid only once a registered plugin actually declares it, never
a permanently open vocabulary. Re-declaring an *existing* metric under
its *same* unit is fine (two independent collectors both legitimately
reporting `cpu_percent` in `%`); a *different* unit for an existing name
is rejected - and validated all-or-nothing across every metric a plugin
declares, never a half-registered plugin from one conflicting entry
among several clean ones.

`backend/app/plugins/resource_collector_instance.py`'s
`ResourceCollectorInstance` wraps a `ResourceCollector` plugin with the
same lifecycle discipline as every other connector wrapper in this
package; `sample()` filters out anything that isn't actually a
`ResourceObservation`. Emitted observations flow through the *existing*,
completely unchanged v0.7 ingestion/summary/trade-off pipeline - no core
edits to `resources.py`'s own summary/comparability/qualification logic
at all.

Proven by 16 dedicated tests, including the full acceptance bar: a
test-only external `synthetic_metric` collector, discovered through the
real entry-point mechanism, has its metric rejected by `/tradeoffs`
*before* registration and accepted *after*, with a genuine zero value
and an explicit `unavailable` quality both flowing through exactly as
honestly as any built-in metric always has (zero is a real measurement,
never confused with "no value"; `unavailable` means genuinely no value,
never a fabricated number).

## External evaluator plugins (Phase 98 - shipped)

`EVALUATOR_REGISTRY` (`app/domain/evaluators.py`) is genuinely
extensible now, not just documented as eventually-extensible: an
EVALUATOR-type plugin discovered through `multisens.plugins` gets its
own `evaluator_type` registered via `register_evaluator()` as part of
the same `discover_plugins()` pass that checks `plugin_id` uniqueness -
a *separate* namespace, checked independently. Two plugins with
different `plugin_id`s can still collide on `evaluator_type`; unlike a
`plugin_id` collision (which rejects both sides - genuine identity
ambiguity), an `evaluator_type` collision rejects only the second
registration attempt with a clear, dedicated error - the first,
already-legitimately-registered plugin (built-in evaluators always win,
since they register before any external discovery runs) keeps working.
Never a silent override either way.

`EvaluatorPlugin.metric_descriptors()` (purely descriptive -
`higher_is_better`/`unit` hints) is implemented by all three built-ins
now; `coverage.py`'s acceptance engine has zero references to it or to
`MetricDescriptor` anywhere, grep-verified by a dedicated test - a
plugin evaluator produces evidence, the profile alone determines
sufficiency.

Proven by 8 dedicated tests, including the full acceptance bar: a
test-only external evaluator (`evaluator_type='test_ok_ratio'`,
discovered through the exact same entry-point mechanism a real installed
package would use) flows through `/evaluate` -> `EvaluationResult` ->
`/coverage`'s requirement acceptance -> `/compare`'s metric deltas, with
zero core edits beyond this phase's own registry wiring - the identical
claim Phase 85's mixed-task test already proved for the three built-in
evaluators, now proven for a genuinely external one.

## Prediction + GroundTruth connectors (Phase 97 - shipped)

`backend/app/plugins/poll_connector_instance.py`'s
`PredictionConnectorInstance`/`GroundTruthConnectorInstance` wrap a
pull-based plugin with the same lifecycle discipline as
`ConnectorInstance` (Phase 95). `poll()` never raises: not-`RUNNING` or
the plugin's own `poll()` failing both return an empty list (the
connector moves to `FAILED` in the latter case); an item that isn't
actually the right canonical type (a misbehaving plugin) is dropped with
a recorded reason, the rest of the same batch still returned.

`backend/app/plugins/poll_runner.py`'s `PollRunner` is the background
loop - the same "own thread, kept off uvicorn's event loop" pattern
`ros_bridge.py` established for exactly the same reason (`poll()` is a
blocking, synchronous plugin call). Each cycle opens its own short-lived
SQLite connection and forwards through
`repository.insert_batch_with_partial_failure` - **the identical
function** `api/sessions.py`'s own `/predictions/batch`/
`/ground-truth/batch` endpoints use (extracted from the API layer into
`repository.py` this phase specifically so both call sites share one
implementation) - so a connector is a code-driven way to call an
endpoint that already exists, never a second ingestion mechanism. A
primary-key collision falls back to per-item inserts exactly like a
retried REST batch would.

Proven by 15 dedicated tests: canonical shape round-tripping exactly
through a real SQLite database (task/source_id/sensor_ids/timestamps/
confidence all intact on readback), malformed-item filtering, a
duplicate id never losing the rest of a batch, a `poll()` that raises
never crashing the loop, a real background thread actually starting and
stopping, and - the acceptance criterion that mattered most - a
connector whose `poll()` always raises writing to a **completely
separate database** while the ordinary REST API against the real
session database is exercised in the same test, proving the isolation
is structural, not just "the mock was never called." This document is the single authoritative decision record the
v0.9 phases build against - each phase updates its own section from
*planned* to *shipped* as it lands, and [CHANGELOG.md](../CHANGELOG.md)'s
eventual `[0.9.0]` entry is the record of what actually got built.
Anywhere this document still says a component "will" do something, that
is a decision already made but not yet implemented - config-driven
`sensor_id -> ConnectorInstance` wiring at container boot (so a real
`config/sensors.yaml` `connector:` block actually produces a running,
polled connector) is not yet built; Phase 96 registers the built-in RTSP
plugin itself and proves its health-mapping logic, Phase 103 exercises
it against RideSafe/PropertyWatch's real sensor ids.

## Built-in RTSP adapter (Phase 96 - shipped)

`backend/app/plugins/builtin_rtsp.py`'s `RtspSensorConnector` is
**descriptor-only** over the existing, completely unchanged v0.1
pipeline - `rtsp_ingestion_node.py`/`sensor_config.py`/
`ingestion.launch.py` were not touched at all. `start()`/`stop()` are
bookkeeping only (the real stream starts/stops via ROS launch at
container boot, independent of this object); `health()` is a pure
mapping function from `RosBridge.snapshot()['sensors'][sensor_id]`
(already keyed by `hardware_id`, which is exactly the sensor `id` from
`config/sensors.yaml` - no id/modality translation needed) into
`ConnectorHealth` - `connection_state == 'connected'` maps to `RUNNING`,
anything else (including "no diagnostics yet") maps to `DEGRADED`, never
a hard `FAILED` this connector itself didn't cause. `sample()` always
returns `None` - video stays data-plane
([architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video)),
never routed through this object; `video_relay.py` and the ROS image
topic remain the only ways to see actual pixels, unchanged. Registered
in `discover_plugins()` only when a real `RosBridge` is supplied (`app/
main.py` does; most tests don't need one). Proven by 12 dedicated tests,
including `ridesafe_front_rgb`/`ridesafe_rear_rgb` sharing one connector
*implementation* while staying fully independent connector *instances* -
this project's own flagship "plugin type != sensor instance"
demonstration (validated further in Phase 103). Live-verified: a fresh
`docker compose build`/`up` shows `plugin discovery: 4 available` (three
built-in evaluators + this connector) with `/api/sensors` and every
other v0.1 endpoint completely unaffected.

## SensorConnector runtime wrapper (Phase 95 - shipped)

`backend/app/plugins/connector_instance.py`'s `ConnectorInstance` wraps
one already-constructed `SensorConnector` plugin object per sensor id,
enforcing the lifecycle rules below for real: mutating calls
(`configure`/`start`/`stop`) raise a clean `ConnectorConfigError`/
`ConnectorRuntimeError`/`ConnectorLifecycleError` on failure (and update
tracked state to `FAILED` first, so a later `health()` reflects the same
reality even if a caller mishandles the exception); observational calls
(`health`/`sample`) never raise, always returning a value describing
current reality so a poller never needs special-cased exception
handling. `sample()`'s "small/scalar-payload-only" contract is enforced,
not just documented: a payload that fails JSON serialization or exceeds
a 65,536-byte cap is discarded (the connector stays `RUNNING` - an
oversized reading is a data-quality problem with one sample, never a
connectivity failure). `config/sensors.yaml` gained an additive,
optional `connector:` block (`plugin:`/`config:`) - see
[connector-api.md](connector-api.md) - and `backend/app/plugins/
secrets.py` resolves `*_env` references (e.g. `password_env:
CAMERA_PASSWORD`) from `os.environ` at connect time only, before the
plugin ever sees the config, never persisted or echoed back anywhere.
Proven by 29 dedicated tests (24 lifecycle + 5 secrets), including two
independent `ConnectorInstance`s wrapping separate objects of the same
connector class staying fully independent (`ridesafe_front_rgb`/
`ridesafe_rear_rgb` never share state).

## Discovery & the plugin registry (Phase 94 - shipped)

`backend/app/plugins/registry.py`'s `discover_plugins()` builds a fresh
`PluginRegistry` at startup (`app/main.py`'s own `lifespan`): the three
built-in evaluators register first (directly imported, each now
exposing its own `descriptor()` -
`multisens.builtin.evaluator.classification`/`object_detection`/
`regression`), then `importlib.metadata.entry_points(group=
"multisens.plugins")` is discovered for external plugins.

**A required convention, not a coincidence**: an entry point's
registered *name* must equal its plugin's own `descriptor().plugin_id`.
This is what lets `plugins.disabled` (read from `config/sensors.yaml`'s
new, optional `plugins.disabled` list - the same file sensors already
live in, no separate file yet) suppress a plugin **before its code is
ever imported** - a real safety property, not just bookkeeping - and
lets duplicate-id detection work off entry-point metadata alone. A
mismatch between entry-point name and `descriptor().plugin_id` is a
`LOAD_FAILED`, never a silent pick-one.

`PluginStatus` (`AVAILABLE`/`INCOMPATIBLE`/`LOAD_FAILED`/`DISABLED`) is
tracked per `PluginRecord`, entirely separate from `ConnectorState` -
installation-level vs. runtime-level, never conflated (see
[Lifecycle, health, idempotency](#lifecycle-health-idempotency)).
Duplicate `plugin_id`s (whether both external, or one external colliding
with a built-in) reject **both** sides deterministically, never "pick
one." Every step that touches plugin-provided code
(`entry_point.load()`, calling the loaded factory, calling
`.descriptor()`) is wrapped individually, proven by 12 dedicated tests
covering zero plugins, one plugin, multiple types, an incompatible API
version, a malformed/raising descriptor, a duplicate id, an import
failure, a disabled plugin never being loaded at all, and one broken
plugin never blocking any other plugin (or backend startup itself) from
succeeding.

See [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video)
for the existing control/video-plane split this design extends rather
than reinvents, [connector-api.md](connector-api.md) for how sensors are
added today (`config/sensors.yaml`, no plugin API, v0.1), and
[evaluators.md](evaluators.md)/[resources.md](resources.md) for the v0.8/
v0.7 layers this release makes externally extensible without changing
their own semantics.

## What this layer answers

> Can a developer extend MultiSens to support a new sensor, data source,
> evaluator, or telemetry provider without editing MultiSens core?

Through v0.8, every new capability meant editing the core application.
v0.9 introduces a small, closed **plugin SDK** so a sensor, algorithm, or
telemetry integration can be added by installing a Python package and
restarting - the same "add a capability without editing core" shift v0.8
already made for evaluators, generalized to sensors, predictions, ground
truth, and resource telemetry.

## What v0.9 explicitly is not

Not a plugin store, not remote installation, not automatic downloads,
not plugin payments, not a sandboxed execution environment, not a
Kubernetes operator, not a generic workflow/scripting engine. Plugins
are **trusted local software, installed deliberately by the operator** -
see [Trust model](#trust-model) below. This boundary is stated here
explicitly and re-verified, not just assumed, in every phase from here
on.

## Plugin taxonomy

Five **executable** plugin types, one **data** packaging convention that
is deliberately *not* a plugin type:

```
PluginType (enum):
    SENSOR_CONNECTOR        - live or recorded sensor data
    PREDICTION_CONNECTOR    - algorithm output, translated to canonical Prediction
    GROUND_TRUTH_CONNECTOR  - reference annotations/measurements, translated to canonical GroundTruth
    EVALUATOR               - a new evaluation family, extending EVALUATOR_REGISTRY (v0.8)
    RESOURCE_COLLECTOR      - platform/resource telemetry, extending v0.7's resource layer

ProfileBundle: NOT a PluginType. Declarative data (profile JSON/YAML +
README + LICENSE + provenance metadata), loaded through the existing
POST /api/profiles endpoint. No executable code, no eval(), no
arbitrary expressions - acceptance criteria stay structured, declarative
comparisons, exactly as v0.4 already established. Zero new discovery or
registry code for this.
```

One deliberate, single `Plugin.run()`-style interface was rejected -
each family gets a meaningful typed contract; only metadata/discovery
(`PluginDescriptor`, `PluginType`, `MULTISENS_PLUGIN_API_VERSION`) and
the connector health/lifecycle shape (`ConnectorHealth`, `ConnectorState`)
are shared.

## Trust model

> Plugins execute with the full permissions of the MultiSens backend
> process/container - filesystem, network, environment variables,
> everything. There is no sandboxing, no seccomp, no separate OS user, no
> per-plugin container isolation in v0.9. Installing a plugin is
> equivalent to installing any other Python package into this
> environment: only install plugins you trust as much as you trust
> MultiSens itself.

This is stated here, in the README, and as a startup log line whenever
any non-built-in plugin loads. Future process-level isolation may be
considered separately; v0.9 does not attempt it, and never claims to.

## Plugin identity

`<namespace>.<category>.<name>` - lowercase, `[a-z0-9_.-]+`, minimum two
dot-separated segments. Examples: `multisens.builtin.sensor.rtsp`,
`acme.sensor.velodyne-lidar`, `jdoe.resource.jetson`. **One global ID
namespace across every plugin type** - two plugins cannot share an ID
even if they are different `PluginType`s. Display name is never
identity.

## `PluginDescriptor`

The single authoritative source is a plugin object's own `descriptor()`
method - **Python code, not a separate manifest file**. A second,
divergent YAML/JSON source of truth was considered and rejected: a
manifest file and the code it describes can drift; one method call
cannot.

```python
@dataclass(frozen=True)
class PluginDescriptor:
    plugin_id: str            # "namespace.category.name"
    name: str                  # display name only, never identity
    version: str                # plugin's own semver
    plugin_type: PluginType
    api_version: str            # the single MULTISENS_PLUGIN_API_VERSION this was built against
    capabilities: dict[str, Any]   # free-form, category-specific, never core-interpreted beyond type checks
    author: str
    license: str
    description: str = ""
    homepage: str | None = None
```

Distribution-level metadata (the underlying pip package name/version,
read via `importlib.metadata.distribution()`) is a secondary audit
signal the registry surfaces alongside this - never authoritative for
compatibility decisions.

## Versioning: three independent axes

- **`plugin.version`** - the plugin's own semver, author-controlled,
  cosmetic to core.
- **`MULTISENS_PLUGIN_API_VERSION`** - one string constant (`"1"`),
  bumped only on a breaking `multisens_sdk` contract change. Deliberately
  decoupled from MultiSens's own `0.9`/`0.10`/`1.0` release numbers - a
  plugin built for API `"1"` should keep working on any MultiSens
  release that hasn't broken that contract.
- **Per-artifact schema version** - reuses the *existing* `format_version`
  fields already on `EvaluationResult`/`GroundTruth`/`Prediction`. No new
  concept.

**Compatibility rule: exact match only in v0.9.**
`plugin.api_version != MULTISENS_PLUGIN_API_VERSION` -> `INCOMPATIBLE`.
The descriptor stays readable/listed for display, but none of the
plugin's runtime methods (`start`/`evaluate`/etc.) are ever called.
Range-based compatibility (`>=1,<2`) is deliberately not attempted in
v0.9 - promising forward/backward compatibility this early would be a
promise this project cannot back up yet (the same "do not promise
stability you cannot maintain" posture applied everywhere else).

## Discovery: Python entry points, not directory scanning

```python
importlib.metadata.entry_points(group="multisens.plugins")
```

Chosen over directory scanning explicitly: standard packaging, no
arbitrary-import risk, works identically whether a plugin arrives via
`pip install`, a Docker image layer, or local editable install.
**Discovery only ever inspects explicitly declared `multisens.plugins`
entry points - it never scans or imports an arbitrary module.** The
backend container's Python (3.10) supports the modern keyword-filtered
`entry_points(group=...)` call natively.

## The `multisens_sdk` package

A new, independently installable top-level package (`sdk/`, sibling to
`backend/`/`frontend/`/`ros2_ws/`), its own `pyproject.toml`, its own
version. Correct dependency direction, enforced by a dedicated
import-boundary test:

```
MultiSens Core (backend/)  ->  multisens_sdk
External Plugin            ->  multisens_sdk

Never: External Plugin -> backend.app.* internals
```

### The central decision: canonical models move into the SDK

A `PredictionConnector` plugin has to *construct* a real `Prediction`
object. If that class stays defined in `backend.app.domain.models`, a
plugin author has two bad options: import backend internals directly
(breaks the dependency diagram above), or hand-roll a parallel dataclass
shaped like `Prediction` that can silently drift from the real one. Both
are unacceptable, so: **`GroundTruth`, `Prediction`, `EvaluationResult`,
`ResourceObservation`, `MatchResult`/`MatchedPair` (data only, not
`match_by_timestamp` itself), `MetricValue`, and `ResourceQuality` move
into `multisens_sdk.models`.** `backend/app/domain/models.py` (and
`matching.py`/`evaluator_output.py`/`resources.py` for the shapes they
each owned) became re-export shims - same classes, same fields, same
validation, relocated, not rewritten. This was the single
highest-blast-radius change in this release (Phase 93); it shipped only
once the full pre-existing 730-test backend suite passed unchanged
against it (verified: `test_sdk_boundary.py::test_backend_reexports_are_the_same_objects_not_copies`
asserts each backend name and its SDK counterpart are the literal same
class object, never independently-defined copies).

**A real packaging gotcha found and fixed while shipping this phase**:
the backend image's base Ubuntu 22.04 system `pip` (22.0.2) silently
mis-resolves this package's PEP 621 `pyproject.toml` metadata - every
`pip3 install /sdk` step reported success, but installed a bogus
`UNKNOWN-0.0.0` distribution containing none of the actual source files,
so `import multisens_sdk` 404'd only at container *startup*, not at
build time. Reproduced and confirmed directly (the identical
`pyproject.toml` installs correctly under a current `pip` on the host);
fixed by upgrading `pip` itself as the very first step in
`backend/Dockerfile`, before installing anything else.

`multisens_sdk` accepts `pydantic` as its one real third-party
dependency (the canonical models already are pydantic; a dependency-free
shadow copy would reintroduce the exact drift risk this decision exists
to avoid). `multisens_sdk.testing` (contract-test helpers, Phase 100) is
a separate, opt-in extra that may depend on `pytest` - never a forced
runtime dependency of every plugin.

## The five contracts

Shared connector health/lifecycle types (every connector-shaped plugin
type; `EvaluatorPlugin` has no runtime lifecycle, it's a pure function):

```python
class ConnectorState(str, Enum):
    STOPPED = "stopped"; STARTING = "starting"; RUNNING = "running"
    DEGRADED = "degraded"; FAILED = "failed"

@dataclass(frozen=True)
class ConnectorHealth:
    state: ConnectorState
    last_sample_age_s: float | None   # None = no sample yet
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
```

### SensorConnector

```python
class SensorConnector(Protocol):
    def descriptor(self) -> PluginDescriptor: ...
    def configure(self, sensor_id: str, config: dict[str, Any]) -> None: ...  # raises ConnectorConfigError
    def start(self) -> None: ...      # idempotent: no-op if already RUNNING
    def stop(self) -> None: ...       # idempotent: no-op if already STOPPED, blocks until STOPPED
    def health(self) -> ConnectorHealth: ...
    def sample(self) -> "SensorSample | None": ...
```

`sample()` is **small/scalar-payload-only** - see
[Data plane vs. control plane](#data-plane-vs-control-plane). A
streaming video/point-cloud connector implements `start`/`stop`/`health`
and, if it wants live dashboard status, publishes onto the ROS sensor
contract directly with `rclpy` - it never returns bytes through
`sample()`.

```python
@dataclass(frozen=True)
class SensorSample:
    sensor_id: str
    timestamp_ms: float
    sequence_id: int | None
    data_type: str            # open string - "scalar" | "vector" | "pose" | "imu" | ... - SDK does not enumerate exhaustively
    payload: Any                # small, JSON-serializable control-plane data only
    metadata: dict[str, Any] = field(default_factory=dict)
```

### PredictionConnector / GroundTruthConnector

Identical shape, pull-based:

```python
class PredictionConnector(Protocol):
    def descriptor(self) -> PluginDescriptor: ...
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: ...
    def poll(self) -> list[Prediction]: ...   # empty list = nothing new since last poll

# GroundTruthConnector: identical shape, poll() -> list[GroundTruth]
```

`poll()`, not a callback/queue: the host calls it from a background
thread on a bounded schedule - the same pattern
[`ros_bridge.py`](../backend/app/ros_bridge.py) already establishes
(an rclpy spin loop kept off uvicorn's event loop) - and forwards
results into the **existing** `/predictions/batch`/`/ground-truth/batch`
ingestion path. No new ingestion mechanism: a connector is a code-driven
way to call an endpoint that already exists.

### EvaluatorPlugin

The v0.8 `Evaluator` Protocol, relocated to the SDK, plus one addition:

```python
class EvaluatorPlugin(Protocol):
    evaluator_type: str
    format_version: str
    def metric_descriptors(self) -> list["MetricDescriptor"]: ...
    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput: ...

@dataclass(frozen=True)
class MetricDescriptor:
    id: str
    type: Literal["float"] = "float"
    higher_is_better: bool | None = None   # None = no defined direction (e.g. bias)
    unit: str | None = None
```

`metric_descriptors()` is **purely descriptive** (UI hints) - never
consulted by `coverage.py`'s acceptance engine, which keeps reading
`EvaluationResult.metrics[criterion.metric]` by string key exactly as it
does today. A plugin evaluator produces evidence; the profile determines
sufficiency - never the other way around. Grep-verified in Phase 98.

### ResourceCollector

```python
class ResourceCollector(Protocol):
    def descriptor(self) -> PluginDescriptor: ...
    def available_metrics(self) -> list["ResourceMetricDescriptor"]: ...
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def sample(self) -> list[ResourceObservation]: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: ...

@dataclass(frozen=True)
class ResourceMetricDescriptor:
    metric: str
    unit: str
    description: str = ""
```

v0.7's `SUPPORTED_RESOURCE_METRICS` becomes the **built-in baseline**; a
registered `ResourceCollector` plugin's `available_metrics()` return
values are unioned in at connector-registration time - `gpu_percent`
becomes valid only once a plugin that declares it is actually
registered, never a permanently open vocabulary. Keeps v0.7's reviewed,
deliberate metric-list discipline while genuinely extending it.

## Lifecycle, health, idempotency

Two state machines, tracked separately:

- **Plugin status** (installation-level, computed once at registry
  build): `AVAILABLE` / `INCOMPATIBLE` / `LOAD_FAILED` / `DISABLED`.
- **Connector state** (per-instance, runtime, via `health()`):
  `STOPPED` / `STARTING` / `RUNNING` / `DEGRADED` / `FAILED`.

Deliberately flattened from a literal `DISCOVERED -> CONFIGURED ->
STARTING -> RUNNING -> STOPPING -> STOPPED` diagram: `DISCOVERED`/
`CONFIGURED` are registry-tracked booleans, not independently-observable
states a plugin reports (nothing calls `health()` before `configure()`
anyway); `STOPPING` is dropped by making `stop()` **synchronous,
blocking until actually stopped or raising** - no limbo state to poll.

- `start()` on `RUNNING` -> no-op. `start()` on `FAILED` -> attempts a
  fresh start (the natural retry after fixing config/network).
- `stop()` on `STOPPED` -> no-op, never raises.
- `configure()` while `RUNNING` -> raises; must stop first.

## Data plane vs. control plane

Extends [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video)'s
already-proven split (measured directly in Phase 2: a generic `rclpy`
subscriber cannot keep up with a raw image topic, and `video_relay.py`
already bypasses ROS entirely for browser video) rather than inventing a
new one:

- **Control plane**: plugin metadata, health, config, small samples
  (`SensorSample.payload`, `ResourceObservation`, `Prediction`/
  `GroundTruth` value dicts) - flows through `multisens_sdk`'s typed
  Python objects freely.
- **Data plane**: video, point clouds, any high-rate binary payload -
  **never** routed through `SensorSample`/generic JSON. A streaming
  `SensorConnector` publishes directly onto the ROS sensor contract
  (`rclpy`, a standard ROS dependency, not a MultiSens abstraction on
  top of it) or, for browser-preview use cases, bypasses both ROS and
  the SDK exactly like `video_relay.py` already does today.

## ROS boundary and RTSP migration

Core stays transport-independent above the connector boundary; the
"MultiSens sensor contract" a connector publishes into **is** ROS,
unchanged. Plugin connectors run **inside the `backend` container**
(confirmed: `backend`'s own Dockerfile is `FROM ros:humble-ros-base`
too, so `rclpy` is already available there) as background threads - the
same established pattern `ros_bridge.py` already uses - never inside the
separate `ros` container, which stays dedicated to the stable, built-in
v0.1 ingestion nodes.

One concrete, additive decision: **new SDK-based connectors publish to a
sensor-id-keyed topic** (`/multisens/sensors/id/{sensor_id}/...`)
rather than the existing modality-keyed one
(`/multisens/sensors/{modality}/...`) - this is what lets two
same-modality live sensors (e.g. `ridesafe_front_rgb`/
`ridesafe_rear_rgb`) coexist going forward, without touching the
existing, working, modality-keyed contract
[connector-api.md](connector-api.md) documents. v0.9 does not build any
dashboard visualization for this new topic shape - only the capability
to publish it.

**The built-in RTSP integration is not rewritten.** Its plugin
registration (`multisens.builtin.sensor.rtsp`) is descriptor-only for
discovery/listing; `health()` is a pure mapping function from the
existing `RosBridge.snapshot()` per-sensor dict into `ConnectorHealth`.
The actual runtime (ROS launch off `config/sensors.yaml`,
`rtsp_ingestion_node.py`) is untouched - see Phase 96.

## `config/sensors.yaml` extension

Additive only - every existing entry with no `connector:` block keeps
working unchanged:

```yaml
sensors:
  - id: ridesafe_front_rgb
    connector:
      plugin: multisens.builtin.sensor.rtsp
      config:
        uri: rtsp://...
        transport: tcp
        password_env: CAMERA_PASSWORD   # resolved from os.environ at connect time, never persisted/echoed
```

## Secrets

A `*_env`-suffixed (or `{"env": "VAR_NAME"}`) config value is resolved
from `os.environ` at connect time only - never written to
`config/sensors.yaml` (which stays a git-tracked file), never persisted
to SQLite. **Defense in depth**: any config key case-insensitively
containing `password`/`token`/`secret`/`key` is redacted in every
`GET /api/connectors`/`GET /api/plugins` response and in logs,
regardless of whether it arrived literally or via env-reference.

## Failure isolation - achievable and not

**Achievable in-process**: every call into plugin code (discovery,
`configure`/`start`/`stop`/`health`/`poll`/`sample`/`evaluate`) is
wrapped at the call site. A discovery-time exception -> `LOAD_FAILED`,
other plugins keep loading. A runtime-method exception -> `FAILED` +
recorded error, never touches the FastAPI process or other connectors.

**Not achievable in-process, documented honestly, not hidden**: a
plugin that blocks forever synchronously (Python cannot force-kill a
thread), a native-extension segfault (kills the whole process), a
plugin that leaks threads/file descriptors it owns, a plugin that
mutates global state affecting others, or anything malicious done with
the full permissions of the process. This is the real boundary of
in-process isolation - see [Trust model](#trust-model).

## Duplicate registration

Two plugins sharing a `plugin_id`, an `evaluator_type`, or a resource
metric name are never arbitrarily resolved by picking one. The later
registration is rejected with a clear, specific error naming both
sources; the earlier one keeps working. Never a silent override -
matches the "never silently override" discipline `EVALUATOR_REGISTRY`
has carried since v0.8.

## API surface & frontend (Phase 102 - shipped)

See [Integrations API & UI (Phase 102 - shipped)](#integrations-api--ui-phase-102---shipped)
above for the full picture (the five routes, the redaction rule, the
`PluginRecord.factory` addition, and the `/integrations` page).

## Packaging

```dockerfile
FROM multisense-backend
RUN pip install my-plugin
```

No runtime internet installation, no automatic downloads - documented
with a worked example once Phase 106 lands.

## Contract testing (Phase 100)

`multisens_sdk.testing` (an opt-in `[testing]` extra, so `pytest` never
becomes a forced runtime dependency of every plugin): plain
pytest-compatible assertion helpers
(`assert_valid_descriptor`/`assert_connector_lifecycle`/
`assert_health_contract`, plus evaluator- and resource-collector-specific
variants) a plugin author can run against their own package.

## Reference plugin (Phase 101)

`examples/plugins/environment-sensor/` - an independently installable
package (its own `pyproject.toml`) implementing a deterministic
synthetic `SensorConnector` (`temperature`/`humidity`, labeled
`SYNTHETIC SAMPLE SOURCE`) and a trivial `synthetic_metric`
`ResourceCollector`, proving two plugin categories with one small
package. The actual clean-room test: installed into a clean environment,
its own imports verified to contain nothing from `backend.app`/
`frontend`/`ros2_ws` internals.

## Out of scope for v0.9

Plugin marketplace, cloud registry, remote/automatic installation,
plugin payments, an untrusted-plugin sandbox, Kubernetes/cluster
orchestration, automatic driver installation, arbitrary shell plugin
execution, user-written Python from the browser, a generic workflow
scripting engine, a visual plugin builder, domain-specific LiDAR/radar
algorithms, flight control, robotics control, a generic ROS-topic
connector with arbitrary message-type mapping, an MQTT connector (the
reference scalar plugin already proves non-camera extensibility without
one), and any live dashboard visualization for the new sensor-id-keyed
topic contract.

## Known limitations (v0.9, deliberate)

- No true process isolation - see [Trust model](#trust-model).
- Exact-match-only API-version compatibility, no range matching.
- No plugin configuration-editing UI - config changes require a restart,
  same as v0.1's sensor config today.
- No connector start/stop mutation API - observability only.
- No first-class LiDAR/point-cloud/IMU schemas in core - a payload's
  `data_type` is an open string core never semantically interprets;
  "can register a connector" is never conflated with "core understands
  the data."
- ARM64/Jetson compatibility of the SDK design is reviewed (pure Python
  + pydantic, no native deps), not yet tested against real Jetson
  hardware - no such hardware is reachable in this development
  environment, same honest deferral as v0.7's own Jetson limitation.
