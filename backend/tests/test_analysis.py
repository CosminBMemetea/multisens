"""Phase 42: AnalysisFilter/Facet/FacetValue model shape tests. Field-
level construction only.

Phase 43: facet discovery + filtering engine tests - discover_facets,
filter_requirement_ids, filter_results, and the filter_requirement_results
composition.

Phase 44: aggregation + grouping tests - aggregate_requirement_results,
group_by_condition, cross_tabulate, failure_breakdown/top_failing_groups,
and classify_na_reason/na_breakdown, including a cross-layer test that
constructs every real N/A reason through the actual select_evidence/
evaluate_requirement functions rather than hand-typed strings - exactly
the drift risk the v0.5 architecture review (issue #43, Q12/Q21) flagged."""
from datetime import datetime, timezone

import pytest

from app.domain.analysis import (
    AggregateCoverage,
    AnalysisFilter,
    Facet,
    FacetValue,
    aggregate_requirement_results,
    classify_na_reason,
    cross_tabulate,
    discover_facets,
    failure_breakdown,
    filter_requirement_ids,
    filter_requirement_results,
    filter_results,
    group_by_condition,
    na_breakdown,
    top_failing_groups,
)
from app.domain.coverage import RequirementResult, evaluate_requirement
from app.domain.evidence import EvidenceBinding, EvidenceSelection, SessionCandidate, select_evidence
from app.domain.models import EvaluationResult, Session
from app.domain.profiles import AcceptanceCriterion, EvaluationProfile, Requirement, RequirementGroup


def test_analysis_filter_defaults_to_no_predicates():
    f = AnalysisFilter()
    assert f.conditions == {}
    assert f.group_id is None
    assert f.task is None
    assert f.status is None


def test_analysis_filter_constructs_with_all_fields():
    f = AnalysisFilter(
        conditions={'illumination': 'night', 'smoke': True},
        group_id='g1', task='presence', status='fail',
    )
    assert f.conditions == {'illumination': 'night', 'smoke': True}
    assert f.group_id == 'g1'
    assert f.task == 'presence'
    assert f.status == 'fail'


def test_analysis_filter_accepts_arbitrary_condition_keys():
    # Non-negotiable per the v0.5 architecture review: conditions are an
    # open dict, not a fixed vocabulary - a domain-unrelated key works
    # exactly like the illumination/eyewear examples.
    f = AnalysisFilter(conditions={'weather': 'rain', 'vibration_level': 3.5})
    assert f.conditions == {'weather': 'rain', 'vibration_level': 3.5}


def test_facet_value_constructs():
    v = FacetValue(value='night', requirement_count=38)
    assert v.value == 'night'
    assert v.requirement_count == 38


def test_facet_constructs_with_multiple_values():
    facet = Facet(key='illumination', values=[
        FacetValue(value='day', requirement_count=42),
        FacetValue(value='night', requirement_count=38),
    ])
    assert facet.key == 'illumination'
    assert len(facet.values) == 2
    assert facet.values[0].value == 'day'


def test_facet_supports_boolean_and_numeric_values():
    facet = Facet(key='smoke', values=[
        FacetValue(value=True, requirement_count=10),
        FacetValue(value=False, requirement_count=20),
    ])
    assert facet.values[0].value is True

    numeric_facet = Facet(key='vibration_level', values=[FacetValue(value=3.5, requirement_count=5)])
    assert numeric_facet.values[0].value == 3.5


# --- fixtures --------------------------------------------------------------

def _criterion(**overrides) -> AcceptanceCriterion:
    return AcceptanceCriterion(**{**dict(metric='accuracy', operator='>=', value=0.5), **overrides})


def _requirement(**overrides) -> Requirement:
    defaults = dict(
        id='req', group_id='g-top', name='Req', task='presence',
        conditions={}, acceptance=[_criterion()],
    )
    return Requirement(**{**defaults, **overrides})


