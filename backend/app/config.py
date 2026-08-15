"""Loads config/sensors.yaml - the same file and env var the ROS ingestion
launch file reads, so the backend's view of "what sensors exist" never
drifts from what's actually running."""
import os

import yaml

DEFAULT_CONFIG_PATH = '/config/sensors.yaml'


def _load_config() -> dict:
    config_path = os.environ.get('MULTISENS_SENSORS_CONFIG', DEFAULT_CONFIG_PATH)
    if not os.path.isfile(config_path):
        return {}
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_sensors() -> list[dict]:
    sensors = _load_config().get('sensors', [])
    return sensors if isinstance(sensors, list) else []


def load_poll_connectors() -> list[dict]:
    """`poll_connectors` (v0.9 bug hunt, issue #110): the config surface
    for activating an installed `PREDICTION_CONNECTOR`/
    `GROUND_TRUTH_CONNECTOR` plugin - mirrors each sensor's own
    `connector:` block shape (`plugin:`/`config:`), just at the top
    level rather than nested under one sensor id, since neither
    connector type is tied to a single sensor (each item they emit
    carries its own `sensor_ids` - see poll_connector_instance.py's own
    module docstring). Same restart-time-only convention as every other
    plugin config in this file - no mutation API."""
    poll_connectors = _load_config().get('poll_connectors', [])
    return poll_connectors if isinstance(poll_connectors, list) else []


def load_resource_collectors() -> list[dict]:
    """`resource_collectors` (v0.9.1, issue #111): the config surface for
    activating an installed `RESOURCE_COLLECTOR` plugin for live,
    session-bound sampling - same `id`/`plugin`/`config`/
    `poll_interval_s` shape as `poll_connectors` above, deliberately not
    reused as one combined list since the two are wired at completely
    different trigger points (poll connectors start at process boot and
    run for the container's lifetime; resource collectors are
    constructed at boot but only actually sample between a session's
    `start` and `complete` - see `app/plugins/manager.py`'s own
    `build_resource_collector_instances()`). Same restart-time-only
    convention as every other plugin config in this file."""
    resource_collectors = _load_config().get('resource_collectors', [])
    return resource_collectors if isinstance(resource_collectors, list) else []


def load_platform_id() -> str:
    """Top-level `platform_id:` (v0.9.1, issue #111) - the value live
    resource collection attributes its observations to
    (`ResourceObservation.platform_id` is required, never `None`).
    `ExecutionPlatform`'s own docstring (`app/domain/resources.py`) is
    explicit that this is "a small, explicitly-declared record... never
    auto-detected by magic" - matched here by reading a declared config
    value rather than guessing from `/proc`/`uname`. Falls back to
    `UNKNOWN_PLATFORM_ID` ('unknown') when absent, the same documented
    fallback `resources.py` already uses whenever a collector "genuinely
    couldn't determine one" - never a fabricated guess."""
    from app.domain.resources import UNKNOWN_PLATFORM_ID
    platform_id = _load_config().get('platform_id')
    return platform_id if isinstance(platform_id, str) and platform_id else UNKNOWN_PLATFORM_ID


def load_disabled_plugin_ids() -> list[str]:
    """`plugins.disabled` (v0.9, Phase 94) - the same config file sensors
    already live in, no separate file until a real need for one shows up.
    Installation stays external package management (`pip install`); this
    only ever suppresses discovery of an already-installed plugin_id -
    see `backend/app/plugins/registry.py`'s own module docstring for why
    the check happens before a disabled plugin's code is ever imported."""
    plugins_section = _load_config().get('plugins', {})
    if not isinstance(plugins_section, dict):
        return []
    disabled = plugins_section.get('disabled', [])
    return [str(d) for d in disabled] if isinstance(disabled, list) else []
