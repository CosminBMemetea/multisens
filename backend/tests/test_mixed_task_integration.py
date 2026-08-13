"""Phase 85 (v0.8): verification, not new engine code - confirms what the
v0.8 architecture review already found by direct code reading (grepped
clean of any classification-specific coupling): coverage.py's
evaluate_criterion, analysis.py, decision.py, and resources.py are all
already evaluator-blind. A single mixed-task profile (classification +
object_detection + regression requirements on the same two
configurations) is exercised end to end through /coverage,
/decision-analysis, /tradeoffs, and /compare - the same real API calls
every other synthetic demo in this project uses, hand-verified numbers,
no shortcuts.

Scenario (two configurations, deliberately built so one fails every
requirement and the other passes every requirement - a clean,
unambiguous minimal-sufficient-set/Pareto story):

  cfg-rgb (1 sensor):
    person_presence accuracy   = 3/4 = 0.75   (bar: >= 0.90) -> FAIL
    obstacle_detection recall  = 1/2 = 0.50   (bar: >= 0.90) -> FAIL
    obstacle_range MAE         = 0.5          (bar: <= 0.20) -> FAIL

  cfg-depth-rgb (2 sensors):
    person_presence accuracy   = 4/4 = 1.00   -> PASS
    obstacle_detection recall  = 2/2 = 1.00   -> PASS
    obstacle_range MAE         = 0.1          -> PASS

cfg-rgb has fewer sensors but worse coverage; cfg-depth-rgb has more
sensors but better coverage - neither dominates the other (a genuine
trade-off, both survive on the Pareto front), matching this project's
own recurring demo pattern.
"""
import pytest

SESSION_ID = 's1'
CONFIGS = ['cfg-rgb', 'cfg-depth-rgb']


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'mixed-task demo'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id=SESSION_ID, scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'mixed-task session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _box(x=0.1, y=0.1, width=0.2, height=0.2) -> dict:
    return {'x': x, 'y': y, 'width': width, 'height': height}


def _seed_and_evaluate_all_tasks(client) -> None:
    # --- person_presence (classification): 4 samples ---
    labels = ['present', 'absent', 'present', 'present']
    client.post(f'/api/sessions/{SESSION_ID}/ground-truth/batch', json={'items': [
        {'timestamp_ms': i * 10.0, 'task': 'person_presence', 'value': {'label': label}}
        for i, label in enumerate(labels)
    ]})
    # cfg-rgb: 3/4 correct (last one wrong)
    rgb_predicted = ['present', 'absent', 'present', 'absent']
    client.post(f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': [
        {'timestamp_ms': i * 10.0 + 1.0, 'source_id': 'cls_rgb', 'sensor_ids': ['rgb'], 'task': 'person_presence',
         'value': {'label': label}}
        for i, label in enumerate(rgb_predicted)
    ]})
    # cfg-depth-rgb: 4/4 correct
    client.post(f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': [
        {'timestamp_ms': i * 10.0 + 1.0, 'source_id': 'cls_rgbd', 'sensor_ids': ['rgb', 'depth'],
         'task': 'person_presence', 'value': {'label': label}}
        for i, label in enumerate(labels)
    ]})

    # --- obstacle_detection (object_detection): 1 frame, 2 GT objects ---
    client.post(f'/api/sessions/{SESSION_ID}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 100.0, 'task': 'obstacle_detection', 'value': {'objects': [
            {'id': 'o1', 'label': 'person', 'bbox': _box(0.0, 0.0, 0.2, 0.2)},
            {'id': 'o2', 'label': 'person', 'bbox': _box(0.6, 0.6, 0.2, 0.2)},
        ]}},
    ]})
    # cfg-rgb: only detects the first object (recall 1/2 = 0.5)
    client.post(f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': [
        {'timestamp_ms': 101.0, 'source_id': 'det_rgb', 'sensor_ids': ['rgb'], 'task': 'obstacle_detection',
         'value': {'detections': [{'label': 'person', 'confidence': 0.9, 'bbox': _box(0.0, 0.0, 0.2, 0.2)}]}},
    ]})
    # cfg-depth-rgb: detects both (recall 2/2 = 1.0)
    client.post(f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': [
        {'timestamp_ms': 101.0, 'source_id': 'det_rgbd', 'sensor_ids': ['rgb', 'depth'], 'task': 'obstacle_detection',
         'value': {'detections': [
             {'label': 'person', 'confidence': 0.9, 'bbox': _box(0.0, 0.0, 0.2, 0.2)},
             {'label': 'person', 'confidence': 0.9, 'bbox': _box(0.6, 0.6, 0.2, 0.2)},
         ]}},
    ]})

    # --- obstacle_range (regression): 2 samples ---
    client.post(f'/api/sessions/{SESSION_ID}/ground-truth/batch', json={'items': [
        {'timestamp_ms': 200.0, 'task': 'obstacle_range', 'value': {'value': 2.0, 'unit': 'm'}},
        {'timestamp_ms': 210.0, 'task': 'obstacle_range', 'value': {'value': 3.0, 'unit': 'm'}},
    ]})
    # cfg-rgb: errors of 0.5 each -> MAE 0.5
    client.post(f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': [
        {'timestamp_ms': 201.0, 'source_id': 'reg_rgb', 'sensor_ids': ['rgb'], 'task': 'obstacle_range',
         'value': {'value': 2.5, 'unit': 'm'}},
        {'timestamp_ms': 211.0, 'source_id': 'reg_rgb', 'sensor_ids': ['rgb'], 'task': 'obstacle_range',
         'value': {'value': 3.5, 'unit': 'm'}},
    ]})
    # cfg-depth-rgb: errors of 0.1 each -> MAE 0.1
    client.post(f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': [
        {'timestamp_ms': 201.0, 'source_id': 'reg_rgbd', 'sensor_ids': ['rgb', 'depth'], 'task': 'obstacle_range',
         'value': {'value': 2.1, 'unit': 'm'}},
        {'timestamp_ms': 211.0, 'source_id': 'reg_rgbd', 'sensor_ids': ['rgb', 'depth'], 'task': 'obstacle_range',
         'value': {'value': 3.1, 'unit': 'm'}},
    ]})

    # --- evaluate every task ---
    resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={'task': 'person_presence', 'evaluator_type': 'classification'})
    assert resp.status_code == 200, resp.text
    resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection',
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })
    assert resp.status_code == 200, resp.text
    resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={'task': 'obstacle_range', 'evaluator_type': 'regression'})
    assert resp.status_code == 200, resp.text


