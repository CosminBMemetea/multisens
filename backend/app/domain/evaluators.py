"""Generic evaluator abstraction (v0.8, Phase 78-79).

`ClassificationEvaluator` (Phase 79) is the first real entry in
`EVALUATOR_REGISTRY` - a thin wrapper around the existing, completely
unchanged `evaluate_classification` (metrics.py). Phase 80-83 add
detection/regression the same way: a small `Evaluator`-shaped wrapper
living here, delegating to its own algorithm module, registered at the
bottom of this file. See the v0.8 architecture review (issue #79) for
the full reasoning.

## Why `Evaluator.evaluate` takes a `MatchResult`, not raw ground truth/predictions

Timestamp-based frame association (`app/domain/matching.py`) is already a
separate, evaluator-blind pass from metric computation in this codebase -
`match_by_timestamp` has never inspected a `value` field, and won't start
now. An evaluator only ever needs "here are the frame-matched pairs, plus
whatever's still unmatched" - it never re-derives that association
itself. This keeps object-level matching (v0.8's detection evaluator,
Phase 81) a clearly separate second pass *within* an already-timestamp-
matched frame, never conflated with it (master prompt §14).

## Why there's no `TaskDefinition` registry

Evaluator identity is stated explicitly on every `/evaluate` request
(`evaluator_type`, mirroring how `tolerance_ms`/`DecisionPolicy` are
already always explicit-per-call, never looked up from stored metadata)
and recorded directly on the resulting `EvaluationResult` row - which is
therefore self-describing and authoritative on its own. A separate
task-to-evaluator-type table would be a second source of truth that
could drift from what a given result actually recorded, for no
demonstrated benefit - the same "don't add an entity before scope
demonstrates the need" reasoning that kept a v0.3 `Experiment` entity and
a v0.7 `ResourceMeasurementRun` entity out of this codebase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.matching import MatchResult
from app.domain.metrics import evaluate_classification
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

    `evaluate` takes an already-computed `MatchResult` (see this module's
    own docstring for why) plus whatever evaluator-specific configuration
    the caller supplied (e.g. a detection evaluator's
    `confidence_threshold`/`iou_threshold`) - never a raw ground-truth/
    prediction list, and never persistence/FastAPI/ROS access, matching
    every other domain module's transport-agnostic discipline."""
    evaluator_type: str
    format_version: str

    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput: ...


class ClassificationEvaluator:
    """Wraps `evaluate_classification` (metrics.py) - that function itself
    is completely unchanged by this phase; this class only translates its
    `ClassificationMetrics` shape into the generic `EvaluatorOutput` shape.
    `parameters` is accepted (protocol conformance) but unused - v0.8's
    classification evaluator has no configurable parameters, same as
    before this phase existed. The confusion matrix moves into
    `details['confusion_matrix']` - the generic structured-evidence slot -
    rather than a dedicated field on `EvaluatorOutput` itself, so future
    evaluators that also want a confusion-matrix-shaped result (or
    anything else structured) don't need a second special-cased field."""
    evaluator_type = 'classification'
    format_version = '1.0'

    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput:
        cm = evaluate_classification(match_result)
        return EvaluatorOutput(
            sample_count=cm.sample_count,
            matched_samples=cm.matched_samples,
            unmatched_predictions=cm.unmatched_predictions,
            unmatched_ground_truth=cm.unmatched_ground_truth,
            metrics={
                'accuracy': cm.accuracy,
                'precision_macro': cm.precision_macro,
                'recall_macro': cm.recall_macro,
                'f1_macro': cm.f1_macro,
                'precision_micro': cm.precision_micro,
                'recall_micro': cm.recall_micro,
                'f1_micro': cm.f1_micro,
            },
            details={'confusion_matrix': {'labels': cm.confusion_matrix.labels, 'counts': cm.confusion_matrix.counts}},
        )


# Static, not a dynamic plugin-loading mechanism (master prompt §6) -
# realistically 3-4 evaluator types will ever exist for this project.
# Phase 80-83 add 'object_detection'/'regression' here the same way. An
# `evaluator_type` absent from this dict is always a clear validation
# error at the API layer (see api/evaluation.py) - never a silent
# fallback to classification.
EVALUATOR_REGISTRY: dict[str, Evaluator] = {
    'classification': ClassificationEvaluator(),
}
