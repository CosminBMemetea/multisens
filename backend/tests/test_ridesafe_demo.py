"""Phase 73: the shipped RideSafe demo's numbers must not silently
drift. Independently recomputes expected accuracy, per-requirement
PASS/FAIL, coverage, the minimum sufficient configuration, the Pareto
front, and the resource summaries straight from the raw JSON (nearest-
timestamp matching and plain-Python set/mean logic - deliberately NOT
importing app.domain.decision/coverage/analysis/profiles/resources),
and cross-checks it against what the real API returns end to end. Same
rigor and structure as test_decision_demo.py (v0.6's identical guard).
"""
import json
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'ridesafe-demo-data.json'
PROFILE_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'ridesafe-demo.json'

DAY_SESSION_ID = 'ridesafe-day-session'
NIGHT_SESSION_ID = 'ridesafe-night-session'

# By construction (see scripts/generate_ridesafe_demo_data.py), not measured.
EXPECTED_ACCURACY = {
    (DAY_SESSION_ID, 'cfg-ridesafe_front_rgb'): 0.72,
    (DAY_SESSION_ID, 'cfg-ridesafe_rear_rgb'): 0.68,
    (DAY_SESSION_ID, 'cfg-ridesafe_front_rgb-ridesafe_rear_rgb'): 0.95,
    (NIGHT_SESSION_ID, 'cfg-ridesafe_front_rgb'): 0.48,
    (NIGHT_SESSION_ID, 'cfg-ridesafe_rear_rgb'): 0.52,
    (NIGHT_SESSION_ID, 'cfg-ridesafe_front_rgb-ridesafe_rear_rgb'): 0.78,
}

CONFIGS = ['cfg-ridesafe_front_rgb', 'cfg-ridesafe_rear_rgb', 'cfg-ridesafe_front_rgb-ridesafe_rear_rgb']

SENSOR_IDS = {
    'cfg-ridesafe_front_rgb': {'ridesafe_front_rgb'},
    'cfg-ridesafe_rear_rgb': {'ridesafe_rear_rgb'},
    'cfg-ridesafe_front_rgb-ridesafe_rear_rgb': {'ridesafe_front_rgb', 'ridesafe_rear_rgb'},
}

# requirement_id -> (illumination, threshold) - hand-derived from
# ridesafe-demo.json, independent of parsing its own `acceptance`/
# `conditions` structure at all.
REQUIREMENTS = {
    'req-day-baseline': ('day', 0.70),
    'req-night-baseline': ('night', 0.50),
    'req-day-strict': ('day', 0.90),
    'req-night-strict': ('night', 0.65),
}

# Hand-verified - every one of the 3 configurations x 4 requirements = 12 cells.
EXPECTED_STATUS = {
    'cfg-ridesafe_front_rgb': {
        'req-day-baseline': 'pass', 'req-night-baseline': 'fail',
        'req-day-strict': 'fail', 'req-night-strict': 'fail',
    },
    'cfg-ridesafe_rear_rgb': {
        'req-day-baseline': 'fail', 'req-night-baseline': 'pass',
        'req-day-strict': 'fail', 'req-night-strict': 'fail',
    },
    'cfg-ridesafe_front_rgb-ridesafe_rear_rgb': {
        'req-day-baseline': 'pass', 'req-night-baseline': 'pass',
        'req-day-strict': 'pass', 'req-night-strict': 'pass',
    },
}

# pass_count / 4, over BOTH sessions - restated here as an independent
# cross-check target.
EXPECTED_COVERAGE = {
    'cfg-ridesafe_front_rgb': 0.25,
    'cfg-ridesafe_rear_rgb': 0.25,
    'cfg-ridesafe_front_rgb-ridesafe_rear_rgb': 1.00,
}

# The only sufficient configuration under the standard demo policy
# (coverage>=1.0, completeness>=0.95, mandatory=False), evaluated with
# both sessions in scope - a single camera alone never reaches every bar.
EXPECTED_MINIMAL_SUFFICIENT = {'cfg-ridesafe_front_rgb-ridesafe_rear_rgb'}

# Non-dominated under (sensor_count, coverage, completeness) - completeness
# is 1.0 everywhere here (both sessions in scope, every requirement
# resolved), so only sensor_count/coverage differentiate. front_rgb and
# rear_rgb tie (same sensor count, same coverage - neither dominates the
# other); front+rear has more sensors but strictly higher coverage - a
# genuine trade-off, so all three survive.
EXPECTED_PARETO_FRONT = set(CONFIGS)

DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 0.95,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}

