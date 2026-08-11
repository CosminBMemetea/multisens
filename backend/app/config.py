"""Loads config/sensors.yaml - the same file and env var the ROS ingestion
launch file reads, so the backend's view of "what sensors exist" never
drifts from what's actually running."""
import os

import yaml

DEFAULT_CONFIG_PATH = '/config/sensors.yaml'


def load_sensors() -> list[dict]:
    config_path = os.environ.get('MULTISENS_SENSORS_CONFIG', DEFAULT_CONFIG_PATH)
    if not os.path.isfile(config_path):
        return []
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get('sensors', [])
