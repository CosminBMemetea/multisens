"""Phase 18: robustness beyond the happy path already covered by earlier
phases' tests - empty sessions, partial coverage, malformed batch items
of several distinct shapes (not just "missing a required field"), and
duplicate ids arriving across separate requests rather than within one
batch. The `client` fixture lives in conftest.py.
"""


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


# --- empty session -----------------------------------------------------------

def test_empty_session_list_endpoints_return_empty_lists_not_errors(client):
    _create_scenario(client)
    _create_session(client)

    assert client.get('/api/sessions/s1/ground-truth').json() == []
    assert client.get('/api/sessions/s1/predictions').json() == []
    assert client.get('/api/sessions/s1/evaluation').json() == []


def test_evaluate_on_completely_empty_session_returns_empty_list(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200
    assert resp.json() == []


# --- partial prediction coverage ---------------------------------------------

def test_partial_prediction_coverage_reports_correct_matched_and_unmatched(client):
    _create_scenario(client)
    _create_session(client)

    ground_truth = [
        {'timestamp_ms': float(i * 1000), 'task': 'presence', 'value': {'label': 'present'}}
        for i in range(10)
    ]
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': ground_truth})

    # Only the first 6 of 10 ground-truth points get a prediction.
    predictions = [
        {'timestamp_ms': float(i * 1000) + 1, 'source_id': 'm', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}}
        for i in range(6)
    ]
    client.post('/api/sessions/s1/predictions/batch', json={'items': predictions})

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    result = resp.json()[0]
    assert result['sample_count'] == 10
    assert result['matched_samples'] == 6
    assert result['unmatched_ground_truth'] == 4
    assert result['unmatched_predictions'] == 0
    assert result['metrics']['accuracy'] == 1.0  # the 6 matched are all correct


# --- missing configuration ----------------------------------------------------

def test_predictions_filtered_by_never_used_configuration_returns_empty(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 0.0, 'source_id': 'm', 'sensor_ids': ['rgb'], 'task': 'presence', 'value': {'label': 'x'}},
    ]})
    resp = client.get('/api/sessions/s1/predictions', params={'configuration_id': 'cfg-nonexistent'})
    assert resp.status_code == 200
    assert resp.json() == []


# --- malformed batches ---------------------------------------------------------

def test_ground_truth_batch_wrong_type_for_timestamp_rejected_per_item(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 'not-a-number', 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1
    assert body['errors'][0]['index'] == 0


def test_predictions_batch_sensor_ids_wrong_type_rejected_per_item(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        # sensor_ids must be a list - a bare string is not coerced into one.
        {'timestamp_ms': 0.0, 'source_id': 'm', 'sensor_ids': 'rgb', 'task': 'presence', 'value': {'label': 'x'}},
        {'timestamp_ms': 1.0, 'source_id': 'm', 'sensor_ids': ['rgb'], 'task': 'presence', 'value': {'label': 'x'}},
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1
    assert body['errors'][0]['index'] == 0


def test_batch_empty_items_list_is_a_valid_noop(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': []})
    assert resp.status_code == 201
    assert resp.json() == {'accepted': 0, 'rejected': 0, 'errors': []}


def test_batch_with_a_non_dict_item_is_a_whole_request_422(client):
    # A structurally malformed batch (an item that isn't even an object)
    # is a different failure mode from "a well-formed item that fails
    # domain validation" - FastAPI rejects the whole request before any
    # handler code runs, which is expected and covered here so the
    # behavior is documented, not just accidental.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [5, 'not-an-object']})
    assert resp.status_code == 422


# --- duplicate events across separate requests --------------------------------

def test_duplicate_id_across_separate_batch_requests_is_rejected_not_crashed(client):
    _create_scenario(client)
    _create_session(client)

    first = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'id': 'shared-id', 'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    assert first.status_code == 201
    assert first.json() == {'accepted': 1, 'rejected': 0, 'errors': []}

    # Same id, different request entirely (simulates a client retry after
    # e.g. a network blip, not just a duplicate within one payload).
    second = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'id': 'shared-id', 'timestamp_ms': 999.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert second.status_code == 201
    body = second.json()
    assert body['accepted'] == 0
    assert body['rejected'] == 1

    # Original row untouched, not overwritten by the failed duplicate.
    listed = client.get('/api/sessions/s1/ground-truth').json()
    assert len(listed) == 1
    assert listed[0]['value']['label'] == 'present'
