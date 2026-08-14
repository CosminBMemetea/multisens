"""A deterministic synthetic temperature/humidity `SensorConnector` -
proves MultiSens plugin extensibility is not camera-specific. Imports
only `multisens_sdk` and the standard library.

**SYNTHETIC SAMPLE SOURCE**: every value here comes from a fixed sine/
cosine pattern indexed by an internal sample counter - never measured
from any real hardware, never randomized (the same deterministic-by-
construction discipline every synthetic dataset in the main MultiSens
repository already follows).
"""
from __future__ import annotations

import math
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

PLUGIN_ID = 'multisens.example.sensor.environment-sensor'
HOMEPAGE = 'https://github.com/CosminBMemetea/multisens/tree/main/examples/plugins/environment-sensor'


class EnvironmentSensorConnector:
    def __init__(self) -> None:
        self._sensor_id: str | None = None
        self._cycle_length = 20
        self._index = 0
        self._active = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='Environment Sensor (temperature/humidity)', version='0.1.0',
            plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'data_type': 'scalar', 'streaming': False, 'recorded': False},
            author='MultiSens Project', license='Apache-2.0', homepage=HOMEPAGE,
            description=(
                'Deterministic synthetic temperature/humidity sensor - SYNTHETIC SAMPLE '
                'SOURCE, proves the SDK is not camera-specific.'
            ),
        )

    def configure(self, sensor_id: str, config: dict[str, Any]) -> None:
        cycle_length = config.get('cycle_length', 20)
        if not isinstance(cycle_length, int) or isinstance(cycle_length, bool) or cycle_length <= 0:
            raise ConnectorConfigError(f"'cycle_length' must be a positive integer, got {cycle_length!r}")
        self._sensor_id = sensor_id
        self._cycle_length = cycle_length
        self._index = 0

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            state=ConnectorState.RUNNING if self._active else ConnectorState.STOPPED,
            last_sample_age_s=0.0 if self._active else None,
            details={'cycle_length': self._cycle_length} if self._active else {},
        )

    def sample(self) -> SensorSample | None:
        if not self._active or self._sensor_id is None:
            return None
        phase = 2 * math.pi * (self._index % self._cycle_length) / self._cycle_length
        temperature_c = round(20.0 + 2.0 * math.sin(phase), 2)
        humidity_percent = round(50.0 + 5.0 * math.cos(phase), 2)
        self._index += 1
        return SensorSample(
            sensor_id=self._sensor_id, timestamp_ms=float(self._index), sequence_id=self._index,
            data_type='scalar',
            payload={'temperature_c': temperature_c, 'humidity_percent': humidity_percent},
            metadata={'synthetic': True, 'label': 'SYNTHETIC SAMPLE SOURCE'},
        )


def create() -> EnvironmentSensorConnector:
    """The entry-point factory - `multisens.plugins` resolves to this
    zero-arg callable, called once per discovery pass."""
    return EnvironmentSensorConnector()
