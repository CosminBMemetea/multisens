"""Phase 102 (v0.9, issue #103): the read-only `/api/plugins`/
`/api/connectors` routes. No route here ever mutates anything - that's
the whole point (see app/api/plugins.py's own module docstring) - so
these tests only ever set up `app.plugins.state` directly and assert on
GET responses.

The redaction tests are the acceptance-bar requirement from issue #103
itself ("a dedicated redaction test confirms no secret value is ever
echoed") - checked as a full-response substring search, not just a
single-field equality check, so a secret leaking through some other part
of the response shape would still be caught.
"""
from typing import Any

import pytest
from app.plugins import state as plugin_state
from app.plugins.connector_instance import ConnectorInstance
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    SensorSample,
)


class _FakeSensorConnector:
    def __init__(self, health_details: dict[str, Any] | None = None):
        self._health_details = health_details or {}

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.sensor.fake', name='Fake Sensor', version='1.0.0',
            plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'data_type': 'scalar', 'api_key': 'super-secret-capability-value'},
        )

    def configure(self, sensor_id: str, config: dict[str, Any]) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING, details=self._health_details)

    def sample(self) -> SensorSample | None:
        return None


@pytest.fixture
def plugin_api_state():
    """`app.plugins.state` is genuine shared module-level state (same
    save/restore discipline as EVALUATOR_REGISTRY's own test fixture in
    test_external_evaluator_plugin.py) - each test gets a clean slate and
    never leaks into the next."""
    original_registry, original_connectors = plugin_state.plugin_registry, plugin_state.connector_instances
    plugin_state.plugin_registry = PluginRegistry()
    plugin_state.connector_instances = {}
    yield
    plugin_state.plugin_registry, plugin_state.connector_instances = original_registry, original_connectors


def _register_fake_plugin(secret_in_capabilities: bool = True) -> None:
    capabilities = {'data_type': 'scalar'}
    if secret_in_capabilities:
        capabilities['api_key'] = 'super-secret-capability-value'
    descriptor = PluginDescriptor(
        plugin_id='acme.sensor.fake', name='Fake Sensor', version='1.0.0',
        plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        capabilities=capabilities, author='Acme', license='MIT', description='A fake sensor.',
    )
    plugin_state.plugin_registry.records['acme.sensor.fake'] = PluginRecord(
        plugin_id='acme.sensor.fake', status=PluginStatus.AVAILABLE,
        descriptor=descriptor, instance=object(), factory=lambda: object(), distribution_name='acme-pkg',
        distribution_version='1.0.0',
    )


def test_list_plugins_empty_registry_returns_empty_list(client, plugin_api_state):
    resp = client.get('/api/plugins')
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_plugins_returns_a_summary_per_record(client, plugin_api_state):
    _register_fake_plugin()
    plugin_state.plugin_registry.records['acme.sensor.broken'] = PluginRecord(
        plugin_id='acme.sensor.broken', status=PluginStatus.LOAD_FAILED,
        descriptor=None, instance=None, error='boom', distribution_name='acme-pkg',
    )
    resp = client.get('/api/plugins')
    assert resp.status_code == 200
    by_id = {p['plugin_id']: p for p in resp.json()}
    assert by_id['acme.sensor.fake']['status'] == 'available'
    assert by_id['acme.sensor.fake']['name'] == 'Fake Sensor'
    assert by_id['acme.sensor.broken']['status'] == 'load_failed'
    assert by_id['acme.sensor.broken']['error'] == 'boom'
    assert by_id['acme.sensor.broken']['name'] is None  # no descriptor - never fabricated


def test_get_plugin_404_for_unknown_id(client, plugin_api_state):
    resp = client.get('/api/plugins/does.not.exist')
    assert resp.status_code == 404


def test_get_plugin_returns_full_detail(client, plugin_api_state):
    _register_fake_plugin(secret_in_capabilities=False)
    resp = client.get('/api/plugins/acme.sensor.fake')
    assert resp.status_code == 200
    body = resp.json()
    assert body['plugin_type'] == 'sensor_connector'
    assert body['api_version'] == MULTISENS_PLUGIN_API_VERSION
    assert body['author'] == 'Acme'
    assert body['capabilities'] == {'data_type': 'scalar'}


