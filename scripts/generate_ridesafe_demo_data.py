#!/usr/bin/env python3
"""Generates examples/profiles/ridesafe-demo-data.json - a deterministic
synthetic dataset for the v0.7 RideSafe demo (Phase 73).

Run once, output committed to git:

    python3 scripts/generate_ridesafe_demo_data.py

RideSafe is ride monitoring and incident evidence, never a safety-
certification or driver/occupant-monitoring claim - see
examples/profiles/README.md and docs/resources.md for the full framing
discipline. Reference sensor ids `ridesafe_front_rgb`/`ridesafe_rear_rgb`
are two separate physical RGB camera positions (reference hardware: 70mai
front/rear dashcams), reusing the exact sensor-instance-not-modality
precedent v0.6's front_rgb/rear_rgb already established - no new
sensor-identity work needed (see docs/decision-support.md).

Two sessions (day/night), matching sensor-lab-demo's own illumination
dimension mechanism but with zero occupant/driver-monitoring framing -
this demo is about whether a camera *sees the scene*, not who or what is
in it. Three configurations (front-only, rear-only, front+rear) tell a
minimal-sufficient-set story identical in shape to Phase 61's exterior-
decision-demo: a single camera alone is a weak baseline day and night;
only the combined configuration reliably clears every bar.

Also generates SYNTHETIC RESOURCE DATA (v0.7) for the day session only -
CPU/memory/network/latency/FPS numbers chosen to tell a clean "two
cameras cost more but reach full coverage" trade-off story, deliberately
NOT measured from real 70mai/webcam hardware. Real MEASURED numbers are
only ever obtainable by running the /resource-observations API locally
against actual connected hardware - never shipped as committed demo
content (v0.7 architecture review, Q25).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'ridesafe-demo-data.json'

SAMPLE_COUNT = 100
TASK = 'scene_visibility'
LABELS = ('visible', 'not_visible')

SCENARIO_ID = 'synthetic-ridesafe-demo'
DAY_SESSION_ID = 'ridesafe-day-session'
NIGHT_SESSION_ID = 'ridesafe-night-session'

# (source_id, sensor_ids, day_target_correct, night_target_correct, rng_seed).
# target_correct is chosen, not measured - exact accuracy by construction,
# same technique every prior demo generator uses.
#
# The story: front_rgb alone clears the daylight baseline but not low
# light; rear_rgb alone is the mirror image (clears low light, not
# daylight) - two cameras with complementary, not identical, strengths,
# same "genuinely different pass/fail pattern per configuration"
# discipline sensor-lab-demo/exterior-decision-demo already established.
# Only the combined front+rear configuration reliably clears every bar,
# day and night - the single minimal sufficient configuration.
CONFIGS = [
    ('ridesafe_front_rgb_classifier', ['ridesafe_front_rgb'], 72, 48, 501),
    ('ridesafe_rear_rgb_classifier', ['ridesafe_rear_rgb'], 68, 52, 502),
    ('ridesafe_front_rear_rgb_classifier', ['ridesafe_front_rgb', 'ridesafe_rear_rgb'], 95, 78, 503),
]

# SYNTHETIC RESOURCE DATA (day session only) - deliberately roughly
# additive but not exactly double for the combined configuration
# (shared overhead), telling the same "more coverage costs more
# resources" story the v0.7 architecture review's own worked examples
# use. platform_id is a fixed, clearly-labeled synthetic placeholder,
# never claimed as a real measured host.
RESOURCE_PLATFORM_ID = 'ridesafe-synthetic-platform'
RESOURCE_TARGETS = {
    'ridesafe_front_rgb': {
        'cpu_percent': 18.2, 'memory_mb': 580.0, 'network_receive_mbps': 4.5,
        'network_transmit_mbps': 1.1, 'pipeline_latency_ms': 32.0, 'fps': 29.5,
    },
    'ridesafe_rear_rgb': {
        'cpu_percent': 17.4, 'memory_mb': 575.0, 'network_receive_mbps': 4.3,
        'network_transmit_mbps': 1.0, 'pipeline_latency_ms': 33.0, 'fps': 29.8,
    },
    'ridesafe_front_rgb-ridesafe_rear_rgb': {
        'cpu_percent': 29.8, 'memory_mb': 825.0, 'network_receive_mbps': 8.6,
        'network_transmit_mbps': 2.0, 'pipeline_latency_ms': 39.0, 'fps': 29.4,
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


def build_ground_truth(session_id: str) -> list[dict]:
    labels = ['visible'] * (SAMPLE_COUNT // 2) + ['not_visible'] * (SAMPLE_COUNT // 2)
    random.Random(42).shuffle(labels)
    return [
        {
            'id': f'gt-{session_id}-{i:04d}',
            'timestamp_ms': float(i * 1000),
            'task': TASK,
            'value': {'label': label},
            'metadata': {'synthetic': True},
        }
        for i, label in enumerate(labels)
    ]


def build_predictions(session_id: str, ground_truth: list[dict], target_index: int) -> list[dict]:
    predictions = []
    for source_id, sensor_ids, day_target, night_target, seed in CONFIGS:
        target_correct = day_target if target_index == 0 else night_target
        config_label = '-'.join(sensor_ids)
        rng = random.Random(seed + target_index)
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


def build_resource_observations() -> list[dict]:
    observations = []
    started, ended = '2026-08-13T18:00:00Z', '2026-08-13T18:00:10Z'
    for config_label, metrics in RESOURCE_TARGETS.items():
        for metric, value in metrics.items():
            observations.append({
                'id': f'resobs-{DAY_SESSION_ID}-{config_label}-{metric}',
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
        'name': 'Synthetic RideSafe Demo',
        'description': (
            'Deterministic synthetic dataset for demonstrating the MultiSens v0.7 '
            'deployment/resource-tradeoff workflow end to end, around a personal '
            'front/rear dashcam reference setup. Ground truth, predictions, and '
            'resource observations are all generated, not measured - see '
            'examples/profiles/README.md. Ride monitoring and incident-evidence '
            'framing only - not a safety-certification, driver-monitoring, or '
            'occupant-monitoring claim of any kind, and does NOT represent real '
            '70mai or any other camera\'s performance.'
        ),
        'tags': ['synthetic', 'demo', 'scene_visibility', 'ridesafe'],
        'metadata': {'synthetic': True},
    }

    day_session = {
        'id': DAY_SESSION_ID, 'name': 'RideSafe Demo Session - Daylight',
        'scenario_id': SCENARIO_ID, 'metadata': {'synthetic': True, 'illumination': 'day'},
    }
    night_session = {
        'id': NIGHT_SESSION_ID, 'name': 'RideSafe Demo Session - Low Light',
        'scenario_id': SCENARIO_ID, 'metadata': {'synthetic': True, 'illumination': 'night'},
    }

    day_ground_truth = build_ground_truth(DAY_SESSION_ID)
    night_ground_truth = build_ground_truth(NIGHT_SESSION_ID)
    day_predictions = build_predictions(DAY_SESSION_ID, day_ground_truth, target_index=0)
    night_predictions = build_predictions(NIGHT_SESSION_ID, night_ground_truth, target_index=1)
    resource_observations = build_resource_observations()

    dataset = {
        'format_version': '1.0',
        'scenario': scenario,
        'sessions': [day_session, night_session],
        'ground_truth': {DAY_SESSION_ID: day_ground_truth, NIGHT_SESSION_ID: night_ground_truth},
        'predictions': {DAY_SESSION_ID: day_predictions, NIGHT_SESSION_ID: night_predictions},
        'resource_observations': {DAY_SESSION_ID: resource_observations},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + '\n')
    total_predictions = len(day_predictions) + len(night_predictions)
    print(
        f'wrote {OUTPUT_PATH} (2 sessions, '
        f'{len(day_ground_truth) + len(night_ground_truth)} ground truth, '
        f'{total_predictions} predictions, {len(resource_observations)} resource observations)'
    )


if __name__ == '__main__':
    main()
