"""v0.9.1 (issue #120): GET /sessions/{id}/evidence - the Evidence
Playback API. Reuses test_evaluate_api.py's own `_seed` fixture data
(rgb source correct on all 3 samples, depth source wrong on the first)
so the multi-source relationship classification is exercised against
data whose per-source correctness is already independently verified by
test_evaluate_api.py's own assertions.
"""


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def _seed(client, session_id='s1'):
    _create_scenario(client)
    _create_session(client, session_id=session_id)

    client.post(f'/api/sessions/{session_id}/ground-truth/batch', json={'items': [
        {'id': 'gt-0', 'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'id': 'gt-100', 'timestamp_ms': 100.0, 'task': 'presence', 'value': {'label': 'absent'}},
        {'id': 'gt-200', 'timestamp_ms': 200.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post(f'/api/sessions/{session_id}/predictions/batch', json={'items': [
        # rgb: all three correct
        {'timestamp_ms': 1.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}, 'confidence': 0.9},
        {'timestamp_ms': 101.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 199.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        # depth: gets the first one wrong (predicts absent when GT says present)
        {'timestamp_ms': 2.0, 'source_id': 'depth_model', 'sensor_ids': ['depth'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 102.0, 'source_id': 'depth_model', 'sensor_ids': ['depth'],
         'task': 'presence', 'value': {'label': 'absent'}},
        {'timestamp_ms': 198.0, 'source_id': 'depth_model', 'sensor_ids': ['depth'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})


def test_evidence_requires_positive_label(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence'})
    assert resp.status_code == 422  # FastAPI validation - no default, never silently guessed


def test_evidence_404_unknown_session(client):
    resp = client.get('/api/sessions/nope/evidence', params={'task': 'presence', 'positive_label': 'present'})
    assert resp.status_code == 404


def test_evidence_negative_tolerance_422(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={
        'task': 'presence', 'positive_label': 'present', 'tolerance_ms': -1,
    })
    assert resp.status_code == 422


def test_evidence_discovers_all_configurations_by_default(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    assert resp.status_code == 200
    samples = resp.json()
    assert [s['gt_sample_id'] for s in samples] == ['gt-0', 'gt-100', 'gt-200']
    all_config_ids = {src['configuration_id'] for s in samples for src in s['sources']}
    assert all_config_ids == {'cfg-rgb', 'cfg-depth'}


def test_evidence_disagreement_on_the_sample_depth_got_wrong(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    samples = {s['gt_sample_id']: s for s in resp.json()}

    gt0 = samples['gt-0']
    assert gt0['relationship'] == 'DISAGREE'
    by_config = {src['configuration_id']: src for src in gt0['sources']}
    assert by_config['cfg-rgb']['outcome'] == 'TP'
    assert by_config['cfg-rgb']['value'] == {'label': 'present'}
    assert by_config['cfg-rgb']['confidence'] == 0.9
    assert by_config['cfg-depth']['outcome'] == 'FN'
    assert by_config['cfg-depth']['confidence'] is None  # never fabricated - was never ingested


def test_evidence_agreement_positive_and_negative(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    samples = {s['gt_sample_id']: s for s in resp.json()}

    assert samples['gt-100']['relationship'] == 'AGREE_NEGATIVE'  # both predicted 'absent', GT is 'absent'
    assert samples['gt-200']['relationship'] == 'AGREE_POSITIVE'  # both predicted 'present', GT is 'present'


def test_evidence_match_delta_and_timestamps_are_real_not_fabricated(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    gt0 = next(s for s in resp.json() if s['gt_sample_id'] == 'gt-0')
    rgb = next(src for src in gt0['sources'] if src['configuration_id'] == 'cfg-rgb')
    assert gt0['gt_timestamp_ms'] == 0.0
    assert rgb['prediction_timestamp_ms'] == 1.0
    assert rgb['match_delta_ms'] == 1.0


def test_evidence_configuration_ids_filter_narrows_the_joined_sources(client):
    _seed(client)
    resp = client.get('/api/sessions/s1/evidence', params={
        'task': 'presence', 'positive_label': 'present', 'configuration_ids': ['cfg-rgb'],
    })
    samples = resp.json()
    all_config_ids = {src['configuration_id'] for s in samples for src in s['sources']}
    assert all_config_ids == {'cfg-rgb'}
    assert all(s['relationship'] == 'ONLY_ONE_SOURCE_AVAILABLE' for s in samples)


def test_evidence_no_common_gt_sample_when_nothing_matches(client):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'id': 'gt-lonely', 'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 5000.0, 'source_id': 'rgb_model', 'sensor_ids': ['rgb'],
         'task': 'presence', 'value': {'label': 'present'}},  # far outside default tolerance
    ]})
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    samples = resp.json()
    assert len(samples) == 1
    assert samples[0]['relationship'] == 'NO_COMMON_GT_SAMPLE'
    assert samples[0]['sources'][0]['prediction_id'] is None


def test_evidence_never_fabricates_a_combined_source_that_was_never_ingested(client):
    _seed(client)  # only rgb_model/depth_model were ever ingested - no "combined" source
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    samples = resp.json()
    source_ids = {src['source_id'] for s in samples for src in s['sources']}
    assert source_ids == {'rgb_model', 'depth_model'}


def test_evidence_reflects_the_real_ridesafe_style_union_source_honestly(client):
    """Mirrors the actual real-recorded-experiment shape: front and rear
    are disjoint in time (no overlap), plus an explicit combined/union
    source that has its own real predictions spanning both windows.
    Front-window samples must show rear as absent (never invented), and
    the union source must agree with whichever camera was actually
    active at that moment - never a fabricated fusion value."""
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'id': 'gt-front', 'timestamp_ms': 0.0, 'task': 'presence', 'value': {'label': 'present'}},
        {'id': 'gt-rear', 'timestamp_ms': 100000.0, 'task': 'presence', 'value': {'label': 'present'}},
    ]})
    client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 0.0, 'source_id': 'detector', 'sensor_ids': ['ridesafe_front_rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100000.0, 'source_id': 'detector', 'sensor_ids': ['ridesafe_rear_rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 0.0, 'source_id': 'union_v1', 'sensor_ids': ['ridesafe_front_rgb', 'ridesafe_rear_rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
        {'timestamp_ms': 100000.0, 'source_id': 'union_v1', 'sensor_ids': ['ridesafe_front_rgb', 'ridesafe_rear_rgb'],
         'task': 'presence', 'value': {'label': 'present'}},
    ]})
    resp = client.get('/api/sessions/s1/evidence', params={'task': 'presence', 'positive_label': 'present'})
    samples = {s['gt_sample_id']: s for s in resp.json()}

    front_sample = samples['gt-front']
    # Unmatched sources report sensor_ids=[] - never guessed from the
    # configuration_id, since that information genuinely isn't known
    # without an actual matched Prediction to read it from.
    rear_column = next(
        src for src in front_sample['sources']
        if src['configuration_id'] == 'cfg-ridesafe_rear_rgb' and src['source_id'] == 'detector'
    )
    assert rear_column['prediction_id'] is None  # rear genuinely never predicted at this moment
    assert rear_column['sensor_ids'] == []
    union_column = next(src for src in front_sample['sources'] if src['source_id'] == 'union_v1')
    assert union_column['outcome'] == 'TP'
    assert front_sample['relationship'] == 'AGREE_POSITIVE'  # front's own detector and union_v1 agree here
