"""Phase 70: resource-observation batch ingestion API - mirrors
test_evaluation_api.py's ground-truth/prediction batch tests exactly,
same partial-failure/malformed-item/unknown-session/too-large coverage.
"""
from app.api.sessions import MAX_BATCH_SIZE


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _valid_item(**overrides) -> dict:
    return {
        'metric': 'cpu_percent', 'value': 30.0, 'unit': '%', 'quality': 'measured',
        'source': 'psutil.cpu_percent', 'platform_id': 'macbook-m2-dockerdesktop',
        'started_at': '2026-01-01T00:00:00Z', 'ended_at': '2026-01-01T00:00:10Z',
        **overrides,
    }


def test_resource_observations_batch_all_valid(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _valid_item(metric='cpu_percent', value=30.0),
        _valid_item(metric='memory_mb', value=800.0, unit='MB'),
    ]})
    assert resp.status_code == 201
    assert resp.json() == {'accepted': 2, 'rejected': 0, 'errors': []}

    listed = client.get('/api/sessions/s1/resource-observations').json()
    assert {o['metric'] for o in listed} == {'cpu_percent', 'memory_mb'}


def test_resource_observations_batch_partial_failure_reports_bad_item_without_dropping_good_ones(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _valid_item(),
        {'metric': 'cpu_percent', 'unit': '%'},  # missing required fields (value/quality/source/platform_id/...)
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1
    assert body['errors'][0]['index'] == 1

    listed = client.get('/api/sessions/s1/resource-observations').json()
    assert len(listed) == 1


def test_resource_observations_batch_value_quality_mismatch_rejected_per_item(client):
    # Domain-layer cross-field validation (Phase 65) fires through the
    # API too, not just in-process - quality='unavailable' with a real
    # value is malformed the same way a missing field is.
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _valid_item(),
        _valid_item(quality='unavailable', value=5.0),
    ]})
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1


def test_resource_observations_batch_unknown_session_404(client):
    resp = client.post('/api/sessions/nope/resource-observations/batch', json={'items': []})
    assert resp.status_code == 404


def test_resource_observations_batch_too_large_rejected(client):
    _create_scenario(client)
    _create_session(client)
    items = [_valid_item() for _ in range(MAX_BATCH_SIZE + 1)]
    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': items})
    assert resp.status_code == 422


def test_resource_observations_batch_duplicate_id_within_batch_partially_succeeds(client):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _valid_item(id='dup'),
        _valid_item(id='dup'),
    ]})
    assert resp.status_code == 201
    body = resp.json()
    assert body['accepted'] == 1
    assert body['rejected'] == 1

    listed = client.get('/api/sessions/s1/resource-observations').json()
    assert len(listed) == 1


def test_list_resource_observations_unknown_session_404(client):
    assert client.get('/api/sessions/nope/resource-observations').status_code == 404


def test_list_resource_observations_filters_by_configuration_and_metric(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _valid_item(metric='cpu_percent', configuration_id='cfg-front'),
        _valid_item(metric='cpu_percent', configuration_id='cfg-rear'),
        _valid_item(metric='memory_mb', unit='MB', configuration_id='cfg-front'),
    ]})

    front_only = client.get('/api/sessions/s1/resource-observations', params={'configuration_id': 'cfg-front'}).json()
    assert len(front_only) == 2

    cpu_only = client.get('/api/sessions/s1/resource-observations', params={'metric': 'cpu_percent'}).json()
    assert len(cpu_only) == 2


def test_resource_observations_batch_null_configuration_id_accepted(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [_valid_item()]})
    assert resp.status_code == 201
    listed = client.get('/api/sessions/s1/resource-observations').json()
    assert listed[0]['configuration_id'] is None
