"""Pure-logic tests for state.py + server.py - zero dependency on cv2/
ultralytics/torch (server.py deliberately never imports capture.py, the
only module that needs those). Drives a real HTTP server on a random
local port and makes real GET requests - same "prefer a real dependency
over a mock" discipline the rest of this project's test suites use."""
import json
import threading
import urllib.error
import urllib.request

from yolo_worker.server import serve
from yolo_worker.state import SharedState, build_health_payload, build_latest_payload


# --- SharedState / payload builders (no network) ----------------------------

def test_snapshot_before_any_frame_reports_starting():
    state = SharedState(sensor_id='demo_rgb')
    snapshot = state.snapshot()
    assert snapshot.frame_timestamp_ms is None
    assert snapshot.detections == []
    assert build_health_payload(snapshot)['status'] == 'starting'


def test_record_frame_updates_the_snapshot():
    state = SharedState(sensor_id='demo_rgb')
    state.record_frame(123.0, [{'label': 'car', 'confidence': 0.9, 'bbox': {'x': 0, 'y': 0, 'width': 0.1, 'height': 0.1}}])
    snapshot = state.snapshot()
    assert snapshot.frame_timestamp_ms == 123.0
    assert snapshot.frames_processed == 1
    assert len(snapshot.detections) == 1
    latest_payload = build_latest_payload(snapshot)
    assert latest_payload == {'sensor_id': 'demo_rgb', 'frame_timestamp_ms': 123.0, 'detections': snapshot.detections}


def test_record_frame_clears_a_previously_recorded_error():
    state = SharedState(sensor_id='demo_rgb')
    state.record_error('transient RTSP hiccup')
    assert state.snapshot().last_error == 'transient RTSP hiccup'
    state.record_frame(1.0, [])
    assert state.snapshot().last_error is None


def test_health_payload_reports_ok_after_a_frame_and_a_nonnegative_age():
    state = SharedState(sensor_id='demo_rgb')
    state.record_frame(1.0, [])
    payload = build_health_payload(state.snapshot())
    assert payload['status'] == 'ok'
    assert payload['frames_processed'] == 1
    assert payload['last_frame_age_s'] >= 0.0


# --- the real HTTP server ----------------------------------------------------

def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_latest_endpoint_serves_the_current_snapshot():
    state = SharedState(sensor_id='demo_rgb')
    state.record_frame(42.0, [{'label': 'car', 'confidence': 0.8, 'bbox': {'x': 0, 'y': 0, 'width': 0.2, 'height': 0.2}}])
    server = serve(state, '127.0.0.1', 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _get_json(f'http://127.0.0.1:{port}/latest')
        assert status == 200
        assert payload['sensor_id'] == 'demo_rgb'
        assert payload['frame_timestamp_ms'] == 42.0
        assert payload['detections'][0]['label'] == 'car'
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_health_endpoint_serves_the_current_snapshot():
    state = SharedState(sensor_id='demo_rgb')
    server = serve(state, '127.0.0.1', 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _get_json(f'http://127.0.0.1:{port}/health')
        assert status == 200
        assert payload['status'] == 'starting'
        assert payload['sensor_id'] == 'demo_rgb'
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_unknown_path_returns_404():
    state = SharedState(sensor_id='demo_rgb')
    server = serve(state, '127.0.0.1', 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _payload = _get_json(f'http://127.0.0.1:{port}/nope')
        assert status == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)
