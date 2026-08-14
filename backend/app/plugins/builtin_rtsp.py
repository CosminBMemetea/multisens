"""`multisens.builtin.sensor.rtsp` - a descriptor-only `SensorConnector`
wrapping the existing, completely unchanged v0.1 RTSP ingestion pipeline
(v0.9, Phase 96).

This is deliberately **not** a rewrite of `rtsp_ingestion_node.py`/
`sensor_config.py`/`ingestion.launch.py` - all three stay untouched. The
real RTSP stream is started/stopped by ROS launch off `config/sensors.yaml`
at container boot, independent of this Python object entirely;
`start()`/`stop()` here are bookkeeping only (whether this backend-side
*view* is actively watching), never a second ingestion runtime.
`health()` is a pure mapping function from `RosBridge.snapshot()`'s
already-existing per-sensor diagnostics dict (keyed by `hardware_id`,
which is exactly the sensor `id` from `config/sensors.yaml` -
`docs/connector-api.md` - so no id/modality translation is needed) into
`ConnectorHealth` - never a second, parallel health-tracking mechanism
(docs/plugin-sdk.md#how-existing-rtsp-ingestion-should-migrate-without-unnecessary-rewrite,
master prompt §47/§62).

`sample()` always returns `None` - video is data-plane, not
control-plane (docs/plugin-sdk.md#data-plane-vs-control-plane); this
connector never returns frame bytes. `video_relay.py`'s existing
RTSP-to-MJPEG relay and the ROS image topic remain the only ways to see
actual pixels, completely unchanged by this phase.
"""
from __future__ import annotations

from typing import Any

from app.ros_bridge import RosBridge
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    SensorSample,
)

PLUGIN_ID = 'multisens.builtin.sensor.rtsp'


class RtspSensorConnector:
    def __init__(self, bridge: RosBridge):
        self._bridge = bridge
        self._sensor_id: str | None = None
        self._active = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='RTSP Sensor Connector', version='1.0.0',
            plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'data_type': 'image', 'streaming': True, 'recorded': False},
            author='MultiSens', license='Apache-2.0',
            description=(
                'Built-in adapter over the existing v0.1 RTSP ingestion pipeline - '
                'descriptor/health only, the real stream is ROS-launched independently.'
            ),
        )

    def configure(self, sensor_id: str, config: dict[str, Any]) -> None:
        if 'uri' not in config:
            raise ConnectorConfigError("RTSP connector config requires a 'uri' field")
        self._sensor_id = sensor_id

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def health(self) -> ConnectorHealth:
        if not self._active or self._sensor_id is None:
            return ConnectorHealth(state=ConnectorState.STOPPED)

        entry = self._bridge.snapshot()['sensors'].get(self._sensor_id)
        if entry is None:
            # No diagnostics received yet, or aged out (RosBridge's own
            # STALE_AFTER_SEC expiry) - the ROS node may still be
            # starting, or its process may be gone. Either way this is
            # "not currently proven healthy," not a hard failure this
            # connector itself caused.
            return ConnectorHealth(
                state=ConnectorState.DEGRADED,
                message=f"no diagnostics received yet for '{self._sensor_id}' (or gone stale)",
            )

        connected = entry.get('connection_state') == 'connected'
        last_sample_age_s = _parse_ms_to_seconds(entry.get('last_frame_age_ms'))
        return ConnectorHealth(
            state=ConnectorState.RUNNING if connected else ConnectorState.DEGRADED,
            last_sample_age_s=last_sample_age_s,
            message=entry.get('message') or None,
            details=dict(entry),
        )

    def sample(self) -> SensorSample | None:
        return None


def _parse_ms_to_seconds(raw: Any) -> float | None:
    if raw is None or raw == 'unavailable':
        return None
    try:
        return float(raw) / 1000.0
    except (TypeError, ValueError):
        return None
