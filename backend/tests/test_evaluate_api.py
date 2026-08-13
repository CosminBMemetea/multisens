"""Evaluation-run API tests (Phase 14): POST /evaluate wires the Phase 13
matching+metric engine to persisted data and stores the result; GET
/evaluation retrieves it. The `client` fixture lives in conftest.py.
"""
import pytest


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _seed(client, session_id='s1'):
    _create_scenario(client)
    _create_session(client, session_id=session_id)

    client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        # rgb: all three correct
        {'timestamp_ms': 1.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 101.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 199.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        # depth: gets the first one wrong
        {'timestamp_ms': 2.0, 'source_id': 'depth_model', 'sensor_ids': ['depth'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 102.0, 'source_id': 'depth_model', 'sensor_ids': ['depth'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 198.0, 'source_id': 'depth_model', 'sensor_ids': ['depth'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})


def test_evaluate_computes_and_persists_results_for_all_configurations(client):
    _seed(client)

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200
    results = {r['configuration_id']: r for r in resp.json()}

    assert set(results) == {'cfg-rgb', 'cfg-depth'}
    assert results['cfg-rgb']['metrics']['accuracy'] == 1.0
    assert results['cfg-rgb']['matched_samples'] == 3
    assert results['cfg-rgb']['sample_count'] == 3
    assert results['cfg-depth']['metrics']['accuracy'] == pytest.approx(2 / 3)

    persisted = client.get('/api/sessions/s1/evaluation').json()
    assert {r['configuration_id'] for r in persisted} == {'cfg-rgb', 'cfg-depth'}


def test_evaluate_records_tolerance_used(client):
    _seed(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'tolerance_ms': 5.0})
    for result in resp.json():
        assert result['tolerance_ms'] == 5.0


def test_evaluate_restricted_to_named_configurations(client):
    _seed(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'configuration_ids': ['cfg-rgb']})
    assert resp.status_code == 200
    results = resp.json()
    assert [r['configuration_id'] for r in results] == ['cfg-rgb']


def test_evaluate_rerun_overwrites_not_duplicates(client):
    _seed(client)
    client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    persisted = client.get('/api/sessions/s1/evaluation').json()
    # Still exactly one row per (configuration, task), not accumulated.
    assert len(persisted) == 2


def test_evaluate_with_no_predictions_returns_na_not_zero(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})

    # No predictions ingested at all, and no configuration named explicitly
    # -> nothing to discover, evaluate() legitimately does nothing.
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200
    assert resp.json() == []


def test_evaluate_named_configuration_with_zero_predictions_is_all_unmatched(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})

    resp = client.post(
        '/api/sessions/s1/evaluate',
        json={'task': 'presence', 'configuration_ids': ['cfg-rgb']},
    )
    assert resp.status_code == 200
    result = resp.json()[0]
    assert result['sample_count'] == 1
    assert result['matched_samples'] == 0
    assert result['unmatched_ground_truth'] == 1
    assert result['metrics']['accuracy'] is None  # N/A, not 0.0


def test_evaluate_unknown_session_404(client):
    resp = client.post('/api/sessions/nope/evaluate', json={'task': 'presence'})
    assert resp.status_code == 404


def test_evaluate_negative_tolerance_rejected(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'tolerance_ms': -1.0})
    assert resp.status_code == 422


# --- evaluator_type dispatch (Phase 79, v0.8) --------------------------------

def test_evaluate_unknown_evaluator_type_422_never_silently_classification(client):
    _seed(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'evaluator_type': 'object_detection'})
    assert resp.status_code == 422
    assert 'object_detection' in resp.json()['detail']

    # And it must genuinely reject, not silently fall back - no result
    # persisted for this (unrecognized-evaluator) call at all.
    assert client.get('/api/sessions/s1/evaluation').json() == []


