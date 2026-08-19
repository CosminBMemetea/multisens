"""An inference worker's small local HTTP endpoint - stdlib `http.server`
only, no web framework dependency, since this never needs to be more
than `GET /latest` and `GET /health`. Deliberately never imports
anything model-specific (no cv2/onnxruntime/ultralytics) - this module,
and its tests, work with only `state.py` and the standard library.

Extracted from the reference YOLO/emotion workers (issue #141) - see
`state.py`'s own docstring for why the prior "duplicated on purpose"
decision was reversed. This IS the "one generic worker protocol" a
third/fourth worker gets for free: `GET /latest` -> `{sensor_id,
frame_timestamp_ms, detections}`, `GET /health` -> `{status, sensor_id,
frames_processed, last_frame_age_s, last_error}`.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from multisens_worker_kit.state import SharedState, build_health_payload, build_latest_payload


def make_handler(state: SharedState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's own naming
            if self.path == '/latest':
                self._respond_json(200, build_latest_payload(state.snapshot()))
            elif self.path == '/health':
                self._respond_json(200, build_health_payload(state.snapshot()))
            else:
                self._respond_json(404, {'error': f"unknown path '{self.path}'"})

        def _respond_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib's own signature
            pass  # quiet by default - frames_processed/health already show liveness

    return Handler


def serve(state: SharedState, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(state))
    return server
