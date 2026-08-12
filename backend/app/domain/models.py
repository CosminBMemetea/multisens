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
