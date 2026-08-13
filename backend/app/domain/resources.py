"""Resource-observation domain model (v0.7, Phase 64-67).

Phase 64 fixed the shape; Phase 65 added this module's own field/
cross-field validation (value-vs-quality consistency, non-empty
identity/unit/source fields, an ordered time window) plus persistence
(see app/persistence/migrations/0004_resource_observations.sql and
repository.py's resource_observations functions); Phase 66 added real
collection (app/resource_collector.py, deliberately NOT in this module -
see that module's own docstring for why); Phase 67 adds
ResourceMetricSummary/ConfigurationResourceProfile, pure aggregation
over already-persisted rows. Comparability/trade-off joining (Phase 68)
and constraints/Pareto (Phase 69) still don't live here yet.

Transport-agnostic like every other domain module - no fastapi, sqlite3,
rclpy, or psutil import. `ResourceObservation` is a pydantic `BaseModel`
like `GroundTruth`/`Prediction` (models.py), not a plain dataclass like
decision.py's `ConfigurationEvidence`/`ConfigurationDecision` - the
distinction that matters is persisted/ingested evidence (pydantic, this
module) versus pure in-memory computation artifacts (dataclass,
decision.py's own types and this module's later-phase
`ConfigurationResourceProfile`/`ConfigurationTradeoff`).

## Why a resource observation is not just another diagnostics stream

v0.1's `system_diagnostics_node` already measures `cpu_percent`/
`memory_percent` via psutil, continuously, forever, streamed live over
`/multisens/diagnostics` -> WebSocket -> dashboard. That mechanism is
correct for what it does but wrong for what v0.7 needs: it has no
time-window concept (a resource observation must be scoped to one
session's start/stop), no persistence (a resource observation must
survive restart to support before/after comparison), and no
configuration attribution (it is a single host-wide number, never "this
number, because these sensors were active"). Phase 66's collector will
call the *same* underlying psutil primitives system_diagnostics_node
already uses - reusing the measurement, not duplicating it - but wrap
them in a new, session-window-aware, persisting mechanism. See
docs/decision-support.md and the v0.7 architecture review (issue #65)
for the full reasoning.

## Configuration attribution is temporal association, not process isolation

Without per-configuration process isolation on a shared host, "this CPU
reading belongs to configuration X" can only ever mean "X was the
configuration actively running while this window was measured" - never
a rigorous causal or isolated cost. `ResourceObservation.configuration_id`
records exactly that association, nothing stronger. Every surface that
renders a resource number must carry this caveat, not just this
docstring - see docs/resources.md (Phase 77).

## Persistence: bounded periodic summary rows, not raw samples

A `ResourceObservation` row is already a small pre-aggregated window (a
collector samples repeatedly for ~5-10s and folds the result into one
row, `sample_count` recording how many samples went in) - there is no
separate raw-sample table in v0.7. A "resource over time" chart is the
sequence of these rows for one `(session_id, configuration_id, metric)`;
a whole-session summary (mean/median/p95/min/max, Phase 67) is a pure
computed aggregation *over* those persisted rows at read time, never a
second stored source of truth - same pattern `aggregate_requirement_results`
already uses for `RequirementResult`. This is a deliberate, narrow
exception to this project's "recompute, never persist" norm: unlike a
`RequirementResult`, a resource-measurement window cannot be recomputed
later once the window has passed, so the summary row itself has to be
the persisted artifact.

## Session, not a new ResourceMeasurementRun entity

`Session.id` plus each observation's own `started_at`/`ended_at`
sub-window is sufficient to answer "was this measured during session X,
over what window" - no new entity. Revisit only if a real need for
several independent measurement windows within one session, that
`Session`'s own fields cannot express, actually shows up.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Every value has an explicit provenance - never just a number.
#
#   - MEASURED: captured directly by a v0.7 collector during the
#     experiment (psutil calls, or the existing fps_received/
#     publish_latency_ms diagnostics reused as-is). Always preferred.
#   - DECLARED: a human-supplied hardware/property value (e.g. "this
#     camera's nominal bitrate is 5 Mbps"), not measured this session.
#     Coexists with a MEASURED row for the same metric without
#     auto-reconciliation - same "never silently merge two evidence
#     sources" discipline EvidenceBinding already established (v0.4).
#   - ESTIMATED: computed from an explicit, visible formula over
#     MEASURED/DECLARED values (`source` names the formula verbatim,
#     e.g. "estimated: bitrate_mbps * duration_hours"). Never an opaque
#     second estimate with no visible inputs.
#   - UNAVAILABLE: no reliable value exists. `value` is None. Reported
#     as an explicit row, never silently dropped - same "NO EVIDENCE,
#     always reported" discipline v0.6's decision layer established.
#     Never coerced to 0.0, which would claim a measurement that never
#     happened (same "unavailable is not zero" rule v0.1's diagnostics
#     already follows for frames_dropped).
ResourceQuality = Literal['measured', 'declared', 'estimated', 'unavailable']

# The v0.7 supported metric vocabulary - deliberately small (architecture
# review, "keep v0.7 small"). Each is genuinely obtainable today, either
# via a new session-scoped collector reusing existing psutil primitives
# (cpu_percent, memory_mb, network_receive_mbps, network_transmit_mbps)
# or by reusing an existing per-sensor diagnostic field outright (fps ==
# fps_received, pipeline_latency_ms == publish_latency_ms, renamed only
# for clarity - not a new measurement).
#
# GPU/power/temperature/storage-write are deliberately NOT in this set:
# no discrete-GPU passthrough and no Jetson exist in the current dev
# environment, so shipping those collectors now would mean code no one
# can exercise or verify (architecture review, "what I would remove").
# storage-write specifically is never measured in v0.7 at all - storage
# is an ESTIMATED derived quantity (bitrate x duration, a later phase),
# never a disk-IO collector.
#
# `ResourceObservation.metric` itself stays a plain `str`, not this
# Literal - same open-vocabulary posture `AcceptanceCriterion.metric`
# already has (profiles.py). This constant is the API-boundary
# validation reference (Phase 70), not a domain-layer enum.
SUPPORTED_RESOURCE_METRICS: dict[str, str] = {
    'cpu_percent': '%',
    'memory_mb': 'MB',
    'network_receive_mbps': 'Mbps',
    'network_transmit_mbps': 'Mbps',
    'fps': 'fps',
    'pipeline_latency_ms': 'ms',
}


class ResourceObservation(BaseModel):
    """One measured/declared/estimated/unavailable value for one metric,
    over one time window, optionally attributed to one configuration.
    Persisted (v0.7, Phase 65) - the ingested-evidence shape, not a
    computed artifact; see this module's own docstring for why that
    makes it a pydantic BaseModel like GroundTruth/Prediction rather
    than a decision.py-style dataclass."""
    id: str
    session_id: str
    # None only for a genuinely unattributed/system-wide reading -
    # reported explicitly, never guessed at. See "configuration
    # attribution is temporal association" above for what a non-None
    # value actually means (and does not mean).
    configuration_id: str | None = None
    metric: str
    # None iff quality == 'unavailable' - enforced below by
    # _value_matches_quality. 0.0 is a valid, distinct measured value,
    # never confused with "no value."
    value: float | None
    unit: str
    quality: ResourceQuality
    # Always populated, never blank even for a measured row - e.g.
    # 'psutil.cpu_percent', 'user_declared', or an ESTIMATED row's exact
    # formula. Free text by design, not a closed enum - mirrors
    # RequirementResult.reasons's own free-text-with-a-real-value
    # posture.
    source: str
    platform_id: str
    started_at: datetime
    ended_at: datetime
    # How many individual samples this row folds together - 1 for a
    # true point sample, >1 for a collector's periodic summary window
    # (see "persistence" above). Always >= 1, even for an UNAVAILABLE
    # row (the collector still attempted at least one sample).
    sample_count: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator('unit', 'source', 'platform_id')
    @classmethod
    def _non_empty(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(f'{info.field_name} must not be empty')
        return v

    @field_validator('sample_count')
    @classmethod
    def _sample_count_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f'sample_count must be >= 1, got {v}')
        return v

    @model_validator(mode='after')
    def _value_matches_quality(self) -> ResourceObservation:
        # Never a fabricated zero standing in for "no value," and never a
        # real value silently reported as unavailable - the two failure
        # directions are equally wrong, so both are checked.
        if self.quality == 'unavailable' and self.value is not None:
            raise ValueError("value must be None when quality is 'unavailable'")
        if self.quality != 'unavailable' and self.value is None:
            raise ValueError(f"value must not be None when quality is '{self.quality}'")
        return self

    @model_validator(mode='after')
    def _window_is_ordered(self) -> ResourceObservation:
        if self.started_at > self.ended_at:
            raise ValueError(
                f'started_at ({self.started_at.isoformat()}) must not be after '
                f'ended_at ({self.ended_at.isoformat()})'
            )
        return self


class ExecutionPlatform(BaseModel):
    """The compute context a resource observation was measured under -
    e.g. 'Apple M2, Docker Desktop' vs. 'Jetson Orin, Ubuntu'. A small,
    explicitly-declared record (like config/sensors.yaml's own posture:
    declared, never auto-detected by magic), not a database table -
    realistically 1-3 platforms will ever exist for this project. Zero
    NVIDIA/Apple-specific fields anywhere - a future GPU metric is just
    another entry in SUPPORTED_RESOURCE_METRICS collected by a
    platform-specific collector that returns 'unavailable' where it
    doesn't apply, never a branch on vendor in this model."""
    id: str
    display_name: str
    architecture: str
    os: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# Fallback platform id for any observation whose collector could not
