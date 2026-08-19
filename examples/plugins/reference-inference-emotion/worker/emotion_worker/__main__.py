"""CLI entrypoint - `python -m emotion_worker --rtsp-url ... --sensor-id ...`.
Mirrors yolo_worker's own __main__.py exactly. See the package README
for the full usage example against a real config/sensors.yaml entry.
"""
from __future__ import annotations

import argparse
import threading
from pathlib import Path

from emotion_worker.capture import DEFAULT_TARGET_INFERENCE_FPS, run_capture_loop
from emotion_worker.detections import DEFAULT_CONFIDENCE_THRESHOLD
from emotion_worker.log import log
from emotion_worker.server import serve
from emotion_worker.state import SharedState

DEFAULT_MODEL_PATH = str(Path(__file__).parent / 'model' / 'emotion-ferplus-8.onnx')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Reference emotion-classification inference worker - own process, own RTSP reader, '
                     'serves detections over a small local HTTP endpoint. Not a driver-monitoring system, '
                     'not an NCAP/DMS compliance claim - a pretrained model classification for architecture '
                     'demonstration only.',
    )
    parser.add_argument('--rtsp-url', required=True, help="the sensor's RTSP URL")
    parser.add_argument('--sensor-id', required=True, help='reported in /latest and /health - matches a config/sensors.yaml entry id')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9200)
    parser.add_argument('--model', default=DEFAULT_MODEL_PATH, help='path to the emotion-ferplus ONNX model')
    parser.add_argument('--confidence-threshold', type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument(
        '--target-inference-fps', type=float, default=DEFAULT_TARGET_INFERENCE_FPS,
        help='caps face-detect+classify rate - this pipeline is fast enough to nearly keep up with '
             'a 30fps source unthrottled, driving ~300%% CPU measured live; 0 disables the cap',
    )
    args = parser.parse_args()

    worker_id = f'emotion-worker:{args.sensor_id}'

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