# SYNTHETIC RESOURCE DATA (day session only) - by construction, not
# measured. configuration_id -> metric -> value.
EXPECTED_RESOURCES = {
    'cfg-ridesafe_front_rgb': {
        'cpu_percent': 18.2, 'memory_mb': 580.0, 'network_receive_mbps': 4.5,
        'network_transmit_mbps': 1.1, 'pipeline_latency_ms': 32.0, 'fps': 29.5,
    },
    'cfg-ridesafe_rear_rgb': {
        'cpu_percent': 17.4, 'memory_mb': 575.0, 'network_receive_mbps': 4.3,
        'network_transmit_mbps': 1.0, 'pipeline_latency_ms': 33.0, 'fps': 29.8,
    },
    'cfg-ridesafe_front_rgb-ridesafe_rear_rgb': {
        'cpu_percent': 29.8, 'memory_mb': 825.0, 'network_receive_mbps': 8.6,
        'network_transmit_mbps': 2.0, 'pipeline_latency_ms': 39.0, 'fps': 29.4,
    },
}


def _load_data() -> dict:
    return json.loads(DATA_PATH.read_text())


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _independent_accuracy(dataset: dict) -> dict[tuple[str, str], float]:
    accuracy = {}
    for session_id in (DAY_SESSION_ID, NIGHT_SESSION_ID):
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
        for config, (total, correct) in totals.items():
            accuracy[(session_id, config)] = correct / total
    return accuracy


def _independent_status(accuracy: dict[tuple[str, str], float]) -> dict[str, dict[str, str]]:
    return {
        config: {
            req_id: ('pass' if accuracy[(illumination_session(illum), config)] >= threshold else 'fail')
            for req_id, (illum, threshold) in REQUIREMENTS.items()
        }
        for config in CONFIGS
    }


def illumination_session(illumination: str) -> str:
    return DAY_SESSION_ID if illumination == 'day' else NIGHT_SESSION_ID


def _independent_minimal_sufficient(coverage: dict[str, float]) -> set[str]:
    sufficient = {c for c in CONFIGS if coverage[c] >= DEMO_POLICY['minimum_requirement_coverage']}
    return {
        c for c in sufficient
        if not any(SENSOR_IDS[other] < SENSOR_IDS[c] for other in sufficient if other != c)
    }


def _independent_pareto_front(coverage: dict[str, float]) -> set[str]:
    def dominates(a: str, b: str) -> bool:
        a_sensors, b_sensors = len(SENSOR_IDS[a]), len(SENSOR_IDS[b])
        if a_sensors > b_sensors or coverage[a] < coverage[b]:
            return False
        return a_sensors < b_sensors or coverage[a] > coverage[b]

    dominated = {c for c in CONFIGS if any(dominates(other, c) for other in CONFIGS if other != c)}
    return set(CONFIGS) - dominated


def _independent_resource_means(dataset: dict) -> dict[str, dict[str, float]]:
    means: dict[str, dict[str, list[float]]] = {}
    for obs in dataset['resource_observations'][DAY_SESSION_ID]:
        by_metric = means.setdefault(obs['configuration_id'], {})
        by_metric.setdefault(obs['metric'], []).append(obs['value'])
    return {
        config: {metric: sum(values) / len(values) for metric, values in metrics.items()}
        for config, metrics in means.items()
    }


def test_dataset_file_has_expected_shape():
    dataset = _load_data()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['sessions']) == 2
    assert 'synthetic' in dataset['scenario']['tags']
    for session_id in (DAY_SESSION_ID, NIGHT_SESSION_ID):
        session = next(s for s in dataset['sessions'] if s['id'] == session_id)
        assert session['metadata']['synthetic'] is True
        assert len(dataset['ground_truth'][session_id]) == 100
        assert len(dataset['predictions'][session_id]) == 300  # 3 configs x 100
    assert len(dataset['resource_observations'][DAY_SESSION_ID]) == 18  # 3 configs x 6 metrics
    assert NIGHT_SESSION_ID not in dataset.get('resource_observations', {})


def test_profile_file_has_expected_shape():
    profile = _load_profile()
    assert profile['metadata']['synthetic'] is True
    assert len(profile['groups']) == 2
    assert len(profile['requirements']) == 4
    assert {r['id'] for r in profile['requirements']} == set(REQUIREMENTS)
    for requirement in profile['requirements']:
        expected_illum, _ = REQUIREMENTS[requirement['id']]
        assert requirement['conditions'] == {'illumination': expected_illum}


