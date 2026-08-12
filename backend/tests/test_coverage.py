"""Phase 30: RequirementResult/CriterionResult/GroupCoverage/
ConfigurationCoverage model shape tests. Field-level construction and
basic validation only.

Phase 34: acceptance engine tests - evaluate_criterion/evaluate_requirement
- metric lookup (including the synthetic "coverage" key), all five
operators, N/A-not-fail for unresolvable metrics, and the requirement-
level status priority (no evidence > any N/A criterion > any failed
criterion > pass). Aggregation (Phase 35) is not implemented or tested
here."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.comparison import ComparisonMetrics
from app.domain.coverage import (
    ConfigurationCoverage,
    CriterionResult,
    EvidenceReference,
    GroupCoverage,
    RequirementResult,
    evaluate_criterion,
    evaluate_requirement,
)
from app.domain.evidence import EvidenceSelection, ResolvedEvidence, SessionCandidate, select_evidence
from app.domain.models import EvaluationResult, Session
from app.domain.profiles import AcceptanceCriterion, Requirement


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


# --- evaluate_criterion (Phase 34) -----------------------------------------

def _metrics(**overrides) -> ComparisonMetrics:
    defaults = dict(
        sample_count=100, matched_samples=95, unmatched_predictions=2, unmatched_ground_truth=5,
        coverage=0.95, metrics={'recall_macro': 0.94, 'precision_macro': None},
    )
    return ComparisonMetrics(**{**defaults, **overrides})


@pytest.mark.parametrize('operator,threshold,observed,expected', [
    ('>=', 0.9, 0.9, 'pass'),
    ('>=', 0.9, 0.89, 'fail'),
    ('<=', 0.1, 0.1, 'pass'),
    ('<=', 0.1, 0.11, 'fail'),
    ('>', 0.9, 0.91, 'pass'),
    ('>', 0.9, 0.9, 'fail'),
    ('<', 0.1, 0.09, 'pass'),
    ('<', 0.1, 0.1, 'fail'),
    ('==', 1.0, 1.0, 'pass'),
    ('==', 1.0, 0.99, 'fail'),
])
def test_evaluate_criterion_every_operator(operator, threshold, observed, expected):
    metrics = _metrics(metrics={'m': observed})
    criterion = AcceptanceCriterion(metric='m', operator=operator, value=threshold)
    result = evaluate_criterion(criterion, metrics)
    assert result.status == expected
    assert result.observed == pytest.approx(observed)


def test_evaluate_criterion_resolves_synthetic_coverage_key():
    metrics = _metrics(coverage=0.95)
    criterion = AcceptanceCriterion(metric='coverage', operator='>=', value=0.9)
    result = evaluate_criterion(criterion, metrics)
    assert result.status == 'pass'
    assert result.observed == pytest.approx(0.95)


def test_evaluate_criterion_missing_metric_is_na_not_fail():
    metrics = _metrics(metrics={})
    criterion = AcceptanceCriterion(metric='does_not_exist', operator='>=', value=0.9)
    result = evaluate_criterion(criterion, metrics)
    assert result.status == 'na'
    assert result.observed is None


def test_evaluate_criterion_undefined_metric_value_is_na_not_fail():
    # Present in the dict but None - e.g. undefined precision - must be
    # treated identically to "not present at all," never coerced to 0.
    metrics = _metrics(metrics={'precision_macro': None})
    criterion = AcceptanceCriterion(metric='precision_macro', operator='>=', value=0.9)
    result = evaluate_criterion(criterion, metrics)
    assert result.status == 'na'


def test_evaluate_criterion_real_zero_metric_is_evaluated_not_na():
    metrics = _metrics(metrics={'m': 0.0})
    criterion = AcceptanceCriterion(metric='m', operator='>=', value=0.0)
    result = evaluate_criterion(criterion, metrics)
    assert result.status == 'pass'
    assert result.observed == 0.0


def test_evaluate_criterion_threshold_zero():
    metrics = _metrics(metrics={'m': 0.01})
    criterion = AcceptanceCriterion(metric='m', operator='>', value=0.0)
    result = evaluate_criterion(criterion, metrics)
    assert result.status == 'pass'


# --- evaluate_requirement (Phase 34) ---------------------------------------

def _session(**overrides) -> Session:
    defaults = dict(
        id='s1', name='Session 1', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        metadata={'illumination': 'night'},
    )
    return Session(**{**defaults, **overrides})


def _evaluation_result(**overrides) -> EvaluationResult:
    defaults = dict(
        id='er1', session_id='s1', configuration_id='cfg-rgb', task='presence',
        tolerance_ms=100.0, sample_count=100, matched_samples=95,
        unmatched_predictions=2, unmatched_ground_truth=5,
        metrics={'recall_macro': 0.94, 'precision_macro': None}, computed_at=datetime.now(timezone.utc),
    )
    return EvaluationResult(**{**defaults, **overrides})


def _requirement(**overrides) -> Requirement:
    defaults = dict(
        id='req-001', group_id='g1', name='Variant 1', task='presence',
        acceptance=[AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.9)],
    )
    return Requirement(**{**defaults, **overrides})


def _resolved_selection(evaluation_result=None, source_id='rgb_model') -> EvidenceSelection:
    return EvidenceSelection(resolved=ResolvedEvidence(
        session=_session(), source_id=source_id, evaluation_result=evaluation_result or _evaluation_result(),
    ))


def test_evaluate_requirement_no_evidence_is_na_with_reasons_and_no_evidence_reference():
    selection = EvidenceSelection(resolved=None, reasons=['no session matches conditions'])
    result = evaluate_requirement(_requirement(), 'p1', '1.0', 'cfg-rgb', selection)
    assert result.status == 'na'
    assert result.reasons == ['no session matches conditions']
    assert result.evidence is None
    assert result.criteria == []


def test_evaluate_requirement_all_criteria_pass_is_pass():
    requirement = _requirement(acceptance=[AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.9)])
    result = evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', _resolved_selection())
    assert result.status == 'pass'
    assert result.reasons == []
    assert result.evidence is not None
    assert result.evidence.session_id == 's1'
    assert result.evidence.source_id == 'rgb_model'
    assert result.evidence.coverage == pytest.approx(0.95)


def test_evaluate_requirement_any_failed_criterion_is_fail():
    requirement = _requirement(acceptance=[AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.99)])
    result = evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', _resolved_selection())
    assert result.status == 'fail'
    assert any('recall_macro' in r for r in result.reasons)
    assert result.evidence is not None  # evidence was resolved - still traceable on a fail


def test_evaluate_requirement_unresolvable_criterion_is_na_even_with_evidence_present():
    requirement = _requirement(acceptance=[AcceptanceCriterion(metric='does_not_exist', operator='>=', value=0.9)])
    result = evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', _resolved_selection())
    assert result.status == 'na'
    assert result.evidence is not None  # unlike the no-evidence case - evidence WAS resolved
    assert any('does_not_exist' in r for r in result.reasons)


def test_evaluate_requirement_one_na_criterion_among_passing_criteria_is_na_not_pass():
    # The stricter-than-"AND over known criteria" rule: one unresolvable
    # criterion makes the whole requirement na, even though every other
    # criterion passed.
    requirement = _requirement(acceptance=[
        AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.9),   # would pass
        AcceptanceCriterion(metric='does_not_exist', operator='>=', value=0.5),  # na
    ])
    result = evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', _resolved_selection())
    assert result.status == 'na'


def test_evaluate_requirement_multiple_criteria_and_semantics():
    requirement = _requirement(acceptance=[
        AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.9),  # passes (0.94)
        AcceptanceCriterion(metric='coverage', operator='>=', value=0.99),      # fails (0.95)
    ])
    result = evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', _resolved_selection())
    assert result.status == 'fail'
    assert len(result.criteria) == 2
    assert result.criteria[0].status == 'pass'
    assert result.criteria[1].status == 'fail'


def test_evaluate_requirement_composes_with_select_evidence_end_to_end():
    # Proves the two phases glue together the way the coverage engine
    # (Phase 35) will actually call them: select_evidence's output feeds
    # directly into evaluate_requirement with no adaptation needed.
    requirement = _requirement(conditions={'illumination': 'night'})
    candidate = SessionCandidate(session=_session(), evaluation_result=_evaluation_result(), source_ids=['rgb_model'])
    selection = select_evidence(requirement, [candidate])
    result = evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', selection)
    assert result.status == 'pass'
    assert result.evidence.evaluation_result_id == 'er1'
