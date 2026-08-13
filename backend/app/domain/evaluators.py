"""Generic evaluator abstraction / registry (v0.8, Phase 78-83).

`Evaluator`/`EvaluatorOutput` themselves live in `evaluator_output.py`
(split out in Phase 82, see that module's own docstring for the import-
cycle reasoning: this module has to import every evaluator-specific
algorithm module to populate `EVALUATOR_REGISTRY`, and those modules need
`EvaluatorOutput` to build their own results - both living here would be
circular). Both names are re-exported below, so every existing
`from app.domain.evaluators import EvaluatorOutput`-style import is
unaffected.

`ClassificationEvaluator` (Phase 79) wraps the completely unchanged
`evaluate_classification` (metrics.py) directly here, since it has no
algorithm module of its own beyond that one function.
`DetectionEvaluator` (Phase 80-82) and `RegressionEvaluator` (Phase 83)
each have a real algorithm module of their own (`detection.py`/
`regression.py`) and are imported from there. See the v0.8 architecture
review (issue #79) for the full reasoning behind this whole layer.

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

from typing import Any

from app.domain.detection import DetectionEvaluator
from app.domain.evaluator_output import Evaluator, EvaluatorOutput
from app.domain.matching import MatchResult
from app.domain.metrics import evaluate_classification
from app.domain.regression import RegressionEvaluator

__all__ = ['Evaluator', 'EvaluatorOutput', 'ClassificationEvaluator', 'EVALUATOR_REGISTRY']


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
# An `evaluator_type` absent from this dict is always a clear validation
# error at the API layer (see api/evaluation.py) - never a silent
# fallback to classification.
EVALUATOR_REGISTRY: dict[str, Evaluator] = {
    'classification': ClassificationEvaluator(),
    'object_detection': DetectionEvaluator(),
    'regression': RegressionEvaluator(),
}
