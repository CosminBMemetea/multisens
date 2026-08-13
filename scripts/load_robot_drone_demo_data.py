#!/usr/bin/env python3
"""Loads examples/profiles/robot-drone-demo-data.json into a running
MultiSens backend via its ordinary REST API, and runs /evaluate for both
tasks (obstacle_detection over the object_detection evaluator,
distance_estimation over the regression evaluator, each across two
configurations) - the v0.8 Robot/Drone Sensing Demo (Phase 89). Same
"no dedicated import endpoint" reasoning and idempotent-ish "skip if the
session already exists" behavior as every prior loader script.

    docker compose up -d
    python3 scripts/load_robot_drone_demo_data.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get('MULTISENS_API_BASE', 'http://localhost:8000')
DATA_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'robot-drone-demo-data.json'

SESSION_ID = 'robot-drone-demo-session'


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f'{API_BASE}{path}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main() -> None:
    dataset = json.loads(DATA_PATH.read_text())

    status, _ = _request('GET', f'/api/sessions/{SESSION_ID}')
    if status == 200:
        print('session already loaded - jumping straight to evaluation.')
    else:
        status, body = _request('POST', '/api/scenarios', dataset['scenario'])
        if status not in (201, 409):
            sys.exit(f'failed to create scenario: {status} {body}')
        print(f"scenario: {'created' if status == 201 else 'already existed'}")

        status, body = _request('POST', '/api/sessions', dataset['sessions'][0])
        if status not in (201, 409):
            sys.exit(f'failed to create session: {status} {body}')

        status, body = _request(
            'POST', f'/api/sessions/{SESSION_ID}/ground-truth/batch',
            {'items': dataset['ground_truth'][SESSION_ID]},
        )
        if status != 201:
            sys.exit(f'ground-truth batch failed: {status} {body}')

        status, body = _request(
            'POST', f'/api/sessions/{SESSION_ID}/predictions/batch',
            {'items': dataset['predictions'][SESSION_ID]},
        )
        if status != 201:
            sys.exit(f'predictions batch failed: {status} {body}')
        print('session created, ground truth + predictions loaded.')

    for task, task_info in dataset['tasks'].items():
        evaluator_type = task_info['evaluator_type']
        parameters = dataset['detection_parameters'] if evaluator_type == 'object_detection' else {}
        for config_id in task_info['configuration_ids']:
            status, results = _request('POST', f'/api/sessions/{SESSION_ID}/evaluate', {
                'task': task, 'configuration_ids': [config_id],
                'evaluator_type': evaluator_type, 'parameters': parameters,
            })
            if status != 200:
                sys.exit(f"evaluate failed for task '{task}' config '{config_id}': {status} {results}")
            m = results[0]['metrics']
            if evaluator_type == 'object_detection':
                print(
                    f"{task:20s} {config_id:20s} precision={m['precision']:.2f} recall={m['recall']:.2f} "
                    f"f1={m['f1']:.2f} mean_iou={m['mean_iou_matched']:.2f} "
                    f"(TP={int(m['true_positives'])} FP={int(m['false_positives'])} FN={int(m['false_negatives'])})"
                )
            else:
                print(
                    f"{task:20s} {config_id:20s} mae={m['mae']:.3f} rmse={m['rmse']:.3f} "
                    f"bias={m['bias']:.3f} median={m['median_absolute_error']:.3f}"
                )

    print(f'\nopen http://localhost:8080/sessions/{SESSION_ID} to view the detection/regression evaluation panels.')


if __name__ == '__main__':
    main()
