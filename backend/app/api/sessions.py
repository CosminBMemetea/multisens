"""Session lifecycle plus ground-truth/prediction/resource-observation
batch ingestion.

Ground truth, predictions, and (v0.7, Phase 70) resource observations all
nest under /api/sessions/{id}/... rather than living at the top level -
none of them mean anything without a session, and a top-level
POST /api/predictions would just be the same resource reached a second
way (see docs/architecture.md-style "avoid RPC-like endpoint explosion"
reasoning applied here).

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
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import get_db, require_session
from app.config import load_platform_id, load_sensors
from app.domain.evidence import matches_conditions
from app.domain.models import GroundTruth, Prediction, Session, derive_configuration_id
from app.domain.resources import ResourceObservation
from app.persistence import repository as repo
from app.plugins import state as plugin_state
from app.plugins.manager import (
    start_inference_connectors,
    start_resource_collection,
    stop_inference_connectors,
    stop_resource_collection,
)

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


class ResourceObservationBatchRequest(BaseModel):
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
    """Thin wrapper over `repository.insert_batch_with_partial_failure`
    (v0.9, Phase 97 - the core retry-on-duplicate logic moved there so
    `plugins/poll_runner.py` can reuse it without an api-layer
    dependency) - just adapts `(index, message)` pairs into this
    endpoint's own `BatchItemError` response shape."""
    return [
        BatchItemError(index=index, error=message)
        for index, message in repo.insert_batch_with_partial_failure(conn, indexed_items, bulk_insert)
    ]


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
    """`created -> running` is the only real transition. `running -> running`
    is an idempotent no-op (a caller retrying a request that actually
    succeeded must never be punished for it). `completed -> *` is rejected
    outright - restarting a finished session would silently resurrect it
    with no record that it was ever done, the same "no silent state
    resurrection" discipline this project applies to evaluation results
    and coverage elsewhere. (v0.9 bug hunt, issue #109 - previously any
    transition from any state silently succeeded.)

    On the real transition only, also starts live resource collection
    (v0.9.1, issue #111) for every configured `resource_collectors:`
    entry, and live background inference (v1.0-RC, issue #122) for every
    configured `inference_connectors:` entry - never on the idempotent
    no-op, which would either restart an already-running collector/connector
    for no reason or silently attach live collection to a session that was
    deliberately never given it. A collector/connector that fails to start
    (see `start_resource_collection`'s own docstring - most commonly,
    already attached to a different, still-running session) never fails
    session start itself; check `GET /api/resource-collectors`/
    `GET /api/inference-connectors` for why a given one isn't attached."""
    session = require_session(conn, session_id)
    if session.status == 'completed':
        raise HTTPException(status_code=409, detail=f"session '{session_id}' is already completed - cannot restart it")
    if session.status != 'running':
        repo.update_session_status(conn, session_id, 'running')
        sensor_ids = [s['id'] for s in load_sensors() if isinstance(s.get('id'), str)]
        configuration_id = derive_configuration_id(sensor_ids) if sensor_ids else None
        plugin_state.resource_collection_runners[session_id] = start_resource_collection(
            session_id, configuration_id, load_platform_id(), sensor_ids, plugin_state.resource_collectors,
        )
        plugin_state.inference_connector_runners[session_id] = start_inference_connectors(
            session_id, plugin_state.inference_connectors,
        )
    return require_session(conn, session_id)


