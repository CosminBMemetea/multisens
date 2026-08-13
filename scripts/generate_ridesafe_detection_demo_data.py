#!/usr/bin/env python3
"""Generates examples/profiles/ridesafe-detection-demo-data.json - a
deterministic synthetic object-detection dataset for the v0.8 RideSafe
detection demo (Phase 87).

Run once, output committed to git:

    python3 scripts/generate_ridesafe_detection_demo_data.py

Extends the existing RideSafe reference story (ridesafe_front_rgb/
ridesafe_rear_rgb, ride monitoring and incident evidence only - see
examples/profiles/README.md and ridesafe-demo-data.json's own docstring
for the full framing discipline) with the first real exercise of the
v0.8 object-detection evaluator. Deliberately a SEPARATE dataset/session
from ridesafe-demo-data.json's own day/night classification sessions -
this never touches that file, so Phase 73's own "numbers must not
silently drift" guard (test_ridesafe_demo.py) stays completely
unaffected.

No profile/requirements/resources here - out of scope for this phase
(issue #88's acceptance criteria: independent verification, backend
regression, live Playwright verification of the Phase 86 detection
panel - decision/coverage integration was never asked for and a generic
`Evaluator` already works standalone through /evaluate).

## Fully deterministic - no randomness at all, seeded or otherwise

Every frame's category (and therefore its exact TP/FP/FN/IoU
contribution) is chosen by a fixed index range, and every bbox within a
category is an exact, hand-computed rectangle - stricter than
ridesafe-demo-data.json's own seeded-shuffle approach, and possible here
because object-detection ground truth needs literal coordinates anyway
(there's no analogous "pick a label" step that benefits from shuffling).

## Five frame categories per task, telling a front > rear detection-quality story

Same "genuinely different pass/fail pattern per configuration" discipline
every prior demo uses (see ridesafe-demo-data.json's own docstring) -
here it's front vs. rear camera object-detection quality, not
front/rear/combined scene visibility:

- A ("clean hit"): GT and a same-label detection overlap enough to match
  (IoU 0.6, offset 0.05 along x from a 0.20-wide box - see
  `_compute_iou` below) -> one true positive.
- B ("localized but too imprecise"): a same-label detection is present
  but shifted far enough that IoU (0.25) falls below `IOU_THRESHOLD`
  (0.5) -> not a matching candidate at all (the IoU threshold gates
  candidacy, not just a post-hoc label - see detection.py's own
  docstring) -> one false negative (the GT object) + one false positive
  (the detection).
- C ("filtered by confidence"): a detection with a perfect IoU=1.0 bbox
  but confidence 0.30, below `CONFIDENCE_THRESHOLD` (0.5) -> dropped
  before matching ever runs -> one false negative, zero false positives
  (a filtered detection contributes nothing, per detection.py's own
  "dropped before matching, never after" rule).
- D ("missing prediction"): no Prediction row at all for this frame ->
  matching.py's own timestamp matching leaves the GT frame entirely
  unmatched -> one false negative.
- E ("clean hit plus a spurious extra"): a same-label detection matches
  GT exactly (IoU=1.0) AND a second, non-overlapping detection is
  present in the same frame with no GT counterpart -> one true positive
  + one false positive.

Front gets a favorable mix (70/10/5/5/10 = A/B/C/D/E out of 100 frames);
rear gets a harder one (45/20/15/15/5) - by construction, not measured,
exactly like ridesafe-demo-data.json's own day/night accuracy split.
Hand-derived aggregate numbers (cross-checked by
backend/tests/test_ridesafe_detection_demo.py against an independent
recomputation AND the real /evaluate API - never just asserted here):

    front: TP=80 FP=20 FN=20  precision=0.80 recall=0.80 f1=0.80 mean_iou_matched=0.65
    rear:  TP=50 FP=25 FN=50  precision=0.6667 recall=0.50 f1=0.5714 mean_iou_matched=0.64
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'ridesafe-detection-demo-data.json'

SAMPLE_COUNT = 100
SCENARIO_ID = 'synthetic-ridesafe-detection-demo'
SESSION_ID = 'ridesafe-detection-demo-session'

CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.5

# A GT object's own bbox is identical for every frame - only the label
# (alternating by frame index, so both 'vehicle' and 'pedestrian' get
# exercised in every category) and the prediction pattern (by category)
# vary. Visual variety isn't the point; deterministic, hand-verifiable
# construction is (see this module's own docstring).
GT_BBOX = {'x': 0.30, 'y': 0.30, 'width': 0.20, 'height': 0.20}
LABELS = ('vehicle', 'pedestrian')

# category -> (x_offset_from_gt, confidence, extra_spurious_detection)
CATEGORY_A = {'x_offset': 0.05, 'confidence': 0.9}   # IoU 0.6 - clean hit
CATEGORY_B = {'x_offset': 0.12, 'confidence': 0.9}   # IoU 0.25 - below threshold
CATEGORY_C = {'x_offset': 0.0, 'confidence': 0.3}    # IoU 1.0 but filtered
SPURIOUS_BBOX = {'x': 0.02, 'y': 0.02, 'width': 0.08, 'height': 0.08}  # no overlap with GT_BBOX

# task -> (source_id, sensor_id, config_id, a_count, b_count, c_count, d_count, e_count)
TASKS = [
    ('front_scene_object_detection', 'ridesafe_front_rgb_detector', 'ridesafe_front_rgb', 70, 10, 5, 5, 10),
    ('rear_scene_object_detection', 'ridesafe_rear_rgb_detector', 'ridesafe_rear_rgb', 45, 20, 15, 15, 5),
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


def build_task_data(task: str, source_id: str, sensor_id: str, a: int, b: int, c: int, d: int, e: int) -> tuple[list[dict], list[dict]]:
    assert a + b + c + d + e == SAMPLE_COUNT
    ground_truth = []
    predictions = []
    for i in range(SAMPLE_COUNT):
        label = LABELS[i % 2]
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
        'name': 'Synthetic RideSafe Detection Demo',
        'description': (
            'Deterministic synthetic object-detection dataset for the MultiSens v0.8 '
            'multi-task evaluation workflow, extending the RideSafe personal front/rear '
            'dashcam reference story. Ground truth and predictions are both generated, '
            'not measured - see examples/profiles/README.md. Ride monitoring and '
            'incident-evidence framing only - not a safety-certification, driver-'
            'monitoring, or occupant-monitoring claim of any kind, and does NOT '
            'represent real 70mai or any other camera\'s object-detection performance.'
        ),
        'tags': ['synthetic', 'demo', 'object_detection', 'ridesafe'],
        'metadata': {'synthetic': True},
    }
    session = {
        'id': SESSION_ID, 'name': 'RideSafe Detection Demo Session',
        'scenario_id': SCENARIO_ID, 'metadata': {'synthetic': True},
    }

    ground_truth: list[dict] = []
    predictions: list[dict] = []
    for task, source_id, sensor_id, a, b, c, d, e in TASKS:
        gt, preds = build_task_data(task, source_id, sensor_id, a, b, c, d, e)
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
        f'wrote {OUTPUT_PATH} (1 session, 2 tasks, '
        f'{len(ground_truth)} ground truth, {len(predictions)} predictions)'
    )


if __name__ == '__main__':
    main()
