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
from app.domain.models import MetricValue
from app.domain.regression import RegressionEvaluator
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, MetricDescriptor, PluginDescriptor, PluginType

__all__ = [
    'Evaluator', 'EvaluatorOutput', 'ClassificationEvaluator', 'EVALUATOR_REGISTRY',
    'register_evaluator', 'DuplicateEvaluatorTypeError',
]


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

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='multisens.builtin.evaluator.classification', name='Classification Evaluator',
            version='1.0.0', plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'evaluator_type': self.evaluator_type}, author='MultiSens', license='Apache-2.0',
            description='Single-label multi-class classification metrics (v0.2).',
        )

    def metric_descriptors(self) -> list[MetricDescriptor]:
        return [
            MetricDescriptor(id='accuracy', higher_is_better=True),
            MetricDescriptor(id='precision_macro', higher_is_better=True),
            MetricDescriptor(id='recall_macro', higher_is_better=True),
            MetricDescriptor(id='f1_macro', higher_is_better=True),
            MetricDescriptor(id='precision_micro', higher_is_better=True),
            MetricDescriptor(id='recall_micro', higher_is_better=True),
            MetricDescriptor(id='f1_micro', higher_is_better=True),
        ]

    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput:
        cm = evaluate_classification(match_result)
        metrics: dict[str, MetricValue] = {
            'accuracy': cm.accuracy,
            'precision_macro': cm.precision_macro,
            'recall_macro': cm.recall_macro,
            'f1_macro': cm.f1_macro,
            'precision_micro': cm.precision_micro,
            'recall_micro': cm.recall_micro,
            'f1_micro': cm.f1_micro,
        }
        # Per-class breakdown (v0.9.2), e.g. "recall:happiness" - a
        # `:` separator that can never collide with the fixed keys above,
        # since none of them contain one. Lets a Requirement target one
        # specific class ("recall:happiness >= 0.6") instead of only the
        # aggregate across every class in the task.
        for label, value in cm.precision_per_class.items():
            metrics[f'precision:{label}'] = value
        for label, value in cm.recall_per_class.items():
            metrics[f'recall:{label}'] = value
        for label, value in cm.f1_per_class.items():
            metrics[f'f1:{label}'] = value
        return EvaluatorOutput(
            sample_count=cm.sample_count,
            matched_samples=cm.matched_samples,
            unmatched_predictions=cm.unmatched_predictions,
            unmatched_ground_truth=cm.unmatched_ground_truth,
            metrics=metrics,
            details={'confusion_matrix': {'labels': cm.confusion_matrix.labels, 'counts': cm.confusion_matrix.counts}},
        )


# Starts with exactly the three built-in evaluators - externally
# discovered EvaluatorPlugins are added at startup by
# app/plugins/registry.py's own discovery pass (v0.9, Phase 98), never by
# importing this module differently. An `evaluator_type` absent from
# this dict is always a clear validation error at the API layer (see
# api/evaluation.py) - never a silent fallback to classification.
EVALUATOR_REGISTRY: dict[str, Evaluator] = {
    'classification': ClassificationEvaluator(),
    'object_detection': DetectionEvaluator(),
    'regression': RegressionEvaluator(),
}


class DuplicateEvaluatorTypeError(Exception):
    """Raised by `register_evaluator` when an incoming plugin's own
    `evaluator_type` is already registered - two plugins must never
    silently share one evaluator_type key, the same "never silently
    override" discipline `PluginRegistry`'s own duplicate `plugin_id`
    handling already has (v0.9, Phase 94). A plugin_id collision and an
    evaluator_type collision are checked independently - plugin_id is
    the global registry's own identity namespace; evaluator_type is
    this dict's own, separate namespace, and either can collide without
    the other."""


def register_evaluator(evaluator: Evaluator) -> None:
    """Adds an external `EvaluatorPlugin` to `EVALUATOR_REGISTRY` - never
    silently overrides an existing key, built-in or previously-registered
    external. The three built-in evaluators are never re-registered
    through this function; they're already the dict's own initial
    contents."""
    if evaluator.evaluator_type in EVALUATOR_REGISTRY:
        raise DuplicateEvaluatorTypeError(
            f"evaluator_type '{evaluator.evaluator_type}' is already registered - "
            f"cannot register plugin '{evaluator.descriptor().plugin_id}'"
        )
    EVALUATOR_REGISTRY[evaluator.evaluator_type] = evaluator
