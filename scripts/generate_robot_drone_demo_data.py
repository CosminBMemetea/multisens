#!/usr/bin/env python3
"""Generates examples/profiles/robot-drone-demo-data.json - a
deterministic, entirely synthetic dataset for the v0.8 Robot/Drone
Sensing Demo (Phase 89) - the first generic robotics-ready reference
example in this project.

Run once, output committed to git:

    python3 scripts/generate_robot_drone_demo_data.py

## Generic robotics evaluation demonstration only

No physical drone/robot required or implied - reference sensor ids
`robot_front_rgb`/`sim_depth`/`sim_range` are entirely synthetic, same
"evaluation-only, graceful no-badge fallback" precedent as
exterior-decision-demo's own `sim_thermal`/`sim_depth`
(scripts/generate_decision_demo_data.py) - deliberately NOT added to
config/sensors.yaml.

THIS IS NEVER an autonomous navigation system, a drone control system,
or a flight safety system (master prompt §32/§68) - MultiSens itself
performs no control, planning, or flight functions of any kind, and a
synthetic detection/distance result here never implies real-world
obstacle avoidance has been validated. Kept clearly distinct in name and
theme from the older, unrelated "Generic Sensor Evaluation Lab" (the
retired-and-rethemed v0.4/v0.5 cabin-safety-demo replacement, see
sensor-lab-demo-data.json) - a completely different demo from a
different release, sharing nothing but the word "generic."

## Two tasks, over the v0.8 detection and regression evaluators - no new evaluator logic

`obstacle_detection` (object_detection evaluator) and
`distance_estimation` (regression evaluator) are both task profiles over
the already-generic v0.8 evaluators (architecture review Q20/§20) - no
dedicated "range_estimation" logic exists or is needed, exactly the
"introduce a new value schema, never new evaluator code" discipline
detection.py/regression.py's own docstrings already establish. Reuses
Phase 87/88's own five-category detection construction verbatim for
`obstacle_detection`; `distance_estimation` uses a repeating five-value
deterministic error cycle per configuration instead (no per-frame
category concept applies to a continuous regression quantity).

`sim_depth` deliberately participates in BOTH tasks (its own depth field
can plausibly support both an obstacle bounding box and a coarse
distance estimate) - the same "one sensor instance, multiple task
predictions" pattern this project's other multi-task sessions already
use, nothing new.

## `obstacle_detection`: robot_front_rgb (camera) vs. sim_depth (depth-derived)

    robot_front_rgb: A=65 B=10 C=10 D=10 E=5 -> TP=70 FP=15 FN=30
        precision=0.8235 recall=0.70 f1=0.7568 mean_iou_matched=0.6286
    sim_depth:        A=50 B=20 C=10 D=15 E=5 -> TP=55 FP=25 FN=45
        precision=0.6875 recall=0.55 f1=0.6111 mean_iou_matched=0.6364

## `distance_estimation`: sim_range (dedicated) vs. sim_depth (camera-derived)

Ground truth ramps linearly (2.00m to 6.95m, unit 'm'); each
configuration applies a fixed 5-value error cycle (repeating 20x across
100 samples), so MAE/RMSE/bias/median are exact, hand-computable
averages over that one cycle - never randomness:

    sim_range errors [+0.05,-0.05,+0.10,-0.10,0.00] ->
        mae=0.06 rmse=0.0707106781 bias=0.0 median_absolute_error=0.05
    sim_depth errors [+0.30,-0.20,+0.50,-0.40,+0.10] ->
        mae=0.30 rmse=0.3316624790 bias=0.06 median_absolute_error=0.30

A dedicated range sensor is, by construction, far more accurate than a
depth-camera-derived distance estimate - the same "genuinely different
pattern per configuration" discipline every prior demo in this project
tells, here about sensing accuracy rather than coverage or resource
cost.
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'robot-drone-demo-data.json'

SAMPLE_COUNT = 100
SCENARIO_ID = 'synthetic-robot-drone-demo'
SESSION_ID = 'robot-drone-demo-session'

CONFIDENCE_THRESHOLD = 0.5
IOU_THRESHOLD = 0.5
OBSTACLE_LABELS = ('obstacle', 'marker')

GT_BBOX = {'x': 0.30, 'y': 0.30, 'width': 0.20, 'height': 0.20}
CATEGORY_A = {'x_offset': 0.05, 'confidence': 0.9}   # IoU 0.6 - clean hit
CATEGORY_B = {'x_offset': 0.12, 'confidence': 0.9}   # IoU 0.25 - below threshold
CATEGORY_C = {'x_offset': 0.0, 'confidence': 0.3}    # IoU 1.0 but filtered
SPURIOUS_BBOX = {'x': 0.02, 'y': 0.02, 'width': 0.08, 'height': 0.08}  # no overlap with GT_BBOX

# task -> (source_id, sensor_id, a, b, c, d, e) for obstacle_detection
DETECTION_TASKS = [
    ('obstacle_detection', 'robot_front_rgb_detector', 'robot_front_rgb', 65, 10, 10, 10, 5),
    ('obstacle_detection', 'sim_depth_obstacle_detector', 'sim_depth', 50, 20, 10, 15, 5),
]

DISTANCE_UNIT = 'm'
# configuration -> 5-value error cycle (repeated 20x across 100 samples).
DISTANCE_CONFIGS = [
    ('distance_estimation', 'sim_range_estimator', 'sim_range', [0.05, -0.05, 0.10, -0.10, 0.00]),
    ('distance_estimation', 'sim_depth_estimator', 'sim_depth', [0.30, -0.20, 0.50, -0.40, 0.10]),
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


def build_obstacle_ground_truth(task: str) -> list[dict]:
    # ONE shared set of GT rows for the whole task - ground truth is
    # looked up per (session, task), not per configuration
    # (repo.list_ground_truth), so both obstacle_detection configurations
    # below evaluate against this same set. Emitting a second, per-sensor
    # copy would silently double the GT row count for the task and wreck
    # match_by_timestamp's own frame association - a real mistake caught
    # and fixed during this script's own construction, not a hypothetical.
    return [
        {
            'id': f'gt-{SESSION_ID}-{task}-{i:04d}',
            'timestamp_ms': float(i * 1000),
            'task': task,
            'value': {'objects': [{'id': f'obj-{i:04d}-0', 'label': OBSTACLE_LABELS[i % 2], 'bbox': GT_BBOX}]},
            'metadata': {'synthetic': True},
        }
        for i in range(SAMPLE_COUNT)
    ]


def build_obstacle_predictions(
    task: str, source_id: str, sensor_id: str, a: int, b: int, c: int, d: int, e: int,
) -> list[dict]:
    assert a + b + c + d + e == SAMPLE_COUNT
    predictions = []
    for i in range(SAMPLE_COUNT):
        label = OBSTACLE_LABELS[i % 2]
        timestamp_ms = float(i * 1000)
        category = _category_for_index(i, a, b, c, d)

        if category == 'D':
            continue

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
            'id': f'pred-{SESSION_ID}-{task}-{sensor_id}-{i:04d}',
            'timestamp_ms': timestamp_ms + 2.0,
            'source_id': source_id,
            'sensor_ids': [sensor_id],
            'task': task,
            'value': {'detections': detections},
            'metadata': {'synthetic': True, 'category': category},
        })
    return predictions


def build_distance_ground_truth(task: str) -> list[dict]:
    # Same "one shared GT set per task" discipline as
    # build_obstacle_ground_truth above.
    return [
        {
            'id': f'gt-{SESSION_ID}-{task}-{i:04d}',
            'timestamp_ms': float(i * 1000),
            'task': task,
            'value': {'value': round(2.0 + 0.05 * i, 4), 'unit': DISTANCE_UNIT},
            'metadata': {'synthetic': True},
        }
        for i in range(SAMPLE_COUNT)
    ]


def build_distance_predictions(task: str, source_id: str, sensor_id: str, error_cycle: list[float]) -> list[dict]:
    predictions = []
    for i in range(SAMPLE_COUNT):
        timestamp_ms = float(i * 1000)
        gt_value = round(2.0 + 0.05 * i, 4)
        error = error_cycle[i % len(error_cycle)]
        pred_value = round(gt_value + error, 4)
        predictions.append({
            'id': f'pred-{SESSION_ID}-{task}-{sensor_id}-{i:04d}',
            'timestamp_ms': timestamp_ms + 2.0,
            'source_id': source_id,
            'sensor_ids': [sensor_id],
            'task': task,
            'value': {'value': pred_value, 'unit': DISTANCE_UNIT},
            'metadata': {'synthetic': True},
        })
    return predictions


def main() -> None:
    scenario = {
        'id': SCENARIO_ID,
        'name': 'Synthetic Robot/Drone Sensing Demo',
        'description': (
            'Deterministic, entirely synthetic dataset for the MultiSens v0.8 '
            'multi-task evaluation workflow, built around a generic mobile robot or '
            'small drone reference platform (reference sensor ids robot_front_rgb, '
            'sim_depth, sim_range - no physical hardware required or implied). This '
            'is a generic robotics sensor-evaluation demonstration only. It is not '
            'an autonomous navigation system, not a drone control system, and not '
            'a flight safety system - MultiSens performs no control, planning, or '
            'flight functions of any kind. A synthetic detection or distance result '
            'here is never a validated obstacle avoidance guarantee for real-world '
            'use. Distinct in name and theme from the unrelated "Generic Sensor '
            'Evaluation Lab" demo (see examples/profiles/README.md). Ground truth '
            'and predictions are both generated, not measured.'
        ),
        'tags': ['synthetic', 'demo', 'object_detection', 'regression', 'robotics'],
        'metadata': {'synthetic': True},
    }
    session = {
        'id': SESSION_ID, 'name': 'Robot/Drone Sensing Demo Session',
        'scenario_id': SCENARIO_ID, 'metadata': {'synthetic': True},
    }

    ground_truth: list[dict] = []
    predictions: list[dict] = []

    ground_truth += build_obstacle_ground_truth('obstacle_detection')
    for task, source_id, sensor_id, a, b, c, d, e in DETECTION_TASKS:
        predictions += build_obstacle_predictions(task, source_id, sensor_id, a, b, c, d, e)

    ground_truth += build_distance_ground_truth('distance_estimation')
    for task, source_id, sensor_id, error_cycle in DISTANCE_CONFIGS:
        predictions += build_distance_predictions(task, source_id, sensor_id, error_cycle)

    dataset = {
        'format_version': '1.0',
        'scenario': scenario,
        'sessions': [session],
        'ground_truth': {SESSION_ID: ground_truth},
        'predictions': {SESSION_ID: predictions},
        'detection_parameters': {
            'confidence_threshold': CONFIDENCE_THRESHOLD, 'iou_threshold': IOU_THRESHOLD,
        },
        'tasks': {
            'obstacle_detection': {'evaluator_type': 'object_detection', 'configuration_ids': [
                'cfg-robot_front_rgb', 'cfg-sim_depth',
            ]},
            'distance_estimation': {'evaluator_type': 'regression', 'configuration_ids': [
                'cfg-sim_range', 'cfg-sim_depth',
            ]},
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    print(
        f'wrote {OUTPUT_PATH} (1 session, 2 tasks, '
        f'{len(ground_truth)} ground truth, {len(predictions)} predictions)'
    )


if __name__ == '__main__':
    main()
