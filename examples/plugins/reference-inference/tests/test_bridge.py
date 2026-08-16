"""Exercises `YoloBridgeConnector`'s full flow against a real local HTTP
server standing in for the inference worker (stdlib `http.server`, no
mocking of `urllib` internals) - the same "prefer a real dependency
over a mock" discipline other MultiSens test suites already follow
(e.g. `test_resource_collector_wiring.py`'s real temporary SQLite DB).
"""
import json
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from multisens_reference_inference.bridge import YoloBridgeConnector
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
    """A real local HTTP server standing in for the inference worker -
    `responses['/latest']` controls what `/latest` currently returns;
    test bodies mutate it directly between `poll()` calls."""
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
        'session_id': 's1', 'sensor_id': 'ridesafe_front_rgb', 'worker_url': worker_url, 'modality': 'rgb',
    }
    config.update(overrides)
    return config


# --- descriptor --------------------------------------------------------

def test_descriptor_is_valid():
    assert_valid_plugin_descriptor(YoloBridgeConnector().descriptor())


# --- configure() validation ----------------------------------------------

@pytest.mark.parametrize('missing_key', ['session_id', 'sensor_id', 'worker_url', 'modality'])
def test_configure_rejects_missing_required_fields(missing_key):
    config = _valid_config('http://localhost:9100')
    del config[missing_key]
    connector = YoloBridgeConnector()
    with pytest.raises(ConnectorConfigError, match=missing_key):
        connector.configure(config)


def test_configure_rejects_unsupported_modality_by_default():
    connector = YoloBridgeConnector()
    with pytest.raises(ConnectorConfigError, match='supported_modalities'):
        connector.configure(_valid_config('http://localhost:9100', modality='thermal'))


def test_configure_allows_unsupported_modality_with_explicit_escape_hatch():
    connector = YoloBridgeConnector()
    connector.configure(_valid_config('http://localhost:9100', modality='thermal', allow_simulated_input=True))
    # must not raise


def test_configure_rejects_invalid_timeout():
    connector = YoloBridgeConnector()
    for bad_timeout in (-1, 0, 'not-a-number'):
        with pytest.raises(ConnectorConfigError, match='timeout_s'):
            connector.configure(_valid_config('http://localhost:9100', timeout_s=bad_timeout))


def test_configure_rejects_invalid_stale_after_s():
    connector = YoloBridgeConnector()
    for bad_value in (-1, 0, 'not-a-number'):
        with pytest.raises(ConnectorConfigError, match='stale_after_s'):
            connector.configure(_valid_config('http://localhost:9100', stale_after_s=bad_value))


# --- lifecycle -------------------------------------------------------------

def test_full_lifecycle_via_contract_helper(fake_worker):
    worker_url, _responses = fake_worker
    connector = YoloBridgeConnector()
    assert_connector_lifecycle(connector, configure=lambda: connector.configure(_valid_config(worker_url)))


def test_poll_before_configured_is_empty():
    connector = YoloBridgeConnector()
    assert connector.poll() == []


def test_poll_before_started_is_empty(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 1000.0, 'detections': []})
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url))
    assert connector.poll() == []


# --- poll() translation ----------------------------------------------------

def test_poll_translates_a_worker_response_into_a_prediction(fake_worker):
    worker_url, responses = fake_worker
    detections = [{'label': 'car', 'confidence': 0.87, 'bbox': {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.15}}]
    responses['/latest'] = (200, {'sensor_id': 'ridesafe_front_rgb', 'frame_timestamp_ms': 1500.0, 'detections': detections})

    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()
    predictions = connector.poll()

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction.session_id == 's1'
    assert prediction.sensor_ids == ['ridesafe_front_rgb']
    assert prediction.source_id == 'ridesafe_front_rgb.yolo_bridge'
    assert prediction.timestamp_ms == 1500.0
    assert prediction.task == 'vehicle_detection'
    assert prediction.value == {'detections': detections}
    assert 's1' in prediction.id and 'ridesafe_front_rgb' in prediction.id


def test_poll_uses_a_configured_task_override(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url, task='front_scene_object_detection'))
    connector.start()
    # detections empty -> a Prediction with an empty detections list is still emitted (a
    # genuine "nothing detected this frame" observation, not the same as "no new frame").
    predictions = connector.poll()
    assert predictions[0].task == 'front_scene_object_detection'


def test_poll_deduplicates_the_same_frame_across_consecutive_polls(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 42.0, 'detections': []})
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()

    first = connector.poll()
    second = connector.poll()
    assert len(first) == 1
    assert second == []  # same frame_timestamp_ms - nothing new


def test_poll_emits_again_once_the_worker_advances_to_a_new_frame(fake_worker):
    worker_url, responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    first = connector.poll()
    responses['/latest'] = (200, {'frame_timestamp_ms': 2.0, 'detections': []})
    second = connector.poll()

    assert len(first) == 1 and len(second) == 1
    assert first[0].id != second[0].id


