"""Phase 30: RequirementResult/CriterionResult/GroupCoverage/
ConfigurationCoverage model shape tests. Field-level construction and
basic validation only.

Phase 34: acceptance engine tests - evaluate_criterion/evaluate_requirement
- metric lookup (including the synthetic "coverage" key), all five
operators, N/A-not-fail for unresolvable metrics, and the requirement-
level status priority (no evidence > any N/A criterion > any failed
criterion > pass).

Phase 35: coverage engine tests - compute_requirement_results (wires
select_evidence + evaluate_requirement across a whole profile) and
compute_configuration_coverage (recursive leaf-count group aggregation -
never an average of child percentages, N/A never 0 for an empty group)."""
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
    compute_configuration_coverage,
    compute_requirement_results,
    evaluate_criterion,
    evaluate_requirement,
)
from app.domain.evidence import EvidenceBinding, EvidenceSelection, ResolvedEvidence, SessionCandidate, select_evidence
from app.domain.models import EvaluationResult, Session
from app.domain.profiles import AcceptanceCriterion, EvaluationProfile, Requirement, RequirementGroup


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


# --- compute_requirement_results (Phase 35) --------------------------------

def test_compute_requirement_results_one_per_requirement_in_profile_order():
    profile = EvaluationProfile(
        id='p1', name='P', version='1.0',
        groups=[RequirementGroup(id='g1', name='G1')],
        requirements=[
            _requirement(id='r1', task='presence'),
            _requirement(id='r2', task='presence', acceptance=[
                AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.99),
            ]),
        ],
        created_at=datetime.now(timezone.utc),
    )
    candidate = SessionCandidate(session=_session(), evaluation_result=_evaluation_result(), source_ids=['rgb_model'])
    results = compute_requirement_results(profile, 'cfg-rgb', {'presence': [candidate]})
    assert [r.requirement_id for r in results] == ['r1', 'r2']
    assert results[0].status == 'pass'
    assert results[1].status == 'fail'  # 0.94 < 0.99


def test_compute_requirement_results_missing_task_in_candidates_is_na():
    profile = EvaluationProfile(
        id='p1', name='P', version='1.0',
        groups=[RequirementGroup(id='g1', name='G1')],
        requirements=[_requirement(id='r1', task='drowsiness')],
        created_at=datetime.now(timezone.utc),
    )
    # candidates_by_task has no entry for 'drowsiness' at all.
    results = compute_requirement_results(profile, 'cfg-rgb', {})
    assert results[0].status == 'na'


def test_compute_requirement_results_binding_resolves_ambiguity():
    s1 = _session(id='s1', metadata={'illumination': 'night'})
    s2 = _session(id='s2', metadata={'illumination': 'night'})
    candidates = [
        SessionCandidate(session=s1, evaluation_result=_evaluation_result(session_id='s1'), source_ids=['rgb_model']),
        SessionCandidate(session=s2, evaluation_result=_evaluation_result(session_id='s2'), source_ids=['rgb_model']),
    ]
    profile = EvaluationProfile(
        id='p1', name='P', version='1.0',
        groups=[RequirementGroup(id='g1', name='G1')],
        requirements=[_requirement(id='r1', task='presence', conditions={'illumination': 'night'})],
        created_at=datetime.now(timezone.utc),
    )
    without_binding = compute_requirement_results(profile, 'cfg-rgb', {'presence': candidates})
    assert without_binding[0].status == 'na'  # ambiguous

    with_binding = compute_requirement_results(
        profile, 'cfg-rgb', {'presence': candidates}, bindings={'r1': EvidenceBinding(session_id='s2')},
    )
    assert with_binding[0].status == 'pass'
    assert with_binding[0].evidence.session_id == 's2'


# --- compute_configuration_coverage (Phase 35) -----------------------------

def _result(requirement_id, status, **overrides) -> RequirementResult:
    defaults = dict(
        profile_id='p1', profile_version='1.0', requirement_id=requirement_id,
        configuration_id='cfg-rgb', task='presence', status=status,
        reasons=[] if status == 'pass' else ['x'], computed_at=datetime.now(timezone.utc),
    )
    return RequirementResult(**{**defaults, **overrides})


def _three_level_profile() -> EvaluationProfile:
    # root
    #   g1 (Function A)              - own requirement r3 (na)
    #     g1-1 (Use Case A1)         - no own requirements
    #       g1-1-1 (Variant group)   - own requirements r1 (pass), r2 (fail)
    #   g2 (Function B)              - empty: no requirements, no children
    groups = [
        RequirementGroup(id='g1', name='Function A'),
        RequirementGroup(id='g1-1', parent_id='g1', name='Use Case A1'),
        RequirementGroup(id='g1-1-1', parent_id='g1-1', name='Variant group'),
        RequirementGroup(id='g2', name='Function B'),
    ]
    requirements = [
        _requirement(id='r1', group_id='g1-1-1'),
        _requirement(id='r2', group_id='g1-1-1'),
        _requirement(id='r3', group_id='g1'),
    ]
    return EvaluationProfile(
        id='p1', name='Example Profile', version='1.0', groups=groups, requirements=requirements,
        created_at=datetime.now(timezone.utc),
    )


