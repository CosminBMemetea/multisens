"""Phase 83 (v0.8): scalar regression evaluation - MAE/RMSE/bias/median-
absolute-error, unit-aware. No R², no vector regression, no relative/
percentage error in v0.8 (all explicitly deferred - see regression.py's
own module docstring), grep-verified below the same way detection.py's
own "no AP/mAP" test works.
"""
import dataclasses
import math

import pytest

from app.domain.evaluators import EVALUATOR_REGISTRY
from app.domain.matching import match_by_timestamp
from app.domain.models import GroundTruth, Prediction
from app.domain.regression import (
    RegressionEvaluator,
    RegressionMetrics,
    RegressionSample,
    build_regression_samples,
    compute_regression_metrics,
    parse_regression_value,
)


def _gt(id_, ts, value, unit='m') -> GroundTruth:
    return GroundTruth(id=id_, session_id='s1', timestamp_ms=ts, task='distance_estimation',
                        value={'value': value, 'unit': unit})


def _pred(id_, ts, value, unit='m') -> Prediction:
    return Prediction(id=id_, session_id='s1', timestamp_ms=ts, source_id='sensor', sensor_ids=['rgb'],
                       task='distance_estimation', value={'value': value, 'unit': unit})


def _sample(gt, pred, unit='m') -> RegressionSample:
    return RegressionSample(ground_truth_value=gt, prediction_value=pred, unit=unit)


# --- parse_regression_value -------------------------------------------------

def test_parse_regression_value_valid():
    value, unit = parse_regression_value({'value': 2.42, 'unit': 'm'}, 'ground_truth')
    assert value == 2.42 and unit == 'm'


def test_parse_regression_value_missing_value_rejected():
    with pytest.raises(ValueError, match='value'):
        parse_regression_value({'unit': 'm'}, 'ground_truth')


def test_parse_regression_value_missing_unit_rejected():
    with pytest.raises(ValueError, match='unit'):
        parse_regression_value({'value': 1.0}, 'ground_truth')


def test_parse_regression_value_non_numeric_rejected():
    with pytest.raises(ValueError, match='value'):
        parse_regression_value({'value': 'far', 'unit': 'm'}, 'ground_truth')


def test_parse_regression_value_empty_unit_rejected():
    with pytest.raises(ValueError, match='unit'):
        parse_regression_value({'value': 1.0, 'unit': '  '}, 'ground_truth')


def test_parse_regression_value_vector_rejected_with_clear_message():
    with pytest.raises(ValueError, match='vector'):
        parse_regression_value({'value': [1.0, 2.0, 3.0], 'unit': 'm'}, 'ground_truth')


def test_parse_regression_value_negative_is_valid():
    value, unit = parse_regression_value({'value': -5.0, 'unit': 'degC'}, 'ground_truth')
    assert value == -5.0


def test_parse_regression_value_zero_is_valid_not_missing():
    value, _ = parse_regression_value({'value': 0.0, 'unit': 'm'}, 'ground_truth')
    assert value == 0.0


# --- build_regression_samples -----------------------------------------------

def test_build_regression_samples_valid():
    match_result = match_by_timestamp([_gt('g1', 0.0, 2.0)], [_pred('p1', 1.0, 2.1)], tolerance_ms=50.0)
    samples = build_regression_samples(match_result)
    assert len(samples) == 1
    assert samples[0].ground_truth_value == 2.0
    assert samples[0].prediction_value == 2.1


def test_build_regression_samples_unit_mismatch_rejected():
    match_result = match_by_timestamp(
        [_gt('g1', 0.0, 2.0, unit='m')], [_pred('p1', 1.0, 200.0, unit='cm')], tolerance_ms=50.0,
    )
    with pytest.raises(ValueError, match='unit mismatch'):
        build_regression_samples(match_result)


def test_build_regression_samples_empty_match_result_is_empty_list():
    match_result = match_by_timestamp([], [], tolerance_ms=50.0)
    assert build_regression_samples(match_result) == []


# --- compute_regression_metrics ---------------------------------------------

def test_hand_computed_mae_rmse_bias_median():
    # GT: 1.0, 2.0, 3.0 ; predicted: 1.5, 1.5, 3.5
    # errors (pred - gt): 0.5, -0.5, 0.5
    samples = [_sample(1.0, 1.5), _sample(2.0, 1.5), _sample(3.0, 3.5)]
    metrics = compute_regression_metrics(samples)
    assert metrics.sample_count == 3
    assert metrics.mae == pytest.approx((0.5 + 0.5 + 0.5) / 3)
    assert metrics.rmse == pytest.approx(math.sqrt((0.25 + 0.25 + 0.25) / 3))
    assert metrics.bias == pytest.approx((0.5 - 0.5 + 0.5) / 3)  # mean signed error
    assert metrics.median_absolute_error == pytest.approx(0.5)
    assert metrics.unit == 'm'


def test_zero_error_all_metrics_zero():
    samples = [_sample(1.0, 1.0), _sample(2.0, 2.0), _sample(-3.0, -3.0)]
    metrics = compute_regression_metrics(samples)
    assert metrics.mae == 0.0
    assert metrics.rmse == 0.0
    assert metrics.bias == 0.0
    assert metrics.median_absolute_error == 0.0


