"""Phase 32: profile persistence + API tests. The `client` fixture lives
in conftest.py."""
import pytest


def _valid_profile_body(**overrides) -> dict:
    defaults = {
        'id': 'example-profile-v1.0',
        'name': 'Example Profile',
        'version': '1.0',
        'description': 'A generic example profile.',
        'groups': [
            {'id': 'group-a', 'name': 'Function A'},
            {'id': 'group-a-1', 'parent_id': 'group-a', 'name': 'Use Case A1'},
        ],
        'requirements': [
            {
                'id': 'req-001', 'group_id': 'group-a-1', 'name': 'Variant 1', 'task': 'presence',
                'conditions': {'illumination': 'night'},
                'acceptance': [
                    {'metric': 'recall_macro', 'operator': '>=', 'value': 0.9},
                    {'metric': 'coverage', 'operator': '>=', 'value': 0.95},
                ],
            },
        ],
    }
    return {**defaults, **overrides}


# --- create ----------------------------------------------------------------

def test_create_profile_returns_201_with_server_assigned_created_at(client):
    resp = client.post('/api/profiles', json=_valid_profile_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body['id'] == 'example-profile-v1.0'
    assert body['created_at'] is not None


def test_create_profile_round_trips_through_get(client):
    create_resp = client.post('/api/profiles', json=_valid_profile_body())
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()

    get_resp = client.get('/api/profiles/example-profile-v1.0')
    assert get_resp.status_code == 200
    fetched = get_resp.json()

    assert fetched == created
    assert len(fetched['groups']) == 2
    assert len(fetched['requirements']) == 1
    assert fetched['requirements'][0]['conditions'] == {'illumination': 'night'}


def test_create_profile_rejects_unsupported_operator_structurally_422(client):
    body = _valid_profile_body()
    body['requirements'][0]['acceptance'][0]['operator'] = '!='
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert client.get('/api/profiles/example-profile-v1.0').status_code == 404


def test_create_profile_rejects_empty_acceptance_list_structurally_422(client):
    body = _valid_profile_body()
    body['requirements'][0]['acceptance'] = []
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422


def test_create_profile_rejects_duplicate_group_id_422(client):
    body = _valid_profile_body(groups=[
        {'id': 'group-a', 'name': 'Function A'},
        {'id': 'group-a', 'name': 'Function A again'},
    ])
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any('duplicate group id' in e for e in resp.json()['detail'])
    assert client.get('/api/profiles/example-profile-v1.0').status_code == 404


def test_create_profile_rejects_unknown_group_reference_422(client):
    body = _valid_profile_body()
    body['requirements'][0]['group_id'] = 'does-not-exist'
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any('unknown group' in e for e in resp.json()['detail'])


def test_create_profile_rejects_group_cycle_422(client):
    body = _valid_profile_body(groups=[
        {'id': 'group-a', 'parent_id': 'group-b', 'name': 'A'},
        {'id': 'group-b', 'parent_id': 'group-a', 'name': 'B'},
    ])
    body['requirements'][0]['group_id'] = 'group-a'
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any('cycle' in e for e in resp.json()['detail'])


def test_create_profile_rejects_empty_profile_422(client):
    body = _valid_profile_body(groups=[], requirements=[])
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any('no requirements' in e for e in resp.json()['detail'])


def test_create_profile_duplicate_id_409_leaves_original_untouched(client):
    first = client.post('/api/profiles', json=_valid_profile_body())
    assert first.status_code == 201

    second = client.post('/api/profiles', json=_valid_profile_body(name='A different name'))
    assert second.status_code == 409

    fetched = client.get('/api/profiles/example-profile-v1.0').json()
    assert fetched['name'] == 'Example Profile'  # unchanged by the rejected second POST


def test_create_profile_missing_required_field_422(client):
    body = _valid_profile_body()
    del body['requirements']
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422


def test_create_profile_arbitrary_condition_keys_round_trip(client):
    body = _valid_profile_body()
    body['requirements'][0]['conditions'] = {
        'weather': 'rain', 'vibration_level': 3.5, 'camera_contaminated': True,
    }
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201, resp.text
    fetched = client.get('/api/profiles/example-profile-v1.0').json()
    assert fetched['requirements'][0]['conditions'] == {
        'weather': 'rain', 'vibration_level': 3.5, 'camera_contaminated': True,
    }


# --- list --------------------------------------------------------------

def test_list_profiles_empty_initially(client):
    resp = client.get('/api/profiles')
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_profiles_returns_summary_not_full_document(client):
    client.post('/api/profiles', json=_valid_profile_body())
    resp = client.get('/api/profiles')
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary['id'] == 'example-profile-v1.0'
    assert summary['requirement_count'] == 1
    assert 'groups' not in summary
    assert 'requirements' not in summary


def test_list_profiles_multiple_profiles_sorted_by_id(client):
    client.post('/api/profiles', json=_valid_profile_body(id='profile-b'))
    client.post('/api/profiles', json=_valid_profile_body(id='profile-a'))
    resp = client.get('/api/profiles')
    ids = [p['id'] for p in resp.json()]
    assert ids == ['profile-a', 'profile-b']


# --- get -----------------------------------------------------------------

def test_get_profile_unknown_id_404(client):
    resp = client.get('/api/profiles/does-not-exist')
    assert resp.status_code == 404


# --- immutability --------------------------------------------------------

def test_no_update_or_delete_routes_exist(client):
    client.post('/api/profiles', json=_valid_profile_body())
    assert client.put('/api/profiles/example-profile-v1.0', json={}).status_code in (404, 405)
    assert client.patch('/api/profiles/example-profile-v1.0', json={}).status_code in (404, 405)
    assert client.delete('/api/profiles/example-profile-v1.0').status_code in (404, 405)
