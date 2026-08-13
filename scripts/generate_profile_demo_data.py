#!/usr/bin/env python3
"""Generates examples/profiles/cabin-safety-demo-data.json - a deterministic
synthetic multi-session dataset for the v0.4 profile/coverage demo (Phase 39),
extended with a third condition dimension - eyewear - for v0.5's Explorer/
breakdown/cross-tab demo (Phase 50).

Run once, output committed to git:

    python3 scripts/generate_profile_demo_data.py

Unlike examples/evaluation/classification-demo.json (one session), this
dataset needs multiple sessions, since v0.4 conditions live in
Session.metadata (see the v0.4 architecture review, issue #31, Q8) - each
distinct (illumination, occlusion, eyewear) combination is its own session,
sharing one scenario (the scenario represents "the kind of test," sessions
represent specific runs under specific observed conditions).

The eyewear dimension is deliberately NOT a full Cartesian product with
occlusion - "partial occlusion AND glasses" would conflate two
visibility-degrading factors into one meaningless combination. It's scoped
to just the two unoccluded/baseline sessions (day and night), asking a
clean, understandable question: does wearing glasses reduce accuracy under
an otherwise-ideal view? Every one of the six original sessions/
requirements now also carries an explicit `eyewear: none` - not left
implicit - so every requirement's three-key condition tuple still matches
exactly one session, preserving the demo's zero-evidence-ambiguity property
(see examples/profiles/README.md).

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

# (session_id, illumination, occlusion, eyewear) - six sessions. The
# original four keep occlusion's none/partial split with eyewear fixed at
# 'none'; two new sessions hold occlusion at 'none' and vary eyewear
# instead - deliberately not all eight (illumination x occlusion x
# eyewear) combinations. Every requirement that names all three condition
# keys still matches exactly one session (no evidence ambiguity anywhere
# in this demo - see app/domain/evidence.py's subset-matching rule).
SESSIONS = [
    ('cabin-day-clear', 'day', 'none', 'none'),
    ('cabin-day-occluded', 'day', 'partial', 'none'),
    ('cabin-night-clear', 'night', 'none', 'none'),
    ('cabin-night-occluded', 'night', 'partial', 'none'),
    ('cabin-day-glasses', 'day', 'none', 'glasses'),
    ('cabin-night-glasses', 'night', 'none', 'glasses'),
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
# everywhere. The glasses sessions add a mild, uniform tax to every
# configuration except thermal, which takes a much larger hit (glasses
# lenses attenuating the thermal signature around the eyes) - large
# enough at night to flip thermal from pass to fail versus the
# night-baseline requirement's identical threshold, the one place in this
# demo where the eyewear dimension changes an outcome, not just a number.
CONFIGS = [
    ('rgb_classifier', ['rgb'], {
        'cabin-day-clear': 92, 'cabin-day-occluded': 75,
        'cabin-night-clear': 60, 'cabin-night-occluded': 45,
        'cabin-day-glasses': 90, 'cabin-night-glasses': 58,
    }, 201),
    ('depth_classifier', ['depth'], {
        'cabin-day-clear': 88, 'cabin-day-occluded': 68,
        'cabin-night-clear': 88, 'cabin-night-occluded': 68,
        'cabin-day-glasses': 87, 'cabin-night-glasses': 87,
    }, 202),
    ('thermal_classifier', ['thermal'], {
        'cabin-day-clear': 78, 'cabin-day-occluded': 80,
        'cabin-night-clear': 85, 'cabin-night-occluded': 78,
        'cabin-day-glasses': 70, 'cabin-night-glasses': 75,
    }, 203),
    ('rgb_thermal_classifier', ['rgb', 'thermal'], {
        'cabin-day-clear': 94, 'cabin-day-occluded': 88,
        'cabin-night-clear': 90, 'cabin-night-occluded': 82,
        'cabin-day-glasses': 91, 'cabin-night-glasses': 86,
    }, 204),
    ('rgb_depth_thermal_classifier', ['rgb', 'depth', 'thermal'], {
        'cabin-day-clear': 97, 'cabin-day-occluded': 93,
        'cabin-night-clear': 95, 'cabin-night-occluded': 90,
        'cabin-day-glasses': 95, 'cabin-night-glasses': 92,
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
            'Deterministic synthetic dataset for demonstrating the MultiSens v0.4/v0.5 '
            'requirement profile, coverage, and condition-exploration workflow end to '
            'end, across multiple illumination/occlusion/eyewear conditions. Ground '
            'truth and predictions are both generated, not measured - see '
            'examples/profiles/README.md. Does NOT represent real sensor performance '
            'or any regulatory result.'
        ),
        'tags': ['synthetic', 'demo', 'presence', 'cabin-safety'],
        'metadata': {'synthetic': True},
    }

    sessions = []
    ground_truth_by_session = {}
    predictions_by_session = {}
    for index, (session_id, illumination, occlusion, eyewear) in enumerate(SESSIONS):
        name = f'Cabin Safety Demo - {illumination} / {occlusion} occlusion'
        if eyewear != 'none':
            name += f' / {eyewear}'
        sessions.append({
            'id': session_id,
            'name': name,
            'scenario_id': SCENARIO_ID,
            'metadata': {
                'synthetic': True, 'illumination': illumination, 'occlusion': occlusion, 'eyewear': eyewear,
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
