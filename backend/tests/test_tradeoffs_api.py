"""Phase 70: POST /api/profiles/{id}/tradeoffs. Domain-level algorithm
correctness (comparability, constraints, generalized Pareto) is already
exhaustively covered in test_resource_tradeoff.py/test_resource_pareto.py;
these tests prove the wiring - request/response shapes, real evidence
discovery joined with real resource evidence, NO EVIDENCE handling, and
malformed-request handling.
"""
GROUND_TRUTH_LABELS = ['present', 'absent', 'present', 'present', 'absent']


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _seed_predictions_with_accuracy(client, session_id, sensor_ids, correct_count) -> None:
    predicted = [
        label if i < correct_count else ('absent' if label == 'present' else 'present')
        for i, label in enumerate(GROUND_TRUTH_LABELS)
    ]
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': i * 100.0 + 1.0, 'source_id': '-'.join(sensor_ids), 'sensor_ids': sensor_ids,
         'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(predicted)
    ]})
    assert resp.status_code == 201, resp.text


def _seed_ground_truth(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': i * 100.0, 'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(GROUND_TRUTH_LABELS)
    ]})
    assert resp.status_code == 201, resp.text


def _evaluate(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _create_profile(client) -> None:
    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'Tradeoff Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{'id': 'req-baseline', 'group_id': 'g1', 'name': 'Baseline', 'task': 'presence',
                           'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}]}],
    })
    assert resp.status_code == 201, resp.text


def _resource_item(**overrides) -> dict:
    return {
        'metric': 'cpu_percent', 'value': 20.0, 'unit': '%', 'quality': 'measured',
        'source': 'psutil.cpu_percent', 'platform_id': 'macbook-m2-dockerdesktop',
        'started_at': '2026-01-01T00:00:00Z', 'ended_at': '2026-01-01T00:00:10Z',
        **overrides,
    }


def _seed_scenario(client) -> None:
    # front_rgb alone: 3/5 = 0.6 -> fails. front_rgb+rear_rgb: 5/5 = 1.0 -> passes.
    _create_scenario(client)
    _create_session(client)
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb'], correct_count=3)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb', 'rear_rgb'], correct_count=5)
    _evaluate(client)
    _create_profile(client)


DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0, 'minimum_evidence_completeness': 1.0,
    'mandatory_requirements_must_pass': False, 'objective': 'minimize_sensor_count',
}


# --- basic wiring / malformed requests ---------------------------------------

def test_tradeoffs_unknown_profile_404(client):
    resp = client.post('/api/profiles/does-not-exist/tradeoffs', json={'policy': DEMO_POLICY, 'session_id': 's1'})
    assert resp.status_code == 404


def test_tradeoffs_unknown_session_404(client):
    _create_profile(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={'policy': DEMO_POLICY, 'session_id': 'nope'})
    assert resp.status_code == 404


def test_tradeoffs_requires_policy_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={'session_id': 's1'})
    assert resp.status_code == 422


def test_tradeoffs_unsupported_resource_metric_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['power_w'],
    })
    assert resp.status_code == 422


def test_tradeoffs_unsupported_metric_in_constraints_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'resource_constraints': [{'metric': 'gpu_percent', 'operator': '<=', 'value': 50.0}],
    })
    assert resp.status_code == 422


def test_tradeoffs_pareto_dimension_not_in_resource_metrics_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': [],
        'pareto_dimensions': {'cpu_percent': 'minimize'},
    })
    assert resp.status_code == 422


# --- decision evidence reused unchanged ---------------------------------------

def test_tradeoffs_reuses_decision_evidence_unchanged(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={'policy': DEMO_POLICY, 'session_id': 's1'})
    assert resp.status_code == 200, resp.text
    by_id = {c['configuration_id']: c for c in resp.json()['configurations']}

    front = by_id['cfg-front_rgb']
    assert front['sensor_count'] == 1
    assert front['policy_status'] == 'insufficient'  # 0.6 < 0.7
    assert front['resource_profile'] is None  # resource_metrics wasn't requested
    assert front['resource_validity'] is None

    both = by_id['cfg-front_rgb-rear_rgb']
    assert both['sensor_count'] == 2
    assert both['policy_status'] == 'sufficient'  # 1.0 >= 0.7


