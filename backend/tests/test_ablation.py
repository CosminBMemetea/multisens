"""Phase 23: proves ablation (baseline = full configuration, candidates =
its direct-removal children) and the mirror sensor-addition case both fall
out of the existing Phase 21/22 engine and API with zero new code - no new
endpoint, no new domain function, just a richer configuration graph run
through /compare. The `client` fixture lives in conftest.py.

derive_configuration_id sorts sensor_ids alphabetically, so:
  ['rgb']                    -> cfg-rgb
  ['rgb', 'depth']           -> cfg-depth-rgb
  ['rgb', 'thermal']         -> cfg-rgb-thermal
  ['depth', 'thermal']       -> cfg-depth-thermal
  ['rgb', 'depth', 'thermal']-> cfg-depth-rgb-thermal
"""
import pytest

GT_LABELS = ['present', 'absent', 'present', 'absent', 'present', 'absent', 'present', 'absent', 'present', 'absent']


def _create_scenario(client) -> None:
    resp = client.post('/api/scenarios', json={'id': 'sc1', 'name': 'ablation demo'})
    assert resp.status_code == 201, resp.text


def _create_session(client) -> None:
    resp = client.post('/api/sessions', json={'id': 's1', 'name': 'ablation demo session', 'scenario_id': 'sc1'})
    assert resp.status_code == 201, resp.text


def _predictions(sensor_ids: list[str], source_id: str, wrong_indices: set[int]) -> list[dict]:
    items = []
    for i, label in enumerate(GT_LABELS):
        predicted = label
        if i in wrong_indices:
            predicted = 'absent' if label == 'present' else 'present'
        items.append({
            'timestamp_ms': i * 100 + 1.0, 'source_id': source_id, 'sensor_ids': sensor_ids,
            'task': 'presence', 'value': {'label': predicted},
        })
    return items


@pytest.fixture
def ablation_session(client):
    _create_scenario(client)
    _create_session(client)

    ground_truth = [
        {'timestamp_ms': float(i * 100), 'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(GT_LABELS)
    ]
    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': ground_truth})
    assert resp.status_code == 201 and resp.json()['rejected'] == 0

    configs = [
        (['rgb'], 'rgb_model', {2, 7}),                    # cfg-rgb, 8/10 correct
        (['rgb', 'depth'], 'rgb_depth_model', {2}),          # cfg-depth-rgb, 9/10
        (['rgb', 'thermal'], 'rgb_thermal_model', {7}),      # cfg-rgb-thermal, 9/10
        (['depth', 'thermal'], 'depth_thermal_model', {1, 4, 9}),  # cfg-depth-thermal, 7/10
        (['rgb', 'depth', 'thermal'], 'full_model', set()),  # cfg-depth-rgb-thermal, 10/10
    ]
    for sensor_ids, source_id, wrong in configs:
        resp = client.post('/api/sessions/s1/predictions/batch', json={
            'items': _predictions(sensor_ids, source_id, wrong),
        })
        assert resp.status_code == 201 and resp.json()['rejected'] == 0, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text
    return client


def test_ablation_from_full_configuration_classifies_direct_removals(ablation_session):
    client = ablation_session
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-depth-rgb-thermal',
        'min_common_sample_count': 5,  # only 10 GT samples in this dataset; default (20) is n/a here
    })
    assert resp.status_code == 200, resp.text
    comparisons = {c['candidate_configuration_id']: c for c in resp.json()['comparisons']}

    # Auto-discovery found all 4 other evaluated configurations in one call.
    assert set(comparisons) == {'cfg-rgb', 'cfg-depth-rgb', 'cfg-rgb-thermal', 'cfg-depth-thermal'}

    # Three direct removals - each differs from the full configuration by
    # exactly one sensor - correctly distinguished from the one general
    # (two-sensor) difference, all from a single /compare call.
    removals = {
        'cfg-depth-rgb': ('thermal', -0.1),
        'cfg-rgb-thermal': ('depth', -0.1),
        'cfg-depth-thermal': ('rgb', -0.3),
    }
    for candidate_id, (removed_sensor, expected_delta) in removals.items():
        c = comparisons[candidate_id]
        assert c['relationship'] == 'direct_removal', candidate_id
        assert c['removed_sensors'] == [removed_sensor], candidate_id
        assert c['added_sensors'] == [], candidate_id
        assert c['reported']['metric_deltas']['accuracy']['absolute'] == pytest.approx(expected_delta), candidate_id

    # Removing two sensors at once (thermal AND depth, landing on cfg-rgb)
    # is NOT a direct edge - must not be reported as a single-sensor
    # removal penalty.
    general = comparisons['cfg-rgb']
    assert general['relationship'] == 'general'
    assert set(general['removed_sensors']) == {'depth', 'thermal'}
    assert general['reported']['metric_deltas']['accuracy']['absolute'] == pytest.approx(-0.2)


def test_sensor_addition_from_minimal_baseline_classifies_direct_additions(ablation_session):
    client = ablation_session
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'min_common_sample_count': 5,
    })
    assert resp.status_code == 200, resp.text
    comparisons = {c['candidate_configuration_id']: c for c in resp.json()['comparisons']}
    assert set(comparisons) == {'cfg-depth-rgb', 'cfg-rgb-thermal', 'cfg-depth-thermal', 'cfg-depth-rgb-thermal'}

    additions = {
        'cfg-depth-rgb': ('depth', pytest.approx(0.9 - 0.8)),
        'cfg-rgb-thermal': ('thermal', pytest.approx(0.9 - 0.8)),
    }
    for candidate_id, (added_sensor, expected_delta) in additions.items():
        c = comparisons[candidate_id]
        assert c['relationship'] == 'direct_addition', candidate_id
        assert c['added_sensors'] == [added_sensor], candidate_id
        assert c['removed_sensors'] == [], candidate_id
        assert c['reported']['metric_deltas']['accuracy']['absolute'] == expected_delta, candidate_id

    # rgb -> depth+thermal is a full swap (removed rgb, added depth+thermal
    # simultaneously) - general, never mislabeled as an addition.
    swap = comparisons['cfg-depth-thermal']
    assert swap['relationship'] == 'general'
    assert swap['removed_sensors'] == ['rgb']
    assert set(swap['added_sensors']) == {'depth', 'thermal'}

    # rgb -> the full configuration adds two sensors at once - general too.
    full = comparisons['cfg-depth-rgb-thermal']
    assert full['relationship'] == 'general'
    assert set(full['added_sensors']) == {'depth', 'thermal'}


def test_ablation_uses_only_existing_compare_endpoint_no_new_route(ablation_session):
    # Documents the Phase 23 finding explicitly: there is no
    # /api/sessions/{id}/ablation route, by design - the ablation view is
    # a client-side filter (relationship == 'direct_removal') over the
    # same /compare response sensor-addition uses.
    client = ablation_session
    assert client.get('/api/sessions/s1/ablation').status_code == 404
