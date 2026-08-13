"""Phase 62: decision-layer robustness. Same discipline as Phase 40/51
(test_profile_robustness.py/test_analysis_robustness.py) applied to the
v0.6 decision layer - dedicated tests for the specific edge cases listed
in issue #63, not a re-run of what test_decision.py/test_decision_api.py
already exercise. A few bullets (multiple equally-minimal sets, fewer-
sensors-same-coverage dominance, removal-sweep NO EVIDENCE) already have
domain-level or API-level coverage elsewhere - those get fresh, distinct
scenarios here rather than literal duplicates, per the same "not
duplicated" discipline test_profile_robustness.py documents.
"""
import pytest

from app.domain.analysis import AggregateCoverage
from app.domain.decision import (
    ConfigurationDecision,
    find_dominated_configurations,
    find_minimal_sufficient_sets,
    find_pareto_front,
    find_sufficient_configurations,
)

# --- domain-level: configuration-set-wide properties (bullets 1, 2, 3, 4) ---


def _agg(pass_count, fail_count, na_count, coverage, completeness):
    return AggregateCoverage(pass_count, fail_count, na_count, coverage, completeness)


def _decision(configuration_id, sensor_ids, status, coverage=1.0, completeness=1.0):
    return ConfigurationDecision(
        configuration_id, frozenset(sensor_ids), _agg(1, 0, 0, coverage, completeness), [], status,
    )


def test_no_configuration_is_sufficient_returns_empty_lists_not_a_crash():
    # A configuration set where nothing ever clears the policy bar -
    # sufficient/minimal must both come back empty, not raise, and the
    # Pareto front (independent of policy_status) must still be computed.
    a = _decision('cfg-a', {'a'}, 'insufficient', coverage=0.2, completeness=1.0)
    b = _decision('cfg-b', {'a', 'b'}, 'undetermined', coverage=0.9, completeness=1.0)
    sufficient = find_sufficient_configurations([a, b])
    assert sufficient == []
    assert find_minimal_sufficient_sets(sufficient) == []
    # Fewer sensors but lower coverage (a) vs. more sensors but higher
    # coverage (b) - a genuine trade-off, neither dominates the other,
    # even though neither is policy-sufficient either.
    front = {d.configuration_id for d in find_pareto_front([a, b])}
    assert front == {'cfg-a', 'cfg-b'}


def test_every_configuration_sufficient_still_filters_dominated_and_supersets():
    # All three configurations already clear the policy bar - blanket
    # sufficiency must not exempt a superset (minimality) or a strictly
    # worse trade-off (dominance) from being filtered out.
    small = _decision('cfg-small', {'a'}, 'sufficient')
    superset = _decision('cfg-superset', {'a', 'b'}, 'sufficient')
    other = _decision('cfg-other', {'c'}, 'sufficient')
    all_decisions = [small, superset, other]

    assert {d.configuration_id for d in find_sufficient_configurations(all_decisions)} == {
        'cfg-small', 'cfg-superset', 'cfg-other',
    }
    assert {d.configuration_id for d in find_minimal_sufficient_sets(all_decisions)} == {'cfg-small', 'cfg-other'}
    assert {d.configuration_id for d in find_dominated_configurations(all_decisions)} == {'cfg-superset'}


def test_three_way_tie_of_disjoint_minimal_sufficient_sets_all_survive():
    # Distinct from test_decision.py's two-way tie - three genuinely
    # disjoint sensor sets, none a subset of another, all sufficient.
    a = _decision('cfg-a', {'front_rgb'}, 'sufficient')
    b = _decision('cfg-b', {'rear_rgb'}, 'sufficient')
    c = _decision('cfg-c', {'sim_thermal'}, 'sufficient')
    minimal = find_minimal_sufficient_sets([a, b, c])
    assert {d.configuration_id for d in minimal} == {'cfg-a', 'cfg-b', 'cfg-c'}


def test_identical_coverage_non_subset_sensor_sets_dominance_prefers_smaller():
    # Distinct from test_decision.py's subset-based case ({a} vs {a,b}) -
    # here the two sensor sets share nothing, so "prefer the smaller"
    # must come purely from sensor_count, not a subset relationship.
    smaller = _decision('cfg-smaller', {'a', 'b'}, 'sufficient', coverage=0.9, completeness=1.0)
    larger = _decision('cfg-larger', {'c', 'd', 'e'}, 'sufficient', coverage=0.9, completeness=1.0)
    dominated = {d.configuration_id for d in find_dominated_configurations([smaller, larger])}
    assert dominated == {'cfg-larger'}
    front = {d.configuration_id for d in find_pareto_front([smaller, larger])}
    assert front == {'cfg-smaller'}


