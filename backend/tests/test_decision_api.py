"""Phase 56: decision API tests - POST /api/profiles/{id}/decision-analysis.
The `client` fixture lives in conftest.py. Domain-level algorithm
correctness (sufficiency semantics, minimality, dominance, gap
transitions) is already exhaustively covered in test_decision.py; these
tests only prove the wiring - request/response shapes, real evidence
discovery, sensor_ids resolution, and malformed-request handling.
"""

GROUND_TRUTH_LABELS = ['present', 'absent', 'present', 'present', 'absent']


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
        {'timestamp_ms': i * 100.0, 'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(GROUND_TRUTH_LABELS)
    ]})
    assert resp.status_code == 201, resp.text


def _seed_predictions_with_accuracy(client, session_id, sensor_ids, correct_count) -> None:
    # First `correct_count` predictions copy ground truth exactly, the
    # rest are deliberately flipped - exact accuracy, not probabilistic.
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


def _evaluate(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _create_two_requirement_profile(client) -> dict:
    body = {
        'id': 'p1', 'name': 'Decision Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [
            {'id': 'req-baseline', 'group_id': 'g1', 'name': 'Baseline', 'task': 'presence',
             'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}]},
            {'id': 'req-strict', 'group_id': 'g1', 'name': 'Strict', 'task': 'presence',
             'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.95}]},
        ],
    }
    resp = client.post('/api/profiles', json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_three_tier_scenario(client) -> None:
    # front_rgb alone: 3/5 = 0.6 -> fails both requirements (0% coverage).
    # + rear_rgb: 4/5 = 0.8 -> passes baseline, fails strict (50%).
    # + sim_thermal: 5/5 = 1.0 -> passes both (100%).
    _create_scenario(client)
    _create_session(client)
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb'], correct_count=3)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb', 'rear_rgb'], correct_count=4)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb', 'rear_rgb', 'sim_thermal'], correct_count=5)
    _evaluate(client)
    _create_two_requirement_profile(client)


DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 1.0,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}


# --- basic wiring ------------------------------------------------------------

def test_decision_analysis_unknown_profile_404(client):
    resp = client.post('/api/profiles/does-not-exist/decision-analysis', json={'policy': DEMO_POLICY})
    assert resp.status_code == 404


def test_decision_analysis_requires_policy_422(client):
    _create_two_requirement_profile(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={})
    assert resp.status_code == 422


def test_decision_analysis_wrong_type_for_configuration_ids_422(client):
    _create_two_requirement_profile(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY, 'configuration_ids': 'cfg-front_rgb',
    })
    assert resp.status_code == 422


# --- policy status / sensor_ids / sensor_count correctness -------------------

def test_decision_analysis_computes_policy_status_and_sensor_ids(client):
    _seed_three_tier_scenario(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={'policy': DEMO_POLICY})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    by_id = {c['configuration_id']: c for c in body['configurations']}
    front = by_id['cfg-front_rgb']
    assert set(front['sensor_ids']) == {'front_rgb'}
    assert front['sensor_count'] == 1
    assert front['policy_status'] == 'insufficient'
    assert front['summary']['pass_count'] == 0

    mid = by_id['cfg-front_rgb-rear_rgb']
    assert set(mid['sensor_ids']) == {'front_rgb', 'rear_rgb'}
    assert mid['policy_status'] == 'insufficient'  # 50% coverage, target is 100%
    assert mid['summary']['pass_count'] == 1

    full = by_id['cfg-front_rgb-rear_rgb-sim_thermal']
    assert set(full['sensor_ids']) == {'front_rgb', 'rear_rgb', 'sim_thermal'}
    assert full['policy_status'] == 'sufficient'
    assert full['summary']['pass_count'] == 2


