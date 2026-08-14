"""`multisens.test.robot.imu` - a deterministic synthetic IMU
`SensorConnector`, test-only fixture for Phase 104's Robot/Drone
Extensibility Validation (v0.9) - the architecture review's own
`robot_imu` paper design (docs/plugin-sdk.md, Phase 92), built for real.
Same boundary/honesty discipline as `lidar.py` in this package: only
`multisens_sdk` + the standard library, and `sample()`'s six-axis payload
is a small, generic, deterministic summary - never a claim that
MultiSens interprets IMU signals (orientation estimation, sensor fusion,
etc.), none of which exists anywhere in this connector or in core.
"""
from __future__ import annotations

from typing import Any

from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    SensorSample,
)

PLUGIN_ID = 'multisens.test.robot.imu'


class RobotImuConnector:
    def __init__(self):
        self._sensor_id: str | None = None
        self._state = ConnectorState.STOPPED
        self._tick = 0

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='Robot IMU (synthetic, test-only)', version='0.1.0',
            plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'data_type': 'imu', 'streaming': True, 'recorded': False},
            author='MultiSens Project', license='Apache-2.0',
            description=(
                'Synthetic IMU connector - proves connector registration/routing for a '
                'robotics-flavored sensor type, never IMU signal semantic understanding.'
            ),
        )

    def configure(self, sensor_id: str, config: dict[str, Any]) -> None:
        # No required fields - IMU sampling needs no external endpoint,
        # unlike the RTSP connector's required 'uri'. Never a reason to
        # invent a config requirement this connector doesn't actually have.
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
        # Deterministic synthetic six-axis reading - small enough to be
        # genuinely control-plane, no different in kind from the
        # temperature/humidity scalars examples/plugins/environment-sensor/
        # already emits.
        phase = (self._tick % 20) / 20.0
        payload = {
            'ax': round(0.1 * phase, 4), 'ay': round(0.05 * phase, 4), 'az': round(9.81 + 0.02 * phase, 4),
            'gx': round(0.01 * phase, 4), 'gy': round(-0.01 * phase, 4), 'gz': round(0.02 * phase, 4),
        }
        return SensorSample(
            sensor_id=self._sensor_id, timestamp_ms=float(self._tick * 20), sequence_id=self._tick,
            data_type='imu', payload=payload,
            metadata={'synthetic': True, 'label': 'SYNTHETIC SAMPLE SOURCE'},
        )
