#!/usr/bin/env python3
"""Generates examples/profiles/cabin-safety-demo-data.json - a deterministic
synthetic multi-session dataset for the v0.4 profile/coverage demo (Phase 39).

Run once, output committed to git:

    python3 scripts/generate_profile_demo_data.py

Unlike examples/evaluation/classification-demo.json (one session), this
dataset needs multiple sessions, since v0.4 conditions live in
Session.metadata (see the v0.4 architecture review, issue #31, Q8) - each
distinct (illumination, occlusion) combination is its own session, sharing
one scenario (the scenario represents "the kind of test," sessions
represent specific runs under specific observed conditions).

SYNTHETIC DATA. Accuracy targets below are numbers chosen to tell a clean,
hand-verifiable coverage story per docs/profiles.md's synthetic reference
profile (cabin-safety-demo.json) - deliberately NOT NCAP or any regulatory
framework, and NOT a claim about real sensor performance. See
examples/profiles/README.md.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'cabin-safety-demo-data.json'

SAMPLE_COUNT = 100
TASK = 'presence'
LABELS = ('present', 'absent')

SCENARIO_ID = 'synthetic-cabin-safety-demo'

# (session_id, illumination, occlusion) - four sessions, one per condition
# combination, so every requirement that names both condition keys
# matches exactly one session (no evidence ambiguity anywhere in this
# demo - see app/domain/evidence.py's subset-matching rule).
SESSIONS = [
    ('cabin-day-clear', 'day', 'none'),
    ('cabin-day-occluded', 'day', 'partial'),
    ('cabin-night-clear', 'night', 'none'),
    ('cabin-night-occluded', 'night', 'partial'),
]

# (source_id, sensor_ids, {session_id: target_correct_count}, rng_seed) -
# target_correct is chosen, not measured, same construction as
# scripts/generate_demo_data.py: a fixed set of ground-truth indices is
# deliberately mislabeled per (session, configuration) pair, so accuracy
# is exact, not a probabilistic approximation. Targets are deliberately
# constructed so each configuration's pass/fail pattern across the demo
# profile's six requirements is genuinely different (see
# examples/profiles/README.md's accuracy table for the full story):
# rgb favors daylight, depth is illumination-invariant but occlusion-
# sensitive, thermal is illumination-invariant and occlusion-tolerant,
# rgb+thermal fuses both strengths, and rgb+depth+thermal dominates
# everywhere.
CONFIGS = [
    ('rgb_classifier', ['rgb'], {
        'cabin-day-clear': 92, 'cabin-day-occluded': 75,
        'cabin-night-clear': 60, 'cabin-night-occluded': 45,
    }, 201),
    ('depth_classifier', ['depth'], {
        'cabin-day-clear': 88, 'cabin-day-occluded': 68,
        'cabin-night-clear': 88, 'cabin-night-occluded': 68,
    }, 202),
    ('thermal_classifier', ['thermal'], {
        'cabin-day-clear': 78, 'cabin-day-occluded': 80,
        'cabin-night-clear': 85, 'cabin-night-occluded': 78,
    }, 203),
    ('rgb_thermal_classifier', ['rgb', 'thermal'], {
        'cabin-day-clear': 94, 'cabin-day-occluded': 88,
        'cabin-night-clear': 90, 'cabin-night-occluded': 82,
    }, 204),
    ('rgb_depth_thermal_classifier', ['rgb', 'depth', 'thermal'], {
        'cabin-day-clear': 97, 'cabin-day-occluded': 93,
        'cabin-night-clear': 95, 'cabin-night-occluded': 90,
    }, 205),
]


def build_ground_truth(session_id: str, gt_seed: int) -> list[dict]:
    labels = ['present'] * (SAMPLE_COUNT // 2) + ['absent'] * (SAMPLE_COUNT // 2)
    random.Random(gt_seed).shuffle(labels)
    return [
        {
            'id': f'gt-{session_id}-{i:04d}',
            'timestamp_ms': float(i * 1000),
            'task': TASK,
            'value': {'label': labels[i]},
            'metadata': {'synthetic': True},
        }
        for i, label in enumerate(labels)
    ]


def build_predictions(session_id: str, session_index: int, ground_truth: list[dict]) -> list[dict]:
    predictions = []
    for source_id, sensor_ids, targets_by_session, seed in CONFIGS:
        target_correct = targets_by_session[session_id]
        config_label = '-'.join(sensor_ids)
        # session_index (not hash(session_id)) keeps this deterministic
        # across runs/processes - Python's string hash is randomized per
        # process by default (PYTHONHASHSEED), which would silently break
        # the "reproduces byte-identical output" guarantee.
        rng = random.Random(seed * 1000 + session_index)
        wrong_indices = set(rng.sample(range(SAMPLE_COUNT), SAMPLE_COUNT - target_correct))
        for i, gt in enumerate(ground_truth):
            true_label = gt['value']['label']
            if i in wrong_indices:
                predicted_label = next(label for label in LABELS if label != true_label)
                confidence = round(rng.uniform(0.50, 0.65), 2)
            else:
                predicted_label = true_label
                confidence = round(rng.uniform(0.85, 0.99), 2)
            predictions.append({
                'id': f'pred-{session_id}-{config_label}-{i:04d}',
                'timestamp_ms': gt['timestamp_ms'] + rng.uniform(1, 5),
                'source_id': source_id,
                'sensor_ids': sensor_ids,
                'task': TASK,
                'value': {'label': predicted_label},
                'confidence': confidence,
                'metadata': {'synthetic': True},
            })
    return predictions


def main() -> None:
    scenario = {
        'id': SCENARIO_ID,
        'name': 'Synthetic Cabin Safety Demo',
        'description': (
            'Deterministic synthetic dataset for demonstrating the MultiSens v0.4 '
            'requirement profile and coverage workflow end to end, across multiple '
            'illumination/occlusion conditions. Ground truth and predictions are '
            'both generated, not measured - see examples/profiles/README.md. '
            'Does NOT represent real sensor performance or any regulatory result.'
        ),
        'tags': ['synthetic', 'demo', 'presence', 'cabin-safety'],
        'metadata': {'synthetic': True},
    }

    sessions = []
    ground_truth_by_session = {}
    predictions_by_session = {}
    for index, (session_id, illumination, occlusion) in enumerate(SESSIONS):
        sessions.append({
            'id': session_id,
            'name': f'Cabin Safety Demo - {illumination} / {occlusion} occlusion',
            'scenario_id': SCENARIO_ID,
            'metadata': {'synthetic': True, 'illumination': illumination, 'occlusion': occlusion},
        })
        ground_truth = build_ground_truth(session_id, gt_seed=42 + index)
        ground_truth_by_session[session_id] = ground_truth
        predictions_by_session[session_id] = build_predictions(session_id, index, ground_truth)

    dataset = {
        'format_version': '1.0',
        'scenario': scenario,
        'sessions': sessions,
        'ground_truth': ground_truth_by_session,
        'predictions': predictions_by_session,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    total_gt = sum(len(v) for v in ground_truth_by_session.values())
    total_pred = sum(len(v) for v in predictions_by_session.values())
    print(f'wrote {OUTPUT_PATH} ({len(sessions)} sessions, {total_gt} ground truth, {total_pred} predictions)')


if __name__ == '__main__':
    main()
