"""Phase 28: comparison robustness. Closes the specific gaps in the
Phase 20-27 test suite: a task with no ground truth at all, the N/A-
metric/no-divide-by-zero path exercised through the real API (not just
the domain-level compute_metric_delta tests), explicit malformed-request
coverage, and a legacy single-configuration ("v0.2-only") session -
proving v0.3 added no schema/migration that a pre-v0.3 session would be
missing.

Zero prediction sources, missing candidate evaluation, and ambiguous-
source 422s already have dedicated tests in test_comparison_api.py; not
duplicated here.
"""
import pytest


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


# --- missing ground truth -> zero common samples -> N/A metrics, not a crash ----

def test_compare_task_with_no_ground_truth_is_invalid_not_a_crash(client):
    """No ground truth was ever ingested for this task - every prediction
    is unmatched, sample_count/matched_samples are 0 for both sides, every
    metric is None (not a fabricated 0.0), and coverage is N/A (0/0). The
    comparison must still come back 200 with validity=invalid, not 500."""
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 0.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 0.0, 'source_id': 'thermal_model', 'sensor_ids': ['thermal'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text
    for result in resp.json():
        assert result['sample_count'] == 0
        assert result['matched_samples'] == 0
        assert result['metrics']['accuracy'] is None

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-thermal'],
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]

    assert comparison['validity']['status'] == 'invalid'
    assert any('common sample' in r for r in comparison['validity']['reasons'])

    for side in (comparison['reported'], comparison['common_set']):
        assert side['baseline']['coverage'] is None
        assert side['candidate']['coverage'] is None
        assert side['coverage_delta_pp'] is None
        for delta in side['metric_deltas'].values():
            assert delta['baseline'] is None
            assert delta['candidate'] is None
            assert delta['absolute'] is None
            assert delta['relative'] is None  # never a ZeroDivisionError


# --- N/A baseline metric through the real API, isolated from zero-common-samples ---

def test_compare_na_baseline_metric_yields_na_relative_delta_not_divide_by_zero(client):
    """Baseline's only prediction falls outside the matching tolerance,
    so matched_samples=0 for baseline specifically (unlike the previous
    test, the candidate has a real, non-None accuracy) - a class of bug
    where a naive `relative = absolute / baseline` would raise
    TypeError/ZeroDivisionError on the None case instead of degrading to
    N/A. A zero-matched baseline necessarily makes the common-set
    intersection empty too (it's a subset of baseline's matched ids), so
    this also re-confirms validity=invalid follows automatically rather
    than needing a special case."""
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 1000.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    # Baseline's only prediction lands far outside the default 100ms
    # tolerance of both ground-truth points - matched_samples=0, so
    # accuracy/precision/recall/f1 are all None for the baseline side.
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 5000.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    # Candidate matches both points, gets a real (non-None) accuracy.
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'thermal_model', 'sensor_ids': ['thermal'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 1001.0, 'source_id': 'thermal_model', 'sensor_ids': ['thermal'],
         'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text
    results = {r['configuration_id']: r for r in resp.json()}
    assert results['cfg-rgb']['metrics']['accuracy'] is None
    assert results['cfg-thermal']['metrics']['accuracy'] == pytest.approx(1.0)

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': ['cfg-thermal'],
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]

    accuracy_delta = comparison['reported']['metric_deltas']['accuracy']
    assert accuracy_delta['baseline'] is None
    assert accuracy_delta['candidate'] == pytest.approx(1.0)
    assert accuracy_delta['absolute'] is None  # baseline is None, not 0 - can't subtract
    assert accuracy_delta['relative'] is None  # never a ZeroDivisionError
    assert comparison['validity']['status'] == 'invalid'


# --- malformed compare requests -----------------------------------------------

def test_compare_missing_task_field_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/compare', json={'baseline_configuration_id': 'cfg-rgb'})
    assert resp.status_code == 422


def test_compare_missing_baseline_configuration_id_field_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/compare', json={'task': 'presence'})
    assert resp.status_code == 422


def test_compare_empty_body_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/compare', json={})
    assert resp.status_code == 422


def test_compare_candidate_ids_wrong_type_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
        'candidate_configuration_ids': 'cfg-thermal',  # string, not list
    })
    assert resp.status_code == 422


def test_compare_body_is_a_list_not_an_object_422(client):
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/compare', json=['not', 'an', 'object'])
    assert resp.status_code == 422


# --- legacy (v0.2-only) session: no v0.3-specific data, must still work --------

def test_compare_against_legacy_single_configuration_session(client):
    """A session ingested exactly the way a pre-v0.3 client would: one
    configuration, no second source, no multi-sensor prediction, evaluated
    through the plain v0.2 /evaluate endpoint. v0.3 added no migration and
    no new required field, so /compare must handle it gracefully - there
    is nothing to compare against, so an empty list, not an error."""
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 101.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'absent'}},
    ]})
    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text

    resp = client.get('/api/sessions/s1/configurations', params={'task': 'presence'})
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'presence', 'baseline_configuration_id': 'cfg-rgb',
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()['comparisons'] == []
