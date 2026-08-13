"""Phase 87 (v0.8): the shipped RideSafe object-detection demo's numbers
must not silently drift, same discipline as every prior demo guard
(test_ridesafe_demo.py, test_decision_demo.py, ...). Independently
recomputes IoU, greedy per-frame object matching, and session-level
TP/FP/FN/precision/recall/mean-matched-IoU straight from the raw JSON -
deliberately NOT importing app.domain.detection at all, a completely
separate re-derivation of the same greedy-IoU algorithm - and
cross-checks it against what the real /evaluate API returns end to end.

This is the first demo dataset built for the v0.8 detection evaluator
(issue #88) - see scripts/generate_ridesafe_detection_demo_data.py for
the full by-construction category breakdown (A: clean hit, B: IoU below
threshold, C: filtered by confidence, D: missing prediction, E: clean
hit plus a spurious extra) that produces the hand-derived numbers below.
"""
import json
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'ridesafe-detection-demo-data.json'

SESSION_ID = 'ridesafe-detection-demo-session'
CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.5

TASK_CONFIGS = {
    'front_scene_object_detection': 'cfg-ridesafe_front_rgb',
    'rear_scene_object_detection': 'cfg-ridesafe_rear_rgb',
}

# By construction (see scripts/generate_ridesafe_detection_demo_data.py's
# own docstring), not measured.
EXPECTED = {
    'front_scene_object_detection': {
        'true_positives': 80, 'false_positives': 20, 'false_negatives': 20,
        'precision': 0.80, 'recall': 0.80, 'f1': 0.80, 'mean_iou_matched': 0.65,
    },
    'rear_scene_object_detection': {
        'true_positives': 50, 'false_positives': 25, 'false_negatives': 50,
        'precision': 50 / 75, 'recall': 0.50, 'f1': 2 * (50 / 75) * 0.50 / ((50 / 75) + 0.50),
        'mean_iou_matched': 0.64,
    },
}

# frame-level (matching.py's own timestamp matching), not object-level -
# every category except D ("missing prediction") has exactly one
# Prediction row per GT row.
EXPECTED_FRAME_COUNTS = {
    'front_scene_object_detection': {'matched_samples': 95, 'unmatched_ground_truth': 5, 'unmatched_predictions': 0},
    'rear_scene_object_detection': {'matched_samples': 85, 'unmatched_ground_truth': 15, 'unmatched_predictions': 0},
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
    per_label_tp: dict[str, int] = {}
    for iou, gi, di in candidates:
        if gi in matched_gt or di in matched_det:
            continue
        matched_gt.add(gi)
        matched_det.add(di)
        ious.append(iou)
        label = objects[gi]['label']
        per_label_tp[label] = per_label_tp.get(label, 0) + 1

    per_label_fp = {}
    for di, d in enumerate(detections):
        if di not in matched_det:
            per_label_fp[d['label']] = per_label_fp.get(d['label'], 0) + 1
    per_label_fn = {}
    for gi, o in enumerate(objects):
        if gi not in matched_gt:
            per_label_fn[o['label']] = per_label_fn.get(o['label'], 0) + 1

    return len(matched_gt), len(detections) - len(matched_det), len(objects) - len(matched_gt), ious, per_label_tp, per_label_fp, per_label_fn


def _independent_metrics(ground_truth: list[dict], predictions: list[dict]) -> dict:
    matched, unmatched_gt, unmatched_pred = _nearest_timestamp_match(ground_truth, predictions)

    tp = fp = fn = 0
    ious: list[float] = []
    per_class: dict[str, dict[str, int]] = {}

    def _accumulate(label: str, key: str, count: int) -> None:
        if count == 0:
            return
        per_class.setdefault(label, {'true_positives': 0, 'false_positives': 0, 'false_negatives': 0})
        per_class[label][key] += count

    for gt, pred in matched:
        objects = gt['value']['objects']
        detections = [d for d in pred['value']['detections'] if d['confidence'] >= CONFIDENCE_THRESHOLD]
        frame_tp, frame_fp, frame_fn, frame_ious, tp_by_label, fp_by_label, fn_by_label = _match_frame_objects(
            objects, detections, IOU_THRESHOLD,
        )
        tp += frame_tp
        fp += frame_fp
        fn += frame_fn
        ious += frame_ious
        for label, count in tp_by_label.items():
            _accumulate(label, 'true_positives', count)
        for label, count in fp_by_label.items():
            _accumulate(label, 'false_positives', count)
        for label, count in fn_by_label.items():
            _accumulate(label, 'false_negatives', count)

    for gt in unmatched_gt:
        for o in gt['value']['objects']:
            fn += 1
            _accumulate(o['label'], 'false_negatives', 1)
    for pred in unmatched_pred:
        for d in pred['value']['detections']:
            if d['confidence'] >= CONFIDENCE_THRESHOLD:
                fp += 1
                _accumulate(d['label'], 'false_positives', 1)

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) > 0 else None
    mean_iou_matched = (sum(ious) / len(ious)) if ious else None

    return {
        'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
        'precision': precision, 'recall': recall, 'f1': f1, 'mean_iou_matched': mean_iou_matched,
        'per_class': per_class,
        'matched_samples': len(matched), 'unmatched_ground_truth': len(unmatched_gt),
        'unmatched_predictions': len(unmatched_pred),
    }


