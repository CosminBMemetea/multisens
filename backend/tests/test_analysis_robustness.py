"""Phase 51: analysis-layer (v0.5) robustness. Same discipline as Phase
28/40's comparison/profile robustness suites applied to the /facets and
/analysis endpoints - closes the specific gaps in issue #52's checklist.
Each test hits the real API through `client` (conftest.py), not the
domain functions directly - test_analysis.py already covers those in
isolation.
"""
import time


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1', metadata=None) -> None:
    resp = client.post('/api/sessions', json={
        'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id,
        'metadata': metadata or {},
    })
    assert resp.status_code == 201, resp.text


def _seed_ground_truth(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201, resp.text


def _seed_predictions(client, session_id='s1', source_id='rgb_model') -> None:
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': source_id, 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 101.0, 'source_id': source_id, 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201, resp.text


def _seed_and_evaluate(client, session_id='s1') -> None:
    _seed_ground_truth(client, session_id)
    _seed_predictions(client, session_id)
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _profile_body(**overrides) -> dict:
    body = {
        'id': 'p1', 'name': 'Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{
            'id': 'req-001', 'group_id': 'g1', 'name': 'Variant 1', 'task': 'presence',
            'conditions': {'illumination': 'night'},
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}],
        }],
        **overrides,
    }
    return body


# --- zero condition dimensions - explorer degrades cleanly -----------------

def test_profile_with_no_conditions_has_empty_facets_and_analysis_still_works(client):
    body = _profile_body(requirements=[{
        'id': 'req-001', 'group_id': 'g1', 'name': 'No conditions', 'task': 'presence',
        'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}],
    }])
    assert client.post('/api/profiles', json=body).status_code == 201

    resp = client.get('/api/profiles/p1/facets')
    assert resp.status_code == 200
    assert resp.json() == []

    # No facets to group by - group_by naming a dimension that doesn't
    # exist anywhere just produces an empty groups list, not an error.
    resp = client.post('/api/profiles/p1/analysis', json={'group_by': ['illumination']})
    assert resp.status_code == 200, resp.text
    assert resp.json()['configurations'] == []  # no evaluated configuration yet either

    _create_scenario(client)
    _create_session(client)
    _seed_and_evaluate(client)
    resp = client.post('/api/profiles/p1/analysis', json={'group_by': ['illumination']})
    assert resp.status_code == 200, resp.text
    config = resp.json()['configurations'][0]
    assert config['groups'] == []
    assert len(config['requirement_results']) == 1  # the unfiltered population is still there


# --- filter naming a condition key no requirement declares ------------------

