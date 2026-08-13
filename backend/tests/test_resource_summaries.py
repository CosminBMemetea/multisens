"""Phase 67: resource summaries. ResourceMetricSummary's mean/median/p95
are independently verified by hand on a fixed, hand-computed dataset -
no shared code with _percentile's own implementation - so a bug in the
implementation can't also be baked into the expected value.
"""
from datetime import datetime, timezone

import pytest

from app.domain.resources import (
    ResourceObservation,
    compute_configuration_resource_profile,
    compute_resource_metric_summary,
)

PLATFORM_ID = 'macbook-m2-dockerdesktop'


def _observation(**overrides) -> ResourceObservation:
    defaults = dict(
        id='obs-1', session_id='s1', configuration_id='cfg-a', metric='cpu_percent',
        value=31.2, unit='%', quality='measured', source='psutil.cpu_percent',
        platform_id=PLATFORM_ID,
        started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
    )
    return ResourceObservation(**{**defaults, **overrides})


# --- compute_resource_metric_summary: hand-computed independent verification

def test_summary_matches_hand_computed_mean_median_p95_min_max():
    # [10, 20, 30, 40, 50] - every statistic computed by hand, not by
    # calling any shared helper:
    #   mean   = (10+20+30+40+50)/5 = 30
    #   median = 30 (the middle of 5 sorted values)
    #   min/max = 10 / 50
    #   p95 (linear interpolation, numpy's default 'linear' method):
    #     index = 0.95 * (5-1) = 3.8
    #     lower=values[3]=40, upper=values[4]=50
    #     p95 = 40 + (50-40) * 0.8 = 48.0
    observations = [
        _observation(id=f'obs-{i}', value=v)
        for i, v in enumerate([10.0, 20.0, 30.0, 40.0, 50.0])
    ]
    summary = compute_resource_metric_summary(observations)
    assert summary.mean == pytest.approx(30.0)
    assert summary.median == pytest.approx(30.0)
    assert summary.p95 == pytest.approx(48.0)
    assert summary.min == pytest.approx(10.0)
    assert summary.max == pytest.approx(50.0)
    assert summary.sample_count == 5
    assert summary.unit == '%'


def test_summary_single_sample_all_statistics_equal_that_value():
    observations = [_observation(value=42.0)]
    summary = compute_resource_metric_summary(observations)
    assert summary.mean == summary.median == summary.p95 == summary.min == summary.max == 42.0
    assert summary.sample_count == 1


def test_summary_empty_observation_list_returns_none():
    assert compute_resource_metric_summary([]) is None


def test_summary_all_unavailable_returns_none_not_a_fabricated_zero():
    observations = [
        _observation(value=None, quality='unavailable'),
        _observation(value=None, quality='unavailable'),
    ]
    assert compute_resource_metric_summary(observations) is None


def test_summary_ignores_unavailable_rows_mixed_with_real_ones():
    observations = [
        _observation(value=10.0),
        _observation(value=None, quality='unavailable'),
        _observation(value=20.0),
    ]
    summary = compute_resource_metric_summary(observations)
    assert summary.sample_count == 2
    assert summary.mean == pytest.approx(15.0)


def test_summary_mixed_units_raises():
    observations = [
        _observation(value=10.0, unit='%'),
        _observation(value=5.0, unit='MB'),
    ]
    with pytest.raises(ValueError, match='mixed units'):
        compute_resource_metric_summary(observations)


# --- compute_configuration_resource_profile ---------------------------------

def test_profile_complete_when_every_requested_metric_has_evidence():
    now = datetime.now(timezone.utc)
    observations = [
        _observation(metric='cpu_percent', value=30.0, unit='%', started_at=now, ended_at=now),
        _observation(metric='memory_mb', value=800.0, unit='MB', started_at=now, ended_at=now),
    ]
    profile = compute_configuration_resource_profile(
        session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID,
        requested_metrics=['cpu_percent', 'memory_mb'], observations=observations,
    )
    assert profile.validity == 'complete'
    assert set(profile.metrics) == {'cpu_percent', 'memory_mb'}
    assert profile.warnings == []


def test_profile_partial_when_some_requested_metrics_have_no_evidence():
    now = datetime.now(timezone.utc)
    observations = [_observation(metric='cpu_percent', value=30.0, started_at=now, ended_at=now)]
    profile = compute_configuration_resource_profile(
        session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID,
        requested_metrics=['cpu_percent', 'network_receive_mbps'], observations=observations,
    )
    assert profile.validity == 'partial'
    assert set(profile.metrics) == {'cpu_percent'}
    assert "network_receive_mbps" in profile.warnings[0]


def test_profile_unavailable_when_no_requested_metric_has_evidence():
    profile = compute_configuration_resource_profile(
        session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID,
        requested_metrics=['cpu_percent'], observations=[],
    )
    assert profile.validity == 'unavailable'
    assert profile.metrics == {}
    assert profile.measurement_window is None


def test_profile_empty_requested_metrics_is_unavailable_not_vacuously_complete():
    observations = [_observation(metric='cpu_percent', value=30.0)]
    profile = compute_configuration_resource_profile(
        session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID,
        requested_metrics=[], observations=observations,
    )
    assert profile.validity == 'unavailable'


def test_profile_measurement_window_spans_irregular_gapped_windows():
    # Two non-contiguous windows for the same metric - the profile's
    # overall window must honestly span the full range, gap included,
    # not just sum the covered durations.
    early_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    early_end = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    late_start = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)  # a real gap after early_end
    late_end = datetime(2026, 1, 1, 0, 1, 5, tzinfo=timezone.utc)
    observations = [
        _observation(id='obs-early', metric='cpu_percent', value=10.0, started_at=early_start, ended_at=early_end),
        _observation(id='obs-late', metric='cpu_percent', value=20.0, started_at=late_start, ended_at=late_end),
    ]
    profile = compute_configuration_resource_profile(
        session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID,
        requested_metrics=['cpu_percent'], observations=observations,
    )
    assert profile.measurement_window == (early_start, late_end)
    assert profile.metrics['cpu_percent'].sample_count == 2


def test_profile_ignores_observations_for_unrequested_metrics():
    observations = [
        _observation(metric='cpu_percent', value=30.0),
        _observation(metric='memory_mb', value=800.0),
    ]
    profile = compute_configuration_resource_profile(
        session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID,
        requested_metrics=['cpu_percent'], observations=observations,
    )
    assert set(profile.metrics) == {'cpu_percent'}
