"""Phase 30: EvaluationProfile/RequirementGroup/Requirement/
AcceptanceCriterion model shape tests. Field-level construction and basic
validation only - cross-field validation (duplicate ids, cycles, unknown
references) is Phase 31's validate_profile, not tested here."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.profiles import AcceptanceCriterion, EvaluationProfile, Requirement, RequirementGroup


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
