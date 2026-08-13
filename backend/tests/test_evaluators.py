"""Phase 78-79 (v0.8): the generic evaluator abstraction's shapes
(EvaluatorOutput's own field/defaults contract) plus, from Phase 79
onward, the first real registry entry - ClassificationEvaluator, a thin
wrapper around the completely unchanged evaluate_classification
(metrics.py). Byte-identical-output proof against evaluate_classification
directly lives here; api/evaluation.py's/comparison.py's own dispatch
wiring is covered by test_evaluation_api.py/test_comparison_api.py.
"""
from app.domain.evaluators import EVALUATOR_REGISTRY, ClassificationEvaluator, EvaluatorOutput
from app.domain.matching import MatchedPair, MatchResult
from app.domain.metrics import evaluate_classification
from app.domain.models import GroundTruth, Prediction


def _gt(label: str, ts: float = 0.0) -> GroundTruth:
    return GroundTruth(id=f'g-{ts}-{label}', session_id='s1', timestamp_ms=ts, task='presence', value={'label': label})


def _pred(label: str, ts: float = 0.0) -> Prediction:
    return Prediction(
        id=f'p-{ts}-{label}', session_id='s1', timestamp_ms=ts, source_id='det', sensor_ids=['rgb'],
        task='presence', value={'label': label},
    )


def _match_result(pairs: list[tuple[str, str]]) -> MatchResult:
    matched = [
        MatchedPair(ground_truth=_gt(actual, i), prediction=_pred(predicted, i), delta_ms=0.0)
        for i, (actual, predicted) in enumerate(pairs)
    ]
    return MatchResult(matched=matched, unmatched_ground_truth=[], unmatched_predictions=[])


def test_evaluator_output_round_trips_all_fields():
    output = EvaluatorOutput(
        sample_count=10, matched_samples=8, unmatched_predictions=1, unmatched_ground_truth=2,
        metrics={'precision': 0.9, 'recall': None}, details={'per_class': {'person': {'precision': 0.9}}},
    )
    assert output.sample_count == 10
    assert output.matched_samples == 8
    assert output.unmatched_predictions == 1
    assert output.unmatched_ground_truth == 2
    assert output.metrics == {'precision': 0.9, 'recall': None}
    assert output.details == {'per_class': {'person': {'precision': 0.9}}}


def test_evaluator_output_details_defaults_to_none():
    output = EvaluatorOutput(
        sample_count=0, matched_samples=0, unmatched_predictions=0, unmatched_ground_truth=0, metrics={},
    )
    assert output.details is None


def test_evaluator_output_metric_none_is_distinct_from_zero():
    # Same MetricValue rule as everywhere else in this codebase - a metric
    # that could not be calculated is None, never a fabricated 0.0.
    output = EvaluatorOutput(
        sample_count=1, matched_samples=0, unmatched_predictions=0, unmatched_ground_truth=1,
        metrics={'precision': None, 'coverage': 0.0},
    )
    assert output.metrics['precision'] is None
    assert output.metrics['coverage'] == 0.0
    assert output.metrics['coverage'] is not None


# --- registry (Phase 79-83) ----------------------------------------------

def test_registry_has_all_three_v0_8_evaluators():
    assert set(EVALUATOR_REGISTRY) == {'classification', 'object_detection', 'regression'}
    assert isinstance(EVALUATOR_REGISTRY['classification'], ClassificationEvaluator)


def test_classification_evaluator_declares_its_identity():
    evaluator = EVALUATOR_REGISTRY['classification']
    assert evaluator.evaluator_type == 'classification'
    assert evaluator.format_version == '1.0'


# --- ClassificationEvaluator wraps evaluate_classification unchanged ----

def test_classification_evaluator_matches_evaluate_classification_byte_for_byte():
    match_result = _match_result([
        ('present', 'present'), ('absent', 'absent'), ('present', 'absent'), ('absent', 'absent'),
    ])
    direct = evaluate_classification(match_result)
    output = ClassificationEvaluator().evaluate(match_result, {})

    assert output.sample_count == direct.sample_count
    assert output.matched_samples == direct.matched_samples
    assert output.unmatched_predictions == direct.unmatched_predictions
    assert output.unmatched_ground_truth == direct.unmatched_ground_truth
    assert output.metrics == {
        'accuracy': direct.accuracy,
        'precision_macro': direct.precision_macro,
        'recall_macro': direct.recall_macro,
        'f1_macro': direct.f1_macro,
        'precision_micro': direct.precision_micro,
        'recall_micro': direct.recall_micro,
        'f1_micro': direct.f1_micro,
    }
    assert output.details == {
        'confusion_matrix': {'labels': direct.confusion_matrix.labels, 'counts': direct.confusion_matrix.counts},
    }


def test_classification_evaluator_parameters_argument_is_ignored_not_rejected():
    # v0.8's classification evaluator has no configurable parameters -
    # accepting (and ignoring) an empty or arbitrary dict is protocol
    # conformance, not a promise any of it does something.
    match_result = _match_result([('present', 'present')])
    output = ClassificationEvaluator().evaluate(match_result, {'unused_key': 123})
    assert output.metrics['accuracy'] == 1.0


def test_classification_evaluator_na_metric_is_none_not_zero():
    match_result = _match_result([])  # empty match set: matched_samples == 0
    output = ClassificationEvaluator().evaluate(match_result, {})
    assert output.metrics['accuracy'] is None
    assert output.matched_samples == 0
