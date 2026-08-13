"""Resource-observation domain model (v0.7, Phase 64-69).

Phase 64 fixed the shape; Phase 65 added this module's own field/
cross-field validation (value-vs-quality consistency, non-empty
identity/unit/source fields, an ordered time window) plus persistence
(see app/persistence/migrations/0004_resource_observations.sql and
repository.py's resource_observations functions); Phase 66 added real
collection (app/resource_collector.py, deliberately NOT in this module -
see that module's own docstring for why); Phase 67 added
ResourceMetricSummary/ConfigurationResourceProfile, pure aggregation
over already-persisted rows; Phase 68 added ConfigurationTradeoff
(joining v0.6 decision evidence with v0.7 resource evidence, without
merging their semantics), comparability rules, and resource deltas;
Phase 69 adds explicit resource constraints (reusing AcceptanceCriterion
directly, not a new grammar) and a resource-aware Pareto/dominance
generalization of decision.py's own already-tested 3-dimension version.
No overall_efficiency_score/deployment_score/any combined number exists
anywhere in this module - every phase's own tests grep-verify it.
ResourceMetricSummary.quality (added while building Phase 71's UI,
which needs to badge each summary's real provenance, not just each raw
row's) reports 'mixed' when a summary's contributing rows span more
than one quality tier - a genuine gap in Phase 67's original shape,
fixed here rather than left for the UI to paper over with a guess.

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

from app.domain.coverage import ACCEPTANCE_OPERATORS
from app.domain.decision import ConfigurationDecision, PolicyStatus
from app.domain.profiles import AcceptanceCriterion

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
    owns that policy, e.g. "prefer measured, fall back to declared").
    It DOES always honestly report which quality tier(s) actually
    contributed via `quality` - 'mixed' when the population spans more
    than one, never silently collapsed to whichever tier happens to be
    most common. A UI badge showing "MEASURED" over a value that's
    actually part-declared would misrepresent its provenance."""
    mean: float
    median: float
    p95: float
    min: float
    max: float
    sample_count: int
    unit: str
    quality: ResourceQuality | Literal['mixed']


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
    real_valued = [o for o in observations if o.value is not None]
    if not real_valued:
        return None
    units = {o.unit for o in real_valued}
    if len(units) > 1:
        raise ValueError(f'cannot summarize observations with mixed units: {sorted(units)}')

    qualities = {o.quality for o in real_valued}
    quality: ResourceQuality | Literal['mixed'] = qualities.pop() if len(qualities) == 1 else 'mixed'

    values = [o.value for o in real_valued]
    sorted_values = sorted(values)
    return ResourceMetricSummary(
        mean=statistics.fmean(values),
        median=statistics.median(sorted_values),
        p95=_percentile(sorted_values, 0.95),
        min=sorted_values[0],
        max=sorted_values[-1],
        sample_count=len(values),
        unit=units.pop(),
        quality=quality,
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


# --- trade-off engine (v0.7, Phase 68) --------------------------------------
#
# Joins v0.4/v0.6 decision evidence with v0.7 resource evidence, without
# merging their semantics - a pure composition, never a re-decision. If
# this layer and evaluate_configurations/compute_configuration_resource_
# profile ever disagree about a value, that's a bug in this layer, never
# a second opinion (same posture v0.5's own module docstring already
# states for its relationship to v0.4).

@dataclass
class ConfigurationTradeoff:
    """One configuration's decision evidence and resource evidence,
    side by side - never blended into one number (master prompt §16,
    already enforced in decision.py: no universal importance/efficiency
    score exists anywhere in this project, and this type doesn't add
    one either)."""
    configuration_id: str
    sensor_count: int
    requirement_coverage: float | None
    evidence_completeness: float | None
    policy_status: PolicyStatus
    resource_profile: ConfigurationResourceProfile | None
    resource_validity: Literal['complete', 'partial', 'unavailable']


def build_configuration_tradeoff(
    decision: ConfigurationDecision, resource_profile: ConfigurationResourceProfile | None,
) -> ConfigurationTradeoff:
    """Pure composition. Never re-decides policy_status/coverage/
    completeness - those come straight from `decision`, exactly as
    v0.6's evaluate_configurations already computed them. `resource_
    profile` is None whenever no resource evidence was ever gathered for
    this configuration (distinct from a profile that exists with
    validity='unavailable', meaning evidence was sought but none found) -
    resource_validity normalizes both cases to one honest status without
    losing the underlying distinction, which remains visible via
    resource_profile itself."""
    return ConfigurationTradeoff(
        configuration_id=decision.configuration_id,
        sensor_count=len(decision.sensor_ids),
        requirement_coverage=decision.aggregate.requirement_coverage,
        evidence_completeness=decision.aggregate.evidence_completeness,
        policy_status=decision.policy_status,
        resource_profile=resource_profile,
        resource_validity=resource_profile.validity if resource_profile is not None else 'unavailable',
    )


# A generous, explicitly-heuristic bound - same "documented heuristic,
# not evidence-based" honesty treatment as min_common_sample_count/
# coverage_warning_threshold_pp (docs/limitations.md). 10x is "not
# remotely the same order of magnitude," not a precisely justified
# statistical threshold.
_DURATION_ORDER_OF_MAGNITUDE_RATIO = 10.0


@dataclass
class ComparabilityResult:
    """Two resource profiles are directly comparable only if every rule
    below holds. Numbers and caveats are always returned together -
    `comparable` never silently gates the caller away from seeing the
    values, and a non-empty `warnings` list never silently normalizes
    the difference away."""
    comparable: bool
    warnings: list[str]


def check_comparability(
    profile_a: ConfigurationResourceProfile | None, metadata_a: dict[str, Any],
    profile_b: ConfigurationResourceProfile | None, metadata_b: dict[str, Any],
) -> ComparabilityResult:
    """`metadata_a`/`metadata_b` are the caller's own representative
    metadata for each side (e.g. one contributing ResourceObservation's
    `metadata`) - comparability needs `resolution`/`target_fps`, which
    live on ResourceObservation, not on ConfigurationResourceProfile
    itself (Phase 67 deliberately didn't carry it - this is the first
    layer that needs it, so it stays a caller-supplied parameter here
    rather than growing Phase 67's shape after the fact)."""
    warnings: list[str] = []

    if profile_a is None or profile_b is None:
        return ComparabilityResult(comparable=False, warnings=['no resource evidence on one or both sides'])

    if profile_a.platform_id == UNKNOWN_PLATFORM_ID or profile_b.platform_id == UNKNOWN_PLATFORM_ID:
        warnings.append("at least one side has an unresolved execution platform - never comparable, even to itself")
    elif profile_a.platform_id != profile_b.platform_id:
        warnings.append(f"different execution platforms: '{profile_a.platform_id}' vs '{profile_b.platform_id}'")

    resolution_a, resolution_b = metadata_a.get('resolution'), metadata_b.get('resolution')
    if resolution_a != resolution_b:
        warnings.append(f'different resolution: {resolution_a!r} vs {resolution_b!r}')

    fps_a, fps_b = metadata_a.get('target_fps'), metadata_b.get('target_fps')
    if fps_a != fps_b:
        warnings.append(f'different requested FPS: {fps_a!r} vs {fps_b!r}')

    if profile_a.measurement_window and profile_b.measurement_window:
        duration_a = (profile_a.measurement_window[1] - profile_a.measurement_window[0]).total_seconds()
        duration_b = (profile_b.measurement_window[1] - profile_b.measurement_window[0]).total_seconds()
        if duration_a > 0 and duration_b > 0:
            ratio = max(duration_a, duration_b) / min(duration_a, duration_b)
            if ratio > _DURATION_ORDER_OF_MAGNITUDE_RATIO:
                warnings.append(
                    f'measurement durations differ by {ratio:.1f}x '
                    f'({duration_a:.1f}s vs {duration_b:.1f}s) - not directly comparable durations'
                )

    return ComparabilityResult(comparable=len(warnings) == 0, warnings=warnings)


@dataclass
class ResourceMetricDelta:
    """One metric's baseline/candidate values and their difference -
    `delta` is None whenever either side lacks this metric, never a
    fabricated partial delta."""
    metric: str
    unit: str
    baseline: float | None
    candidate: float | None
    delta: float | None


@dataclass
class ConfigurationResourceDelta:
    """Composed the same way v0.6's SensorAdditionAnalysis composes a
    decision-evidence delta: many small, structured fields, never a
    single magic number. Describes an OBSERVED resource delta only -
    "candidate used +5.1 Mbps more than baseline," never "the added
    sensor cost 5.1 Mbps" or any other causal phrasing."""
    baseline_configuration_id: str
    candidate_configuration_id: str
    comparability: ComparabilityResult
    metric_deltas: list[ResourceMetricDelta]


def compute_resource_delta(
    baseline: ConfigurationTradeoff, baseline_metadata: dict[str, Any],
    candidate: ConfigurationTradeoff, candidate_metadata: dict[str, Any],
) -> ConfigurationResourceDelta:
    """Uses each side's per-metric mean as the representative value -
    the same statistic a headline comparison table would show first;
    median/p95/min/max remain available on each side's own
    ConfigurationResourceProfile for anyone who needs the fuller
    picture, not discarded here."""
    comparability = check_comparability(
        baseline.resource_profile, baseline_metadata, candidate.resource_profile, candidate_metadata,
    )

    baseline_metrics = baseline.resource_profile.metrics if baseline.resource_profile else {}
    candidate_metrics = candidate.resource_profile.metrics if candidate.resource_profile else {}
    metric_deltas = []
    for metric in sorted(set(baseline_metrics) | set(candidate_metrics)):
        b_summary = baseline_metrics.get(metric)
        c_summary = candidate_metrics.get(metric)
        b_value = b_summary.mean if b_summary else None
        c_value = c_summary.mean if c_summary else None
        delta = c_value - b_value if b_value is not None and c_value is not None else None
        unit = (b_summary or c_summary).unit
        metric_deltas.append(ResourceMetricDelta(metric=metric, unit=unit, baseline=b_value, candidate=c_value, delta=delta))

    return ConfigurationResourceDelta(
        baseline_configuration_id=baseline.configuration_id,
        candidate_configuration_id=candidate.configuration_id,
        comparability=comparability,
        metric_deltas=metric_deltas,
    )


# --- resource constraints (v0.7, Phase 69) ----------------------------------
#
# Reuses AcceptanceCriterion's exact shape (metric/operator/value) - not
# a second criterion grammar - and coverage.py's own ACCEPTANCE_OPERATORS
# mapping, so a resource constraint can never silently disagree with how
# v0.4 already applies '>=' / '<=' / '>' / '<' / '=='.

ResourceConstraintStatus = Literal['pass', 'fail', 'na']


@dataclass
class ResourceConstraintResult:
    criterion: AcceptanceCriterion
    # None iff status == 'na' - the metric had no real value in this
    # profile (unavailable, or never requested). Never coerced to 0.0.
    observed: float | None
    status: ResourceConstraintStatus


def evaluate_resource_constraint(
    criterion: AcceptanceCriterion, profile: ConfigurationResourceProfile,
) -> ResourceConstraintResult:
    """Uses the profile's mean for `criterion.metric` as the observed
    value - the same representative statistic compute_resource_delta
    uses, for the same reason (median/p95/min/max stay available on the
    profile itself for anyone who needs them). A metric absent from
    `profile.metrics` (never measured, or measured but entirely
    unavailable - Phase 67 already excludes all-unavailable metrics from
    the dict) is always 'na', never 'fail' - an unmeasured constraint is
    not the same claim as a measured-and-failing one, same posture
    evaluate_criterion already takes for coverage requirements (v0.4)."""
    summary = profile.metrics.get(criterion.metric)
    if summary is None:
        return ResourceConstraintResult(criterion=criterion, observed=None, status='na')
    passed = ACCEPTANCE_OPERATORS[criterion.operator](summary.mean, criterion.value)
    return ResourceConstraintResult(criterion=criterion, observed=summary.mean, status='pass' if passed else 'fail')


QualificationStatus = Literal['qualifies', 'does_not_qualify', 'undetermined']


def evaluate_resource_qualification(constraint_results: list[ResourceConstraintResult]) -> QualificationStatus:
    """A direct 3-state map - deliberately NOT the same best-case/worst-
    case N/A-resolution bounding evaluate_policy (decision.py) uses for
    unresolved evaluation evidence. That bounding exists because an
    evaluation N/A can only ever resolve to pass or fail *later*, as more
    testing happens - a missing resource measurement has no equivalent
    "will resolve later" property; it is just missing, now, for this
    exact measurement window. Applying the same hypothetical-bounding
    math here would be a category error, not a consistency win - do not
    "fix" this to match evaluate_policy.

    Any FAIL dominates (does_not_qualify), regardless of how many other
    constraints pass. Any N/A with everything else passing ->
    undetermined - never treated as qualifying, since an unmeasured
    constraint is not evidence that it would have passed. Zero
    constraints -> undetermined, never a vacuous qualifies (same "empty
    population is never silently a real answer" discipline used
    throughout this project)."""
    if not constraint_results:
        return 'undetermined'
    if any(r.status == 'fail' for r in constraint_results):
        return 'does_not_qualify'
    if any(r.status == 'na' for r in constraint_results):
        return 'undetermined'
    return 'qualifies'


# --- resource-aware Pareto / dominance (v0.7, Phase 69) ---------------------
#
# A mechanical generalization of decision.py's own already-tested
# _dominates/find_pareto_front - not a second algorithm. decision.py's
# version is fixed to exactly 3 dimensions (sensor_count minimize,
# requirement_coverage maximize, evidence_completeness maximize); this
# version takes an arbitrary caller-chosen dict of dimensions, each
# tagged minimize/maximize, so v0.7 can add resource metrics (cpu,
# network, latency, ...) to the same trade-off analysis without
# reimplementing dominance. See test_resource_pareto.py's own
# equivalence test: called with exactly decision.py's 3 dimensions, this
# produces identical results to decision.py's fixed version on every
# scenario decision.py's own test suite already covers.

ParetoDirection = Literal['minimize', 'maximize']


@dataclass
class ParetoPoint:
    """One candidate's coordinates in an arbitrary-dimension trade-off
    space. `id` is opaque to this module - typically a configuration_id,
    never interpreted or parsed here. A dimension name absent from
    `values`, or present with value None, is treated identically -
    "no known value on this dimension" - never a fabricated 0."""
    id: str
    values: dict[str, float | None]


def _dimension_ge(x: float | None, y: float | None, direction: ParetoDirection) -> bool:
    """x is same-or-better than y on this dimension. None is always
    worst, regardless of direction - not knowing a value is never
    better than knowing one, whether higher or lower is preferred here.
    Reduces exactly to decision.py's _ge_treating_none_as_worst when
    direction='maximize'."""
    if x is None and y is None:
        return True
    if x is None:
        return False
    if y is None:
        return True
    return x <= y if direction == 'minimize' else x >= y


def _dimension_gt(x: float | None, y: float | None, direction: ParetoDirection) -> bool:
    """Reduces exactly to decision.py's _gt_treating_none_as_worst when
    direction='maximize'."""
    if x is None:
        return False
    if y is None:
        return True
    return x < y if direction == 'minimize' else x > y


def dominates_general(a: ParetoPoint, b: ParetoPoint, dimensions: dict[str, ParetoDirection]) -> bool:
    """`a` dominates `b` iff `a` is same-or-better than `b` on every
    dimension in `dimensions`, and strictly better on at least one -
    the exact master-prompt definition decision.py's own _dominates
    already implements for its fixed 3 dimensions."""
    for name, direction in dimensions.items():
        if not _dimension_ge(a.values.get(name), b.values.get(name), direction):
            return False
    return any(
        _dimension_gt(a.values.get(name), b.values.get(name), direction)
        for name, direction in dimensions.items()
    )


def find_dominated_points(points: list[ParetoPoint], dimensions: dict[str, ParetoDirection]) -> list[ParetoPoint]:
    """O(n^2) pairwise, same justification as decision.py's own version -
    configuration count is bounded by evaluated evidence, never a
    generated power set."""
    return [
        candidate for candidate in points
        if any(dominates_general(other, candidate, dimensions) for other in points if other is not candidate)
    ]


def find_pareto_front_general(points: list[ParetoPoint], dimensions: dict[str, ParetoDirection]) -> list[ParetoPoint]:
    dominated_ids = {p.id for p in find_dominated_points(points, dimensions)}
    return [p for p in points if p.id not in dominated_ids]