def test_no_professional_domain_or_safety_certification_language():
    # Explicit self-review requirement (issue #74): RideSafe is ride
    # monitoring and incident evidence, never a safety-certification,
    # driver-monitoring, or occupant-monitoring claim. A negated mention
    # ("not a safety-certification system") is the disclaimer itself,
    # not a violation - only an unnegated (positive) claim counts, same
    # "disclaimer is not an implementation" distinction this project's
    # own audits already apply elsewhere.
    negation_cues = ('not a ', 'not an ', 'never a ', 'never an ', 'nor ', 'no ')
    forbidden = ['driver monitoring', 'occupant monitoring', 'safety certification',
                 'safety-certification', 'certified', 'compliant', 'guarantees safety',
                 'prevents incidents', 'crime prevention']

    def assert_only_negated(text: str, label: str) -> None:
        lowered = text.lower()
        for term in forbidden:
            start = 0
            while (idx := lowered.find(term, start)) != -1:
                preceding = lowered[max(0, idx - 20):idx]
                assert any(cue in preceding for cue in negation_cues), (
                    f"found unnegated forbidden term '{term}' in {label}: ...{lowered[max(0, idx - 40):idx + 40]}..."
                )
                start = idx + len(term)

    assert_only_negated(PROFILE_PATH.read_text(), 'profile')
    assert_only_negated(DATA_PATH.read_text(), 'dataset')


def test_independent_accuracy_matches_construction_targets():
    accuracy = _independent_accuracy(_load_data())
    assert accuracy == EXPECTED_ACCURACY


def test_independent_status_matches_hand_derived_table():
    accuracy = _independent_accuracy(_load_data())
    assert _independent_status(accuracy) == EXPECTED_STATUS


def test_independent_minimal_sufficient_matches_hand_derived_set():
    assert _independent_minimal_sufficient(EXPECTED_COVERAGE) == EXPECTED_MINIMAL_SUFFICIENT


def test_independent_pareto_front_matches_hand_derived_set():
    assert _independent_pareto_front(EXPECTED_COVERAGE) == EXPECTED_PARETO_FRONT


def test_independent_resource_means_match_construction_targets():
    assert _independent_resource_means(_load_data()) == EXPECTED_RESOURCES


def _seed_full_demo(client) -> dict:
    dataset = _load_data()
    profile = _load_profile()

    resp = client.post('/api/scenarios', json=dataset['scenario'])
    assert resp.status_code == 201, resp.text

    for session_id in (DAY_SESSION_ID, NIGHT_SESSION_ID):
        session = next(s for s in dataset['sessions'] if s['id'] == session_id)
        resp = client.post('/api/sessions', json=session)
        assert resp.status_code == 201, resp.text
        resp = client.post(
            f'/api/sessions/{session_id}/ground-truth/batch', json={'items': dataset['ground_truth'][session_id]},
        )
        assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
        resp = client.post(
            f'/api/sessions/{session_id}/predictions/batch', json={'items': dataset['predictions'][session_id]},
        )
        assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
        if session_id in dataset.get('resource_observations', {}):
            resp = client.post(
                f'/api/sessions/{session_id}/resource-observations/batch',
                json={'items': dataset['resource_observations'][session_id]},
            )
            assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
        resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'scene_visibility'})
        assert resp.status_code == 200, resp.text

    resp = client.post('/api/profiles', json=profile)
    assert resp.status_code == 201, resp.text
    return profile


def test_api_decision_analysis_matches_independently_computed_values(client):
    profile = _seed_full_demo(client)

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
        assert api_config['summary']['evidence_completeness'] == pytest.approx(1.0)
        results_by_req = {r['requirement_id']: r['status'] for r in api_config['requirement_results']}
        assert results_by_req == expected_status

    assert set(body['minimal_sufficient_configuration_ids']) == EXPECTED_MINIMAL_SUFFICIENT
    assert set(body['pareto_front_configuration_ids']) == EXPECTED_PARETO_FRONT


def test_api_tradeoffs_joins_real_resource_evidence(client):
    profile = _seed_full_demo(client)

    resp = client.post(f"/api/profiles/{profile['id']}/tradeoffs", json={
        'policy': DEMO_POLICY, 'session_id': DAY_SESSION_ID,
        'resource_metrics': ['cpu_percent', 'memory_mb', 'network_receive_mbps',
                              'network_transmit_mbps', 'pipeline_latency_ms', 'fps'],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    configs_by_id = {c['configuration_id']: c for c in body['configurations']}

    for config_id, expected_metrics in EXPECTED_RESOURCES.items():
        profile_metrics = configs_by_id[config_id]['resource_profile']['metrics']
        for metric, expected_value in expected_metrics.items():
            assert profile_metrics[metric]['mean'] == pytest.approx(expected_value)
            assert profile_metrics[metric]['quality'] == 'measured'
        assert configs_by_id[config_id]['resource_validity'] == 'complete'

    # Day-only scope only ever sees the 2 day-conditioned requirements -
    # completeness is genuinely 0.5, not a bug (see the demo's own
    # README section on this exact, honest behavior).
    front = configs_by_id['cfg-ridesafe_front_rgb']
    assert front['requirement_coverage'] == pytest.approx(0.5)  # 1 pass / (1 pass + 1 fail) among day-only reqs
