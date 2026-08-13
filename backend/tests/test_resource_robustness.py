"""Phase 76: resource/trade-off layer robustness. Same discipline as
Phase 40/51/62 (test_profile_robustness.py/test_analysis_robustness.py/
test_decision_robustness.py) applied to the v0.7 resource layer -
dedicated tests for the specific edge cases listed in issue #77, not a
re-run of what test_resources.py/test_resource_summaries.py/
test_resource_tradeoff.py/test_resource_pareto.py/
test_resource_observations_api.py/test_tradeoffs_api.py already exercise.
A few bullets (missing-metric partiality, N/A constraints, some malformed
shapes) already have domain-level or API-level coverage elsewhere - those
get fresh, distinct scenarios here rather than literal duplicates, per
the same "not duplicated" discipline test_decision_robustness.py
documents.
"""
GROUND_TRUTH_LABELS = ['present', 'absent', 'present', 'present', 'absent']


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _seed_ground_truth(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'timestamp_ms': i * 100.0, 'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(GROUND_TRUTH_LABELS)
    ]})
    assert resp.status_code == 201, resp.text


def _seed_predictions_with_accuracy(client, session_id, sensor_ids, correct_count) -> None:
    predicted = [
        label if i < correct_count else ('absent' if label == 'present' else 'present')
        for i, label in enumerate(GROUND_TRUTH_LABELS)
    ]
    resp = client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        {'timestamp_ms': i * 100.0 + 1.0, 'source_id': '-'.join(sensor_ids), 'sensor_ids': sensor_ids,
         'task': 'presence', 'value': {'label': label}}
        for i, label in enumerate(predicted)
    ]})
    assert resp.status_code == 201, resp.text


def _evaluate(client, session_id='s1') -> None:
    resp = client.post(f'/api/sessions/{session_id}/evaluate', json={'task': 'presence'})
    assert resp.status_code == 200, resp.text


def _create_profile(client) -> None:
    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'Robustness Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{'id': 'req-baseline', 'group_id': 'g1', 'name': 'Baseline', 'task': 'presence',
                           'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}]}],
    })
    assert resp.status_code == 201, resp.text


def _resource_item(**overrides) -> dict:
    return {
        'metric': 'cpu_percent', 'value': 20.0, 'unit': '%', 'quality': 'measured',
        'source': 'psutil.cpu_percent', 'platform_id': 'macbook-m2-dockerdesktop',
        'started_at': '2026-01-01T00:00:00Z', 'ended_at': '2026-01-01T00:00:10Z',
        **overrides,
    }


def _seed_scenario(client) -> None:
    # front_rgb alone: 3/5 = 0.6 -> insufficient. front_rgb+rear_rgb: 5/5 = 1.0 -> sufficient.
    _create_scenario(client)
    _create_session(client)
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb'], correct_count=3)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb', 'rear_rgb'], correct_count=5)
    _evaluate(client)
    _create_profile(client)


DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0, 'minimum_evidence_completeness': 1.0,
    'mandatory_requirements_must_pass': False, 'objective': 'minimize_sensor_count',
}


# --- bullet 1: missing metrics (partial validity via the real pipeline) ------

def test_requested_metric_never_ingested_is_partial_not_complete_or_unavailable(client):
    # Distinct from test_tradeoffs_api.py's "never measured" case (single
    # requested metric, fully unavailable) - here TWO metrics are
    # requested, only one was ever ingested, so validity must land on the
    # genuinely-in-between 'partial' state, not silently round to either end.
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent', value=20.0),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent', 'memory_mb'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['resource_validity'] == 'partial'
    assert set(front['resource_profile']['metrics']) == {'cpu_percent'}
    assert any('memory_mb' in w for w in front['resource_profile']['warnings'])


# --- bullet 2: a failed measurement (collector returns unavailable) ----------

def test_ingested_unavailable_row_behaves_like_no_evidence_never_a_crash_or_fake_value(client):
    # A collector that genuinely attempted a measurement and failed
    # ingests an explicit quality='unavailable' row (resource_collector.py's
    # own documented behavior) - distinct from a metric that was simply
    # never requested/ingested at all. The API must accept the row, and
    # the resulting profile must be honest: no value, no crash, and never
    # confused with a real 0.0 reading.
    _seed_scenario(client)
    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent',
                        value=None, quality='unavailable'),
    ]})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {'accepted': 1, 'rejected': 0, 'errors': []}

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['resource_validity'] == 'unavailable'
    assert front['resource_profile']['metrics'] == {}


# --- bullet 3: a partial time series ------------------------------------------

