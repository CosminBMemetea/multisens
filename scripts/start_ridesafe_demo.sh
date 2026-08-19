#!/usr/bin/env bash
# One-shot, idempotent RideSafe demo startup - checks each component
# before starting it, so re-running this after a partial start (or a
# fully-up demo) never creates duplicate/conflicting processes. Safe to
# run from a completely clean terminal, and safe to run again on top of
# an already-running demo (it just reports what's already up).
#
#     ./scripts/start_ridesafe_demo.sh
#
# To stop everything this script started: ./scripts/stop_ridesafe_demo.sh
set -u
cd "$(dirname "$0")/.."

echo "== mediamtx =="
if pgrep -x mediamtx >/dev/null; then
  echo "already running"
else
  nohup mediamtx > /tmp/mediamtx.log 2>&1 &
  disown
  sleep 1
  echo "started (pid $!)"
fi

echo "== RTSP replay (front+rear) =="
if [ -f /tmp/replay_ridesafe_rtsp.pid ] && kill -0 "$(cat /tmp/replay_ridesafe_rtsp.pid)" 2>/dev/null; then
  echo "already running (pid $(cat /tmp/replay_ridesafe_rtsp.pid))"
else
  nohup ./scripts/replay_ridesafe_rtsp.sh > /tmp/replay_supervisor.log 2>&1 &
  disown
  sleep 2
  echo "started"
fi

echo "== YOLO workers =="
start_worker() {
  local sensor_id=$1 rtsp_path=$2 port=$3
  if lsof -i ":$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "$sensor_id: already running on port $port"
    return
  fi
  (
    cd examples/plugins/reference-inference/worker
    nohup python3 -m yolo_worker --rtsp-url "rtsp://localhost:8554/$rtsp_path" \
      --sensor-id "$sensor_id" --port "$port" > "/tmp/yolo_worker_${rtsp_path}.log" 2>&1 &
    disown
  )
  echo "$sensor_id: started on port $port"
}
start_worker ridesafe_front_rgb ridesafe_front 9100
start_worker ridesafe_rear_rgb ridesafe_rear 9101
sleep 3

echo "== MultiSens (docker compose, RideSafe inference overlay) =="
# No --build by default - a full rebuild+recreate of all 3 containers is
# real, avoidable CPU/time cost on every run when nothing actually
# changed (found under real memory pressure during the RideSafe bring-up
# - see docs/limitations.md-style notes on this machine's 8GB ceiling).
# After changing backend/ros/frontend source, rerun with BUILD=1.
if [ "${BUILD:-0}" = "1" ]; then
  docker compose -f docker-compose.yml -f docker-compose.ridesafe.yml up -d --build
else
  docker compose -f docker-compose.yml -f docker-compose.ridesafe.yml up -d
fi
echo "waiting for backend..."
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "== Live-viewing session =="
# A single, stable, reused session for live viewing - not a fresh one
# every run, and never the real ridesafe-demo-001 evaluation record
# (that one stays completed; see docs/development.md).
SESSION_ID="ridesafe-live"
SESSION_STATUS=$(curl -s "http://localhost:8000/api/sessions/$SESSION_ID" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','__missing__'))" 2>/dev/null)
if [ "$SESSION_STATUS" = "__missing__" ] || [ -z "$SESSION_STATUS" ]; then
  curl -s -X POST http://localhost:8000/api/scenarios -H 'Content-Type: application/json' \
    -d '{"id":"ridesafe-live-sc","name":"RideSafe live viewing"}' > /dev/null
  curl -s -X POST http://localhost:8000/api/sessions -H 'Content-Type: application/json' \
    -d "{\"id\":\"$SESSION_ID\",\"name\":\"RideSafe live viewing\",\"scenario_id\":\"ridesafe-live-sc\"}" > /dev/null
  echo "session created"
fi
# A backend restart detaches inference from an already-'running' session
# (see docs/development.md) - starting is only a no-op if truly still
# attached, otherwise this is exactly what reattaches it.
curl -s -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start" > /dev/null
sleep 3
echo "inference-connectors:"
curl -s http://localhost:8000/api/inference-connectors | python3 -c "
import json,sys
for c in json.load(sys.stdin):
    print(f'  {c[\"connector_id\"]}: {c[\"state\"]}')
"

echo
echo "Done. Dashboard: http://localhost:8080"
