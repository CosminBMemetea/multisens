"""Phase 53/54: decision-support domain model + engine tests. Phase 53's
tests (below) lock in the DecisionPolicy/PolicyStatus contract itself;
Phase 54's tests cover evaluate_policy's sufficiency semantics and the
minimality/dominance algorithms, per the master prompt's own Section 47
checklist.
"""
import typing

import pytest

from app.domain.analysis import AggregateCoverage
from app.domain.decision import (
    ConfigurationDecision,
    ConfigurationEvidence,
    DecisionObjective,
    DecisionPolicy,
    PolicyStatus,
    evaluate_configurations,
    evaluate_policy,
    find_dominated_configurations,
    find_minimal_sufficient_sets,
    find_pareto_front,
    find_sufficient_configurations,
)


def test_decision_policy_round_trips_all_fields():
    policy = DecisionPolicy(
        minimum_requirement_coverage=1.0,
        minimum_evidence_completeness=0.95,
        mandatory_requirements_must_pass=True,
        objective='minimize_sensor_count',
    )
    assert policy.minimum_requirement_coverage == 1.0
    assert policy.minimum_evidence_completeness == 0.95
    assert policy.mandatory_requirements_must_pass is True
    assert policy.objective == 'minimize_sensor_count'


def test_decision_policy_has_no_default_for_any_field():
    # Every field is required - an omitted policy must be a 422 at the
    # API layer (Phase 56), never a silently-applied default here.
    with pytest.raises(TypeError):
        DecisionPolicy(minimum_requirement_coverage=1.0)  # missing the other three


def test_policy_status_has_exactly_three_values():
    assert typing.get_args(PolicyStatus) == ('sufficient', 'insufficient', 'undetermined')


def test_decision_objective_has_exactly_one_value_in_v06():
    # Only "minimize sensor count" is implemented in v0.6 - cost/power/
    # latency/... are architected for (an additive Literal extension)
    # but deliberately not implemented without real data behind them.
    assert typing.get_args(DecisionObjective) == ('minimize_sensor_count',)


# --- evaluate_policy (Phase 54) ---------------------------------------------

DEMO_POLICY = DecisionPolicy(
    minimum_requirement_coverage=1.0,
    minimum_evidence_completeness=0.95,
    mandatory_requirements_must_pass=True,
    objective='minimize_sensor_count',
)


def _agg(pass_count: int, fail_count: int, na_count: int, coverage: float | None, completeness: float | None):
    return AggregateCoverage(pass_count, fail_count, na_count, coverage, completeness)


def test_evaluate_policy_sufficient_when_all_criteria_met():
    policy = DecisionPolicy(0.8, 0.9, False, 'minimize_sensor_count')
    aggregate = _agg(pass_count=9, fail_count=1, na_count=0, coverage=0.9, completeness=1.0)
    assert evaluate_policy(aggregate, policy) == 'sufficient'


def test_evaluate_policy_insufficient_when_coverage_below_threshold():
    policy = DecisionPolicy(0.95, 0.9, False, 'minimize_sensor_count')
    aggregate = _agg(pass_count=9, fail_count=1, na_count=0, coverage=0.9, completeness=1.0)
    assert evaluate_policy(aggregate, policy) == 'insufficient'


def test_evaluate_policy_completeness_below_threshold_is_undetermined_not_insufficient():
    # 5 pass / 0 fail / 5 na -> coverage would trivially be 1.0 (no
    # fails at all), but only half the population has been decided -
    # completeness 0.5 is well below the 0.95 bar. Completeness can
    # only ever *improve* as more N/A's resolve (never worsen), so a
    # shortfall here is "not enough evidence gathered yet," always in
    # principle fixable by more testing - UNDETERMINED, never a
    # permanent INSUFFICIENT. (This exact case caught a real bug in an
    # earlier draft, where completeness was bounded the same way as
    # coverage and the threshold silently never fired - see PolicyStatus's
    # own docstring.)
    policy = DecisionPolicy(0.5, 0.95, False, 'minimize_sensor_count')
    aggregate = _agg(pass_count=5, fail_count=0, na_count=5, coverage=1.0, completeness=0.5)
    assert evaluate_policy(aggregate, policy) == 'undetermined'


