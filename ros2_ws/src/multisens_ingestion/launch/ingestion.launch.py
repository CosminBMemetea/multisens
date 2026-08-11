"""Config-driven ingestion: reads config/sensors.yaml and instantiates one
rtsp_ingestion_node per entry. Adding a fourth sensor is a config change,
not a code or launch-file change.

Config path comes from MULTISENS_SENSORS_CONFIG (set by docker-compose,
default matches the volume mount target) rather than a launch argument,
because the sensor list has to be known before building the list of Node
actions this function returns - a launch argument's value isn't resolved
until launch execution, too late to decide how many nodes to create.

Config loading/validation lives in multisens_ingestion.sensor_config (a
plain module with no launch_ros/rclpy import) so it's testable without a
live ROS environment - see ros2_ws/src/multisens_ingestion/test/.
"""
import os

from launch import LaunchDescription
from launch_ros.actions import Node
from multisens_ingestion.sensor_config import DEFAULT_CONFIG_PATH, load_sensors_config, select_usable_sensors

# Every Node below gets respawn=True: rtsp_ingestion_node's own reconnect
# loop only covers its RTSP *connection* dying, not its OS process dying
# (crash, OOM-kill, `kill -9`). Found the gap in Phase 8 by actually killing
# one node's process directly - the other nodes kept running fine (proving
# launch doesn't cascade-fail), but the dead one just stayed dead forever
# with no code path to bring it back. respawn is ros2 launch's own answer to
# exactly this, standard mechanism instead of a hand-rolled supervisor.
RESPAWN_DELAY_SEC = 2.0


def _make_node(entry: dict) -> Node:
    sensor_id = entry['id']
    return Node(
        package='multisens_ingestion',
        executable='rtsp_ingestion_node',
        name=f'{sensor_id}_ingestion',
        output='screen',
        respawn=True,
        respawn_delay=RESPAWN_DELAY_SEC,
        parameters=[{
            'sensor_id': sensor_id,
            'modality': entry['modality'],
            'source_type': entry['source_type'],
            'rtsp_url': entry['url'],
            # -1.0 means "not configured" - diagnostics reports "unavailable"
            # rather than a guessed number.
            'expected_fps': float(entry.get('expected_fps', -1.0)),
        }],
    )


def _make_system_diagnostics_node() -> Node:
    return Node(
        package='multisens_diagnostics',
        executable='system_diagnostics_node',
        name='system_diagnostics',
        output='screen',
        respawn=True,
        respawn_delay=RESPAWN_DELAY_SEC,
    )


def _make_sync_status_node() -> Node:
    return Node(
        package='multisens_sync',
        executable='sync_status_node',
        name='sync_status',
        output='screen',
        respawn=True,
        respawn_delay=RESPAWN_DELAY_SEC,
    )


def generate_launch_description():
    config_path = os.environ.get('MULTISENS_SENSORS_CONFIG', DEFAULT_CONFIG_PATH)
    sensors = load_sensors_config(config_path)
    usable = select_usable_sensors(sensors, config_path)

    if not usable:
        raise RuntimeError(f'no usable sensors found in {config_path}')

    nodes = [_make_node(entry) for entry in usable]
    nodes.append(_make_system_diagnostics_node())
    nodes.append(_make_sync_status_node())

    return LaunchDescription(nodes)
