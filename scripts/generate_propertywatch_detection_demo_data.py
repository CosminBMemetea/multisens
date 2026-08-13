#!/usr/bin/env python3
"""Generates examples/profiles/propertywatch-detection-demo-data.json - a
deterministic synthetic object-detection dataset for the v0.8
PropertyWatch detection demo (Phase 88).

Run once, output committed to git:

    python3 scripts/generate_propertywatch_detection_demo_data.py

Extends the existing PropertyWatch reference story (property_entrance_rgb/
property_storage_rgb/property_indoor_rgb, generic home/garage/workshop/
storage/small-warehouse monitoring - see propertywatch-demo-data.json's
own docstring for the full framing discipline) with the v0.8 detection
evaluator. No biometric identity features of any kind - detected labels
are generic object categories (package/vehicle/pet/person-as-a-generic-
moving-object), never face recognition or person identification; purpose
is sensor/system evaluation, not identifying who someone is. Deliberately
a SEPARATE dataset/session from propertywatch-demo-data.json's own
classification session - this never touches that file, so Phase 74's own
"numbers must not silently drift" guard (test_propertywatch_demo.py)
stays completely unaffected.

Same five deterministic frame categories Phase 87
(scripts/generate_ridesafe_detection_demo_data.py) already established -
reused here verbatim rather than re-derived, same bbox geometry (IoU 0.6
for a clean hit, IoU 0.25 for a too-imprecise miss, IoU 1.0 for a
filtered/spurious pair):

    A: clean hit (IoU 0.6, above threshold)             -> 1 true positive
    B: too imprecise (IoU 0.25, below threshold)         -> 1 FN + 1 FP
    C: filtered by confidence (IoU 1.0, confidence 0.30) -> 1 FN
    D: missing prediction (no Prediction row at all)     -> 1 FN
    E: clean hit + spurious extra (IoU 1.0 + non-overlap) -> 1 TP + 1 FP

Three tasks, one per camera position, with a deliberately different
quality tier each - entrance (the flagship "worth its resource load"
camera, v0.7) has the strongest detection quality, indoor the weakest,
by construction:

    entrance_package_detection: A=75 B=10 C=5  D=5  E=5
    storage_object_detection:   A=55 B=15 C=10 D=15 E=5
    indoor_object_detection:    A=40 B=20 C=15 D=20 E=5

Hand-derived aggregate numbers (cross-checked by
backend/tests/test_propertywatch_detection_demo.py against an
independent recomputation AND the real /evaluate API - never just
asserted here):

    entrance: TP=80 FP=15 FN=20  precision=0.8421 recall=0.80 f1=0.8205 mean_iou_matched=0.625
    storage:  TP=60 FP=20 FN=40  precision=0.75   recall=0.60 f1=0.6667 mean_iou_matched=0.6333
    indoor:   TP=45 FP=25 FN=55  precision=0.6429 recall=0.45 f1=0.5295 mean_iou_matched=0.6444
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'propertywatch-detection-demo-data.json'

SAMPLE_COUNT = 100
SCENARIO_ID = 'synthetic-propertywatch-detection-demo'
SESSION_ID = 'propertywatch-detection-demo-session'

CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.5

GT_BBOX = {'x': 0.30, 'y': 0.30, 'width': 0.20, 'height': 0.20}
CATEGORY_A = {'x_offset': 0.05, 'confidence': 0.9}   # IoU 0.6 - clean hit
CATEGORY_B = {'x_offset': 0.12, 'confidence': 0.9}   # IoU 0.25 - below threshold
CATEGORY_C = {'x_offset': 0.0, 'confidence': 0.3}    # IoU 1.0 but filtered
SPURIOUS_BBOX = {'x': 0.02, 'y': 0.02, 'width': 0.08, 'height': 0.08}  # no overlap with GT_BBOX

# task -> (source_id, sensor_id, labels, a, b, c, d, e)
TASKS = [
    ('entrance_package_detection', 'property_entrance_rgb_detector', 'property_entrance_rgb',
     ('package', 'person'), 75, 10, 5, 5, 5),
    ('storage_object_detection', 'property_storage_rgb_detector', 'property_storage_rgb',
     ('vehicle', 'person'), 55, 15, 10, 15, 5),
    ('indoor_object_detection', 'property_indoor_rgb_detector', 'property_indoor_rgb',
     ('person', 'pet'), 40, 20, 15, 20, 5),
]


def _category_for_index(i: int, a: int, b: int, c: int, d: int) -> str:
    if i < a:
        return 'A'
    if i < a + b:
        return 'B'
    if i < a + b + c:
        return 'C'
    if i < a + b + c + d:
        return 'D'
    return 'E'


def _detection(label: str, x: float, confidence: float) -> dict:
    return {'label': label, 'confidence': confidence, 'bbox': {**GT_BBOX, 'x': x}}


def build_task_data(
    task: str, source_id: str, sensor_id: str, labels: tuple[str, str], a: int, b: int, c: int, d: int, e: int,
) -> tuple[list[dict], list[dict]]:
    assert a + b + c + d + e == SAMPLE_COUNT
    ground_truth = []
    predictions = []
    for i in range(SAMPLE_COUNT):
        label = labels[i % 2]
        timestamp_ms = float(i * 1000)
        category = _category_for_index(i, a, b, c, d)
        gt_id = f'gt-{SESSION_ID}-{task}-{i:04d}'

        ground_truth.append({
            'id': gt_id,
            'timestamp_ms': timestamp_ms,
            'task': task,
            'value': {'objects': [{'id': f'obj-{i:04d}-0', 'label': label, 'bbox': GT_BBOX}]},
            'metadata': {'synthetic': True},
        })

        if category == 'D':
            continue  # no Prediction row at all for this frame

        if category == 'A':
            detections = [_detection(label, GT_BBOX['x'] + CATEGORY_A['x_offset'], CATEGORY_A['confidence'])]
        elif category == 'B':
            detections = [_detection(label, GT_BBOX['x'] + CATEGORY_B['x_offset'], CATEGORY_B['confidence'])]
        elif category == 'C':
            detections = [_detection(label, GT_BBOX['x'] + CATEGORY_C['x_offset'], CATEGORY_C['confidence'])]
        else:  # E
            detections = [
                _detection(label, GT_BBOX['x'], 0.9),
                _detection(label, SPURIOUS_BBOX['x'], 0.9),
            ]

        predictions.append({
            'id': f'pred-{SESSION_ID}-{task}-{i:04d}',
            'timestamp_ms': timestamp_ms + 2.0,
            'source_id': source_id,
            'sensor_ids': [sensor_id],
            'task': task,
            'value': {'detections': detections},
            'metadata': {'synthetic': True, 'category': category},
        })
    return ground_truth, predictions


def main() -> None:
    scenario = {
        'id': SCENARIO_ID,
        'name': 'Synthetic PropertyWatch Detection Demo',
        'description': (
            'Deterministic synthetic object-detection dataset for the MultiSens v0.8 '
            'multi-task evaluation workflow, extending the PropertyWatch personal/home '
            'multi-camera monitoring reference story. Ground truth and predictions are '
            'both generated, not measured - see examples/profiles/README.md. No '
            'surveillance-identification or face-recognition features of any kind - '
            'detected labels are generic object categories (package/vehicle/pet/person '
            'as a generic moving object, never an identity), purpose is sensor/system '
            'evaluation, and does NOT represent any real camera\'s object-detection '
            'performance.'
        ),
        'tags': ['synthetic', 'demo', 'object_detection', 'propertywatch'],
        'metadata': {'synthetic': True},
    }
    session = {
        'id': SESSION_ID, 'name': 'PropertyWatch Detection Demo Session',
        'scenario_id': SCENARIO_ID, 'metadata': {'synthetic': True},
    }

    ground_truth: list[dict] = []
    predictions: list[dict] = []
    for task, source_id, sensor_id, labels, a, b, c, d, e in TASKS:
        gt, preds = build_task_data(task, source_id, sensor_id, labels, a, b, c, d, e)
        ground_truth += gt
        predictions += preds

    dataset = {
        'format_version': '1.0',
        'scenario': scenario,
        'sessions': [session],
        'ground_truth': {SESSION_ID: ground_truth},
        'predictions': {SESSION_ID: predictions},
        'evaluator_parameters': {
            'confidence_threshold': CONFIDENCE_THRESHOLD, 'iou_threshold': IOU_THRESHOLD,
        },
        'tasks': [t[0] for t in TASKS],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    print(
        f'wrote {OUTPUT_PATH} (1 session, 3 tasks, '
        f'{len(ground_truth)} ground truth, {len(predictions)} predictions)'
    )


if __name__ == '__main__':
    main()
