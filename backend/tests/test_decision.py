"""Phase 53: decision-support domain model shape tests. Field-level
shape only - no evaluate_policy/minimality/dominance logic exists yet
(Phase 54), so these tests lock in the DecisionPolicy/PolicyStatus
contract itself, not any decision it produces.
"""
import typing

import pytest

from app.domain.decision import DecisionObjective, DecisionPolicy, PolicyStatus


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
