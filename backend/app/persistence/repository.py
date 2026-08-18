"""Repository boundary: the only module (besides db.py) that touches
sqlite3. Every function takes/returns app.domain.models types, never a raw
row or dict - callers (API handlers, the metric engine) never see SQL.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Callable

from app.domain.models import EvaluationResult, GroundTruth, Prediction, Scenario, Session, SessionStatus
from app.domain.profiles import EvaluationProfile
from app.domain.resources import ResourceObservation


def insert_batch_with_partial_failure(
    conn: sqlite3.Connection,
    indexed_items: list[tuple[int, Any]],
    bulk_insert: Callable[[sqlite3.Connection, list[Any]], None],
) -> list[tuple[int, str]]:
    """One bulk insert for the common case; a primary-key collision (e.g.
    a retried batch that reused a client-supplied id) falls back to
    inserting one at a time so a single duplicate doesn't reject the
    rest of an otherwise-valid batch. Returns `(index, error_message)`
    pairs for whatever didn't make it in - deliberately no pydantic
    response-shape dependency here (persistence layer, not an API
    concern) - `api/sessions.py`'s own `BatchItemError` wraps these for
    the REST response; `plugins/poll_runner.py` (v0.9, Phase 97) uses
    the same function directly for connector-sourced batches, the exact
    "a connector is a code-driven way to call an endpoint that already
    exists" reuse this was written for."""
    if not indexed_items:
        return []
    items = [item for _, item in indexed_items]
    try:
        bulk_insert(conn, items)
        return []
    except sqlite3.IntegrityError:
        conn.rollback()
        errors = []
        for index, item in indexed_items:
            try:
                bulk_insert(conn, [item])
            except sqlite3.IntegrityError as e:
                conn.rollback()
                errors.append((index, f'insert failed (duplicate id?): {e}'))
        return errors


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
    configuration_id: str | None = None, task: str | None = None, source_id: str | None = None,
) -> list[Prediction]:
    query = 'SELECT * FROM predictions WHERE session_id = ?'
    params: list[str] = [session_id]
    if configuration_id is not None:
        query += ' AND configuration_id = ?'
        params.append(configuration_id)
    if task is not None:
        query += ' AND task = ?'
        params.append(task)
    if source_id is not None:
        query += ' AND source_id = ?'
        params.append(source_id)
    query += ' ORDER BY timestamp_ms'
    rows = conn.execute(query, params).fetchall()
    return [_row_to_prediction(row) for row in rows]


def list_configuration_ids(conn: sqlite3.Connection, session_id: str, task: str) -> list[str]:
    """Distinct configuration_ids with at least one prediction for this
    session/task - lets /evaluate discover what to evaluate when the
    caller doesn't name specific configurations."""
    rows = conn.execute(
        'SELECT DISTINCT configuration_id FROM predictions WHERE session_id = ? AND task = ? '
        'ORDER BY configuration_id',
        (session_id, task),
    ).fetchall()
    return [row['configuration_id'] for row in rows]


def list_distinct_source_ids(
    conn: sqlite3.Connection, session_id: str, configuration_id: str, task: str,
) -> list[str]:
    """Distinct source_ids with at least one prediction for this
    session/configuration/task - lets /compare (Phase 22) detect
    ambiguous prediction sources instead of guessing which one to use."""
    rows = conn.execute(
        'SELECT DISTINCT source_id FROM predictions '
        'WHERE session_id = ? AND configuration_id = ? AND task = ? ORDER BY source_id',
        (session_id, configuration_id, task),
    ).fetchall()
    return [row['source_id'] for row in rows]


def get_sensor_ids_for_configuration(conn: sqlite3.Connection, configuration_id: str) -> list[str] | None:
    """One representative prediction row's sensor_ids for this
    configuration_id, across any session - guaranteed identical across
    every row sharing the same configuration_id (Prediction's own
    validator enforces configuration_id == derive_configuration_id
    (sensor_ids), see models.py), so any one row is authoritative. None
    if no prediction anywhere has ever used this configuration_id - the
    decision API's (v0.6, Phase 56) signal that a configuration was
    named but never evaluated, reported explicitly rather than guessed
    at by reverse-parsing the id string (not safe - see
    comparison.py's classify_relationship docstring)."""
    row = conn.execute(
        'SELECT sensor_ids FROM predictions WHERE configuration_id = ? LIMIT 1', (configuration_id,),
    ).fetchone()
    return json.loads(row['sensor_ids']) if row is not None else None


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
        '(id, session_id, configuration_id, task, format_version, evaluator_type, tolerance_ms, '
        'sample_count, matched_samples, unmatched_predictions, unmatched_ground_truth, metrics, '
        'confusion_matrix, details, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(session_id, configuration_id, task) DO UPDATE SET '
        'id=excluded.id, format_version=excluded.format_version, evaluator_type=excluded.evaluator_type, '
        'tolerance_ms=excluded.tolerance_ms, '
        'sample_count=excluded.sample_count, matched_samples=excluded.matched_samples, '
        'unmatched_predictions=excluded.unmatched_predictions, '
        'unmatched_ground_truth=excluded.unmatched_ground_truth, metrics=excluded.metrics, '
        'confusion_matrix=excluded.confusion_matrix, details=excluded.details, '
        'computed_at=excluded.computed_at',
        (result.id, result.session_id, result.configuration_id, result.task,
         result.format_version, result.evaluator_type, result.tolerance_ms, result.sample_count,
         result.matched_samples, result.unmatched_predictions, result.unmatched_ground_truth,
         json.dumps(result.metrics),
         json.dumps(result.confusion_matrix) if result.confusion_matrix is not None else None,
         json.dumps(result.details) if result.details is not None else None,
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
        task=row['task'], format_version=row['format_version'], evaluator_type=row['evaluator_type'],
        tolerance_ms=row['tolerance_ms'],
        sample_count=row['sample_count'],
        matched_samples=row['matched_samples'], unmatched_predictions=row['unmatched_predictions'],
        unmatched_ground_truth=row['unmatched_ground_truth'], metrics=json.loads(row['metrics']),
        confusion_matrix=json.loads(row['confusion_matrix']) if row['confusion_matrix'] else None,
        details=json.loads(row['details']) if row['details'] else None,
        computed_at=datetime.fromisoformat(row['computed_at']),
    )


