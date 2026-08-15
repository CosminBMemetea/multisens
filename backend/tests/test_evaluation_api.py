"""Evaluation ingestion API tests (Phase 12): scenario/session CRUD,
ground-truth and prediction batch ingestion with partial-failure
reporting, and session existence validation. The `client` fixture lives in
conftest.py (shared with test_evaluate_api.py, Phase 14).
"""
from app.api.sessions import MAX_BATCH_SIZE


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


# --- scenarios -------------------------------------------------------------

def test_create_and_list_scenario(client):
    resp = client.post('/api/scenarios', json={'id': 'sc1', 'name': 'Normal illumination', 'tags': ['indoor']})
    assert resp.status_code == 201
    assert resp.json()['tags'] == ['indoor']

    listed = client.get('/api/scenarios').json()
    assert [s['id'] for s in listed] == ['sc1']


def test_create_scenario_generates_id_when_omitted(client):
    resp = client.post('/api/scenarios', json={'name': 'no id given'})
    assert resp.status_code == 201
    assert resp.json()['id']


def test_create_scenario_duplicate_id_rejected(client):
    _create_scenario(client)
    resp = client.post('/api/scenarios', json={'id': 'sc1', 'name': 'again'})
    assert resp.status_code == 409


# --- sessions ----------------------------------------------------------------

def test_create_session_requires_existing_scenario(client):
    resp = client.post('/api/sessions', json={'id': 's1', 'name': 'demo', 'scenario_id': 'does-not-exist'})
    assert resp.status_code == 422


def test_create_session_defaults_to_created_status(client):
    _create_scenario(client)
    resp = client.post('/api/sessions', json={'id': 's1', 'name': 'demo', 'scenario_id': 'sc1'})
    assert resp.status_code == 201
    assert resp.json()['status'] == 'created'


def test_get_session_not_found(client):
    assert client.get('/api/sessions/nope').status_code == 404


def test_start_then_complete_session(client):
    _create_scenario(client)
    _create_session(client)

    started = client.post('/api/sessions/s1/start')
    assert started.status_code == 200
    assert started.json()['status'] == 'running'

    completed = client.post('/api/sessions/s1/complete')
    assert completed.status_code == 200
    assert completed.json()['status'] == 'completed'
    assert completed.json()['ended_at'] is not None


def test_start_unknown_session_404(client):
    assert client.post('/api/sessions/nope/start').status_code == 404


# --- session lifecycle state-transition guards (v0.9 bug hunt, BUG-002, ---
# --- issue #109 - previously any transition from any state silently  ------
# --- succeeded, including double-complete silently overwriting ended_at) --

def test_repeated_start_is_an_idempotent_no_op(client):
    _create_scenario(client)
    _create_session(client)
    first = client.post('/api/sessions/s1/start')
    assert first.status_code == 200
    assert first.json()['status'] == 'running'

    second = client.post('/api/sessions/s1/start')
    assert second.status_code == 200
    assert second.json()['status'] == 'running'


def test_start_after_completed_is_rejected_409(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    client.post('/api/sessions/s1/complete')

    resp = client.post('/api/sessions/s1/start')
    assert resp.status_code == 409
    assert 'already completed' in resp.json()['detail']
    # The session must stay completed, not silently bounce back to running.
    assert client.get('/api/sessions/s1').json()['status'] == 'completed'


def test_repeated_complete_is_idempotent_and_never_moves_ended_at(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')

    first = client.post('/api/sessions/s1/complete')
    assert first.status_code == 200
    first_ended_at = first.json()['ended_at']
    assert first_ended_at is not None

    second = client.post('/api/sessions/s1/complete')
    assert second.status_code == 200
    # The real bug: a second /complete call used to silently re-stamp
    # ended_at with a new, later timestamp, destroying the true
    # completion time.
    assert second.json()['ended_at'] == first_ended_at


def test_complete_before_start_is_rejected_409(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/complete')
    assert resp.status_code == 409
    assert 'never started' in resp.json()['detail']
    # The session must stay created, never silently jump straight to
    # completed skipping running entirely.
    session = client.get('/api/sessions/s1').json()
    assert session['status'] == 'created'
    assert session['ended_at'] is None


# --- ground truth batch ingestion --------------------------------------------

def test_ground_truth_batch_all_valid(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body == {'accepted': 2, 'rejected': 0, 'errors': []}

    listed = client.get('/api/sessions/s1/ground-truth').json()
    assert [gt['timestamp_ms'] for gt in listed] == [100.0, 200.0]  # ordered, not insertion order


def test_ground_truth_batch_partial_failure_reports_bad_item_without_dropping_good_ones(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 200.0, 'value': {'label': 'present'}},  # missing required 'task'
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1
    assert body['errors'][0]['index'] == 1

    listed = client.get('/api/sessions/s1/ground-truth').json()
    assert len(listed) == 1


def test_ground_truth_batch_unknown_session_404(client):
    resp = client.post('/api/sessions/nope/ground-truth/batch', json={'items': []})
    assert resp.status_code == 404


def test_ground_truth_batch_too_large_rejected(client):
    _create_scenario(client)
    _create_session(client)
    items = [{'timestamp_ms': float(i), 'task': 'presence', 'value': {'label': 'present'}}
             for i in range(MAX_BATCH_SIZE + 1)]
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': items})
    assert resp.status_code == 422


def test_ground_truth_batch_duplicate_id_within_batch_partially_succeeds(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'id': 'dup', 'timestamp_ms': 1.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'id': 'dup', 'timestamp_ms': 2.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1
    assert body['errors'][0]['index'] == 1

    listed = client.get('/api/sessions/s1/ground-truth').json()
    assert len(listed) == 1


# --- prediction batch ingestion ------------------------------------------------

def test_predictions_batch_derives_configuration_id_and_lists_filtered(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 100.0, 'source_id': 'rgb_detector', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}, 'confidence': 0.9},
        {'timestamp_ms': 100.0, 'source_id': 'fusion', 'sensor_ids': ['depth', 'rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    assert resp.status_code == 201
    assert resp.json() == {'accepted': 2, 'rejected': 0, 'errors': []}

    rgb_only = client.get('/api/sessions/s1/predictions', params={'configuration_id': 'cfg-rgb'}).json()
    assert len(rgb_only) == 1
    assert rgb_only[0]['confidence'] == 0.9

    fusion_only = client.get('/api/sessions/s1/predictions', params={'configuration_id': 'cfg-depth-rgb'}).json()
    assert len(fusion_only) == 1


def test_predictions_batch_confidence_out_of_range_rejected(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 100.0, 'source_id': 'rgb_detector', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}, 'confidence': 1.5},
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body == {'accepted': 0, 'rejected': 1, 'errors': [{'index': 0, 'error': body['errors'][0]['error']}]}
    assert 'confidence' in body['errors'][0]['error']


def test_predictions_batch_empty_sensor_ids_rejected(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 100.0, 'source_id': 'x', 'sensor_ids': [], 'task': 'presence', 'value': {}},
    ]})
    assert resp.status_code == 201
    assert resp.json()['rejected'] == 1


def test_predictions_batch_unknown_session_404(client):
    resp = client.post('/api/sessions/nope/predictions/batch', json={'items': []})
    assert resp.status_code == 404
