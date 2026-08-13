"""`Evaluator`/`EvaluatorOutput` shapes (v0.8, Phase 78), split out of
`evaluators.py` in Phase 82.

`evaluators.py` owns `EVALUATOR_REGISTRY`, which has to import every
evaluator-specific algorithm module (`detection.py`, ...) to populate
itself. Those same modules need `EvaluatorOutput`/`Evaluator` to build
and type their own `evaluate()` return values. If both lived in
`evaluators.py`, that would be a real import cycle (`evaluators.py` ->
`detection.py` -> `evaluators.py`) - this module is the shared home
both sides can depend on without one importing the other.
`evaluators.py` re-exports both names, so `from app.domain.evaluators
import EvaluatorOutput` (every existing call site) is unaffected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.matching import MatchResult
from app.domain.models import MetricValue


@dataclass
class EvaluatorOutput:
    """What any `Evaluator.evaluate()` call returns - the same shape
    `EvaluationResult` persists (Phase 78 migration), regardless of which
    evaluator produced it. `metrics` stays flat (`dict[str, MetricValue]`,
    same open-vocabulary posture `AcceptanceCriterion.metric` already
    has) - a value that could be `None` is `None`, never a fabricated
    zero, same `MetricValue` rule as everywhere else in this codebase.
    `details` is the one generic escape hatch for whatever structured
    evidence doesn't fit a flat float dict (a per-class breakdown, a
    confusion matrix, ...) - `None` whenever an evaluator has nothing
    beyond its flat metrics to report."""
    sample_count: int
    matched_samples: int
    unmatched_predictions: int
    unmatched_ground_truth: int
    metrics: dict[str, MetricValue]
    details: dict[str, Any] | None = None


class Evaluator(Protocol):
    """The contract every evaluator type implements. `evaluator_type` is
    the exact string a caller passes to `/evaluate`'s own `evaluator_type`
    field and the exact string recorded on the resulting
    `EvaluationResult.evaluator_type` - never a display name, never
    inferred. `format_version` is this evaluator's own result-shape
    version (independent per evaluator type - a detection evaluator's
    '1.0' is unrelated to classification's), recorded on
    `EvaluationResult.format_version`.

    `evaluate` takes an already-computed `MatchResult` (frame-level
    timestamp association, matching.py - never re-derived here) plus
    whatever evaluator-specific configuration the caller supplied (e.g. a
    detection evaluator's `confidence_threshold`/`iou_threshold`) - never
    a raw ground-truth/prediction list, and never persistence/FastAPI/ROS
    access, matching every other domain module's transport-agnostic
    discipline."""
    evaluator_type: str
    format_version: str

    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput: ...