# determine a real ExecutionPlatform - never silently None (every
# ResourceObservation.platform_id is always populated), but honestly
# named so a comparability check (Phase 68) can treat it as never
# comparable to anything, including itself.
UNKNOWN_PLATFORM_ID = 'unknown'


# --- resource summaries (v0.7, Phase 67) ------------------------------------
#
# Pure computed aggregation over already-persisted ResourceObservation
# rows - never a second stored source of truth, same pattern
# aggregate_requirement_results already uses for RequirementResult (v0.4).
# A "resource over time" chart (architecture review) is the underlying
# sequence of rows; these functions only summarize them for display.

@dataclass
class ResourceMetricSummary:
    """Computed over one metric's real-valued (value is not None)
    ResourceObservation rows. Does not itself decide which quality tier
    (measured/declared/estimated) to include - the caller passes exactly
    the rows it wants summarized; mixing qualities within one call is
    the caller's choice, not something this type resolves (Phase 68
    owns that policy, e.g. "prefer measured, fall back to declared")."""
    mean: float
    median: float
    p95: float
    min: float
    max: float
    sample_count: int
    unit: str


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolation percentile (matches numpy's default 'linear'
    method) - the standard, easily independently-reproducible choice for
    the small sample counts a v0.7-scale session actually produces. A
    single value has no interpolation to do."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = fraction * (len(sorted_values) - 1)
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def compute_resource_metric_summary(observations: list[ResourceObservation]) -> ResourceMetricSummary | None:
    """None if `observations` is empty or every row is unavailable
    (value is None) - never a fabricated zero-valued summary, same
    "empty/undecided population is never silently a real answer"
    discipline v0.6's evaluate_policy already established for zero
    requirements. Every observation passed in must share one unit -
    averaging Mbps with % would be silently meaningless, so a mismatch
    raises rather than picking one arbitrarily."""
    values = [o.value for o in observations if o.value is not None]
    if not values:
        return None
    units = {o.unit for o in observations if o.value is not None}
    if len(units) > 1:
        raise ValueError(f'cannot summarize observations with mixed units: {sorted(units)}')

    sorted_values = sorted(values)
    return ResourceMetricSummary(
        mean=statistics.fmean(values),
        median=statistics.median(sorted_values),
        p95=_percentile(sorted_values, 0.95),
        min=sorted_values[0],
        max=sorted_values[-1],
        sample_count=len(values),
        unit=units.pop(),
    )


