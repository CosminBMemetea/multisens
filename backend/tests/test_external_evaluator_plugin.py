"""Phase 98 (v0.9): `EVALUATOR_REGISTRY` becomes externally extensible.

The acceptance bar (issue #99): a test-only external evaluator plugin -
built for this test suite, never a shipped docs example, discovered
through the exact same `multisens.plugins` entry-point mechanism a real
installed package would use - proves discovery -> evaluation ->
`EvaluationResult` -> requirement acceptance -> comparison, with zero
core edits beyond Phase 98's own registry wiring (`register_evaluator`/
the `_discover_one` collision check). Phase 85's own mixed-task
integration test already proved every downstream layer is
evaluator-blind for the three *built-in* evaluators; this proves the
identical claim for a genuinely externally-discovered one.
"""
import inspect
from types import SimpleNamespace

import pytest
from app.domain import coverage as coverage_module
from app.domain.evaluators import EVALUATOR_REGISTRY, DuplicateEvaluatorTypeError, register_evaluator
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, EvaluatorOutput, MetricDescriptor, PluginDescriptor, PluginType


@pytest.fixture
def clean_evaluator_registry():
    """EVALUATOR_REGISTRY is genuine shared module-level state (the same
    dict object api/evaluation.py already imported) - exactly what makes
    runtime registration work without an app restart, and exactly why
    tests that mutate it must restore it afterward, the same discipline
    monkeypatch.setenv already applies to os.environ."""
    original = dict(EVALUATOR_REGISTRY)
    yield EVALUATOR_REGISTRY
    EVALUATOR_REGISTRY.clear()
    EVALUATOR_REGISTRY.update(original)


class _OkRatioEvaluator:
    """A trivial, self-contained external evaluator: the fraction of
    matched pairs whose prediction value has `{"ok": true}`. Deliberately
    unrelated to classification/detection/regression so there's no doubt
    this is genuinely new evaluation logic, not a built-in in disguise."""
    evaluator_type = 'test_ok_ratio'
    format_version = '1.0'

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.evaluator.ok-ratio', name='OK Ratio Evaluator', version='0.1.0',
            plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            author='Acme', license='Apache-2.0',
        )

    def metric_descriptors(self) -> list[MetricDescriptor]:
        return [MetricDescriptor(id='ok_ratio', higher_is_better=True)]

    def evaluate(self, match_result, parameters) -> EvaluatorOutput:
        matched = match_result.matched
        ok_ratio = None
        if matched:
            ok_count = sum(1 for m in matched if m.prediction.value.get('ok') is True)
            ok_ratio = ok_count / len(matched)
        return EvaluatorOutput(
            sample_count=len(matched) + len(match_result.unmatched_ground_truth),
            matched_samples=len(matched),
            unmatched_predictions=len(match_result.unmatched_predictions),
            unmatched_ground_truth=len(match_result.unmatched_ground_truth),
            metrics={'ok_ratio': ok_ratio},
        )


def _entry_point_for(plugin) -> SimpleNamespace:
    return SimpleNamespace(
        name=plugin.descriptor().plugin_id, load=lambda: plugin,
        dist=SimpleNamespace(name='acme-ok-ratio-plugin', version='0.1.0'),
    )


# --- metric_descriptors() is purely descriptive, never consulted -----------

def test_coverage_engine_never_references_metric_descriptors_grep_verified():
    source = inspect.getsource(coverage_module)
    assert 'MetricDescriptor' not in source
    assert 'metric_descriptors' not in source


# --- discovery registers the external evaluator -----------------------------

def test_discovery_registers_external_evaluator_into_evaluator_registry(clean_evaluator_registry):
    plugin = _OkRatioEvaluator()
    registry = discover_plugins(entry_points=[_entry_point_for(plugin)])
    record = registry.get('acme.evaluator.ok-ratio')
    assert record.status == PluginStatus.AVAILABLE
    assert EVALUATOR_REGISTRY['test_ok_ratio'] is plugin


# --- duplicate evaluator_type across two different plugin_ids --------------

def test_duplicate_evaluator_type_across_different_plugin_ids_rejects_only_the_second(clean_evaluator_registry):
    first = _OkRatioEvaluator()

    class _AlsoClaimsOkRatio(_OkRatioEvaluator):
        def descriptor(self) -> PluginDescriptor:
            return PluginDescriptor(
                plugin_id='acme.evaluator.ok-ratio-v2', name='OK Ratio Evaluator v2', version='0.2.0',
                plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            )

    second = _AlsoClaimsOkRatio()
    registry = discover_plugins(entry_points=[_entry_point_for(first), _entry_point_for(second)])

    # Distinct plugin_ids - no plugin_id collision at all - but both
    # declared evaluator_type == 'test_ok_ratio'. First-registered wins
    # and keeps working; the second gets a clear, dedicated rejection -
    # deliberately asymmetric from plugin_id collisions (which reject
    # BOTH sides, since a plugin_id collision is genuine identity
    # ambiguity - an evaluator_type collision between two clearly-distinct
    # plugins is not).
    assert registry.get('acme.evaluator.ok-ratio').status == PluginStatus.AVAILABLE
    second_record = registry.get('acme.evaluator.ok-ratio-v2')
    assert second_record.status == PluginStatus.LOAD_FAILED
    assert 'test_ok_ratio' in second_record.error
    assert EVALUATOR_REGISTRY['test_ok_ratio'] is first


