"""Phase 21: comparison engine - pure functions, no persistence/transport."""
from datetime import datetime, timezone

import pytest

from app.domain.comparison import (
    assess_validity,
    build_comparison_side,
    classify_relationship,
    comparison_metrics_from_classification,
    comparison_metrics_from_evaluation_result,
    compare_configurations,
    compute_metric_delta,
    filter_matched_by_ground_truth_ids,
    intersect_matched_ground_truth_ids,
)
from app.domain.matching import MatchedPair, MatchResult, match_by_timestamp
from app.domain.metrics import evaluate_classification
from app.domain.models import ComparisonMetrics, EvaluationResult, GroundTruth, Prediction


def _now():
    return datetime.now(timezone.utc)


def _gt(id_: str, ts: float, label: str) -> GroundTruth:
    return GroundTruth(id=id_, session_id='s1', timestamp_ms=ts, task='presence', value={'label': label})


def _pred(id_: str, ts: float, label: str, sensor_ids: list[str]) -> Prediction:
    return Prediction(
        id=id_, session_id='s1', timestamp_ms=ts, source_id='m', sensor_ids=sensor_ids,
        task='presence', value={'label': label},
    )


def _eval_result(configuration_id: str, sample_count: int, matched_samples: int, accuracy) -> EvaluationResult:
    return EvaluationResult(
        id=f'e-{configuration_id}', session_id='s1', configuration_id=configuration_id, task='presence',
        tolerance_ms=100.0, sample_count=sample_count, matched_samples=matched_samples,
        unmatched_predictions=0, unmatched_ground_truth=sample_count - matched_samples,
        metrics={'accuracy': accuracy}, computed_at=_now(),
    )


# --- classify_relationship ----------------------------------------------

def test_classify_relationship_direct_addition():
    added, removed, rel = classify_relationship(['rgb'], ['rgb', 'thermal'])
    assert added == ['thermal']
    assert removed == []
    assert rel == 'direct_addition'


def test_classify_relationship_direct_removal():
    added, removed, rel = classify_relationship(['rgb', 'depth', 'thermal'], ['rgb', 'thermal'])
    assert added == []
    assert removed == ['depth']
    assert rel == 'direct_removal'


def test_classify_relationship_general_swap():
    added, removed, rel = classify_relationship(['rgb', 'depth'], ['rgb', 'thermal'])
    assert added == ['thermal']
    assert removed == ['depth']
    assert rel == 'general'


def test_classify_relationship_general_multi_sensor_addition():
    added, removed, rel = classify_relationship(['rgb'], ['rgb', 'depth', 'thermal'])
    assert set(added) == {'depth', 'thermal'}
    assert rel == 'general'


def test_classify_relationship_works_with_arbitrary_sensor_names():
    # Not rgb/depth/thermal - proves nothing here assumes the demo's own
    # sensor vocabulary, and proves configuration_id strings are never
    # parsed (these two configuration ids would be ambiguous to reverse
    # -split on '-' since the sensor names themselves contain hyphens).
    added, removed, rel = classify_relationship(['camera-front'], ['camera-front', 'ir-driver-facing'])
    assert added == ['ir-driver-facing']
    assert rel == 'direct_addition'


def test_classify_relationship_identical_sets_is_general_with_no_changes():
    added, removed, rel = classify_relationship(['rgb', 'depth'], ['rgb', 'depth'])
    assert added == []
    assert removed == []
    assert rel == 'general'


# --- compute_metric_delta -------------------------------------------------

def test_metric_delta_absolute_and_relative():
    d = compute_metric_delta(baseline=0.80, candidate=0.94)
    assert d.absolute == pytest.approx(0.14)
    assert d.relative == pytest.approx(0.175)


def test_metric_delta_baseline_zero_relative_is_na():
    d = compute_metric_delta(baseline=0.0, candidate=0.5)
    assert d.absolute == pytest.approx(0.5)
    assert d.relative is None


def test_metric_delta_missing_baseline_is_na():
    d = compute_metric_delta(baseline=None, candidate=0.9)
    assert d.absolute is None
    assert d.relative is None


def test_metric_delta_missing_candidate_is_na():
    d = compute_metric_delta(baseline=0.9, candidate=None)
    assert d.absolute is None
    assert d.relative is None