@dataclass
class ConfigurationResourceProfile:
    """One configuration's resource evidence for one session, joined
    across whatever metrics were requested - the v0.7 counterpart to
    v0.6's AggregateCoverage. `observations` passed to the compute
    function below should already be scoped to this session/
    configuration/platform by the caller (Phase 68's comparability
    logic, not this module) - this type only aggregates and judges
    validity over what it's given."""
    configuration_id: str
    session_id: str
    platform_id: str
    metrics: dict[str, ResourceMetricSummary]
    # None only when no requested metric has any real-valued evidence at
    # all. Spans the full min(started_at)..max(ended_at) range across
    # every contributing row, including any gaps between windows -
    # windows need not be contiguous, and this is not a sum of only the
    # covered time, an honest span rather than a flattering one.
    measurement_window: tuple[datetime, datetime] | None
    validity: Literal['complete', 'partial', 'unavailable']
    warnings: list[str]


def compute_configuration_resource_profile(
    session_id: str, configuration_id: str, platform_id: str,
    requested_metrics: list[str], observations: list[ResourceObservation],
) -> ConfigurationResourceProfile:
    """`validity`: 'complete' iff every requested metric has at least one
    real-valued row (and at least one metric was actually requested -
    zero requested metrics is 'unavailable', never a vacuous 'complete');
    'partial' if some but not all do; 'unavailable' if none do."""
    metrics: dict[str, ResourceMetricSummary] = {}
    warnings: list[str] = []
    window_starts: list[datetime] = []
    window_ends: list[datetime] = []

    for metric in requested_metrics:
        metric_observations = [o for o in observations if o.metric == metric]
        summary = compute_resource_metric_summary(metric_observations)
        if summary is None:
            warnings.append(f"no measured/declared/estimated evidence for '{metric}' in this window")
            continue
        metrics[metric] = summary
        window_starts.extend(o.started_at for o in metric_observations if o.value is not None)
        window_ends.extend(o.ended_at for o in metric_observations if o.value is not None)

    if requested_metrics and len(metrics) == len(requested_metrics):
        validity: Literal['complete', 'partial', 'unavailable'] = 'complete'
    elif metrics:
        validity = 'partial'
    else:
        validity = 'unavailable'

    measurement_window = (min(window_starts), max(window_ends)) if window_starts else None

    return ConfigurationResourceProfile(
        configuration_id=configuration_id, session_id=session_id, platform_id=platform_id,
        metrics=metrics, measurement_window=measurement_window, validity=validity, warnings=warnings,
    )
