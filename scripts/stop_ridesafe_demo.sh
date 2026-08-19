#!/usr/bin/env bash
# Stops everything start_ridesafe_demo.sh starts. Leaves mediamtx running
# by default (shared, harmless idle process, and possibly something you
# also use outside this demo) - pass --all to stop it too.
set -u
cd "$(dirname "$0")/.."

echo "== MultiSens (docker compose) =="
docker compose -f docker-compose.yml -f docker-compose.ridesafe.yml down

echo "== YOLO workers =="
pkill -f 'yolo_worker' 2>/dev/null && echo "stopped" || echo "not running"

echo "== RTSP replay =="
if [ -f /tmp/replay_ridesafe_rtsp.pid ]; then
  PID=$(cat /tmp/replay_ridesafe_rtsp.pid)
  # Kills the whole process group the top-level script started, not just
  # that one PID - the front/rear supervisor loops and their current
  # ffmpeg children are separate processes that a plain `kill $PID`
  # would leave running (found the hard way during the RideSafe bring-up).
  pkill -P "$PID" 2>/dev/null
  kill "$PID" 2>/dev/null
  pkill -f 'ridesafe_front.mp4|ridesafe_rear.mp4' 2>/dev/null
  rm -f /tmp/replay_ridesafe_rtsp.pid
  echo "stopped"
else
  echo "not running"
fi

if [ "${1:-}" = "--all" ]; then
  echo "== mediamtx =="
  pkill -x mediamtx 2>/dev/null && echo "stopped" || echo "not running"
fi

echo
echo "Done."