def test_metric_delta_negative_baseline_relative_uses_absolute_value():
    # abs(baseline) in the denominator - a metric shouldn't realistically
    # go negative, but the math must not silently flip sign if it did.
    d = compute_metric_delta(baseline=-0.5, candidate=0.5)
    assert d.relative == pytest.approx(1.0 / 0.5)


# --- ComparisonMetrics / coverage -----------------------------------------

def test_comparison_metrics_from_evaluation_result_computes_coverage():
    result = _eval_result('cfg-rgb', sample_count=5, matched_samples=4, accuracy=0.75)
    cm = comparison_metrics_from_evaluation_result(result)
    assert cm.coverage == pytest.approx(0.8)


def test_comparison_metrics_coverage_na_when_sample_count_zero():
    result = _eval_result('cfg-rgb', sample_count=0, matched_samples=0, accuracy=None)
    cm = comparison_metrics_from_evaluation_result(result)
    assert cm.coverage is None


def test_build_comparison_side_coverage_delta_pp():
    baseline = ComparisonMetrics(
        sample_count=5, matched_samples=4, unmatched_predictions=0, unmatched_ground_truth=1,
        coverage=0.8, metrics={'accuracy': 0.75},
    )
    candidate = ComparisonMetrics(
        sample_count=5, matched_samples=5, unmatched_predictions=0, unmatched_ground_truth=0,
        coverage=1.0, metrics={'accuracy': 1.0},
    )
    side = build_comparison_side(baseline, candidate)
    assert side.coverage_delta_pp == pytest.approx(20.0)
    assert side.matched_sample_delta == 1
    assert side.metric_deltas['accuracy'].absolute == pytest.approx(0.25)


def test_build_comparison_side_coverage_delta_na_when_either_side_na():
    baseline = ComparisonMetrics(
        sample_count=0, matched_samples=0, unmatched_predictions=0, unmatched_ground_truth=0,
        coverage=None, metrics={'accuracy': None},
    )
    candidate = ComparisonMetrics(
        sample_count=5, matched_samples=5, unmatched_predictions=0, unmatched_ground_truth=0,
        coverage=1.0, metrics={'accuracy': 1.0},
    )
    side = build_comparison_side(baseline, candidate)
    assert side.coverage_delta_pp is None


# --- common-set intersection ------------------------------------------------

def test_intersect_matched_ground_truth_ids():
    g0, g1, g2 = _gt('g0', 0, 'present'), _gt('g1', 100, 'absent'), _gt('g2', 200, 'present')
    baseline_match = MatchResult(
        matched=[MatchedPair(g0, _pred('p0', 1, 'present', ['rgb']), 1.0),
                 MatchedPair(g1, _pred('p1', 101, 'present', ['rgb']), 1.0)],
        unmatched_ground_truth=[], unmatched_predictions=[],
    )
    candidate_match = MatchResult(
        matched=[MatchedPair(g0, _pred('q0', 2, 'present', ['rgb', 'thermal']), 2.0),
                 MatchedPair(g2, _pred('q2', 202, 'present', ['rgb', 'thermal']), 2.0)],
        unmatched_ground_truth=[], unmatched_predictions=[],
    )
    assert intersect_matched_ground_truth_ids(baseline_match, candidate_match) == {'g0'}


def test_filter_matched_by_ground_truth_ids_produces_zero_unmatched():
    g0, g1 = _gt('g0', 0, 'present'), _gt('g1', 100, 'absent')
    match = MatchResult(
        matched=[MatchedPair(g0, _pred('p0', 1, 'present', ['rgb']), 1.0),
                 MatchedPair(g1, _pred('p1', 101, 'absent', ['rgb']), 1.0)],
        unmatched_ground_truth=[], unmatched_predictions=[],
    )
    filtered = filter_matched_by_ground_truth_ids(match, {'g0'})
    assert len(filtered.matched) == 1
    assert filtered.matched[0].ground_truth.id == 'g0'
    assert filtered.unmatched_ground_truth == []
    assert filtered.unmatched_predictions == []


