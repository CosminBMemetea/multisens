"""Phase 45: analysis API tests - GET /api/profiles/{id}/facets,
POST /api/profiles/{id}/analysis, GET /api/sessions/{id}/profile-usage.
The `client` fixture lives in conftest.py."""


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
        {'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 300.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 400.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201, resp.text


def _seed_predictions(client, session_id='s1', source_id='rgb_model', sensor_ids=None, all_correct=True) -> None:
    # Ground truth (see _seed_ground_truth) is at 0/100/200/300/400ms:
    # present, absent, present, present, absent. Predictions land 1ms
    # after each - comfortably inside the default 100ms tolerance for
    # every point, not clustered near just the first one.
    labels = ['present', 'absent', 'present', 'present', 'absent']
    if not all_correct:
        labels[-1] = 'present'  # flip the last one wrong -> 4/5 = 0.8 accuracy
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': i * 100.0 + 1.0, 'source_id': source_id, 'sensor_ids': sensor_ids or ['rgb'],
         'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(labels)
    ]})
    assert resp.status_code == 201, resp.text


def _evaluate(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _create_profile(client, **overrides) -> dict:
    body = {
        'id': 'p1', 'name': 'Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{
            'id': 'req-001', 'group_id': 'g1', 'name': 'Variant 1', 'task': 'presence',
            'conditions': {'illumination': 'night'},
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}],
        }],
        **overrides,
    }
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _two_dimension_profile(**overrides) -> dict:
    body = {
        'id': 'p1', 'name': 'Two Dimension Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [
            {
                'id': 'req-day-none', 'group_id': 'g1', 'name': 'Day/None', 'task': 'presence',
                'conditions': {'illumination': 'day', 'eyewear': 'none'},
                'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}],
            },
            {
                'id': 'req-night-glasses', 'group_id': 'g1', 'name': 'Night/Glasses', 'task': 'presence',
                'conditions': {'illumination': 'night', 'eyewear': 'glasses'},
                'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}],
            },
        ],
        **overrides,
    }
    return body


# --- /facets ---------------------------------------------------------------

def test_facets_unknown_profile_404(client):
    resp = client.get('/api/profiles/does-not-exist/facets')
    assert resp.status_code == 404


def test_facets_discovered_from_profile_requirements(client):
    _create_profile(client)
    resp = client.get('/api/profiles/p1/facets')
    assert resp.status_code == 200
    facets = {f['key']: f for f in resp.json()}
    assert 'illumination' in facets
    assert facets['illumination']['values'] == [{'value': 'night', 'requirement_count': 1}]


def test_facets_empty_for_profile_with_no_conditions(client):
    body = {
        'id': 'p1', 'name': 'No Conditions', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'G1'}],
        'requirements': [{
            'id': 'r1', 'group_id': 'g1', 'name': 'R1', 'task': 'presence',
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}],
        }],
    }
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201, resp.text
    resp = client.get('/api/profiles/p1/facets')
    assert resp.json() == []


# --- /analysis: basic filtered summary ------------------------------------

def test_analysis_unknown_profile_404(client):
    resp = client.post('/api/profiles/does-not-exist/analysis', json={})
    assert resp.status_code == 404


def test_analysis_no_filters_summary_matches_full_population(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions(client, all_correct=False)  # 4/5 = 0.8 accuracy
    _evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/analysis', json={})
    assert resp.status_code == 200, resp.text
    configs = {c['configuration_id']: c for c in resp.json()['configurations']}
    summary = configs['cfg-rgb']['summary']
    assert summary['pass_count'] == 1  # 0.8 >= 0.7
    assert summary['fail_count'] == 0
    assert len(configs['cfg-rgb']['requirement_results']) == 1


def test_analysis_condition_filter_excludes_non_matching_requirements(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions(client)
    _evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/analysis', json={'filters': {'conditions': {'illumination': 'day'}}})
    assert resp.status_code == 200
    config = resp.json()['configurations'][0]
    assert config['summary'] == {
        'pass_count': 0, 'fail_count': 0, 'na_count': 0,
        'requirement_coverage': None, 'evidence_completeness': None,
    }
    assert config['requirement_results'] == []


def test_analysis_status_filter(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions(client)  # all correct -> pass
    _evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/analysis', json={'filters': {'status': 'fail'}})
    assert resp.status_code == 200
    assert resp.json()['configurations'][0]['requirement_results'] == []


# --- /analysis: failure_root / na_breakdown (Phase 48) ---------------------

def test_analysis_failure_root_reflects_a_real_failure(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions(client, all_correct=False)  # 4/5 = 0.8, still >= 0.7 -> pass
    _evaluate(client)
    # req-001's own threshold (0.7) passes at 0.8 - build a stricter profile
    # so this scenario produces a real, hand-traceable failure instead.
    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'Strict', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{
            'id': 'req-001', 'group_id': 'g1', 'name': 'Variant 1', 'task': 'presence',
            'conditions': {'illumination': 'night'},
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.95}],
        }],
    })
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/profiles/p1/analysis', json={})
    assert resp.status_code == 200, resp.text
    config = resp.json()['configurations'][0]
    assert config['failure_root']['fail_count'] == 1
    assert config['failure_root']['pass_count'] == 0
    assert config['failure_root']['na_count'] == 0
    # failure_breakdown deliberately isn't pre-filtered to fail-only - the
    # group's own child list (if any) is still present, not stripped out.
    assert config['failure_root']['group_id'] is None
    assert config['na_breakdown'] == {}


