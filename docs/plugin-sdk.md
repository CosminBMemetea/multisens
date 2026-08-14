# Plugin SDK & External Integration Framework (v0.9)

**Status: in progress (Phase 92 architecture review approved; Phase 93 -
the `multisens_sdk` package itself - shipped; Phases 94-106 not yet
built).** This document is the single authoritative decision record the
v0.9 phases build against - each phase updates its own section from
*planned* to *shipped* as it lands, and [CHANGELOG.md](../CHANGELOG.md)'s
eventual `[0.9.0]` entry is the record of what actually got built.
Sections describing the SDK package, its five contracts, and the model
relocation now describe real, tested code (`sdk/multisens_sdk/`, 19
dedicated tests, the full pre-existing 730-test backend suite passing
unchanged against it). Anywhere this document still says a component
"will" do something, that is a decision already made but not yet
implemented - runtime wiring (discovery, the registry, actual
connector/evaluator/collector execution) starts at Phase 94.

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

## Planned API surface (Phase 102)

Read-only; no plugin-installation mutation endpoints:

```
GET  /api/plugins
GET  /api/plugins/{plugin_id}
GET  /api/plugins/{plugin_id}/capabilities
GET  /api/connectors
GET  /api/connectors/{sensor_id}
```

## Planned frontend (Phase 102)

One new `/integrations` page - installed plugins and their connector
instances' state/health in a simple table, reusing existing badge
components. Never a marketplace-style browse/install affordance.

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