def test_tradeoffs_no_evidence_configuration_id_reported_explicitly(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'configuration_ids': ['cfg-front_rgb', 'cfg-never-evaluated'],
    })
    assert resp.status_code == 200, resp.text
    by_id = {c['configuration_id']: c for c in resp.json()['configurations']}
    phantom = by_id['cfg-never-evaluated']
    assert phantom['policy_status'] is None
    assert phantom['sensor_count'] == 0
    assert phantom['resource_profile'] is None
    assert phantom['qualification'] == 'undetermined'


# --- resource evidence joined in -----------------------------------------------

def test_tradeoffs_joins_real_resource_evidence(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=20.0),
        _resource_item(configuration_id='cfg-front_rgb-rear_rgb', value=30.0),
    ]})

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    by_id = {c['configuration_id']: c for c in resp.json()['configurations']}

    front = by_id['cfg-front_rgb']
    assert front['resource_validity'] == 'complete'
    assert front['resource_profile']['metrics']['cpu_percent']['mean'] == 20.0
    assert front['resource_profile']['platform_id'] == 'macbook-m2-dockerdesktop'

    both = by_id['cfg-front_rgb-rear_rgb']
    assert both['resource_profile']['metrics']['cpu_percent']['mean'] == 30.0


def test_tradeoffs_resource_metric_never_measured_is_unavailable_not_zero(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['resource_validity'] == 'unavailable'
    assert front['resource_profile']['metrics'] == {}


# --- resource constraints / qualification --------------------------------------

def test_tradeoffs_constraint_qualification_wired_through(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=20.0),
        _resource_item(configuration_id='cfg-front_rgb-rear_rgb', value=60.0),
    ]})

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
        'resource_constraints': [{'metric': 'cpu_percent', 'operator': '<=', 'value': 50.0}],
    })
    assert resp.status_code == 200, resp.text
    by_id = {c['configuration_id']: c for c in resp.json()['configurations']}

    assert by_id['cfg-front_rgb']['qualification'] == 'qualifies'
    assert by_id['cfg-front_rgb']['constraint_results'][0]['status'] == 'pass'

    assert by_id['cfg-front_rgb-rear_rgb']['qualification'] == 'does_not_qualify'
    assert by_id['cfg-front_rgb-rear_rgb']['constraint_results'][0]['status'] == 'fail'


def test_tradeoffs_constraint_na_never_qualifies(client):
    _seed_scenario(client)
    # cpu_percent measured, but the constraint targets a metric with zero evidence.
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent', value=20.0),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent', 'memory_mb'],
        'resource_constraints': [{'metric': 'memory_mb', 'operator': '<=', 'value': 1000.0}],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['constraint_results'][0]['status'] == 'na'
    assert front['qualification'] == 'undetermined'


# --- generalized Pareto over decision + resource dimensions --------------------

def test_tradeoffs_pareto_front_reflects_resource_dimension(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=20.0),
        _resource_item(configuration_id='cfg-front_rgb-rear_rgb', value=60.0),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
        'pareto_dimensions': {'requirement_coverage': 'maximize', 'cpu_percent': 'minimize'},
    })
    assert resp.status_code == 200, resp.text
    # A genuine trade-off: cfg-front_rgb has lower coverage but lower cpu;
    # cfg-front_rgb-rear_rgb has higher coverage but higher cpu - neither
    # dominates, both survive.
    assert set(resp.json()['pareto_front_configuration_ids']) == {'cfg-front_rgb', 'cfg-front_rgb-rear_rgb'}


# --- resource comparison section (optional nested section) ---------------------

def test_tradeoffs_resource_comparison_returns_deltas_and_comparability(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=20.0,
                        started_at='2026-01-01T00:00:00Z', ended_at='2026-01-01T00:00:10Z'),
        _resource_item(configuration_id='cfg-front_rgb-rear_rgb', value=30.0,
                        started_at='2026-01-01T00:00:00Z', ended_at='2026-01-01T00:00:10Z'),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
        'resource_comparison': {
            'baseline_configuration_id': 'cfg-front_rgb', 'candidate_configuration_id': 'cfg-front_rgb-rear_rgb',
        },
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['resource_comparison']
    assert comparison['comparability']['comparable'] is True
    cpu_delta = next(d for d in comparison['metric_deltas'] if d['metric'] == 'cpu_percent')
    assert cpu_delta['baseline'] == 20.0
    assert cpu_delta['candidate'] == 30.0
    assert cpu_delta['delta'] == 10.0


