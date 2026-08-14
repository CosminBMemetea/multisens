"""Phase 96 (v0.9): the built-in RTSP `SensorConnector` -
`multisens.builtin.sensor.rtsp`. Descriptor-only over the existing,
completely unchanged v0.1 ingestion pipeline: `health()` is a pure
mapping function from a `RosBridge`-shaped snapshot source, never a
second health-tracking mechanism, and `sample()` always returns `None`
(video stays data-plane, never routed through this object).

A fake bridge (`.snapshot()` returning a controllable dict) stands in for
the real `RosBridge` - spinning an actual rclpy node has nothing to do
with what this phase adds, which is purely the mapping/wrapping logic.
"""
from app.plugins.builtin_rtsp import PLUGIN_ID, RtspSensorConnector
from app.plugins.connector_instance import ConnectorInstance
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import ConnectorConfigError, ConnectorState, PluginType
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION


class _FakeBridge:
    def __init__(self):
        self._sensors: dict[str, dict] = {}

    def set_sensor(self, sensor_id: str, **fields) -> None:
        self._sensors[sensor_id] = fields

    def snapshot(self) -> dict:
        return {'sensors': dict(self._sensors), 'system': None, 'sync': None}


def test_descriptor_matches_the_documented_plugin_id_and_capabilities():
    connector = RtspSensorConnector(_FakeBridge())
    descriptor = connector.descriptor()
    assert descriptor.plugin_id == PLUGIN_ID == 'multisens.builtin.sensor.rtsp'
    assert descriptor.plugin_type == PluginType.SENSOR_CONNECTOR
    assert descriptor.api_version == MULTISENS_PLUGIN_API_VERSION
    assert descriptor.capabilities == {'data_type': 'image', 'streaming': True, 'recorded': False}


def test_configure_requires_a_uri_field():
    connector = RtspSensorConnector(_FakeBridge())
    try:
        connector.configure('rgb', {'transport': 'tcp'})
        assert False, 'expected ConnectorConfigError'
    except ConnectorConfigError as e:
        assert 'uri' in str(e)


def test_health_before_start_is_stopped_without_touching_the_bridge():
    bridge = _FakeBridge()
    connector = RtspSensorConnector(bridge)
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    assert connector.health().state == ConnectorState.STOPPED


def test_health_after_start_with_no_snapshot_entry_is_degraded_not_failed():
    # The ROS node may still be starting, or the connector was just
    # activated before any diagnostics arrived - "not yet proven
    # healthy," never a hard failure this connector itself caused.
    connector = RtspSensorConnector(_FakeBridge())
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    connector.start()
    health = connector.health()
    assert health.state == ConnectorState.DEGRADED
    assert 'rgb' in health.message


def test_health_maps_connected_diagnostics_to_running_with_details():
    bridge = _FakeBridge()
    bridge.set_sensor('rgb', connection_state='connected', fps_received='29.8', fps_expected='30.0',
                       last_frame_age_ms='33', level='ok', message='')
    connector = RtspSensorConnector(bridge)
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    connector.start()

    health = connector.health()
    assert health.state == ConnectorState.RUNNING
    assert health.last_sample_age_s == 0.033
    assert health.details['fps_received'] == '29.8'


def test_health_maps_disconnected_diagnostics_to_degraded_not_running():
    bridge = _FakeBridge()
    bridge.set_sensor('rgb', connection_state='disconnected', level='error', message='RTSP source unreachable')
    connector = RtspSensorConnector(bridge)
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    connector.start()

    health = connector.health()
    assert health.state == ConnectorState.DEGRADED
    assert health.message == 'RTSP source unreachable'


def test_health_handles_unavailable_last_frame_age_without_crashing():
    bridge = _FakeBridge()
    bridge.set_sensor('rgb', connection_state='connected', last_frame_age_ms='unavailable')
    connector = RtspSensorConnector(bridge)
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    connector.start()
    assert connector.health().last_sample_age_s is None


def test_sample_always_returns_none_video_is_data_plane_not_control_plane():
    bridge = _FakeBridge()
    bridge.set_sensor('rgb', connection_state='connected')
    connector = RtspSensorConnector(bridge)
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    connector.start()
    assert connector.sample() is None


def test_stop_returns_to_stopped_state():
    bridge = _FakeBridge()
    bridge.set_sensor('rgb', connection_state='connected')
    connector = RtspSensorConnector(bridge)
    connector.configure('rgb', {'uri': 'rtsp://example/rgb'})
    connector.start()
    assert connector.health().state == ConnectorState.RUNNING
    connector.stop()
    assert connector.health().state == ConnectorState.STOPPED


# --- through the real ConnectorInstance wrapper -----------------------------

def test_two_rtsp_sensor_instances_share_the_bridge_but_stay_independent():
    # ridesafe_front_rgb / ridesafe_rear_rgb - the flagship "one connector
    # implementation, two sensor instances" demonstration
    # (docs/plugin-sdk.md).
    bridge = _FakeBridge()
    bridge.set_sensor('ridesafe_front_rgb', connection_state='connected')
    bridge.set_sensor('ridesafe_rear_rgb', connection_state='disconnected')

    front = ConnectorInstance('ridesafe_front_rgb', PLUGIN_ID, RtspSensorConnector(bridge))
    rear = ConnectorInstance('ridesafe_rear_rgb', PLUGIN_ID, RtspSensorConnector(bridge))
    front.configure({'uri': 'rtsp://example/front'})
    rear.configure({'uri': 'rtsp://example/rear'})
    front.start()
    rear.start()

    assert front.health().state == ConnectorState.RUNNING
    assert rear.health().state == ConnectorState.DEGRADED


# --- registry integration ---------------------------------------------------

def test_discover_plugins_registers_the_rtsp_connector_when_a_bridge_is_supplied():
    registry = discover_plugins(entry_points=[], ros_bridge=_FakeBridge())
    record = registry.get(PLUGIN_ID)
    assert record is not None
    assert record.status == PluginStatus.AVAILABLE
    assert record.distribution_name == 'multisens'


def test_discover_plugins_skips_the_rtsp_connector_when_no_bridge_is_supplied():
    # Most tests (and any environment with no real RosBridge) simply
    # don't register it - never a crash from a missing bridge.
    registry = discover_plugins(entry_points=[])
    assert registry.get(PLUGIN_ID) is None


def test_registry_factory_yields_a_fresh_connector_object_per_call():
    # v0.9, Phase 102: this is exactly what app/plugins/manager.py relies
    # on to give ridesafe_front_rgb/ridesafe_rear_rgb their own connector
    # objects - the registry's singleton `record.instance` must never be
    # what a second sensor id gets wired to.
    bridge = _FakeBridge()
    registry = discover_plugins(entry_points=[], ros_bridge=bridge)
    record = registry.get(PLUGIN_ID)
    assert record.factory is not None

    front = record.factory()
    rear = record.factory()
    assert front is not rear
    assert front is not record.instance and rear is not record.instance

    bridge.set_sensor('front', connection_state='connected')
    bridge.set_sensor('rear', connection_state='disconnected')
    front.configure('front', {'uri': 'rtsp://example/front'})
    rear.configure('rear', {'uri': 'rtsp://example/rear'})
    front.start()
    rear.start()
    assert front.health().state == ConnectorState.RUNNING
    assert rear.health().state == ConnectorState.DEGRADED