def test_evaluate_policy_mandatory_failure_forces_insufficient():
    # Coverage/completeness both comfortably meet a loose bar, but one
    # requirement failed and mandatory_requirements_must_pass is True.
    policy = DecisionPolicy(0.5, 0.5, True, 'minimize_sensor_count')
    aggregate = _agg(pass_count=9, fail_count=1, na_count=0, coverage=0.9, completeness=1.0)
    assert evaluate_policy(aggregate, policy) == 'insufficient'


def test_evaluate_policy_zero_population_is_undetermined():
    aggregate = _agg(pass_count=0, fail_count=0, na_count=0, coverage=None, completeness=None)
    assert evaluate_policy(aggregate, DEMO_POLICY) == 'undetermined'


def test_evaluate_policy_na_heavy_worst_case_still_sufficient_is_sufficient():
    # 10 pass, 0 fail, 2 na. Even if both na resolve to fail (worst
    # case: 10 pass / 2 fail), coverage = 10/12 = 0.833 still clears an
    # 0.8 bar, and completeness would then be 1.0 - genuinely
    # guaranteed sufficient regardless of how the na's resolve.
    policy = DecisionPolicy(0.8, 0.8, False, 'minimize_sensor_count')
    aggregate = _agg(pass_count=10, fail_count=0, na_count=2, coverage=1.0, completeness=10 / 12)
    assert evaluate_policy(aggregate, policy) == 'sufficient'


def test_evaluate_policy_na_heavy_best_case_still_insufficient_is_insufficient():
    # 1 pass, 8 fail, 1 na. Even if the na resolves to pass (best case:
    # 2 pass / 8 fail), coverage = 2/10 = 0.2 still misses a 0.5 bar -
    # genuinely guaranteed insufficient regardless of the na's resolution.
    policy = DecisionPolicy(0.5, 0.5, False, 'minimize_sensor_count')
    aggregate = _agg(pass_count=1, fail_count=8, na_count=1, coverage=1 / 9, completeness=0.9)
    assert evaluate_policy(aggregate, policy) == 'insufficient'


def test_evaluate_policy_na_straddling_best_and_worst_is_undetermined():
    # 5 pass, 4 fail, 1 na against a 0.5 coverage bar. Worst case (5
    # pass / 5 fail) = 0.5, meets a >=0.5 bar -> would be sufficient.
    # Best case (6 pass / 4 fail) = 0.6 also passes... use a bar where
    # they genuinely straddle: 0.55. Worst = 0.5 (fails a 0.55 bar),
    # best = 0.6 (passes it) - the real outcome depends on the
    # unresolved na, so this must be undetermined, never insufficient.
    policy = DecisionPolicy(0.55, 0.0, False, 'minimize_sensor_count')
    aggregate = _agg(pass_count=5, fail_count=4, na_count=1, coverage=5 / 9, completeness=0.9)
    assert evaluate_policy(aggregate, policy) == 'undetermined'


def test_evaluate_configurations_attaches_policy_status_per_configuration():
    evidence = [
        ConfigurationEvidence('cfg-a', frozenset({'a'}), _agg(9, 1, 0, 0.9, 1.0)),
        ConfigurationEvidence('cfg-b', frozenset({'b'}), _agg(1, 9, 0, 0.1, 1.0)),
    ]
    policy = DecisionPolicy(0.8, 0.9, False, 'minimize_sensor_count')
    decisions = evaluate_configurations(evidence, policy)
    by_id = {d.configuration_id: d.policy_status for d in decisions}
    assert by_id == {'cfg-a': 'sufficient', 'cfg-b': 'insufficient'}


# --- find_minimal_sufficient_sets -------------------------------------------

def _decision(configuration_id: str, sensor_ids: frozenset[str], status: PolicyStatus) -> ConfigurationDecision:
    # coverage/completeness don't matter for minimality - only sensor_ids
    # and policy_status do.
    return ConfigurationDecision(configuration_id, sensor_ids, _agg(1, 0, 0, 1.0, 1.0), status)


def test_minimal_sufficient_set_excludes_a_superset():
    small = _decision('cfg-small', frozenset({'a'}), 'sufficient')
    large = _decision('cfg-large', frozenset({'a', 'b'}), 'sufficient')
    minimal = find_minimal_sufficient_sets([small, large])
    assert [d.configuration_id for d in minimal] == ['cfg-small']


