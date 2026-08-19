#!/usr/bin/env python3
"""Emotion demo: controlled evaluation sampling, kept explicitly separate
from live inference frequency - same discipline as
scripts/ridesafe_evaluation_sampler.py, adapted for a multi-class (not
present/absent) task and, since issue #139, more than one source.

Once every `--interval-s` seconds (default 2.0), for every entry in
SOURCES (RGB and simulated depth, each its own emotion_worker instance):

1. Grabs one real JPEG snapshot from that sensor's own live MJPEG relay
   (a registered, session-associated source).
2. Reads that source's worker `/latest` for its current top-1
   classification and real `frame_timestamp_ms`.
3. Derives an `emotion_classification` Prediction (the model's own top-1
   label, or "no_face" if none was detected - a real, distinct outcome,
   not silently dropped) stamped with that source's own frame timestamp,
   and POSTs it to `/api/sessions/{session_id}/predictions/batch`.

One GT sample (authored from the RGB snapshot - the same real face,
whichever source is being judged) is later matched against every
source's Prediction independently by Evidence Playback, which is what
turns this into an actual RGB-vs-depth comparison rather than two
unrelated single-source runs.

The saved snapshot's filename embeds the exact frame_timestamp_ms, so GT
authoring later labels the exact same frame the RGB prediction used.

    python3 scripts/emotion_evaluation_sampler.py \\
      --session-id emotion-demo-003 --duration-s 40 --interval-s 2.0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = [
    {'sensor_id': 'emotion_demo_face_rgb', 'worker_url': 'http://localhost:9200'},
    {'sensor_id': 'emotion_demo_face_depth', 'worker_url': 'http://localhost:9201'},
]
# GT is always authored from the RGB snapshot - it's the only source
# showing the actual, undistorted face.
GT_SOURCE_SENSOR_ID = 'emotion_demo_face_rgb'
SAMPLES_DIR = Path(__file__).parent.parent / 'data' / 'recorded' / 'emotion-demo' / 'samples'


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


def sample_source(backend_url: str, session_id: str, tick_index: int, sensor_id: str, worker_url: str) -> None:
    try:
        latest = _get_json(f'{worker_url}/latest')
    except Exception as e:
        print(f'  {sensor_id}: worker unreachable ({e}) - skipped this tick')
        return

    frame_timestamp_ms = latest.get('frame_timestamp_ms')
    detections = latest.get('detections') or []
    if frame_timestamp_ms is None:
        print(f'  {sensor_id}: worker has no frame yet - skipped this tick')
        return

    snapshot_path = SAMPLES_DIR / f'{sensor_id}_{tick_index:03d}_{int(frame_timestamp_ms)}.jpg'
    mjpeg_url = f'{backend_url}/api/sensors/{sensor_id}/stream.mjpeg'
    got_snapshot = _grab_snapshot(mjpeg_url, snapshot_path)

    top = detections[0] if detections else None
    label = top['label'] if top else 'no_face'
    confidence = top['confidence'] if top else None

    prediction = {
        'timestamp_ms': frame_timestamp_ms,
        'source_id': f'{sensor_id}.emotion_presence_sampler',
        'sensor_ids': [sensor_id],
        'task': 'emotion_classification',
        'value': {'label': label},
        'confidence': confidence,
        'metadata': {
            'snapshot_path': str(snapshot_path.relative_to(SAMPLES_DIR.parent.parent.parent)) if got_snapshot else None,
            'sample_tick': tick_index,
        },
    }
    print(f'  {sensor_id}: {label} (conf={confidence}) snapshot={"ok" if got_snapshot else "FAILED"}')

    status, resp = _post_json(f'{backend_url}/api/sessions/{session_id}/predictions/batch', {'items': [prediction]})
    if status != 201 or resp.get('rejected', 0) > 0:
        print(f'  WARNING: batch ingest status={status} resp={resp}')


def sample_once(backend_url: str, session_id: str, tick_index: int) -> None:
    for source in SOURCES:
        sample_source(backend_url, session_id, tick_index, source['sensor_id'], source['worker_url'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--duration-s', type=float, default=40.0)
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

    print(f'\nDone: {tick_index} ticks sampled over {elapsed:.0f}s.')


if __name__ == '__main__':
    main()