def test_tradeoffs_resource_comparison_unknown_baseline_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'resource_comparison': {'baseline_configuration_id': 'cfg-does-not-exist',
                                 'candidate_configuration_id': 'cfg-front_rgb'},
    })
    assert resp.status_code == 422


# --- v0.9 bug hunt: resource-only configurations (issues #112/#113) -----------
# A configuration named explicitly but never evaluated against this
# profile's requirements (no decision evidence) can still have real
# resource evidence - previously that configuration was correctly
# reported in `configurations` (Phase 76) but silently excluded from
# both `resource_comparison` and the Pareto front, since both were built
# from a list that only ever held decision-evaluated configurations.

def test_tradeoffs_resource_only_configuration_is_eligible_for_resource_comparison(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=20.0),
        _resource_item(configuration_id='cfg-resource-only', value=45.0),
    ]})

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'configuration_ids': ['cfg-front_rgb', 'cfg-resource-only'],
        'resource_metrics': ['cpu_percent'],
        'resource_comparison': {
            'baseline_configuration_id': 'cfg-front_rgb', 'candidate_configuration_id': 'cfg-resource-only',
        },
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()

    resource_only = next(c for c in body['configurations'] if c['configuration_id'] == 'cfg-resource-only')
    assert resource_only['policy_status'] is None  # genuinely no decision evidence
    assert resource_only['resource_profile']['metrics']['cpu_percent']['mean'] == 45.0  # genuinely has resource evidence

    # The actual regression: this used to 422 with "has no evidence in
    # this analysis" even though the configuration above clearly does.
    comparison = body['resource_comparison']
    assert comparison is not None
    cpu_delta = next(d for d in comparison['metric_deltas'] if d['metric'] == 'cpu_percent')
    assert cpu_delta['baseline'] == 20.0
    assert cpu_delta['candidate'] == 45.0
    assert cpu_delta['delta'] == 25.0


def test_tradeoffs_resource_only_configuration_appears_in_pareto_front(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=50.0),
        # No decision evidence at all for this one, but it has the lowest
        # cpu_percent of the two - it must win the (single-dimension)
        # Pareto front, not be silently dropped from consideration.
        _resource_item(configuration_id='cfg-resource-only', value=10.0),
    ]})

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'configuration_ids': ['cfg-front_rgb', 'cfg-resource-only'],
        'resource_metrics': ['cpu_percent'],
        'pareto_dimensions': {'cpu_percent': 'minimize'},
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()['pareto_front_configuration_ids'] == ['cfg-resource-only']


# --- v0.9 bug hunt: resource_constraints must reference requested metrics -----
# (issue #114) - a constraint naming a real, supported metric that simply
# wasn't included in resource_metrics used to silently produce zero
# constraint_results, with no error and no 'na' entry either.

def test_tradeoffs_constraint_metric_not_in_resource_metrics_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'resource_metrics': ['memory_mb'],  # cpu_percent deliberately not requested
        'resource_constraints': [{'metric': 'cpu_percent', 'operator': '<=', 'value': 50.0}],
    })
    assert resp.status_code == 422
    assert 'cpu_percent' in str(resp.json()['detail'])


def test_tradeoffs_constraint_with_resource_metrics_entirely_omitted_422(client):
    # The exact original repro: a constraint with no resource_metrics
    # field at all used to 200 with a silently-empty constraint_results
    # list rather than surfacing the mistake.
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'resource_constraints': [{'metric': 'cpu_percent', 'operator': '<=', 'value': 50.0}],
    })
    assert resp.status_code == 422


# --- v0.9 bug hunt: platform_id must reflect only requested metrics (#115) ----

def test_tradeoffs_platform_id_reflects_only_requested_metrics(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent', value=20.0,
                        platform_id='macbook-m2-dockerdesktop'),
        # A different metric, deliberately recorded under a different
        # platform - never requested by this call.
        _resource_item(configuration_id='cfg-front_rgb', metric='memory_mb', unit='MB', value=500.0,
                        platform_id='jetson-orin'),
    ]})

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    # Before the fix: platform_id would be 'unknown' (two distinct
    # platform_ids across all of this configuration's observations),
    # even though the one requested metric has a single, real platform.
    assert front['resource_profile']['platform_id'] == 'macbook-m2-dockerdesktop'
