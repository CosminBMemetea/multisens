"""`multisens.test.robot.lidar` - a deterministic synthetic LiDAR
`SensorConnector`, test-only fixture for Phase 104's Robot/Drone
Extensibility Validation (v0.9). Proves the SDK boundary against a
robotics-flavored scenario: a plugin author can register a connector for
LiDAR-shaped data using nothing but `multisens_sdk` + the standard
library - no `backend.app` import, no core change - matching the
architecture review's own `robot_lidar` paper design (docs/plugin-sdk.md,
Phase 92).

Explicitly **not** a claim that MultiSens understands LiDAR semantics:
`sample()` emits a small, generic, JSON-serializable summary
(`point_count`/`range_m`) - control-plane-sized, matching the SDK's own
small-payload rule (docs/plugin-sdk.md#data-plane-vs-control-plane) -
never actual point-cloud geometry, and no point-cloud-specific
processing or validation exists anywhere in this connector or in
MultiSens core. Every value is deterministic and labeled `SYNTHETIC
SAMPLE SOURCE`, the same convention
`examples/plugins/environment-sensor/` already established.
"""
from __future__ import annotations

from typing import Any

from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    SensorSample,
)

PLUGIN_ID = 'multisens.test.robot.lidar'


class RobotLidarConnector:
    def __init__(self):
        self._sensor_id: str | None = None
        self._state = ConnectorState.STOPPED
        self._tick = 0

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='Robot LiDAR (synthetic, test-only)', version='0.1.0',
            plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'data_type': 'point_cloud_summary', 'streaming': True, 'recorded': False},
            author='MultiSens Project', license='Apache-2.0',
            description=(
                'Synthetic LiDAR connector - proves connector registration/routing for a '
                'robotics-flavored sensor type, never point-cloud semantic understanding.'
            ),
        )

    def configure(self, sensor_id: str, config: dict[str, Any]) -> None:
        scan_rate_hz = config.get('scan_rate_hz', 10)
        if not isinstance(scan_rate_hz, (int, float)) or isinstance(scan_rate_hz, bool) or scan_rate_hz <= 0:
            raise ConnectorConfigError("'scan_rate_hz' must be a positive number")
        self._sensor_id = sensor_id

    def start(self) -> None:
        self._state = ConnectorState.RUNNING

    def stop(self) -> None:
        self._state = ConnectorState.STOPPED

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=self._state)

    def sample(self) -> SensorSample | None:
        if self._state != ConnectorState.RUNNING or self._sensor_id is None:
            return None
        self._tick += 1
        # A small, generic summary only - real point-cloud geometry is
        # data-plane, not this object's job, exactly like the built-in
        # RTSP connector's sample() never carrying frame bytes.
        point_count = 1000 + (self._tick % 5) * 50
        range_m = 5.0 + (self._tick % 10) * 0.5
        return SensorSample(
            sensor_id=self._sensor_id, timestamp_ms=float(self._tick * 100), sequence_id=self._tick,
            data_type='point_cloud_summary', payload={'point_count': point_count, 'range_m': range_m},
            metadata={'synthetic': True, 'label': 'SYNTHETIC SAMPLE SOURCE'},
        )
