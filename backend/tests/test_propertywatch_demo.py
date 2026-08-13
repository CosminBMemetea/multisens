"""Phase 74: the shipped PropertyWatch demo's numbers must not silently
drift. Independently recomputes expected accuracy (per task), per-
requirement PASS/FAIL/N/A, coverage, the minimum sufficient
configuration, the Pareto front, and the resource summaries straight
from the raw JSON (nearest-timestamp matching per task and plain-Python
set/mean logic - deliberately NOT importing
app.domain.decision/coverage/analysis/profiles/resources), and cross-
checks it against what the real API returns end to end. Same rigor and
structure as test_ridesafe_demo.py (Phase 73's identical guard).
"""
import json
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'propertywatch-demo-data.json'
PROFILE_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'profiles' / 'propertywatch-demo.json'

SESSION_ID = 'propertywatch-demo-session'

ENTRANCE_ONLY = 'cfg-property_entrance_rgb'
ENTRANCE_STORAGE = 'cfg-property_entrance_rgb-property_storage_rgb'
FULL = 'cfg-property_entrance_rgb-property_indoor_rgb-property_storage_rgb'
CONFIGS = [ENTRANCE_ONLY, ENTRANCE_STORAGE, FULL]

SENSOR_IDS = {
    ENTRANCE_ONLY: {'property_entrance_rgb'},
    ENTRANCE_STORAGE: {'property_entrance_rgb', 'property_storage_rgb'},
    FULL: {'property_entrance_rgb', 'property_storage_rgb', 'property_indoor_rgb'},
}

# By construction (see scripts/generate_propertywatch_demo_data.py), not
# measured. (configuration_id, task) -> accuracy - a config only has an
# entry for a task if it actually includes that area's camera.
EXPECTED_ACCURACY = {
    (ENTRANCE_ONLY, 'entrance_visibility'): 0.78,
    (ENTRANCE_STORAGE, 'entrance_visibility'): 0.85,
    (ENTRANCE_STORAGE, 'storage_visibility'): 0.72,
    (FULL, 'entrance_visibility'): 0.92,
    (FULL, 'storage_visibility'): 0.80,
    (FULL, 'indoor_visibility'): 0.88,
}

# requirement_id -> (task, threshold) - hand-derived from
# propertywatch-demo.json, independent of parsing its own `acceptance`
# structure at all.
REQUIREMENTS = {
    'req-entrance-baseline': ('entrance_visibility', 0.70),
    'req-storage-visible': ('storage_visibility', 0.70),
    'req-indoor-visible': ('indoor_visibility', 0.70),
    'req-entrance-strict': ('entrance_visibility', 0.90),
}

# Hand-verified - every one of the 3 configurations x 4 requirements =
# 12 cells. 'na' means the configuration never produced any evidence for
# that task at all (no relevant camera), never a fabricated fail.
EXPECTED_STATUS = {
    ENTRANCE_ONLY: {
        'req-entrance-baseline': 'pass', 'req-storage-visible': 'na',
        'req-indoor-visible': 'na', 'req-entrance-strict': 'fail',
    },
    ENTRANCE_STORAGE: {
        'req-entrance-baseline': 'pass', 'req-storage-visible': 'pass',
        'req-indoor-visible': 'na', 'req-entrance-strict': 'fail',
    },
    FULL: {
        'req-entrance-baseline': 'pass', 'req-storage-visible': 'pass',
        'req-indoor-visible': 'pass', 'req-entrance-strict': 'pass',
    },
}

# pass_count / (pass_count + fail_count) - restated here as an
# independent cross-check target. N/A requirements are excluded from
# the denominator (v0.4's own coverage formula), never counted as fail.
EXPECTED_COVERAGE = {
    ENTRANCE_ONLY: 0.5,           # 1 pass / (1 pass + 1 fail); 2 na excluded
    ENTRANCE_STORAGE: 2 / 3,      # 2 pass / (2 pass + 1 fail); 1 na excluded
    FULL: 1.0,                    # 4 pass / (4 pass + 0 fail)
}
EXPECTED_COMPLETENESS = {
    ENTRANCE_ONLY: 0.5,     # 2 decided / 4 total
    ENTRANCE_STORAGE: 0.75,  # 3 decided / 4 total
    FULL: 1.0,              # 4 decided / 4 total
}

