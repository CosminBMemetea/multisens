"""Phase 22: comparison API tests. The `client` fixture lives in
conftest.py."""
import pytest


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _seed_and_evaluate(client, session_id='s1'):
    _create_scenario(client)
    _create_session(client, session_id=session_id)

    client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 300.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 400.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    # cfg-rgb: misses the 300ms point, gets the 100ms point wrong -> 3/4 correct
    client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 101.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 201.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 401.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    # cfg-rgb-thermal: matches all 5, all correct
    client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': 2.0, 'source_id': 'fusion_model', 'sensor_ids': ['rgb', 'thermal'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 102.0, 'source_id': 'fusion_model', 'sensor_ids': ['rgb', 'thermal'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 202.0, 'source_id': 'fusion_model', 'sensor_ids': ['rgb', 'thermal'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 302.0, 'source_id': 'fusion_model', 'sensor_ids': ['rgb', 'thermal'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 402.0, 'source_id': 'fusion_model', 'sensor_ids': ['rgb', 'thermal'],
         'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


# --- GET /configurations ------------------------------------------------

def test_list_configurations_before_evaluate_has_null_sample_counts(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 0.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    resp = client.get('/api/sessions/s1/configurations', params={'task': 'presence'})
    assert resp.status_code == 200
    configs = resp.json()
    assert len(configs) == 1
    assert configs[0]['configuration_id'] == 'cfg-rgb'
    assert configs[0]['sensor_ids'] == ['rgb']
    assert configs[0]['source_ids'] == ['rgb_model']
    assert configs[0]['prediction_count'] == 1
    assert configs[0]['sample_count'] is None
    assert configs[0]['matched_samples'] is None


def test_list_configurations_after_evaluate_has_sample_counts(client):
    _seed_and_evaluate(client)
    resp = client.get('/api/sessions/s1/configurations', params={'task': 'presence'})
    configs = {c['configuration_id']: c for c in resp.json()}
    assert configs['cfg-rgb']['sample_count'] == 5
    assert configs['cfg-rgb']['matched_samples'] == 4
    assert configs['cfg-rgb-thermal']['matched_samples'] == 5


def test_list_configurations_unknown_session_404(client):
    resp = client.get('/api/sessions/nope/configurations', params={'task': 'presence'})
    assert resp.status_code == 404


# --- POST /compare - errors -------------------------------------------------

def test_compare_unknown_session_404(client):
    resp = client.post('/api/sessions/nope/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
    })
    assert resp.status_code == 404


def test_compare_negative_tolerance_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb', 'tolerance_ms': -1,
    })
    assert resp.status_code == 422


def test_compare_baseline_not_evaluated_422(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 0.0, 'source_id': 'm', 'sensor_ids': ['rgb'], 'task': 'presence', 'value': {'label': 'x'}},
    ]})
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
    })
    assert resp.status_code == 422
    assert 'not been evaluated' in resp.json()['detail']


def test_compare_named_candidate_not_evaluated_422(client):
    _seed_and_evaluate(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-does-not-exist'],
    })
    assert resp.status_code == 422
    assert 'not been evaluated' in resp.json()['detail']


def test_compare_ambiguous_source_returns_422_with_available_list(client):
    _seed_and_evaluate(client)
    # Add a second, distinct source for cfg-rgb under the same task.
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 500.0, 'source_id': 'rgb_model_v2', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-rgb-thermal'],
    })
    assert resp.status_code == 422
    detail = resp.json()['detail']
    assert 'multiple prediction sources' in detail
    assert 'rgb_model' in detail and 'rgb_model_v2' in detail


def test_compare_explicit_source_id_resolves_ambiguity(client):
    _seed_and_evaluate(client)
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 500.0, 'source_id': 'rgb_model_v2', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'baseline_source_id': 'rgb_model',
        'candidate_configuration_ids': ['cfg-rgb-thermal'],
    })
    assert resp.status_code == 200, resp.text


def test_compare_unknown_source_id_422(client):
    _seed_and_evaluate(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'baseline_source_id': 'does-not-exist',
        'candidate_configuration_ids': ['cfg-rgb-thermal'],
    })
    assert resp.status_code == 422
    assert 'not found' in resp.json()['detail']


# --- POST /compare - success -------------------------------------------------

def test_compare_auto_discovery_excludes_baseline_and_unevaluated(client):
    _seed_and_evaluate(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
    })
    assert resp.status_code == 200
    comparisons = resp.json()['comparisons']
    candidate_ids = [c['candidate_configuration_id'] for c in comparisons]
    assert candidate_ids == ['cfg-rgb-thermal']  # only other evaluated config


def test_compare_full_flow_hand_verified_numbers(client):
    _seed_and_evaluate(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-rgb-thermal'],
    })
    assert resp.status_code == 200
    comparison = resp.json()['comparisons'][0]

    assert comparison['added_sensors'] == ['thermal']
    assert comparison['removed_sensors'] == []
    assert comparison['relationship'] == 'direct_addition'
    assert comparison['baseline_source_id'] == 'rgb_model'
    assert comparison['candidate_source_id'] == 'fusion_model'

    # reported: baseline 4/5 matched (80% coverage), candidate 5/5 (100%)
    assert comparison['reported']['baseline']['coverage'] == pytest.approx(0.8)
    assert comparison['reported']['candidate']['coverage'] == pytest.approx(1.0)
    assert comparison['reported']['coverage_delta_pp'] == pytest.approx(20.0)
    assert comparison['reported']['matched_sample_delta'] == 1
    assert comparison['reported']['metric_deltas']['accuracy']['absolute'] == pytest.approx(0.25)

    # common-set: intersection is baseline's 4 matched points
    assert comparison['common_set']['common_sample_count'] == 4
    assert comparison['common_set']['baseline']['metrics']['accuracy'] == pytest.approx(0.75)
    assert comparison['common_set']['candidate']['metrics']['accuracy'] == pytest.approx(1.0)

    # both the low-common-sample-count and coverage-difference warnings fire
    assert comparison['validity']['status'] == 'valid_with_warnings'
    assert len(comparison['validity']['reasons']) == 2


def test_compare_self_comparison_is_invalid(client):
    _seed_and_evaluate(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-rgb'],
    })
    assert resp.status_code == 200
    comparison = resp.json()['comparisons'][0]
    assert comparison['validity']['status'] == 'invalid'
    assert 'same configuration' in comparison['validity']['reasons'][0]


def test_compare_custom_tolerance_is_recorded(client):
    _seed_and_evaluate(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-rgb-thermal'], 'tolerance_ms': 5.0,
    })
    assert resp.status_code == 200
    assert resp.json()['comparisons'][0]['tolerance_ms'] == 5.0
