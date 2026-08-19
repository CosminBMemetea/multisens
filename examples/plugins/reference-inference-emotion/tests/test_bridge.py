"""Exercises `EmotionBridgeConnector`'s full flow against a real local
HTTP server standing in for the inference worker - nearly a
byte-for-byte port of the sibling reference-inference package's own
test_bridge.py, since the two connectors share the exact same
architecture and only differ in field names/task/source_id suffix."""
import json
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from multisens_reference_inference_emotion.bridge import EmotionBridgeConnector
from multisens_sdk import ConnectorConfigError, ConnectorState
from multisens_sdk.testing import (
    assert_connector_lifecycle,
    assert_health_contract,
    assert_valid_plugin_descriptor,
)


def _make_fake_worker_handler(responses: dict) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            status, payload = responses.get(self.path, (404, {'error': 'not found'}))
            if payload is None:
                body = b'not json at all'
            else:
                body = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

    return Handler


@pytest.fixture
def fake_worker():
    responses: dict = {}
    server = HTTPServer(('127.0.0.1', 0), _make_fake_worker_handler(responses))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f'http://127.0.0.1:{port}', responses
    server.shutdown()
    thread.join(timeout=2)


def _valid_config(worker_url: str, **overrides) -> dict:
    config = {
        'session_id': 's1', 'sensor_id': 'emotion_demo_face_rgb', 'worker_url': worker_url, 'modality': 'rgb',
    }
    config.update(overrides)
    return config


# --- descriptor --------------------------------------------------------

def test_descriptor_is_valid():
    assert_valid_plugin_descriptor(EmotionBridgeConnector().descriptor())


# --- configure() validation ----------------------------------------------

@pytest.mark.parametrize('missing_key', ['session_id', 'sensor_id', 'worker_url', 'modality'])
def test_configure_rejects_missing_required_fields(missing_key):
    config = _valid_config('http://localhost:9200')
    del config[missing_key]
    connector = EmotionBridgeConnector()
    with pytest.raises(ConnectorConfigError, match=missing_key):
        connector.configure(config)


def test_configure_rejects_unsupported_modality_by_default():
    connector = EmotionBridgeConnector()
    with pytest.raises(ConnectorConfigError, match='supported_modalities'):
        connector.configure(_valid_config('http://localhost:9200', modality='thermal'))


def test_configure_allows_unsupported_modality_with_explicit_escape_hatch():
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config('http://localhost:9200', modality='thermal', allow_simulated_input=True))


def test_configure_rejects_invalid_timeout():
    connector = EmotionBridgeConnector()
    for bad_timeout in (-1, 0, 'not-a-number'):
        with pytest.raises(ConnectorConfigError, match='timeout_s'):
            connector.configure(_valid_config('http://localhost:9200', timeout_s=bad_timeout))


def test_configure_rejects_invalid_stale_after_s():
    connector = EmotionBridgeConnector()
    for bad_value in (-1, 0, 'not-a-number'):
        with pytest.raises(ConnectorConfigError, match='stale_after_s'):
            connector.configure(_valid_config('http://localhost:9200', stale_after_s=bad_value))


# --- lifecycle -------------------------------------------------------------

def test_full_lifecycle_via_contract_helper(fake_worker):
    worker_url, _responses = fake_worker
    connector = EmotionBridgeConnector()
    assert_connector_lifecycle(connector, configure=lambda: connector.configure(_valid_config(worker_url)))


def test_poll_before_configured_is_empty():
    connector = EmotionBridgeConnector()
    assert connector.poll() == []


def test_poll_before_started_is_empty(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 1000.0, 'detections': []})
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    assert connector.poll() == []


# --- poll() translation ----------------------------------------------------

def test_poll_translates_a_worker_response_into_a_prediction(fake_worker):
    worker_url, responses = fake_worker
    detections = [{'label': 'happiness', 'confidence': 0.85, 'bbox': {'x': 0.3, 'y': 0.2, 'width': 0.3, 'height': 0.4}}]
    responses['/latest'] = (200, {'sensor_id': 'emotion_demo_face_rgb', 'frame_timestamp_ms': 1500.0, 'detections': detections})

    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()
    predictions = connector.poll()

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction.session_id == 's1'
    assert prediction.sensor_ids == ['emotion_demo_face_rgb']
    assert prediction.source_id == 'emotion_demo_face_rgb.emotion_bridge'
    assert prediction.timestamp_ms == 1500.0
    assert prediction.task == 'facial_emotion'
    assert prediction.value == {'detections': detections}
    assert 's1' in prediction.id and 'emotion_demo_face_rgb' in prediction.id


def test_poll_uses_a_configured_task_override(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url, task='cabin_emotion_reference'))
    connector.start()
    predictions = connector.poll()
    assert predictions[0].task == 'cabin_emotion_reference'