def test_get_plugin_capabilities_endpoint(client, plugin_api_state):
    _register_fake_plugin(secret_in_capabilities=False)
    resp = client.get('/api/plugins/acme.sensor.fake/capabilities')
    assert resp.status_code == 200
    assert resp.json() == {'data_type': 'scalar'}


def test_get_plugin_capabilities_404_for_unknown(client, plugin_api_state):
    resp = client.get('/api/plugins/does.not.exist/capabilities')
    assert resp.status_code == 404


def test_list_connectors_empty(client, plugin_api_state):
    resp = client.get('/api/connectors')
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_connector_404_for_unknown_sensor(client, plugin_api_state):
    resp = client.get('/api/connectors/does-not-exist')
    assert resp.status_code == 404


def test_get_connector_returns_state_and_health(client, plugin_api_state, monkeypatch):
    instance = ConnectorInstance('rgb', 'acme.sensor.fake', _FakeSensorConnector())
    instance.configure({'uri': 'rtsp://example/rgb'})
    instance.start()
    plugin_state.connector_instances['rgb'] = instance
    monkeypatch.setattr('app.api.plugins.load_sensors', lambda: [
        {'id': 'rgb', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://example/rgb'}}},
    ])

    resp = client.get('/api/connectors/rgb')
    assert resp.status_code == 200
    body = resp.json()
    assert body['sensor_id'] == 'rgb'
    assert body['plugin_id'] == 'acme.sensor.fake'
    assert body['state'] == 'running'
    assert body['health']['state'] == 'running'
    assert body['config'] == {'uri': 'rtsp://example/rgb'}

    list_resp = client.get('/api/connectors')
    assert list_resp.status_code == 200
    assert [c['sensor_id'] for c in list_resp.json()] == ['rgb']


# --- redaction (issue #103's own explicit acceptance-bar requirement) -------

def test_plugin_capabilities_secret_is_redacted_everywhere_it_could_surface(client, plugin_api_state):
    _register_fake_plugin(secret_in_capabilities=True)

    detail = client.get('/api/plugins/acme.sensor.fake').json()
    caps = client.get('/api/plugins/acme.sensor.fake/capabilities').json()
    listing = client.get('/api/plugins').json()

    for payload in (detail, caps, listing):
        assert 'super-secret-capability-value' not in str(payload)
    assert detail['capabilities']['api_key'] == '***REDACTED***'
    assert caps['api_key'] == '***REDACTED***'


def test_connector_config_secret_is_redacted_regardless_of_literal_or_env_form(client, plugin_api_state, monkeypatch):
    instance = ConnectorInstance('rgb', 'acme.sensor.fake', _FakeSensorConnector())
    instance.configure({'uri': 'rtsp://example/rgb'})
    instance.start()
    plugin_state.connector_instances['rgb'] = instance
    monkeypatch.setattr('app.api.plugins.load_sensors', lambda: [{
        'id': 'rgb',
        'connector': {
            'plugin': 'acme.sensor.fake',
            'config': {'uri': 'rtsp://example/rgb', 'password': 'hunter2', 'token_env': 'CAMERA_TOKEN'},
        },
    }])

    detail = client.get('/api/connectors/rgb').json()
    listing = client.get('/api/connectors').json()

    for payload in (detail, listing):
        assert 'hunter2' not in str(payload)
    assert detail['config']['password'] == '***REDACTED***'
    assert detail['config']['token_env'] == '***REDACTED***'
    assert detail['config']['uri'] == 'rtsp://example/rgb'  # non-secret fields still visible


def test_connector_health_details_secret_is_redacted(client, plugin_api_state, monkeypatch):
    instance = ConnectorInstance(
        'rgb', 'acme.sensor.fake',
        _FakeSensorConnector(health_details={'firmware_secret_key': 'do-not-leak', 'fps': 30}),
    )
    instance.configure({'uri': 'rtsp://example/rgb'})
    instance.start()
    plugin_state.connector_instances['rgb'] = instance
    monkeypatch.setattr('app.api.plugins.load_sensors', lambda: [])

    detail = client.get('/api/connectors/rgb').json()
    assert 'do-not-leak' not in str(detail)
    assert detail['health']['details']['firmware_secret_key'] == '***REDACTED***'
    assert detail['health']['details']['fps'] == 30