def _profile() -> EvaluationProfile:
    # g-top
    #   g-child (parent g-top)
    # g-other (sibling of g-top, no relation to g-child)
    groups = [
        RequirementGroup(id='g-top', name='Top'),
        RequirementGroup(id='g-child', parent_id='g-top', name='Child'),
        RequirementGroup(id='g-other', name='Other'),
    ]
    requirements = [
        _requirement(id='r1', group_id='g-top', task='presence',
                     conditions={'illumination': 'night', 'smoke': True}),
        _requirement(id='r2', group_id='g-child', task='presence',
                     conditions={'illumination': 'night'}),
        _requirement(id='r3', group_id='g-child', task='drowsiness',
                     conditions={'illumination': 'day'}),
        _requirement(id='r4', group_id='g-other', task='presence', conditions={}),
        _requirement(id='r5', group_id='g-other', task='presence',
                     conditions={'vibration_level': 3.5}),
    ]
    return EvaluationProfile(
        id='p1', name='P', version='1.0', groups=groups, requirements=requirements,
        created_at=datetime.now(timezone.utc),
    )


def _result(requirement_id: str, status: str, **overrides) -> RequirementResult:
    defaults = dict(
        profile_id='p1', profile_version='1.0', requirement_id=requirement_id,
        configuration_id='cfg-rgb', task='presence', status=status,
        reasons=[] if status == 'pass' else ['x'], computed_at=datetime.now(timezone.utc),
    )
    return RequirementResult(**{**defaults, **overrides})


# --- discover_facets ---------------------------------------------------

def test_discover_facets_counts_requirements_per_key_value():
    facets = {f.key: f for f in discover_facets(_profile())}
    assert set(facets) == {'illumination', 'smoke', 'vibration_level'}

    illumination_values = {v.value: v.requirement_count for v in facets['illumination'].values}
    assert illumination_values == {'night': 2, 'day': 1}

    assert {v.value: v.requirement_count for v in facets['smoke'].values} == {True: 1}
    assert {v.value: v.requirement_count for v in facets['vibration_level'].values} == {3.5: 1}


def test_discover_facets_ignores_requirements_with_no_conditions():
    # r4 has conditions={} - contributes nothing to any facet.
    facets = discover_facets(_profile())
    total_requirement_mentions = sum(v.requirement_count for f in facets for v in f.values)
    # r1 contributes 2 (illumination + smoke), r2/r3/r5 contribute 1 each - never r4.
    assert total_requirement_mentions == 5


def test_discover_facets_empty_profile_has_no_facets():
    profile = EvaluationProfile(
        id='p2', name='P2', version='1.0', groups=[], requirements=[],
        created_at=datetime.now(timezone.utc),
    )
    assert discover_facets(profile) == []


# --- filter_requirement_ids: conditions ---------------------------------

def test_filter_by_single_condition():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(conditions={'illumination': 'night'}))
    assert ids == {'r1', 'r2'}


def test_filter_and_semantics_across_multiple_conditions():
    ids = filter_requirement_ids(
        _profile(), AnalysisFilter(conditions={'illumination': 'night', 'smoke': True}),
    )
    assert ids == {'r1'}  # r2 has illumination=night but lacks smoke entirely


def test_filter_missing_condition_key_excludes_not_wildcards():
    # Every requirement except r1 lacks 'smoke' entirely - none of them
    # should match, not even r2 which shares illumination=night with r1.
    ids = filter_requirement_ids(_profile(), AnalysisFilter(conditions={'smoke': True}))
    assert ids == {'r1'}


def test_filter_boolean_condition_is_type_sensitive():
    # No requirement declares smoke=False in this fixture, and smoke=1
    # (int) must not match smoke=True (bool) even though `1 == True`.
    assert filter_requirement_ids(_profile(), AnalysisFilter(conditions={'smoke': False})) == set()
    assert filter_requirement_ids(_profile(), AnalysisFilter(conditions={'smoke': 1})) == set()


def test_filter_numeric_condition():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(conditions={'vibration_level': 3.5}))
    assert ids == {'r5'}


