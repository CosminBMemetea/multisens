"""The worker's small local HTTP endpoint - identical in shape to
yolo_worker's own server.py. stdlib `http.server` only, no web
framework dependency. Deliberately never imports `capture.py` (the only
module with cv2/onnxruntime dependencies), so this module - and its
tests - work with only `state.py` and the standard library.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from emotion_worker.state import SharedState, build_health_payload, build_latest_payload


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
