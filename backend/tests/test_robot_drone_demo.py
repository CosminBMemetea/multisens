"""Phase 89 (v0.8): the shipped Robot/Drone Sensing Demo's numbers must
not silently drift - same discipline as Phase 87/88's own detection demo
guards. Independently recomputes both evaluators straight from the raw
JSON - IoU + greedy per-frame object matching for `obstacle_detection`
(zero imports from app.domain.detection), plain MAE/RMSE/bias/median for
`distance_estimation` (zero imports from app.domain.regression) - and
cross-checks against the real /evaluate API end to end.

Also carries this demo's own explicit overclaim scan (issue #90's
acceptance criteria): no "autonomous," "navigation," or "flight safety"
language anywhere in the shipped dataset, beyond the disclaimer's own
negated mention.
"""
import json
import statistics
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'robot-drone-demo-data.json'

SESSION_ID = 'robot-drone-demo-session'
CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.5

DETECTION_CONFIGS = {
    'robot_front_rgb': 'cfg-robot_front_rgb',
    'sim_depth': 'cfg-sim_depth',
}
DISTANCE_CONFIGS = {
    'sim_range': 'cfg-sim_range',
    'sim_depth': 'cfg-sim_depth',
}

# By construction (see scripts/generate_robot_drone_demo_data.py's own
# docstring), not measured.
EXPECTED_DETECTION = {
    'robot_front_rgb': {
        'true_positives': 70, 'false_positives': 15, 'false_negatives': 30,
        'precision': 70 / 85, 'recall': 0.70, 'f1': 2 * (70 / 85) * 0.70 / ((70 / 85) + 0.70),
        'mean_iou_matched': 44 / 70,
        'frames': {'matched_samples': 90, 'unmatched_ground_truth': 10, 'unmatched_predictions': 0},
    },
    'sim_depth': {
        'true_positives': 55, 'false_positives': 25, 'false_negatives': 45,
        'precision': 55 / 80, 'recall': 0.55, 'f1': 2 * (55 / 80) * 0.55 / ((55 / 80) + 0.55),
        'mean_iou_matched': 35 / 55,
        'frames': {'matched_samples': 85, 'unmatched_ground_truth': 15, 'unmatched_predictions': 0},
    },
}

EXPECTED_DISTANCE = {
    'sim_range': {
        'mae': 0.06, 'bias': 0.0, 'median_absolute_error': 0.05,
        'rmse': ((0.05**2 + 0.05**2 + 0.10**2 + 0.10**2 + 0.0**2) / 5) ** 0.5,
    },
    'sim_depth': {
        'mae': 0.30, 'bias': 0.06, 'median_absolute_error': 0.30,
        'rmse': ((0.30**2 + 0.20**2 + 0.50**2 + 0.40**2 + 0.10**2) / 5) ** 0.5,
    },
}


def _load_data() -> dict:
    return json.loads(DATA_PATH.read_text())


def _iou(a: dict, b: dict) -> float:
    x_left = max(a['x'], b['x'])
    y_top = max(a['y'], b['y'])
    x_right = min(a['x'] + a['width'], b['x'] + b['width'])
    y_bottom = min(a['y'] + a['height'], b['y'] + b['height'])
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    intersection = (x_right - x_left) * (y_bottom - y_top)
    area_a = a['width'] * a['height']
    area_b = b['width'] * b['height']
    return intersection / (area_a + area_b - intersection)


def _nearest_timestamp_match(ground_truth: list[dict], predictions: list[dict], tolerance_ms: float = 100.0):
    preds = sorted(predictions, key=lambda p: p['timestamp_ms'])
    used: set[int] = set()
    matched = []
    unmatched_gt = []
    for gt in sorted(ground_truth, key=lambda g: g['timestamp_ms']):
        best_idx, best_dist = None, None
        for idx, p in enumerate(preds):
            if idx in used:
                continue
            dist = abs(p['timestamp_ms'] - gt['timestamp_ms'])
            if dist <= tolerance_ms and (best_dist is None or dist < best_dist):
                best_idx, best_dist = idx, dist
        if best_idx is None:
            unmatched_gt.append(gt)
        else:
            used.add(best_idx)
            matched.append((gt, preds[best_idx]))
    unmatched_pred = [p for idx, p in enumerate(preds) if idx not in used]
    return matched, unmatched_gt, unmatched_pred


def _match_frame_objects(objects: list[dict], detections: list[dict], iou_threshold: float):
    candidates = []
    for gi, o in enumerate(objects):
        for di, d in enumerate(detections):
            if o['label'] != d['label']:
                continue
            iou = _iou(o['bbox'], d['bbox'])
            if iou >= iou_threshold:
                candidates.append((iou, gi, di))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    matched_gt: set[int] = set()
    matched_det: set[int] = set()
    ious: list[float] = []
    for iou, gi, di in candidates:
        if gi in matched_gt or di in matched_det:
            continue
        matched_gt.add(gi)
        matched_det.add(di)
        ious.append(iou)

    return len(matched_gt), len(detections) - len(matched_det), len(objects) - len(matched_gt), ious


