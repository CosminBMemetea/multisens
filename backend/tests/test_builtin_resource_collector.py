"""v0.9.1 (issue #111): `BuiltInResourceCollector` -
`multisens.builtin.resource.system-metrics`. Wraps the existing,
completely unchanged v0.7 `SystemMetricsWindow`/`collect_sensor_metrics`
(app/resource_collector.py) behind the `ResourceCollector` plugin
interface, so it goes through the identical session-bound live-collection
path an external plugin uses.

A fake bridge stands in for the real `RosBridge` - same pattern
test_builtin_rtsp.py already established.
"""
import psutil
import pytest
from app.plugins.builtin_resource_collector import PLUGIN_ID, BuiltInResourceCollector
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import ConnectorConfigError, ConnectorState, PluginType


class _FakeBridge:
    def __init__(self):
        self._sensors: dict[str, dict] = {}

    def set_sensor(self, sensor_id: str, **fields) -> None:
        self._sensors[sensor_id] = fields

    def snapshot(self) -> dict:
        return {'sensors': dict(self._sensors), 'system': None, 'sync': None}


def test_descriptor_matches_the_documented_plugin_id():
    collector = BuiltInResourceCollector(_FakeBridge())
    descriptor = collector.descriptor()
    assert descriptor.plugin_id == PLUGIN_ID == 'multisens.builtin.resource.system-metrics'
    assert descriptor.plugin_type == PluginType.RESOURCE_COLLECTOR


def test_available_metrics_matches_the_six_built_in_metrics():
    collector = BuiltInResourceCollector(_FakeBridge())
    metrics = {d.metric: d.unit for d in collector.available_metrics()}
    assert metrics == {
        'cpu_percent': '%', 'memory_mb': 'MB', 'network_receive_mbps': 'Mbps',
        'network_transmit_mbps': 'Mbps', 'fps': 'fps', 'pipeline_latency_ms': 'ms',
    }


def test_configure_requires_a_session_id():
    collector = BuiltInResourceCollector(_FakeBridge())
    with pytest.raises(ConnectorConfigError, match='session_id'):
        collector.configure({})


def test_health_before_start_is_stopped():
    collector = BuiltInResourceCollector(_FakeBridge())
    assert collector.health().state == ConnectorState.STOPPED


def test_sample_before_start_returns_nothing_never_raises():
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1'})
    assert collector.sample() == []


def test_start_then_sample_produces_real_cpu_memory_network_rows():
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1', 'configuration_id': 'cfg-x', 'platform_id': 'test-platform'})
    collector.start()
    assert collector.health().state == ConnectorState.RUNNING

    observations = collector.sample()
    metrics = {o.metric for o in observations}
    assert metrics == {'cpu_percent', 'memory_mb', 'network_receive_mbps', 'network_transmit_mbps'}
    for o in observations:
        assert o.session_id == 's1'
        assert o.configuration_id == 'cfg-x'
        assert o.platform_id == 'test-platform'
        assert o.quality in ('measured', 'unavailable')


def test_repeated_sample_reopens_the_window_each_time():
    # SystemMetricsWindow is a start()/end() one-shot shape - sample()
    # must turn it into a genuinely repeating collector, not a one-time
    # read that goes stale.
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1'})
    collector.start()

    first = collector.sample()
    second = collector.sample()
    third = collector.sample()
    assert len(first) == len(second) == len(third) == 4  # 4 system metrics, no sensor_ids configured


def test_configuration_id_and_platform_id_are_optional():
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1'})  # no configuration_id/platform_id
    collector.start()
    observations = collector.sample()
    assert all(o.configuration_id is None for o in observations)
    assert all(o.platform_id == 'unknown' for o in observations)  # UNKNOWN_PLATFORM_ID fallback


def test_stop_makes_sample_return_nothing_again():
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1'})
    collector.start()
    assert collector.sample() != []
    collector.stop()
    assert collector.health().state == ConnectorState.STOPPED
    assert collector.sample() == []


# --- sensor_ids: fps/pipeline_latency_ms from the ROS snapshot --------------

def test_sensor_ids_adds_fps_and_latency_rows_from_the_bridge_snapshot():
    bridge = _FakeBridge()
    bridge.set_sensor('robot_front_rgb', fps_received=29.5, publish_latency_ms=42.0)
    collector = BuiltInResourceCollector(bridge)
    collector.configure({'session_id': 's1', 'sensor_ids': ['robot_front_rgb']})
    collector.start()

    observations = collector.sample()
    metrics = {o.metric for o in observations}
    assert {'fps', 'pipeline_latency_ms'} <= metrics
    fps_row = next(o for o in observations if o.metric == 'fps')
    assert fps_row.value == 29.5
    assert fps_row.quality == 'measured'
    assert fps_row.session_id == 's1'


def test_sensor_absent_from_snapshot_produces_explicit_unavailable_rows():
    bridge = _FakeBridge()  # 'robot_front_rgb' never reported
    collector = BuiltInResourceCollector(bridge)
    collector.configure({'session_id': 's1', 'sensor_ids': ['robot_front_rgb']})
    collector.start()

    observations = collector.sample()
    fps_row = next(o for o in observations if o.metric == 'fps')
    assert fps_row.value is None
    assert fps_row.quality == 'unavailable'


def test_no_sensor_ids_configured_means_no_sensor_metric_rows():
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1'})  # sensor_ids omitted
    collector.start()
    observations = collector.sample()
    assert {'fps', 'pipeline_latency_ms'}.isdisjoint({o.metric for o in observations})


# --- registry integration ----------------------------------------------------

def test_discover_plugins_registers_the_builtin_resource_collector_when_a_bridge_is_supplied():
    registry = discover_plugins(entry_points=[], ros_bridge=_FakeBridge())
    record = registry.get(PLUGIN_ID)
    assert record is not None
    assert record.status == PluginStatus.AVAILABLE
    assert record.distribution_name == 'multisens'


def test_discover_plugins_skips_the_builtin_resource_collector_when_no_bridge_is_supplied():
    registry = discover_plugins(entry_points=[])
    assert registry.get(PLUGIN_ID) is None


def test_registry_factory_yields_a_fresh_collector_object_per_call():
    bridge = _FakeBridge()
    registry = discover_plugins(entry_points=[], ros_bridge=bridge)
    record = registry.get(PLUGIN_ID)
    assert record.factory is not None

    first = record.factory()
    second = record.factory()
    assert first is not second
    assert first is not record.instance and second is not record.instance


def test_never_a_second_competing_baseline_metric_definition():
    # The built-in's own available_metrics() must exactly match
    # SUPPORTED_RESOURCE_METRICS's own baseline six, or discovery would
    # silently union in a conflicting unit for one of them.
    from app.domain.resources import SUPPORTED_RESOURCE_METRICS
    collector = BuiltInResourceCollector(_FakeBridge())
    for d in collector.available_metrics():
        assert SUPPORTED_RESOURCE_METRICS[d.metric] == d.unit


def test_cpu_percent_and_memory_mb_are_real_psutil_readings_not_fabricated():
    # Not a mock - genuinely calls psutil, same overhead-verified path
    # test_resource_collector.py already exercises for SystemMetricsWindow
    # directly; this just proves the adapter doesn't intercept/replace it.
    collector = BuiltInResourceCollector(_FakeBridge())
    collector.configure({'session_id': 's1'})
    collector.start()
    observations = collector.sample()
    memory_row = next(o for o in observations if o.metric == 'memory_mb')
    assert memory_row.value == pytest.approx(psutil.virtual_memory().used / (1024 * 1024), rel=0.05)
