"""v0.9.1 (issue #111): `start_session`/`complete_session` actually
starting/stopping live resource collection - the last mile after
`test_resource_collector_wiring.py` already proved
`start_resource_collection()`/`stop_resource_collection()` work in
isolation. `plugin_state.resource_collectors`/`resource_collection_runners`
are genuine process-wide module state (the same shared-state discipline
`test_external_resource_collector_plugin.py` already established for
`SUPPORTED_RESOURCE_METRICS`), so every test here saves and restores them.
"""
import time
from datetime import datetime, timezone

import pytest
from app.domain.resources import ResourceObservation
from app.main import app
from app.plugins import state as plugin_state
from app.plugins.manager import build_resource_collector_instances
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from fastapi.testclient import TestClient
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    ResourceMetricDescriptor,
)


class _FakeResourceCollector:
    def __init__(self):
        self.configured_with: dict | None = None
        self.started = False
        self.next_sample_result: list = []

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.resource.fake', name='Fake Resource Collector', version='1.0.0',
            plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )

    def available_metrics(self) -> list[ResourceMetricDescriptor]:
        return [ResourceMetricDescriptor(metric='fake_metric', unit='x')]

    def configure(self, config: dict) -> None:
        self.configured_with = config

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self.started else ConnectorState.STOPPED)

    def sample(self) -> list:
        return self.next_sample_result


@pytest.fixture
def fake_resource_collector(monkeypatch, tmp_path):
    """Wires one fake RESOURCE_COLLECTOR plugin into plugin_state, exactly
    as main.py's lifespan would from a real `resource_collectors:` config
    entry - and restores plugin_state to its untouched defaults
    afterward, so this never leaks into an unrelated test."""
    plugin = _FakeResourceCollector()
    registry = PluginRegistry()
    registry.records['acme.resource.fake'] = PluginRecord(
        plugin_id='acme.resource.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin, factory=lambda: plugin, distribution_name='acme',
    )
    collectors = build_resource_collector_instances(
        [{'id': 'sys-metrics', 'plugin': 'acme.resource.fake', 'poll_interval_s': 0.05}], registry,
    )

    original_registry = plugin_state.plugin_registry
    original_collectors = plugin_state.resource_collectors
    original_runners = dict(plugin_state.resource_collection_runners)
    plugin_state.plugin_registry = registry
    plugin_state.resource_collectors = collectors

    yield plugin

    for runners in plugin_state.resource_collection_runners.values():
        for _instance, runner in runners.values():
            runner.stop()
    plugin_state.plugin_registry = original_registry
    plugin_state.resource_collectors = original_collectors
    plugin_state.resource_collection_runners = original_runners


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def test_starting_a_session_starts_its_configured_resource_collectors(client, fake_resource_collector):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/start')
    assert resp.status_code == 200

    assert 's1' in plugin_state.resource_collection_runners
    runners = plugin_state.resource_collection_runners['s1']
    assert set(runners) == {'sys-metrics'}
    instance, _runner = runners['sys-metrics']
    assert instance.state == ConnectorState.RUNNING
    assert fake_resource_collector.configured_with['session_id'] == 's1'


def test_completing_a_session_stops_its_resource_collectors(client, fake_resource_collector):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')

    resp = client.post('/api/sessions/s1/complete')
    assert resp.status_code == 200

    assert 's1' not in plugin_state.resource_collection_runners
    assert fake_resource_collector.started is False


def test_repeated_start_does_not_restart_an_already_running_collector(client, fake_resource_collector):
    # The idempotent no-op path (BUG-002/#109's own guard) must never
    # re-trigger start_resource_collection - reconfiguring a RUNNING
    # instance would raise, and even if it didn't, it would fabricate a
    # fresh baseline mid-session.
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    first_instance, _ = plugin_state.resource_collection_runners['s1']['sys-metrics']

    second = client.post('/api/sessions/s1/start')
    assert second.status_code == 200
    second_instance, _ = plugin_state.resource_collection_runners['s1']['sys-metrics']
    assert first_instance is second_instance  # never rebuilt


def test_repeated_complete_does_not_double_stop(client, fake_resource_collector):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    client.post('/api/sessions/s1/complete')

    # Must not raise (e.g. from calling stop() a second time on an
    # already-STOPPED instance) and must stay absent.
    resp = client.post('/api/sessions/s1/complete')
    assert resp.status_code == 200
    assert 's1' not in plugin_state.resource_collection_runners


def test_a_session_with_no_resource_collectors_configured_starts_cleanly(client):
    # No fake_resource_collector fixture here - plugin_state.resource_collectors
    # is genuinely empty, matching every environment with no
    # `resource_collectors:` config entry. Must not error.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/start')
    assert resp.status_code == 200
    assert plugin_state.resource_collection_runners.get('s1', {}) == {}


def test_live_collection_actually_writes_rows_reachable_through_the_normal_read_api(
    monkeypatch, tmp_path, fake_resource_collector,
):
    """The real end-to-end proof: start a session through the real REST
    API, let the real background thread sample for a couple of cycles,
    and confirm the resulting rows are visible through the exact same
    GET /api/sessions/{id}/resource-observations endpoint a batch-posted
    row would be - live collection and batch ingestion converge on one
    read path, never a parallel one.

    Deliberately does NOT use the shared `client` fixture: that fixture
    overrides FastAPI's `get_db` dependency to point request handlers at
    a tmp database, but `start_resource_collection()` is called directly
    from the session-lifecycle handler (not through that dependency), so
    its `PollRunner`'s default connect would resolve `MULTISENS_DB_PATH`
    to a *different* database than the one this test reads back from -
    exactly the same env-var-driven default `build_poll_runners()`'s own
    main.py wiring already relies on in production. Setting the env var
    here makes both paths agree, matching the real deployed app."""
    monkeypatch.setenv('MULTISENS_DB_PATH', str(tmp_path / 'test.db'))
    client = TestClient(app)

    now = datetime.now(timezone.utc)
    fake_resource_collector.next_sample_result = [ResourceObservation(
        id='live-obs-1', session_id='s1', configuration_id=None, metric='fake_metric', value=42.0,
        unit='x', quality='measured', source='acme.resource.fake', platform_id='unknown',
        started_at=now, ended_at=now,
    )]

    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    time.sleep(0.3)
    client.post('/api/sessions/s1/complete')

    resp = client.get('/api/sessions/s1/resource-observations')
    assert resp.status_code == 200
    ids = {o['id'] for o in resp.json()}
    assert 'live-obs-1' in ids
