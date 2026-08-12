"""Phase 40: profile/coverage robustness. Closes the specific gaps in the
Phase 30-39 test suite per issue #41's checklist. Malformed-profile
rejection (unsupported operator, empty acceptance, duplicate group id,
unknown group reference, a 2-node group cycle, empty profile, duplicate
id 409, no update/delete routes) and several coverage-discovery cases
(unknown session filter, wrong-conditions N/A, explicit-configuration-
with-no-evidence all-N/A, ambiguous-session-resolved-via-binding,
multi-configuration coverage) already have dedicated tests in
test_profiles_api.py and test_profiles_coverage_api.py; not duplicated
here.
"""
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
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 300.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 400.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    assert resp.status_code == 201, resp.text


def _seed_predictions(client, session_id='s1', source_id='rgb_model', sensor_ids=None) -> None:
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
         'task': 'presence', 'value': {'label': 'present'}},  # wrong: gt is 'absent' -> 4/5 correct
    ]})
    assert resp.status_code == 201, resp.text


def _evaluate(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _seed_and_evaluate(client, session_id='s1', source_id='rgb_model', sensor_ids=None) -> None:
    _seed_ground_truth(client, session_id)
    _seed_predictions(client, session_id, source_id, sensor_ids)
    _evaluate(client, session_id)


def _profile_body(**overrides) -> dict:
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
    return body


# --- malformed profile: gaps not already covered by test_profiles_api.py ---

def test_create_profile_rejects_dangling_parent_group_reference_422(client):
    body = _profile_body(groups=[{'id': 'g1', 'parent_id': 'does-not-exist', 'name': 'G1'}])
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any('unknown parent group' in e for e in resp.json()['detail'])


def test_create_profile_rejects_blank_task_422(client):
    body = _profile_body()
    body['requirements'][0]['task'] = '   '
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any('no task' in e for e in resp.json()['detail'])


def test_create_profile_rejects_non_finite_threshold_422(client):
    body = _profile_body()
    body['requirements'][0]['acceptance'] = [{'metric': 'accuracy', 'operator': '>=', 'value': float('nan')}]
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422


def test_create_profile_rejects_duplicate_requirement_id_422(client):
    body = _profile_body(requirements=[
        {'id': 'req-001', 'group_id': 'g1', 'name': 'A', 'task': 'presence',
         'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
        {'id': 'req-001', 'group_id': 'g1', 'name': 'B', 'task': 'presence',
         'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
    ])
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 422
    assert any("duplicate requirement id 'req-001'" in e for e in resp.json()['detail'])


# --- malformed coverage request -------------------------------------------

def test_coverage_wrong_type_for_configuration_ids_422(client):
    resp = client.post('/api/profiles', json=_profile_body())
    assert resp.status_code == 201
    resp = client.post('/api/profiles/p1/coverage', json={'configuration_ids': 'cfg-rgb'})  # string, not list
    assert resp.status_code == 422


# --- ambiguous prediction source, through the real /coverage API ----------

def test_coverage_ambiguous_prediction_source_is_na(client):
    # Distinct from an ambiguous *session* (already covered in
    # test_profiles_coverage_api.py) - here exactly one session matches
    # the requirement's conditions, but that session has two distinct
    # source_ids for the same configuration/task, reusing v0.3's
    # _resolve_source_id ambiguity rule.
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client, source_id='rgb_model')
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 500.0, 'source_id': 'rgb_model_v2', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    resp = client.post('/api/profiles', json=_profile_body())
    assert resp.status_code == 201

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200
    result = resp.json()['configuration_coverages'][0]['requirement_results'][0]
    assert result['status'] == 'na'
    assert any('multiple prediction sources' in r for r in result['reasons'])
    assert result['evidence'] is None


# --- missing metric, through the real /coverage API ------------------------

def test_coverage_unknown_metric_name_is_na(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)
    body = _profile_body()
    body['requirements'][0]['acceptance'] = [{'metric': 'does_not_exist', 'operator': '>=', 'value': 0.5}]
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200
    result = resp.json()['configuration_coverages'][0]['requirement_results'][0]
    assert result['status'] == 'na'
    assert result['evidence'] is not None  # evidence WAS resolved - the metric just isn't in it
    assert result['criteria'][0]['status'] == 'na'
    assert result['criteria'][0]['observed'] is None


# --- partial evidence: mixed statuses within one coverage call ------------

def test_coverage_partial_evidence_mixes_resolved_and_na_requirements(client):
    _create_scenario(client)
    _create_session(client, session_id='s1', metadata={'illumination': 'night'})
    _seed_and_evaluate(client, session_id='s1')

    profile = _profile_body(requirements=[
        {'id': 'req-resolvable', 'group_id': 'g1', 'name': 'Resolvable', 'task': 'presence',
         'conditions': {'illumination': 'night'},
         'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
        {'id': 'req-unresolvable', 'group_id': 'g1', 'name': 'Unresolvable', 'task': 'presence',
         'conditions': {'illumination': 'day'},  # no session matches
         'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
    ])
    resp = client.post('/api/profiles', json=profile)
    assert resp.status_code == 201

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200
    coverage = resp.json()['configuration_coverages'][0]
    results = {r['requirement_id']: r for r in coverage['requirement_results']}
    assert results['req-resolvable']['status'] == 'pass'
    assert results['req-resolvable']['evidence'] is not None
    assert results['req-unresolvable']['status'] == 'na'
    assert results['req-unresolvable']['evidence'] is None

    # Group aggregation must reflect the mix, not collapse to one status.
    root = coverage['root']
    assert root['pass_count'] == 1
    assert root['na_count'] == 1
    assert root['fail_count'] == 0
    assert root['requirement_coverage'] == pytest.approx(1.0)  # 1 pass / (1 pass + 0 fail)
    assert root['evidence_completeness'] == pytest.approx(0.5)  # 1 decided / 2 total


# --- legacy v0.2/v0.3-only session (no v0.4 conditions at all) ------------

def test_coverage_against_legacy_session_with_no_metadata_is_na_not_crash(client):
    # A session ingested exactly the way a pre-v0.4 client would - no
    # Session.metadata conditions were ever set (the field defaults to
    # {} and no v0.2/v0.3 workflow ever populates it). v0.4 added no
    # migration a legacy session would be missing; a requirement with any
    # declared condition simply can never match it - N/A, not a crash.
    _create_scenario(client)
    _create_session(client, session_id='legacy-s1', metadata={})
    _seed_and_evaluate(client, session_id='legacy-s1')

    resp = client.post('/api/profiles', json=_profile_body())
    assert resp.status_code == 201

    resp = client.post('/api/profiles/p1/coverage', json={})
    assert resp.status_code == 200, resp.text
    result = resp.json()['configuration_coverages'][0]['requirement_results'][0]
    assert result['status'] == 'na'
    assert any('no session matches conditions' in r for r in result['reasons'])


# --- two profile versions coexisting ---------------------------------------

def test_two_profile_versions_are_independently_addressable(client):
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_and_evaluate(client)

    v1 = _profile_body(id='p1', version='1.0')
    v1['requirements'][0]['acceptance'] = [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]
    v2 = _profile_body(id='p1-v2', version='2.0')
    v2['requirements'][0]['acceptance'] = [{'metric': 'accuracy', 'operator': '>=', 'value': 0.99}]

    assert client.post('/api/profiles', json=v1).status_code == 201
    assert client.post('/api/profiles', json=v2).status_code == 201

    ids = {p['id'] for p in client.get('/api/profiles').json()}
    assert {'p1', 'p1-v2'} <= ids

    cov_v1 = client.post('/api/profiles/p1/coverage', json={}).json()['configuration_coverages'][0]
    cov_v2 = client.post('/api/profiles/p1-v2/coverage', json={}).json()['configuration_coverages'][0]

    assert cov_v1['profile_version'] == '1.0'
    assert cov_v2['profile_version'] == '2.0'
    assert cov_v1['requirement_results'][0]['status'] == 'pass'   # 0.8 >= 0.5
    assert cov_v2['requirement_results'][0]['status'] == 'fail'   # 0.8 < 0.99
