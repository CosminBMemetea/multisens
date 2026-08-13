#!/usr/bin/env python3
"""Loads examples/profiles/propertywatch-demo-data.json and
propertywatch-demo.json into a running MultiSens backend via its
ordinary REST API - same "no dedicated import endpoint" reasoning as
every prior loader script.

Idempotent-ish: skips ingestion if the session already exists, skips
creating the profile if its id already exists (profiles are immutable).

    docker compose up -d
    python3 scripts/load_propertywatch_demo_data.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get('MULTISENS_API_BASE', 'http://localhost:8000')
DATA_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'propertywatch-demo-data.json'
PROFILE_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'propertywatch-demo.json'

TASKS = ['entrance_visibility', 'storage_visibility', 'indoor_visibility']

# Deliberately loose (like RideSafe's own loader) - illustrative only,
# for this script's own printed summary. See examples/profiles/README.md
# for why some configurations are genuinely N/A on some requirements
# (a camera-less area has no evidence at all, not a fabricated fail).
DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 0.7,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}

RESOURCE_METRICS = ['cpu_percent', 'memory_mb', 'network_receive_mbps', 'network_transmit_mbps',
                     'pipeline_latency_ms', 'fps']


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
    profile = json.loads(PROFILE_PATH.read_text())
    session = dataset['sessions'][0]
    session_id = session['id']

    status, _ = _request('GET', f'/api/sessions/{session_id}')
    if status == 200:
        print('session already loaded - jumping to profile/tradeoffs.')
    else:
        status, body = _request('POST', '/api/scenarios', dataset['scenario'])
        if status not in (201, 409):
            sys.exit(f'failed to create scenario: {status} {body}')
        print(f"scenario: {'created' if status == 201 else 'already existed'}")

        status, body = _request('POST', '/api/sessions', session)
        if status not in (201, 409):
            sys.exit(f"failed to create session '{session_id}': {status} {body}")

        status, body = _request(
            'POST', f'/api/sessions/{session_id}/ground-truth/batch',
            {'items': dataset['ground_truth'][session_id]},
        )
        if status != 201:
            sys.exit(f'ground-truth batch failed: {status} {body}')

        status, body = _request(
            'POST', f'/api/sessions/{session_id}/predictions/batch',
            {'items': dataset['predictions'][session_id]},
        )
        if status != 201:
            sys.exit(f'predictions batch failed: {status} {body}')

        status, body = _request(
            'POST', f'/api/sessions/{session_id}/resource-observations/batch',
            {'items': dataset['resource_observations'][session_id]},
        )
        if status != 201:
            sys.exit(f'resource-observations batch failed: {status} {body}')

        print(f"session '{session_id}': ground truth + predictions + resource observations loaded")

        for task in TASKS:
            status, results = _request('POST', f'/api/sessions/{session_id}/evaluate', {'task': task})
            if status != 200:
                sys.exit(f"evaluate failed for task '{task}': {status} {results}")
            print(f"  evaluated {len(results)} configurations for task '{task}'")

    status, body = _request('GET', f"/api/profiles/{profile['id']}")
    if status == 200:
        print(f"profile '{profile['id']}' already exists - nothing to import.")
    else:
        status, body = _request('POST', '/api/profiles', profile)
        if status != 201:
            sys.exit(f'failed to create profile: {status} {body}')
        print(f"profile '{profile['id']}': created")

    status, tradeoffs = _request(
        'POST', f"/api/profiles/{profile['id']}/tradeoffs",
        {
            'policy': DEMO_POLICY, 'session_id': session_id,
            'resource_metrics': RESOURCE_METRICS,
            'pareto_dimensions': {'sensor_count': 'minimize', 'requirement_coverage': 'maximize'},
        },
    )
    if status != 200:
        sys.exit(f'tradeoffs failed: {status} {tradeoffs}')

    print('\nresource trade-off summary:')
    for c in sorted(tradeoffs['configurations'], key=lambda c: (c['sensor_count'], c['configuration_id'])):
        cov = f"{round(c['requirement_coverage'] * 100)}%" if c['requirement_coverage'] is not None else 'N/A'
        cpu = c['resource_profile']['metrics'].get('cpu_percent', {}).get('mean') if c['resource_profile'] else None
        cpu_str = f'{cpu:.1f}%' if cpu is not None else 'N/A'
        print(
            f"  {c['configuration_id']:65s} sensors={c['sensor_count']}  coverage={cov:>5s}  "
            f"status={c['policy_status'] or 'NO EVIDENCE':13s}  cpu={cpu_str}"
        )

    print(f"\npareto front (sensors vs coverage): {tradeoffs['pareto_front_configuration_ids']}")
    print(f"\nopen http://localhost:8080/profiles/{profile['id']}?tab=decision to view coverage/decision.")
    print(f"open http://localhost:8080/profiles/{profile['id']}?tab=resources to view resource trade-offs.")


if __name__ == '__main__':
    main()
