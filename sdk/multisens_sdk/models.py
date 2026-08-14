"""Canonical wire-shape models (relocated from `backend/app/domain/models.py`
and `backend/app/domain/resources.py` in v0.9, Phase 93 - same classes, same
fields, same validation, moved so a plugin can construct a real `Prediction`/
`GroundTruth`/`EvaluationResult`/`ResourceObservation` without importing
MultiSens backend internals at all.

Backend re-exports every one of these unchanged from
`app.domain.models`/`app.domain.resources` - no call site anywhere in the
existing 730-test backend suite needed to change its import path. See
docs/plugin-sdk.md#the-central-decision-canonical-models-move-into-the-sdk
in the main repository for why this relocation exists.

`Scenario`/`Session` and every comparison-layer model
(`PairwiseComparison`, `ComparisonSide`, ...) deliberately stay
backend-only - no plugin contract ever constructs one, so relocating them
would only make this package bigger for no plugin-facing benefit (the
SDK's own "keep it small" principle, docs/plugin-sdk.md).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# A metric value of None means "not calculable" (e.g. zero denominator) and
# must render as N/A - never coerced to 0.0, which would mean something
# different (calculated, and the answer was zero).
MetricValue = float | None


def derive_configuration_id(sensor_ids: list[str]) -> str:
    """Canonical id for a set of sensors - same sensor_ids in any order
    always produce the same id. Not a pre-registered resource: an ad-hoc
    combination works with zero setup, same as sensor_ids itself."""
    return 'cfg-' + '-'.join(sorted(sensor_ids))


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
    # derive_configuration_id above. Left settable so a repository layer
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
    # Which Evaluator produced this result - 'classification' for every
    # pre-v0.8 row, explicit on every new one. Never inferred from metric
    # names or task strings.
    evaluator_type: str = 'classification'
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
    # Generic evaluator-specific structured evidence that doesn't fit the
    # flat metrics dict - e.g. a detection evaluator's per-class precision/
    # recall breakdown. None whenever an evaluator has nothing beyond its
    # flat metrics to report.
    details: dict[str, Any] | None = None
    computed_at: datetime


# --- resource observations (v0.7) -------------------------------------------
#
# ResourceQuality's four values:
#   - MEASURED: captured directly by a collector during the experiment.
#   - DECLARED: a human-supplied value, not measured this session.
#   - ESTIMATED: computed from an explicit, visible formula over
#     MEASURED/DECLARED values (`source` names the formula verbatim).
#   - UNAVAILABLE: no reliable value exists. `value` is None, reported as
#     an explicit row, never silently dropped and never coerced to 0.0.
ResourceQuality = Literal['measured', 'declared', 'estimated', 'unavailable']


class ResourceObservation(BaseModel):
    """One measured/declared/estimated/unavailable value for one metric,
    over one time window, optionally attributed to one configuration."""
    id: str
    session_id: str
    # None only for a genuinely unattributed/system-wide reading -
    # reported explicitly, never guessed at.
    configuration_id: str | None = None
    metric: str
    # None iff quality == 'unavailable', enforced below. 0.0 is a valid,
    # distinct measured value, never confused with "no value."
    value: float | None
    unit: str
    quality: ResourceQuality
    # Always populated, never blank even for a measured row - e.g.
    # 'psutil.cpu_percent', 'user_declared', or an ESTIMATED row's exact
    # formula. Free text by design, not a closed enum.
    source: str
    platform_id: str
    started_at: datetime
    ended_at: datetime
    # How many individual samples this row folds together - 1 for a true
    # point sample, >1 for a collector's periodic summary window. Always
    # >= 1, even for an UNAVAILABLE row (the collector still attempted at
    # least one sample).
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
