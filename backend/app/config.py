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