# --- evaluation profiles (v0.4, Phase 32) ----------------------------------
#
# One TEXT column holds the entire validated document - see the
# migration's own comment for why this isn't normalized. name/version are
# duplicated into real columns purely for cheap listing/sorting.

def create_profile(conn: sqlite3.Connection, profile: EvaluationProfile) -> None:
    conn.execute(
        'INSERT INTO evaluation_profiles (id, name, version, document, created_at) VALUES (?, ?, ?, ?, ?)',
        (profile.id, profile.name, profile.version, profile.model_dump_json(), profile.created_at.isoformat()),
    )
    conn.commit()


def get_profile(conn: sqlite3.Connection, profile_id: str) -> EvaluationProfile | None:
    row = conn.execute('SELECT document FROM evaluation_profiles WHERE id = ?', (profile_id,)).fetchone()
    return EvaluationProfile.model_validate_json(row['document']) if row else None


def list_profiles(conn: sqlite3.Connection) -> list[EvaluationProfile]:
    rows = conn.execute('SELECT document FROM evaluation_profiles ORDER BY id').fetchall()
    return [EvaluationProfile.model_validate_json(row['document']) for row in rows]


# --- resource observations (v0.7, Phase 65) ---------------------------------

def insert_resource_observations_batch(conn: sqlite3.Connection, items: list[ResourceObservation]) -> None:
    conn.executemany(
        'INSERT INTO resource_observations '
        '(id, session_id, configuration_id, metric, value, unit, quality, source, '
        'platform_id, started_at, ended_at, sample_count, metadata) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [(o.id, o.session_id, o.configuration_id, o.metric, o.value, o.unit, o.quality, o.source,
          o.platform_id, o.started_at.isoformat(), o.ended_at.isoformat(), o.sample_count,
          json.dumps(o.metadata)) for o in items],
    )
    conn.commit()


def list_resource_observations(
    conn: sqlite3.Connection, session_id: str,
    configuration_id: str | None = None, metric: str | None = None,
) -> list[ResourceObservation]:
    query = 'SELECT * FROM resource_observations WHERE session_id = ?'
    params: list[str] = [session_id]
    if configuration_id is not None:
        query += ' AND configuration_id = ?'
        params.append(configuration_id)
    if metric is not None:
        query += ' AND metric = ?'
        params.append(metric)
    query += ' ORDER BY metric, started_at'
    rows = conn.execute(query, params).fetchall()
    return [_row_to_resource_observation(row) for row in rows]


def _row_to_resource_observation(row: sqlite3.Row) -> ResourceObservation:
    return ResourceObservation(
        id=row['id'], session_id=row['session_id'], configuration_id=row['configuration_id'],
        metric=row['metric'], value=row['value'], unit=row['unit'], quality=row['quality'],
        source=row['source'], platform_id=row['platform_id'],
        started_at=datetime.fromisoformat(row['started_at']), ended_at=datetime.fromisoformat(row['ended_at']),
        sample_count=row['sample_count'], metadata=json.loads(row['metadata']),
    )


# --- cleanup (RideSafe bring-up, Phase 1) ----------------------------------
#
# No delete path existed anywhere in this file before this - every prior
# release only ever added data (see insert_batch_with_partial_failure's own
# docstring). Migration 0001 declares every child table's session_id as
# `REFERENCES sessions(id)` and db.py sets `PRAGMA foreign_keys=ON`
# (db.py:34), but that only enforces inserts - there is no `ON DELETE
# CASCADE`, so a bare `DELETE FROM sessions` would raise
# `sqlite3.IntegrityError` against any session with rows in a child table,
# not silently orphan them. `delete_session` below deletes every child
# table first, in the one order that's always safe regardless of which
# tables happen to have rows for a given session.

def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute('DELETE FROM resource_observations WHERE session_id = ?', (session_id,))
    conn.execute('DELETE FROM evaluation_results WHERE session_id = ?', (session_id,))
    conn.execute('DELETE FROM predictions WHERE session_id = ?', (session_id,))
    conn.execute('DELETE FROM ground_truth WHERE session_id = ?', (session_id,))
    conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
    conn.commit()


def delete_scenario(conn: sqlite3.Connection, scenario_id: str) -> None:
    """Fails with `sqlite3.IntegrityError` if any session still references
    this scenario - delete those sessions first (`delete_session` above).
    Deliberately not cascaded automatically: a scenario can outlive any one
    session that used it, so silently deleting still-referenced scenarios
    would be a real, surprising data loss rather than cleanup."""
    conn.execute('DELETE FROM scenarios WHERE id = ?', (scenario_id,))
    conn.commit()


def delete_profile(conn: sqlite3.Connection, profile_id: str) -> None:
    """`evaluation_profiles` has no foreign key to/from any other table
    (profiles are evaluated against already-persisted session evidence on
    demand, never joined at the schema level) - a plain delete, no cascade
    needed."""
    conn.execute('DELETE FROM evaluation_profiles WHERE id = ?', (profile_id,))
    conn.commit()
