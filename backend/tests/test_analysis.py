"""Phase 42: AnalysisFilter/Facet/FacetValue model shape tests. Field-
level construction only - facet discovery, filtering, grouping, and
cross-tab are not implemented or tested here (Phase 43/44)."""
from app.domain.analysis import AnalysisFilter, Facet, FacetValue


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
