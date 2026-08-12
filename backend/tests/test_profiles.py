"""Phase 30: EvaluationProfile/RequirementGroup/Requirement/
AcceptanceCriterion model shape tests (field-level construction and basic
validation - unknown operator, empty acceptance list).

Phase 31: validate_profile tests - the cross-field checks Pydantic's own
field-level validation cannot express: duplicate ids, dangling group
references, parent-group cycles, requirements without a task, non-finite
thresholds, an empty profile."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.profiles import (
    AcceptanceCriterion,
    EvaluationProfile,
    Requirement,
    RequirementGroup,
    validate_profile,
)


def _criterion(**overrides) -> AcceptanceCriterion:
    defaults = {'metric': 'recall_macro', 'operator': '>=', 'value': 0.9}
    return AcceptanceCriterion(**{**defaults, **overrides})


def _requirement(**overrides) -> Requirement:
    defaults = dict(
        id='req-001', group_id='group-a', name='Variant 1', task='presence',
        conditions={'illumination': 'night'}, acceptance=[_criterion()],
    )
    return Requirement(**{**defaults, **overrides})


def _group(**overrides) -> RequirementGroup:
    defaults = dict(id='group-a', name='Function A')
    return RequirementGroup(**{**defaults, **overrides})


# --- AcceptanceCriterion -------------------------------------------------

def test_acceptance_criterion_constructs_with_known_operator():
    c = _criterion(operator='>=')
    assert c.metric == 'recall_macro'
    assert c.value == 0.9


@pytest.mark.parametrize('operator', ['>=', '<=', '>', '<', '=='])
def test_acceptance_criterion_accepts_every_supported_operator(operator):
    assert _criterion(operator=operator).operator == operator


def test_acceptance_criterion_rejects_unknown_operator():
    with pytest.raises(ValidationError):
        _criterion(operator='!=')


# --- Requirement -----------------------------------------------------------

def test_requirement_constructs_with_arbitrary_condition_keys():
    # Non-negotiable per the v0.4 architecture review: conditions are an
    # open dict, not a fixed vocabulary - a domain-unrelated key works
    # exactly like the illumination/eyewear examples, no special-casing.
    req = _requirement(conditions={'weather': 'rain', 'vibration_level': 3.5, 'camera_contaminated': True})
    assert req.conditions == {'weather': 'rain', 'vibration_level': 3.5, 'camera_contaminated': True}


def test_requirement_conditions_default_to_empty_dict():
    req = _requirement(conditions={})
    assert req.conditions == {}


def test_requirement_rejects_empty_acceptance_list():
    with pytest.raises(ValidationError, match='acceptance must not be empty'):
        _requirement(acceptance=[])


def test_requirement_accepts_multiple_criteria():
    req = _requirement(acceptance=[_criterion(metric='recall_macro'), _criterion(metric='coverage', value=0.95)])
    assert len(req.acceptance) == 2


def test_requirement_has_no_mandatory_or_weight_field():
    # Deliberately absent in v0.4 - see the architecture review on #31.
    req = _requirement()
    assert not hasattr(req, 'mandatory')
    assert not hasattr(req, 'weight')


# --- RequirementGroup --------------------------------------------------

def test_requirement_group_top_level_has_no_parent():
    group = _group()
    assert group.parent_id is None


def test_requirement_group_nested_carries_parent_id():
    group = _group(id='group-a-1', parent_id='group-a', name='Use Case A1')
    assert group.parent_id == 'group-a'


# --- EvaluationProfile ---------------------------------------------------

def test_evaluation_profile_constructs_with_groups_and_requirements():
    profile = EvaluationProfile(
        id='example-profile-v1.0', name='Example Profile', version='1.0',
        groups=[_group()], requirements=[_requirement()],
        created_at=datetime.now(timezone.utc),
    )
    assert profile.id == 'example-profile-v1.0'
    assert len(profile.groups) == 1
    assert len(profile.requirements) == 1


def test_evaluation_profile_allows_empty_groups_and_requirements_at_model_level():
    # An empty profile is a Phase 31 validation concern ("empty profile
    # where inappropriate"), not a model-shape concern - the model itself
    # must not forbid what the validator is responsible for rejecting.
    profile = EvaluationProfile(
        id='empty-profile', name='Empty', version='1.0',
        groups=[], requirements=[], created_at=datetime.now(timezone.utc),
    )
    assert profile.groups == []
    assert profile.requirements == []


def test_evaluation_profile_metadata_defaults_to_empty_dict():
    profile = EvaluationProfile(
        id='p', name='P', version='1.0', groups=[], requirements=[],
        created_at=datetime.now(timezone.utc),
    )
    assert profile.metadata == {}


def test_evaluation_profile_model_validate_rejects_unsupported_operator_in_raw_document():
    # Demonstrates the actual profile-ingestion path (Phase 32 will parse
    # a raw YAML/JSON document via model_validate, not construct Python
    # objects directly): an unsupported operator is rejected structurally
    # before an EvaluationProfile instance can exist at all - validate_profile
    # never even runs on it.
    with pytest.raises(ValidationError):
        EvaluationProfile.model_validate({
            'id': 'p', 'name': 'P', 'version': '1.0',
            'groups': [{'id': 'group-a', 'name': 'Function A'}],
            'requirements': [{
                'id': 'req-001', 'group_id': 'group-a', 'name': 'Variant 1', 'task': 'presence',
                'acceptance': [{'metric': 'recall_macro', 'operator': '!=', 'value': 0.9}],
            }],
            'created_at': datetime.now(timezone.utc).isoformat(),
        })


# --- validate_profile (Phase 31) ------------------------------------------

def _profile(groups, requirements, **overrides) -> EvaluationProfile:
    defaults = dict(id='p1', name='Profile', version='1.0', created_at=datetime.now(timezone.utc))
    return EvaluationProfile(**{**defaults, **overrides}, groups=groups, requirements=requirements)


def test_validate_profile_accepts_a_well_formed_profile():
    profile = _profile([_group()], [_requirement()])
    assert validate_profile(profile) == []


def test_validate_profile_accepts_arbitrary_depth_hierarchy():
    groups = [
        _group(id='g1', name='Top'),
        _group(id='g1-1', parent_id='g1', name='Mid'),
        _group(id='g1-1-1', parent_id='g1-1', name='Leaf group'),
    ]
    requirement = _requirement(group_id='g1-1-1')
    assert validate_profile(_profile(groups, [requirement])) == []


def test_validate_profile_rejects_duplicate_group_id():
    groups = [_group(id='g1', name='A'), _group(id='g1', name='A again')]
    errors = validate_profile(_profile(groups, [_requirement(group_id='g1')]))
    assert any("duplicate group id 'g1'" in e for e in errors)


def test_validate_profile_rejects_duplicate_requirement_id():
    reqs = [_requirement(id='req-001'), _requirement(id='req-001')]
    errors = validate_profile(_profile([_group()], reqs))
    assert any("duplicate requirement id 'req-001'" in e for e in errors)


def test_validate_profile_rejects_dangling_parent_group_reference():
    groups = [_group(id='g1', parent_id='does-not-exist', name='A')]
    errors = validate_profile(_profile(groups, [_requirement(group_id='g1')]))
    assert any("unknown parent group 'does-not-exist'" in e for e in errors)


def test_validate_profile_rejects_group_self_loop():
    groups = [_group(id='g1', parent_id='g1', name='A')]
    errors = validate_profile(_profile(groups, [_requirement(group_id='g1')]))
    assert any('cycle' in e for e in errors)


def test_validate_profile_rejects_two_node_group_cycle():
    groups = [
        _group(id='g1', parent_id='g2', name='A'),
        _group(id='g2', parent_id='g1', name='B'),
    ]
    errors = validate_profile(_profile(groups, [_requirement(group_id='g1')]))
    cycle_errors = [e for e in errors if 'cycle' in e]
    assert len(cycle_errors) == 2  # both g1 and g2 individually flagged


def test_validate_profile_rejects_unknown_group_reference_from_requirement():
    errors = validate_profile(_profile([_group()], [_requirement(group_id='does-not-exist')]))
    assert any("unknown group 'does-not-exist'" in e for e in errors)


def test_validate_profile_rejects_requirement_with_blank_task():
    errors = validate_profile(_profile([_group()], [_requirement(task='   ')]))
    assert any("requirement 'req-001' has no task" in e for e in errors)


def test_validate_profile_rejects_empty_profile():
    errors = validate_profile(_profile([], []))
    assert any('no requirements' in e for e in errors)


@pytest.mark.parametrize('bad_value', [float('nan'), float('inf'), float('-inf')])
def test_validate_profile_rejects_non_finite_threshold(bad_value):
    req = _requirement(acceptance=[_criterion(value=bad_value)])
    errors = validate_profile(_profile([_group()], [req]))
    assert any('non-finite threshold' in e for e in errors)


def test_validate_profile_rejects_criterion_with_blank_metric_name():
    req = _requirement(acceptance=[_criterion(metric='  ')])
    errors = validate_profile(_profile([_group()], [req]))
    assert any('no metric name' in e for e in errors)


def test_validate_profile_reports_every_error_not_just_the_first():
    # "Do not partially accept a malformed profile" also means: don't
    # stop at the first problem found. Two independent defects here
    # (dangling group reference, blank task) must both be reported.
    req = _requirement(group_id='does-not-exist', task='')
    errors = validate_profile(_profile([_group()], [req]))
    assert any('unknown group' in e for e in errors)
    assert any('no task' in e for e in errors)
    assert len(errors) == 2