def test_poll_deduplicates_the_same_frame_across_consecutive_polls(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 42.0, 'detections': []})
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()

    first = connector.poll()
    second = connector.poll()
    assert len(first) == 1
    assert second == []


def test_poll_emits_again_once_the_worker_advances_to_a_new_frame(fake_worker):
    worker_url, responses = fake_worker
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    first = connector.poll()
    responses['/latest'] = (200, {'frame_timestamp_ms': 2.0, 'detections': []})
    second = connector.poll()

    assert len(first) == 1 and len(second) == 1
    assert first[0].id != second[0].id


def test_prediction_id_includes_session_id_to_avoid_cross_session_collisions(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 99.0, 'detections': []})

    connector_a = EmotionBridgeConnector()
    connector_a.configure(_valid_config(worker_url, session_id='session-a'))
    connector_a.start()
    pred_a = connector_a.poll()[0]

    connector_b = EmotionBridgeConnector()
    connector_b.configure(_valid_config(worker_url, session_id='session-b'))
    connector_b.start()
    pred_b = connector_b.poll()[0]

    assert pred_a.id != pred_b.id


# --- error handling ---------------------------------------------------------

def test_poll_propagates_a_worker_down_error_deliberately_uncaught(fake_worker):
    worker_url, _responses = fake_worker
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config('http://127.0.0.1:1'))  # nothing listens here
    connector.start()
    with pytest.raises(urllib.error.URLError):
        connector.poll()


def test_poll_failure_is_reflected_in_this_plugins_own_health(fake_worker):
    worker_url, _responses = fake_worker
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config('http://127.0.0.1:1'))  # nothing listens here
    connector.start()

    with pytest.raises(urllib.error.URLError):
        connector.poll()

    health = connector.health()
    assert health.state == ConnectorState.DEGRADED
    assert health.message is not None


def test_poll_handles_a_malformed_worker_response_without_raising(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'detections': 'not-a-list'})
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()

    predictions = connector.poll()

    assert predictions == []
    health = connector.health()
    assert_health_contract(health)
    assert health.state == ConnectorState.DEGRADED
    assert health.message is not None


# --- health() ----------------------------------------------------------------

def test_health_reflects_last_sample_age_after_a_successful_poll(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()
    assert connector.health().last_sample_age_s is None  # no poll yet

    connector.poll()

    health = connector.health()
    assert_health_contract(health)
    assert health.state == ConnectorState.RUNNING
    assert health.last_sample_age_s is not None


def test_health_details_report_face_present_and_top_emotion(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {
        'frame_timestamp_ms': 1.0,
        'detections': [{'label': 'surprise', 'confidence': 0.72, 'bbox': {'x': 0, 'y': 0, 'width': 0.5, 'height': 0.5}}],
    })
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()
    connector.poll()

    details = connector.health().details
    assert details['face_present'] is True
    assert details['top_emotion'] == 'surprise'
    assert details['top_confidence'] == pytest.approx(0.72)


def test_health_details_report_no_face_when_detections_are_empty(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()
    connector.poll()

    details = connector.health().details
    assert details['face_present'] is False
    assert details['top_emotion'] is None
    assert details['top_confidence'] is None


# --- staleness ---------------------------------------------------------------

def test_health_stays_running_while_the_frame_keeps_advancing_within_the_threshold(fake_worker):
    worker_url, responses = fake_worker
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=5.0))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector.poll()
    responses['/latest'] = (200, {'frame_timestamp_ms': 2.0, 'detections': []})
    connector.poll()

    assert connector.health().state == ConnectorState.RUNNING


def test_health_reports_degraded_once_the_frame_stops_advancing_past_stale_after_s(fake_worker):
    worker_url, responses = fake_worker
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=0.05))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    first = connector.poll()
    assert len(first) == 1
    assert connector.health().state == ConnectorState.RUNNING

    time.sleep(0.1)
    second = connector.poll()
    assert second == []

    health = connector.health()
    assert_health_contract(health)
    assert health.state == ConnectorState.DEGRADED
    assert health.last_sample_age_s is not None and health.last_sample_age_s > 0.05
    assert 'no new frame' in health.message


def test_health_recovers_from_degraded_once_a_genuinely_new_frame_arrives(fake_worker):
    worker_url, responses = fake_worker
    connector = EmotionBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=0.05))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector.poll()
    time.sleep(0.1)
    connector.poll()
    assert connector.health().state == ConnectorState.DEGRADED

    responses['/latest'] = (200, {'frame_timestamp_ms': 2.0, 'detections': []})
    connector.poll()

    assert connector.health().state == ConnectorState.RUNNING
