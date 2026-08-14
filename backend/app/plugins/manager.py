"""Builds real `ConnectorInstance`s from `config/sensors.yaml`'s optional
per-sensor `connector:` block (v0.9, Phase 102) - the wiring
docs/connector-api.md already documented back in Phase 95 but nothing
had yet executed. Runs once at startup (see `app/main.py`'s lifespan);
there is no mutation API (issue #103's own explicit "config stays a
restart-time file change" boundary) - a connector's config only ever
changes by editing the file and restarting the container.

One fresh plugin object per sensor id, never a shared one - `plugin_id`
names an *implementation*, not an instance, so two sensor ids naming the
same `plugin_id` (two RTSP cameras) each get their own object via the
registry's own `PluginRecord.factory` (Phase 102's own addition to
`registry.py`). A sensor whose connector can't be built at all (unknown
plugin, wrong plugin_type, not AVAILABLE) is skipped with a printed
diagnostic - it never prevents the rest of the sensors' connectors from
being built, nor crashes application startup.
"""
from __future__ import annotations

from typing import Any

from app.plugins.connector_instance import ConnectorInstance, ConnectorLifecycleError, ConnectorRuntimeError
from app.plugins.registry import PluginRegistry, PluginStatus
from multisens_sdk import ConnectorConfigError, PluginType


def build_connector_instances(sensors: list[dict], registry: PluginRegistry) -> dict[str, ConnectorInstance]:
    instances: dict[str, ConnectorInstance] = {}
    for sensor in sensors:
        connector_spec = sensor.get('connector')
        if not isinstance(connector_spec, dict):
            continue  # no connector block - this sensor stays video-plane/ROS-only, unchanged

        sensor_id = sensor.get('id')
        plugin_id = connector_spec.get('plugin')
        config = connector_spec.get('config', {})
        if not isinstance(sensor_id, str) or not isinstance(plugin_id, str):
            print(f"connector wiring: sensor entry missing 'id' or connector.plugin - skipped ({sensor!r})")
            continue

        record = registry.get(plugin_id)
        if record is None or record.status != PluginStatus.AVAILABLE:
            status = record.status.value if record is not None else 'not found'
            print(f"connector wiring: sensor '{sensor_id}' names plugin '{plugin_id}' ({status}) - skipped")
            continue
        if record.descriptor is None or record.descriptor.plugin_type != PluginType.SENSOR_CONNECTOR:
            print(f"connector wiring: sensor '{sensor_id}' names plugin '{plugin_id}' which is not a sensor "
                  f"connector - skipped")
            continue
        if record.factory is None:
            print(f"connector wiring: sensor '{sensor_id}' plugin '{plugin_id}' has no usable factory - skipped")
            continue

        connector_obj = record.factory()
        instance = ConnectorInstance(sensor_id, plugin_id, connector_obj)
        instances[sensor_id] = instance

        try:
            instance.configure(dict(config) if isinstance(config, dict) else {})
            instance.start()
        except (ConnectorConfigError, ConnectorRuntimeError, ConnectorLifecycleError) as e:
            # Left registered in `instances` (STOPPED if configure() itself
            # rejected the config, FAILED if configure() succeeded but
            # start() didn't) rather than dropped - GET
            # /api/connectors/{sensor_id} must still be able to show *why*
            # it isn't running, never a silent 404 for a sensor that
            # really is named in config.
            print(f"connector wiring: sensor '{sensor_id}' plugin '{plugin_id}' failed to start: {e}")

    return instances