def test_filter_on_undeclared_condition_key_is_zero_matches_not_error(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201

    resp = client.post(
        '/api/profiles/p1/analysis', json={'filters': {'conditions': {'weather': 'rain'}}},
    )
    assert resp.status_code == 200, resp.text
    config = resp.json()['configurations'][0]
    assert config['requirement_results'] == []
    assert config['summary'] == {
        'pass_count': 0, 'fail_count': 0, 'na_count': 0,
        'requirement_coverage': None, 'evidence_completeness': None,
    }


# --- mixed value types for the same condition key --------------------------

def test_facets_and_filters_distinguish_boolean_from_string_same_key(client):
    # A boolean True and the string "true" are genuinely different
    # condition values, not a bug - same type-sensitive rule
    # conditions_are_subset already enforces for evidence matching
    # (v0.4), now exercised through discover_facets/filter_requirement_ids.
    body = _profile_body(requirements=[
        {'id': 'req-bool', 'group_id': 'g1', 'name': 'Bool', 'task': 'presence',
         'conditions': {'flag': True},
         'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
        {'id': 'req-str', 'group_id': 'g1', 'name': 'Str', 'task': 'presence',
         'conditions': {'flag': 'true'},
         'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
    ])
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201, resp.text
    # No type coercion happened at profile-creation time either.
    conditions_by_req = {r['id']: r['conditions']['flag'] for r in resp.json()['requirements']}
    assert conditions_by_req['req-bool'] is True
    assert conditions_by_req['req-str'] == 'true'

    resp = client.get('/api/profiles/p1/facets')
    assert resp.status_code == 200
    facet = next(f for f in resp.json() if f['key'] == 'flag')
    values = {v['value']: v['requirement_count'] for v in facet['values']}
    assert values == {True: 1, 'true': 1}

    _create_scenario(client)
    _create_session(client)
    _seed_and_evaluate(client)

    resp = client.post('/api/profiles/p1/analysis', json={'filters': {'conditions': {'flag': True}}})
    matched = {r['requirement_id'] for r in resp.json()['configurations'][0]['requirement_results']}
    assert matched == {'req-bool'}

    resp = client.post('/api/profiles/p1/analysis', json={'filters': {'conditions': {'flag': 'true'}}})
    matched = {r['requirement_id'] for r in resp.json()['configurations'][0]['requirement_results']}
    assert matched == {'req-str'}


# --- large profile: interactive filtering stays responsive -----------------

def test_large_profile_facets_and_analysis_stay_responsive(client):
    # Low-thousands of requirements, split across two condition values -
    # the client-side re-bucketing boundary (architecture review Q19)
    # only works if the server side itself doesn't degrade badly first.
    requirement_count = 2000
    requirements = [
        {
            'id': f'req-{i:05d}', 'group_id': 'g1', 'name': f'Requirement {i}', 'task': 'presence',
            'conditions': {'dim': 'a' if i % 2 == 0 else 'b'},
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}],
        }
        for i in range(requirement_count)
    ]
    body = _profile_body(requirements=requirements)
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201, resp.text

    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)

    started = time.perf_counter()
    facets_resp = client.get('/api/profiles/p1/facets')
    analysis_resp = client.post('/api/profiles/p1/analysis', json={'group_by': ['dim']})
    elapsed = time.perf_counter() - started

    assert facets_resp.status_code == 200
    assert analysis_resp.status_code == 200, analysis_resp.text
    assert elapsed < 5.0, f'facets + analysis took {elapsed:.2f}s for {requirement_count} requirements'

    dim_facet = next(f for f in facets_resp.json() if f['key'] == 'dim')
    values = {v['value']: v['requirement_count'] for v in dim_facet['values']}
    assert values == {'a': requirement_count // 2, 'b': requirement_count // 2}

    config = analysis_resp.json()['configurations'][0]
    assert len(config['requirement_results']) == requirement_count
    groups = {tuple(g['key']): g['aggregate'] for g in config['groups']}
    assert set(groups) == {('a',), ('b',)}
    # The session's metadata never declares 'dim' at all, so every
    # requirement is N/A - irrelevant to this test, which only cares that
    # bucketing at this scale is correct and fast, not about pass/fail.
    for aggregate in groups.values():
        assert aggregate['na_count'] == requirement_count // 2
        assert aggregate['pass_count'] == 0
        assert aggregate['fail_count'] == 0


# --- old v0.4-only profile, no v0.5-specific usage --------------------------

def test_analysis_endpoints_work_unchanged_against_an_ordinary_v04_profile(client):
    # An entirely ordinary profile, built the same way a v0.4-only client
    # would - no opt-in flag or migration needed for v0.5's analysis
    # layer to work against it.
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201

    resp = client.get('/api/profiles/p1/facets')
    assert resp.status_code == 200
    assert [f['key'] for f in resp.json()] == ['illumination']

    resp = client.post('/api/profiles/p1/analysis', json={})
    assert resp.status_code == 200, resp.text
    result = resp.json()['configurations'][0]['requirement_results'][0]
    assert result['status'] == 'pass'  # 2/2 = 1.0 >= 0.5


# --- missing Session.metadata entirely, through the analysis layer ---------

def test_analysis_against_session_with_no_metadata_is_na_not_crash(client):
    # A legacy pre-v0.4 session (metadata defaults to {}, no conditions
    # ever set) - already a v0.4 /coverage case, re-confirmed here through
    # /analysis and na_breakdown specifically.
    _create_scenario(client)
    _create_session(client, session_id='legacy-s1', metadata={})
    _seed_and_evaluate(client, session_id='legacy-s1')
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201

    resp = client.post('/api/profiles/p1/analysis', json={})
    assert resp.status_code == 200, resp.text
    config = resp.json()['configurations'][0]
    result = config['requirement_results'][0]
    assert result['status'] == 'na'
    assert any('no session matches conditions' in r for r in result['reasons'])
    assert config['na_breakdown'] == {'no_matching_evidence': 1}


# --- /analysis malformed-request shapes -------------------------------------

def test_analysis_wrong_type_for_configuration_ids_422(client):
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201
    resp = client.post('/api/profiles/p1/analysis', json={'configuration_ids': 'cfg-rgb'})  # string, not list
    assert resp.status_code == 422


def test_analysis_wrong_type_for_filters_conditions_422(client):
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201
    resp = client.post('/api/profiles/p1/analysis', json={'filters': {'conditions': ['night']}})  # list, not dict
    assert resp.status_code == 422


def test_analysis_invalid_status_enum_value_422(client):
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201
    resp = client.post('/api/profiles/p1/analysis', json={'filters': {'status': 'maybe'}})
    assert resp.status_code == 422


def test_analysis_non_string_group_by_element_422(client):
    assert client.post('/api/profiles', json=_profile_body()).status_code == 201
    resp = client.post('/api/profiles/p1/analysis', json={'group_by': [123]})
    assert resp.status_code == 422
