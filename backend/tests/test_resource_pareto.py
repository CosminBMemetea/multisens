"""Phase 69: resource constraints and resource-aware Pareto/dominance.
The Pareto generalization's own acceptance criterion is an equivalence
test: called with exactly decision.py's fixed 3 dimensions, it must
produce identical results to decision.py's own already-tested
find_dominated_configurations/find_pareto_front on every scenario that
module's own test suite already covers.
"""
import inspect

import pytest

from app.domain.analysis import AggregateCoverage
from app.domain.decision import ConfigurationDecision
from app.domain.decision import find_dominated_configurations as decision_find_dominated
from app.domain.decision import find_pareto_front as decision_find_pareto_front
from app.domain.profiles import AcceptanceCriterion
from app.domain.resources import (
    ConfigurationResourceProfile,
    ParetoPoint,
    ResourceMetricSummary,
    evaluate_resource_constraint,
    evaluate_resource_qualification,
    find_dominated_points,
    find_pareto_front_general,
)
from app.domain import resources as resources_module

PLATFORM_ID = 'macbook-m2-dockerdesktop'


def _summary(mean, unit='%'):
    return ResourceMetricSummary(mean=mean, median=mean, p95=mean, min=mean, max=mean, sample_count=1, unit=unit,
                                  quality='measured')


def _profile(metrics):
    return ConfigurationResourceProfile(
        configuration_id='cfg-a', session_id='s1', platform_id=PLATFORM_ID,
        metrics=metrics, measurement_window=None, validity='complete', warnings=[],
    )


# --- resource constraints ----------------------------------------------------

def test_constraint_pass():
    criterion = AcceptanceCriterion(metric='cpu_percent', operator='<=', value=50.0)
    result = evaluate_resource_constraint(criterion, _profile({'cpu_percent': _summary(30.0)}))
    assert result.status == 'pass'
    assert result.observed == 30.0


def test_constraint_fail():
    criterion = AcceptanceCriterion(metric='cpu_percent', operator='<=', value=20.0)
    result = evaluate_resource_constraint(criterion, _profile({'cpu_percent': _summary(30.0)}))
    assert result.status == 'fail'


def test_constraint_na_when_metric_absent_never_fail():
    criterion = AcceptanceCriterion(metric='network_receive_mbps', operator='<=', value=10.0)
    result = evaluate_resource_constraint(criterion, _profile({}))
    assert result.status == 'na'
    assert result.observed is None


# --- qualification: direct 3-state map, never the evaluate_policy bounding -

def test_qualification_all_pass_qualifies():
    results = [evaluate_resource_constraint(AcceptanceCriterion(metric='cpu_percent', operator='<=', value=50.0),
                                              _profile({'cpu_percent': _summary(30.0)}))]
    assert evaluate_resource_qualification(results) == 'qualifies'


def test_qualification_any_fail_does_not_qualify_regardless_of_others():
    profile = _profile({'cpu_percent': _summary(30.0), 'memory_mb': _summary(2000.0, unit='MB')})
    results = [
        evaluate_resource_constraint(AcceptanceCriterion(metric='cpu_percent', operator='<=', value=50.0), profile),
        evaluate_resource_constraint(AcceptanceCriterion(metric='memory_mb', operator='<=', value=1000.0), profile),
    ]
    assert evaluate_resource_qualification(results) == 'does_not_qualify'


def test_qualification_na_with_rest_passing_is_undetermined_never_qualifies():
    profile = _profile({'cpu_percent': _summary(30.0)})
    results = [
        evaluate_resource_constraint(AcceptanceCriterion(metric='cpu_percent', operator='<=', value=50.0), profile),
        evaluate_resource_constraint(AcceptanceCriterion(metric='network_receive_mbps', operator='<=', value=10.0), profile),
    ]
    assert evaluate_resource_qualification(results) == 'undetermined'
    assert evaluate_resource_qualification(results) != 'qualifies'


def test_qualification_zero_constraints_is_undetermined_not_vacuous_qualifies():
    assert evaluate_resource_qualification([]) == 'undetermined'


# --- generalized Pareto: equivalence with decision.py's fixed 3D version ---

def _agg(coverage, completeness):
    return AggregateCoverage(pass_count=1, fail_count=0, na_count=0, requirement_coverage=coverage, evidence_completeness=completeness)


