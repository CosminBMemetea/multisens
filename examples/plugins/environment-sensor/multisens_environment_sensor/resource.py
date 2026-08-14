"""A deterministic synthetic `ResourceCollector` - proves resource
telemetry is externally extensible. Imports only `multisens_sdk` and the
standard library.

**SYNTHETIC SAMPLE SOURCE**: `synthetic_metric`'s value cycles through a
fixed, deterministic sequence - never a real host measurement, never
randomized.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    ResourceMetricDescriptor,
    ResourceObservation,
)

PLUGIN_ID = 'multisens.example.resource.synthetic-metric'
HOMEPAGE = 'https://github.com/CosminBMemetea/multisens/tree/main/examples/plugins/environment-sensor'


class SyntheticMetricCollector:
    def __init__(self) -> None:
        self._session_id: str | None = None
        self._platform_id = 'example-synthetic-platform'
        self._index = 0
        self._active = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='Synthetic Metric Collector', version='0.1.0',
            plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            author='MultiSens Project', license='Apache-2.0', homepage=HOMEPAGE,
            description=(
                'Deterministic synthetic resource metric - SYNTHETIC SAMPLE SOURCE, '
                'proves ResourceCollector extensibility.'
            ),
        )

    def available_metrics(self) -> list[ResourceMetricDescriptor]:
        return [ResourceMetricDescriptor(
            metric='synthetic_metric', unit='widgets',
            description='A deterministic example metric - never a real measurement.',
        )]

    def configure(self, config: dict[str, Any]) -> None:
        session_id = config.get('session_id')
        if not session_id or not isinstance(session_id, str):
            raise ConnectorConfigError("'session_id' is required and must be a non-empty string")
        self._session_id = session_id

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self._active else ConnectorState.STOPPED)

    def sample(self) -> list[ResourceObservation]:
        if not self._active or self._session_id is None:
            return []
        now = datetime.now(timezone.utc)
        self._index += 1
        return [ResourceObservation(
            id=f'synthetic-metric-{self._index}', session_id=self._session_id, metric='synthetic_metric',
            value=float(10 + (self._index % 5)), unit='widgets', quality='measured',
            source='multisens_environment_sensor.synthetic_metric', platform_id=self._platform_id,
            started_at=now, ended_at=now, metadata={'synthetic': True, 'label': 'SYNTHETIC SAMPLE SOURCE'},
        )]


def create() -> SyntheticMetricCollector:
    """The entry-point factory - `multisens.plugins` resolves to this
    zero-arg callable, called once per discovery pass."""
    return SyntheticMetricCollector()
