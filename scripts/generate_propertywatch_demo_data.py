#!/usr/bin/env python3
"""Generates examples/profiles/propertywatch-demo-data.json - a
deterministic synthetic dataset for the v0.7 PropertyWatch demo
(Phase 74).

Run once, output committed to git:

    python3 scripts/generate_propertywatch_demo_data.py

PropertyWatch is a personal/home multi-camera monitoring setup -
"home, garage, workshop, storage space, or small warehouse," never one
hardcoded building type. No surveillance-identification or face-
recognition features - every task here is plain area visibility
(present/absent-style binary classification), same generic value schema
every prior demo uses. Reference sensor ids `property_entrance_rgb`/
`property_storage_rgb`/`property_indoor_rgb` are three separate physical
camera positions, reusing the same sensor-instance-not-modality
precedent v0.6/v0.7's other demos already established.

Deliberately structured around THREE SEPARATE TASKS (entrance_visibility/
storage_visibility/indoor_visibility), one per camera position, rather
than RideSafe's single shared task - a configuration only ever produces
predictions for a task if it actually includes that area's camera, so a
camera-less area is genuinely N/A (no evidence), never a fabricated
fail. This is the flagship "is the third camera worth its resource
load" worked example (v0.7 architecture review, Q23/Q24): three nested
configurations (entrance-only -> +storage -> +storage+indoor), each a
strict superset of the last, producing a genuine 3-point Pareto
staircase (more sensors always costs more, but also always reaches more
requirement coverage - never a dominated point).

Also generates SYNTHETIC RESOURCE DATA (v0.7) for the one session -
CPU/memory/network/latency/FPS numbers scaling roughly linearly per
added camera, a deliberately different resource story from RideSafe's
"two cameras share some overhead" one. Never measured from real
hardware - see examples/profiles/README.md.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'propertywatch-demo-data.json'

SAMPLE_COUNT = 100
LABELS = ('visible', 'not_visible')

SCENARIO_ID = 'synthetic-propertywatch-demo'
SESSION_ID = 'propertywatch-demo-session'

ENTRANCE, STORAGE, INDOOR = 'property_entrance_rgb', 'property_storage_rgb', 'property_indoor_rgb'

# (source_id, sensor_ids, {task: target_correct_count}, rng_seed_base) -
# nested configurations, each a strict superset of the last. A
# configuration only produces predictions for a task if the relevant
# camera is actually present - entrance-only never produces
# storage_visibility/indoor_visibility predictions at all (genuinely no
# evidence, not a fabricated fail). target_correct is chosen, not
# measured - exact accuracy by construction, same technique every prior
# demo generator uses.
CONFIGS = [
    ('property_entrance_classifier', [ENTRANCE], {'entrance_visibility': 78}, 601),
    ('property_entrance_storage_classifier', [ENTRANCE, STORAGE],
     {'entrance_visibility': 85, 'storage_visibility': 72}, 602),
    ('property_entrance_storage_indoor_classifier', [ENTRANCE, STORAGE, INDOOR],
     {'entrance_visibility': 92, 'storage_visibility': 80, 'indoor_visibility': 88}, 603),
]
TASKS = ['entrance_visibility', 'storage_visibility', 'indoor_visibility']

# SYNTHETIC RESOURCE DATA - roughly linear per added camera, a
# deliberately different shape from RideSafe's "shared overhead" story.
RESOURCE_PLATFORM_ID = 'propertywatch-synthetic-platform'
RESOURCE_TARGETS = {
    ENTRANCE: {
        'cpu_percent': 15.0, 'memory_mb': 480.0, 'network_receive_mbps': 3.8,
        'network_transmit_mbps': 0.9, 'pipeline_latency_ms': 28.0, 'fps': 29.6,
    },
    f'{ENTRANCE}-{STORAGE}': {
        'cpu_percent': 26.5, 'memory_mb': 730.0, 'network_receive_mbps': 7.5,
        'network_transmit_mbps': 1.8, 'pipeline_latency_ms': 34.0, 'fps': 29.5,
    },
    f'{ENTRANCE}-{INDOOR}-{STORAGE}': {
        'cpu_percent': 38.0, 'memory_mb': 980.0, 'network_receive_mbps': 11.4,
        'network_transmit_mbps': 2.7, 'pipeline_latency_ms': 41.0, 'fps': 29.3,
    },
}
RESOURCE_UNITS = {
    'cpu_percent': '%', 'memory_mb': 'MB', 'network_receive_mbps': 'Mbps',
    'network_transmit_mbps': 'Mbps', 'pipeline_latency_ms': 'ms', 'fps': 'fps',
}
RESOURCE_SOURCES = {
    'cpu_percent': 'psutil.cpu_percent', 'memory_mb': 'psutil.virtual_memory',
    'network_receive_mbps': 'psutil.net_io_counters', 'network_transmit_mbps': 'psutil.net_io_counters',
    'pipeline_latency_ms': 'ros_diagnostics:publish_latency_ms', 'fps': 'ros_diagnostics:fps_received',
}


def build_ground_truth() -> dict[str, list[dict]]:
    ground_truth = {}
    for task_index, task in enumerate(TASKS):
        labels = ['visible'] * (SAMPLE_COUNT // 2) + ['not_visible'] * (SAMPLE_COUNT // 2)
        random.Random(42 + task_index).shuffle(labels)
        ground_truth[task] = [
            {
                'id': f'gt-{SESSION_ID}-{task}-{i:04d}',
                'timestamp_ms': float(i * 1000),
                'task': task,
                'value': {'label': label},
                'metadata': {'synthetic': True},
            }
            for i, label in enumerate(labels)
        ]
    return ground_truth


def build_predictions(ground_truth: dict[str, list[dict]]) -> list[dict]:
    predictions = []
    for source_id, sensor_ids, task_targets, seed_base in CONFIGS:
        # Always sorted - derive_configuration_id (backend/app/domain/models.py)
        # sorts sensor_ids before joining, and entrance/storage/indoor are
        # NOT already alphabetical (indoor < storage), unlike RideSafe's
        # front/rear pair - joining insertion order here would silently
        # produce the wrong configuration_id.
        config_label = '-'.join(sorted(sensor_ids))
        for task, target_correct in task_targets.items():
            rng = random.Random(seed_base + TASKS.index(task))
            task_gt = ground_truth[task]
            wrong_indices = set(rng.sample(range(SAMPLE_COUNT), SAMPLE_COUNT - target_correct))
            for i, gt in enumerate(task_gt):
                true_label = gt['value']['label']
                if i in wrong_indices:
                    predicted_label = next(label for label in LABELS if label != true_label)
                    confidence = round(rng.uniform(0.50, 0.65), 2)
                else:
                    predicted_label = true_label
                    confidence = round(rng.uniform(0.85, 0.99), 2)
                predictions.append({
                    'id': f'pred-{SESSION_ID}-{config_label}-{task}-{i:04d}',
                    'timestamp_ms': gt['timestamp_ms'] + rng.uniform(1, 5),
                    'source_id': source_id,
                    'sensor_ids': sensor_ids,
                    'task': task,
                    'value': {'label': predicted_label},
                    'confidence': confidence,
                    'metadata': {'synthetic': True},
                })
    return predictions


def build_resource_observations() -> list[dict]:
    observations = []
    started, ended = '2026-08-13T20:00:00Z', '2026-08-13T20:00:10Z'
    for config_label, metrics in RESOURCE_TARGETS.items():
        for metric, value in metrics.items():
            observations.append({
                'id': f'resobs-{SESSION_ID}-{config_label}-{metric}',
                'configuration_id': f'cfg-{config_label}',
                'metric': metric,
                'value': value,
                'unit': RESOURCE_UNITS[metric],
                'quality': 'measured',
                'source': RESOURCE_SOURCES[metric],
                'platform_id': RESOURCE_PLATFORM_ID,
                'started_at': started,
                'ended_at': ended,
                'sample_count': 1,
                'metadata': {'synthetic': True},
            })
    return observations


def main() -> None:
    scenario = {
        'id': SCENARIO_ID,
        'name': 'Synthetic PropertyWatch Demo',
        'description': (
            'Deterministic synthetic dataset for demonstrating the MultiSens v0.7 '
            'deployment/resource-tradeoff workflow around a personal multi-camera '
            'property monitoring setup - home, garage, workshop, storage space, or '
            'small warehouse, never one hardcoded building type. Ground truth, '
            'predictions, and resource observations are all generated, not '
            'measured - see examples/profiles/README.md. No surveillance-'
            'identification or face-recognition features of any kind.'
        ),
        'tags': ['synthetic', 'demo', 'area_visibility', 'propertywatch'],
        'metadata': {'synthetic': True},
    }

    session = {
        'id': SESSION_ID, 'name': 'PropertyWatch Demo Session',
        'scenario_id': SCENARIO_ID, 'metadata': {'synthetic': True},
    }

    ground_truth_by_task = build_ground_truth()
    predictions = build_predictions(ground_truth_by_task)
    resource_observations = build_resource_observations()

    all_ground_truth = [gt for task_gt in ground_truth_by_task.values() for gt in task_gt]

    dataset = {
        'format_version': '1.0',
        'scenario': scenario,
        'sessions': [session],
        'ground_truth': {SESSION_ID: all_ground_truth},
        'predictions': {SESSION_ID: predictions},
        'resource_observations': {SESSION_ID: resource_observations},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    print(
        f'wrote {OUTPUT_PATH} (1 session, {len(all_ground_truth)} ground truth, '
        f'{len(predictions)} predictions, {len(resource_observations)} resource observations)'
    )


if __name__ == '__main__':
    main()
