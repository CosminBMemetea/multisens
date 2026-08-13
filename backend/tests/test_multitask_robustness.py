"""Phase 90 (v0.8): multi-task evaluation layer robustness. Same
discipline as Phase 40/51/62/76 (test_profile_robustness.py/
test_analysis_robustness.py/test_decision_robustness.py/
test_resource_robustness.py) applied to the v0.8 evaluator/comparison
layer - dedicated tests for the specific edge cases listed in issue #91,
not a re-run of what test_detection.py/test_detection_matching.py/
test_detection_metrics.py/test_regression.py/test_evaluators.py/
test_evaluate_api.py/test_evaluation_api_integration.py/
test_mixed_task_integration.py already exercise at the domain or API
level. Several bullets already have solid coverage elsewhere (unknown
evaluator_type at the API level, evaluator-type-mismatch comparisons,
detection common-set semantics) - those get a fresh, distinct scenario
here rather than a literal duplicate, per the same "not duplicated"
discipline test_resource_robustness.py documents.
"""
import pytest


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'robustness scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'robustness session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _box(x=0.1, y=0.1, width=0.2, height=0.2) -> dict:
    return {'x': x, 'y': y, 'width': width, 'height': height}


DETECTION_PARAMS = {'confidence_threshold': 0.5, 'iou_threshold': 0.5}


# --- bullet 1: malformed evaluator values reach the real API as a clean 422 -

def test_api_evaluate_detection_bbox_extending_past_frame_is_422_not_500(client):
    # Bbox validation is lazy (GroundTruth.value stays a generic dict at
    # ingestion - app/domain/detection.py's own module docstring) - the
    # malformed shape is accepted at /ground-truth/batch and only
    # rejected once /evaluate actually parses it.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'obstacle_detection',
         'value': {'objects': [{'id': 'o1', 'label': 'car', 'bbox': {'x': 0.9, 'y': 0.1, 'width': 0.5, 'height': 0.2}}]}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'det', 'sensor_ids': ['rgb'], 'task': 'obstacle_detection',
         'value': {'detections': [{'label': 'car', 'confidence': 0.9, 'bbox': _box()}]}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection', 'parameters': DETECTION_PARAMS,
    })
    assert resp.status_code == 422, resp.text
    assert 'bbox' in resp.json()['detail']


def test_api_evaluate_detection_negative_width_bbox_is_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'obstacle_detection',
         'value': {'objects': [{'id': 'o1', 'label': 'car', 'bbox': _box()}]}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'det', 'sensor_ids': ['rgb'], 'task': 'obstacle_detection',
         'value': {'detections': [{'label': 'car', 'confidence': 0.9,
                                    'bbox': {'x': 0.1, 'y': 0.1, 'width': -0.2, 'height': 0.2}}]}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection', 'parameters': DETECTION_PARAMS,
    })
    assert resp.status_code == 422, resp.text
    assert 'width' in resp.json()['detail']


def test_api_evaluate_detection_non_numeric_confidence_is_422_not_500(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'obstacle_detection',
         'value': {'objects': [{'id': 'o1', 'label': 'car', 'bbox': _box()}]}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'det', 'sensor_ids': ['rgb'], 'task': 'obstacle_detection',
         'value': {'detections': [{'label': 'car', 'confidence': 'high', 'bbox': _box()}]}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection', 'parameters': DETECTION_PARAMS,
    })
    assert resp.status_code == 422, resp.text
    assert 'confidence' in resp.json()['detail']


def test_api_evaluate_regression_single_pair_unit_mismatch_is_422_not_500(client):
    # Distinct from the cross-sample mixed-units test below - this is one
    # matched ground-truth/prediction PAIR disagreeing with itself
    # (build_regression_samples's own per-pair check), through the real
    # API rather than calling the domain function directly.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'distance_estimation', 'value': {'value': 2.0, 'unit': 'm'}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'reg', 'sensor_ids': ['depth'], 'task': 'distance_estimation',
         'value': {'value': 6.5, 'unit': 'ft'}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})
    assert resp.status_code == 422, resp.text
    assert 'unit mismatch' in resp.json()['detail']


def test_api_evaluate_regression_cross_sample_mixed_units_is_422_not_500(client):
    # Distinct from the single-pair test above - each individual pair
    # agrees with itself, but two different matched pairs for the SAME
    # configuration disagree with each other (compute_regression_metrics's
    # own cross-sample check), through the real API.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'distance_estimation', 'value': {'value': 2.0, 'unit': 'm'}},
        {'timestamp_ms': 100.0, 'task': 'distance_estimation', 'value': {'value': 10.0, 'unit': 'ft'}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'reg', 'sensor_ids': ['depth'], 'task': 'distance_estimation',
         'value': {'value': 2.1, 'unit': 'm'}},
        {'timestamp_ms': 101.0, 'source_id': 'reg', 'sensor_ids': ['depth'], 'task': 'distance_estimation',
         'value': {'value': 10.5, 'unit': 'ft'}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})
    assert resp.status_code == 422, resp.text
    assert 'mixed units' in resp.json()['detail']


# --- bullet 2: unknown evaluator_type - fresh angle: atomic, no partial write

