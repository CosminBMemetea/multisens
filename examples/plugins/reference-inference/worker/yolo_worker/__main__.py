"""CLI entrypoint - `python -m yolo_worker --rtsp-url ... --sensor-id ...`.
See the package README for the full usage example against a real
`config/sensors.yaml` entry.
"""
from __future__ import annotations

import argparse
import threading

from yolo_worker.capture import run_capture_loop
from yolo_worker.detections import DEFAULT_CONFIDENCE_THRESHOLD
from yolo_worker.log import log
from yolo_worker.server import serve
from yolo_worker.state import SharedState


def main() -> None:
    parser = argparse.ArgumentParser(
        description='v1.0-RC reference YOLOv8n inference worker (issue #123) - '
                     'own process, own RTSP reader, serves detections over a small local HTTP endpoint.',
    )
    parser.add_argument('--rtsp-url', required=True, help="the sensor's RTSP URL (same source the ROS ingestion node reads)")
    parser.add_argument('--sensor-id', required=True, help='reported in /latest and /health - matches a config/sensors.yaml entry id')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9100)
    parser.add_argument('--model', default='yolov8n.pt')
    parser.add_argument('--confidence-threshold', type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    args = parser.parse_args()

    # One worker per sensor (Phase 8 decision) - derived, not a separate
    # flag, since there's currently no case where the two would differ.
    worker_id = f'yolo-worker:{args.sensor_id}'

    state = SharedState(sensor_id=args.sensor_id)
    stop_event = threading.Event()
    capture_thread = threading.Thread(
        target=run_capture_loop,
        kwargs=dict(
            rtsp_url=args.rtsp_url, state=state, worker_id=worker_id, sensor_id=args.sensor_id,
            model_path=args.model, confidence_threshold=args.confidence_threshold, stop_event=stop_event,
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
