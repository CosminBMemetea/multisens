#!/usr/bin/env python3
"""RideSafe bring-up Phase 18/19: controlled evaluation sampling, kept
explicitly separate from live inference frequency (the live yolo_worker/
bridge pipeline keeps running at whatever rate it manages - ~2.3fps
measured - completely independently of this script).

Once every `--interval-s` seconds (default 2.0, matching the prior
one-shot RideSafe experiment this reproduces live), for each sensor:

1. Grabs one real JPEG snapshot from that sensor's own live MJPEG relay
   (`GET /api/sensors/{sensor_id}/stream.mjpeg`) - a registered,
   session-associated source, not arbitrary filesystem access (Phase 24
   will reuse these same files for Evidence Playback's frame evidence).
2. Reads that sensor's yolo_worker `/latest` for its current detections
   and real `frame_timestamp_ms`.
3. Derives a `vehicle_presence` classification Prediction ("present" iff
   the worker returned at least one detection - it already applied the
   confidence_threshold/class filter itself, no new threshold logic
   here) stamped with that same frame_timestamp_ms, and POSTs it to
   `/api/sessions/{session_id}/predictions/batch`.

The saved snapshot's filename embeds the exact frame_timestamp_ms, so a
human (or a later GT-authoring pass) can label it against the exact same
timestamp this prediction used - GT and prediction align on one real
frame, not a synthetic tick.

    python3 scripts/ridesafe_evaluation_sampler.py \\
      --session-id ridesafe-demo-001 --duration-s 98 --interval-s 2.0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

SENSORS = {
    'ridesafe_front_rgb': 'http://localhost:9100',
    'ridesafe_rear_rgb': 'http://localhost:9101',
}
SAMPLES_DIR = Path(__file__).parent.parent / 'data' / 'recorded' / 'ridesafe' / 'samples'


def _get_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _post_json(url: str, body: dict, timeout: float = 10.0) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _grab_snapshot(mjpeg_url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ['ffmpeg', '-y', '-i', mjpeg_url, '-frames:v', '1', '-q:v', '3', str(out_path)],
        capture_output=True, timeout=15,
    )
    return out_path.is_file() and out_path.stat().st_size > 0 and result.returncode in (0, 1)


def sample_once(backend_url: str, session_id: str, tick_index: int) -> None:
    items = []
    for sensor_id, worker_url in SENSORS.items():
        try:
            latest = _get_json(f'{worker_url}/latest')
        except Exception as e:
            print(f'  {sensor_id}: worker unreachable ({e}) - skipped this tick')
            continue

        frame_timestamp_ms = latest.get('frame_timestamp_ms')
        detections = latest.get('detections') or []
        if frame_timestamp_ms is None:
            print(f'  {sensor_id}: worker has no frame yet - skipped this tick')
            continue

        snapshot_path = SAMPLES_DIR / sensor_id / f'f_{tick_index:03d}_{int(frame_timestamp_ms)}.jpg'
        mjpeg_url = f'{backend_url}/api/sensors/{sensor_id}/stream.mjpeg'
        got_snapshot = _grab_snapshot(mjpeg_url, snapshot_path)

        present = len(detections) > 0
        top_confidence = max((d.get('confidence', 0.0) for d in detections), default=None)

        prediction = {
            'timestamp_ms': frame_timestamp_ms,
            'source_id': f'{sensor_id}.vehicle_presence_sampler',
            'sensor_ids': [sensor_id],
            'task': 'vehicle_presence',
            'value': {'label': 'present' if present else 'absent'},
            'confidence': top_confidence,
            'metadata': {
                'snapshot_path': str(snapshot_path.relative_to(SAMPLES_DIR.parent.parent.parent)) if got_snapshot else None,
                'raw_detection_count': len(detections),
                'sample_tick': tick_index,
            },
        }
        items.append(prediction)
        print(f'  {sensor_id}: {"present" if present else "absent"} '
              f'(conf={top_confidence}) snapshot={"ok" if got_snapshot else "FAILED"}')

    if items:
        status, resp = _post_json(f'{backend_url}/api/sessions/{session_id}/predictions/batch', {'items': items})
        if status != 201 or resp.get('rejected', 0) > 0:
            print(f'  WARNING: batch ingest status={status} resp={resp}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--duration-s', type=float, default=98.0)
    parser.add_argument('--interval-s', type=float, default=2.0)
    parser.add_argument('--backend-url', default='http://localhost:8000')
    args = parser.parse_args()

    tick_index = 0
    elapsed = 0.0
    next_tick_at = time.monotonic()
    while elapsed <= args.duration_s:
        print(f'--- tick {tick_index} (t+{elapsed:.0f}s) ---')
        sample_once(args.backend_url, args.session_id, tick_index)
        tick_index += 1
        next_tick_at += args.interval_s
        sleep_s = max(0.0, next_tick_at - time.monotonic())
        time.sleep(sleep_s)
        elapsed += args.interval_s

    print(f'\nDone: {tick_index} ticks sampled per sensor over {elapsed:.0f}s.')


if __name__ == '__main__':
    main()