def test_api_evaluate_unknown_evaluator_type_persists_nothing_for_any_configuration(client):
    # test_evaluate_api.py already proves the 422 itself (Phase 79) - the
    # fresh angle here is that the check happens once, before the
    # per-configuration loop, so a multi-configuration request fails
    # atomically: neither configuration ends up with a persisted (and
    # therefore misleadingly-labeled) evaluation result.
    _create_scenario(client)
    _create_session(client)
    for source_id, sensor_id in (('cls_a', 'rgb'), ('cls_b', 'depth')):
        resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
            {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        ]})
        resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
            {'timestamp_ms': 1.0, 'source_id': source_id, 'sensor_ids': [sensor_id], 'task': 'presence',
             'value': {'label': 'present'}},
        ]})
        assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'evaluator_type': 'pose_estimation'})
    assert resp.status_code == 422, resp.text
    assert 'pose_estimation' in resp.json()['detail']

    resp = client.get('/api/sessions/s1/evaluation')
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# --- bullet 3: missing/None-valued metrics flow through comparison cleanly -

def test_compare_detection_with_all_na_metrics_on_one_side_does_not_crash(client):
    # A configuration with zero ground truth and zero predictions for the
    # task has precision/recall/f1/mean_iou_matched all None (no
    # denominator, no fabricated 0.0 - detection.py's own MetricValue
    # rule) - compute_metric_delta already handles a None baseline/
    # candidate by design; this proves it survives real HTTP/JSON
    # end to end against a genuinely populated candidate, not just at the
    # pure-function level.
    _create_scenario(client)
    _create_session(client)
    # Baseline: a session-wide empty configuration - never submits any
    # ground truth or predictions for this task at all before /evaluate.
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'obstacle_detection', 'value': {'objects': []}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'det_empty', 'sensor_ids': ['rgb'], 'task': 'obstacle_detection',
         'value': {'detections': []}},
        {'timestamp_ms': 1.0, 'source_id': 'det_full', 'sensor_ids': ['depth'], 'task': 'obstacle_detection',
         'value': {'detections': []}},
    ]})
    assert resp.status_code == 201, resp.text
    # depth also gets a genuine hit on a second frame the rgb config never sees.
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 100.0, 'task': 'obstacle_detection',
         'value': {'objects': [{'id': 'o2', 'label': 'car', 'bbox': _box()}]}},
    ]})
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 101.0, 'source_id': 'det_full', 'sensor_ids': ['depth'], 'task': 'obstacle_detection',
         'value': {'detections': [{'label': 'car', 'confidence': 0.9, 'bbox': _box()}]}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection', 'parameters': DETECTION_PARAMS,
    })
    assert resp.status_code == 200, resp.text

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'obstacle_detection', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'], 'parameters': DETECTION_PARAMS,
    })
    assert resp.status_code == 200, resp.text
    side = resp.json()['comparisons'][0]['reported']
    precision_delta = side['metric_deltas']['precision']
    assert precision_delta['baseline'] is None  # 0/0 TP+FP for cfg-rgb - genuinely N/A
    assert precision_delta['candidate'] == pytest.approx(1.0)
    assert precision_delta['absolute'] is None  # never fabricated just because one side is real
    assert precision_delta['relative'] is None


# --- bullet 4: pre-v0.8 classification workflow, zero v0.8 fields anywhere -

def test_pre_v0_8_classification_workflow_unchanged_with_no_v0_8_fields_in_any_request(client):
    # Explicit self-review requirement (issue #91): a full evaluate+compare
    # round trip using ONLY the request shape that existed before v0.8 -
    # no evaluator_type, no parameters, anywhere - must behave byte-for-
    # byte like it always did. evaluator_type still ends up 'classification'
    # (the default), confusion_matrix still populates, details stays None.
    _create_scenario(client)
    _create_session(client)
    labels = ['present', 'absent', 'present', 'present']
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': i * 10.0, 'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(labels)
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': i * 10.0 + 1.0, 'source_id': 'cls_a', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'label': label}}
        for i, label in enumerate(labels)
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': i * 10.0 + 1.0, 'source_id': 'cls_b', 'sensor_ids': ['depth'], 'task': 'presence',
         'value': {'label': 'present'}}
        for i in range(4)
    ]})

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})  # no evaluator_type/parameters
    assert resp.status_code == 200, resp.text
    for result in resp.json():
        assert result['evaluator_type'] == 'classification'
        # Classification's own details carries confusion_matrix (Phase 79) -
        # evaluate_session also mirrors it onto the dedicated top-level
        # confusion_matrix field for pre-v0.8 frontend/callers, so both
        # must agree, never just one populated.
        assert result['details'] == {'confusion_matrix': result['confusion_matrix']}
        assert result['confusion_matrix'] is not None

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'],
    })  # no parameters field at all
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    assert comparison['validity']['status'] in ('valid', 'valid_with_warnings')
    assert comparison['reported']['metric_deltas']['accuracy']['baseline'] == pytest.approx(1.0)


# --- bullet 5: mixed-task profiles under real API load - fresh angle -------

