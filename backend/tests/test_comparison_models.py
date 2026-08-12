"""Phase 20: comparison domain models. Construction/validation only - the
algorithms that populate these (relationship classification, common-set
intersection, delta math) are Phase 21's job (app/domain/comparison.py).
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.models import (
    ComparisonMetrics,
    ComparisonSide,
    ComparisonValidity,
    MetricDelta,
    PairwiseComparison,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _metrics(**overrides) -> ComparisonMetrics:
    base = dict(
        sample_count=10, matched_samples=10, unmatched_predictions=0,
        unmatched_ground_truth=0, coverage=1.0, metrics={'accuracy': 0.9},
    )
    base.update(overrides)
    return ComparisonMetrics(**base)


def _side(**overrides) -> ComparisonSide:
    base = dict(
        baseline=_metrics(), candidate=_metrics(),
        metric_deltas={'accuracy': MetricDelta(baseline=0.9, candidate=0.9, absolute=0.0, relative=0.0)},
        coverage_delta_pp=0.0, matched_sample_delta=0,
    )
    base.update(overrides)
    return ComparisonSide(**base)


# --- ComparisonValidity -------------------------------------------------

def test_validity_valid_allows_empty_reasons():
    v = ComparisonValidity(status='valid')
    assert v.reasons == []


def test_validity_warning_requires_a_reason():
    with pytest.raises(ValidationError):
        ComparisonValidity(status='valid_with_warnings')


def test_validity_invalid_requires_a_reason():
    with pytest.raises(ValidationError):
        ComparisonValidity(status='invalid', reasons=[])


def test_validity_warning_with_reason_constructs():
    v = ComparisonValidity(status='valid_with_warnings', reasons=['coverage differs by 8.2 pp'])
    assert v.status == 'valid_with_warnings'
    assert v.reasons == ['coverage differs by 8.2 pp']


# --- MetricDelta ----------------------------------------------------------

def test_metric_delta_allows_all_none_for_na_case():
    d = MetricDelta(baseline=None, candidate=0.9, absolute=None, relative=None)
    assert d.baseline is None
    assert d.absolute is None
    assert d.relative is None


def test_metric_delta_holds_computed_values():
    d = MetricDelta(baseline=0.80, candidate=0.94, absolute=0.14, relative=0.175)
    assert d.absolute == pytest.approx(0.14)
    assert d.relative == pytest.approx(0.175)


# --- ComparisonMetrics ------------------------------------------------------

def test_comparison_metrics_coverage_can_be_none():
    m = _metrics(sample_count=0, matched_samples=0, coverage=None, metrics={'accuracy': None})
    assert m.coverage is None
    assert m.metrics['accuracy'] is None


# --- ComparisonSide ----------------------------------------------------------

def test_comparison_side_common_sample_count_defaults_to_none():
    side = _side()
    assert side.common_sample_count is None


def test_comparison_side_common_set_variant_carries_sample_count():
    side = _side(common_sample_count=84)
    assert side.common_sample_count == 84


# --- PairwiseComparison -----------------------------------------------------

def test_pairwise_comparison_full_construction():
    comparison = PairwiseComparison(
        session_id='s1', task='presence',
        baseline_configuration_id='cfg-rgb', candidate_configuration_id='cfg-rgb-thermal',
        baseline_source_id='rgb_model', candidate_source_id='rgb_thermal_fusion_model',
        tolerance_ms=100.0,
        added_sensors=['thermal'], removed_sensors=[],
        relationship='direct_addition',
        reported=_side(), common_set=_side(common_sample_count=84),
        validity=ComparisonValidity(status='valid'),
        computed_at=_now(),
    )
    assert comparison.relationship == 'direct_addition'
    assert comparison.common_set.common_sample_count == 84
    assert comparison.reported.common_sample_count is None
    assert comparison.baseline_source_id == 'rgb_model'
    assert comparison.candidate_source_id == 'rgb_thermal_fusion_model'


def test_pairwise_comparison_rejects_unknown_relationship():
    with pytest.raises(ValidationError):
        PairwiseComparison(
            session_id='s1', task='presence',
            baseline_configuration_id='cfg-rgb', candidate_configuration_id='cfg-depth',
            baseline_source_id='rgb_model', candidate_source_id='depth_model',
            tolerance_ms=100.0, added_sensors=['depth'], removed_sensors=['rgb'],
            relationship='swap',  # not a real value
            reported=_side(), common_set=_side(),
            validity=ComparisonValidity(status='valid'),
            computed_at=_now(),
        )


def test_pairwise_comparison_general_relationship_can_have_both_added_and_removed():
    # A swap (e.g. [rgb, depth] -> [rgb, thermal]) has non-empty added AND
    # removed sets simultaneously - the model itself doesn't forbid this,
    # only the not-yet-written Phase 21 classifier decides what counts as
    # 'general' vs 'direct'.
    comparison = PairwiseComparison(
        session_id='s1', task='presence',
        baseline_configuration_id='cfg-depth-rgb', candidate_configuration_id='cfg-rgb-thermal',
        baseline_source_id='depth_rgb_model', candidate_source_id='rgb_thermal_model',
        tolerance_ms=100.0,
        added_sensors=['thermal'], removed_sensors=['depth'],
        relationship='general',
        reported=_side(), common_set=_side(),
        validity=ComparisonValidity(status='valid'),
        computed_at=_now(),
    )
    assert comparison.added_sensors == ['thermal']
    assert comparison.removed_sensors == ['depth']


def test_pairwise_comparison_requires_both_source_ids():
    # Traceability gap found during the v0.3 product-direction review:
    # a comparison must be able to say exactly which prediction source
    # produced each side's evidence, not just which configuration.
    with pytest.raises(ValidationError):
        PairwiseComparison(
            session_id='s1', task='presence',
            baseline_configuration_id='cfg-rgb', candidate_configuration_id='cfg-depth',
            candidate_source_id='depth_model',  # baseline_source_id omitted
            tolerance_ms=100.0, added_sensors=['depth'], removed_sensors=['rgb'],
            relationship='general',
            reported=_side(), common_set=_side(),
            validity=ComparisonValidity(status='valid'),
            computed_at=_now(),
        )
