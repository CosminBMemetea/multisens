"""Evaluation API: runs the matching + metric engine (Phase 13) over
persisted ground-truth/prediction data for a session, and persists the
result.

Classification-only end to end, matching evaluate_classification - the
only evaluator that exists yet (see app/domain/metrics.py). A future
DetectionEvaluator would need a task-type lookup here; not built until a
second evaluator actually exists.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_db, require_session
from app.domain.matching import match_by_timestamp
from app.domain.metrics import evaluate_classification
from app.domain.models import EvaluationResult
from app.persistence import repository as repo

router = APIRouter(prefix='/api/sessions', tags=['evaluation'])

# Not a measured value like the ROS/DDS sync tolerance (docs/architecture.md) -
# ground truth and predictions can originate from entirely different
# systems/clocks with no shared reference, so there is no analogous "real
# skew" to measure here. Callers should tune this per scenario.
DEFAULT_TOLERANCE_MS = 100.0


class EvaluateRequest(BaseModel):
    task: str
    # None means "every configuration that has at least one prediction for
    # this task" - discovered from the data, not enumerated by the caller.
    configuration_ids: list[str] | None = None
    tolerance_ms: float = DEFAULT_TOLERANCE_MS


@router.post('/{session_id}/evaluate')
def evaluate_session(
    session_id: str, body: EvaluateRequest, conn: sqlite3.Connection = Depends(get_db),
) -> list[EvaluationResult]:
    require_session(conn, session_id)
    if body.tolerance_ms < 0:
        raise HTTPException(status_code=422, detail=f'tolerance_ms must be >= 0, got {body.tolerance_ms}')

    configuration_ids = body.configuration_ids
    if configuration_ids is None:
        configuration_ids = repo.list_configuration_ids(conn, session_id, body.task)

    # Ground truth doesn't depend on configuration - it's the same "what
    # actually happened" regardless of which sensors a prediction used -
    # so it's fetched once and matched against each configuration in turn.
    ground_truth = repo.list_ground_truth(conn, session_id, task=body.task)

    results: list[EvaluationResult] = []
    for configuration_id in configuration_ids:
        predictions = repo.list_predictions(conn, session_id, configuration_id=configuration_id, task=body.task)
        match_result = match_by_timestamp(ground_truth, predictions, tolerance_ms=body.tolerance_ms)
        metrics = evaluate_classification(match_result)

        result = EvaluationResult(
            id=str(uuid4()), session_id=session_id, configuration_id=configuration_id, task=body.task,
            tolerance_ms=body.tolerance_ms,
            sample_count=metrics.sample_count, matched_samples=metrics.matched_samples,
            unmatched_predictions=metrics.unmatched_predictions,
            unmatched_ground_truth=metrics.unmatched_ground_truth,
            metrics={
                'accuracy': metrics.accuracy,
                'precision_macro': metrics.precision_macro,
                'recall_macro': metrics.recall_macro,
                'f1_macro': metrics.f1_macro,
                'precision_micro': metrics.precision_micro,
                'recall_micro': metrics.recall_micro,
                'f1_micro': metrics.f1_micro,
            },
            confusion_matrix={
                'labels': metrics.confusion_matrix.labels,
                'counts': metrics.confusion_matrix.counts,
            },
            computed_at=datetime.now(timezone.utc),
        )
        repo.upsert_evaluation_result(conn, result)
        results.append(result)

    return results


@router.get('/{session_id}/evaluation')
def get_session_evaluation(
    session_id: str, conn: sqlite3.Connection = Depends(get_db),
) -> list[EvaluationResult]:
    require_session(conn, session_id)
    return repo.list_evaluation_results(conn, session_id)
