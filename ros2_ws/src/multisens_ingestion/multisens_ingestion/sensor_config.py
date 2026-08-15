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
    duplicate id (which would silently collide on the same topic - topics
    are keyed by id, not modality, since v1.0-RC issue #121; two sensors
    sharing one modality, e.g. two RGB cameras, is explicitly legal).
    Returns the entries that should actually become ingestion nodes.

    Also raises if a declared `derived_from_sensor_id` (v1.0-RC issue
    #124 - e.g. a simulated thermal/depth feed derived from one real
    webcam) names an id that isn't itself declared anywhere in this same
    config - a plugin-free config typo here would otherwise render as a
    silently false provenance claim on the dashboard rather than a
    startup error."""
    all_ids = {entry['id'] for entry in sensors}
    seen_ids = set()
    usable = []
    for entry in sensors:
        transport = entry.get('transport', 'rtsp')
        if transport not in SUPPORTED_TRANSPORTS:
            print(f"skipping sensor '{entry.get('id')}': "
                  f"unsupported transport '{transport}' (only rtsp is implemented)")
            continue

        sensor_id = entry['id']
        if sensor_id in seen_ids:
            raise ValueError(
                f"duplicate sensor id '{sensor_id}' in {config_path} - two sensors "
                f"would publish to the same /multisens/sensors/{sensor_id}/image_raw topic")
        seen_ids.add(sensor_id)

        derived_from = entry.get('derived_from_sensor_id')
        if derived_from and derived_from not in all_ids:
            raise ValueError(
                f"sensor '{sensor_id}' in {config_path} declares "
                f"derived_from_sensor_id '{derived_from}', which is not itself a "
                f"declared sensor id - this would be a false provenance claim")

        usable.append(entry)

    return usable