def test_prediction_id_includes_session_id_to_avoid_cross_session_collisions(fake_worker):
    # A recorded replay looping back to the same frame_timestamp_ms in a
    # *different* session must never collide with the first session's own
    # row - predictions.id is a single global primary key
    # (backend/app/persistence/migrations/0001_initial.sql), not scoped
    # per session.
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'frame_timestamp_ms': 99.0, 'detections': []})

    connector_a = YoloBridgeConnector()
    connector_a.configure(_valid_config(worker_url, session_id='session-a'))
    connector_a.start()
    pred_a = connector_a.poll()[0]

    connector_b = YoloBridgeConnector()
    connector_b.configure(_valid_config(worker_url, session_id='session-b'))
    connector_b.start()
    pred_b = connector_b.poll()[0]

    assert pred_a.id != pred_b.id


# --- error handling ---------------------------------------------------------

def test_poll_propagates_a_worker_down_error_deliberately_uncaught(fake_worker):
    # Per the module docstring: PredictionConnectorInstance._poll_raw()
    # already isolates any poll() exception - duplicating that guard here
    # would just be a second copy of it. This test proves the plugin
    # itself really does let it through rather than swallowing it.
    worker_url, _responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config('http://127.0.0.1:1'))  # nothing listens here
    connector.start()
    with pytest.raises(urllib.error.URLError):
        connector.poll()


def test_poll_failure_is_reflected_in_this_plugins_own_health(fake_worker):
    # v1.0-RC issue #126 (found live-verifying its own self-healing fix):
    # this plugin's own health() must independently reflect a poll()
    # failure, not just the core wrapper's tracked state - health() can
    # be called on a completely separate schedule from poll(), and
    # without this, a poll() failure followed by an unrelated health()
    # call used to silently report RUNNING again (this plugin's own
    # _last_error was never touched by a propagated exception), masking
    # the real, still-ongoing outage.
    worker_url, _responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config('http://127.0.0.1:1'))  # nothing listens here
    connector.start()

    with pytest.raises(urllib.error.URLError):
        connector.poll()

    health = connector.health()
    assert health.state == ConnectorState.DEGRADED
    assert health.message is not None


def test_poll_handles_a_malformed_worker_response_without_raising(fake_worker):
    worker_url, responses = fake_worker
    responses['/latest'] = (200, {'detections': 'not-a-list'})  # missing frame_timestamp_ms, wrong detections type
    connector = YoloBridgeConnector()
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
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url))
    connector.start()
    assert connector.health().last_sample_age_s is None  # no poll yet

    connector.poll()

    health = connector.health()
    assert_health_contract(health)
    assert health.state == ConnectorState.RUNNING
    assert health.last_sample_age_s is not None


# --- staleness (v1.0-RC, issue #127) ------------------------------------------

def test_health_stays_running_while_the_frame_keeps_advancing_within_the_threshold(fake_worker):
    worker_url, responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=5.0))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector.poll()
    responses['/latest'] = (200, {'frame_timestamp_ms': 2.0, 'detections': []})
    connector.poll()

    assert connector.health().state == ConnectorState.RUNNING


def test_health_reports_degraded_once_the_frame_stops_advancing_past_stale_after_s(fake_worker):
    # The core of issue #127: the worker keeps responding successfully
    # (poll() never raises, no exception ever reaches _poll_raw()), but
    # frame_timestamp_ms is stuck - a real, distinguishable-from-healthy
    # staleness that must surface as DEGRADED, not a silently-stale RUNNING.
    worker_url, responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=0.05))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    first = connector.poll()
    assert len(first) == 1
    assert connector.health().state == ConnectorState.RUNNING  # not stale yet

    time.sleep(0.1)
    second = connector.poll()  # same frame_timestamp_ms - poll() itself still succeeds, returns []
    assert second == []

    health = connector.health()
    assert_health_contract(health)
    assert health.state == ConnectorState.DEGRADED
    assert health.last_sample_age_s is not None and health.last_sample_age_s > 0.05
    assert 'no new frame' in health.message


def test_health_last_sample_age_s_tracks_frame_advance_not_poll_attempts(fake_worker):
    # Repeated poll() *attempts* against an unchanging frame must not
    # reset the staleness clock - only a genuine new frame_timestamp_ms
    # does. Otherwise a fast poll_interval_s could mask real staleness
    # indefinitely just by attempting often.
    worker_url, responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=0.05))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector.poll()
    time.sleep(0.03)
    connector.poll()  # same frame again - an attempt, not an advance
    time.sleep(0.03)
    connector.poll()  # still the same frame - total elapsed since the real advance now > 0.05s

    assert connector.health().state == ConnectorState.DEGRADED


def test_health_recovers_from_degraded_once_a_genuinely_new_frame_arrives(fake_worker):
    worker_url, responses = fake_worker
    connector = YoloBridgeConnector()
    connector.configure(_valid_config(worker_url, stale_after_s=0.05))
    connector.start()

    responses['/latest'] = (200, {'frame_timestamp_ms': 1.0, 'detections': []})
    connector.poll()
    time.sleep(0.1)
    connector.poll()
    assert connector.health().state == ConnectorState.DEGRADED

    responses['/latest'] = (200, {'frame_timestamp_ms': 2.0, 'detections': []})  # a genuine advance
    connector.poll()

    assert connector.health().state == ConnectorState.RUNNING
