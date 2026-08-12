"""Evaluation domain model (v0.2, Phase 10).

Transport-agnostic on purpose: a Prediction may arrive over REST, from an
imported file, or - later - from a ROS adapter, but this module has no
FastAPI, sqlite3, or rclpy import. It defines what a prediction or ground
truth event *is* once it has arrived, not how it got here.

`value: dict` on GroundTruth/Prediction is deliberately generic rather than
a classification-specific `label: str` field: a v0.2 presence classification
event and a future detection bounding-box event both fit without a schema
change. Task-specific interpretation of `value` belongs to the metric
engine (Phase 13), not here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SessionStatus = Literal['created', 'running', 'completed', 'failed']

# A metric value of None means "not calculable" (e.g. zero denominator) and
# must render as N/A - never coerced to 0.0, which would mean something
# different (calculated, and the answer was zero).
MetricValue = float | None


def derive_configuration_id(sensor_ids: list[str]) -> str:
    """Canonical id for a set of sensors - same sensor_ids in any order
    always produce the same id. Not a pre-registered resource: an ad-hoc
    combination works with zero setup, same as sensor_ids itself."""
    return 'cfg-' + '-'.join(sorted(sensor_ids))


class Scenario(BaseModel):
    id: str
    name: str
    description: str = ''
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    id: str
    name: str
    scenario_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: SessionStatus = 'created'
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroundTruth(BaseModel):
    id: str
    session_id: str
    timestamp_ms: float
    task: str
    value: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class Prediction(BaseModel):
    id: str
    session_id: str
    timestamp_ms: float
    source_id: str
    sensor_ids: list[str]
    # Derived from sensor_ids, not chosen by the caller - see
    # _derive_configuration_id below. Left settable so a repository layer
    # can round-trip a row without recomputing it.
    configuration_id: str = ''
    task: str
    value: dict[str, Any]
    confidence: float | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator('sensor_ids')
    @classmethod
    def _sensor_ids_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError(
                'sensor_ids must not be empty - a prediction must declare '
                'at least one input sensor'
            )
        return v

    @field_validator('confidence')
    @classmethod
    def _confidence_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f'confidence must be within [0, 1], got {v}')
        return v

    @model_validator(mode='after')
    def _derive_configuration_id(self) -> Prediction:
        expected = derive_configuration_id(self.sensor_ids)
        if not self.configuration_id:
            self.configuration_id = expected
        elif self.configuration_id != expected:
            raise ValueError(
                f"configuration_id '{self.configuration_id}' does not match "
                f"sensor_ids {self.sensor_ids} (expected '{expected}') - "
                f"configuration_id is derived, not chosen"
            )
        return self


class EvaluationResult(BaseModel):
    id: str
    session_id: str
    configuration_id: str
    task: str
    format_version: str = '1.0'
    # Stored, not just passed in at evaluate-time and forgotten: a metric
    # number is not reproducible/auditable without knowing the tolerance
    # that produced its matched/unmatched split.
    tolerance_ms: float
    sample_count: int
    matched_samples: int
    unmatched_predictions: int
    unmatched_ground_truth: int
    metrics: dict[str, MetricValue]
    confusion_matrix: dict[str, Any] | None = None
    computed_at: datetime


# --- comparison (v0.3, Phase 20) ------------------------------------------
#
# Never a causal layer. A PairwiseComparison says configuration A measured
# differently from configuration B under stated conditions - it does not
# say why. `relationship` distinguishes a single-sensor change (the
# closest thing to attributable evidence this project will ever claim)
# from a general multi-sensor difference (evidence the two configurations
# differ, nothing more) - see docs/comparison.md once Phase 29 writes it,
# and PairwiseComparison's own docstring below in the meantime.
#
# Deliberately NOT persisted anywhere: every comparison is derived from
# already-persisted EvaluationResults plus already-persisted ground
# truth/predictions, recomputed on request. A named `Experiment` entity
# was considered and rejected for the same reason - a comparison request's
# own fields (session, task, baseline, candidates) already are what an
# Experiment would hold, and persisting a second copy of that shape would
# only add a place for it to drift from the request that actually ran.


class ComparisonValidity(BaseModel):
    """Evidence-quality verdict, never a statistical claim - no p-values,
    no confidence intervals - and never a compliance/requirement verdict
    either: this says whether the *comparison itself* is methodologically
    fair (same evidence, adequate common population), not whether either
    configuration is "good enough" for any purpose. A future requirement
    layer's PASS/FAIL/N/A is a different, not-yet-built judgment that
    would consume this evidence, not a renamed version of it. `reasons`
    must be non-empty whenever status isn't 'valid': never silently
    comparing incomparable configurations means always saying why, not
    just flagging that something's off."""
    status: Literal['valid', 'valid_with_warnings', 'invalid']
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def _reasons_required_unless_valid(self) -> ComparisonValidity:
        if self.status != 'valid' and not self.reasons:
            raise ValueError(f"status '{self.status}' requires at least one reason")
        return self


