from datetime import datetime, timezone

import pytest

from app.domain.models import EvaluationResult, GroundTruth, Prediction, Scenario, Session
from app.persistence import db, repository as repo


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / 'test.db'))
    yield connection
    connection.close()


def test_migration_is_idempotent(conn):
    before = [row[0] for row in conn.execute('SELECT version FROM schema_migrations')]
    db.migrate(conn)  # already applied once inside db.connect(); must not error or reapply
    after = [row[0] for row in conn.execute('SELECT version FROM schema_migrations')]
    assert after == before
    assert len(after) == len(set(after))  # no version applied twice
    assert after == sorted(after)


def test_scenario_round_trip(conn):
    scenario = Scenario(id='sc1', name='Normal illumination', tags=['indoor', 'demo'])
    repo.create_scenario(conn, scenario)
    fetched = repo.get_scenario(conn, 'sc1')
    assert fetched == scenario
    assert repo.list_scenarios(conn) == [scenario]


def test_get_scenario_missing_returns_none(conn):
    assert repo.get_scenario(conn, 'nope') is None


def test_session_round_trip_with_defaults(conn):
    repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
    started = _now()
    session = Session(id='s1', name='Demo session', scenario_id='sc1', started_at=started)
    repo.create_session(conn, session)

    fetched = repo.get_session(conn, 's1')
    assert fetched.status == 'created'
    assert fetched.ended_at is None
    assert fetched.started_at == started


def test_session_status_update_sets_ended_at(conn):
    repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
    repo.create_session(conn, Session(id='s1', name='demo', scenario_id='sc1', started_at=_now()))

    repo.update_session_status(conn, 's1', 'running')
    assert repo.get_session(conn, 's1').status == 'running'

    end = _now()
    repo.update_session_status(conn, 's1', 'completed', ended_at=end)
    fetched = repo.get_session(conn, 's1')
    assert fetched.status == 'completed'
    assert fetched.ended_at == end


def test_ground_truth_batch_insert_and_list_ordered_by_timestamp(conn):
    repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
    repo.create_session(conn, Session(id='s1', name='demo', scenario_id='sc1', started_at=_now()))

    items = [
        GroundTruth(id='g2', session_id='s1', timestamp_ms=200.0, task='presence', value={'label': 'present'}),
        GroundTruth(id='g1', session_id='s1', timestamp_ms=100.0, task='presence', value={'label': 'absent'}),
    ]
    repo.insert_ground_truth_batch(conn, items)

    fetched = repo.list_ground_truth(conn, 's1')
    assert [gt.id for gt in fetched] == ['g1', 'g2']
    assert fetched[0].value == {'label': 'absent'}


def test_predictions_batch_insert_and_filter_by_configuration_id(conn):
    repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
    repo.create_session(conn, Session(id='s1', name='demo', scenario_id='sc1', started_at=_now()))

    rgb_pred = Prediction(
        id='p1', session_id='s1', timestamp_ms=100.0, source_id='rgb_detector',
        sensor_ids=['rgb'], task='presence', value={'label': 'present'}, confidence=0.9,
    )
    depth_pred = Prediction(
        id='p2', session_id='s1', timestamp_ms=100.0, source_id='depth_detector',
        sensor_ids=['depth'], task='presence', value={'label': 'present'},
    )
    repo.insert_predictions_batch(conn, [rgb_pred, depth_pred])

    all_preds = repo.list_predictions(conn, 's1')
    assert len(all_preds) == 2

    rgb_only = repo.list_predictions(conn, 's1', configuration_id='cfg-rgb')
    assert [p.id for p in rgb_only] == ['p1']
    assert rgb_only[0].confidence == 0.9

    depth_only = repo.list_predictions(conn, 's1', configuration_id='cfg-depth')
    assert depth_only[0].confidence is None


def test_evaluation_result_upsert_overwrites_not_duplicates(conn):
    repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
    repo.create_session(conn, Session(id='s1', name='demo', scenario_id='sc1', started_at=_now()))

    first = EvaluationResult(
        id='e1', session_id='s1', configuration_id='cfg-rgb', task='presence',
        tolerance_ms=100.0, sample_count=10, matched_samples=10, unmatched_predictions=0,
        unmatched_ground_truth=0, metrics={'accuracy': 0.5}, computed_at=_now(),
    )
    repo.upsert_evaluation_result(conn, first)

    second = EvaluationResult(
        id='e2', session_id='s1', configuration_id='cfg-rgb', task='presence',
        tolerance_ms=100.0, sample_count=20, matched_samples=20, unmatched_predictions=1,
        unmatched_ground_truth=2, metrics={'accuracy': 0.9}, computed_at=_now(),
    )
    repo.upsert_evaluation_result(conn, second)

    results = repo.list_evaluation_results(conn, 's1')
    assert len(results) == 1  # overwritten, not appended
    assert results[0].metrics['accuracy'] == 0.9
    assert results[0].sample_count == 20


def test_evaluation_result_na_metric_round_trips_as_none(conn):
    repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
    repo.create_session(conn, Session(id='s1', name='demo', scenario_id='sc1', started_at=_now()))

    result = EvaluationResult(
        id='e1', session_id='s1', configuration_id='cfg-rgb', task='presence',
        tolerance_ms=100.0, sample_count=0, matched_samples=0, unmatched_predictions=0,
        unmatched_ground_truth=0, metrics={'accuracy': None}, computed_at=_now(),
    )
    repo.upsert_evaluation_result(conn, result)

    fetched = repo.get_evaluation_result(conn, 's1', 'cfg-rgb', 'presence')
    assert fetched.metrics['accuracy'] is None
    assert fetched.tolerance_ms == 100.0


def test_data_persists_across_reconnect(tmp_path):
    db_path = str(tmp_path / 'restart.db')

    conn1 = db.connect(db_path)
    repo.create_scenario(conn1, Scenario(id='sc1', name='demo'))
    repo.create_session(conn1, Session(id='s1', name='demo', scenario_id='sc1', started_at=_now()))
    conn1.close()  # simulates a container restart: connection gone, file remains

    conn2 = db.connect(db_path)
    try:
        assert repo.get_scenario(conn2, 'sc1') is not None
        assert repo.get_session(conn2, 's1') is not None
    finally:
        conn2.close()
