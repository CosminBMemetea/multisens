"""Phase 102 (v0.9): `build_connector_instances` - the config-driven
wiring from `config/sensors.yaml`'s optional `connector:` block to real
`ConnectorInstance` objects, first exercised at application startup this
phase (docs/connector-api.md documented the block's shape back in Phase
95; nothing built it until now).
"""
from typing import Any

from app.plugins.connector_instance import ConnectorInstance
from app.plugins.manager import build_connector_instances, stop_connector_instances
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    SensorSample,
)


class _FakeSensorConnector:
    """Mutable per-instance state, so two objects constructed from the
    same factory can be told apart in assertions - the exact property a
    shared singleton object would fail to have."""
    def __init__(self):
        self.configured_sensor_id: str | None = None
        self.started = False
        self.fail_stop = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.sensor.fake', name='Fake Sensor', version='1.0.0',
            plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )

    def configure(self, sensor_id: str, config: dict[str, Any]) -> None:
        if 'uri' not in config:
            raise ConnectorConfigError("'uri' is required")
        self.configured_sensor_id = sensor_id

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        if self.fail_stop:
            raise RuntimeError('deliberately broken stop()')
        self.started = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self.started else ConnectorState.STOPPED)

    def sample(self) -> SensorSample | None:
        return None


def _registry_with_fake_sensor_plugin() -> PluginRegistry:
    registry = PluginRegistry()
    instance = _FakeSensorConnector()
    registry.records['acme.sensor.fake'] = PluginRecord(
        plugin_id='acme.sensor.fake', status=PluginStatus.AVAILABLE,
        descriptor=instance.descriptor(), instance=instance,
        factory=lambda: _FakeSensorConnector(), distribution_name='acme',
    )
    registry.records['acme.evaluator.fake'] = PluginRecord(
        plugin_id='acme.evaluator.fake', status=PluginStatus.AVAILABLE,
        descriptor=PluginDescriptor(
            plugin_id='acme.evaluator.fake', name='Fake Evaluator', version='1.0.0',
            plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        ),
        instance=object(), factory=lambda: object(), distribution_name='acme',
    )
    return registry


def test_sensor_with_no_connector_block_is_never_wired():
    sensors = [{'id': 'rgb', 'modality': 'rgb'}]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert instances == {}


def test_connector_naming_an_unknown_plugin_id_is_skipped_not_a_crash():
    sensors = [{'id': 'rgb', 'connector': {'plugin': 'does.not.exist', 'config': {'uri': 'x'}}}]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert instances == {}


def test_connector_naming_a_wrong_typed_plugin_is_skipped_not_a_crash():
    sensors = [{'id': 'rgb', 'connector': {'plugin': 'acme.evaluator.fake', 'config': {}}}]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert instances == {}


def test_valid_connector_is_built_configured_and_started():
    sensors = [{'id': 'rgb', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://x'}}}]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert set(instances) == {'rgb'}
    instance = instances['rgb']
    assert isinstance(instance, ConnectorInstance)
    assert instance.state == ConnectorState.RUNNING


def test_failed_configure_leaves_a_stopped_but_still_reachable_instance():
    # Missing 'uri' - the fake connector's own configure() raises
    # ConnectorConfigError, which ConnectorInstance.configure() re-raises
    # without ever having reached RUNNING - the instance itself stays
    # STOPPED (never FAILED; that state is reserved for a start()/stop()
    # failure, see connector_instance.py), but must still be reachable
    # through GET /api/connectors/{sensor_id}, never silently dropped.
    sensors = [{'id': 'rgb', 'connector': {'plugin': 'acme.sensor.fake', 'config': {}}}]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert 'rgb' in instances
    assert instances['rgb'].state == ConnectorState.STOPPED


def test_two_sensor_ids_naming_the_same_plugin_get_independent_connector_objects():
    sensors = [
        {'id': 'front', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://front'}}},
        {'id': 'rear', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://rear'}}},
    ]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert set(instances) == {'front', 'rear'}
    assert instances['front']._connector is not instances['rear']._connector
    assert instances['front']._connector.configured_sensor_id == 'front'
    assert instances['rear']._connector.configured_sensor_id == 'rear'


# --- stop_connector_instances (v0.9, Phase 105 robustness review - the
# shutdown-time counterpart, extracted out of main.py's lifespan for a
# dedicated test) -------------------------------------------------------

def test_stop_connector_instances_stops_every_running_connector():
    sensors = [
        {'id': 'front', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://front'}}},
        {'id': 'rear', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://rear'}}},
    ]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    assert instances['front'].state == ConnectorState.RUNNING
    assert instances['rear'].state == ConnectorState.RUNNING

    stop_connector_instances(instances)

    assert instances['front'].state == ConnectorState.STOPPED
    assert instances['rear'].state == ConnectorState.STOPPED


def test_stop_connector_instances_one_failure_never_blocks_stopping_the_rest():
    sensors = [
        {'id': 'front', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://front'}}},
        {'id': 'rear', 'connector': {'plugin': 'acme.sensor.fake', 'config': {'uri': 'rtsp://rear'}}},
    ]
    instances = build_connector_instances(sensors, _registry_with_fake_sensor_plugin())
    instances['front']._connector.fail_stop = True

    stop_connector_instances(instances)  # must not raise

    assert instances['front'].state == ConnectorState.FAILED  # its own stop() failed, recorded honestly
    assert instances['rear'].state == ConnectorState.STOPPED  # never blocked by the sibling's failure


def test_stop_connector_instances_handles_an_empty_dict():
    stop_connector_instances({})  # must not raise