# --- API-level: end-to-end pipeline robustness (bullets 5, 6, 7, 8, 9) -----

GROUND_TRUTH_LABELS = ['present', 'absent', 'present', 'present', 'absent']


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1', metadata=None) -> None:
    resp = client.post('/api/sessions', json={
        'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id,
        'metadata': metadata or {},
    })
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


DEMO_POLICY = {
    'minimum_requirement_coverage': 1.0,
    'minimum_evidence_completeness': 1.0,
    'mandatory_requirements_must_pass': False,
    'objective': 'minimize_sensor_count',
}


# --- bullet 5: missing direct-removal configuration is NO EVIDENCE ---------

def test_removal_sweep_reports_no_evidence_for_a_sensor_pair_never_evaluated(client):
    # Fresh 4-sensor scenario (distinct from test_decision_api.py's
    # 3-sensor one) - only the full set and one single-sensor removal
    # were ever run, so the other three removals must all come back
    # NO EVIDENCE, never an estimate.
    _create_scenario(client)
    _create_session(client)
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb', 'rear_rgb', 'sim_thermal', 'sim_depth'], 5)
    _seed_predictions_with_accuracy(client, 's1', ['rear_rgb', 'sim_thermal', 'sim_depth'], 4)  # front_rgb removed
    _evaluate(client)
    client.post('/api/profiles', json={
        'id': 'p1', 'name': 'P', 'version': '1.0', 'groups': [{'id': 'g1', 'name': 'G1'}],
        'requirements': [{'id': 'req', 'group_id': 'g1', 'name': 'Req', 'task': 'presence',
                           'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]}],
    })

    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY,
        'gap_analysis': {
            'baseline_configuration_id': 'cfg-front_rgb-rear_rgb-sim_depth-sim_thermal',
            'include_removal_sweep': True,
        },
    })
    assert resp.status_code == 200, resp.text
    sweep = {r['removed_sensor_id']: r for r in resp.json()['gap_analysis']['removal_sweep']}

    assert sweep['front_rgb']['configuration_id'] == 'cfg-rear_rgb-sim_depth-sim_thermal'
    assert sweep['front_rgb']['policy_status'] is not None

    for removed in ('rear_rgb', 'sim_depth', 'sim_thermal'):
        assert sweep[removed]['configuration_id'] is None
        assert sweep[removed]['policy_status'] is None


# --- bullet 6: N/A-heavy configuration is undetermined, not insufficient ---

def test_na_heavy_configuration_via_real_pipeline_is_undetermined(client):
    # One requirement's conditions match the seeded session (resolves to
    # pass); four more each name a condition value no session has, so
    # they resolve to N/A. The real na_count (4/5) drives completeness
    # far below the policy bar - this must surface as undetermined
    # through the actual evidence-discovery pipeline, not just the
    # hand-built AggregateCoverage case test_decision.py already covers.
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb'], 5)
    _evaluate(client)

    requirements = [{
        'id': 'req-resolvable', 'group_id': 'g1', 'name': 'Resolvable', 'task': 'presence',
        'conditions': {'illumination': 'night'},
        'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}],
    }]
    for i, unreachable in enumerate(['day', 'dawn', 'dusk', 'overcast']):
        requirements.append({
            'id': f'req-na-{i}', 'group_id': 'g1', 'name': f'Unreachable {i}', 'task': 'presence',
            'conditions': {'illumination': unreachable},
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}],
        })
    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'P', 'version': '1.0', 'groups': [{'id': 'g1', 'name': 'G1'}],
        'requirements': requirements,
    })
    assert resp.status_code == 201, resp.text

    policy = {
        'minimum_requirement_coverage': 0.5, 'minimum_evidence_completeness': 0.9,
        'mandatory_requirements_must_pass': False, 'objective': 'minimize_sensor_count',
    }
    resp = client.post('/api/profiles/p1/decision-analysis', json={'policy': policy})
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')

    assert front['summary']['pass_count'] == 1
    assert front['summary']['na_count'] == 4
    assert front['summary']['requirement_coverage'] == pytest.approx(1.0)  # 1 pass / (1 pass + 0 fail)
    assert front['summary']['evidence_completeness'] == pytest.approx(0.2)  # 1 decided / 5 total
    assert front['policy_status'] == 'undetermined'  # not insufficient, despite 4/5 requirements N/A