# The only sufficient configuration under the standard demo policy
# (coverage>=1.0, completeness>=0.95, mandatory=False) - the two partial
# configurations are UNDETERMINED (completeness genuinely below the
# bar), never INSUFFICIENT, since a missing camera's evidence could
# always still arrive later, unlike a measured-and-failing result.
EXPECTED_MINIMAL_SUFFICIENT = {FULL}

# All three configurations are non-dominated - a genuine 3-point
# staircase (more sensors always costs more, but also always reaches
# strictly more coverage) - the flagship "is the third camera worth its
# resource load" story this demo exists to tell.
EXPECTED_PARETO_FRONT = set(CONFIGS)

DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 0.95,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}

# SYNTHETIC RESOURCE DATA - by construction, not measured.
EXPECTED_RESOURCES = {
    ENTRANCE_ONLY: {
        'cpu_percent': 15.0, 'memory_mb': 480.0, 'network_receive_mbps': 3.8,
        'network_transmit_mbps': 0.9, 'pipeline_latency_ms': 28.0, 'fps': 29.6,
    },
    ENTRANCE_STORAGE: {
        'cpu_percent': 26.5, 'memory_mb': 730.0, 'network_receive_mbps': 7.5,
        'network_transmit_mbps': 1.8, 'pipeline_latency_ms': 34.0, 'fps': 29.5,
    },
    FULL: {
        'cpu_percent': 38.0, 'memory_mb': 980.0, 'network_receive_mbps': 11.4,
        'network_transmit_mbps': 2.7, 'pipeline_latency_ms': 41.0, 'fps': 29.3,
    },
}


def _load_data() -> dict:
    return json.loads(DATA_PATH.read_text())


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _independent_accuracy(dataset: dict) -> dict[tuple[str, str], float]:
    gt_by_task_ts: dict[str, dict[float, str]] = {}
    for g in dataset['ground_truth'][SESSION_ID]:
        gt_by_task_ts.setdefault(g['task'], {})[g['timestamp_ms']] = g['value']['label']

    totals: dict[tuple[str, str], list[int]] = {}
    for p in dataset['predictions'][SESSION_ID]:
        config = 'cfg-' + '-'.join(sorted(p['sensor_ids']))
        task = p['task']
        gt_ts = sorted(gt_by_task_ts[task])
        nearest = min(gt_ts, key=lambda t: abs(t - p['timestamp_ms']))
        correct = gt_by_task_ts[task][nearest] == p['value']['label']
        counts = totals.setdefault((config, task), [0, 0])
        counts[0] += 1
        counts[1] += int(correct)
    return {key: correct / total for key, (total, correct) in totals.items()}


def _independent_status(accuracy: dict[tuple[str, str], float]) -> dict[str, dict[str, str]]:
    status = {}
    for config in CONFIGS:
        status[config] = {}
        for req_id, (task, threshold) in REQUIREMENTS.items():
            key = (config, task)
            if key not in accuracy:
                status[config][req_id] = 'na'
            else:
                status[config][req_id] = 'pass' if accuracy[key] >= threshold else 'fail'
    return status


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
    for obs in dataset['resource_observations'][SESSION_ID]:
        by_metric = means.setdefault(obs['configuration_id'], {})
        by_metric.setdefault(obs['metric'], []).append(obs['value'])
    return {
        config: {metric: sum(values) / len(values) for metric, values in metrics.items()}
        for config, metrics in means.items()
    }


def test_dataset_file_has_expected_shape():
    dataset = _load_data()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['sessions']) == 1
    assert 'synthetic' in dataset['scenario']['tags']
    session = dataset['sessions'][0]
    assert session['metadata']['synthetic'] is True
    assert len(dataset['ground_truth'][SESSION_ID]) == 300  # 3 tasks x 100
    assert len(dataset['predictions'][SESSION_ID]) == 600   # 1+2+3 task-configs x 100
    assert len(dataset['resource_observations'][SESSION_ID]) == 18  # 3 configs x 6 metrics