def test_register_evaluator_directly_rejects_a_duplicate_type(clean_evaluator_registry):
    register_evaluator(_OkRatioEvaluator())
    with pytest.raises(DuplicateEvaluatorTypeError, match='test_ok_ratio'):
        register_evaluator(_OkRatioEvaluator())


def test_external_evaluator_can_never_silently_override_a_built_in(clean_evaluator_registry):
    class _FakeClassificationImpostor(_OkRatioEvaluator):
        evaluator_type = 'classification'  # collides with the real built-in
        def descriptor(self) -> PluginDescriptor:
            return PluginDescriptor(
                plugin_id='acme.evaluator.classification-impostor', name='Impostor', version='0.1.0',
                plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            )

    original_classification = EVALUATOR_REGISTRY['classification']
    with pytest.raises(DuplicateEvaluatorTypeError):
        register_evaluator(_FakeClassificationImpostor())
    assert EVALUATOR_REGISTRY['classification'] is original_classification


# --- end-to-end: discovery -> evaluate -> coverage -> compare ---------------

def _seed_and_evaluate(client) -> None:
    resp = client.post('/api/scenarios', json={'id': 'sc1', 'name': 'demo'})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions', json={'id': 's1', 'name': 'demo', 'scenario_id': 'sc1'})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/ground-truth/batch', json={'items': [
        {'timestamp_ms': i * 10.0, 'task': 'external_task', 'value': {'expected': True}}
        for i in range(4)
    ]})
    assert resp.status_code == 201, resp.text

    # cfg-a: 3/4 "ok" -> ok_ratio 0.75
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': i * 10.0 + 1.0, 'source_id': 'a', 'sensor_ids': ['rgb'], 'task': 'external_task',
         'value': {'ok': i < 3}}
        for i in range(4)
    ]})
    assert resp.status_code == 201, resp.text
    # cfg-b: 1/4 "ok" -> ok_ratio 0.25
    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': i * 10.0 + 1.0, 'source_id': 'b', 'sensor_ids': ['depth'], 'task': 'external_task',
         'value': {'ok': i < 1}}
        for i in range(4)
    ]})
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/sessions/s1/evaluate', json={'task': 'external_task', 'evaluator_type': 'test_ok_ratio'})
    assert resp.status_code == 200, resp.text


def test_external_evaluator_flows_through_evaluate_endpoint(client, clean_evaluator_registry):
    register_evaluator(_OkRatioEvaluator())
    _seed_and_evaluate(client)

    resp = client.get('/api/sessions/s1/evaluation')
    assert resp.status_code == 200, resp.text
    results = {r['configuration_id']: r for r in resp.json()}
    assert results['cfg-rgb']['evaluator_type'] == 'test_ok_ratio'
    assert results['cfg-rgb']['metrics']['ok_ratio'] == pytest.approx(0.75)
    assert results['cfg-depth']['metrics']['ok_ratio'] == pytest.approx(0.25)


def test_external_evaluator_metric_drives_requirement_coverage(client, clean_evaluator_registry):
    register_evaluator(_OkRatioEvaluator())
    _seed_and_evaluate(client)

    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'External Evaluator Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{'id': 'req-ok', 'group_id': 'g1', 'name': 'OK ratio', 'task': 'external_task',
                           'acceptance': [{'metric': 'ok_ratio', 'operator': '>=', 'value': 0.5}]}],
    })
    assert resp.status_code == 201, resp.text

    resp = client.post('/api/profiles/p1/coverage', json={'session_ids': ['s1']})
    assert resp.status_code == 200, resp.text
    coverages = {c['configuration_id']: c for c in resp.json()['configuration_coverages']}
    rgb_status = coverages['cfg-rgb']['requirement_results'][0]['status']
    depth_status = coverages['cfg-depth']['requirement_results'][0]['status']
    assert rgb_status == 'pass'    # 0.75 >= 0.5
    assert depth_status == 'fail'  # 0.25 < 0.5


def test_external_evaluator_metric_deltas_computed_generically_by_compare(client, clean_evaluator_registry):
    register_evaluator(_OkRatioEvaluator())
    _seed_and_evaluate(client)

    resp = client.post('/api/sessions/s1/compare', json={
        'task': 'external_task', 'baseline_configuration_id': 'cfg-depth',
        'candidate_configuration_ids': ['cfg-rgb'],
    })
    assert resp.status_code == 200, resp.text
    comparison = resp.json()['comparisons'][0]
    delta = comparison['reported']['metric_deltas']['ok_ratio']
    assert delta['baseline'] == pytest.approx(0.25)
    assert delta['candidate'] == pytest.approx(0.75)
    assert delta['absolute'] == pytest.approx(0.5)