def test_resource_evidence_window_is_not_cross_checked_against_evaluation_evidence(client):
    # The resource layer has no concept of "the session's real duration" -
    # a measurement_window is honestly just the span of whatever rows
    # were actually ingested, even if that's a tiny sliver compared to
    # the (unrelated) evaluation evidence gathered for the same session.
    # This is a real, documented architectural property (resources.py's
    # own "Session, not a new ResourceMeasurementRun entity" section), not
    # a bug - this test pins that behavior down explicitly.
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent', value=20.0,
                        started_at='2026-01-01T00:00:00Z', ended_at='2026-01-01T00:00:01Z'),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['resource_validity'] == 'complete'
    window = front['resource_profile']['measurement_window']
    assert window[0] == '2026-01-01T00:00:00Z'
    assert window[1] == '2026-01-01T00:00:01Z'


# --- bullet 4: inconsistent platform metadata across observations ------------

def test_same_configuration_different_platform_ids_falls_back_to_unknown(client):
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', platform_id='macbook-m2-dockerdesktop', value=20.0),
        _resource_item(configuration_id='cfg-front_rgb', platform_id='jetson-orin-nano',
                        started_at='2026-01-01T00:00:10Z', ended_at='2026-01-01T00:00:20Z', value=25.0),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    # Both rows still contribute to the summary (this call never drops
    # evidence) - only the platform attribution itself degrades to
    # honest "unresolved", never guessing which of the two is right.
    assert front['resource_profile']['platform_id'] == 'unknown'
    assert front['resource_profile']['metrics']['cpu_percent']['sample_count'] == 2


# --- bullet 5: different hosts compared directly (comparability warning) -----

def test_resource_comparison_across_different_platforms_is_not_comparable(client):
    # Distinct from test_resource_tradeoff.py's pure-domain
    # test_different_platforms_are_not_comparable and from
    # test_tradeoffs_api.py's same-platform comparison test - this is the
    # real /tradeoffs pipeline with two genuinely different platform_ids.
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', platform_id='macbook-m2-dockerdesktop', value=20.0),
        _resource_item(configuration_id='cfg-front_rgb-rear_rgb', platform_id='jetson-orin-nano', value=30.0),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
        'resource_comparison': {
            'baseline_configuration_id': 'cfg-front_rgb', 'candidate_configuration_id': 'cfg-front_rgb-rear_rgb',
        },
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['resource_comparison']
    assert comparison['comparability']['comparable'] is False
    assert any('platform' in w for w in comparison['comparability']['warnings'])
    # The numbers themselves are still reported - comparable=False never
    # silently hides the deltas, only flags them as not directly trustworthy.
    cpu_delta = next(d for d in comparison['metric_deltas'] if d['metric'] == 'cpu_percent')
    assert cpu_delta['baseline'] == 20.0
    assert cpu_delta['candidate'] == 30.0


# --- bullet 6: invalid/mismatched units ---------------------------------------

def test_mixed_units_for_the_same_metric_is_a_clean_422_not_a_crash(client):
    # Real defect caught by this phase's own review: `unit` is a fully
    # open string at ingestion (by design - see resources.py's own
    # module docstring), so nothing stops two rows for the same metric/
    # configuration from carrying different units (e.g. a bad collector
    # config, or a hand-typed 'declared' row with a typo). Before this
    # phase's fix, that reached compute_resource_metric_summary's own
    # ValueError uncaught, surfacing as an unhandled 500. It must now be
    # a normal, clean 422.
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent', unit='%', value=20.0),
        _resource_item(configuration_id='cfg-front_rgb', metric='cpu_percent', unit='percent', value=25.0,
                        started_at='2026-01-01T00:00:10Z', ended_at='2026-01-01T00:00:20Z'),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 422
    assert 'mixed units' in resp.json()['detail']


# --- bullet 7: a genuine zero value (distinct from unavailable) --------------