def test_decision_analysis_minimal_sufficient_and_pareto_front(client):
    _seed_three_tier_scenario(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={'policy': DEMO_POLICY})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Only the 3-sensor configuration reaches 100% coverage - the only
    # sufficient, therefore the only minimal sufficient, configuration.
    assert body['sufficient_configuration_ids'] == ['cfg-front_rgb-rear_rgb-sim_thermal']
    assert body['minimal_sufficient_configuration_ids'] == ['cfg-front_rgb-rear_rgb-sim_thermal']

    # Pareto front: cfg-front_rgb-rear_rgb (2 sensors, 50%) is dominated
    # by cfg-front_rgb-rear_rgb-sim_thermal (3 sensors is NOT fewer, so
    # actually NOT dominated on sensor count - but cfg-front_rgb (1
    # sensor, 0%) is dominated by cfg-front_rgb-rear_rgb (2 sensors,
    # 50% - not fewer sensors, so also not strictly dominated on count
    # alone. Since none of the three configurations has both
    # same-or-fewer sensors AND same-or-better coverage than another,
    # all three are non-dominated - a genuine three-point trade-off
    # curve.
    assert set(body['pareto_front_configuration_ids']) == {
        'cfg-front_rgb', 'cfg-front_rgb-rear_rgb', 'cfg-front_rgb-rear_rgb-sim_thermal',
    }
    dominated_flags = {c['configuration_id']: c['dominated'] for c in body['configurations']}
    assert all(not dominated for dominated in dominated_flags.values())


def test_decision_analysis_explicit_configuration_id_with_no_evidence_reports_unknown(client):
    _seed_three_tier_scenario(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY,
        'configuration_ids': ['cfg-front_rgb', 'cfg-front_rgb-sim_depth'],  # never evaluated
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {c['configuration_id']: c for c in body['configurations']}

    assert by_id['cfg-front_rgb']['policy_status'] == 'insufficient'

    phantom = by_id['cfg-front_rgb-sim_depth']
    assert phantom['policy_status'] is None
    assert phantom['sensor_ids'] == []
    assert phantom['sensor_count'] == 0
    # Never silently dropped from sufficiency/minimality/Pareto either -
    # it just can't win any of them without a policy_status.
    assert 'cfg-front_rgb-sim_depth' not in body['sufficient_configuration_ids']


# --- gap_analysis: sensor addition -------------------------------------------

def test_decision_analysis_gap_analysis_addition_transitions_and_deltas(client):
    _seed_three_tier_scenario(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY,
        'gap_analysis': {
            'baseline_configuration_id': 'cfg-front_rgb',
            'candidate_configuration_id': 'cfg-front_rgb-rear_rgb',
        },
    })
    assert resp.status_code == 200, resp.text
    gap = resp.json()['gap_analysis']['addition']

    assert gap['added_sensor_ids'] == ['rear_rgb']
    assert gap['removed_sensor_ids'] == []
    assert gap['coverage_delta_pp'] == 50.0  # 0% -> 50%
    assert gap['transitions']['fail_to_pass'] == ['req-baseline']
    assert gap['transitions']['na_to_pass'] == []
    assert gap['transitions']['pass_to_fail'] == []
    assert gap['baseline_policy_status'] == 'insufficient'
    assert gap['candidate_policy_status'] == 'insufficient'


def test_decision_analysis_gap_analysis_unknown_baseline_422(client):
    _seed_three_tier_scenario(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY,
        'gap_analysis': {'baseline_configuration_id': 'cfg-does-not-exist'},
    })
    assert resp.status_code == 422


# --- gap_analysis: removal sweep ---------------------------------------------

def test_decision_analysis_gap_analysis_removal_sweep_reports_no_evidence(client):
    _seed_three_tier_scenario(client)
    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY,
        'gap_analysis': {
            'baseline_configuration_id': 'cfg-front_rgb-rear_rgb-sim_thermal',
            'include_removal_sweep': True,
        },
    })
    assert resp.status_code == 200, resp.text
    sweep = {r['removed_sensor_id']: r for r in resp.json()['gap_analysis']['removal_sweep']}

    # Removing sim_thermal -> cfg-front_rgb-rear_rgb, which WAS evaluated.
    assert sweep['sim_thermal']['configuration_id'] == 'cfg-front_rgb-rear_rgb'
    assert sweep['sim_thermal']['policy_status'] == 'insufficient'

    # Removing front_rgb or rear_rgb -> {rear_rgb, sim_thermal} or
    # {front_rgb, sim_thermal}, neither ever evaluated - NO EVIDENCE.
    assert sweep['front_rgb']['configuration_id'] is None
    assert sweep['front_rgb']['policy_status'] is None
    assert sweep['rear_rgb']['configuration_id'] is None
    assert sweep['rear_rgb']['policy_status'] is None
