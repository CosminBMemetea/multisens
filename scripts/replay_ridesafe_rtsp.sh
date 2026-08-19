#!/usr/bin/env bash
# Loops both real 70mai recordings into mediamtx as RTSP sources
# (rtsp://localhost:8554/ridesafe_front, .../ridesafe_rear), restarting
# ffmpeg on any exit.
#
# Found empirically during the RideSafe bring-up (Phase 6 independence
# test): an unsupervised `ffmpeg -re -stream_loop -1 -c copy -f rtsp`
# can still exit on its own after a transient RTSP write failure -
# "Failed reading RTSP data: End of file" / "Broken pipe" seen here
# after ~73 minutes of otherwise-healthy streaming. `-stream_loop -1`
# only re-loops the *input* file; it does not reconnect the RTSP
# *output* once ffmpeg itself decides to exit. Requires mediamtx
# already running (`brew install mediamtx && mediamtx`).
set -u
cd "$(dirname "$0")/.."

# Guard against a second copy running concurrently (found the hard way,
# RideSafe bring-up: two supervisors both loop-restarting ffmpeg into the
# same RTSP paths silently fight each other - mediamtx accepts only one
# publisher per path, so the "losing" side just cycles exit/restart
# forever, and *neither* stream is actually stable). PID file, not just
# a "pgrep the script name" check, so a stale file left behind by a
# killed-not-exited process doesn't block a genuine restart.
LOCK_FILE="/tmp/replay_ridesafe_rtsp.pid"
if [ -f "$LOCK_FILE" ] && kill -0 "$(cat "$LOCK_FILE")" 2>/dev/null; then
  echo "already running as pid $(cat "$LOCK_FILE") - not starting a second copy." >&2
  echo "if you're sure it's not actually running, rm $LOCK_FILE and try again." >&2
  exit 1
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

replay() {
  local name=$1 file=$2
  while true; do
    ffmpeg -re -stream_loop -1 -i "$file" -c copy -f rtsp "rtsp://localhost:8554/$name" \
      >> "/tmp/ffmpeg_${name}.log" 2>&1
    echo "$(date): ffmpeg for $name exited, restarting in 1s" >> "/tmp/ffmpeg_${name}.log"
    sleep 1
  done
}

replay ridesafe_front data/recorded/ridesafe/processed/ridesafe_front.mp4 &
FRONT_PID=$!
replay ridesafe_rear data/recorded/ridesafe/processed/ridesafe_rear.mp4 &
REAR_PID=$!

echo "front supervisor pid: $FRONT_PID"
echo "rear supervisor pid: $REAR_PID"
wait