def test_filter_empty_conditions_matches_every_requirement():
    ids = filter_requirement_ids(_profile(), AnalysisFilter())
    assert ids == {'r1', 'r2', 'r3', 'r4', 'r5'}


# --- filter_requirement_ids: hierarchy + task ---------------------------

def test_filter_by_group_includes_descendants():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(group_id='g-top'))
    assert ids == {'r1', 'r2', 'r3'}  # r2/r3 are in g-child, a descendant of g-top


def test_filter_by_child_group_excludes_parent_and_siblings():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(group_id='g-child'))
    assert ids == {'r2', 'r3'}


def test_filter_by_sibling_group_is_disjoint():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(group_id='g-other'))
    assert ids == {'r4', 'r5'}


def test_filter_by_task():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(task='drowsiness'))
    assert ids == {'r3'}


def test_filter_combines_conditions_group_and_task():
    ids = filter_requirement_ids(_profile(), AnalysisFilter(
        conditions={'illumination': 'night'}, group_id='g-top', task='presence',
    ))
    assert ids == {'r1', 'r2'}  # r3 is in g-top's subtree but wrong task


# --- filter_results: status ----------------------------------------------

def test_filter_results_by_status():
    results = [_result('r1', 'pass'), _result('r2', 'fail'), _result('r3', 'na')]
    filtered = filter_results(results, {'r1', 'r2', 'r3'}, status='pass')
    assert [r.requirement_id for r in filtered] == ['r1']


def test_filter_results_intersects_requirement_ids_and_status():
    results = [_result('r1', 'pass'), _result('r2', 'pass'), _result('r3', 'pass')]
    filtered = filter_results(results, {'r1', 'r2'}, status='pass')
    assert {r.requirement_id for r in filtered} == {'r1', 'r2'}


def test_filter_results_no_status_filter_returns_all_in_id_set():
    results = [_result('r1', 'pass'), _result('r2', 'fail')]
    filtered = filter_results(results, {'r1', 'r2'}, status=None)
    assert {r.requirement_id for r in filtered} == {'r1', 'r2'}


# --- filter_requirement_results: composition -----------------------------

def test_filter_requirement_results_composes_condition_and_status_filters():
    profile = _profile()
    results = [
        _result('r1', 'pass'), _result('r2', 'fail'), _result('r3', 'pass'),
        _result('r4', 'pass'), _result('r5', 'na'),
    ]
    filtered = filter_requirement_results(
        profile, results, AnalysisFilter(conditions={'illumination': 'night'}, status='fail'),
    )
    # illumination=night -> {r1, r2}; status=fail -> only r2.
    assert [r.requirement_id for r in filtered] == ['r2']


def test_filter_requirement_results_empty_filter_returns_everything():
    profile = _profile()
    results = [_result(r.id, 'pass') for r in profile.requirements]
    filtered = filter_requirement_results(profile, results, AnalysisFilter())
    assert {r.requirement_id for r in filtered} == {'r1', 'r2', 'r3', 'r4', 'r5'}


# --- aggregate_requirement_results ---------------------------------------

def test_aggregate_all_pass():
    agg = aggregate_requirement_results([_result('r1', 'pass'), _result('r2', 'pass')])
    assert isinstance(agg, AggregateCoverage)
    assert (agg.pass_count, agg.fail_count, agg.na_count) == (2, 0, 0)
    assert agg.requirement_coverage == pytest.approx(1.0)
    assert agg.evidence_completeness == pytest.approx(1.0)
    assert agg.total == 2


def test_aggregate_all_fail():
    agg = aggregate_requirement_results([_result('r1', 'fail'), _result('r2', 'fail')])
    assert agg.requirement_coverage == pytest.approx(0.0)
    assert agg.evidence_completeness == pytest.approx(1.0)


def test_aggregate_all_na_is_none_coverage_not_zero():
    agg = aggregate_requirement_results([_result('r1', 'na'), _result('r2', 'na')])
    assert agg.requirement_coverage is None  # pass+fail == 0
    assert agg.evidence_completeness == pytest.approx(0.0)  # decided(0)/total(2)


