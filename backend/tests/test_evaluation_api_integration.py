"""Phase 84 (v0.8): finishing the evaluator_type/parameters wiring across
the public API surface - /evaluate itself was already fully generic
since Phase 79 (verified again here across all three evaluator types).
The real, new work this phase: /compare's common-set re-evaluation used
to crash any object_detection comparison with an unhandled 500 (it
unconditionally passed empty parameters, and object_detection has no
default confidence_threshold/iou_threshold) - fixed by threading an
explicit `parameters` field through CompareRequest, exactly like
tolerance_ms already is. /timeline is confirmed to degrade gracefully
(never 500, a clear dedicated message) for a non-classification result.
"""
import pytest


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _box(x=0.1, y=0.1, width=0.2, height=0.2) -> dict:
    return {'x': x, 'y': y, 'width': width, 'height': height}


def _seed_detection(client, session_id, source_id, sensor_ids, box, label='person'):
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'obstacle_detection', 'value': {'objects': [{'id': 'o1', 'label': label, 'bbox': box}]}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': source_id, 'sensor_ids': sensor_ids, 'task': 'obstacle_detection',
         'value': {'detections': [{'label': label, 'confidence': 0.9, 'bbox': box}]}},
    ]})
    assert resp.status_code == 201, resp.text


def _seed_regression(client, session_id, source_id, sensor_ids, gt_value, pred_value, unit='m'):
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'distance_estimation', 'value': {'value': gt_value, 'unit': unit}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': source_id, 'sensor_ids': sensor_ids, 'task': 'distance_estimation',
         'value': {'value': pred_value, 'unit': unit}},
    ]})
    assert resp.status_code == 201, resp.text


# --- /evaluate: all three evaluator types through the real endpoint --------

def test_evaluate_all_three_evaluator_types_dispatch_correctly(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    assert resp.status_code == 201
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'cls', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'label': 'present'}},
    ]})
    assert resp.status_code == 201
    _seed_detection(client, 's1', 'det', ['depth'], _box())
    _seed_regression(client, 's1', 'reg', ['thermal'], 2.0, 2.1)

    r1 = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'evaluator_type': 'classification'})
    r2 = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection',
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })
    r3 = client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})

    assert r1.status_code == 200 and r1.json()[0]['evaluator_type'] == 'classification'
    assert r2.status_code == 200 and r2.json()[0]['evaluator_type'] == 'object_detection'
    assert r3.status_code == 200 and r3.json()[0]['evaluator_type'] == 'regression'


# --- /compare: the real bug this phase found and fixed ---------------------

def test_compare_two_object_detection_configurations_no_longer_crashes(client):
    _create_scenario(client)
    _create_session(client)
    _seed_detection(client, 's1', 'det_a', ['rgb'], _box())
    _seed_detection(client, 's1', 'det_b', ['depth'], _box())

    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection',
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })
    assert resp.status_code == 200, resp.text

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'obstacle_detection', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'],
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    assert comparison['common_set']['baseline']['metrics']['precision'] == 1.0
    assert comparison['validity']['status'] in ('valid', 'valid_with_warnings')


def test_compare_object_detection_missing_parameters_is_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    _seed_detection(client, 's1', 'det_a', ['rgb'], _box())
    _seed_detection(client, 's1', 'det_b', ['depth'], _box())
    client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection',
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'obstacle_detection', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'],
        # parameters omitted entirely - must be a clean 422, never a crash.
    })
    assert resp.status_code == 422
    assert 'confidence_threshold' in resp.json()['detail']


def test_compare_regression_configurations_needs_no_parameters(client):
    # Regression has no configurable parameters - the empty default must
    # keep working exactly like it always did (classification's own
    # zero-parameter case, proven unaffected by this phase's fix).
    _create_scenario(client)
    _create_session(client)
    _seed_regression(client, 's1', 'reg_a', ['rgb'], 2.0, 2.1)
    _seed_regression(client, 's1', 'reg_b', ['depth'], 2.0, 2.0)
    client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'distance_estimation', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'],
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    assert comparison['common_set']['baseline']['metrics']['mae'] == pytest.approx(0.1)
    assert comparison['common_set']['candidate']['metrics']['mae'] == pytest.approx(0.0)


def test_compare_evaluator_type_mismatch_through_real_api(client):
    _create_scenario(client)
    _create_session(client)

    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'shared_task', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'cls', 'sensor_ids': ['rgb'], 'task': 'shared_task',
         'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/evaluate', json={'task': 'shared_task', 'evaluator_type': 'classification'})

    # A second configuration, same task name, but evaluated as regression -
    # a deliberately mismatched pair to exercise the comparability check.
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 100.0, 'task': 'shared_task', 'value': {'value': 1.0, 'unit': 'm'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 101.0, 'source_id': 'reg', 'sensor_ids': ['depth'], 'task': 'shared_task',
         'value': {'value': 1.1, 'unit': 'm'}},
    ]})
    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'shared_task', 'evaluator_type': 'regression', 'configuration_ids': ['cfg-depth'],
    })
    assert resp.status_code == 200, resp.text

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'shared_task', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'],
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    assert comparison['validity']['status'] == 'invalid'
    assert 'evaluator_type' in comparison['validity']['reasons'][0]


# --- /timeline: graceful degradation for non-classification results --------

def test_timeline_object_detection_result_is_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    _seed_detection(client, 's1', 'det', ['rgb'], _box())
    client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection',
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })

    resp = client.get('/api/sessions/s1/timeline', params={'task': 'obstacle_detection', 'configuration_id': 'cfg-rgb'})
    assert resp.status_code == 422
    assert 'object_detection' in resp.json()['detail']
    assert 'classification' in resp.json()['detail']


def test_timeline_regression_result_is_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    _seed_regression(client, 's1', 'reg', ['rgb'], 2.0, 2.1)
    client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})

    resp = client.get('/api/sessions/s1/timeline', params={'task': 'distance_estimation', 'configuration_id': 'cfg-rgb'})
    assert resp.status_code == 422
    assert 'regression' in resp.json()['detail']


def test_timeline_classification_result_still_works_unchanged(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'cls', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'evaluator_type': 'classification'})

    resp = client.get('/api/sessions/s1/timeline', params={'task': 'presence', 'configuration_id': 'cfg-rgb'})
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]['kind'] == 'correct'
