#!/usr/bin/env python3
"""Generates examples/profiles/sensor-lab-demo-data.json - a deterministic
synthetic multi-session dataset for the v0.4 profile/coverage demo (Phase 39),
extended with a third condition dimension - weather - for v0.5's Explorer/
breakdown/cross-tab demo (Phase 50).

Run once, output committed to git:

    python3 scripts/generate_profile_demo_data.py

Unlike examples/evaluation/classification-demo.json (one session), this
dataset needs multiple sessions, since v0.4 conditions live in
Session.metadata (see the v0.4 architecture review, issue #31, Q8) - each
distinct (illumination, occlusion, weather) combination is its own session,
sharing one scenario (the scenario represents "the kind of test," sessions
represent specific runs under specific observed conditions).

The weather dimension is deliberately NOT a full Cartesian product with
occlusion - "partial occlusion AND rain" would conflate two
visibility-degrading factors into one meaningless combination. It's scoped
to just the two unoccluded/baseline sessions (day and night), asking a
clean, understandable question: does rain reduce accuracy under an
otherwise-clear view? Every one of the six original sessions/requirements
now also carries an explicit `weather: clear` - not left implicit - so
every requirement's three-key condition tuple still matches exactly one
session, preserving the demo's zero-evidence-ambiguity property (see
examples/profiles/README.md).

SYNTHETIC DATA. Accuracy targets below are numbers chosen to tell a clean,
hand-verifiable coverage story per docs/profiles.md's synthetic reference
profile (sensor-lab-demo.json) - not a claim about real sensor performance.
See examples/profiles/README.md.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'sensor-lab-demo-data.json'

SAMPLE_COUNT = 100
TASK = 'presence'
LABELS = ('present', 'absent')

SCENARIO_ID = 'synthetic-sensor-lab-demo'

# (session_id, illumination, occlusion, weather) - six sessions. The
# original four keep occlusion's none/partial split with weather fixed at
# 'clear'; two new sessions hold occlusion at 'none' and vary weather
# instead - deliberately not all eight (illumination x occlusion x
# weather) combinations. Every requirement that names all three condition
# keys still matches exactly one session (no evidence ambiguity anywhere
# in this demo - see app/domain/evidence.py's subset-matching rule).
SESSIONS = [
    ('lab-day-clear', 'day', 'none', 'clear'),
    ('lab-day-occluded', 'day', 'partial', 'clear'),
    ('lab-night-clear', 'night', 'none', 'clear'),
    ('lab-night-occluded', 'night', 'partial', 'clear'),
    ('lab-day-rain', 'day', 'none', 'rain'),
    ('lab-night-rain', 'night', 'none', 'rain'),
]

# (source_id, sensor_ids, {session_id: target_correct_count}, rng_seed) -
# target_correct is chosen, not measured, same construction as
# scripts/generate_demo_data.py: a fixed set of ground-truth indices is
# deliberately mislabeled per (session, configuration) pair, so accuracy
# is exact, not a probabilistic approximation. Targets are deliberately
# constructed so each configuration's pass/fail pattern across the demo
# profile's requirements is genuinely different (see
# examples/profiles/README.md's accuracy table for the full story):
# rgb favors daylight, depth is illumination-invariant but occlusion-
# sensitive, thermal is illumination-invariant and occlusion-tolerant,
# rgb+thermal fuses both strengths, and rgb+depth+thermal dominates
# everywhere. The rain sessions add a mild, uniform tax to every
# configuration except thermal, which takes a much larger hit (moisture on
# the lens/housing attenuating the thermal signature) - large enough at
# night to flip thermal from pass to fail versus the night-baseline
# requirement's identical threshold, the one place in this demo where the
# weather dimension changes an outcome, not just a number.
CONFIGS = [
    ('rgb_classifier', ['rgb'], {
        'lab-day-clear': 92, 'lab-day-occluded': 75,
        'lab-night-clear': 60, 'lab-night-occluded': 45,
        'lab-day-rain': 90, 'lab-night-rain': 58,
    }, 201),
    ('depth_classifier', ['depth'], {
        'lab-day-clear': 88, 'lab-day-occluded': 68,
        'lab-night-clear': 88, 'lab-night-occluded': 68,
        'lab-day-rain': 87, 'lab-night-rain': 87,
    }, 202),
    ('thermal_classifier', ['thermal'], {
        'lab-day-clear': 78, 'lab-day-occluded': 80,
        'lab-night-clear': 85, 'lab-night-occluded': 78,
        'lab-day-rain': 70, 'lab-night-rain': 75,
    }, 203),
    ('rgb_thermal_classifier', ['rgb', 'thermal'], {
        'lab-day-clear': 94, 'lab-day-occluded': 88,
        'lab-night-clear': 90, 'lab-night-occluded': 82,
        'lab-day-rain': 91, 'lab-night-rain': 86,
    }, 204),
    ('rgb_depth_thermal_classifier', ['rgb', 'depth', 'thermal'], {
        'lab-day-clear': 97, 'lab-day-occluded': 93,
        'lab-night-clear': 95, 'lab-night-occluded': 90,
        'lab-day-rain': 95, 'lab-night-rain': 92,
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
        'name': 'Synthetic Sensor Lab Demo',
        'description': (
            'Deterministic synthetic dataset for demonstrating the MultiSens v0.4/v0.5 '
            'requirement profile, coverage, and condition-exploration workflow end to '
            'end, across multiple illumination/occlusion/weather conditions. Ground '
            'truth and predictions are both generated, not measured - see '
            'examples/profiles/README.md. Does NOT represent real sensor performance.'
        ),
        'tags': ['synthetic', 'demo', 'presence', 'sensor-lab'],
        'metadata': {'synthetic': True},
    }

    sessions = []
    ground_truth_by_session = {}
    predictions_by_session = {}
    for index, (session_id, illumination, occlusion, weather) in enumerate(SESSIONS):
        name = f'Sensor Lab Demo - {illumination} / {occlusion} occlusion'
        if weather != 'clear':
            name += f' / {weather}'
        sessions.append({
            'id': session_id,
            'name': name,
            'scenario_id': SCENARIO_ID,
            'metadata': {
                'synthetic': True, 'illumination': illumination, 'occlusion': occlusion, 'weather': weather,
            },
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