def test_aggregate_empty_list_is_none_for_both():
    agg = aggregate_requirement_results([])
    assert agg.requirement_coverage is None
    assert agg.evidence_completeness is None
    assert agg.total == 0


def test_aggregate_mixed():
    agg = aggregate_requirement_results([_result('r1', 'pass'), _result('r2', 'fail'), _result('r3', 'na')])
    assert (agg.pass_count, agg.fail_count, agg.na_count) == (1, 1, 1)
    assert agg.requirement_coverage == pytest.approx(0.5)
    assert agg.evidence_completeness == pytest.approx(2 / 3)


# --- group_by_condition ---------------------------------------------------

def test_group_by_condition_buckets_by_observed_value():
    profile = _profile()
    requirement_by_id = {r.id: r for r in profile.requirements}
    results = [_result('r1', 'pass'), _result('r2', 'fail'), _result('r3', 'pass')]
    buckets = group_by_condition(results, requirement_by_id, 'illumination')
    # r1, r2 -> night; r3 -> day.
    assert set(buckets) == {'night', 'day'}
    assert (buckets['night'].pass_count, buckets['night'].fail_count) == (1, 1)
    assert (buckets['day'].pass_count, buckets['day'].fail_count) == (1, 0)


def test_group_by_condition_excludes_requirements_missing_the_key():
    profile = _profile()
    requirement_by_id = {r.id: r for r in profile.requirements}
    # r4/r5 don't declare 'illumination' at all.
    results = [_result(r.id, 'pass') for r in profile.requirements]
    buckets = group_by_condition(results, requirement_by_id, 'illumination')
    total_in_buckets = sum(b.total for b in buckets.values())
    assert total_in_buckets == 3  # r1, r2, r3 only - never r4/r5


def test_group_by_condition_unknown_key_produces_no_buckets():
    profile = _profile()
    requirement_by_id = {r.id: r for r in profile.requirements}
    results = [_result(r.id, 'pass') for r in profile.requirements]
    assert group_by_condition(results, requirement_by_id, 'does_not_exist') == {}


# --- cross_tabulate ------------------------------------------------------

def test_cross_tabulate_requires_both_keys_present():
    profile = _profile()
    requirement_by_id = {r.id: r for r in profile.requirements}
    results = [_result(r.id, 'pass') for r in profile.requirements]
    # Only r1 has both 'illumination' and 'smoke'.
    cells = cross_tabulate(results, requirement_by_id, 'illumination', 'smoke')
    assert set(cells) == {('night', True)}
    assert cells[('night', True)].pass_count == 1


def _crosstab_profile() -> EvaluationProfile:
    # Every requirement declares both illumination and eyewear, so all
    # four land in cells - a proper 2x2 grid, not a degenerate one-axis
    # case.
    requirements = [
        _requirement(id='c1', conditions={'illumination': 'day', 'eyewear': 'none'}),
        _requirement(id='c2', conditions={'illumination': 'day', 'eyewear': 'glasses'}),
        _requirement(id='c3', conditions={'illumination': 'night', 'eyewear': 'none'}),
        _requirement(id='c4', conditions={'illumination': 'night', 'eyewear': 'glasses'}),
    ]
    return EvaluationProfile(
        id='p4', name='Crosstab', version='1.0', groups=[RequirementGroup(id='g-top', name='Top')],
        requirements=requirements, created_at=datetime.now(timezone.utc),
    )


def test_cross_tabulate_populates_a_proper_2d_grid():
    profile = _crosstab_profile()
    requirement_by_id = {r.id: r for r in profile.requirements}
    results = [
        _result('c1', 'pass'), _result('c2', 'pass'),
        _result('c3', 'fail'), _result('c4', 'pass'),
    ]
    cells = cross_tabulate(results, requirement_by_id, 'illumination', 'eyewear')
    assert set(cells) == {('day', 'none'), ('day', 'glasses'), ('night', 'none'), ('night', 'glasses')}
    assert cells[('night', 'none')].fail_count == 1
    assert cells[('day', 'none')].pass_count == 1
    # Each cell's aggregate is exactly what aggregate_requirement_results
    # would produce for that same one-result subset - no separate formula.
    assert cells[('night', 'none')] == aggregate_requirement_results([_result('c3', 'fail')])


