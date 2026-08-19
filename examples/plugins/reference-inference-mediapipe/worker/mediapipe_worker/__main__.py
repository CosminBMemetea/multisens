"""CLI entrypoint - `python -m mediapipe_worker --rtsp-url ... --sensor-id ...`.
Mirrors yolo_worker's/emotion_worker's own __main__.py, with `SharedState`/
`serve` imported directly from `multisens_worker_kit` (issue #141/#142) -
this package has no local state.py/server.py to import from instead.
See the package README for the full usage example against a real
config/sensors.yaml entry, and for the model download step (no bundled
default path - the `.tflite` model is never fetched automatically here).
"""
from __future__ import annotations

import argparse
import threading

from multisens_worker_kit.server import serve
from multisens_worker_kit.state import SharedState

from mediapipe_worker.capture import DEFAULT_TARGET_INFERENCE_FPS, log, run_capture_loop
from mediapipe_worker.detections import DEFAULT_CONFIDENCE_THRESHOLD


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Reference face-detection inference worker (MediaPipe Tasks API) - own process, '
                     'own RTSP reader, serves detections over a small local HTTP endpoint.',
    )
    parser.add_argument('--rtsp-url', required=True, help="the sensor's RTSP URL")
    parser.add_argument('--sensor-id', required=True, help='reported in /latest and /health - matches a config/sensors.yaml entry id')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9400)
    parser.add_argument('--model', required=True, help='path to the blaze_face_short_range.tflite model - see README.md for the download command')
    parser.add_argument('--confidence-threshold', type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument(
        '--target-inference-fps', type=float, default=DEFAULT_TARGET_INFERENCE_FPS,
        help='caps the face-detect rate - 0 disables the cap',
    )
    args = parser.parse_args()

    worker_id = f'mediapipe-worker:{args.sensor_id}'

    state = SharedState(sensor_id=args.sensor_id)
    stop_event = threading.Event()
    capture_thread = threading.Thread(
        target=run_capture_loop,
        kwargs=dict(
            rtsp_url=args.rtsp_url, state=state, worker_id=worker_id, sensor_id=args.sensor_id,
            model_path=args.model, confidence_threshold=args.confidence_threshold,
            target_inference_fps=args.target_inference_fps, stop_event=stop_event,
        ),
        daemon=True,
    )
    capture_thread.start()

    server = serve(state, args.host, args.port)
    log('info', 'startup', worker_id=worker_id, sensor_id=args.sensor_id, model=args.model,
        rtsp_url=args.rtsp_url, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()


if __name__ == '__main__':
    main()