def _create_mixed_profile(client) -> None:
    resp = client.post('/api/profiles', json={
        'id': 'mixed-p1', 'name': 'Mixed-Task Integration Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [
            {'id': 'req-presence', 'group_id': 'g1', 'name': 'Presence', 'task': 'person_presence',
             'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.90}]},
            {'id': 'req-detection', 'group_id': 'g1', 'name': 'Detection', 'task': 'obstacle_detection',
             'acceptance': [{'metric': 'recall', 'operator': '>=', 'value': 0.90}]},
            {'id': 'req-range', 'group_id': 'g1', 'name': 'Range', 'task': 'obstacle_range',
             'acceptance': [{'metric': 'mae', 'operator': '<=', 'value': 0.20}]},
        ],
    })
    assert resp.status_code == 201, resp.text


DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0, 'minimum_evidence_completeness': 1.0,
    'mandatory_requirements_must_pass': False, 'objective': 'minimize_sensor_count',
}


@pytest.fixture
def mixed_setup(client):
    _create_scenario(client)
    _create_session(client)
    _seed_and_evaluate_all_tasks(client)
    _create_mixed_profile(client)
    return client


# --- v0.4 acceptance criteria: evaluator-blind metric lookup ---------------

def test_coverage_pass_fail_correct_across_all_three_evaluator_types(mixed_setup):
    client = mixed_setup
    resp = client.post('/api/profiles/mixed-p1/coverage', json={'session_ids': [SESSION_ID]})
    assert resp.status_code == 200, resp.text
    coverages = {c['configuration_id']: c for c in resp.json()['configuration_coverages']}
    assert set(coverages) == set(CONFIGS)

    rgb_results = {r['requirement_id']: r for r in coverages['cfg-rgb']['requirement_results']}
    assert rgb_results['req-presence']['status'] == 'fail'
    assert rgb_results['req-detection']['status'] == 'fail'
    assert rgb_results['req-range']['status'] == 'fail'
    assert rgb_results['req-presence']['criteria'][0]['observed'] == pytest.approx(0.75)
    assert rgb_results['req-detection']['criteria'][0]['observed'] == pytest.approx(0.5)
    assert rgb_results['req-range']['criteria'][0]['observed'] == pytest.approx(0.5)

    rgbd_results = {r['requirement_id']: r for r in coverages['cfg-depth-rgb']['requirement_results']}
    assert rgbd_results['req-presence']['status'] == 'pass'
    assert rgbd_results['req-detection']['status'] == 'pass'
    assert rgbd_results['req-range']['status'] == 'pass'

    assert coverages['cfg-rgb']['root']['pass_count'] == 0
    assert coverages['cfg-rgb']['root']['fail_count'] == 3
    assert coverages['cfg-depth-rgb']['root']['pass_count'] == 3
    assert coverages['cfg-depth-rgb']['root']['requirement_coverage'] == pytest.approx(1.0)