# --- failure_breakdown / top_failing_groups -------------------------------

def _hierarchy_profile() -> EvaluationProfile:
    # root
    #   g1 (Function A)
    #     g1-1 (Use Case A1) - requirements h1 (fail), h2 (pass)
    #   g2 (Function B) - requirement h3 (fail)
    groups = [
        RequirementGroup(id='g1', name='Function A'),
        RequirementGroup(id='g1-1', parent_id='g1', name='Use Case A1'),
        RequirementGroup(id='g2', name='Function B'),
    ]
    requirements = [
        _requirement(id='h1', group_id='g1-1', task='presence'),
        _requirement(id='h2', group_id='g1-1', task='presence'),
        _requirement(id='h3', group_id='g2', task='presence'),
    ]
    return EvaluationProfile(
        id='p3', name='Hierarchy', version='1.0', groups=groups, requirements=requirements,
        created_at=datetime.now(timezone.utc),
    )


def test_failure_breakdown_preserves_pass_and_na_counts_for_context():
    profile = _hierarchy_profile()
    results = [_result('h1', 'fail'), _result('h2', 'pass'), _result('h3', 'fail')]
    root = failure_breakdown(profile, results)

    g1_1 = next(g for g in root.children[0].children if g.group_id == 'g1-1')
    assert (g1_1.pass_count, g1_1.fail_count, g1_1.na_count) == (1, 1, 0)

    g2 = next(g for g in root.children if g.group_id == 'g2')
    assert (g2.pass_count, g2.fail_count) == (0, 1)

    assert (root.pass_count, root.fail_count) == (1, 2)


def test_top_failing_groups_sorted_descending_includes_zero_failure_groups():
    profile = _hierarchy_profile()
    results = [_result('h1', 'fail'), _result('h2', 'pass'), _result('h3', 'fail')]
    root = failure_breakdown(profile, results)
    ranked = top_failing_groups(root)
    fail_counts = [g.fail_count for g in ranked]
    assert fail_counts == sorted(fail_counts, reverse=True)
    # Every group appears, including g1 (0 own failures, but 1 via its
    # g1-1 child) and the root itself.
    assert len(ranked) == 4  # root, g1, g1-1, g2


# --- classify_na_reason (unit-level, hand-picked strings) -----------------

@pytest.mark.parametrize('reason,expected', [
    ("no session matches conditions {'illumination': 'night'} for task 'presence'", 'no_matching_evidence'),
    ("3 sessions match conditions {} - ambiguous, provide an explicit binding: ['s1', 's2', 's3']",
     'ambiguous_evidence'),
    ("session 's1' has multiple prediction sources: ['a', 'b'] - specify which one explicitly via a binding",
     'ambiguous_evidence'),
    ("metric 'recall_macro' is unavailable for this evidence (undefined)", 'missing_metric'),
    ("bound session 's1' has no evaluated result for this configuration/task", 'other'),
    ("something entirely unrecognized", 'other'),
])
def test_classify_na_reason(reason, expected):
    assert classify_na_reason(reason) == expected


# --- na_breakdown -----------------------------------------------------

def test_na_breakdown_counts_by_category():
    results = [
        _result('r1', 'na', reasons=["no session matches conditions {} for task 'presence'"]),
        _result('r2', 'na', reasons=["no session matches conditions {} for task 'presence'"]),
        _result('r3', 'na', reasons=["2 sessions match conditions {} - ambiguous, provide an explicit binding: []"]),
        _result('r4', 'pass'),  # not na - excluded
    ]
    assert na_breakdown(results) == {'no_matching_evidence': 2, 'ambiguous_evidence': 1}


