"""Pure config loading/validation - no launch_ros or rclpy import, on
purpose, so this is testable with plain pytest and no live ROS environment.
ingestion.launch.py calls this, then wraps the result in launch_ros Node
actions; that wrapping step is the only ROS-specific part left in the
launch file.
"""
import os

import yaml

DEFAULT_CONFIG_PATH = '/config/sensors.yaml'
SUPPORTED_TRANSPORTS = {'rtsp'}


def load_sensors_config(config_path: str) -> list[dict]:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f'sensors config not found: {config_path}')
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get('sensors', [])


def select_usable_sensors(sensors: list[dict], config_path: str = '<config>') -> list[dict]:
    """Filters out sensors with an unsupported transport and raises on a
    duplicate modality (which would silently collide on the same topic).
    Returns the entries that should actually become ingestion nodes."""
    seen_modalities = set()
    usable = []
    for entry in sensors:
        transport = entry.get('transport', 'rtsp')
        if transport not in SUPPORTED_TRANSPORTS:
            print(f"skipping sensor '{entry.get('id')}': "
                  f"unsupported transport '{transport}' (only rtsp is implemented)")
            continue

        modality = entry['modality']
        if modality in seen_modalities:
            raise ValueError(
                f"duplicate modality '{modality}' in {config_path} - two sensors "
                f"would publish to the same /multisens/sensors/{modality}/image_raw topic")
        seen_modalities.add(modality)

        usable.append(entry)

    return usable