def test_compute_configuration_coverage_nested_groups_aggregate_bottom_up():
    profile = _three_level_profile()
    results = [_result('r1', 'pass'), _result('r2', 'fail'), _result('r3', 'na')]
    coverage = compute_configuration_coverage(profile, 'cfg-rgb', results)

    root = coverage.root
    g1 = next(g for g in root.children if g.group_id == 'g1')
    g1_1 = next(g for g in g1.children if g.group_id == 'g1-1')
    g1_1_1 = next(g for g in g1_1.children if g.group_id == 'g1-1-1')
    g2 = next(g for g in root.children if g.group_id == 'g2')

    # Leaf group: its own two requirements only.
    assert (g1_1_1.pass_count, g1_1_1.fail_count, g1_1_1.na_count) == (1, 1, 0)
    assert g1_1_1.requirement_coverage == pytest.approx(0.5)
    assert g1_1_1.evidence_completeness == pytest.approx(1.0)

    # Mid group: no own requirements, purely its child's counts.
    assert (g1_1.pass_count, g1_1.fail_count, g1_1.na_count) == (1, 1, 0)

    # Top group: own r3 (na) plus its descendant's counts.
    assert (g1.pass_count, g1.fail_count, g1.na_count) == (1, 1, 1)
    assert g1.requirement_coverage == pytest.approx(0.5)  # 1 / (1+1), na excluded from denominator
    assert g1.evidence_completeness == pytest.approx(2 / 3)

    # Empty group: N/A, never 0.
    assert (g2.pass_count, g2.fail_count, g2.na_count) == (0, 0, 0)
    assert g2.requirement_coverage is None
    assert g2.evidence_completeness is None

    # Root: sum of both top-level groups (g2 contributes nothing).
    assert (root.pass_count, root.fail_count, root.na_count) == (1, 1, 1)
    assert root.requirement_coverage == pytest.approx(0.5)
    assert root.evidence_completeness == pytest.approx(2 / 3)
    assert root.group_id is None


def test_compute_configuration_coverage_all_pass():
    profile = _three_level_profile()
    results = [_result('r1', 'pass'), _result('r2', 'pass'), _result('r3', 'pass')]
    coverage = compute_configuration_coverage(profile, 'cfg-rgb', results)
    assert coverage.root.requirement_coverage == pytest.approx(1.0)
    assert coverage.root.evidence_completeness == pytest.approx(1.0)


def test_compute_configuration_coverage_all_fail():
    profile = _three_level_profile()
    results = [_result('r1', 'fail'), _result('r2', 'fail'), _result('r3', 'fail')]
    coverage = compute_configuration_coverage(profile, 'cfg-rgb', results)
    assert coverage.root.requirement_coverage == pytest.approx(0.0)
    assert coverage.root.evidence_completeness == pytest.approx(1.0)


def test_compute_configuration_coverage_all_na_is_none_not_zero():
    profile = _three_level_profile()
    results = [_result('r1', 'na'), _result('r2', 'na'), _result('r3', 'na')]
    coverage = compute_configuration_coverage(profile, 'cfg-rgb', results)
    assert coverage.root.requirement_coverage is None
    assert coverage.root.evidence_completeness == pytest.approx(0.0)


def test_compute_configuration_coverage_is_not_an_average_of_child_percentages():
    # Group A: 1 requirement, 100% coverage. Group B: 10 requirements, 1
    # pass / 9 fail, 10% coverage. A naive average would report ~55% for
    # the parent; leaf-count aggregation must report 2/11 ~= 18.2%.
    groups = [RequirementGroup(id='ga', name='A'), RequirementGroup(id='gb', name='B')]
    requirements = [_requirement(id='a1', group_id='ga')] + [
        _requirement(id=f'b{i}', group_id='gb') for i in range(10)
    ]
    profile = EvaluationProfile(
        id='p1', name='P', version='1.0', groups=groups, requirements=requirements,
        created_at=datetime.now(timezone.utc),
    )
    results = [_result('a1', 'pass')] + [_result(f'b{i}', 'pass' if i == 0 else 'fail') for i in range(10)]
    coverage = compute_configuration_coverage(profile, 'cfg-rgb', results)

    naive_average = (1.0 + 0.1) / 2
    assert coverage.root.requirement_coverage == pytest.approx(2 / 11)
    assert coverage.root.requirement_coverage != pytest.approx(naive_average)


def test_compute_configuration_coverage_raises_on_missing_result():
    profile = _three_level_profile()
    results = [_result('r1', 'pass'), _result('r2', 'fail')]  # r3 missing
    with pytest.raises(ValueError, match='missing'):
        compute_configuration_coverage(profile, 'cfg-rgb', results)


def test_compute_configuration_coverage_raises_on_unexpected_result():
    profile = _three_level_profile()
    results = [
        _result('r1', 'pass'), _result('r2', 'fail'), _result('r3', 'na'),
        _result('does-not-exist', 'pass'),
    ]
    with pytest.raises(ValueError, match='unexpected'):
        compute_configuration_coverage(profile, 'cfg-rgb', results)
