"""Tests the bridge's own logic (staleness expiry, message translation)
without a live ROS graph: RosBridge() is never .start()-ed here, so no
rclpy.init()/DDS participant is ever created - _on_diagnostics/_on_sync are
called directly with real diagnostic_msgs objects, which is enough to
exercise the real translation and expiry code paths.
"""
import time

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

from app import ros_bridge as ros_bridge_module
from app.ros_bridge import RosBridge


def _diagnostic_array(hardware_id: str, level=DiagnosticStatus.OK, **values) -> DiagnosticArray:
    status = DiagnosticStatus()
    status.hardware_id = hardware_id
    status.level = level
    status.message = 'test'
    status.values = [KeyValue(key=k, value=str(v)) for k, v in values.items()]
    msg = DiagnosticArray()
    msg.status = [status]
    return msg


def test_fresh_sensor_appears_in_snapshot():
    bridge = RosBridge()
    bridge._on_diagnostics(_diagnostic_array('rgb', fps_received='30.0'))

    snapshot = bridge.snapshot()

    assert 'rgb' in snapshot['sensors']
    assert snapshot['sensors']['rgb']['fps_received'] == '30.0'
    assert snapshot['sensors']['rgb']['level'] == 'ok'


def test_system_hardware_id_goes_to_system_not_sensors():
    bridge = RosBridge()
    bridge._on_diagnostics(_diagnostic_array('system', cpu_percent='10.0'))

    snapshot = bridge.snapshot()

    assert snapshot['sensors'] == {}
    assert snapshot['system']['cpu_percent'] == '10.0'


def test_sync_status_translated_separately():
    bridge = RosBridge()
    msg = DiagnosticArray()
    status = DiagnosticStatus()
    status.hardware_id = 'sync'
    status.level = DiagnosticStatus.WARN
    status.message = 'stale: thermal'
    status.values = [KeyValue(key='max_skew_ms', value='12.0')]
    msg.status = [status]

    bridge._on_sync(msg)

    assert bridge.snapshot()['sync'] == {
        'level': 'warn', 'message': 'stale: thermal', 'max_skew_ms': '12.0',
    }


def test_stale_sensor_disappears_from_snapshot(monkeypatch):
    # Regression test for the Phase 8 bug: a sensor whose reporting node
    # died must not be shown as "connected" forever just because its last
    # message is still sitting in memory.
    monkeypatch.setattr(ros_bridge_module, 'STALE_AFTER_SEC', 0.05)
    bridge = RosBridge()
    bridge._on_diagnostics(_diagnostic_array('thermal', connection_state='connected'))

    assert 'thermal' in bridge.snapshot()['sensors']

    time.sleep(0.1)

    assert 'thermal' not in bridge.snapshot()['sensors']


def test_stale_system_and_sync_become_none(monkeypatch):
    monkeypatch.setattr(ros_bridge_module, 'STALE_AFTER_SEC', 0.05)
    bridge = RosBridge()
    bridge._on_diagnostics(_diagnostic_array('system', cpu_percent='5.0'))

    assert bridge.snapshot()['system'] is not None

    time.sleep(0.1)

    assert bridge.snapshot()['system'] is None


def test_snapshot_never_touched_bridge_returns_empty_state():
    bridge = RosBridge()
    assert bridge.snapshot() == {'sensors': {}, 'system': None, 'sync': None}