def test_genuine_zero_value_flows_through_as_a_real_measurement_not_unavailable(client):
    # Distinct from test_resources.py's pydantic-level
    # test_resource_observation_value_none_is_distinct_from_zero - this
    # proves 0.0 survives all the way through summary + profile + API
    # response as a real, complete measurement (e.g. an idle host
    # legitimately reading 0% network transmit).
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', metric='network_transmit_mbps', unit='Mbps',
                        value=0.0, quality='measured'),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['network_transmit_mbps'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['resource_validity'] == 'complete'
    summary = front['resource_profile']['metrics']['network_transmit_mbps']
    assert summary['mean'] == 0.0
    assert summary['quality'] == 'measured'


# --- bullet 8: a configuration with resource evidence but no coverage result -

def test_resource_only_configuration_explicitly_requested_keeps_its_resource_evidence(client):
    # Real defect caught by this phase's own review: a configuration_id
    # that only ever appears in resource observations (never in any
    # prediction, so it has no sensor-identity mapping and therefore no
    # decision evidence at all) used to be reported as pure NO EVIDENCE
    # when explicitly requested - resource_profile silently None even
    # though real resource rows existed for it in the same session. The
    # two evidence types are independent; missing one must never hide the
    # other (see app/domain/resources.py's own ConfigurationTradeoff
    # docstring).
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-resource_only', value=45.0),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
        'configuration_ids': ['cfg-front_rgb', 'cfg-resource_only'],
    })
    assert resp.status_code == 200, resp.text
    phantom = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-resource_only')
    assert phantom['policy_status'] is None  # still genuinely NO EVIDENCE on the decision side
    assert phantom['sensor_count'] == 0
    assert phantom['resource_validity'] == 'complete'
    assert phantom['resource_profile']['metrics']['cpu_percent']['mean'] == 45.0


# --- bullet 9: a configuration with a coverage result but no resource evidence

def test_sufficient_decision_survives_totally_absent_resource_evidence(client):
    # Distinct from test_tradeoffs_api.py's "one requested metric never
    # measured" case - here the configuration has zero resource
    # observations of any kind in the entire session, paired with a real,
    # policy-sufficient decision. Decision evidence and resource evidence
    # are genuinely independent axes - a strong result on one must never
    # be blocked or hidden by a total absence on the other.
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent', 'memory_mb'],
    })
    assert resp.status_code == 200, resp.text
    both = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb-rear_rgb')
    assert both['policy_status'] == 'sufficient'
    assert both['resource_validity'] == 'unavailable'
    assert both['resource_profile'] is not None  # explicit, never silently omitted
    assert both['resource_profile']['metrics'] == {}


# --- bullet 10: a synthetic/physical mixture within one session --------------

def test_synthetic_and_physical_observations_blend_honestly_metadata_is_inert(client):
    # metadata is free-form and never inspected by the engine (same
    # posture as every other metadata dict in this project) - a
    # synthetic-flagged row and an unflagged "physical" row for the same
    # metric/configuration must aggregate together exactly like any other
    # two rows, never silently partitioned or one excluded.
    _seed_scenario(client)
    client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        _resource_item(configuration_id='cfg-front_rgb', value=10.0, metadata={'synthetic': True}),
        _resource_item(configuration_id='cfg-front_rgb', value=30.0,
                        started_at='2026-01-01T00:00:10Z', ended_at='2026-01-01T00:00:20Z'),
    ]})
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent'],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    summary = front['resource_profile']['metrics']['cpu_percent']
    assert summary['sample_count'] == 2
    assert summary['mean'] == 20.0  # (10.0 + 30.0) / 2, both rows counted


# --- bullet 11: resource constraints with all-N/A metrics --------------------

def test_all_constraints_na_is_undetermined_never_qualifies_or_fails(client):
    # Distinct from test_tradeoffs_api.py's test_tradeoffs_constraint_na_
    # never_qualifies (one constraint na alongside one measured, unrelated
    # metric) - here every requested metric and every constraint is N/A,
    # zero resource evidence exists at all, so evaluate_resource_
    # qualification's "any N/A -> undetermined" path must not be
    # accidentally satisfied only because a fail happened to dominate.
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['cpu_percent', 'memory_mb'],
        'resource_constraints': [
            {'metric': 'cpu_percent', 'operator': '<=', 'value': 50.0},
            {'metric': 'memory_mb', 'operator': '<=', 'value': 1000.0},
        ],
    })
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert {r['status'] for r in front['constraint_results']} == {'na'}
    assert front['qualification'] == 'undetermined'


# --- bullet 12: /tradeoffs malformed-request shapes ---------------------------

def test_tradeoffs_missing_session_id_422(client):
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={'policy': DEMO_POLICY})
    assert resp.status_code == 422


def test_tradeoffs_resource_comparison_unknown_candidate_422(client):
    # Distinct from test_tradeoffs_api.py's unknown-baseline test - the
    # same 422 must fire for the other side of the pairing, not just
    # whichever one happens to be checked first.
    _seed_scenario(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1',
        'resource_comparison': {'baseline_configuration_id': 'cfg-front_rgb',
                                 'candidate_configuration_id': 'cfg-does-not-exist'},
    })
    assert resp.status_code == 422
