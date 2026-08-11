"""Global/system diagnostics: CPU, RAM, uptime, connected sensor count.

Deliberately separate from per-sensor diagnostics (published by each
rtsp_ingestion_node itself) - no single sensor owns "how many sensors are
currently connected" or host resource usage, so this is its own small node
rather than bolted onto one arbitrarily-chosen sensor.

Connected-sensor-count is derived by listening to /multisens/diagnostics and
tracking the last time each hardware_id reported level=OK, not by trusting a
single snapshot - a sensor is only counted "connected" if it reported OK
within the last STALE_AFTER_SEC, so a sensor that stops reporting (crashed
node, not just a lost RTSP source) ages out instead of being stuck "connected"
forever.

sync_health is reported as "unavailable" - Phase 5 (synchronization) doesn't
exist yet, and this repo does not fabricate metrics for components that
haven't been built.
"""
import os
import time

import psutil
import rclpy
import yaml
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.node import Node

DEFAULT_CONFIG_PATH = '/config/sensors.yaml'
PUBLISH_PERIOD_SEC = 2.0
STALE_AFTER_SEC = 3.0


class SystemDiagnosticsNode(Node):
    def __init__(self):
        super().__init__('system_diagnostics_node')

        config_path = os.environ.get('MULTISENS_SENSORS_CONFIG', DEFAULT_CONFIG_PATH)
        self._known_sensor_ids = self._load_sensor_ids(config_path)
        self._last_ok_monotonic = {}
        self._start_monotonic = time.monotonic()

        self.create_subscription(
            DiagnosticArray, '/multisens/diagnostics', self._on_diagnostics, 10)
        self._publisher = self.create_publisher(DiagnosticArray, '/multisens/diagnostics', 10)

        # First psutil.cpu_percent() call always returns 0.0 (no baseline yet);
        # call it once here so the first real publish isn't a fabricated zero.
        psutil.cpu_percent(interval=None)

        self.create_timer(PUBLISH_PERIOD_SEC, self._publish_diagnostics)
        self.get_logger().info(
            f'tracking {len(self._known_sensor_ids)} configured sensors: '
            f'{sorted(self._known_sensor_ids)}')

    @staticmethod
    def _load_sensor_ids(config_path: str) -> set:
        if not os.path.isfile(config_path):
            return set()
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return {entry['id'] for entry in data.get('sensors', [])}

    def _on_diagnostics(self, msg: DiagnosticArray):
        # This node also publishes to /multisens/diagnostics, so it receives
        # its own "system" status back here too - only count hardware_ids
        # that are actual configured sensors, or self-reports inflate the
        # connected count above the true total.
        now = time.monotonic()
        for status in msg.status:
            if status.hardware_id in self._known_sensor_ids and status.level == DiagnosticStatus.OK:
                self._last_ok_monotonic[status.hardware_id] = now

    def _connected_sensor_count(self) -> int:
        now = time.monotonic()
        return sum(
            1 for last_ok in self._last_ok_monotonic.values()
            if now - last_ok <= STALE_AFTER_SEC)

    def _publish_diagnostics(self):
        connected = self._connected_sensor_count()
        total = len(self._known_sensor_ids)
        uptime_sec = time.monotonic() - self._start_monotonic

        status = DiagnosticStatus()
        status.name = 'multisens: system'
        status.hardware_id = 'system'
        status.level = DiagnosticStatus.OK if connected == total and total > 0 else DiagnosticStatus.WARN
        status.message = f'{connected}/{total} configured sensors connected'
        status.values = [
            KeyValue(key='cpu_percent', value=f'{psutil.cpu_percent(interval=None):.1f}'),
            KeyValue(key='memory_percent', value=f'{psutil.virtual_memory().percent:.1f}'),
            KeyValue(key='uptime_sec', value=f'{uptime_sec:.0f}'),
            KeyValue(key='connected_sensor_count', value=str(connected)),
            KeyValue(key='total_sensor_count', value=str(total)),
            KeyValue(key='sync_health', value='unavailable'),
        ]

        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = [status]
        self._publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = SystemDiagnosticsNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