def test_dataset_file_has_expected_shape():
    dataset = _load_data()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['sessions']) == 1
    assert 'synthetic' in dataset['scenario']['tags']
    assert set(dataset['tasks']) == set(TASK_CONFIGS)
    assert dataset['evaluator_parameters'] == {
        'confidence_threshold': CONFIDENCE_THRESHOLD, 'iou_threshold': IOU_THRESHOLD,
    }
    ground_truth = dataset['ground_truth'][SESSION_ID]
    predictions = dataset['predictions'][SESSION_ID]
    for task in TASK_CONFIGS:
        assert sum(1 for g in ground_truth if g['task'] == task) == 100
        for g in ground_truth:
            if g['task'] == task:
                assert g['metadata']['synthetic'] is True
                assert len(g['value']['objects']) == 1
        for p in predictions:
            if p['task'] == task:
                assert p['metadata']['synthetic'] is True


def test_no_professional_domain_or_safety_certification_language():
    # Same negation-aware scan as test_ridesafe_demo.py's own Phase 73
    # guard (issue #88's explicit self-review requirement): a negated
    # mention ("not a safety-certification system") is the disclaimer
    # itself, never a violation - only an unnegated (positive) claim
    # counts.
    negation_cues = ('not a ', 'not an ', 'never a ', 'never an ', 'nor ', 'no ')
    forbidden = ['driver monitoring', 'occupant monitoring', 'safety certification',
                 'safety-certification', 'certified', 'compliant', 'guarantees safety',
                 'prevents incidents', 'crime prevention', 'autonomous', 'navigation',
                 'flight safety']

    text = DATA_PATH.read_text().lower()
    for term in forbidden:
        start = 0
        while (idx := text.find(term, start)) != -1:
            preceding = text[max(0, idx - 20):idx]
            assert any(cue in preceding for cue in negation_cues), (
                f"found unnegated forbidden term '{term}' in dataset: ...{text[max(0, idx - 40):idx + 40]}..."
            )
            start = idx + len(term)


def test_independent_metrics_match_construction_targets():
    dataset = _load_data()
    ground_truth = dataset['ground_truth'][SESSION_ID]
    predictions = dataset['predictions'][SESSION_ID]

    for task, expected in EXPECTED.items():
        task_gt = [g for g in ground_truth if g['task'] == task]
        task_pred = [p for p in predictions if p['task'] == task]
        result = _independent_metrics(task_gt, task_pred)

        assert result['true_positives'] == expected['true_positives']
        assert result['false_positives'] == expected['false_positives']
        assert result['false_negatives'] == expected['false_negatives']
        assert result['precision'] == pytest.approx(expected['precision'])
        assert result['recall'] == pytest.approx(expected['recall'])
        assert result['f1'] == pytest.approx(expected['f1'])
        assert result['mean_iou_matched'] == pytest.approx(expected['mean_iou_matched'])

        frame_counts = EXPECTED_FRAME_COUNTS[task]
        assert result['matched_samples'] == frame_counts['matched_samples']
        assert result['unmatched_ground_truth'] == frame_counts['unmatched_ground_truth']
        assert result['unmatched_predictions'] == frame_counts['unmatched_predictions']

        # Both labels appear (LABELS alternates by frame index) and their
        # per-class counts sum back to the session totals - an
        # independent recomputation, not a copy of production's own
        # _aggregate_per_class.
        assert set(result['per_class']) == {'vehicle', 'pedestrian'}
        assert sum(c['true_positives'] for c in result['per_class'].values()) == expected['true_positives']
        assert sum(c['false_positives'] for c in result['per_class'].values()) == expected['false_positives']
        assert sum(c['false_negatives'] for c in result['per_class'].values()) == expected['false_negatives']


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


def test_api_evaluate_matches_independently_computed_values(client):
    dataset = _load_data()
    _seed_demo(client)

    for task, config_id in TASK_CONFIGS.items():
        resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={
            'task': task, 'evaluator_type': 'object_detection',
            'parameters': dataset['evaluator_parameters'],
        })
        assert resp.status_code == 200, resp.text
        results = resp.json()
        assert len(results) == 1
        result = results[0]
        assert result['configuration_id'] == config_id
        assert result['evaluator_type'] == 'object_detection'

        expected = EXPECTED[task]
        metrics = result['metrics']
        assert metrics['true_positives'] == pytest.approx(expected['true_positives'])
        assert metrics['false_positives'] == pytest.approx(expected['false_positives'])
        assert metrics['false_negatives'] == pytest.approx(expected['false_negatives'])
        assert metrics['precision'] == pytest.approx(expected['precision'])
        assert metrics['recall'] == pytest.approx(expected['recall'])
        assert metrics['f1'] == pytest.approx(expected['f1'])
        assert metrics['mean_iou_matched'] == pytest.approx(expected['mean_iou_matched'])

        frame_counts = EXPECTED_FRAME_COUNTS[task]
        assert result['matched_samples'] == frame_counts['matched_samples']
        assert result['unmatched_ground_truth'] == frame_counts['unmatched_ground_truth']
        assert result['unmatched_predictions'] == frame_counts['unmatched_predictions']
        assert result['sample_count'] == 100

        assert set(result['details']['per_class']) == {'vehicle', 'pedestrian'}
        assert result['details']['parameters'] == dataset['evaluator_parameters']


def test_api_rejects_evaluation_without_explicit_parameters(client):
    # object_detection has no hidden default confidence/IoU threshold
    # (v0.8 architecture review Q14, detection.py's own
    # parse_detection_parameters) - omitting `parameters` entirely must
    # be a clean 422, never a silent classification-style fallback.
    _seed_demo(client)
    resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={
        'task': 'front_scene_object_detection', 'evaluator_type': 'object_detection',
    })
    assert resp.status_code == 422, resp.text