def _decision(configuration_id, sensor_count, coverage, completeness):
    sensor_ids = frozenset(f'sensor-{i}' for i in range(sensor_count))
    return ConfigurationDecision(configuration_id, sensor_ids, _agg(coverage, completeness), [], 'sufficient')


THREE_DIMENSIONS = {
    'sensor_count': 'minimize',
    'requirement_coverage': 'maximize',
    'evidence_completeness': 'maximize',
}


def _to_point(decision: ConfigurationDecision) -> ParetoPoint:
    return ParetoPoint(id=decision.configuration_id, values={
        'sensor_count': float(len(decision.sensor_ids)),
        'requirement_coverage': decision.aggregate.requirement_coverage,
        'evidence_completeness': decision.aggregate.evidence_completeness,
    })


# Mirrors every scenario decision.py's own test_decision.py already
# covers for dominance/Pareto - same scenarios, cross-checked here.
EQUIVALENCE_SCENARIOS = [
    pytest.param([_decision('small', 1, 1.0, 1.0), _decision('large', 2, 1.0, 1.0)], id='fewer_sensors_same_coverage'),
    pytest.param([_decision('better', 1, 0.95, 1.0), _decision('worse', 1, 0.80, 1.0)], id='higher_coverage_same_sensors'),
    pytest.param([_decision('fewer', 1, 0.7, 1.0), _decision('more', 2, 1.0, 1.0)], id='genuine_tradeoff_both_survive'),
    pytest.param([_decision('undecided', 1, None, None), _decision('decided', 1, 0.5, 0.5)], id='none_dominated_by_real'),
    pytest.param([_decision('a', 1, None, None), _decision('b', 1, None, None)], id='two_nones_tie'),
    pytest.param([
        _decision('a', 1, 1.0, 1.0), _decision('b', 2, 1.0, 1.0), _decision('c', 3, 0.5, 1.0),
    ], id='three_way_mixed'),
]


@pytest.mark.parametrize('decisions', EQUIVALENCE_SCENARIOS)
def test_generalized_pareto_matches_decisionpy_three_dimension_result(decisions):
    original_dominated = {d.configuration_id for d in decision_find_dominated(decisions)}
    original_front = {d.configuration_id for d in decision_find_pareto_front(decisions)}

    points = [_to_point(d) for d in decisions]
    generalized_dominated = {p.id for p in find_dominated_points(points, THREE_DIMENSIONS)}
    generalized_front = {p.id for p in find_pareto_front_general(points, THREE_DIMENSIONS)}

    assert generalized_dominated == original_dominated
    assert generalized_front == original_front


def test_generalized_pareto_extends_beyond_three_dimensions():
    # The whole point of generalizing - a dimension decision.py's fixed
    # version could never express (a resource metric, minimize).
    a = ParetoPoint(id='cfg-a', values={'sensor_count': 1.0, 'requirement_coverage': 1.0, 'cpu_percent': 20.0})
    b = ParetoPoint(id='cfg-b', values={'sensor_count': 1.0, 'requirement_coverage': 1.0, 'cpu_percent': 40.0})
    dimensions = {'sensor_count': 'minimize', 'requirement_coverage': 'maximize', 'cpu_percent': 'minimize'}
    dominated = {p.id for p in find_dominated_points([a, b], dimensions)}
    assert dominated == {'cfg-b'}


def test_generalized_pareto_missing_dimension_value_is_worst():
    with_value = ParetoPoint(id='cfg-with', values={'cpu_percent': 20.0})
    without_value = ParetoPoint(id='cfg-without', values={})
    dominated = {p.id for p in find_dominated_points([with_value, without_value], {'cpu_percent': 'minimize'})}
    assert dominated == {'cfg-without'}


# --- no magic score anywhere -------------------------------------------------

def test_no_combined_score_field_exists_in_resources_module():
    # Checks for an actual field/attribute *definition* (name: ... or
    # name = ...), not prose - the module's own docstrings legitimately
    # name these terms as explicitly-rejected examples ("no
    # overall_efficiency_score exists"), which a bare substring check
    # would wrongly flag as if it were the field itself.
    import re
    source = inspect.getsource(resources_module)
    for forbidden in ('efficiency_score', 'deployment_score', 'overall_efficiency_score', 'importance_score'):
        assert not re.search(rf'\b{forbidden}\s*[:=]', source), f'found a defined field/attribute: {forbidden}'