def test_multiple_equally_minimal_sets_are_all_returned_unranked():
    a = _decision('cfg-a', frozenset({'front_rgb', 'sim_thermal'}), 'sufficient')
    b = _decision('cfg-b', frozenset({'rear_rgb', 'sim_depth'}), 'sufficient')
    minimal = find_minimal_sufficient_sets([a, b])
    assert {d.configuration_id for d in minimal} == {'cfg-a', 'cfg-b'}


def test_minimality_is_set_inclusion_not_just_sensor_count():
    # Three sufficient configs, all size 2 or fewer: {a} is a subset of
    # {a, b}, so {a, b} is excluded even though nothing "smaller" ties
    # it on count alone - and {c, d}, not a superset of anything else
    # here, survives alongside {a}.
    small = _decision('cfg-small', frozenset({'a'}), 'sufficient')
    superset = _decision('cfg-superset', frozenset({'a', 'b'}), 'sufficient')
    unrelated = _decision('cfg-unrelated', frozenset({'c', 'd'}), 'sufficient')
    minimal = find_minimal_sufficient_sets([small, superset, unrelated])
    assert {d.configuration_id for d in minimal} == {'cfg-small', 'cfg-unrelated'}


def test_undetermined_and_insufficient_configurations_never_appear_as_minimal():
    sufficient = _decision('cfg-suf', frozenset({'a'}), 'sufficient')
    undetermined = _decision('cfg-und', frozenset({'b'}), 'undetermined')
    insufficient = _decision('cfg-insuf', frozenset({'c'}), 'insufficient')
    all_decisions = [sufficient, undetermined, insufficient]
    only_sufficient = find_sufficient_configurations(all_decisions)
    assert [d.configuration_id for d in only_sufficient] == ['cfg-suf']
    minimal = find_minimal_sufficient_sets(only_sufficient)
    assert [d.configuration_id for d in minimal] == ['cfg-suf']


# --- dominance / Pareto front ------------------------------------------------

def _decision_with_coverage(configuration_id, sensor_ids, coverage, completeness):
    return ConfigurationDecision(
        configuration_id, frozenset(sensor_ids), _agg(1, 0, 0, coverage, completeness), 'sufficient',
    )


def test_fewer_sensors_same_coverage_dominates_more_sensors():
    small = _decision_with_coverage('cfg-small', {'a'}, 1.0, 1.0)
    large = _decision_with_coverage('cfg-large', {'a', 'b'}, 1.0, 1.0)
    dominated = {d.configuration_id for d in find_dominated_configurations([small, large])}
    assert dominated == {'cfg-large'}
    front = {d.configuration_id for d in find_pareto_front([small, large])}
    assert front == {'cfg-small'}


def test_higher_coverage_same_sensors_dominates_lower_coverage():
    better = _decision_with_coverage('cfg-better', {'a'}, 0.95, 1.0)
    worse = _decision_with_coverage('cfg-worse', {'a'}, 0.80, 1.0)
    dominated = {d.configuration_id for d in find_dominated_configurations([better, worse])}
    assert dominated == {'cfg-worse'}


def test_non_dominated_configurations_all_appear_on_pareto_front():
    # Genuinely incomparable trade-off: fewer sensors but lower coverage
    # vs. more sensors but higher coverage - neither dominates the other.
    fewer_lower = _decision_with_coverage('cfg-fewer', {'a'}, 0.7, 1.0)
    more_higher = _decision_with_coverage('cfg-more', {'a', 'b'}, 1.0, 1.0)
    front = {d.configuration_id for d in find_pareto_front([fewer_lower, more_higher])}
    assert front == {'cfg-fewer', 'cfg-more'}


def test_none_coverage_is_dominated_by_a_real_value_without_crashing():
    undecided = _decision_with_coverage('cfg-undecided', {'a'}, None, None)
    decided = _decision_with_coverage('cfg-decided', {'a'}, 0.5, 0.5)
    dominated = {d.configuration_id for d in find_dominated_configurations([undecided, decided])}
    assert dominated == {'cfg-undecided'}


def test_two_none_coverage_configurations_tie_and_neither_dominates():
    a = _decision_with_coverage('cfg-a', {'a'}, None, None)
    b = _decision_with_coverage('cfg-b', {'b'}, None, None)
    dominated = find_dominated_configurations([a, b])
    assert dominated == []