# --- v0.6 decision support: mixed-task profile, zero engine changes -------

def test_decision_analysis_minimal_sufficient_set_and_pareto_across_mixed_tasks(mixed_setup):
    client = mixed_setup
    resp = client.post('/api/profiles/mixed-p1/decision-analysis', json={
        'policy': DEMO_POLICY, 'session_ids': [SESSION_ID],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body['minimal_sufficient_configuration_ids'] == ['cfg-depth-rgb']
    assert body['sufficient_configuration_ids'] == ['cfg-depth-rgb']
    # A genuine trade-off - fewer sensors but worse coverage (cfg-rgb) vs.
    # more sensors but full coverage (cfg-depth-rgb): neither dominates.
    assert set(body['pareto_front_configuration_ids']) == {'cfg-rgb', 'cfg-depth-rgb'}

    configs_by_id = {c['configuration_id']: c for c in body['configurations']}
    assert configs_by_id['cfg-rgb']['policy_status'] == 'insufficient'
    assert configs_by_id['cfg-depth-rgb']['policy_status'] == 'sufficient'


# --- v0.7 resource trade-offs: mixed-task decision evidence + resources ---

def test_tradeoffs_joins_mixed_task_decision_evidence_with_resource_evidence(mixed_setup):
    client = mixed_setup
    client.post(f'/api/sessions/{SESSION_ID}/resource-observations/batch', json={'items': [
        {'metric': 'cpu_percent', 'value': 20.0, 'unit': '%', 'quality': 'measured', 'source': 'psutil.cpu_percent',
         'platform_id': 'test-platform', 'configuration_id': 'cfg-rgb',
         'started_at': '2026-01-01T00:00:00Z', 'ended_at': '2026-01-01T00:00:10Z'},
        {'metric': 'cpu_percent', 'value': 35.0, 'unit': '%', 'quality': 'measured', 'source': 'psutil.cpu_percent',
         'platform_id': 'test-platform', 'configuration_id': 'cfg-depth-rgb',
         'started_at': '2026-01-01T00:00:00Z', 'ended_at': '2026-01-01T00:00:10Z'},
    ]})

    resp = client.post('/api/profiles/mixed-p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': SESSION_ID, 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    configs_by_id = {c['configuration_id']: c for c in resp.json()['configurations']}

    assert configs_by_id['cfg-rgb']['policy_status'] == 'insufficient'
    assert configs_by_id['cfg-rgb']['resource_profile']['metrics']['cpu_percent']['mean'] == 20.0
    assert configs_by_id['cfg-depth-rgb']['policy_status'] == 'sufficient'
    assert configs_by_id['cfg-depth-rgb']['resource_profile']['metrics']['cpu_percent']['mean'] == 35.0


# --- v0.3 comparison: numeric deltas for detection/regression metrics -----

def test_compare_produces_correct_deltas_for_detection_and_regression_metrics(mixed_setup):
    client = mixed_setup

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'obstacle_detection', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth-rgb'],
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    recall_delta = comparison['reported']['metric_deltas']['recall']
    assert recall_delta['baseline'] == pytest.approx(0.5)
    assert recall_delta['candidate'] == pytest.approx(1.0)
    assert recall_delta['absolute'] == pytest.approx(0.5)

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'obstacle_range', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth-rgb'],
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    mae_delta = comparison['reported']['metric_deltas']['mae']
    assert mae_delta['baseline'] == pytest.approx(0.5)
    assert mae_delta['candidate'] == pytest.approx(0.1)
    assert mae_delta['absolute'] == pytest.approx(-0.4)  # candidate - baseline, a real improvement


# --- common-set semantics: GT-id-based, not object-level for detection ----

def test_common_set_comparison_means_same_matched_gt_frames_for_detection(mixed_setup):
    # Both configurations matched the same one GT frame (timestamp_ms=100)
    # for obstacle_detection - common_sample_count counts frames, not the
    # individual objects within them (2 GT objects, but 1 frame).
    client = mixed_setup
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'obstacle_detection', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth-rgb'],
        'parameters': {'confidence_threshold': 0.5, 'iou_threshold': 0.5},
    })
    comparison = resp.json()['comparisons'][0]
    assert comparison['common_set']['common_sample_count'] == 1  # one frame, not two objects
