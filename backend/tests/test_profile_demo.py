"""Phase 39: the shipped synthetic reference profile's numbers must not
silently drift. Independently recomputes expected accuracy, per-
requirement PASS/FAIL/N/A, and group/root coverage straight from the raw
JSON (nearest-timestamp matching and plain-dict condition matching in
plain Python - deliberately NOT importing app.domain.evidence/coverage/
profiles), and cross-checks it against what the real API returns end to
end. If these two disagree, either the shipped files changed or the API
broke - either way, this is the guard. Same rigor and structure as
test_synthetic_demo.py (v0.2/v0.3's identical guard).
"""
import json
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'cabin-safety-demo-data.json'
PROFILE_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'cabin-safety-demo.json'

# By construction (see scripts/generate_profile_demo_data.py), not measured.
EXPECTED_ACCURACY = {
    'cabin-day-clear': {'cfg-rgb': 0.92, 'cfg-depth': 0.88, 'cfg-thermal': 0.78,
                         'cfg-rgb-thermal': 0.94, 'cfg-depth-rgb-thermal': 0.97},
    'cabin-day-occluded': {'cfg-rgb': 0.75, 'cfg-depth': 0.68, 'cfg-thermal': 0.80,
                            'cfg-rgb-thermal': 0.88, 'cfg-depth-rgb-thermal': 0.93},
    'cabin-night-clear': {'cfg-rgb': 0.60, 'cfg-depth': 0.88, 'cfg-thermal': 0.85,
                           'cfg-rgb-thermal': 0.90, 'cfg-depth-rgb-thermal': 0.95},
    'cabin-night-occluded': {'cfg-rgb': 0.45, 'cfg-depth': 0.68, 'cfg-thermal': 0.78,
                              'cfg-rgb-thermal': 0.82, 'cfg-depth-rgb-thermal': 0.90},
}

# requirement_id -> (illumination, occlusion, threshold) - hand-derived
# from cabin-safety-demo.json, independent of parsing that file's
# `acceptance`/`conditions` structure at all.
REQUIREMENTS = {
    'req-day-baseline': ('day', 'none', 0.85),
    'req-night-baseline': ('night', 'none', 0.85),
    'req-day-occluded': ('day', 'partial', 0.80),
    'req-night-occluded': ('night', 'partial', 0.75),
    'req-day-strict': ('day', 'none', 0.95),
    'req-night-strict': ('night', 'none', 0.95),
}

REQUIREMENT_GROUP = {
    'req-day-baseline': 'alertness', 'req-night-baseline': 'alertness',
    'req-day-occluded': 'visibility-robustness', 'req-night-occluded': 'visibility-robustness',
    'req-day-strict': 'occupancy', 'req-night-strict': 'occupancy',
}

CONFIGS = ['cfg-rgb', 'cfg-depth', 'cfg-thermal', 'cfg-rgb-thermal', 'cfg-depth-rgb-thermal']

# Hand-verified (see examples/profiles/README.md's derivation) - every one
# of the 6 requirements x 5 configurations = 30 cells, not just a sample.
EXPECTED_STATUS = {
    'req-day-baseline': {'cfg-rgb': 'pass', 'cfg-depth': 'pass', 'cfg-thermal': 'fail',
                          'cfg-rgb-thermal': 'pass', 'cfg-depth-rgb-thermal': 'pass'},
    'req-night-baseline': {'cfg-rgb': 'fail', 'cfg-depth': 'pass', 'cfg-thermal': 'pass',
                            'cfg-rgb-thermal': 'pass', 'cfg-depth-rgb-thermal': 'pass'},
    'req-day-occluded': {'cfg-rgb': 'fail', 'cfg-depth': 'fail', 'cfg-thermal': 'pass',
                          'cfg-rgb-thermal': 'pass', 'cfg-depth-rgb-thermal': 'pass'},
    'req-night-occluded': {'cfg-rgb': 'fail', 'cfg-depth': 'fail', 'cfg-thermal': 'pass',
                            'cfg-rgb-thermal': 'pass', 'cfg-depth-rgb-thermal': 'pass'},
    'req-day-strict': {'cfg-rgb': 'fail', 'cfg-depth': 'fail', 'cfg-thermal': 'fail',
                        'cfg-rgb-thermal': 'fail', 'cfg-depth-rgb-thermal': 'pass'},
    'req-night-strict': {'cfg-rgb': 'fail', 'cfg-depth': 'fail', 'cfg-thermal': 'fail',
                          'cfg-rgb-thermal': 'fail', 'cfg-depth-rgb-thermal': 'pass'},
}

# pass_count / 6 - derived from EXPECTED_STATUS above, restated here as an
# independent cross-check target for the root GroupCoverage.
EXPECTED_ROOT_COVERAGE = {
    'cfg-rgb': 1 / 6, 'cfg-depth': 2 / 6, 'cfg-thermal': 3 / 6,
    'cfg-rgb-thermal': 4 / 6, 'cfg-depth-rgb-thermal': 6 / 6,
}


