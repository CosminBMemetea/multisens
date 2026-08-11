#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