def test_evaluate_omitted_evaluator_type_defaults_to_classification(client):
    # Every pre-v0.8 caller keeps working byte-for-byte unchanged - this
    # is the single most important guarantee of this phase.
    _seed(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200
    results = {r['configuration_id']: r for r in resp.json()}
    assert results['cfg-rgb']['evaluator_type'] == 'classification'
    assert results['cfg-rgb']['metrics']['accuracy'] == 1.0
    # The dedicated confusion_matrix field stays populated (pre-Phase-86
    # frontend backward compatibility), sourced from the same place the
    # new generic `details` field carries it.
    assert results['cfg-rgb']['confusion_matrix'] == results['cfg-rgb']['details']['confusion_matrix']


def test_evaluate_explicit_classification_evaluator_type_matches_default(client):
    _seed(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'evaluator_type': 'classification'})
    assert resp.status_code == 200
    results = {r['configuration_id']: r for r in resp.json()}
    assert results['cfg-rgb']['evaluator_type'] == 'classification'
    assert results['cfg-rgb']['metrics']['accuracy'] == 1.0


def test_get_evaluation_unknown_session_404(client):
    resp = client.get('/api/sessions/nope/evaluation')
    assert resp.status_code == 404


def test_get_evaluation_empty_before_any_evaluate_call(client):
    _create_scenario(client)
    _create_session(client)
    assert client.get('/api/sessions/s1/evaluation').json() == []


def test_evaluate_confusion_matrix_shape_matches_observed_labels(client):
    _seed(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    results = {r['configuration_id']: r for r in resp.json()}
    cm = results['cfg-rgb']['confusion_matrix']
    assert cm['labels'] == ['absent', 'present']
    assert len(cm['counts']) == 2
    assert all(len(row) == 2 for row in cm['counts'])


def test_evaluate_missing_label_key_returns_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'not_a_label': 'x'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'm', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'not_a_label': 'x'}},
    ]})
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 422
    assert 'label' in resp.json()['detail']


# --- timeline ---------------------------------------------------------------

def test_timeline_all_correct(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/timeline', params={'task': 'presence', 'configuration_id': 'cfg-rgb'})
    assert resp.status_code == 200
    events = resp.json()
    assert [e['kind'] for e in events] == ['correct', 'correct', 'correct']
    assert [e['timestamp_ms'] for e in events] == sorted(e['timestamp_ms'] for e in events)


def test_timeline_marks_the_one_incorrect_depth_sample(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/timeline', params={'task': 'presence', 'configuration_id': 'cfg-depth'})
    assert resp.status_code == 200
    events = resp.json()
    assert [e['kind'] for e in events] == ['incorrect', 'correct', 'correct']
    assert events[0]['ground_truth_label'] == 'present'
    assert events[0]['predicted_label'] == 'absent'


def test_timeline_missing_and_unmatched_predictions(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 5000.0, 'source_id': 'm', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'label': 'present'}},
    ]})
    resp = client.get(
        '/api/sessions/s1/timeline',
        params={'task': 'presence', 'configuration_id': 'cfg-rgb', 'tolerance_ms': 10},
    )
    assert resp.status_code == 200
    kinds = {e['kind'] for e in resp.json()}
    assert kinds == {'missing_prediction', 'unmatched_prediction'}


def test_timeline_unknown_session_404(client):
    resp = client.get('/api/sessions/nope/timeline', params={'task': 'presence', 'configuration_id': 'cfg-rgb'})
    assert resp.status_code == 404


def test_timeline_negative_tolerance_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.get(
        '/api/sessions/s1/timeline',
        params={'task': 'presence', 'configuration_id': 'cfg-rgb', 'tolerance_ms': -1},
    )
    assert resp.status_code == 422


def test_timeline_missing_label_key_returns_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'not_a_label': 'x'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'm', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'not_a_label': 'x'}},
    ]})
    resp = client.get('/api/sessions/s1/timeline', params={'task': 'presence', 'configuration_id': 'cfg-rgb'})
    assert resp.status_code == 422