def test_profile_file_has_expected_shape():
    profile = _load_profile()
    assert profile['metadata']['synthetic'] is True
    assert len(profile['groups']) == 2
    assert len(profile['requirements']) == 4
    assert {r['id'] for r in profile['requirements']} == set(REQUIREMENTS)
    for requirement in profile['requirements']:
        expected_task, _ = REQUIREMENTS[requirement['id']]
        assert requirement['task'] == expected_task
        assert requirement.get('conditions', {}) == {}


def test_no_surveillance_identification_or_hardcoded_building_type():
    # A negated mention ("no face-recognition features") is the
    # disclaimer itself, not a violation - only an unnegated (positive)
    # claim counts, same distinction test_ridesafe_demo.py's identical
    # check already applies.
    negation_cues = ('not a ', 'not an ', 'never a ', 'never an ', 'nor ', 'no ')
    forbidden = ['face recognition', 'face-recognition', 'facial recognition',
                 'identification of individuals', 'license plate']

    def assert_only_negated(text: str, label: str) -> None:
        # A wide-ish window - natural-language negation-with-conjunction
        # ("no X or Y") can place the cue well before the actual term,
        # e.g. this project's own "no surveillance-identification or
        # face-recognition features" (39 chars from 'no' to the term).
        lowered = text.lower()
        for term in forbidden:
            start = 0
            while (idx := lowered.find(term, start)) != -1:
                preceding = lowered[max(0, idx - 45):idx]
                assert any(cue in preceding for cue in negation_cues), (
                    f"found unnegated forbidden term '{term}' in {label}"
                )
                start = idx + len(term)

    assert_only_negated(PROFILE_PATH.read_text(), 'profile')
    assert_only_negated(DATA_PATH.read_text(), 'dataset')

    # Never hardcoded to exactly one building type - the description
    # must offer the generic list, not pick just one.
    profile_text = PROFILE_PATH.read_text().lower()
    assert 'home' in profile_text and 'garage' in profile_text and 'warehouse' in profile_text


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
    session = dataset['sessions'][0]

    resp = client.post('/api/scenarios', json=dataset['scenario'])
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions', json=session)
    assert resp.status_code == 201, resp.text
    resp = client.post(
        f'/api/sessions/{SESSION_ID}/ground-truth/batch', json={'items': dataset['ground_truth'][SESSION_ID]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
    resp = client.post(
        f'/api/sessions/{SESSION_ID}/predictions/batch', json={'items': dataset['predictions'][SESSION_ID]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text
    resp = client.post(
        f'/api/sessions/{SESSION_ID}/resource-observations/batch',
        json={'items': dataset['resource_observations'][SESSION_ID]},
    )
    assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text

    for task in ('entrance_visibility', 'storage_visibility', 'indoor_visibility'):
        resp = client.post(f'/api/sessions/{SESSION_ID}/evaluate', json={'task': task})
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
        assert api_config['summary']['evidence_completeness'] == pytest.approx(EXPECTED_COMPLETENESS[config_id])
        results_by_req = {r['requirement_id']: r['status'] for r in api_config['requirement_results']}
        assert results_by_req == expected_status

    assert set(body['minimal_sufficient_configuration_ids']) == EXPECTED_MINIMAL_SUFFICIENT
    assert set(body['pareto_front_configuration_ids']) == EXPECTED_PARETO_FRONT

    # The two partial configurations are UNDETERMINED, never INSUFFICIENT
    # - a missing camera's evidence could still arrive later.
    assert configs_by_id[ENTRANCE_ONLY]['policy_status'] == 'undetermined'
    assert configs_by_id[ENTRANCE_STORAGE]['policy_status'] == 'undetermined'
    assert configs_by_id[FULL]['policy_status'] == 'sufficient'


def test_api_tradeoffs_joins_real_resource_evidence(client):
    profile = _seed_full_demo(client)

    resp = client.post(f"/api/profiles/{profile['id']}/tradeoffs", json={
        'policy': DEMO_POLICY, 'session_id': SESSION_ID,
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
