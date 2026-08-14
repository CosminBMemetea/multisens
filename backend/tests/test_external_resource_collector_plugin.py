"""Phase 99 (v0.9): `SUPPORTED_RESOURCE_METRICS` becomes externally
extensible. The acceptance bar (issue #100): a test-only external
resource plugin (`synthetic_metric`) - discovered through the exact same
`multisens.plugins` entry-point mechanism a real installed package would
use - proves unit/provenance/zero-value/unavailable-value/persistence/
trade-off integration, with zero core edits beyond this phase's own
union-at-registration wiring.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from app.domain.resources import SUPPORTED_RESOURCE_METRICS, DuplicateResourceMetricError, register_resource_metrics
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    ResourceMetricDescriptor,
    ResourceObservation,
)


@pytest.fixture
def clean_supported_resource_metrics():
    """SUPPORTED_RESOURCE_METRICS is genuine shared module-level state
    (the same dict api/profiles.py already imported) - exactly what
    makes runtime registration work without an app restart, and exactly
    why tests that mutate it must restore it afterward."""
    original = dict(SUPPORTED_RESOURCE_METRICS)
    yield SUPPORTED_RESOURCE_METRICS
    SUPPORTED_RESOURCE_METRICS.clear()
    SUPPORTED_RESOURCE_METRICS.update(original)


class _SyntheticMetricPlugin:
    """A trivial, self-contained external ResourceCollector - one new
    metric (`synthetic_metric`, unit `widgets`), deliberately unrelated
    to any of the six built-in metrics."""
    def __init__(self):
        self._sample_index = 0

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.resource.synthetic-metric', name='Synthetic Metric Collector', version='0.1.0',
            plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            author='Acme', license='Apache-2.0',
        )

    def available_metrics(self) -> list[ResourceMetricDescriptor]:
        return [ResourceMetricDescriptor(metric='synthetic_metric', unit='widgets', description='A test metric.')]

    def configure(self, config: dict) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING)

    def sample(self) -> list[ResourceObservation]:
        now = datetime.now(timezone.utc)
        self._sample_index += 1
        return [ResourceObservation(
            id=f'synthetic-obs-{self._sample_index}', session_id='s1', configuration_id='cfg-rgb',
            metric='synthetic_metric', value=float(self._sample_index * 10), unit='widgets',
            quality='measured', source='synthetic_metric_plugin', platform_id='test-platform',
            started_at=now, ended_at=now,
        )]


def _entry_point_for(plugin) -> SimpleNamespace:
    return SimpleNamespace(
        name=plugin.descriptor().plugin_id, load=lambda: plugin,
        dist=SimpleNamespace(name='acme-synthetic-metric-plugin', version='0.1.0'),
    )


# --- registration/union ------------------------------------------------------

def test_new_metric_is_unsupported_before_any_plugin_declares_it(clean_supported_resource_metrics):
    assert 'synthetic_metric' not in SUPPORTED_RESOURCE_METRICS


def test_discovery_unions_the_new_metric_into_supported_resource_metrics(clean_supported_resource_metrics):
    plugin = _SyntheticMetricPlugin()
    registry = discover_plugins(entry_points=[_entry_point_for(plugin)])
    assert registry.get('acme.resource.synthetic-metric').status == PluginStatus.AVAILABLE
    assert SUPPORTED_RESOURCE_METRICS['synthetic_metric'] == 'widgets'
    # The six built-in metrics are still there too - union, never replace.
    assert 'cpu_percent' in SUPPORTED_RESOURCE_METRICS


def test_redeclaring_an_existing_metric_with_the_same_unit_is_fine(clean_supported_resource_metrics):
    register_resource_metrics([ResourceMetricDescriptor(metric='cpu_percent', unit='%')])
    assert SUPPORTED_RESOURCE_METRICS['cpu_percent'] == '%'


def test_redeclaring_an_existing_metric_with_a_different_unit_is_rejected(clean_supported_resource_metrics):
    with pytest.raises(DuplicateResourceMetricError, match='cpu_percent'):
        register_resource_metrics([ResourceMetricDescriptor(metric='cpu_percent', unit='ratio')])
    assert SUPPORTED_RESOURCE_METRICS['cpu_percent'] == '%'  # unchanged


def test_one_conflicting_metric_fails_the_whole_registration_atomically(clean_supported_resource_metrics):
    # 'new_metric_a' has no conflict, 'cpu_percent' does - neither should
    # be applied, never a half-registered plugin.
    with pytest.raises(DuplicateResourceMetricError):
        register_resource_metrics([
            ResourceMetricDescriptor(metric='new_metric_a', unit='x'),
            ResourceMetricDescriptor(metric='cpu_percent', unit='ratio'),
        ])
    assert 'new_metric_a' not in SUPPORTED_RESOURCE_METRICS


def test_conflicting_plugin_registers_as_load_failed_not_available(clean_supported_resource_metrics):
    class _ConflictingPlugin(_SyntheticMetricPlugin):
        def descriptor(self):
            d = super().descriptor()
            return PluginDescriptor(
                plugin_id='acme.resource.conflicting', name='Conflicting', version='0.1.0',
                plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            )
        def available_metrics(self):
            return [ResourceMetricDescriptor(metric='cpu_percent', unit='ratio')]

    plugin = _ConflictingPlugin()
    registry = discover_plugins(entry_points=[_entry_point_for(plugin)])
    record = registry.get('acme.resource.conflicting')
    assert record.status == PluginStatus.LOAD_FAILED
    assert 'cpu_percent' in record.error


# --- end-to-end: discovery -> ingestion -> trade-off integration -----------

DEMO_POLICY = {
    'minimum_requirement_coverage': 0.0, 'minimum_evidence_completeness': 0.0,
    'mandatory_requirements_must_pass': False, 'objective': 'minimize_sensor_count',
}


def _seed_profile_and_session(client) -> None:
    resp = client.post('/api/scenarios', json={'id': 'sc1', 'name': 'demo'})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions', json={'id': 's1', 'name': 'demo', 'scenario_id': 'sc1'})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/profiles', json={
        'id': 'p1', 'name': 'Synthetic Metric Test Profile', 'version': '1.0',
        'groups': [{'id': 'g1', 'name': 'Group 1'}],
        'requirements': [{'id': 'req-unrelated', 'group_id': 'g1', 'name': 'Unrelated', 'task': 'presence',
                           'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.7}]}],
    })
    assert resp.status_code == 201, resp.text


def test_tradeoffs_rejects_the_new_metric_before_any_plugin_declares_it(client, clean_supported_resource_metrics):
    _seed_profile_and_session(client)
    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['synthetic_metric'],
    })
    assert resp.status_code == 422, resp.text
    assert 'synthetic_metric' in str(resp.json()['detail'])


def test_full_pipeline_synthetic_metric_flows_through_ingestion_and_tradeoffs(client, clean_supported_resource_metrics):
    plugin = _SyntheticMetricPlugin()
    registry = discover_plugins(entry_points=[_entry_point_for(plugin)])
    assert registry.get('acme.resource.synthetic-metric').status == PluginStatus.AVAILABLE

    _seed_profile_and_session(client)

    # The plugin's own sample() output, exactly as a real collector loop
    # (Phase 99's own ResourceCollectorInstance.sample()) would forward
    # it - through the *existing*, completely unchanged v0.7 batch
    # ingestion endpoint.
    observations = [obs.model_dump(mode='json') for obs in plugin.sample()]
    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': observations})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {'accepted': 1, 'rejected': 0, 'errors': []}

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['synthetic_metric'],
        'configuration_ids': ['cfg-rgb'],
    })
    assert resp.status_code == 200, resp.text
    configs_by_id = {c['configuration_id']: c for c in resp.json()['configurations']}
    rgb = configs_by_id['cfg-rgb']
    assert rgb['resource_validity'] == 'complete'
    summary = rgb['resource_profile']['metrics']['synthetic_metric']
    assert summary['mean'] == pytest.approx(10.0)
    assert summary['quality'] == 'measured'


def test_zero_value_and_unavailable_quality_both_flow_through_honestly(client, clean_supported_resource_metrics):
    register_resource_metrics([ResourceMetricDescriptor(metric='synthetic_metric', unit='widgets')])
    _seed_profile_and_session(client)
    now = datetime.now(timezone.utc).isoformat()

    resp = client.post('/api/sessions/s1/resource-observations/batch', json={'items': [
        {'metric': 'synthetic_metric', 'value': 0.0, 'unit': 'widgets', 'quality': 'measured',
         'source': 'synthetic_metric_plugin', 'platform_id': 'test-platform', 'configuration_id': 'cfg-rgb',
         'started_at': now, 'ended_at': now},
        {'metric': 'synthetic_metric', 'value': None, 'unit': 'widgets', 'quality': 'unavailable',
         'source': 'synthetic_metric_plugin', 'platform_id': 'test-platform', 'configuration_id': 'cfg-depth',
         'started_at': now, 'ended_at': now},
    ]})
    assert resp.status_code == 201, resp.text
    assert resp.json()['rejected'] == 0

    resp = client.post('/api/profiles/p1/tradeoffs', json={
        'policy': DEMO_POLICY, 'session_id': 's1', 'resource_metrics': ['synthetic_metric'],
        'configuration_ids': ['cfg-rgb', 'cfg-depth'],
    })
    assert resp.status_code == 200, resp.text
    configs_by_id = {c['configuration_id']: c for c in resp.json()['configurations']}
    # A genuine zero is a real, complete measurement - never confused
    # with "no value."
    assert configs_by_id['cfg-rgb']['resource_profile']['metrics']['synthetic_metric']['mean'] == 0.0
    assert configs_by_id['cfg-rgb']['resource_validity'] == 'complete'
    # An explicit 'unavailable' row means genuinely no value - never a
    # fabricated number standing in for it.
    assert configs_by_id['cfg-depth']['resource_profile']['metrics'] == {}
    assert configs_by_id['cfg-depth']['resource_validity'] == 'unavailable'
