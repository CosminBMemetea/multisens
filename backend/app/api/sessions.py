"""Session lifecycle plus ground-truth/prediction batch ingestion.

Ground truth and predictions nest under /api/sessions/{id}/... rather than
living at the top level - neither means anything without a session, and a
top-level POST /api/predictions would just be the same resource reached a
second way (see docs/architecture.md-style "avoid RPC-like endpoint
explosion" reasoning applied here).

Batch items are accepted as loose dicts (not a typed Pydantic list) and
validated one at a time against the domain model. That's deliberate: if the
request body were typed as `list[GroundTruthItem]`, FastAPI would reject
one malformed item by failing the *entire* request with a blanket 422,
which is exactly the all-or-nothing behavior partial-failure reporting is
supposed to replace.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import get_db, require_session
from app.domain.models import GroundTruth, Prediction, Session
from app.persistence import repository as repo

router = APIRouter(prefix='/api/sessions', tags=['sessions'])

# A guard against an accidental/abusive request size, not a real system
# limit - "a few thousand events" (see docs/limitations.md-to-be) fits
# comfortably under this with room to spare.
MAX_BATCH_SIZE = 5000


class SessionCreateRequest(BaseModel):
    id: str | None = None
    name: str
    scenario_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroundTruthBatchRequest(BaseModel):
    items: list[dict[str, Any]]


class PredictionBatchRequest(BaseModel):
    items: list[dict[str, Any]]


class BatchItemError(BaseModel):
    index: int
    error: str


class BatchIngestResponse(BaseModel):
    accepted: int
    rejected: int
    errors: list[BatchItemError]


def _format_validation_error(e: ValidationError) -> str:
    return '; '.join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
    )


def _insert_with_partial_failure(
    conn: sqlite3.Connection,
    indexed_items: list[tuple[int, Any]],
    bulk_insert: Callable[[sqlite3.Connection, list[Any]], None],
) -> list[BatchItemError]:
    """One bulk insert for the common case; a primary-key collision (e.g. a
    retried batch that reused a client-supplied id) falls back to inserting
    one at a time so a single duplicate doesn't reject the rest of an
    otherwise-valid batch."""
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
                errors.append(BatchItemError(index=index, error=f'insert failed (duplicate id?): {e}'))
        return errors


@router.post('', status_code=201)
def create_session(body: SessionCreateRequest, conn: sqlite3.Connection = Depends(get_db)) -> Session:
    if repo.get_scenario(conn, body.scenario_id) is None:
        raise HTTPException(status_code=422, detail=f"scenario '{body.scenario_id}' does not exist")
    session_id = body.id or str(uuid4())
    if repo.get_session(conn, session_id) is not None:
        raise HTTPException(status_code=409, detail=f"session '{session_id}' already exists")
    session = Session(
        id=session_id, name=body.name, scenario_id=body.scenario_id,
        started_at=datetime.now(timezone.utc), metadata=body.metadata,
    )
    repo.create_session(conn, session)
    return session


@router.get('')
def list_sessions(conn: sqlite3.Connection = Depends(get_db)) -> list[Session]:
    return repo.list_sessions(conn)


@router.get('/{session_id}')
def get_session(session_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Session:
    return require_session(conn, session_id)


@router.post('/{session_id}/start')
def start_session(session_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Session:
    require_session(conn, session_id)
    repo.update_session_status(conn, session_id, 'running')
    return require_session(conn, session_id)


@router.post('/{session_id}/complete')
def complete_session(session_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Session:
    require_session(conn, session_id)
    repo.update_session_status(conn, session_id, 'completed', ended_at=datetime.now(timezone.utc))
    return require_session(conn, session_id)


@router.post('/{session_id}/ground-truth/batch', status_code=201)
def ingest_ground_truth_batch(
    session_id: str, body: GroundTruthBatchRequest, conn: sqlite3.Connection = Depends(get_db),
) -> BatchIngestResponse:
    require_session(conn, session_id)
    if len(body.items) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=422, detail=f'batch too large: {len(body.items)} (max {MAX_BATCH_SIZE})')

    indexed_valid: list[tuple[int, GroundTruth]] = []
    errors: list[BatchItemError] = []
    for index, raw in enumerate(body.items):
        try:
            gt = GroundTruth.model_validate({**raw, 'session_id': session_id, 'id': raw.get('id') or str(uuid4())})
        except ValidationError as e:
            errors.append(BatchItemError(index=index, error=_format_validation_error(e)))
        else:
            indexed_valid.append((index, gt))

    insert_errors = _insert_with_partial_failure(conn, indexed_valid, repo.insert_ground_truth_batch)
    all_errors = sorted(errors + insert_errors, key=lambda e: e.index)
    return BatchIngestResponse(
        accepted=len(indexed_valid) - len(insert_errors), rejected=len(all_errors), errors=all_errors,
    )


@router.post('/{session_id}/predictions/batch', status_code=201)
def ingest_predictions_batch(
    session_id: str, body: PredictionBatchRequest, conn: sqlite3.Connection = Depends(get_db),
) -> BatchIngestResponse:
    require_session(conn, session_id)
    if len(body.items) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=422, detail=f'batch too large: {len(body.items)} (max {MAX_BATCH_SIZE})')

    indexed_valid: list[tuple[int, Prediction]] = []
    errors: list[BatchItemError] = []
    for index, raw in enumerate(body.items):
        try:
            pred = Prediction.model_validate(
                {**raw, 'session_id': session_id, 'id': raw.get('id') or str(uuid4())}
            )
        except ValidationError as e:
            errors.append(BatchItemError(index=index, error=_format_validation_error(e)))
        else:
            indexed_valid.append((index, pred))

    insert_errors = _insert_with_partial_failure(conn, indexed_valid, repo.insert_predictions_batch)
    all_errors = sorted(errors + insert_errors, key=lambda e: e.index)
    return BatchIngestResponse(
        accepted=len(indexed_valid) - len(insert_errors), rejected=len(all_errors), errors=all_errors,
    )


@router.get('/{session_id}/ground-truth')
def list_session_ground_truth(
    session_id: str, task: str | None = None, conn: sqlite3.Connection = Depends(get_db),
) -> list[GroundTruth]:
    require_session(conn, session_id)
    return repo.list_ground_truth(conn, session_id, task=task)


@router.get('/{session_id}/predictions')
def list_session_predictions(
    session_id: str, configuration_id: str | None = None, task: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[Prediction]:
    require_session(conn, session_id)
    return repo.list_predictions(conn, session_id, configuration_id=configuration_id, task=task)
