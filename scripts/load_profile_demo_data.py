#!/usr/bin/env python3
"""Loads examples/profiles/sensor-lab-demo-data.json and
sensor-lab-demo.json into a running MultiSens backend via its ordinary
REST API - same "no dedicated import endpoint" reasoning as
scripts/load_demo_data.py.

Idempotent-ish: skips ingestion for a session that already exists, skips
creating the profile if its id already exists (profiles are immutable -
see app/domain/profiles.py - so there is nothing to "re-import" over).

    docker compose up -d
    python3 scripts/load_profile_demo_data.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get('MULTISENS_API_BASE', 'http://localhost:8000')
DATA_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'sensor-lab-demo-data.json'
PROFILE_PATH = Path(__file__).parent.parent / 'examples' / 'profiles' / 'sensor-lab-demo.json'


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

    status, _ = _request('GET', f"/api/sessions/{dataset['sessions'][0]['id']}")
    if status == 200:
        print("sessions already loaded - jumping to evaluate.")
    else:
        status, body = _request('POST', '/api/scenarios', dataset['scenario'])
        if status not in (201, 409):
            sys.exit(f'failed to create scenario: {status} {body}')
        print(f"scenario: {'created' if status == 201 else 'already existed'}")

        for session in dataset['sessions']:
            status, body = _request('POST', '/api/sessions', session)
            if status not in (201, 409):
                sys.exit(f"failed to create session '{session['id']}': {status} {body}")

            status, body = _request(
                'POST', f"/api/sessions/{session['id']}/ground-truth/batch",
                {'items': dataset['ground_truth'][session['id']]},
            )
            if status != 201:
                sys.exit(f"ground-truth batch failed for '{session['id']}': {status} {body}")

            status, body = _request(
                'POST', f"/api/sessions/{session['id']}/predictions/batch",
                {'items': dataset['predictions'][session['id']]},
            )
            if status != 201:
                sys.exit(f"predictions batch failed for '{session['id']}': {status} {body}")

            print(f"session '{session['id']}': ground truth + predictions loaded")

    for session in dataset['sessions']:
        status, results = _request('POST', f"/api/sessions/{session['id']}/evaluate", {'task': 'presence'})
        if status != 200:
            sys.exit(f"evaluate failed for '{session['id']}': {status} {results}")
        print(f"  evaluated {len(results)} configurations for '{session['id']}'")

    status, body = _request('GET', f"/api/profiles/{profile['id']}")
    if status == 200:
        print(f"profile '{profile['id']}' already exists - nothing to import.")
    else:
        status, body = _request('POST', '/api/profiles', profile)
        if status != 201:
            sys.exit(f'failed to create profile: {status} {body}')
        print(f"profile '{profile['id']}': created")

    # session_ids scoped to just this demo's own sessions - an unfiltered
    # call also discovers any configuration with an evaluated result for
    # 'presence' anywhere else in the database (e.g. the standing v0.2/v0.3
    # demo session), which is correct discovery behavior but would make
    # this sanity-check summary noisy with unrelated all-N/A rows.
    session_ids = [s['id'] for s in dataset['sessions']]
    status, coverage = _request(
        'POST', f"/api/profiles/{profile['id']}/coverage", {'session_ids': session_ids},
    )
    if status != 200:
        sys.exit(f'coverage computation failed: {status} {coverage}')

    print('\ncoverage summary:')
    for cc in sorted(coverage['configuration_coverages'], key=lambda c: c['configuration_id']):
        root = cc['root']
        cov = f"{round(root['requirement_coverage'] * 100)}%" if root['requirement_coverage'] is not None else 'N/A'
        comp = f"{round(root['evidence_completeness'] * 100)}%" if root['evidence_completeness'] is not None else 'N/A'
        print(
            f"  {cc['configuration_id']:25s} pass={root['pass_count']} fail={root['fail_count']} "
            f"na={root['na_count']}  coverage={cov:>5s}  completeness={comp:>5s}"
        )

    print(f"\nopen http://localhost:8080/profiles/{profile['id']} to view.")


if __name__ == '__main__':
    main()
