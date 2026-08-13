"""Phase 61: the shipped exterior decision demo's numbers must not
silently drift. Independently recomputes expected accuracy, per-
requirement PASS/FAIL, coverage, the minimum sufficient configuration,
and the Pareto front straight from the raw JSON (nearest-timestamp
matching and plain-Python set logic - deliberately NOT importing
app.domain.decision/coverage/analysis/profiles), and cross-checks it
against what the real API returns end to end. Same rigor and structure
as test_profile_demo.py (v0.4/v0.5's identical guard).
"""
import json
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'exterior-decision-demo-data.json'
PROFILE_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'exterior-decision-demo.json'

# By construction (see scripts/generate_decision_demo_data.py), not measured.
EXPECTED_ACCURACY = {
    'cfg-front_rgb': 0.60,
    'cfg-rear_rgb': 0.55,
    'cfg-front_rgb-rear_rgb': 0.72,
    'cfg-front_rgb-sim_thermal': 0.88,
    'cfg-front_rgb-sim_depth': 0.70,
    'cfg-front_rgb-rear_rgb-sim_thermal': 0.98,
    'cfg-front_rgb-rear_rgb-sim_depth': 0.85,
    'cfg-front_rgb-rear_rgb-sim_depth-sim_thermal': 0.98,
}

# requirement_id -> threshold - hand-derived from exterior-decision-demo.json,
# independent of parsing that file's `acceptance` structure at all.
REQUIREMENTS = {
    'req-basic': 0.50,
    'req-standard': 0.70,
    'req-advanced': 0.85,
    'req-strict': 0.97,
}

CONFIGS = list(EXPECTED_ACCURACY)

SENSOR_IDS = {
    'cfg-front_rgb': {'front_rgb'},
    'cfg-rear_rgb': {'rear_rgb'},
    'cfg-front_rgb-rear_rgb': {'front_rgb', 'rear_rgb'},
    'cfg-front_rgb-sim_thermal': {'front_rgb', 'sim_thermal'},
    'cfg-front_rgb-sim_depth': {'front_rgb', 'sim_depth'},
    'cfg-front_rgb-rear_rgb-sim_thermal': {'front_rgb', 'rear_rgb', 'sim_thermal'},
    'cfg-front_rgb-rear_rgb-sim_depth': {'front_rgb', 'rear_rgb', 'sim_depth'},
    'cfg-front_rgb-rear_rgb-sim_depth-sim_thermal': {'front_rgb', 'rear_rgb', 'sim_depth', 'sim_thermal'},
}

# Hand-verified (see examples/profiles/README.md's derivation) - every
# one of the 8 configurations x 4 requirements = 32 cells.
EXPECTED_STATUS = {
    'cfg-front_rgb': {'req-basic': 'pass', 'req-standard': 'fail', 'req-advanced': 'fail', 'req-strict': 'fail'},
    'cfg-rear_rgb': {'req-basic': 'pass', 'req-standard': 'fail', 'req-advanced': 'fail', 'req-strict': 'fail'},
    'cfg-front_rgb-rear_rgb': {'req-basic': 'pass', 'req-standard': 'pass', 'req-advanced': 'fail', 'req-strict': 'fail'},
    'cfg-front_rgb-sim_thermal': {'req-basic': 'pass', 'req-standard': 'pass', 'req-advanced': 'pass', 'req-strict': 'fail'},
    'cfg-front_rgb-sim_depth': {'req-basic': 'pass', 'req-standard': 'pass', 'req-advanced': 'fail', 'req-strict': 'fail'},
    'cfg-front_rgb-rear_rgb-sim_thermal': {'req-basic': 'pass', 'req-standard': 'pass', 'req-advanced': 'pass', 'req-strict': 'pass'},
    'cfg-front_rgb-rear_rgb-sim_depth': {'req-basic': 'pass', 'req-standard': 'pass', 'req-advanced': 'pass', 'req-strict': 'fail'},
    'cfg-front_rgb-rear_rgb-sim_depth-sim_thermal': {'req-basic': 'pass', 'req-standard': 'pass', 'req-advanced': 'pass', 'req-strict': 'pass'},
}

# pass_count / 4 - restated here as an independent cross-check target.
EXPECTED_COVERAGE = {
    'cfg-front_rgb': 0.25,
    'cfg-rear_rgb': 0.25,
    'cfg-front_rgb-rear_rgb': 0.50,
    'cfg-front_rgb-sim_thermal': 0.75,
    'cfg-front_rgb-sim_depth': 0.50,
    'cfg-front_rgb-rear_rgb-sim_thermal': 1.00,
    'cfg-front_rgb-rear_rgb-sim_depth': 0.75,
    'cfg-front_rgb-rear_rgb-sim_depth-sim_thermal': 1.00,
}

# The one and only sufficient config not a superset of another sufficient
# one, under the standard demo policy (coverage>=1.0, completeness>=0.95,
# mandatory=False) - sim_depth genuinely adds nothing under this profile.
EXPECTED_MINIMAL_SUFFICIENT = {'cfg-front_rgb-rear_rgb-sim_thermal'}

# Non-dominated under (sensor_count, coverage, completeness) - completeness
# is 1.0 everywhere in this demo (fully evaluated, single session), so
# only sensor_count/coverage differentiate here.
EXPECTED_PARETO_FRONT = {
    'cfg-front_rgb', 'cfg-rear_rgb', 'cfg-front_rgb-sim_thermal', 'cfg-front_rgb-rear_rgb-sim_thermal',
}
EXPECTED_DOMINATED = {
    'cfg-front_rgb-rear_rgb', 'cfg-front_rgb-sim_depth',
    'cfg-front_rgb-rear_rgb-sim_depth', 'cfg-front_rgb-rear_rgb-sim_depth-sim_thermal',
}

DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 0.95,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}


def _load_data() -> dict:
    return json.loads(DATA_PATH.read_text())


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _independent_accuracy(dataset: dict) -> dict[str, float]:
    session_id = dataset['sessions'][0]['id']
    ground_truth = dataset['ground_truth'][session_id]
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
    return {config: correct / total for config, (total, correct) in totals.items()}


def _independent_status(accuracy: dict[str, float]) -> dict[str, dict[str, str]]:
    return {
        config: {
            req_id: ('pass' if accuracy[config] >= threshold else 'fail')
            for req_id, threshold in REQUIREMENTS.items()
        }
        for config in CONFIGS
    }


def _independent_minimal_sufficient(coverage: dict[str, float]) -> set[str]:
    """Plain set-inclusion minimality over the sufficient (coverage >=
    1.0) configurations, reimplemented from scratch in plain Python -
    not importing app.domain.decision.find_minimal_sufficient_sets."""
    sufficient = {c for c in CONFIGS if coverage[c] >= DEMO_POLICY['minimum_requirement_coverage']}
    return {
        c for c in sufficient
        if not any(SENSOR_IDS[other] < SENSOR_IDS[c] for other in sufficient if other != c)
    }


def _independent_pareto_front(coverage: dict[str, float]) -> set[str]:
    """Plain pairwise dominance, reimplemented from scratch - completeness
    is 1.0 for every configuration in this demo (single fully-evaluated
    session), so only sensor_count/coverage matter here."""
    def dominates(a: str, b: str) -> bool:
        a_sensors, b_sensors = len(SENSOR_IDS[a]), len(SENSOR_IDS[b])
        if a_sensors > b_sensors or coverage[a] < coverage[b]:
            return False
        return a_sensors < b_sensors or coverage[a] > coverage[b]

    dominated = {c for c in CONFIGS if any(dominates(other, c) for other in CONFIGS if other != c)}
    return set(CONFIGS) - dominated


def test_dataset_file_has_expected_shape():
    dataset = _load_data()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['sessions']) == 1
    assert 'synthetic' in dataset['scenario']['tags']
    session = dataset['sessions'][0]
    assert session['metadata']['synthetic'] is True
    assert len(dataset['ground_truth'][session['id']]) == 100
    assert len(dataset['predictions'][session['id']]) == 800  # 8 configs x 100


def test_profile_file_has_expected_shape():
    profile = _load_profile()
    assert profile['metadata']['synthetic'] is True
    assert len(profile['groups']) == 2
    assert len(profile['requirements']) == 4
    assert {r['id'] for r in profile['requirements']} == set(REQUIREMENTS)
    # No condition dimensions anywhere - this demo is about the sensor-
    # combination space, not a second condition-exploration showcase.
    for requirement in profile['requirements']:
        assert requirement.get('conditions', {}) == {}


def test_independent_accuracy_matches_construction_targets():
    accuracy = _independent_accuracy(_load_data())
    assert accuracy == EXPECTED_ACCURACY


def test_independent_status_matches_hand_derived_table():
    accuracy = _independent_accuracy(_load_data())
    assert _independent_status(accuracy) == EXPECTED_STATUS


def test_independent_minimal_sufficient_matches_hand_derived_set():
    assert _independent_minimal_sufficient(EXPECTED_COVERAGE) == EXPECTED_MINIMAL_SUFFICIENT


def test_independent_pareto_front_matches_hand_derived_set():
    front = _independent_pareto_front(EXPECTED_COVERAGE)
    assert front == EXPECTED_PARETO_FRONT
    assert set(CONFIGS) - front == EXPECTED_DOMINATED


def test_api_decision_analysis_matches_independently_computed_values(client):
    dataset = _load_data()
    profile = _load_profile()
    session = dataset['sessions'][0]

    resp = client.post('/api/scenarios', json=dataset['scenario'])
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions', json=session)
    assert resp.status_code == 201, resp.text
    resp = client.post(
        f"/api/sessions/{session['id']}/ground-truth/batch", json={'items': dataset['ground_truth'][session['id']]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
    resp = client.post(
        f"/api/sessions/{session['id']}/predictions/batch", json={'items': dataset['predictions'][session['id']]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
    resp = client.post(f"/api/sessions/{session['id']}/evaluate", json={'task': 'object_presence'})
    assert resp.status_code == 200, resp.text

    resp = client.post('/api/profiles', json=profile)
    assert resp.status_code == 201, resp.text

    resp = client.post(f"/api/profiles/{profile['id']}/decision-analysis", json={'policy': DEMO_POLICY})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    configs_by_id = {c['configuration_id']: c for c in body['configurations']}
    assert set(configs_by_id) == set(CONFIGS)

    for config_id, expected_status in EXPECTED_STATUS.items():
        api_config = configs_by_id[config_id]
        assert api_config['sensor_count'] == len(SENSOR_IDS[config_id])
        assert set(api_config['sensor_ids']) == SENSOR_IDS[config_id]
        assert api_config['summary']['requirement_coverage'] == pytest.approx(EXPECTED_COVERAGE[config_id])
        results_by_req = {r['requirement_id']: r['status'] for r in api_config['requirement_results']}
        assert results_by_req == expected_status

    assert set(body['minimal_sufficient_configuration_ids']) == EXPECTED_MINIMAL_SUFFICIENT
    assert set(body['pareto_front_configuration_ids']) == EXPECTED_PARETO_FRONT
    dominated_ids = {c['configuration_id'] for c in body['configurations'] if c['dominated']}
    assert dominated_ids == EXPECTED_DOMINATED