def _independent_detection_metrics(ground_truth: list[dict], predictions: list[dict]) -> dict:
    matched, unmatched_gt, unmatched_pred = _nearest_timestamp_match(ground_truth, predictions)

    tp = fp = fn = 0
    ious: list[float] = []
    for gt, pred in matched:
        objects = gt['value']['objects']
        detections = [d for d in pred['value']['detections'] if d['confidence'] >= CONFIDENCE_THRESHOLD]
        frame_tp, frame_fp, frame_fn, frame_ious = _match_frame_objects(objects, detections, IOU_THRESHOLD)
        tp += frame_tp
        fp += frame_fp
        fn += frame_fn
        ious += frame_ious

    for gt in unmatched_gt:
        fn += len(gt['value']['objects'])
    for pred in unmatched_pred:
        fp += sum(1 for d in pred['value']['detections'] if d['confidence'] >= CONFIDENCE_THRESHOLD)

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) > 0 else None
    mean_iou_matched = (sum(ious) / len(ious)) if ious else None

    return {
        'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
        'precision': precision, 'recall': recall, 'f1': f1, 'mean_iou_matched': mean_iou_matched,
        'frames': {
            'matched_samples': len(matched), 'unmatched_ground_truth': len(unmatched_gt),
            'unmatched_predictions': len(unmatched_pred),
        },
    }


def _independent_regression_metrics(ground_truth: list[dict], predictions: list[dict]) -> dict:
    matched, _, _ = _nearest_timestamp_match(ground_truth, predictions)
    errors = [p['value']['value'] - g['value']['value'] for g, p in matched]
    absolute_errors = sorted(abs(e) for e in errors)
    return {
        'mae': statistics.fmean(absolute_errors),
        'rmse': statistics.fmean(e * e for e in errors) ** 0.5,
        'bias': statistics.fmean(errors),
        'median_absolute_error': statistics.median(absolute_errors),
        'matched_samples': len(matched),
    }


def test_dataset_file_has_expected_shape():
    dataset = _load_data()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['sessions']) == 1
    assert 'synthetic' in dataset['scenario']['tags']
    assert set(dataset['tasks']) == {'obstacle_detection', 'distance_estimation'}

    ground_truth = dataset['ground_truth'][SESSION_ID]
    predictions = dataset['predictions'][SESSION_ID]
    assert sum(1 for g in ground_truth if g['task'] == 'obstacle_detection') == 100
    assert sum(1 for g in ground_truth if g['task'] == 'distance_estimation') == 100
    for g in ground_truth:
        assert g['metadata']['synthetic'] is True
    for p in predictions:
        assert p['metadata']['synthetic'] is True


def test_no_overclaim_language():
    # Explicit acceptance criteria (issue #90): no "autonomous,"
    # "navigation," or "flight safety" anywhere in the shipped dataset,
    # beyond the disclaimer's own negated mention - same negation-aware
    # scan pattern as test_ridesafe_demo.py/test_propertywatch_demo.py's
    # own guards, extended with robotics-specific terms.
    negation_cues = ('not a ', 'not an ', 'never a ', 'never an ', 'nor ', 'no ')
    forbidden = ['autonomous', 'navigation system', 'drone control', 'flight safety',
                 'obstacle avoidance', 'certified', 'biometric',
                 'face recognition', 'guarantees safety']

    text = DATA_PATH.read_text().lower()
    for term in forbidden:
        start = 0
        while (idx := text.find(term, start)) != -1:
            preceding = text[max(0, idx - 30):idx]
            assert any(cue in preceding for cue in negation_cues), (
                f"found unnegated forbidden term '{term}' in dataset: ...{text[max(0, idx - 50):idx + 50]}..."
            )
            start = idx + len(term)


def test_distinct_from_generic_sensor_evaluation_lab():
    # Explicit scope requirement (issue #90): kept clearly distinct in
    # name/theme from the retired-and-rethemed "Generic Sensor Evaluation
    # Lab" (sensor-lab-demo, v0.4/v0.5) - a completely different, older
    # demo. Not merely a naming coincidence check - confirms the IDs
    # genuinely do not collide.
    dataset = _load_data()
    assert dataset['scenario']['id'] != 'sensor-lab-demo-v1.0'
    assert 'sensor-lab-demo' not in dataset['scenario']['id']
    assert dataset['sessions'][0]['id'] not in ('lab-day-clear', 'lab-day-glasses', 'lab-night-clear')


