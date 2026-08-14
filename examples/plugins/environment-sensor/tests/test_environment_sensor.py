"""Demonstrates the full plugin flow (v0.9, Phase 101 acceptance bar):
discovery-shape metadata, configuration (valid and invalid), start, data
emission, health, stop, and failure - using only `multisens_sdk.testing`
contract helpers, the same tools any third-party plugin author would
reach for.
"""
import pytest
from multisens_environment_sensor.resource import SyntheticMetricCollector
from multisens_environment_sensor.sensor import EnvironmentSensorConnector
from multisens_sdk import ConnectorConfigError, ConnectorState
from multisens_sdk.testing import (
    assert_connector_lifecycle,
    assert_health_contract,
    assert_resource_observation_shape,
    assert_valid_plugin_descriptor,
)

# --- EnvironmentSensorConnector ---------------------------------------------

def test_sensor_descriptor_is_valid():
    assert_valid_plugin_descriptor(EnvironmentSensorConnector().descriptor())


def test_sensor_configuration_valid():
    connector = EnvironmentSensorConnector()
    connector.configure('demo_env_sensor', {'cycle_length': 10})  # must not raise


def test_sensor_configuration_invalid():
    connector = EnvironmentSensorConnector()
    with pytest.raises(ConnectorConfigError, match='cycle_length'):
        connector.configure('demo_env_sensor', {'cycle_length': -1})
    with pytest.raises(ConnectorConfigError, match='cycle_length'):
        connector.configure('demo_env_sensor', {'cycle_length': 'not a number'})


def test_sensor_full_lifecycle_via_contract_helper():
    connector = EnvironmentSensorConnector()
    assert_connector_lifecycle(connector, configure=lambda: connector.configure('demo_env_sensor', {}))


def test_sensor_start_then_data_emission_then_health_then_stop():
    connector = EnvironmentSensorConnector()
    connector.configure('demo_env_sensor', {'cycle_length': 4})
    connector.start()

    sample = connector.sample()
    assert sample is not None
    assert sample.sensor_id == 'demo_env_sensor'
    assert sample.data_type == 'scalar'
    assert set(sample.payload) == {'temperature_c', 'humidity_percent'}
    assert sample.metadata['synthetic'] is True
    assert sample.metadata['label'] == 'SYNTHETIC SAMPLE SOURCE'

    health = connector.health()
    assert_health_contract(health)
    assert health.state == ConnectorState.RUNNING

    connector.stop()
    assert connector.health().state == ConnectorState.STOPPED
    assert connector.sample() is None  # no data once stopped


def test_sensor_samples_are_deterministic_across_a_full_cycle():
    a = EnvironmentSensorConnector()
    a.configure('demo_env_sensor', {'cycle_length': 4})
    a.start()
    samples_a = [a.sample().payload for _ in range(4)]

    b = EnvironmentSensorConnector()
    b.configure('demo_env_sensor', {'cycle_length': 4})
    b.start()
    samples_b = [b.sample().payload for _ in range(4)]

    assert samples_a == samples_b  # identical config -> identical deterministic sequence


def test_sensor_sample_before_start_is_none():
    connector = EnvironmentSensorConnector()
    connector.configure('demo_env_sensor', {})
    assert connector.sample() is None  # never started


# --- SyntheticMetricCollector ------------------------------------------------

def test_resource_descriptor_is_valid():
    assert_valid_plugin_descriptor(SyntheticMetricCollector().descriptor())


def test_resource_configuration_invalid_without_session_id():
    collector = SyntheticMetricCollector()
    with pytest.raises(ConnectorConfigError, match='session_id'):
        collector.configure({})


def test_resource_full_lifecycle_via_contract_helper():
    collector = SyntheticMetricCollector()
    assert_connector_lifecycle(collector, configure=lambda: collector.configure({'session_id': 'demo-session'}))


def test_resource_sample_shape_is_valid():
    collector = SyntheticMetricCollector()
    collector.configure({'session_id': 'demo-session'})
    collector.start()
    observations = collector.sample()
    assert len(observations) == 1
    assert_resource_observation_shape(observations[0])
    assert observations[0].metric == 'synthetic_metric'
    assert observations[0].metadata['label'] == 'SYNTHETIC SAMPLE SOURCE'


def test_resource_sample_before_start_is_empty():
    collector = SyntheticMetricCollector()
    collector.configure({'session_id': 'demo-session'})
    assert collector.sample() == []
