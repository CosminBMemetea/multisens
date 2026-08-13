"""Phase 42: AnalysisFilter/Facet/FacetValue model shape tests. Field-
level construction only.

Phase 43: facet discovery + filtering engine tests - discover_facets,
filter_requirement_ids, filter_results, and the filter_requirement_results
composition. Grouping/cross-tab are not implemented or tested here
(Phase 44)."""
from datetime import datetime, timezone

from app.domain.analysis import (
    AnalysisFilter,
    Facet,
    FacetValue,
    discover_facets,
    filter_requirement_ids,
    filter_requirement_results,
    filter_results,
)
from app.domain.coverage import RequirementResult
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