# --- cross-layer: real select_evidence/evaluate_requirement scenarios -----
#
# Constructs every N/A reason through the actual v0.4 functions, not
# hand-typed strings - the guard the v0.5 architecture review's Q12/Q21
# specifically demanded. This is exactly the test that caught the
# multi-prediction-source wording gap while classify_na_reason was being
# written.

def _session(**overrides) -> Session:
    defaults = dict(
        id='s1', name='S', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        metadata={'illumination': 'night'},
    )
    return Session(**{**defaults, **overrides})


def _evaluation_result(**overrides) -> EvaluationResult:
    defaults = dict(
        id='er1', session_id='s1', configuration_id='cfg-rgb', task='presence',
        tolerance_ms=100.0, sample_count=100, matched_samples=95,
        unmatched_predictions=2, unmatched_ground_truth=5,
        metrics={'recall_macro': 0.94}, computed_at=datetime.now(timezone.utc),
    )
    return EvaluationResult(**{**defaults, **overrides})


def _na_result_from_selection(selection: EvidenceSelection, requirement: Requirement) -> RequirementResult:
    return evaluate_requirement(requirement, 'p1', '1.0', 'cfg-rgb', selection)


def test_na_reason_classification_matches_real_no_matching_evidence_scenario():
    requirement = _requirement(id='r1', conditions={'illumination': 'day'})  # no session matches
    selection = select_evidence(requirement, candidates=[])
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'no_matching_evidence'


def test_na_reason_classification_matches_real_ambiguous_session_scenario():
    requirement = _requirement(id='r1', conditions={'illumination': 'night'})
    s1, s2 = _session(id='s1'), _session(id='s2')
    candidates = [
        SessionCandidate(session=s1, evaluation_result=_evaluation_result(session_id='s1'), source_ids=['m']),
        SessionCandidate(session=s2, evaluation_result=_evaluation_result(session_id='s2'), source_ids=['m']),
    ]
    selection = select_evidence(requirement, candidates)
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'ambiguous_evidence'


def test_na_reason_classification_matches_real_ambiguous_source_scenario():
    requirement = _requirement(id='r1', conditions={'illumination': 'night'})
    candidate = SessionCandidate(session=_session(), evaluation_result=_evaluation_result(), source_ids=['a', 'b'])
    selection = select_evidence(requirement, [candidate])
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'ambiguous_evidence'


def test_na_reason_classification_matches_real_missing_metric_scenario():
    requirement = _requirement(
        id='r1', conditions={'illumination': 'night'},
        acceptance=[_criterion(metric='does_not_exist')],
    )
    candidate = SessionCandidate(session=_session(), evaluation_result=_evaluation_result(), source_ids=['a'])
    selection = select_evidence(requirement, [candidate])
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'missing_metric'


def test_na_reason_classification_matches_real_bound_session_not_found_scenario():
    requirement = _requirement(id='r1', conditions={'illumination': 'day'})  # would never match by discovery
    selection = select_evidence(requirement, candidates=[], binding=EvidenceBinding(session_id='does-not-exist'))
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'other'


def test_na_reason_classification_matches_real_unknown_source_binding_scenario():
    requirement = _requirement(id='r1', conditions={})
    candidate = SessionCandidate(session=_session(), evaluation_result=_evaluation_result(), source_ids=['a'])
    selection = select_evidence(
        requirement, [candidate], binding=EvidenceBinding(session_id='s1', source_id='does-not-exist'),
    )
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'other'


def test_na_reason_classification_matches_real_no_predictions_found_scenario():
    requirement = _requirement(id='r1', conditions={})
    candidate = SessionCandidate(session=_session(), evaluation_result=_evaluation_result(), source_ids=[])
    selection = select_evidence(requirement, [candidate])
    result = _na_result_from_selection(selection, requirement)
    assert result.status == 'na'
    assert classify_na_reason(result.reasons[0]) == 'other'