def test_common_set_metrics_multiclass():
    # 3 classes, common-set restricted to 2 of 3 matched ids - proves the
    # existing (unmodified) evaluate_classification is what computes
    # common-set metrics, not a parallel implementation.
    gts = [_gt('g0', 0, 'a'), _gt('g1', 100, 'b'), _gt('g2', 200, 'c')]
    preds = [_pred('p0', 1, 'a', ['rgb']), _pred('p1', 101, 'b', ['rgb']), _pred('p2', 201, 'a', ['rgb'])]
    full_match = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    restricted = filter_matched_by_ground_truth_ids(full_match, {'g0', 'g1'})
    cm = evaluate_classification(restricted)
    assert cm.sample_count == 2
    assert cm.matched_samples == 2
    assert cm.accuracy == 1.0  # both g0->a and g1->b were correct


# --- validity --------------------------------------------------------------

def test_validity_clean_case_is_valid():
    side = build_comparison_side(
        ComparisonMetrics(sample_count=100, matched_samples=100, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=100, matched_samples=98, unmatched_predictions=0,
                           unmatched_ground_truth=2, coverage=0.98, metrics={'accuracy': 0.93}),
    )
    common = build_comparison_side(
        ComparisonMetrics(sample_count=90, matched_samples=90, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=90, matched_samples=90, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.93}),
        common_sample_count=90,
    )
    validity = assess_validity(side, common)
    assert validity.status == 'valid'
    assert validity.reasons == []


