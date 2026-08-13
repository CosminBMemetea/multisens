#!/usr/bin/env python3
"""Generates examples/profiles/exterior-decision-demo-data.json - a
deterministic synthetic multi-configuration dataset for the v0.6
decision-support demo (Phase 61).

Run once, output committed to git:

    python3 scripts/generate_decision_demo_data.py

A genuinely different scenario from sensor-lab-demo.json's condition-
exploration story - exterior sensing across sensor *instances*,
not just modalities: front_rgb and rear_rgb are two separate physical
RGB camera positions, sim_thermal and sim_depth are simulated. This is
a new profile document, not squeezed into sensor-lab-demo (v0.6
architecture review, issue #54, Q23) - the two demos answer genuinely
different questions (v0.4/v0.5's "does this evidence satisfy a
requirement" vs v0.6's "which sensor combination is minimally
sufficient").

Deliberately no condition dimensions (Requirement.conditions is empty
everywhere) - this demo is about the *sensor-combination* space v0.6
reasons over, not a second condition-exploration showcase; that's
already exhaustively demonstrated by sensor-lab-demo. One session,
one task, four acceptance thresholds is enough to produce a genuinely
informative, hand-verifiable minimum-sufficient-configuration and
Pareto-front story.

front_rgb/rear_rgb are NOT added to config/sensors.yaml, deliberately -
they would violate the exact one-sensor-per-modality launch-time guard
Phase 57 reviewed and explicitly deferred (both are modality `rgb`;
sim_thermal/sim_depth would likewise collide with the already-configured
live `thermal`/`depth` entries). These sensor ids are evaluation-only
for this demo, with no live ingestion configured for them - the
frontend's SourceTypeBadge correctly renders no badge for an unknown
sensor id (already built to degrade gracefully) rather than fabricating
a live source_type that doesn't exist. See docs/decision-support.md.

SYNTHETIC DATA. Accuracy targets below are numbers chosen to tell a
clean, hand-verifiable decision-support story - deliberately NOT a claim
about real 70mai/dashcam or any other camera's performance. See
examples/profiles/README.md.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'exterior-decision-demo-data.json'

SAMPLE_COUNT = 100
TASK = 'object_presence'
LABELS = ('present', 'absent')

SCENARIO_ID = 'synthetic-exterior-decision-demo'
SESSION_ID = 'exterior-demo-session'

# (source_id, sensor_ids, target_correct_count, rng_seed) - eight
# configurations spanning the reference sensor-combination space (v0.6
# master prompt §22), not an exhaustive power set (§23 explicitly warns
# against that). target_correct is chosen, not measured, same
# construction as scripts/generate_profile_demo_data.py - accuracy is
# exact, not a probabilistic approximation.
#
# The story: front_rgb alone is a weak baseline; rear_rgb alone is
# similarly weak (a second ordinary camera, not a new sensing
# modality); adding rear_rgb to front_rgb helps modestly; adding
# sim_thermal helps much more (a genuinely different sensing modality);
# sim_depth on its own paired with front_rgb helps about as much as
# rear_rgb does (also a modest, non-modality-changing addition);
# front_rgb+rear_rgb+sim_thermal reaches every requirement; adding
# sim_depth on top changes nothing further - the "some sensors add no
# additional requirement coverage" case the whole layer exists to catch.
CONFIGS = [
    ('front_rgb_classifier', ['front_rgb'], 60, 301),
    ('rear_rgb_classifier', ['rear_rgb'], 55, 302),
    ('front_rear_rgb_classifier', ['front_rgb', 'rear_rgb'], 72, 303),
    ('front_rgb_thermal_classifier', ['front_rgb', 'sim_thermal'], 88, 304),
    ('front_rgb_depth_classifier', ['front_rgb', 'sim_depth'], 70, 305),
    ('front_rear_rgb_thermal_classifier', ['front_rgb', 'rear_rgb', 'sim_thermal'], 98, 306),
    ('front_rear_rgb_depth_classifier', ['front_rgb', 'rear_rgb', 'sim_depth'], 85, 307),
    ('all_sensors_classifier', ['front_rgb', 'rear_rgb', 'sim_thermal', 'sim_depth'], 98, 308),
]


def build_ground_truth() -> list[dict]:
    labels = ['present'] * (SAMPLE_COUNT // 2) + ['absent'] * (SAMPLE_COUNT // 2)
    random.Random(42).shuffle(labels)
    return [
        {
            'id': f'gt-{SESSION_ID}-{i:04d}',
            'timestamp_ms': float(i * 1000),
            'task': TASK,
            'value': {'label': label},
            'metadata': {'synthetic': True},
        }
        for i, label in enumerate(labels)
    ]


def build_predictions(ground_truth: list[dict]) -> list[dict]:
    predictions = []
    for source_id, sensor_ids, target_correct, seed in CONFIGS:
        config_label = '-'.join(sensor_ids)
        rng = random.Random(seed)
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
                'id': f'pred-{SESSION_ID}-{config_label}-{i:04d}',
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
        'name': 'Synthetic Exterior Decision Demo',
        'description': (
            'Deterministic synthetic dataset for demonstrating the MultiSens v0.6 '
            'decision-support workflow end to end, across a reference exterior '
            'sensor-combination space (front/rear RGB camera positions plus '
            'simulated thermal/depth). Ground truth and predictions are both '
            'generated, not measured - see examples/profiles/README.md. Does NOT '
            'represent real camera performance of any kind, physical or simulated.'
        ),
        'tags': ['synthetic', 'demo', 'object_presence', 'exterior-decision'],
        'metadata': {'synthetic': True},
    }

    session = {
        'id': SESSION_ID,
        'name': 'Exterior Decision Demo Session',
        'scenario_id': SCENARIO_ID,
        'metadata': {'synthetic': True},
    }

    ground_truth = build_ground_truth()
    predictions = build_predictions(ground_truth)

    dataset = {
        'format_version': '1.0',
        'scenario': scenario,
        'sessions': [session],
        'ground_truth': {SESSION_ID: ground_truth},
        'predictions': {SESSION_ID: predictions},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    print(f'wrote {OUTPUT_PATH} (1 session, {len(ground_truth)} ground truth, {len(predictions)} predictions)')


if __name__ == '__main__':
    main()
