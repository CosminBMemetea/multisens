"""Phase 36 addition: POST /api/profiles/{id}/coverage tests. The
`client` fixture lives in conftest.py. No phase's issue explicitly scoped
this route (Phase 32 was create/list/get only, Phase 35 was pure domain
logic) - added here as the connective tissue Phase 37's coverage matrix
UI will need to call, flagged in the Phase 35 completion report."""
import pytest


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
    # 5 ground-truth points, shared by every configuration seeded against
    # this session - a config's accuracy then depends only on which of
    # its own predictions are wrong.
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 300.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 400.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201, resp.text


def _seed_predictions(client, session_id='s1', source_id='rgb_model', sensor_ids=None) -> None:
    # 4/5 correct: wrong at the 400ms point.
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': source_id, 'sensor_ids': sensor_ids or ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 101.0, 'source_id': source_id, 'sensor_ids': sensor_ids or ['rgb'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 201.0, 'source_id': source_id, 'sensor_ids': sensor_ids or ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 301.0, 'source_id': source_id, 'sensor_ids': sensor_ids or ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 401.0, 'source_id': source_id, 'sensor_ids': sensor_ids or ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},  # wrong: gt is 'absent'
    ]})
    assert resp.status_code == 201, resp.text


def _evaluate(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _seed_and_evaluate(client, session_id='s1', source_id='rgb_model', sensor_ids=None) -> None:
    _seed_ground_truth(client, session_id)
    _seed_predictions(client, session_id, source_id, sensor_ids)
    _evaluate(client, session_id)


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


def test_coverage_unknown_profile_404(client):
    resp = client.post('/api/profiles/does-not-exist/coverage', json={})
    assert resp.status_code == 404


def test_coverage_unknown_session_filter_404(client):
    _create_profile(client)
    resp = client.post('/api/profiles/p1/coverage', json={'session_ids': ['does-not-exist']})
    assert resp.status_code == 404


def test_coverage_full_flow_hand_verified(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200, resp.text
    coverages = resp.json()['configuration_coverages']
    assert len(coverages) == 1
    coverage = coverages[0]
    assert coverage['configuration_id'] == 'cfg-rgb'

    result = coverage['requirement_results'][0]
    assert result['requirement_id'] == 'req-001'
    # 4/5 correct = 0.8 accuracy >= 0.7 threshold - pass.
    assert result['status'] == 'pass'
    assert result['criteria'][0]['observed'] == pytest.approx(0.8)
    assert result['evidence']['session_id'] == 's1'
    assert result['evidence']['source_id'] == 'rgb_model'

    assert coverage['root']['pass_count'] == 1
    assert coverage['root']['fail_count'] == 0
    assert coverage['root']['na_count'] == 0
    assert coverage['root']['requirement_coverage'] == pytest.approx(1.0)
    assert coverage['root']['evidence_completeness'] == pytest.approx(1.0)


def test_coverage_wrong_conditions_is_na(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'day'})  # profile requires 'night'
    _seed_and_evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200
    result = resp.json()['configuration_coverages'][0]['requirement_results'][0]
    assert result['status'] == 'na'
    assert result['evidence'] is None
    assert any('no session matches conditions' in r for r in result['reasons'])


def test_coverage_explicit_configuration_id_with_no_evidence_anywhere_is_all_na(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/coverage', json={'configuration_ids': ['cfg-thermal']})
    assert resp.status_code == 200
    coverage = resp.json()['configuration_coverages'][0]
    assert coverage['configuration_id'] == 'cfg-thermal'
    assert coverage['requirement_results'][0]['status'] == 'na'
    assert coverage['root']['requirement_coverage'] is None


def test_coverage_ambiguous_evidence_resolved_via_binding(client):
    _create_scenario(client)
    _create_session(client, session_id='s1', metadata={'illumination': 'night'})
    _create_session(client, session_id='s2', metadata={'illumination': 'night'})
    _seed_and_evaluate(client, session_id='s1')
    _seed_and_evaluate(client, session_id='s2')
    _create_profile(client)

    without_binding = client.post('/api/profiles/p1/coverage', json={})
    result = without_binding.json()['configuration_coverages'][0]['requirement_results'][0]
    assert result['status'] == 'na'
    assert any('ambiguous' in r for r in result['reasons'])

    with_binding = client.post('/api/profiles/p1/coverage', json={
        'requirement_bindings': {'req-001': {'session_id': 's2'}},
    })
    resolved = with_binding.json()['configuration_coverages'][0]['requirement_results'][0]
    assert resolved['status'] == 'pass'
    assert resolved['evidence']['session_id'] == 's2'


def test_coverage_multiple_configurations_each_get_own_coverage(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions(client, source_id='rgb_model', sensor_ids=['rgb'])
    _seed_predictions(client, source_id='thermal_model', sensor_ids=['thermal'])
    _evaluate(client)
    _create_profile(client)

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200
    coverages = {c['configuration_id']: c for c in resp.json()['configuration_coverages']}
    assert set(coverages) == {'cfg-rgb', 'cfg-thermal'}
    assert coverages['cfg-rgb']['requirement_results'][0]['evidence']['source_id'] == 'rgb_model'
    assert coverages['cfg-thermal']['requirement_results'][0]['evidence']['source_id'] == 'thermal_model'


def test_coverage_session_ids_filter_excludes_other_sessions(client):
    _create_scenario(client)
    _create_session(client, session_id='s1', metadata={'illumination': 'night'})
    _create_session(client, session_id='s2', metadata={'illumination': 'night'})
    _seed_and_evaluate(client, session_id='s1')
    _seed_and_evaluate(client, session_id='s2')
    _create_profile(client)

    resp = client.post('/api/profiles/p1/coverage', json={'session_ids': ['s2']})
    result = resp.json()['configuration_coverages'][0]['requirement_results'][0]
    assert result['evidence']['session_id'] == 's2'
