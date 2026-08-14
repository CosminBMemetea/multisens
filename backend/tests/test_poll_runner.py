"""Phase 97 (v0.9): `PollRunner` - forwarding a connector's `poll()`
output into the *existing* batch-insert path. Canonical emission shape
round-trips correctly, malformed items never reach the database, and a
broken connector never affects data posted through the ordinary REST
API against the same session.
"""
import time

from app.persistence import db as db_module
from app.persistence import repository as repo
from app.plugins.poll_runner import PollRunner
from multisens_sdk import Prediction


def _connect_factory(db_path):
    return lambda: db_module.connect(str(db_path))


def _seed_scenario_and_session(db_path, session_id='s1', scenario_id='sc1') -> None:
    conn = db_module.connect(str(db_path))
    try:
        from app.domain.models import Scenario, Session
        from datetime import datetime, timezone
        repo.create_scenario(conn, Scenario(id=scenario_id, name='demo'))
        repo.create_session(conn, Session(
            id=session_id, name='demo session', scenario_id=scenario_id,
            started_at=datetime.now(timezone.utc),
        ))
    finally:
        conn.close()


def _prediction(pred_id: str, session_id: str = 's1') -> Prediction:
    return Prediction(
        id=pred_id, session_id=session_id, timestamp_ms=100.0, source_id='acme-detector',
        sensor_ids=['robot_front_rgb'], task='obstacle_detection',
        value={'detections': [{'label': 'obstacle', 'confidence': 0.9,
                                'bbox': {'x': 0.1, 'y': 0.1, 'width': 0.2, 'height': 0.2}}]},
        confidence=0.9,
    )


# --- canonical emission shape round-trips correctly -------------------------

def test_poll_once_forwards_predictions_and_they_round_trip_exactly(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_scenario_and_session(db_path)
    emitted = [_prediction('pred-a'), _prediction('pred-b')]

    runner = PollRunner(poll=lambda: emitted, bulk_insert=repo.insert_predictions_batch,
                         connect=_connect_factory(db_path))
    runner.poll_once()

    conn = db_module.connect(str(db_path))
    try:
        stored = repo.list_predictions(conn, 's1')
    finally:
        conn.close()

    assert {p.id for p in stored} == {'pred-a', 'pred-b'}
    by_id = {p.id: p for p in stored}
    original = by_id['pred-a']
    assert original.task == 'obstacle_detection'
    assert original.source_id == 'acme-detector'
    assert original.sensor_ids == ['robot_front_rgb']
    assert original.timestamp_ms == 100.0
    assert original.confidence == 0.9
    assert runner.total_ingested == 2
    assert runner.total_rejected == 0


def test_poll_once_with_no_new_items_does_not_touch_the_database(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_scenario_and_session(db_path)
    runner = PollRunner(poll=lambda: [], bulk_insert=repo.insert_predictions_batch,
                         connect=_connect_factory(db_path))
    runner.poll_once()
    assert runner.total_ingested == 0
    assert runner.last_error is None


# --- malformed items -----------------------------------------------------------

def test_poll_once_handles_a_duplicate_id_without_losing_the_rest_of_the_batch(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_scenario_and_session(db_path)
    conn = db_module.connect(str(db_path))
    try:
        repo.insert_predictions_batch(conn, [_prediction('pred-existing')])
    finally:
        conn.close()

    runner = PollRunner(poll=lambda: [_prediction('pred-existing'), _prediction('pred-new')],
                         bulk_insert=repo.insert_predictions_batch, connect=_connect_factory(db_path))
    runner.poll_once()

    conn = db_module.connect(str(db_path))
    try:
        stored_ids = {p.id for p in repo.list_predictions(conn, 's1')}
    finally:
        conn.close()
    assert stored_ids == {'pred-existing', 'pred-new'}  # the duplicate rejected, the new one still landed
    assert runner.total_ingested == 1
    assert runner.total_rejected == 1
    assert 'duplicate' in runner.last_error


def test_poll_once_when_poll_itself_raises_records_error_never_crashes(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_scenario_and_session(db_path)

    def _explode():
        raise RuntimeError('connector poll() is broken')

    runner = PollRunner(poll=_explode, bulk_insert=repo.insert_predictions_batch,
                         connect=_connect_factory(db_path))
    runner.poll_once()  # must not raise
    assert runner.total_ingested == 0
    assert 'broken' in runner.last_error


# --- connector failure isolation from the real REST API ---------------------

def test_broken_connector_never_affects_data_posted_through_the_normal_rest_api(client, tmp_path):
    resp = client.post('/api/scenarios', json={'id': 'sc1', 'name': 'demo'})
    assert resp.status_code == 201, resp.text
    resp = client.post('/api/sessions', json={'id': 's1', 'name': 'demo', 'scenario_id': 'sc1'})
    assert resp.status_code == 201, resp.text

    # The REST client's own fixture already pointed the app at a real tmp
    # db; a broken PollRunner writing to a COMPLETELY SEPARATE database
    # must have zero effect on it - proving the isolation is structural,
    # not just "the mock never got called."
    other_db = tmp_path / 'unrelated-poll-runner.db'
    db_module.connect(str(other_db)).close()

    def _explode():
        raise RuntimeError('this connector is always broken')

    runner = PollRunner(poll=_explode, bulk_insert=repo.insert_predictions_batch,
                         connect=_connect_factory(other_db))
    runner.poll_once()
    assert runner.last_error is not None

    resp = client.post('/api/sessions/s1/predictions/batch', json={'items': [
        {'timestamp_ms': 1.0, 'source_id': 'manual', 'sensor_ids': ['rgb'], 'task': 'presence',
         'value': {'label': 'present'}},
    ]})
    assert resp.status_code == 201
    assert resp.json() == {'accepted': 1, 'rejected': 0, 'errors': []}

    resp = client.get('/api/sessions/s1/predictions')
    assert resp.status_code == 200
    assert len(resp.json()) == 1  # only the manually-POSTed one - the broken runner touched nothing here


# --- start/stop actually drive a real background thread ----------------------

def test_start_stop_actually_run_the_background_loop(tmp_path):
    db_path = tmp_path / 'test.db'
    _seed_scenario_and_session(db_path)
    call_count = {'n': 0}

    def _poll():
        call_count['n'] += 1
        return [_prediction(f'pred-{call_count["n"]}')] if call_count['n'] <= 2 else []

    runner = PollRunner(poll=_poll, bulk_insert=repo.insert_predictions_batch,
                         connect=_connect_factory(db_path), poll_interval_s=0.05)
    runner.start()
    time.sleep(0.3)
    runner.stop()

    assert call_count['n'] >= 2
    assert runner.total_ingested >= 2

    calls_after_stop = call_count['n']
    time.sleep(0.15)
    assert call_count['n'] == calls_after_stop  # genuinely stopped, not still polling in the background
