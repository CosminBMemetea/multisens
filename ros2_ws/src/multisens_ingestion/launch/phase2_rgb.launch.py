"""Phase 2: one real sensor. Parameters are launch-hardcoded here; Phase 3
replaces this with N nodes instantiated from config/sensors.yaml."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='multisens_ingestion',
            executable='rtsp_ingestion_node',
            name='rgb_ingestion',
            output='screen',
            parameters=[{
                'sensor_id': 'rgb',
                'modality': 'rgb',
                'source_type': 'physical',
                'rtsp_url': 'rtsp://host.docker.internal:8554/rgb',
            }],
        ),
    ])
