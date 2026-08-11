#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
source /workspace/install/setup.bash
exec ros2 launch multisens_ingestion phase1_graph.launch.py