def _load_data() -> dict:
    return json.loads(DATA_PATH.read_text())


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _independent_accuracy(dataset: dict) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for session_id, ground_truth in dataset['ground_truth'].items():
        gt_by_ts = {g['timestamp_ms']: g['value']['label'] for g in ground_truth}
        gt_timestamps = sorted(gt_by_ts)
        totals: dict[str, list[int]] = {}
        for p in dataset['predictions'][session_id]:
            config = 'cfg-' + '-'.join(sorted(p['sensor_ids']))
            nearest = min(gt_timestamps, key=lambda t: abs(t - p['timestamp_ms']))
            correct = gt_by_ts[nearest] == p['value']['label']
            counts = totals.setdefault(config, [0, 0])
            counts[0] += 1
            counts[1] += int(correct)
        result[session_id] = {config: correct / total for config, (total, correct) in totals.items()}
    return result


def _independent_status(accuracy: dict[str, dict[str, float]], sessions_by_condition: dict[tuple, str]) -> dict:
    """Reimplements the PASS/FAIL decision from scratch: no evidence
    selection, no acceptance engine - just a dict of accuracies and a
    threshold, exactly what a requirement's condition + acceptance
    criterion reduce to for this deliberately condition-unambiguous demo."""
    status: dict[str, dict[str, str]] = {}
    for req_id, (illumination, occlusion, threshold) in REQUIREMENTS.items():
        session_id = sessions_by_condition[(illumination, occlusion)]
        status[req_id] = {}
        for config in CONFIGS:
            observed = accuracy[session_id][config]
            status[req_id][config] = 'pass' if observed >= threshold else 'fail'
    return status


def test_dataset_file_has_expected_shape():
    dataset = _load_data()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['sessions']) == 4
    assert 'synthetic' in dataset['scenario']['tags']
    for session in dataset['sessions']:
        assert session['metadata']['synthetic'] is True
        assert len(dataset['ground_truth'][session['id']]) == 100
        assert len(dataset['predictions'][session['id']]) == 500  # 5 configs x 100


def test_profile_file_has_expected_shape():
    profile = _load_profile()
    assert profile['metadata']['synthetic'] is True
    assert len(profile['groups']) == 3
    assert len(profile['requirements']) == 6
    assert {g['id'] for g in profile['groups']} == {'alertness', 'visibility-robustness', 'occupancy'}
    assert {r['id'] for r in profile['requirements']} == set(REQUIREMENTS)
    for requirement in profile['requirements']:
        assert requirement['group_id'] == REQUIREMENT_GROUP[requirement['id']]


def test_independent_accuracy_matches_construction_targets():
    accuracy = _independent_accuracy(_load_data())
    assert accuracy == EXPECTED_ACCURACY


def test_independent_status_matches_hand_derived_table():
    # Sanity check on the independent-recomputation helpers themselves,
    # before trusting them to validate the API response below.
    dataset = _load_data()
    sessions_by_condition = {
        (s['metadata']['illumination'], s['metadata']['occlusion']): s['id'] for s in dataset['sessions']
    }
    accuracy = _independent_accuracy(dataset)
    status = _independent_status(accuracy, sessions_by_condition)
    assert status == EXPECTED_STATUS


def test_api_coverage_matches_independently_computed_status(client):
    dataset = _load_data()
    profile = _load_profile()

    resp = client.post('/api/scenarios', json=dataset['scenario'])
    assert resp.status_code == 201, resp.text

    for session in dataset['sessions']:
        resp = client.post('/api/sessions', json=session)
        assert resp.status_code == 201, resp.text
        resp = client.post(
            f"/api/sessions/{session['id']}/ground-truth/batch",
            json={'items': dataset['ground_truth'][session['id']]},
        )
        assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
        resp = client.post(
            f"/api/sessions/{session['id']}/predictions/batch",
            json={'items': dataset['predictions'][session['id']]},
        )
        assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
        resp = client.post(f"/api/sessions/{session['id']}/evaluate", json={'task': 'presence'})
        assert resp.status_code == 200, resp.text

    resp = client.post('/api/profiles', json=profile)
    assert resp.status_code == 201, resp.text

    resp = client.post(f"/api/profiles/{profile['id']}/coverage", json={})
    assert resp.status_code == 200, resp.text
    coverages = {c['configuration_id']: c for c in resp.json()['configuration_coverages']}
    assert set(coverages) == set(CONFIGS)

    # Every one of the 30 cells (6 requirements x 5 configurations),
    # cross-checked against the independently hand-derived table.
    for config, coverage in coverages.items():
        results_by_req = {r['requirement_id']: r for r in coverage['requirement_results']}
        assert set(results_by_req) == set(REQUIREMENTS)
        for req_id, expected_status in EXPECTED_STATUS.items():
            actual = results_by_req[req_id]
            assert actual['status'] == expected_status[config], f'{req_id} / {config}'
            assert actual['evidence'] is not None  # every cell in this demo has resolvable evidence, never N/A
            observed = actual['criteria'][0]['observed']
            assert observed == pytest.approx(EXPECTED_ACCURACY[actual['evidence']['session_id']][config])

    # Root coverage per configuration - leaf-count aggregation, cross-
    # checked against the independently derived pass-count table.
    for config, coverage in coverages.items():
        root = coverage['root']
        assert root['pass_count'] + root['fail_count'] == 6
        assert root['na_count'] == 0
        assert root['requirement_coverage'] == pytest.approx(EXPECTED_ROOT_COVERAGE[config])
        assert root['evidence_completeness'] == pytest.approx(1.0)