class MetricDelta(BaseModel):
    baseline: MetricValue
    candidate: MetricValue
    absolute: MetricValue  # candidate - baseline; None if either side is None
    # absolute / abs(baseline); None if baseline is None or zero - never a
    # division by zero, same N/A-not-fabricated rule as MetricValue itself.
    relative: MetricValue


class ComparisonMetrics(BaseModel):
    sample_count: int
    matched_samples: int
    unmatched_predictions: int
    unmatched_ground_truth: int
    # matched_samples / sample_count; None when sample_count is 0 - not
    # 0.0, which would mean "measured, and coverage was zero."
    coverage: MetricValue
    metrics: dict[str, MetricValue]


class ComparisonSide(BaseModel):
    """One of the two ways to compare a baseline/candidate pair.
    `reported` reads persisted EvaluationResults as-is (each side may have
    been computed with a different tolerance_ms). `common_set` filters
    both configurations' already-matched pairs down to the ground-truth
    ids *both* matched, so the comparison is over an identical sample
    population - see PairwiseComparison.tolerance_ms for which tolerance
    that filtering uses. Both sides are always computed together; there is
    no caller-selected either/or mode."""
    # Only meaningful on the common_set side; None on reported, which
    # never restricts to a shared population at all.
    common_sample_count: int | None = None
    baseline: ComparisonMetrics
    candidate: ComparisonMetrics
    metric_deltas: dict[str, MetricDelta]
    # Percentage POINTS: (candidate.coverage - baseline.coverage) * 100 -
    # never a relative percentage change of coverage itself, which is a
    # different and easily-confused quantity.
    coverage_delta_pp: MetricValue
    matched_sample_delta: int


class PairwiseComparison(BaseModel):
    session_id: str
    task: str
    baseline_configuration_id: str
    candidate_configuration_id: str
    # Resolved (not guessed) source per side - see the source-ambiguity
    # rule in docs/comparison.md once Phase 22 writes it: a configuration
    # with more than one distinct source_id for this task must be
    # disambiguated by the caller before a PairwiseComparison can exist at
    # all, so by the time one exists, both are always known. Carried here,
    # not just resolved internally and dropped, so evidence stays fully
    # traceable back to "which exact prediction source" - added after an
    # explicit product-direction review flagged its absence as the one
    # real traceability gap in the initial Phase 20 shape.
    baseline_source_id: str
    candidate_source_id: str
    tolerance_ms: float
    # Read from a real Prediction.sensor_ids row for each configuration,
    # never parsed out of a configuration_id string - see
    # derive_configuration_id, which documents why that string isn't a
    # safe thing to reverse-parse.
    added_sensors: list[str]
    removed_sensors: list[str]
    relationship: Literal['direct_addition', 'direct_removal', 'general']
    reported: ComparisonSide
    common_set: ComparisonSide
    validity: ComparisonValidity
    computed_at: datetime
