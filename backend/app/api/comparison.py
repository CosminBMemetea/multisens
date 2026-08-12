"""Comparison API (v0.3, Phase 22): exposes app/domain/comparison.py
through HTTP. Thin translation layer only - fetches already-persisted
data, resolves source-id ambiguity, and calls compare_configurations;
no comparison logic lives here, matching how evaluation.py relates to
matching.py/metrics.py.

No comparison results are persisted - every /compare call recomputes
from whatever is in the database at request time (see the "why no
Experiment entity, why no persistence" note in domain/models.py).
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_db, require_session
from app.api.evaluation import DEFAULT_TOLERANCE_MS
from app.domain.comparison import (
    DEFAULT_COVERAGE_WARNING_THRESHOLD_PP,
    DEFAULT_MIN_COMMON_SAMPLE_COUNT,
    compare_configurations,
)
from app.domain.models import PairwiseComparison
from app.persistence import repository as repo

router = APIRouter(prefix='/api/sessions', tags=['comparison'])


class ConfigurationSummary(BaseModel):
    configuration_id: str
    sensor_ids: list[str]
    source_ids: list[str]
    prediction_count: int
    # Only present once /evaluate has been run for this configuration/task
    # - None (not 0) means "not evaluated yet", never a fabricated count.
    sample_count: int | None = None
    matched_samples: int | None = None


@router.get('/{session_id}/configurations')
def list_session_configurations(
    session_id: str, task: str, conn: sqlite3.Connection = Depends(get_db),
) -> list[ConfigurationSummary]:
    require_session(conn, session_id)
    summaries = []
    for configuration_id in repo.list_configuration_ids(conn, session_id, task):
        predictions = repo.list_predictions(conn, session_id, configuration_id=configuration_id, task=task)
        result = repo.get_evaluation_result(conn, session_id, configuration_id, task)
        summaries.append(ConfigurationSummary(
            configuration_id=configuration_id,
            sensor_ids=predictions[0].sensor_ids if predictions else [],
            source_ids=sorted({p.source_id for p in predictions}),
            prediction_count=len(predictions),
            sample_count=result.sample_count if result else None,
            matched_samples=result.matched_samples if result else None,
        ))
    return summaries


class CompareRequest(BaseModel):
    task: str
    baseline_configuration_id: str
    # None means "every other configuration that already has a persisted
    # evaluation result for this task" - discovered from the data, never
    # enumerated by the caller, same convention as /evaluate.
    candidate_configuration_ids: list[str] | None = None
    baseline_source_id: str | None = None
    candidate_source_ids: dict[str, str] = Field(default_factory=dict)
    tolerance_ms: float = DEFAULT_TOLERANCE_MS
    coverage_warning_threshold_pp: float = DEFAULT_COVERAGE_WARNING_THRESHOLD_PP
    min_common_sample_count: int = DEFAULT_MIN_COMMON_SAMPLE_COUNT


class CompareResponse(BaseModel):
    comparisons: list[PairwiseComparison]


def _resolve_source_id(
    conn: sqlite3.Connection, session_id: str, configuration_id: str, task: str, requested: str | None,
) -> str:
    available = repo.list_distinct_source_ids(conn, session_id, configuration_id, task)
    if requested is not None:
        if requested not in available:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"source_id '{requested}' not found for configuration '{configuration_id}' "
                    f"task '{task}' - available: {available}"
                ),
            )
        return requested
    if len(available) == 1:
        return available[0]
    if not available:
        raise HTTPException(
            status_code=422,
            detail=f"no predictions found for configuration '{configuration_id}' task '{task}'",
        )
    raise HTTPException(
        status_code=422,
        detail=(
            f"configuration '{configuration_id}' has multiple prediction sources for task "
            f"'{task}': {available} - specify which one explicitly"
        ),
    )


def _require_evaluated(
    conn: sqlite3.Connection, session_id: str, configuration_id: str, task: str,
):
    result = repo.get_evaluation_result(conn, session_id, configuration_id, task)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"configuration '{configuration_id}' has not been evaluated for task '{task}' "
                f"- run /evaluate first"
            ),
        )
    return result


@router.post('/{session_id}/compare')
def compare_session_configurations(
    session_id: str, body: CompareRequest, conn: sqlite3.Connection = Depends(get_db),
) -> CompareResponse:
    require_session(conn, session_id)
    if body.tolerance_ms < 0:
        raise HTTPException(status_code=422, detail=f'tolerance_ms must be >= 0, got {body.tolerance_ms}')

    baseline_result = _require_evaluated(conn, session_id, body.baseline_configuration_id, body.task)

    if body.candidate_configuration_ids is None:
        candidate_ids = [
            configuration_id
            for configuration_id in repo.list_configuration_ids(conn, session_id, body.task)
            if configuration_id != body.baseline_configuration_id
            and repo.get_evaluation_result(conn, session_id, configuration_id, body.task) is not None
        ]
    else:
        candidate_ids = body.candidate_configuration_ids
        for configuration_id in candidate_ids:
            _require_evaluated(conn, session_id, configuration_id, body.task)

    baseline_source_id = _resolve_source_id(
        conn, session_id, body.baseline_configuration_id, body.task, body.baseline_source_id,
    )
    baseline_predictions = repo.list_predictions(
        conn, session_id, configuration_id=body.baseline_configuration_id, task=body.task,
        source_id=baseline_source_id,
    )
    baseline_sensor_ids = baseline_predictions[0].sensor_ids if baseline_predictions else []
    ground_truth = repo.list_ground_truth(conn, session_id, task=body.task)

    comparisons = []
    for candidate_id in candidate_ids:
        candidate_source_id = _resolve_source_id(
            conn, session_id, candidate_id, body.task, body.candidate_source_ids.get(candidate_id),
        )
        candidate_predictions = repo.list_predictions(
            conn, session_id, configuration_id=candidate_id, task=body.task, source_id=candidate_source_id,
        )
        candidate_sensor_ids = candidate_predictions[0].sensor_ids if candidate_predictions else []
        candidate_result = repo.get_evaluation_result(conn, session_id, candidate_id, body.task)

        comparisons.append(compare_configurations(
            session_id=session_id,
            task=body.task,
            baseline_configuration_id=body.baseline_configuration_id,
            candidate_configuration_id=candidate_id,
            baseline_source_id=baseline_source_id,
            candidate_source_id=candidate_source_id,
            baseline_sensor_ids=baseline_sensor_ids,
            candidate_sensor_ids=candidate_sensor_ids,
            ground_truth=ground_truth,
            baseline_predictions=baseline_predictions,
            candidate_predictions=candidate_predictions,
            baseline_evaluation_result=baseline_result,
            candidate_evaluation_result=candidate_result,
            tolerance_ms=body.tolerance_ms,
            coverage_warning_threshold_pp=body.coverage_warning_threshold_pp,
            min_common_sample_count=body.min_common_sample_count,
        ))

    return CompareResponse(comparisons=comparisons)
