"""Phase 30: RequirementResult/CriterionResult/GroupCoverage/
ConfigurationCoverage model shape tests. Field-level construction and
basic validation only - evidence selection (Phase 33), acceptance
evaluation (Phase 34), and aggregation (Phase 35) are not implemented or
tested here, only the shapes those phases will produce."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.coverage import (
    ConfigurationCoverage,
    CriterionResult,
    EvidenceReference,
    GroupCoverage,
    RequirementResult,
)


def _criterion_result(**overrides) -> CriterionResult:
    defaults = dict(metric='recall_macro', operator='>=', threshold=0.9, observed=0.94, status='pass')
    return CriterionResult(**{**defaults, **overrides})


def _evidence() -> EvidenceReference:
    return EvidenceReference(
        session_id='s1', scenario_id='sc1', configuration_id='cfg-rgb', source_id='rgb_model',
        evaluation_result_id='er1', matched_samples=95, sample_count=100, coverage=0.95,
    )


def _requirement_result(**overrides) -> RequirementResult:
    defaults = dict(
        profile_id='p1', profile_version='1.0', requirement_id='req-001',
        configuration_id='cfg-rgb', task='presence', status='pass',
        criteria=[_criterion_result()], evidence=_evidence(),
        computed_at=datetime.now(timezone.utc),
    )
    return RequirementResult(**{**defaults, **overrides})


# --- CriterionResult -------------------------------------------------------

def test_criterion_result_pass_carries_observed_value():
    result = _criterion_result(status='pass', observed=0.94)
    assert result.observed == pytest.approx(0.94)


def test_criterion_result_na_allows_observed_to_be_none():
    result = _criterion_result(status='na', observed=None)
    assert result.observed is None


# --- RequirementResult -----------------------------------------------------

def test_requirement_result_pass_allows_empty_reasons():
    result = _requirement_result(status='pass', reasons=[])
    assert result.reasons == []


@pytest.mark.parametrize('status', ['fail', 'na'])
def test_requirement_result_non_pass_requires_a_reason(status):
    with pytest.raises(ValidationError, match='requires at least one reason'):
        _requirement_result(status=status, reasons=[])


def test_requirement_result_fail_with_reason_constructs():
    result = _requirement_result(status='fail', reasons=['recall_macro >= 0.9 failed: observed 0.83'])
    assert result.status == 'fail'


def test_requirement_result_na_can_have_no_evidence():
    # No matching session at all is a valid na case - evidence is None,
    # not a fabricated placeholder.
    result = _requirement_result(status='na', reasons=['no evidence'], criteria=[], evidence=None)
    assert result.evidence is None
    assert result.criteria == []


def test_requirement_result_pass_has_evidence():
    result = _requirement_result(status='pass')
    assert result.evidence is not None
    assert result.evidence.session_id == 's1'


# --- GroupCoverage -----------------------------------------------------

def test_group_coverage_root_has_no_group_id():
    root = GroupCoverage(
        group_id=None, name='root', pass_count=10, fail_count=2, na_count=1,
        requirement_coverage=10 / 12, evidence_completeness=12 / 13,
    )
    assert root.group_id is None
    assert root.children == []


def test_group_coverage_nests_children_recursively():
    child = GroupCoverage(
        group_id='group-a-1', name='Use Case A1', pass_count=4, fail_count=0, na_count=0,
        requirement_coverage=1.0, evidence_completeness=1.0,
    )
    parent = GroupCoverage(
        group_id='group-a', name='Function A', pass_count=4, fail_count=0, na_count=0,
        requirement_coverage=1.0, evidence_completeness=1.0, children=[child],
    )
    assert len(parent.children) == 1
    assert parent.children[0].group_id == 'group-a-1'


def test_group_coverage_allows_none_for_undecided_percentages():
    # pass + fail == 0 (everything N/A) - coverage must be None, never a
    # fabricated 0 or 1.
    group = GroupCoverage(
        group_id='group-b', name='Function B', pass_count=0, fail_count=0, na_count=5,
        requirement_coverage=None, evidence_completeness=0.0,
    )
    assert group.requirement_coverage is None
    assert group.evidence_completeness == 0.0


# --- ConfigurationCoverage -----------------------------------------------

def test_configuration_coverage_constructs_with_root_and_results():
    root = GroupCoverage(
        group_id=None, name='root', pass_count=1, fail_count=0, na_count=0,
        requirement_coverage=1.0, evidence_completeness=1.0,
    )
    coverage = ConfigurationCoverage(
        profile_id='p1', profile_version='1.0', configuration_id='cfg-rgb',
        requirement_results=[_requirement_result()], root=root,
    )
    assert coverage.configuration_id == 'cfg-rgb'
    assert len(coverage.requirement_results) == 1
    assert coverage.root.pass_count == 1
