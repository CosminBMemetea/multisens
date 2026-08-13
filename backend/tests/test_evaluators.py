"""Phase 78 (v0.8): the generic evaluator abstraction's shapes only -
EvaluatorOutput's own field/defaults contract and the registry's starting
state. No evaluator implementation exists yet (Phase 79 adds
'classification'; Phase 80-83 add 'object_detection'/'regression') - see
app/domain/evaluators.py's own module docstring for why evaluate_session/
compare_configurations stay untouched until then.
"""
from app.domain.evaluators import EVALUATOR_REGISTRY, EvaluatorOutput


def test_evaluator_registry_starts_empty():
    # Locks in this phase's own scope boundary - an unpopulated registry
    # is not an oversight, it's what "shapes only, no algorithms yet"
    # means. Phase 79 is the first phase allowed to add an entry.
    assert EVALUATOR_REGISTRY == {}


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