def test_independent_detection_metrics_match_construction_targets():
    dataset = _load_data()
    ground_truth = [g for g in dataset['ground_truth'][SESSION_ID] if g['task'] == 'obstacle_detection']
    predictions = [p for p in dataset['predictions'][SESSION_ID] if p['task'] == 'obstacle_detection']

    for sensor_id, expected in EXPECTED_DETECTION.items():
        sensor_predictions = [p for p in predictions if p['sensor_ids'] == [sensor_id]]
        result = _independent_detection_metrics(ground_truth, sensor_predictions)

        assert result['true_positives'] == expected['true_positives']
        assert result['false_positives'] == expected['false_positives']
        assert result['false_negatives'] == expected['false_negatives']
        assert result['precision'] == pytest.approx(expected['precision'])
        assert result['recall'] == pytest.approx(expected['recall'])
        assert result['f1'] == pytest.approx(expected['f1'])
        assert result['mean_iou_matched'] == pytest.approx(expected['mean_iou_matched'])
        assert result['frames'] == expected['frames']


def test_independent_regression_metrics_match_construction_targets():
    dataset = _load_data()
    ground_truth = [g for g in dataset['ground_truth'][SESSION_ID] if g['task'] == 'distance_estimation']
    predictions = [p for p in dataset['predictions'][SESSION_ID] if p['task'] == 'distance_estimation']

    for sensor_id, expected in EXPECTED_DISTANCE.items():
        sensor_predictions = [p for p in predictions if p['sensor_ids'] == [sensor_id]]
        result = _independent_regression_metrics(ground_truth, sensor_predictions)

        assert result['matched_samples'] == 100
        assert result['mae'] == pytest.approx(expected['mae'])
        assert result['rmse'] == pytest.approx(expected['rmse'])
        assert result['bias'] == pytest.approx(expected['bias'])
        assert result['median_absolute_error'] == pytest.approx(expected['median_absolute_error'])


def _seed_demo(client) -> None:
    dataset = _load_data()
    resp = client.post('/api/scenarios', json=dataset['scenario'])
    assert resp.status_code == 201, resp.text

    session = dataset['sessions'][0]
    resp = client.post('/api/sessions', json=session)
    assert resp.status_code == 201, resp.text

    resp = client.post(
        f'/api/sessions/{SESSION_ID}/ground-truth/batch', json={'items': dataset['ground_truth'][SESSION_ID]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
    resp = client.post(
        f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': dataset['predictions'][SESSION_ID]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text


def test_api_evaluate_detection_matches_independently_computed_values(client):
    dataset = _load_data()
    _seed_demo(client)

    for sensor_id, config_id in DETECTION_CONFIGS.items():
        resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={
            'task': 'obstacle_detection', 'configuration_ids': [config_id],
            'evaluator_type': 'object_detection', 'parameters': dataset['detection_parameters'],
        })
        assert resp.status_code == 200, resp.text
        results = resp.json()
        assert len(results) == 1
        result = results[0]
        assert result['evaluator_type'] == 'object_detection'

        expected = EXPECTED_DETECTION[sensor_id]
        metrics = result['metrics']
        assert metrics['true_positives'] == pytest.approx(expected['true_positives'])
        assert metrics['false_positives'] == pytest.approx(expected['false_positives'])
        assert metrics['false_negatives'] == pytest.approx(expected['false_negatives'])
        assert metrics['precision'] == pytest.approx(expected['precision'])
        assert metrics['recall'] == pytest.approx(expected['recall'])
        assert metrics['f1'] == pytest.approx(expected['f1'])
        assert metrics['mean_iou_matched'] == pytest.approx(expected['mean_iou_matched'])
        assert result['matched_samples'] == expected['frames']['matched_samples']
        assert result['unmatched_ground_truth'] == expected['frames']['unmatched_ground_truth']


def test_api_evaluate_regression_matches_independently_computed_values(client):
    _seed_demo(client)

    for sensor_id, config_id in DISTANCE_CONFIGS.items():
        resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={
            'task': 'distance_estimation', 'configuration_ids': [config_id],
            'evaluator_type': 'regression', 'parameters': {},
        })
        assert resp.status_code == 200, resp.text
        results = resp.json()
        assert len(results) == 1
        result = results[0]
        assert result['evaluator_type'] == 'regression'

        expected = EXPECTED_DISTANCE[sensor_id]
        metrics = result['metrics']
        assert metrics['mae'] == pytest.approx(expected['mae'])
        assert metrics['rmse'] == pytest.approx(expected['rmse'])
        assert metrics['bias'] == pytest.approx(expected['bias'])
        assert metrics['median_absolute_error'] == pytest.approx(expected['median_absolute_error'])
        assert result['matched_samples'] == 100
        assert result['details']['unit'] == 'm'
