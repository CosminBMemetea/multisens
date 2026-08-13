# Resource Observation Contract (v0.7)

The authoritative reference for MultiSens's resource-observation layer:
what a `ResourceObservation` is, the provenance vocabulary every value
carries, how observations are collected and persisted, and how they're
summarized into a per-configuration profile. See
[deployment-tradeoffs.md](deployment-tradeoffs.md) for what's built *on
top* of this layer (comparability, constraints, the generalized Pareto
front) and [decision-support.md](decision-support.md) for the v0.6
decision evidence this layer stays independent of.

## What this layer answers

> For one session, how much CPU/memory/network/latency/FPS did a given
> sensor configuration actually use - and how confident should anyone be
> in that number?

A genuinely different axis from every prior release: v0.2-v0.6 all
reason about *whether a configuration's output is good enough*. v0.7
reasons about *what it costs to run* - the two never merge into one
score (see [deployment-tradeoffs.md](deployment-tradeoffs.md#no-combined-score-anywhere-ever)).

## Why a resource observation is not just another diagnostics stream

v0.1's `system_diagnostics_node` already measures `cpu_percent`/
`memory_percent` via `psutil`, continuously, forever, streamed live over
`/multisens/diagnostics` → WebSocket → dashboard. That's correct for
what it does but wrong for what v0.7 needs: no time-window concept (a
resource observation must be scoped to one session's start/stop), no
persistence (must survive a restart to support before/after
comparison), and no configuration attribution (a live diagnostic is a
single host-wide number, never "this number, because these sensors were
active"). The v0.7 collector (`app/resource_collector.py`) calls the
*same* underlying `psutil` primitives - reusing the measurement, never
duplicating it - wrapped in a new, session-window-aware, persisting
mechanism.

## `ResourceQuality`: four values, never a fabricated number

```python
ResourceQuality = Literal['measured', 'declared', 'estimated', 'unavailable']
```

- **`measured`** - captured directly by a v0.7 collector during the
  experiment. Always preferred.
- **`declared`** - a human-supplied hardware/property value (e.g. "this
  camera's nominal bitrate is 5 Mbps"), not measured this session.
  Coexists with a `measured` row for the same metric without
  auto-reconciliation - same "never silently merge two evidence
  sources" discipline `EvidenceBinding` established in v0.4.
- **`estimated`** - computed from an explicit, visible formula over
  `measured`/`declared` values (`source` names the formula verbatim).
  Never an opaque second estimate with no visible inputs.
- **`unavailable`** - no reliable value exists. `value` is `None`,
  reported as an explicit row, never silently dropped - same `NO
  EVIDENCE`-is-always-reported discipline v0.6's decision layer
  established. Never coerced to `0.0`, which would claim a measurement
  that never happened.

`value is None` **iff** `quality == 'unavailable'` - enforced by a
pydantic cross-field validator in both directions: a real value can
never hide behind `unavailable`, and `unavailable` can never carry a
fabricated number. A genuine `0.0` reading (e.g. an idle host's network
transmit rate) is a completely different, valid `measured` row -
distinctness proven directly by
[test_resources.py](../backend/tests/test_resources.py) and, end to
end through the whole pipeline, by
[test_resource_robustness.py](../backend/tests/test_resource_robustness.py).

## `SUPPORTED_RESOURCE_METRICS`: the reviewed six

```python
SUPPORTED_RESOURCE_METRICS = {
    'cpu_percent': '%', 'memory_mb': 'MB',
    'network_receive_mbps': 'Mbps', 'network_transmit_mbps': 'Mbps',
    'fps': 'fps', 'pipeline_latency_ms': 'ms',
}
```

Deliberately small (v0.7 architecture review, "keep v0.7 small"). Each
is genuinely obtainable today: `cpu_percent`/`memory_mb`/
`network_receive_mbps`/`network_transmit_mbps` via a new session-scoped
collector reusing existing `psutil` primitives; `fps`/
`pipeline_latency_ms` by reusing `fps_received`/`publish_latency_ms`
outright, renamed only for clarity - not a new measurement.

**GPU/power/temperature/storage-write are deliberately excluded.** No
discrete-GPU passthrough and no Jetson exist in the environment this
release was built in, so shipping those collectors now would mean code
no one can exercise or verify - see the Jetson/cross-platform validation
deferral in [limitations.md](limitations.md). storage-write specifically
is never measured at all in v0.7; storage is only ever an `estimated`
derived quantity (bitrate × duration), never a disk-IO collector.

`ResourceObservation.metric` itself stays a plain `str`, not this
`Literal` - the same open-vocabulary posture `AcceptanceCriterion.metric`
already has. `SUPPORTED_RESOURCE_METRICS` is the API-boundary validation
reference (a `resource_metrics`/`resource_constraints` entry outside
this set is `422`), not a domain-layer enum.

**`unit` itself is a fully open string, not validated against this
table at ingestion.** A batch-ingested row can carry any `unit` value -
this is deliberate (same open-vocabulary posture as `metric`), but it
means a typo or a misconfigured collector can silently ingest a
mismatched unit. See
[deployment-tradeoffs.md](deployment-tradeoffs.md#a-mismatched-unit-is-caught-at-read-time-not-ingestion)
for what happens when two rows for the same metric/configuration
disagree on unit.

## Persistence: bounded periodic summary rows, not raw samples

A `ResourceObservation` row is already a small pre-aggregated window (a
collector samples repeatedly for ~5-10s and folds the result into one
row; `sample_count` records how many samples went in) - there is no
separate raw-sample table. A "resource over time" chart is the sequence
of these rows for one `(session_id, configuration_id, metric)`; a
whole-session summary (mean/median/p95/min/max) is a pure computed
aggregation *over* those persisted rows at read time, never a second
stored source of truth - the same pattern `aggregate_requirement_results`
already uses for `RequirementResult`. This is a deliberate, narrow
exception to this project's "recompute, never persist" norm: unlike a
`RequirementResult`, a resource-measurement window cannot be recomputed
later once the window has passed, so the summary row's inputs have to be
the persisted artifact.

## Configuration attribution is temporal association, not process isolation

Without per-configuration process isolation on a shared host, "this CPU
reading belongs to configuration X" can only ever mean "X was the
configuration actively running while this window was measured" - never
a rigorous causal or isolated cost. `ResourceObservation.configuration_id`
records exactly that association, nothing stronger, and it's optional -
`None` for a genuinely unattributed/system-wide reading, reported
explicitly, never guessed at.

## Session, not a new `ResourceMeasurementRun` entity

`Session.id` plus each observation's own `started_at`/`ended_at`
sub-window is sufficient to answer "was this measured during session X,
over what window" - no new entity. One consequence, confirmed by the
v0.7 robustness review: **a resource observation's window is never
cross-checked against the session's own evaluation-evidence timespan.**
A session whose ground truth/predictions span 500 seconds can carry a
resource observation window covering only 5 of those seconds, and
nothing in this layer flags the mismatch - `measurement_window` honestly
reports only what was actually measured, gaps and short windows
included, never fabricated to match the session's apparent duration.

## `ExecutionPlatform` and `UNKNOWN_PLATFORM_ID`

```python
class ExecutionPlatform(BaseModel):
    id: str
    display_name: str
    architecture: str
    os: str
    metadata: dict[str, Any] = {}
```

A small, explicitly-declared record - like `config/sensors.yaml`'s own
posture: declared, never auto-detected by magic - not a database table;
realistically 1-3 platforms will ever exist for this project. Zero
NVIDIA/Apple-specific fields anywhere: a future GPU metric is just
another entry in `SUPPORTED_RESOURCE_METRICS`, collected by a
platform-specific collector that returns `unavailable` where it doesn't
apply, never a branch on vendor in this model.

`UNKNOWN_PLATFORM_ID = 'unknown'` is the fallback whenever a
configuration's observations don't all agree on one `platform_id` (or
a collector genuinely couldn't determine one) - honestly named so
[deployment-tradeoffs.md](deployment-tradeoffs.md#comparability-four-independent-rules)'s
comparability check can treat it as never comparable, even to itself,
rather than silently picking one of the disagreeing values.

## Resource summaries: mean/median/p95/min/max, honest about quality

`compute_resource_metric_summary(observations)` → `ResourceMetricSummary
| None`:

- `None` if the population is empty or every row is `unavailable` -
  never a fabricated zero-valued summary, same "empty/undecided
  population is never silently a real answer" discipline v0.6's
  `evaluate_policy` established for zero requirements.
- Every real-valued observation passed in must share one `unit` -
  averaging Mbps with % would be silently meaningless, so a mismatch
  raises (surfaced by the API as a clean `422`, not an unhandled crash -
  see [deployment-tradeoffs.md](deployment-tradeoffs.md#a-mismatched-unit-is-caught-at-read-time-not-ingestion)).
- `p95` via linear interpolation (numpy's default `'linear'` method) -
  reproducible without a numpy dependency, verified against a
  hand-computed fixed dataset.
- `quality` reports the single shared tier when every contributing row
  agrees, or the literal string `'mixed'` when the population spans more
  than one tier - never silently collapsed to whichever tier happens to
  be most common. A UI badge showing "MEASURED" over a value that's
  actually part-`declared` would misrepresent its provenance; this field
  exists specifically so it can't.

`compute_configuration_resource_profile(...)` joins per-metric summaries
into one `ConfigurationResourceProfile` for a `(session, configuration,
platform)`:

- `validity`: `'complete'` iff every requested metric has real evidence
  (and at least one metric was actually requested - zero requested
  metrics is `'unavailable'`, never a vacuous `'complete'`); `'partial'`
  if some but not all do; `'unavailable'` if none do.
- `measurement_window` spans the full `min(started_at)..max(ended_at)`
  range across every contributing row, including any gaps between
  windows - an honest span, not a flattering sum of only the covered
  time.
- `warnings` names exactly which requested metric had no evidence,
  never silent.

## Collection: `app/resource_collector.py`

Deliberately **not** in `app/domain/` - like `ros_bridge.py`, it touches
a real system dependency (`psutil`) directly, so it belongs with the
other infra-facing translators, not the transport-agnostic domain layer.
Two independent paths, matching the architecture review's instruction
not to duplicate an existing measurement mechanism:

- **`SystemMetricsWindow`** - a session-window-bound collector for
  `cpu_percent`/`memory_mb`/`network_receive_mbps`/
  `network_transmit_mbps`. `start()` primes `psutil`'s internal
  `cpu_percent()` baseline and takes the network counters' starting
  snapshot (same "prime once before trusting the next reading"
  discipline `system_diagnostics_node` already documents); `end()`
  reads the real deltas and returns one row per metric. A zero-duration
  window's network rate is `unavailable`, never a divide-by-zero or a
  fabricated `0` Mbps.
- **`collect_sensor_metrics`** - not a new measurement at all. Translates
  fields `RosBridge.snapshot()` already carries (`fps_received`,
  `publish_latency_ms`) directly into `fps`/`pipeline_latency_ms` rows. A
  sensor absent from the snapshot produces explicit `unavailable` rows,
  never a fabricated `0` - distinct from `fps_received`'s own genuine
  measured `0.0` ("no frames received recently," a real reading, see
  [topics.md](topics.md)).

Collector overhead measured directly against this repo's own Docker
backend container: ~0.27ms per `start()`/`end()` pair - negligible next
to a realistic 5-10s collection window. Inherits the same
"reflects the Linux VM's overall resource view, not a cgroup-isolated
per-container figure" caveat [limitations.md](limitations.md) already
documents for the `ros` container's own diagnostics, now measured from
inside the **backend** container instead, and extended for the first
time to network metrics (host-interface-wide, not per-RTSP-stream).

## API surface

```
POST /api/sessions/{id}/resource-observations/batch
GET  /api/sessions/{id}/resource-observations
```

The batch endpoint follows the exact loose-dict/partial-failure pattern
`ground-truth`/`predictions` batch ingestion already established:
`{"accepted": N, "rejected": M, "errors": [...]}`, each bad item
reported with its index, good items never dropped because one sibling
item failed. The list endpoint is filterable by `configuration_id`/
`metric`, matching `predictions`' own filtered-query shape.

No file-import endpoint here either, same as every other ingestion path
in this project - see [limitations.md](limitations.md).

## Frontend

The "Resources" tab on `ProfileDetail.tsx` (sixth tab, alongside
Coverage/Explorer/Failures/Evidence/Decision) is where this layer and
[deployment-tradeoffs.md](deployment-tradeoffs.md)'s trade-off layer both
render:

- **`components/ResourcesPanel.tsx`** - a session picker (resource
  evidence is inherently single-session-scoped, see "Session, not a new
  `ResourceMeasurementRun` entity" above), a configuration resource table
  (Streams/Coverage/CPU/RAM/Network/Latency), calling `POST /tradeoffs`
  with every `SUPPORTED_RESOURCE_METRICS` entry requested. Missing
  values render as an em dash, never `"0"`.
- **`components/ResourceQualityBadge.tsx`** - an item-level badge (not a
  page banner) - `MEASURED`/`DECLARED`/`ESTIMATED`/`UNAVAILABLE`/`MIXED`,
  with real `platform_id` context appended, never an invented friendly
  name.
- **`components/ResourceTimeSeriesChart.tsx`** - a plain inline SVG
  polyline, no charting library - matches this project's existing
  no-unnecessary-dependency posture; only mounted when a metric actually
  has ≥2 real-valued points.
- A resource detail drill-down shows mean/median/p95/min/max/
  sample_count, the quality+platform badge, the time-series chart, and a
  per-row contributing-observations list (each with its own quality
  badge) - so a `mixed` population's true composition is visible, not
  collapsed into a guess.

## Known resource-layer limitations

See [limitations.md](limitations.md) for the current authoritative list;
summarized here: only six metrics are supported (no GPU/power/
temperature/storage-write); a resource observation's `unit` is fully
open at ingestion, not validated against `SUPPORTED_RESOURCE_METRICS`;
`measurement_window` is never cross-checked against a session's own
evaluation-evidence timespan; resource evidence is measured from inside
whichever container the collector runs in (Docker-Desktop-VM caveat
inherited from v0.1's own diagnostics, now extended to network metrics);
and cross-platform comparison has only ever been exercised with one
platform in the environment this release was built in (Jetson/
cross-platform validation explicitly deferred - see
[deployment-tradeoffs.md](deployment-tradeoffs.md#comparability-four-independent-rules)).
