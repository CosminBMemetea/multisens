#!/usr/bin/env python3
"""Loads examples/evaluation/classification-demo.json into a running
MultiSens backend via its ordinary REST API - no dedicated import
endpoint exists (see examples/evaluation/README.md for why), so this
script *is* the import path: create scenario, create session, two
batches, evaluate.

Idempotent-ish: re-running it after the scenario/session already exist
prints a message and continues (ground-truth/prediction ids are fixed in
the file, so a second batch POST would report every item as a duplicate-
id rejection - harmless, but noisy, so this skips ingestion entirely if
the session is already present).

    docker compose up -d
    python3 scripts/load_demo_data.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get('MULTISENS_API_BASE', 'http://localhost:8000')
DATA_PATH = Path(__file__).parent.parent / 'examples' / 'evaluation' / 'classification-demo.json'


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
    session_id = dataset['session']['id']

    status, _ = _request('GET', f'/api/sessions/{session_id}')
    if status == 200:
        print(f"session '{session_id}' already exists - nothing to ingest, jumping to evaluate.")
    else:
        status, body = _request('POST', '/api/scenarios', dataset['scenario'])
        if status not in (201, 409):
            sys.exit(f'failed to create scenario: {status} {body}')
        print(f"scenario: {'created' if status == 201 else 'already existed'}")

        status, body = _request('POST', '/api/sessions', dataset['session'])
        if status not in (201, 409):
            sys.exit(f'failed to create session: {status} {body}')
        print(f"session: {'created' if status == 201 else 'already existed'}")

        status, body = _request(
            'POST', f'/api/sessions/{session_id}/ground-truth/batch', {'items': dataset['ground_truth']}
        )
        if status != 201:
            sys.exit(f'ground-truth batch failed: {status} {body}')
        print(f"ground truth: accepted={body['accepted']} rejected={body['rejected']}")

        status, body = _request(
            'POST', f'/api/sessions/{session_id}/predictions/batch', {'items': dataset['predictions']}
        )
        if status != 201:
            sys.exit(f'predictions batch failed: {status} {body}')
        print(f"predictions: accepted={body['accepted']} rejected={body['rejected']}")

    status, results = _request('POST', f'/api/sessions/{session_id}/evaluate', {'task': 'presence'})
    if status != 200:
        sys.exit(f'evaluate failed: {status} {results}')

    print('\nevaluation results:')
    for r in sorted(results, key=lambda r: r['configuration_id']):
        print(
            f"  {r['configuration_id']:12s} accuracy={r['metrics']['accuracy']:.3f} "
            f"precision_macro={r['metrics']['precision_macro']:.3f} "
            f"recall_macro={r['metrics']['recall_macro']:.3f} "
            f"f1_macro={r['metrics']['f1_macro']:.3f} "
            f"({r['matched_samples']}/{r['sample_count']} matched)"
        )
    print(f"\nopen http://localhost:8080/sessions/{session_id} to view.")


if __name__ == '__main__':
    main()