def test_get_session_evaluation_lists_all_three_evaluator_types_together(client):
    # test_mixed_task_integration.py (Phase 85) already exercises
    # coverage/decision/tradeoffs/compare across a mixed-task profile -
    # the fresh angle here is the plain aggregate GET endpoint itself,
    # confirmed to return entries of all three evaluator_types together
    # with no type-specific filtering bug.
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'cls', 'sensor_ids': ['rgb'], 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 10.0, 'task': 'obstacle_detection',
         'value': {'objects': [{'id': 'o1', 'label': 'car', 'bbox': _box()}]}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 11.0, 'source_id': 'det', 'sensor_ids': ['depth'], 'task': 'obstacle_detection',
         'value': {'detections': [{'label': 'car', 'confidence': 0.9, 'bbox': _box()}]}},
    ]})
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 20.0, 'task': 'distance_estimation', 'value': {'value': 2.0, 'unit': 'm'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 21.0, 'source_id': 'reg', 'sensor_ids': ['thermal'], 'task': 'distance_estimation',
         'value': {'value': 2.1, 'unit': 'm'}},
    ]})

    client.post('/api/sessions/s1/evaluate', json={'task': 'presence', 'evaluator_type': 'classification'})
    client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection', 'parameters': DETECTION_PARAMS,
    })
    client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})

    resp = client.get('/api/sessions/s1/evaluation')
    assert resp.status_code == 200, resp.text
    results = resp.json()
    assert {r['evaluator_type'] for r in results} == {'classification', 'object_detection', 'regression'}
    assert len(results) == 3


# --- bullet 6: empty detections, both sides, through the real API ----------

def test_api_evaluate_empty_ground_truth_objects_and_empty_predictions_no_crash(client):
    # test_detection_matching.py already proves match_objects_in_frame([],
    # [], threshold) is all-zero at the pure-function level - this is the
    # same shape through real ingestion + /evaluate: a frame with zero GT
    # objects AND a matched prediction row with zero detections.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'obstacle_detection', 'value': {'objects': []}},
    ]})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'det', 'sensor_ids': ['rgb'], 'task': 'obstacle_detection',
         'value': {'detections': []}},
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={
        'task': 'obstacle_detection', 'evaluator_type': 'object_detection', 'parameters': DETECTION_PARAMS,
    })
    assert resp.status_code == 200, resp.text
    result = resp.json()[0]
    assert result['matched_samples'] == 1
    assert result['metrics']['true_positives'] == 0.0
    assert result['metrics']['false_positives'] == 0.0
    assert result['metrics']['false_negatives'] == 0.0
    assert result['metrics']['precision'] is None
    assert result['metrics']['recall'] is None
    assert result['metrics']['mean_iou_matched'] is None


# --- bullet 8: comparison common-set semantics for regression samples ------

def test_compare_common_set_sample_count_for_regression_equals_shared_matched_pairs(client):
    # Distinct from test_mixed_task_integration.py's own detection
    # common-set test (frames, not objects) - regression has no
    # analogous per-frame-vs-per-object distinction at all, since one
    # already-timestamp-matched pair already IS one sample
    # (regression.py's own "no matching engine of its own" docstring).
    # common_sample_count must equal exactly the ground-truth ids both
    # configurations matched, nothing more/less.
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'distance_estimation', 'value': {'value': 2.0, 'unit': 'm'}},
        {'timestamp_ms': 100.0, 'task': 'distance_estimation', 'value': {'value': 3.0, 'unit': 'm'}},
        {'timestamp_ms': 200.0, 'task': 'distance_estimation', 'value': {'value': 4.0, 'unit': 'm'}},
    ]})
    # baseline (rgb) only matches the first two ground-truth points.
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'reg_rgb', 'sensor_ids': ['rgb'], 'task': 'distance_estimation',
         'value': {'value': 2.1, 'unit': 'm'}},
        {'timestamp_ms': 101.0, 'source_id': 'reg_rgb', 'sensor_ids': ['rgb'], 'task': 'distance_estimation',
         'value': {'value': 3.2, 'unit': 'm'}},
    ]})
    # candidate (depth) matches all three.
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'reg_depth', 'sensor_ids': ['depth'], 'task': 'distance_estimation',
         'value': {'value': 2.05, 'unit': 'm'}},
        {'timestamp_ms': 101.0, 'source_id': 'reg_depth', 'sensor_ids': ['depth'], 'task': 'distance_estimation',
         'value': {'value': 3.05, 'unit': 'm'}},
        {'timestamp_ms': 201.0, 'source_id': 'reg_depth', 'sensor_ids': ['depth'], 'task': 'distance_estimation',
         'value': {'value': 4.05, 'unit': 'm'}},
    ]})
    client.post('/api/sessions/s1/evaluate', json={'task': 'distance_estimation', 'evaluator_type': 'regression'})

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'distance_estimation', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-depth'],
    })
    assert resp.status_code == 200, resp.text
    common_set = resp.json()['comparisons'][0]['common_set']
    assert common_set['common_sample_count'] == 2  # only the first two ground-truth points overlap
    assert common_set['baseline']['matched_samples'] == 2
    assert common_set['candidate']['matched_samples'] == 2
