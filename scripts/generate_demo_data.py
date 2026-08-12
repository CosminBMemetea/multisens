#!/usr/bin/env python3
"""Generates examples/evaluation/classification-demo.json - a deterministic
synthetic dataset for the v0.2 evaluation demo (Phase 17).

Run once, output committed to git:

    python3 scripts/generate_demo_data.py

This is a dev-time generator, not part of the runtime - like a script that
produced a fixture once. Re-running it reproduces byte-identical output
(fixed seeds throughout), so there is no ambiguity about what "the demo
dataset" is.

SYNTHETIC DATA. Accuracy targets below (rgb=90%, depth=83%, thermal=87%)
are numbers chosen to fall within the ranges used elsewhere in this
project's planning docs for demonstrating the evaluation UI - they are
generated, not measured, and do not represent any real sensor's
performance. See examples/evaluation/README.md.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'evaluation' / 'classification-demo.json'

SAMPLE_COUNT = 100
TASK = 'presence'
LABELS = ('present', 'absent')

# (source_id, sensor_id, target_correct_count, rng_seed) - target_correct
# is chosen, not measured; each configuration gets its own seed so the
# three error patterns are independent, not mirror images of each other.
CONFIGS = [
    ('rgb_classifier', 'rgb', 90, 101),
    ('depth_classifier', 'depth', 83, 102),
    ('thermal_classifier', 'thermal', 87, 103),
]


def build_ground_truth() -> list[dict]:
    labels = ['present'] * (SAMPLE_COUNT // 2) + ['absent'] * (SAMPLE_COUNT // 2)
    random.Random(42).shuffle(labels)
    return [
        {
            'id': f'gt-{i:04d}',
            'timestamp_ms': float(i * 1000),
            'task': TASK,
            'value': {'label': labels[i]},
            'metadata': {'synthetic': True},
        }
        for i in range(SAMPLE_COUNT)
    ]


def build_predictions(ground_truth: list[dict]) -> list[dict]:
    predictions = []
    for source_id, sensor_id, target_correct, seed in CONFIGS:
        rng = random.Random(seed)
        # Exact by construction, not a probabilistic expectation: exactly
        # target_correct of the SAMPLE_COUNT predictions match ground
        # truth, so the resulting accuracy is exactly target_correct/100,
        # not "roughly" it.
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
                'id': f'pred-{sensor_id}-{i:04d}',
                'timestamp_ms': gt['timestamp_ms'] + rng.uniform(1, 5),
                'source_id': source_id,
                'sensor_ids': [sensor_id],
                'task': TASK,
                'value': {'label': predicted_label},
                'confidence': confidence,
                'metadata': {'synthetic': True},
            })
    return predictions


def main() -> None:
    ground_truth = build_ground_truth()
    predictions = build_predictions(ground_truth)

    dataset = {
        'format_version': '1.0',
        'session': {
            'id': 'demo-presence-classification',
            'name': 'Demo Presence Classification',
            'scenario_id': 'synthetic-cabin-demo',
            'metadata': {'synthetic': True},
        },
        'scenario': {
            'id': 'synthetic-cabin-demo',
            'name': 'Synthetic Cabin Demo',
            'description': (
                'Deterministic synthetic dataset for demonstrating the MultiSens '
                'evaluation workflow end to end. Ground truth and predictions are '
                'both generated, not measured - see examples/evaluation/README.md. '
                'Does NOT represent real sensor performance.'
            ),
            'tags': ['synthetic', 'demo', 'presence'],
            'metadata': {'synthetic': True},
        },
        'ground_truth': ground_truth,
        'predictions': predictions,
    }

    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    print(f'wrote {OUTPUT_PATH} ({len(ground_truth)} ground truth, {len(predictions)} predictions)')


if __name__ == '__main__':
    main()
