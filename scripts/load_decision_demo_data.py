#!/usr/bin/env python3
"""Loads examples/profiles/exterior-decision-demo-data.json and
exterior-decision-demo.json into a running MultiSens backend via its
ordinary REST API - same "no dedicated import endpoint" reasoning as
scripts/load_demo_data.py / scripts/load_profile_demo_data.py.

Idempotent-ish: skips ingestion if the session already exists, skips
creating the profile if its id already exists (profiles are immutable).

    docker compose up -d
    python3 scripts/load_decision_demo_data.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get('MULTISENS_API_BASE', 'http://localhost:8000')
DATA_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'exterior-decision-demo-data.json'
PROFILE_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'exterior-decision-demo.json'

# Same demo policy examples/profiles/README.md documents for this demo -
# not a system default (see docs/decision-support.md - DecisionPolicy has
# no default anywhere; this script supplies one explicitly, same as any
# other caller would have to).
DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 0.95,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}


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

    status, _ = _request('GET', f"/api/sessions/{session['id']}")
    if status == 200:
        print("session already loaded - jumping to evaluate.")
    else:
        status, body = _request('POST', '/api/scenarios', dataset['scenario'])
        if status not in (201, 409):
            sys.exit(f'failed to create scenario: {status} {body}')
        print(f"scenario: {'created' if status == 201 else 'already existed'}")

        status, body = _request('POST', '/api/sessions', session)
        if status not in (201, 409):
            sys.exit(f"failed to create session '{session['id']}': {status} {body}")

        status, body = _request(
            'POST', f"/api/sessions/{session['id']}/ground-truth/batch",
            {'items': dataset['ground_truth'][session['id']]},
        )
        if status != 201:
            sys.exit(f"ground-truth batch failed: {status} {body}")

        status, body = _request(
            'POST', f"/api/sessions/{session['id']}/predictions/batch",
            {'items': dataset['predictions'][session['id']]},
        )
        if status != 201:
            sys.exit(f"predictions batch failed: {status} {body}")

        print(f"session '{session['id']}': ground truth + predictions loaded")

    status, results = _request('POST', f"/api/sessions/{session['id']}/evaluate", {'task': 'object_presence'})
    if status != 200:
        sys.exit(f"evaluate failed: {status} {results}")
    print(f"  evaluated {len(results)} configurations for '{session['id']}'")

    status, body = _request('GET', f"/api/profiles/{profile['id']}")
    if status == 200:
        print(f"profile '{profile['id']}' already exists - nothing to import.")
    else:
        status, body = _request('POST', '/api/profiles', profile)
        if status != 201:
            sys.exit(f'failed to create profile: {status} {body}')
        print(f"profile '{profile['id']}': created")

    # session_ids scoped to just this demo's own session - same "avoid
    # noisy unrelated-configuration rows" reasoning as
    # load_profile_demo_data.py.
    status, analysis = _request(
        'POST', f"/api/profiles/{profile['id']}/decision-analysis",
        {'policy': DEMO_POLICY, 'session_ids': [session['id']]},
    )
    if status != 200:
        sys.exit(f'decision analysis failed: {status} {analysis}')

    print('\ndecision analysis summary:')
    for c in sorted(analysis['configurations'], key=lambda c: (c['sensor_count'], c['configuration_id'])):
        cov = f"{round(c['summary']['requirement_coverage'] * 100)}%" if c['summary']['requirement_coverage'] is not None else 'N/A'
        print(
            f"  {c['configuration_id']:48s} sensors={c['sensor_count']}  coverage={cov:>5s}  "
            f"status={c['policy_status'] or 'NO EVIDENCE':13s}  dominated={c['dominated']}"
        )

    print(f"\nminimum sufficient: {analysis['minimal_sufficient_configuration_ids']}")
    print(f"pareto front:       {analysis['pareto_front_configuration_ids']}")
    print(f"\nopen http://localhost:8080/profiles/{profile['id']}?tab=decision to view.")


if __name__ == '__main__':
    main()