# --- bullet 7: mandatory failure forces insufficient despite coverage met --

def test_mandatory_requirement_failure_forces_insufficient_via_real_pipeline(client):
    _create_scenario(client)
    _create_session(client)
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb'], correct_count=4)  # 4/5 = 0.8
    _evaluate(client)

    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'P', 'version': '1.0', 'groups': [{'id': 'g1', 'name': 'G1'}],
        'requirements': [
            {'id': 'req-pass', 'group_id': 'g1', 'name': 'Passes', 'task': 'presence',
             'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]},
            {'id': 'req-fail', 'group_id': 'g1', 'name': 'Fails', 'task': 'presence',
             'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.99}]},
        ],
    })
    assert resp.status_code == 201, resp.text

    # Coverage 1/2 = 0.5 exactly meets the 0.5 bar, completeness is 1.0 -
    # only mandatory_requirements_must_pass can flip this to insufficient.
    policy = {
        'minimum_requirement_coverage': 0.5, 'minimum_evidence_completeness': 0.5,
        'mandatory_requirements_must_pass': True, 'objective': 'minimize_sensor_count',
    }
    resp = client.post('/api/profiles/p1/decision-analysis', json={'policy': policy})
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['summary']['requirement_coverage'] == pytest.approx(0.5)
    assert front['summary']['evidence_completeness'] == pytest.approx(1.0)
    assert front['policy_status'] == 'insufficient'


# --- bullet 8: legacy v0.4/v0.5-only profile, no silent policy default ----

def test_decision_analysis_works_against_legacy_conditioned_profile_and_422s_without_policy(client):
    # A profile shaped exactly like a pre-v0.6 (v0.4/v0.5) one - grouped
    # requirements keyed to conditions, no decision-specific concept
    # anywhere in its own document. decision-analysis must work against
    # it completely unchanged when a policy is supplied...
    _create_scenario(client)
    _create_session(client, metadata={'illumination': 'night'})
    _seed_ground_truth(client)
    _seed_predictions_with_accuracy(client, 's1', ['front_rgb'], correct_count=4)
    _evaluate(client)

    resp = client.post('/api/profiles', json={
        'id': 'legacy-p1', 'name': 'Legacy Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{
            'id': 'req-001', 'group_id': 'g1', 'name': 'Night baseline', 'task': 'presence',
            'conditions': {'illumination': 'night'},
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}],
        }],
    })
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/profiles/legacy-p1/decision-analysis', json={'policy': DEMO_POLICY})
    assert resp.status_code == 200, resp.text
    front = next(c for c in resp.json()['configurations'] if c['configuration_id'] == 'cfg-front_rgb')
    assert front['policy_status'] == 'sufficient'  # 0.8 >= 0.7, coverage/completeness both 1.0

    # ...and must never silently apply a default policy - omitting it
    # entirely is always a 422, regardless of how old or condition-heavy
    # the target profile is.
    resp = client.post('/api/profiles/legacy-p1/decision-analysis', json={})
    assert resp.status_code == 422


# --- bullet 9: /decision-analysis malformed request shapes -----------------

def test_gap_analysis_missing_baseline_configuration_id_422(client):
    client.post('/api/profiles', json={
        'id': 'p1', 'name': 'P', 'version': '1.0', 'groups': [{'id': 'g1', 'name': 'G1'}],
        'requirements': [{'id': 'req', 'group_id': 'g1', 'name': 'Req', 'task': 'presence',
                           'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]}],
    })
    resp = client.post('/api/profiles/p1/decision-analysis', json={
        'policy': DEMO_POLICY,
        'gap_analysis': {'include_removal_sweep': True},  # baseline_configuration_id omitted
    })
    assert resp.status_code == 422


def test_decision_analysis_invalid_policy_objective_literal_422(client):
    client.post('/api/profiles', json={
        'id': 'p1', 'name': 'P', 'version': '1.0', 'groups': [{'id': 'g1', 'name': 'G1'}],
        'requirements': [{'id': 'req', 'group_id': 'g1', 'name': 'Req', 'task': 'presence',
                           'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.5}]}],
    })
    bad_policy = {**DEMO_POLICY, 'objective': 'minimize_cost'}  # not implemented in v0.6
    resp = client.post('/api/profiles/p1/decision-analysis', json={'policy': bad_policy})
    assert resp.status_code == 422
