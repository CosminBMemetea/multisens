"""Phase 17: the shipped synthetic demo dataset's numbers must not
silently drift. Independently recomputes expected accuracy straight from
the raw JSON (nearest-timestamp matching in plain Python - deliberately
NOT importing app.domain.matching/metrics) and cross-checks it against
what a real POST .../evaluate call returns through the actual HTTP API.
If these two disagree, either the shipped file changed or the API broke -
either way, this is the guard.
"""
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / 'examples' / 'evaluation' / 'classification-demo.json'

# By construction (see scripts/generate_demo_data.py), not measured.
# Deliberately forms a clean lattice - every configuration strictly
# outperforms every configuration whose sensor set it's a superset of
# (single < pair < all three) - so there is no "removing a sensor
# helped" case anywhere in the demo.
EXPECTED_ACCURACY = {
    'cfg-rgb': 0.90,
    'cfg-depth': 0.83,
    'cfg-thermal': 0.87,
    'cfg-depth-rgb': 0.93,
    'cfg-rgb-thermal': 0.95,
    'cfg-depth-thermal': 0.90,
    'cfg-depth-rgb-thermal': 0.97,
}


def _load_dataset() -> dict:
    return json.loads(DATA_PATH.read_text())


def _independent_accuracy(dataset: dict) -> dict[str, float]:
    gt_by_ts = {g['timestamp_ms']: g['value']['label'] for g in dataset['ground_truth']}
    gt_timestamps = sorted(gt_by_ts)
    totals: dict[str, list[int]] = {}
    for p in dataset['predictions']:
        config = 'cfg-' + '-'.join(sorted(p['sensor_ids']))
        nearest = min(gt_timestamps, key=lambda t: abs(t - p['timestamp_ms']))
        correct = gt_by_ts[nearest] == p['value']['label']
        counts = totals.setdefault(config, [0, 0])
        counts[0] += 1
        counts[1] += int(correct)
    return {config: correct / total for config, (total, correct) in totals.items()}


def test_dataset_file_has_expected_shape():
    dataset = _load_dataset()
    assert dataset['format_version'] == '1.0'
    assert len(dataset['ground_truth']) == 100
    assert len(dataset['predictions']) == 700
    assert 'synthetic' in dataset['scenario']['tags']
    assert dataset['scenario']['metadata'].get('synthetic') is True


def test_independent_accuracy_matches_construction_targets():
    # Sanity check on the independent-recomputation helper itself, before
    # trusting it to validate the API response below.
    assert _independent_accuracy(_load_dataset()) == EXPECTED_ACCURACY


def test_api_evaluate_matches_independently_computed_accuracy(client):
    dataset = _load_dataset()
    session_id = dataset['session']['id']

    resp = client.post('/api/scenarios', json=dataset['scenario'])
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions', json=dataset['session'])
    assert resp.status_code == 201, resp.text

    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': dataset['ground_truth']})
    assert resp.status_code == 201, resp.text
    assert resp.json()['rejected'] == 0, resp.json()

    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': dataset['predictions']})
    assert resp.status_code == 201, resp.text
    assert resp.json()['rejected'] == 0, resp.json()

    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text
    results = {r['configuration_id']: r for r in resp.json()}

    independent = _independent_accuracy(dataset)
    assert set(results) == set(independent)
    for config, expected_accuracy in independent.items():
        assert results[config]['metrics']['accuracy'] == expected_accuracy
        assert results[config]['sample_count'] == 100
        # The 1-5ms prediction offset is comfortably inside the default
        # 100ms tolerance, so every sample should match, none unmatched.
        assert results[config]['matched_samples'] == 100
        assert results[config]['unmatched_ground_truth'] == 0
        assert results[config]['unmatched_predictions'] == 0


# By construction (accuracy targets above), not measured. Full - removed:
# 97 - 93 = 4 (thermal), 97 - 95 = 2 (depth), 97 - 90 = 7 (rgb) points out
# of 100, i.e. exactly these percentage-point deltas.
EXPECTED_ABLATION_ACCURACY_DELTA_PP = {
    'thermal': -4.0,
    'depth': -2.0,
    'rgb': -7.0,
}


def test_compare_endpoint_ablation_deltas_match_construction_targets(client):
    """Same rigor as the accuracy check above, one layer up: the /compare
    endpoint's reported deltas for each single-sensor removal from the
    full configuration must match hand-computed values, and every one of
    these comparisons must classify as direct_removal and come back
    VALID - the whole point of constructing the demo as a clean lattice
    with full common-sample coverage."""
    dataset = _load_dataset()
    session_id = dataset['session']['id']

    client.post('/api/scenarios', json=dataset['scenario'])
    client.post('/api/sessions', json=dataset['session'])
    client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': dataset['ground_truth']})
    client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': dataset['predictions']})
    client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})

    resp = client.post(
        f'/api/sessions/{session_id}/compare',
        json={'task': 'presence', 'baseline_configuration_id': 'cfg-depth-rgb-thermal'},
    )
    assert resp.status_code == 200, resp.text
    comparisons = {c['removed_sensors'][0]: c for c in resp.json()['comparisons'] if c['relationship'] == 'direct_removal'}

    assert set(comparisons) == set(EXPECTED_ABLATION_ACCURACY_DELTA_PP)
    for removed_sensor, expected_delta_pp in EXPECTED_ABLATION_ACCURACY_DELTA_PP.items():
        c = comparisons[removed_sensor]
        accuracy_delta = c['reported']['metric_deltas']['accuracy']['absolute']
        assert round(accuracy_delta * 100, 8) == expected_delta_pp
        assert c['validity']['status'] == 'valid'
        assert c['common_set']['common_sample_count'] == 100