def test_negative_values_handled_correctly():
    # Temperature-style negative GT/prediction values.
    samples = [_sample(-10.0, -8.0, unit='degC'), _sample(-5.0, -6.0, unit='degC')]
    metrics = compute_regression_metrics(samples)
    # errors: +2.0, -1.0
    assert metrics.mae == pytest.approx(1.5)
    assert metrics.bias == pytest.approx(0.5)
    assert metrics.unit == 'degC'


def test_empty_samples_all_na_not_zero():
    metrics = compute_regression_metrics([])
    assert metrics.sample_count == 0
    assert metrics.mae is None
    assert metrics.rmse is None
    assert metrics.bias is None
    assert metrics.median_absolute_error is None
    assert metrics.unit is None


def test_one_sample():
    metrics = compute_regression_metrics([_sample(2.0, 2.5)])
    assert metrics.sample_count == 1
    assert metrics.mae == pytest.approx(0.5)
    assert metrics.rmse == pytest.approx(0.5)
    assert metrics.bias == pytest.approx(0.5)
    assert metrics.median_absolute_error == pytest.approx(0.5)


def test_mixed_units_across_samples_rejected():
    samples = [_sample(1.0, 1.1, unit='m'), _sample(2.0, 2.1, unit='cm')]
    with pytest.raises(ValueError, match='mixed units'):
        compute_regression_metrics(samples)


# --- explicitly deferred: R², relative/percentage error, vector -----------

def test_no_relative_or_percentage_error_field_exists():
    field_names = {f.name.lower() for f in dataclasses.fields(RegressionMetrics)}
    forbidden = {'relative_error', 'percentage_error', 'absolute_percentage_error', 'r2', 'r_squared'}
    assert not (field_names & forbidden)


# --- RegressionEvaluator: registration + dispatch ---------------------------

def test_regression_evaluator_registered():
    assert isinstance(EVALUATOR_REGISTRY['regression'], RegressionEvaluator)
    assert EVALUATOR_REGISTRY['regression'].evaluator_type == 'regression'
    assert EVALUATOR_REGISTRY['regression'].format_version == '1.0'


def test_evaluate_end_to_end_frame_level_counts():
    gts = [_gt('g1', 0.0, 2.0), _gt('g2', 1000.0, 3.0)]
    preds = [_pred('p1', 1.0, 2.1), _pred('p2', 1001.0, 2.9)]
    match_result = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    output = RegressionEvaluator().evaluate(match_result, {})

    assert output.sample_count == 2
    assert output.matched_samples == 2
    assert output.unmatched_predictions == 0
    assert output.unmatched_ground_truth == 0
    assert output.metrics['mae'] == pytest.approx((0.1 + 0.1) / 2)
    assert output.details == {'unit': 'm'}


def test_evaluate_unmatched_frames_reported_not_hidden():
    gts = [_gt('g1', 0.0, 2.0)]
    preds = [_pred('p1', 5000.0, 2.1)]  # far outside tolerance
    match_result = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    output = RegressionEvaluator().evaluate(match_result, {})
    assert output.matched_samples == 0
    assert output.unmatched_ground_truth == 1
    assert output.unmatched_predictions == 1
    assert output.metrics['mae'] is None  # no matched samples at all


def test_evaluate_unit_mismatch_raises_value_error():
    match_result = match_by_timestamp(
        [_gt('g1', 0.0, 2.0, unit='m')], [_pred('p1', 1.0, 200.0, unit='cm')], tolerance_ms=50.0,
    )
    with pytest.raises(ValueError, match='unit mismatch'):
        RegressionEvaluator().evaluate(match_result, {})


def test_evaluate_vector_value_rejected():
    gt = GroundTruth(id='g1', session_id='s1', timestamp_ms=0.0, task='position',
                      value={'value': [1.0, 2.0], 'unit': 'm'})
    pred = Prediction(id='p1', session_id='s1', timestamp_ms=1.0, source_id='sensor', sensor_ids=['rgb'],
                       task='position', value={'value': [1.1, 2.1], 'unit': 'm'})
    match_result = match_by_timestamp([gt], [pred], tolerance_ms=50.0)
    with pytest.raises(ValueError, match='vector'):
        RegressionEvaluator().evaluate(match_result, {})


# --- independent verification (zero imports from the production evaluator) -

def test_independent_verification_of_regression_evaluator_output():
    gt_values = [1.0, 2.0, 3.0, 4.0]
    pred_values = [1.2, 1.8, 3.3, 3.7]  # errors: +0.2, -0.2, +0.3, -0.3

    gts = [_gt(f'g{i}', i * 1000.0, v) for i, v in enumerate(gt_values)]
    preds = [_pred(f'p{i}', i * 1000.0 + 1.0, v) for i, v in enumerate(pred_values)]

    # --- independent recomputation, plain Python only ---
    errors = [p - g for g, p in zip(gt_values, pred_values)]
    expected_mae = sum(abs(e) for e in errors) / len(errors)
    expected_rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
    expected_bias = sum(errors) / len(errors)
    sorted_abs = sorted(abs(e) for e in errors)
    n = len(sorted_abs)
    expected_median = (sorted_abs[n // 2 - 1] + sorted_abs[n // 2]) / 2 if n % 2 == 0 else sorted_abs[n // 2]

    # --- production evaluator ---
    match_result = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    output = RegressionEvaluator().evaluate(match_result, {})

    assert output.metrics['mae'] == pytest.approx(expected_mae)
    assert output.metrics['rmse'] == pytest.approx(expected_rmse)
    assert output.metrics['bias'] == pytest.approx(expected_bias)
    assert output.metrics['median_absolute_error'] == pytest.approx(expected_median)
