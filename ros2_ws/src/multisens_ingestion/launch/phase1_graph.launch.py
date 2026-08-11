"""Phase 1 launch: boots a minimal two-node graph to validate the ROS
runtime, launch mechanism, and DDS discovery. No RTSP ingestion yet."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='multisens_ingestion',
            executable='placeholder_talker',
            name='placeholder_talker',
            output='screen',
        ),
        Node(
            package='multisens_ingestion',
            executable='placeholder_listener',
            name='placeholder_listener',
            output='screen',
        ),
    ])