@router.post('/{session_id}/complete')
def complete_session(session_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Session:
    """`running -> completed` is the only real transition, stamping
    `ended_at`. `completed -> completed` is an idempotent no-op that
    deliberately does NOT re-stamp `ended_at` - the original completion
    time is the true one, never silently overwritten by a later retry.
    `created -> *` is rejected outright - a session that was never
    started has no real end time to record. (v0.9 bug hunt, issue #109.)

    On the real transition only, also stops this session's live resource
    collection (v0.9.1, issue #111) and live inference connectors
    (v1.0-RC, issue #122), if any were started - the idempotent no-op
    leaves an already-stopped collection/connector alone rather than
    calling stop() a second time."""
    session = require_session(conn, session_id)
    if session.status == 'created':
        raise HTTPException(status_code=409, detail=f"session '{session_id}' was never started - cannot complete it")
    if session.status != 'completed':
        repo.update_session_status(conn, session_id, 'completed', ended_at=datetime.now(timezone.utc))
        stop_resource_collection(plugin_state.resource_collection_runners.pop(session_id, {}))
        stop_inference_connectors(plugin_state.inference_connector_runners.pop(session_id, {}))
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


@router.post('/{session_id}/resource-observations/batch', status_code=201)
def ingest_resource_observations_batch(
    session_id: str, body: ResourceObservationBatchRequest, conn: sqlite3.Connection = Depends(get_db),
) -> BatchIngestResponse:
    """v0.7, Phase 70 - same loose-dict/partial-failure batch pattern as
    ground-truth/predictions above, not a special case."""
    require_session(conn, session_id)
    if len(body.items) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=422, detail=f'batch too large: {len(body.items)} (max {MAX_BATCH_SIZE})')

    indexed_valid: list[tuple[int, ResourceObservation]] = []
    errors: list[BatchItemError] = []
    for index, raw in enumerate(body.items):
        try:
            obs = ResourceObservation.model_validate(
                {**raw, 'session_id': session_id, 'id': raw.get('id') or str(uuid4())}
            )
        except ValidationError as e:
            errors.append(BatchItemError(index=index, error=_format_validation_error(e)))
        else:
            indexed_valid.append((index, obs))

    insert_errors = _insert_with_partial_failure(conn, indexed_valid, repo.insert_resource_observations_batch)
    all_errors = sorted(errors + insert_errors, key=lambda e: e.index)
    return BatchIngestResponse(
        accepted=len(indexed_valid) - len(insert_errors), rejected=len(all_errors), errors=all_errors,
    )


@router.get('/{session_id}/resource-observations')
def list_session_resource_observations(
    session_id: str, configuration_id: str | None = None, metric: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ResourceObservation]:
    require_session(conn, session_id)
    return repo.list_resource_observations(conn, session_id, configuration_id=configuration_id, metric=metric)


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


# RideSafe bring-up, Phase 24 - Evidence Playback's "inspect frame":
# serves the exact snapshot file a prediction's own metadata already
# names (e.g. the RideSafe sampler's `snapshot_path`), never an
# arbitrary caller-supplied path. `MEDIA_ROOT` is the read-only host
# bind mount (docker-compose.yml) - same "hardcoded container-internal
# path, mount controls what's actually there" convention as
# config.py's own DEFAULT_CONFIG_PATH.
MEDIA_ROOT = Path('/media')


@router.get('/{session_id}/predictions/{prediction_id}/frame')
def get_prediction_frame(session_id: str, prediction_id: str, conn: sqlite3.Connection = Depends(get_db)):
    require_session(conn, session_id)
    prediction = repo.get_prediction(conn, session_id, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail=f"no prediction '{prediction_id}' in session '{session_id}'")

    snapshot_path = prediction.metadata.get('snapshot_path')
    if not snapshot_path or not isinstance(snapshot_path, str):
        raise HTTPException(status_code=404, detail='this prediction has no associated frame snapshot')

    # Resolve and re-check containment under MEDIA_ROOT - defends against
    # a `../../etc/passwd`-style path ever having been persisted into
    # metadata (from a misbehaving or malicious connector), not just
    # against a caller-supplied path (there is none here).
    resolved = (MEDIA_ROOT / snapshot_path).resolve()
    if MEDIA_ROOT.resolve() not in resolved.parents or not resolved.is_file():
        raise HTTPException(status_code=404, detail='snapshot file not found')

    return FileResponse(resolved, media_type='image/jpeg')


class ProfileUsageEntry(BaseModel):
    profile_id: str
    profile_name: str
    profile_version: str
    requirement_ids: list[str]


@router.get('/{session_id}/profile-usage')
def list_session_profile_usage(
    session_id: str, conn: sqlite3.Connection = Depends(get_db),
) -> list[ProfileUsageEntry]:
    """v0.5, Phase 45 - "which profile requirements could use evidence
    from this session?" A simple reverse reference for dataset auditing,
    not a full dependency graph. Defined as candidacy (this session's
    metadata is a superset of the requirement's declared conditions - the
    same matches_conditions rule v0.4's evidence selection uses, reused
    directly), never as "is currently the actually-resolved evidence" -
    a session that lost an ambiguity contest is still relevant to an
    auditor deciding whether a dataset is still needed, so computing true
    resolution (with its own ambiguity/binding machinery) would be both
    more expensive and the wrong question to ask here."""
    session = require_session(conn, session_id)
    usage = []
    for profile in repo.list_profiles(conn):
        matching_requirement_ids = [
            r.id for r in profile.requirements if matches_conditions(session, r.conditions)
        ]
        if matching_requirement_ids:
            usage.append(ProfileUsageEntry(
                profile_id=profile.id, profile_name=profile.name, profile_version=profile.version,
                requirement_ids=matching_requirement_ids,
            ))
    return usage