def test_analysis_na_breakdown_classifies_no_matching_evidence(client):
    # A configuration exists (so it shows up in the response at all), but
    # its only session is illumination=day - req-001 (illumination=night)
    # has nothing matching to select as evidence, so this must classify as
    # 'no_matching_evidence' via the real classify_na_reason path, not a
    # hand-typed string re-implemented in this test.
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'day'})
    _seed_ground_truth(client)
    _seed_predictions(client)
    _evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/analysis', json={})
    assert resp.status_code == 200, resp.text
    config = resp.json()['configurations'][0]
    assert config['na_breakdown'] == {'no_matching_evidence': 1}
    assert config['failure_root']['na_count'] == 1


# --- /analysis: group_by --------------------------------------------------

def test_analysis_group_by_zero_dims_has_no_groups(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions(client)
    _evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/analysis', json={'group_by': []})
    assert resp.json()['configurations'][0]['groups'] == []


def test_analysis_group_by_one_dim_breakdown(client):
    _create_scenario(client)
    _create_session(client, session_id='s-day', metadata={'illumination': 'day', 'eyewear': 'none'})
    _create_session(client, session_id='s-night', metadata={'illumination': 'night', 'eyewear': 'glasses'})
    for sid in ('s-day', 's-night'):
        _seed_ground_truth(client, session_id=sid)
        _seed_predictions(client, session_id=sid)
        _evaluate(client, session_id=sid)
    resp = client.post('/api/profiles', json=_two_dimension_profile())
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/profiles/p1/analysis', json={'group_by': ['illumination']})
    assert resp.status_code == 200, resp.text
    groups = {tuple(g['key']): g['aggregate'] for g in resp.json()['configurations'][0]['groups']}
    assert set(groups) == {('day',), ('night',)}
    assert groups[('day',)]['pass_count'] == 1
    assert groups[('night',)]['pass_count'] == 1


def test_analysis_group_by_two_dims_crosstab(client):
    _create_scenario(client)
    _create_session(client, session_id='s-day', metadata={'illumination': 'day', 'eyewear': 'none'})
    _create_session(client, session_id='s-night', metadata={'illumination': 'night', 'eyewear': 'glasses'})
    for sid in ('s-day', 's-night'):
        _seed_ground_truth(client, session_id=sid)
        _seed_predictions(client, session_id=sid)
        _evaluate(client, session_id=sid)
    resp = client.post('/api/profiles', json=_two_dimension_profile())
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/profiles/p1/analysis', json={'group_by': ['illumination', 'eyewear']})
    assert resp.status_code == 200, resp.text
    cells = {tuple(g['key']): g['aggregate'] for g in resp.json()['configurations'][0]['groups']}
    assert set(cells) == {('day', 'none'), ('night', 'glasses')}
    assert cells[('day', 'none')]['pass_count'] == 1
    assert cells[('night', 'glasses')]['pass_count'] == 1


def test_analysis_group_by_more_than_two_dims_422(client):
    _create_profile(client)
    resp = client.post('/api/profiles/p1/analysis', json={'group_by': ['a', 'b', 'c']})
    assert resp.status_code == 422


# --- /analysis: malformed / session filtering -----------------------------

def test_analysis_unknown_session_filter_404(client):
    _create_profile(client)
    resp = client.post('/api/profiles/p1/analysis', json={'session_ids': ['does-not-exist']})
    assert resp.status_code == 404


def test_analysis_wrong_type_for_group_by_422(client):
    _create_profile(client)
    resp = client.post('/api/profiles/p1/analysis', json={'group_by': 'illumination'})  # string, not list
    assert resp.status_code == 422


# --- /profile-usage ----------------------------------------------------

def test_profile_usage_unknown_session_404(client):
    resp = client.get('/api/sessions/does-not-exist/profile-usage')
    assert resp.status_code == 404


def test_profile_usage_lists_matching_profile_and_requirements(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night', 'eyewear': 'glasses'})
    _create_profile(client)  # req-001 needs illumination=night

    resp = client.get('/api/sessions/s1/profile-usage')
    assert resp.status_code == 200, resp.text
    usage = resp.json()
    assert len(usage) == 1
    assert usage[0]['profile_id'] == 'p1'
    assert usage[0]['requirement_ids'] == ['req-001']


def test_profile_usage_empty_when_no_requirement_matches(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'day'})
    _create_profile(client)  # req-001 needs illumination=night

    resp = client.get('/api/sessions/s1/profile-usage')
    assert resp.json() == []


def test_profile_usage_shows_candidacy_not_just_resolved_evidence(client):
    # Two sessions both match the requirement's conditions - ambiguous
    # for /coverage's evidence selection (neither gets resolved), but
    # both are still legitimate "used by" candidates for auditing.
    _create_scenario(client)
    _create_session(client, session_id='s1', metadata={'illumination': 'night'})
    _create_session(client, session_id='s2', metadata={'illumination': 'night'})
    _create_profile(client)

    usage_s1 = client.get('/api/sessions/s1/profile-usage').json()
    usage_s2 = client.get('/api/sessions/s2/profile-usage').json()
    assert usage_s1[0]['requirement_ids'] == ['req-001']
    assert usage_s2[0]['requirement_ids'] == ['req-001']
