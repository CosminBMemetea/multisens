"""v1.0-RC (issue #122): `start_session`/`complete_session` actually
starting/stopping live inference connectors - mirrors
`test_session_resource_collection_wiring.py` exactly, for
`inference_connectors`/`PREDICTION_CONNECTOR` instead of
`resource_collectors`/`RESOURCE_COLLECTOR`.
`plugin_state.inference_connectors`/`inference_connector_runners` are
genuine process-wide module state, so every test here saves and
restores them.
"""
import time
from datetime import datetime, timezone

import pytest
from app.main import app
from app.plugins import state as plugin_state
from app.plugins.manager import build_inference_connector_instances
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from fastapi.testclient import TestClient
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    Prediction,
)


class _FakeInferenceBridge:
    def __init__(self):
        self.configured_with: dict | None = None
        self.started = False
        self.next_poll_result: list = []

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.inference.fake', name='Fake Inference Bridge', version='1.0.0',
            plugin_type=PluginType.PREDICTION_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )

    def configure(self, config: dict) -> None:
        self.configured_with = config

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self.started else ConnectorState.STOPPED)

    def poll(self) -> list:
        return self.next_poll_result


@pytest.fixture
def fake_inference_connector(monkeypatch, tmp_path):
    """Wires one fake PREDICTION_CONNECTOR plugin into plugin_state,
    exactly as main.py's lifespan would from a real
    `inference_connectors:` config entry - and restores plugin_state to
    its untouched defaults afterward, so this never leaks into an
    unrelated test."""
    plugin = _FakeInferenceBridge()
    registry = PluginRegistry()
    registry.records['acme.inference.fake'] = PluginRecord(
        plugin_id='acme.inference.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin, factory=lambda: plugin, distribution_name='acme',
    )
    connectors = build_inference_connector_instances(
        [{'id': 'vehicles-front', 'plugin': 'acme.inference.fake', 'poll_interval_s': 0.05}], registry,
    )

    original_registry = plugin_state.plugin_registry
    original_connectors = plugin_state.inference_connectors
    original_runners = dict(plugin_state.inference_connector_runners)
    plugin_state.plugin_registry = registry
    plugin_state.inference_connectors = connectors

    yield plugin

    for runners in plugin_state.inference_connector_runners.values():
        for _instance, runner in runners.values():
            runner.stop()
    plugin_state.plugin_registry = original_registry
    plugin_state.inference_connectors = original_connectors
    plugin_state.inference_connector_runners = original_runners


def _create_scenario(client, scenario_id='sc1') -> None:
    resp = client.post('/api/scenarios', json={'id': scenario_id, 'name': 'demo scenario'})
    assert resp.status_code == 201, resp.text


def _create_session(client, session_id='s1', scenario_id='sc1') -> None:
    resp = client.post('/api/sessions', json={'id': session_id, 'name': 'demo session', 'scenario_id': scenario_id})
    assert resp.status_code == 201, resp.text


def test_starting_a_session_starts_its_configured_inference_connectors(client, fake_inference_connector):
    _create_scenario(client)
    _create_session(client)

    resp = client.post('/api/sessions/s1/start')
    assert resp.status_code == 200

    assert 's1' in plugin_state.inference_connector_runners
    runners = plugin_state.inference_connector_runners['s1']
    assert set(runners) == {'vehicles-front'}
    instance, _runner = runners['vehicles-front']
    assert instance.state == ConnectorState.RUNNING
    assert fake_inference_connector.configured_with['session_id'] == 's1'


def test_completing_a_session_stops_its_inference_connectors(client, fake_inference_connector):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')

    resp = client.post('/api/sessions/s1/complete')
    assert resp.status_code == 200

    assert 's1' not in plugin_state.inference_connector_runners
    assert fake_inference_connector.started is False


def test_repeated_start_does_not_restart_an_already_running_connector(client, fake_inference_connector):
    # The idempotent no-op path (BUG-002/#109's own guard) must never
    # re-trigger start_inference_connectors - reconfiguring a RUNNING
    # instance would raise.
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    first_instance, _ = plugin_state.inference_connector_runners['s1']['vehicles-front']

    second = client.post('/api/sessions/s1/start')
    assert second.status_code == 200
    second_instance, _ = plugin_state.inference_connector_runners['s1']['vehicles-front']
    assert first_instance is second_instance  # never rebuilt


def test_repeated_complete_does_not_double_stop(client, fake_inference_connector):
    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    client.post('/api/sessions/s1/complete')

    resp = client.post('/api/sessions/s1/complete')
    assert resp.status_code == 200
    assert 's1' not in plugin_state.inference_connector_runners


def test_a_session_with_no_inference_connectors_configured_starts_cleanly(client):
    # No fake_inference_connector fixture here - plugin_state.inference_connectors
    # is genuinely empty, matching every environment with no
    # `inference_connectors:` config entry. Must not error.
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/start')
    assert resp.status_code == 200
    assert plugin_state.inference_connector_runners.get('s1', {}) == {}


def test_resource_collection_and_inference_are_independently_wired(client, fake_inference_connector):
    # The two session-bound wiring paths (#111, #122) must not interfere
    # with each other - starting a session with only an inference
    # connector configured must not touch resource_collection_runners at
    # all (empty, never a KeyError from an unwired dict).
    _create_scenario(client)
    _create_session(client)
    resp = client.post('/api/sessions/s1/start')
    assert resp.status_code == 200
    assert plugin_state.resource_collection_runners.get('s1', {}) == {}
    assert set(plugin_state.inference_connector_runners['s1']) == {'vehicles-front'}


def test_live_inference_actually_writes_rows_reachable_through_the_normal_read_api(
    monkeypatch, tmp_path, fake_inference_connector,
):
    """The real end-to-end proof: start a session through the real REST
    API, let the real background thread poll for a couple of cycles, and
    confirm the resulting rows are visible through the exact same
    GET /api/sessions/{id}/predictions endpoint a batch-posted row would
    be - live inference and batch ingestion converge on one read path,
    never a parallel one.

    Deliberately does NOT use the shared `client` fixture - same
    MULTISENS_DB_PATH env-var reasoning as
    test_session_resource_collection_wiring.py's own equivalent test."""
    monkeypatch.setenv('MULTISENS_DB_PATH', str(tmp_path / 'test.db'))
    client = TestClient(app)

    fake_inference_connector.next_poll_result = [Prediction(
        id='live-pred-1', session_id='s1', timestamp_ms=100.0, source_id='acme.inference.fake',
        sensor_ids=['demo_rgb'], task='vehicle_presence', value={'label': 'present'}, confidence=0.9,
    )]

    _create_scenario(client)
    _create_session(client)
    client.post('/api/sessions/s1/start')
    time.sleep(0.3)
    client.post('/api/sessions/s1/complete')

    resp = client.get('/api/sessions/s1/predictions')
    assert resp.status_code == 200
    ids = {p['id'] for p in resp.json()}
    assert 'live-pred-1' in ids