def test_validity_zero_common_samples_is_invalid():
    side = build_comparison_side(
        ComparisonMetrics(sample_count=10, matched_samples=10, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=10, matched_samples=10, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
    )
    common = build_comparison_side(
        ComparisonMetrics(sample_count=0, matched_samples=0, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=None, metrics={'accuracy': None}),
        ComparisonMetrics(sample_count=0, matched_samples=0, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=None, metrics={'accuracy': None}),
        common_sample_count=0,
    )
    validity = assess_validity(side, common)
    assert validity.status == 'invalid'
    assert 'no common samples' in validity.reasons[0]


def test_validity_low_common_sample_count_is_warning():
    side = build_comparison_side(
        ComparisonMetrics(sample_count=10, matched_samples=10, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=10, matched_samples=10, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
    )
    common = build_comparison_side(
        ComparisonMetrics(sample_count=4, matched_samples=4, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=4, matched_samples=4, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        common_sample_count=4,
    )
    validity = assess_validity(side, common, min_common_sample_count=20)
    assert validity.status == 'valid_with_warnings'
    assert any('below the minimum' in r for r in validity.reasons)


def test_validity_coverage_difference_is_warning():
    side = build_comparison_side(
        ComparisonMetrics(sample_count=100, matched_samples=80, unmatched_predictions=0,
                           unmatched_ground_truth=20, coverage=0.8, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=100, matched_samples=100, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
    )
    common = build_comparison_side(
        ComparisonMetrics(sample_count=80, matched_samples=80, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        ComparisonMetrics(sample_count=80, matched_samples=80, unmatched_predictions=0,
                           unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9}),
        common_sample_count=80,
    )
    validity = assess_validity(side, common, coverage_warning_threshold_pp=5.0)
    assert validity.status == 'valid_with_warnings'
    assert any('coverage differs' in r for r in validity.reasons)


# --- compare_configurations (end to end, hand-verified) ---------------------

def test_compare_configurations_end_to_end_hand_verified():
    ground_truth = [
        _gt('g0', 0, 'present'), _gt('g1', 100, 'absent'), _gt('g2', 200, 'present'),
        _gt('g3', 300, 'present'), _gt('g4', 400, 'absent'),
    ]
    # baseline (cfg-rgb): misses g3 entirely, gets g1 wrong -> 3/4 correct
    baseline_predictions = [
        _pred('p0', 1, 'present', ['rgb']),
        _pred('p1', 101, 'present', ['rgb']),  # wrong: actual absent
        _pred('p2', 201, 'present', ['rgb']),
        _pred('p4', 401, 'absent', ['rgb']),
    ]
    # candidate (cfg-rgb-thermal): matches all 5, all correct
    candidate_predictions = [
        _pred('q0', 2, 'present', ['rgb', 'thermal']),
        _pred('q1', 102, 'absent', ['rgb', 'thermal']),
        _pred('q2', 202, 'present', ['rgb', 'thermal']),
        _pred('q3', 302, 'present', ['rgb', 'thermal']),
        _pred('q4', 402, 'absent', ['rgb', 'thermal']),
    ]
    baseline_result = _eval_result('cfg-rgb', sample_count=5, matched_samples=4, accuracy=0.75)
    candidate_result = _eval_result('cfg-rgb-thermal', sample_count=5, matched_samples=5, accuracy=1.0)

    comparison = compare_configurations(
        session_id='s1', task='presence',
        baseline_configuration_id='cfg-rgb', candidate_configuration_id='cfg-rgb-thermal',
        baseline_source_id='rgb_model', candidate_source_id='rgb_thermal_model',
        baseline_sensor_ids=['rgb'], candidate_sensor_ids=['rgb', 'thermal'],
        ground_truth=ground_truth,
        baseline_predictions=baseline_predictions, candidate_predictions=candidate_predictions,
        baseline_evaluation_result=baseline_result, candidate_evaluation_result=candidate_result,
        tolerance_ms=50.0,
    )

    assert comparison.added_sensors == ['thermal']
    assert comparison.removed_sensors == []
    assert comparison.relationship == 'direct_addition'
    assert comparison.baseline_source_id == 'rgb_model'
    assert comparison.candidate_source_id == 'rgb_thermal_model'

    # reported: straight from the persisted EvaluationResults
    assert comparison.reported.baseline.coverage == pytest.approx(0.8)
    assert comparison.reported.candidate.coverage == pytest.approx(1.0)
    assert comparison.reported.coverage_delta_pp == pytest.approx(20.0)
    assert comparison.reported.matched_sample_delta == 1
    assert comparison.reported.metric_deltas['accuracy'].absolute == pytest.approx(0.25)
    assert comparison.reported.metric_deltas['accuracy'].relative == pytest.approx(0.25 / 0.75)

    # common-set: intersection is baseline's 4 matched ids (g0,g1,g2,g4) -
    # candidate matched all 5, so its filtered view drops g3.
    assert comparison.common_set.common_sample_count == 4
    assert comparison.common_set.baseline.matched_samples == 4
    assert comparison.common_set.baseline.metrics['accuracy'] == pytest.approx(0.75)  # 3/4, unchanged
    assert comparison.common_set.candidate.matched_samples == 4
    assert comparison.common_set.candidate.metrics['accuracy'] == pytest.approx(1.0)  # 4/4, all correct

    # validity: common_sample_count=4 < default min (20), and reported
    # coverage differs by 20pp > default threshold (5pp) - both fire.
    assert comparison.validity.status == 'valid_with_warnings'
    assert len(comparison.validity.reasons) == 2


def test_compare_configurations_disjoint_matches_is_invalid():
    ground_truth = [_gt('g0', 0, 'present'), _gt('g1', 1000, 'absent')]
    baseline_predictions = [_pred('p0', 1, 'present', ['rgb'])]         # only matches g0
    candidate_predictions = [_pred('q1', 1001, 'absent', ['depth'])]     # only matches g1
    baseline_result = _eval_result('cfg-rgb', sample_count=2, matched_samples=1, accuracy=1.0)
    candidate_result = _eval_result('cfg-depth', sample_count=2, matched_samples=1, accuracy=1.0)

    comparison = compare_configurations(
        session_id='s1', task='presence',
        baseline_configuration_id='cfg-rgb', candidate_configuration_id='cfg-depth',
        baseline_source_id='rgb_model', candidate_source_id='depth_model',
        baseline_sensor_ids=['rgb'], candidate_sensor_ids=['depth'],
        ground_truth=ground_truth,
        baseline_predictions=baseline_predictions, candidate_predictions=candidate_predictions,
        baseline_evaluation_result=baseline_result, candidate_evaluation_result=candidate_result,
        tolerance_ms=50.0,
    )
    assert comparison.relationship == 'general'  # rgb -> depth is a swap, not a direct edge
    assert comparison.common_set.common_sample_count == 0
    assert comparison.validity.status == 'invalid'
