"""Phase 93 (v0.9): sanity coverage for the brand-new SDK-only types -
`PluginDescriptor`/`PluginType`/`MULTISENS_PLUGIN_API_VERSION`/
`ConnectorState`/`ConnectorHealth`/`SensorSample`/`MetricDescriptor`/
`ResourceMetricDescriptor` and the five Protocol contracts - none of
which existed anywhere before this phase. Runtime wiring (registry,
discovery, the actual call-site failure isolation) is Phase 94+; this
only proves the shapes themselves construct and behave as documented.
"""
from typing import Any

import pytest
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    EvaluatorOutput,
    GroundTruthConnector,
    MetricDescriptor,
    PluginDescriptor,
    PluginType,
    PredictionConnector,
    ResourceCollector,
    ResourceMetricDescriptor,
    SensorConnector,
    SensorSample,
)
from multisens_sdk.matching import MatchResult


def test_plugin_api_version_is_a_single_string_not_a_range():
    # Exact-match compatibility only in v0.9 - a range like ">=1,<2" would
    # imply forward/backward-compatibility promises this project isn't
    # ready to make yet (docs/plugin-sdk.md#versioning).
    assert MULTISENS_PLUGIN_API_VERSION == "1"
    assert isinstance(MULTISENS_PLUGIN_API_VERSION, str)


def test_plugin_type_has_exactly_the_five_documented_values():
    assert {t.value for t in PluginType} == {
        'sensor_connector', 'prediction_connector', 'ground_truth_connector',
        'evaluator', 'resource_collector',
    }


def test_plugin_descriptor_is_frozen_and_constructs():
    descriptor = PluginDescriptor(
        plugin_id='acme.sensor.mock', name='Mock Sensor', version='0.1.0',
        plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        capabilities={'data_type': 'scalar', 'streaming': False},
        author='Acme', license='Apache-2.0',
    )
    assert descriptor.plugin_id == 'acme.sensor.mock'
    with pytest.raises(Exception):
        descriptor.plugin_id = 'changed'  # frozen - identity must not be mutable after construction


def test_plugin_descriptor_capabilities_defaults_to_empty_not_none():
    descriptor = PluginDescriptor(
        plugin_id='acme.sensor.mock', name='Mock', version='0.1.0',
        plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
    )
    assert descriptor.capabilities == {}


def test_connector_state_has_exactly_the_five_documented_values():
    assert {s.value for s in ConnectorState} == {'stopped', 'starting', 'running', 'degraded', 'failed'}


def test_connector_health_no_sample_yet_is_none_not_zero():
    health = ConnectorHealth(state=ConnectorState.STARTING)
    assert health.last_sample_age_s is None
    assert health.state == ConnectorState.STARTING


def test_sensor_sample_data_type_is_an_open_string():
    # The SDK never enumerates data_type exhaustively - "imu" is just as
    # valid as any other string, core routes it generically.
    sample = SensorSample(sensor_id='robot_imu', timestamp_ms=123.0, sequence_id=1,
                           data_type='imu', payload={'accel': [0.0, 0.0, 9.8]})
    assert sample.data_type == 'imu'
    assert sample.metadata == {}


def test_metric_descriptor_higher_is_better_none_means_no_defined_direction():
    bias = MetricDescriptor(id='bias', higher_is_better=None, unit='m')
    assert bias.higher_is_better is None
    precision = MetricDescriptor(id='precision', higher_is_better=True)
    assert precision.higher_is_better is True


def test_resource_metric_descriptor_constructs():
    gpu = ResourceMetricDescriptor(metric='gpu_percent', unit='%', description='GPU utilization')
    assert gpu.metric == 'gpu_percent'
    assert gpu.unit == '%'


# --- structural (duck-typed) contract satisfaction - no registry involved yet

class _FakeSensorConnector:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(plugin_id='acme.sensor.mock', name='Mock', version='0.1.0',
                                 plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION)
    def configure(self, sensor_id: str, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: return ConnectorHealth(state=ConnectorState.RUNNING)
    def sample(self) -> SensorSample | None: return None


class _FakePredictionConnector:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(plugin_id='acme.prediction.mock', name='Mock', version='0.1.0',
                                 plugin_type=PluginType.PREDICTION_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION)
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: return ConnectorHealth(state=ConnectorState.RUNNING)
    def poll(self) -> list: return []


class _FakeGroundTruthConnector:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(plugin_id='acme.groundtruth.mock', name='Mock', version='0.1.0',
                                 plugin_type=PluginType.GROUND_TRUTH_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION)
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: return ConnectorHealth(state=ConnectorState.RUNNING)
    def poll(self) -> list: return []


class _FakeResourceCollector:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(plugin_id='acme.resource.mock', name='Mock', version='0.1.0',
                                 plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION)
    def available_metrics(self) -> list[ResourceMetricDescriptor]: return []
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def sample(self) -> list: return []
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: return ConnectorHealth(state=ConnectorState.RUNNING)


def test_fake_sensor_connector_satisfies_the_protocol_structurally():
    connector: SensorConnector = _FakeSensorConnector()
    connector.configure('robot_front_rgb', {})
    connector.start()
    assert connector.health().state == ConnectorState.RUNNING
    assert connector.sample() is None
    connector.stop()


def test_fake_prediction_connector_satisfies_the_protocol_structurally():
    connector: PredictionConnector = _FakePredictionConnector()
    connector.configure({})
    connector.start()
    assert connector.poll() == []
    connector.stop()


def test_fake_ground_truth_connector_satisfies_the_protocol_structurally():
    connector: GroundTruthConnector = _FakeGroundTruthConnector()
    connector.configure({})
    connector.start()
    assert connector.poll() == []
    connector.stop()


def test_fake_resource_collector_satisfies_the_protocol_structurally():
    collector: ResourceCollector = _FakeResourceCollector()
    assert collector.available_metrics() == []
    collector.configure({})
    collector.start()
    assert collector.sample() == []
    collector.stop()


def test_evaluator_output_still_works_identically_via_the_sdk():
    # Same construction shape the v0.8 Evaluator/EvaluatorOutput always
    # had - proves the relocation changed nothing observable.
    output = EvaluatorOutput(sample_count=10, matched_samples=8, unmatched_predictions=1,
                              unmatched_ground_truth=2, metrics={'accuracy': 0.8}, details=None)
    assert output.metrics['accuracy'] == 0.8
    assert output.details is None
    assert isinstance(MatchResult(matched=[], unmatched_ground_truth=[], unmatched_predictions=[]).matched, list)
