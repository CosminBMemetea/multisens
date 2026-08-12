"""Repository boundary: the only module (besides db.py) that touches
sqlite3. Every function takes/returns app.domain.models types, never a raw
row or dict - callers (API handlers, the metric engine) never see SQL.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.domain.models import EvaluationResult, GroundTruth, Prediction, Scenario, Session, SessionStatus


# --- scenarios ---------------------------------------------------------

def create_scenario(conn: sqlite3.Connection, scenario: Scenario) -> None:
    conn.execute(
        'INSERT INTO scenarios (id, name, description, tags, metadata) VALUES (?, ?, ?, ?, ?)',
        (scenario.id, scenario.name, scenario.description,
         json.dumps(scenario.tags), json.dumps(scenario.metadata)),
    )
    conn.commit()


def get_scenario(conn: sqlite3.Connection, scenario_id: str) -> Scenario | None:
    row = conn.execute('SELECT * FROM scenarios WHERE id = ?', (scenario_id,)).fetchone()
    return _row_to_scenario(row) if row else None


def list_scenarios(conn: sqlite3.Connection) -> list[Scenario]:
    rows = conn.execute('SELECT * FROM scenarios ORDER BY id').fetchall()
    return [_row_to_scenario(row) for row in rows]


def _row_to_scenario(row: sqlite3.Row) -> Scenario:
    return Scenario(
        id=row['id'], name=row['name'], description=row['description'],
        tags=json.loads(row['tags']), metadata=json.loads(row['metadata']),
    )


# --- sessions ------------------------------------------------------------

def create_session(conn: sqlite3.Connection, session: Session) -> None:
    conn.execute(
        'INSERT INTO sessions (id, name, scenario_id, started_at, ended_at, status, metadata) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (session.id, session.name, session.scenario_id, session.started_at.isoformat(),
         session.ended_at.isoformat() if session.ended_at else None,
         session.status, json.dumps(session.metadata)),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, session_id: str) -> Session | None:
    row = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    return _row_to_session(row) if row else None


def list_sessions(conn: sqlite3.Connection) -> list[Session]:
    rows = conn.execute('SELECT * FROM sessions ORDER BY started_at').fetchall()
    return [_row_to_session(row) for row in rows]


def update_session_status(
    conn: sqlite3.Connection, session_id: str, status: SessionStatus, ended_at: datetime | None = None,
) -> None:
    conn.execute(
        'UPDATE sessions SET status = ?, ended_at = ? WHERE id = ?',
        (status, ended_at.isoformat() if ended_at else None, session_id),
    )
    conn.commit()


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row['id'], name=row['name'], scenario_id=row['scenario_id'],
        started_at=datetime.fromisoformat(row['started_at']),
        ended_at=datetime.fromisoformat(row['ended_at']) if row['ended_at'] else None,
        status=row['status'], metadata=json.loads(row['metadata']),
    )


# --- ground truth / predictions ------------------------------------------

def insert_ground_truth_batch(conn: sqlite3.Connection, items: list[GroundTruth]) -> None:
    conn.executemany(
        'INSERT INTO ground_truth (id, session_id, timestamp_ms, task, value, metadata) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        [(gt.id, gt.session_id, gt.timestamp_ms, gt.task,
          json.dumps(gt.value), json.dumps(gt.metadata)) for gt in items],
    )
    conn.commit()


def list_ground_truth(conn: sqlite3.Connection, session_id: str, task: str | None = None) -> list[GroundTruth]:
    if task is None:
        rows = conn.execute(
            'SELECT * FROM ground_truth WHERE session_id = ? ORDER BY timestamp_ms', (session_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM ground_truth WHERE session_id = ? AND task = ? ORDER BY timestamp_ms',
            (session_id, task),
        ).fetchall()
    return [_row_to_ground_truth(row) for row in rows]


def _row_to_ground_truth(row: sqlite3.Row) -> GroundTruth:
    return GroundTruth(
        id=row['id'], session_id=row['session_id'], timestamp_ms=row['timestamp_ms'],
        task=row['task'], value=json.loads(row['value']), metadata=json.loads(row['metadata']),
    )


def insert_predictions_batch(conn: sqlite3.Connection, items: list[Prediction]) -> None:
    conn.executemany(
        'INSERT INTO predictions '
        '(id, session_id, timestamp_ms, source_id, sensor_ids, configuration_id, task, '
        'value, confidence, latency_ms, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [(p.id, p.session_id, p.timestamp_ms, p.source_id, json.dumps(p.sensor_ids),
          p.configuration_id, p.task, json.dumps(p.value), p.confidence, p.latency_ms,
          json.dumps(p.metadata)) for p in items],
    )
    conn.commit()


def list_predictions(
    conn: sqlite3.Connection, session_id: str,
    configuration_id: str | None = None, task: str | None = None,
) -> list[Prediction]:
    query = 'SELECT * FROM predictions WHERE session_id = ?'
    params: list[str] = [session_id]
    if configuration_id is not None:
        query += ' AND configuration_id = ?'
        params.append(configuration_id)
    if task is not None:
        query += ' AND task = ?'
        params.append(task)
    query += ' ORDER BY timestamp_ms'
    rows = conn.execute(query, params).fetchall()
    return [_row_to_prediction(row) for row in rows]


def _row_to_prediction(row: sqlite3.Row) -> Prediction:
    return Prediction(
        id=row['id'], session_id=row['session_id'], timestamp_ms=row['timestamp_ms'],
        source_id=row['source_id'], sensor_ids=json.loads(row['sensor_ids']),
        configuration_id=row['configuration_id'], task=row['task'],
        value=json.loads(row['value']), confidence=row['confidence'], latency_ms=row['latency_ms'],
        metadata=json.loads(row['metadata']),
    )


# --- evaluation results ---------------------------------------------------

def upsert_evaluation_result(conn: sqlite3.Connection, result: EvaluationResult) -> None:
    """INSERT OR REPLACE keyed on (session_id, configuration_id, task) - a
    second evaluate() call for the same combination overwrites the previous
    result rather than accumulating a history (see docs/evaluation.md)."""
    conn.execute(
        'INSERT INTO evaluation_results '
        '(id, session_id, configuration_id, task, format_version, sample_count, '
        'matched_samples, unmatched_predictions, unmatched_ground_truth, metrics, '
        'confusion_matrix, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(session_id, configuration_id, task) DO UPDATE SET '
        'id=excluded.id, format_version=excluded.format_version, '
        'sample_count=excluded.sample_count, matched_samples=excluded.matched_samples, '
        'unmatched_predictions=excluded.unmatched_predictions, '
        'unmatched_ground_truth=excluded.unmatched_ground_truth, metrics=excluded.metrics, '
        'confusion_matrix=excluded.confusion_matrix, computed_at=excluded.computed_at',
        (result.id, result.session_id, result.configuration_id, result.task,
         result.format_version, result.sample_count, result.matched_samples,
         result.unmatched_predictions, result.unmatched_ground_truth,
         json.dumps(result.metrics),
         json.dumps(result.confusion_matrix) if result.confusion_matrix is not None else None,
         result.computed_at.isoformat()),
    )
    conn.commit()


def get_evaluation_result(
    conn: sqlite3.Connection, session_id: str, configuration_id: str, task: str,
) -> EvaluationResult | None:
    row = conn.execute(
        'SELECT * FROM evaluation_results WHERE session_id = ? AND configuration_id = ? AND task = ?',
        (session_id, configuration_id, task),
    ).fetchone()
    return _row_to_evaluation_result(row) if row else None


def list_evaluation_results(conn: sqlite3.Connection, session_id: str) -> list[EvaluationResult]:
    rows = conn.execute(
        'SELECT * FROM evaluation_results WHERE session_id = ? ORDER BY configuration_id, task',
        (session_id,),
    ).fetchall()
    return [_row_to_evaluation_result(row) for row in rows]


def _row_to_evaluation_result(row: sqlite3.Row) -> EvaluationResult:
    return EvaluationResult(
        id=row['id'], session_id=row['session_id'], configuration_id=row['configuration_id'],
        task=row['task'], format_version=row['format_version'], sample_count=row['sample_count'],
        matched_samples=row['matched_samples'], unmatched_predictions=row['unmatched_predictions'],
        unmatched_ground_truth=row['unmatched_ground_truth'], metrics=json.loads(row['metrics']),
        confusion_matrix=json.loads(row['confusion_matrix']) if row['confusion_matrix'] else None,
        computed_at=datetime.fromisoformat(row['computed_at']),
    )
