"""Phase 68: trade-off engine. Joins v0.6 decision evidence with v0.7
resource evidence without merging their semantics - these tests prove
the join never re-decides policy_status/coverage/completeness, that
comparability warnings fire on the right conditions, and that no
causal/importance-score language exists anywhere in this layer.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.analysis import AggregateCoverage
from app.domain.decision import ConfigurationDecision
from app.domain.resources import (
    ConfigurationResourceProfile,
    ResourceMetricSummary,
    ResourceObservation,
    build_configuration_tradeoff,
    check_comparability,
    compute_resource_delta,
)

PLATFORM_A = 'macbook-m2-dockerdesktop'
PLATFORM_B = 'jetson-orin-ubuntu'


def _agg(pass_count=1, fail_count=0, na_count=0, coverage=1.0, completeness=1.0):
    return AggregateCoverage(pass_count, fail_count, na_count, coverage, completeness)


def _decision(configuration_id='cfg-a', sensor_ids=('a',), status='sufficient', **agg_overrides):
    return ConfigurationDecision(configuration_id, frozenset(sensor_ids), _agg(**agg_overrides), [], status)


def _summary(mean=30.0, unit='%'):
    return ResourceMetricSummary(mean=mean, median=mean, p95=mean, min=mean, max=mean, sample_count=1, unit=unit)


def _profile(configuration_id='cfg-a', platform_id=PLATFORM_A, metrics=None, window=None, validity='complete'):
    now = datetime.now(timezone.utc)
    return ConfigurationResourceProfile(
        configuration_id=configuration_id, session_id='s1', platform_id=platform_id,
        metrics=metrics if metrics is not None else {'cpu_percent': _summary()},
        measurement_window=window if window is not None else (now, now + timedelta(seconds=10)),
        validity=validity, warnings=[],
    )


# --- build_configuration_tradeoff: never re-decides -------------------------

def test_tradeoff_reuses_decision_evidence_unchanged():
    decision = _decision(configuration_id='cfg-front_rgb', sensor_ids=('front_rgb',), status='insufficient',
                          pass_count=1, fail_count=1, coverage=0.5, completeness=1.0)
    tradeoff = build_configuration_tradeoff(decision, resource_profile=None)
    assert tradeoff.configuration_id == 'cfg-front_rgb'
    assert tradeoff.sensor_count == 1
    assert tradeoff.requirement_coverage == 0.5
    assert tradeoff.evidence_completeness == 1.0
    assert tradeoff.policy_status == 'insufficient'


def test_tradeoff_with_no_resource_profile_is_unavailable():
    decision = _decision()
    tradeoff = build_configuration_tradeoff(decision, resource_profile=None)
    assert tradeoff.resource_profile is None
    assert tradeoff.resource_validity == 'unavailable'


def test_tradeoff_resource_validity_mirrors_profile_validity():
    decision = _decision()
    profile = _profile(validity='partial')
    tradeoff = build_configuration_tradeoff(decision, resource_profile=profile)
    assert tradeoff.resource_profile is profile
    assert tradeoff.resource_validity == 'partial'


def test_tradeoff_sensor_count_derived_from_sensor_ids_length():
    decision = _decision(sensor_ids=('front_rgb', 'rear_rgb', 'sim_thermal'))
    tradeoff = build_configuration_tradeoff(decision, resource_profile=None)
    assert tradeoff.sensor_count == 3


# --- check_comparability -----------------------------------------------------

def test_comparable_when_everything_matches():
    profile_a = _profile(platform_id=PLATFORM_A)
    profile_b = _profile(platform_id=PLATFORM_A)
    result = check_comparability(profile_a, {'resolution': '640x480', 'target_fps': 30},
                                  profile_b, {'resolution': '640x480', 'target_fps': 30})
    assert result.comparable is True
    assert result.warnings == []


def test_different_platforms_are_not_comparable():
    result = check_comparability(_profile(platform_id=PLATFORM_A), {}, _profile(platform_id=PLATFORM_B), {})
    assert result.comparable is False
    assert any('platform' in w for w in result.warnings)


def test_unknown_platform_never_comparable_even_to_itself():
    from app.domain.resources import UNKNOWN_PLATFORM_ID
    result = check_comparability(
        _profile(platform_id=UNKNOWN_PLATFORM_ID), {}, _profile(platform_id=UNKNOWN_PLATFORM_ID), {},
    )
    assert result.comparable is False
    assert any('unresolved execution platform' in w for w in result.warnings)


def test_different_resolution_is_not_comparable():
    result = check_comparability(
        _profile(), {'resolution': '640x480'}, _profile(), {'resolution': '1920x1080'},
    )
    assert result.comparable is False
    assert any('resolution' in w for w in result.warnings)


def test_different_target_fps_is_not_comparable():
    result = check_comparability(_profile(), {'target_fps': 30}, _profile(), {'target_fps': 60})
    assert result.comparable is False
    assert any('FPS' in w for w in result.warnings)


def test_wildly_different_durations_are_not_comparable():
    now = datetime.now(timezone.utc)
    short = _profile(window=(now, now + timedelta(seconds=2)))
    long = _profile(window=(now, now + timedelta(seconds=600)))
    result = check_comparability(short, {}, long, {})
    assert result.comparable is False
    assert any('durations differ' in w for w in result.warnings)


def test_similar_order_of_magnitude_durations_are_comparable():
    now = datetime.now(timezone.utc)
    a = _profile(window=(now, now + timedelta(seconds=8)))
    b = _profile(window=(now, now + timedelta(seconds=10)))
    result = check_comparability(a, {}, b, {})
    assert result.comparable is True


def test_missing_resource_profile_on_either_side_is_not_comparable():
    result = check_comparability(None, {}, _profile(), {})
    assert result.comparable is False
    assert 'no resource evidence' in result.warnings[0]


# --- compute_resource_delta --------------------------------------------------

def test_resource_delta_computes_baseline_candidate_and_difference():
    baseline = build_configuration_tradeoff(
        _decision(configuration_id='cfg-front'), _profile(metrics={'cpu_percent': _summary(21.0)}),
    )
    candidate = build_configuration_tradeoff(
        _decision(configuration_id='cfg-front-rear'), _profile(metrics={'cpu_percent': _summary(31.0)}),
    )
    delta = compute_resource_delta(baseline, {'resolution': '640x480'}, candidate, {'resolution': '640x480'})
    assert delta.baseline_configuration_id == 'cfg-front'
    assert delta.candidate_configuration_id == 'cfg-front-rear'
    cpu_delta = next(d for d in delta.metric_deltas if d.metric == 'cpu_percent')
    assert cpu_delta.baseline == 21.0
    assert cpu_delta.candidate == 31.0
    assert cpu_delta.delta == pytest.approx(10.0)
    assert cpu_delta.unit == '%'


def test_resource_delta_metric_present_only_on_one_side_has_none_delta():
    baseline = build_configuration_tradeoff(_decision(configuration_id='cfg-a'), _profile(metrics={'cpu_percent': _summary(20.0)}))
    candidate = build_configuration_tradeoff(
        _decision(configuration_id='cfg-b'),
        _profile(metrics={'cpu_percent': _summary(30.0), 'memory_mb': _summary(800.0, unit='MB')}),
    )
    delta = compute_resource_delta(baseline, {}, candidate, {})
    memory_delta = next(d for d in delta.metric_deltas if d.metric == 'memory_mb')
    assert memory_delta.baseline is None
    assert memory_delta.candidate == 800.0
    assert memory_delta.delta is None


def test_resource_delta_carries_comparability_alongside_the_numbers():
    baseline = build_configuration_tradeoff(_decision(configuration_id='cfg-a'), _profile(platform_id=PLATFORM_A))
    candidate = build_configuration_tradeoff(_decision(configuration_id='cfg-b'), _profile(platform_id=PLATFORM_B))
    delta = compute_resource_delta(baseline, {}, candidate, {})
    # Even when not comparable, the numbers are still returned - never
    # silently suppressed alongside the warning.
    assert delta.comparability.comparable is False
    assert len(delta.metric_deltas) > 0


# --- non-causal language discipline ------------------------------------------

def test_no_causal_or_importance_score_language_in_this_module():
    import inspect

    from app.domain import resources as resources_module

    source = inspect.getsource(resources_module)
    causal_pattern = re.compile(r'\bcaus(e|ed|es|ing)\b', re.IGNORECASE)
    matches = [m.group() for m in causal_pattern.finditer(source) if 'because' not in source[max(0, m.start() - 3):m.start()]]
    assert matches == [], f'found causal-adjacent language: {matches}'
    # Checks for an actual field/attribute *definition*, not prose - later
    # phases' own module docstrings legitimately name these terms as
    # explicitly-rejected examples ("no deployment_score exists"), which a
    # bare substring check would wrongly flag as if it were the field itself.
    score_field_pattern = re.compile(r'\b(importance|efficiency|deployment)_score\s*[:=]')
    assert not score_field_pattern.search(source), 'found a defined combined-score field'
