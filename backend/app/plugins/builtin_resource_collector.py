"""`multisens.builtin.resource.system-metrics` - wraps the existing,
completely unchanged v0.7 collection code (`app/resource_collector.py`'s
`SystemMetricsWindow` + `collect_sensor_metrics`) behind the same
`ResourceCollector` plugin interface an external plugin uses (v0.9.1,
issue #111). One lifecycle model, not two: this built-in goes through
the identical `ResourceCollectorInstance`/session-bound wiring
(`app/plugins/manager.py`'s `build_resource_collector_instances()`) an
installed `RESOURCE_COLLECTOR` plugin does, registered as a built-in
exactly like `builtin_rtsp.py`'s `RtspSensorConnector` already is.

`SystemMetricsWindow` is a `start()`/`end()` *window* shape (one shot
over an explicit span), not a repeatable `sample()` shape - `sample()`
below closes the current window and immediately reopens the next one,
turning it into a repeating collector without changing
`SystemMetricsWindow` itself at all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.resource_collector import SystemMetricsWindow, collect_sensor_metrics
from app.ros_bridge import RosBridge
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

PLUGIN_ID = 'multisens.builtin.resource.system-metrics'

_METRICS = (
    ('cpu_percent', '%'),
    ('memory_mb', 'MB'),
    ('network_receive_mbps', 'Mbps'),
    ('network_transmit_mbps', 'Mbps'),
    ('fps', 'fps'),
    ('pipeline_latency_ms', 'ms'),
)


class BuiltInResourceCollector:
    def __init__(self, bridge: RosBridge):
        self._bridge = bridge
        self._window = SystemMetricsWindow()
        self._session_id: str | None = None
        self._configuration_id: str | None = None
        self._platform_id: str | None = None
        self._sensor_ids: list[str] = []
        self._active = False
        self._sensor_window_started_at: datetime | None = None

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='Built-in System Metrics Collector', version='1.0.0',
            plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            author='MultiSens', license='Apache-2.0',
            description=(
                'Built-in adapter over the existing v0.7 psutil/ROS-snapshot collection code '
                '(app/resource_collector.py) - cpu_percent/memory_mb/network_*/fps/pipeline_latency_ms, '
                'unchanged measurement logic, now reachable through the same session-bound live-collection '
                'path an external ResourceCollector plugin uses.'
            ),
        )

    def available_metrics(self) -> list[ResourceMetricDescriptor]:
        return [ResourceMetricDescriptor(metric=metric, unit=unit) for metric, unit in _METRICS]

    def configure(self, config: dict[str, Any]) -> None:
        session_id = config.get('session_id')
        if not session_id or not isinstance(session_id, str):
            raise ConnectorConfigError("'session_id' is required and must be a non-empty string")
        self._session_id = session_id
        configuration_id = config.get('configuration_id')
        self._configuration_id = configuration_id if isinstance(configuration_id, str) else None
        platform_id = config.get('platform_id')
        self._platform_id = platform_id if isinstance(platform_id, str) else None
        sensor_ids = config.get('sensor_ids', [])
        self._sensor_ids = [s for s in sensor_ids if isinstance(s, str)] if isinstance(sensor_ids, list) else []

    def start(self) -> None:
        self._window.start()
        self._sensor_window_started_at = datetime.now(timezone.utc)
        self._active = True

    def stop(self) -> None:
        self._active = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self._active else ConnectorState.STOPPED)

    def sample(self) -> list[ResourceObservation]:
        if not self._active:
            return []
        now = datetime.now(timezone.utc)
        # platform_id is required by SystemMetricsWindow.end()/
        # collect_sensor_metrics - 'unknown' (UNKNOWN_PLATFORM_ID) is the
        # documented fallback (resources.py) whenever a collector
        # genuinely couldn't determine one, never a guess.
        platform_id = self._platform_id or 'unknown'
        observations = list(self._window.end(self._session_id, self._configuration_id, platform_id))
        self._window.start()  # reopen the next window immediately - never a gap

        sensor_window_ended_at = now
        if self._sensor_ids:
            observations.extend(collect_sensor_metrics(
                self._bridge.snapshot(), self._sensor_ids, self._session_id, self._configuration_id,
                platform_id, self._sensor_window_started_at, sensor_window_ended_at,
            ))
        self._sensor_window_started_at = sensor_window_ended_at
        return observations
