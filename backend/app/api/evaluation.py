"""Evaluation API: runs the matching + metric engine (Phase 13) over
persisted ground-truth/prediction data for a session, and persists the
result.

Dispatches through `EVALUATOR_REGISTRY` (Phase 79, v0.8) rather than
calling `evaluate_classification` directly - `evaluator_type` defaults to
`'classification'` so every pre-v0.8 caller keeps working unchanged, but
is never silently assumed for an explicitly-named, unrecognized type
(422 instead - see `evaluate_session` below).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_db, require_session
from app.domain.evaluators import EVALUATOR_REGISTRY
from app.domain.evidence_playback import build_evidence_samples
from app.domain.matching import match_by_timestamp
from app.domain.metrics import extract_label
from app.domain.models import EvaluationResult, Prediction
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
    # Defaults to 'classification' so every pre-v0.8 caller (script, test,
    # frontend build) keeps working byte-for-byte unchanged - this default
    # is not an arbitrary guess, it's literally what every existing caller
    # already got before this field existed. New callers should state it
    # explicitly; an unrecognized value is always a 422 (see below), never
    # silently coerced to classification.
    evaluator_type: str = 'classification'
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.post('/{session_id}/evaluate')
def evaluate_session(
    session_id: str, body: EvaluateRequest, conn: sqlite3.Connection = Depends(get_db),
) -> list[EvaluationResult]:
    require_session(conn, session_id)
    if body.tolerance_ms < 0:
        raise HTTPException(status_code=422, detail=f'tolerance_ms must be >= 0, got {body.tolerance_ms}')

    evaluator = EVALUATOR_REGISTRY.get(body.evaluator_type)
    if evaluator is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown evaluator_type '{body.evaluator_type}' - "
                f"supported: {sorted(EVALUATOR_REGISTRY)}"
            ),
        )

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
        try:
            output = evaluator.evaluate(match_result, body.parameters)
        except ValueError as e:
            # A malformed matched value (e.g. classification's missing
            # 'label' field) is a data problem, not a server bug - 422,
            # not 500. Generic across every evaluator, not classification-
            # specific - any Evaluator.evaluate() raising ValueError gets
            # the same treatment.
            raise HTTPException(status_code=422, detail=str(e)) from e

        # confusion_matrix stays populated for backward compatibility with
        # the pre-Phase-86 frontend, which still reads it as its own
        # dedicated field - sourced generically from details, not a
        # classification-specific branch here. Any evaluator that puts a
        # 'confusion_matrix' key in its details gets the same treatment;
        # one that doesn't (detection, regression) leaves this column null.
        confusion_matrix = output.details.get('confusion_matrix') if output.details else None

        result = EvaluationResult(
            id=str(uuid4()), session_id=session_id, configuration_id=configuration_id, task=body.task,
            format_version=evaluator.format_version, evaluator_type=body.evaluator_type,
            tolerance_ms=body.tolerance_ms,
            sample_count=output.sample_count, matched_samples=output.matched_samples,
            unmatched_predictions=output.unmatched_predictions,
            unmatched_ground_truth=output.unmatched_ground_truth,
            metrics=output.metrics,
            confusion_matrix=confusion_matrix,
            details=output.details,
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


# --- evidence playback (v0.9.1, issue #120) ----------------------------------

class SourceEvidenceResponse(BaseModel):
    configuration_id: str
    source_id: str
    sensor_ids: list[str]
    prediction_id: str | None
    prediction_timestamp_ms: float | None
    value: dict[str, Any] | None
    confidence: float | None
    match_delta_ms: float | None
    outcome: Literal['TP', 'FP', 'FN', 'TN'] | None


class EvidenceSampleResponse(BaseModel):
    gt_sample_id: str
    gt_timestamp_ms: float
    task: str
    gt_value: dict[str, Any]
    sources: list[SourceEvidenceResponse]
    relationship: Literal[
        'AGREE_POSITIVE', 'AGREE_NEGATIVE', 'DISAGREE', 'ONLY_ONE_SOURCE_AVAILABLE', 'NO_COMMON_GT_SAMPLE',
    ]


@router.get('/{session_id}/evidence')
def session_evidence(
    session_id: str, task: str, positive_label: str,
    tolerance_ms: float = DEFAULT_TOLERANCE_MS,
    configuration_ids: list[str] | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[EvidenceSampleResponse]:
    """Per-ground-truth-sample evidence, joined across every
    `(configuration_id, source_id)` pair active in the session for this
    task - see `domain/evidence_playback.py`'s own module docstring for
    why this is a join over `match_by_timestamp`'s already-computed
    per-sample results, never new matching logic, and never an inferred
    combined/fused value.

    `positive_label` is required, not defaulted - see
    `build_evidence_samples`'s own docstring for why guessing which
    label is "the event of interest" would be a fabrication this project
    doesn't make elsewhere (object_detection's confidence_threshold/
    iou_threshold have the same no-default posture).

    `configuration_ids` defaults to every configuration with at least
    one prediction for this task (same discovery convention `/evaluate`
    already uses), not an enumerated list the caller must know in advance.
    """
    require_session(conn, session_id)
    if tolerance_ms < 0:
        raise HTTPException(status_code=422, detail=f'tolerance_ms must be >= 0, got {tolerance_ms}')

    ground_truth = repo.list_ground_truth(conn, session_id, task=task)

    ids = configuration_ids if configuration_ids is not None else repo.list_configuration_ids(conn, session_id, task)
    predictions_by_source: dict[tuple[str, str], list[Prediction]] = {}
    for configuration_id in ids:
        for source_id in repo.list_distinct_source_ids(conn, session_id, configuration_id, task):
            predictions_by_source[(configuration_id, source_id)] = repo.list_predictions(
                conn, session_id, configuration_id=configuration_id, task=task, source_id=source_id,
            )

    samples = build_evidence_samples(
        ground_truth=ground_truth, predictions_by_source=predictions_by_source,
        tolerance_ms=tolerance_ms, positive_label=positive_label,
    )
    return [
        EvidenceSampleResponse(
            gt_sample_id=s.gt_sample_id, gt_timestamp_ms=s.gt_timestamp_ms, task=s.task, gt_value=s.gt_value,
            relationship=s.relationship,
            sources=[
                SourceEvidenceResponse(
                    configuration_id=src.configuration_id, source_id=src.source_id, sensor_ids=src.sensor_ids,
                    prediction_id=src.prediction_id, prediction_timestamp_ms=src.prediction_timestamp_ms,
                    value=src.value, confidence=src.confidence, match_delta_ms=src.match_delta_ms,
                    outcome=src.outcome,
                )
                for src in s.sources
            ],
        )
        for s in samples
    ]


TimelineEventKind = Literal['correct', 'incorrect', 'missing_prediction', 'unmatched_prediction']


class TimelineEvent(BaseModel):
    timestamp_ms: float
    kind: TimelineEventKind
    ground_truth_label: str | None = None
    predicted_label: str | None = None
    delta_ms: float | None = None


@router.get('/{session_id}/timeline')
def get_session_timeline(
    session_id: str, task: str, configuration_id: str, tolerance_ms: float = DEFAULT_TOLERANCE_MS,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[TimelineEvent]:
    """Per-sample match detail for the session-detail timeline strip.

    Deliberately NOT persisted alongside EvaluationResult - that stays a
    pure aggregate (see Phase 14). This recomputes match_by_timestamp
    fresh on every call instead, which is fine at this project's target
    scale (a few thousand events) and means the timeline can never drift
    from what a fresh /evaluate call would compute.
    """
    require_session(conn, session_id)
    if tolerance_ms < 0:
        raise HTTPException(status_code=422, detail=f'tolerance_ms must be >= 0, got {tolerance_ms}')

    # This view is classification-specific (a label-vs-label strip), never
    # generalized to detection/regression (v0.8, Phase 84) - a known,
    # documented scope boundary, not an oversight. Checked explicitly
    # against the persisted evaluator_type, rather than left to fail
    # accidentally inside extract_label below, so the error names the
    # real reason plainly instead of a generic "no label field" guess.
    # If nothing has been evaluated yet, this falls through unchanged -
    # same as every pre-v0.8 behavior.
    evaluation_result = repo.get_evaluation_result(conn, session_id, configuration_id, task)
    if evaluation_result is not None and evaluation_result.evaluator_type != 'classification':
        raise HTTPException(
            status_code=422,
            detail=(
                f"/timeline only supports classification results - configuration "
                f"'{configuration_id}' task '{task}' was evaluated with evaluator_type "
                f"'{evaluation_result.evaluator_type}'"
            ),
        )

    ground_truth = repo.list_ground_truth(conn, session_id, task=task)
    predictions = repo.list_predictions(conn, session_id, configuration_id=configuration_id, task=task)
    match_result = match_by_timestamp(ground_truth, predictions, tolerance_ms=tolerance_ms)

    try:
        events = [
            TimelineEvent(
                timestamp_ms=m.ground_truth.timestamp_ms,
                kind='correct' if extract_label(m.ground_truth.value, 'label') == extract_label(m.prediction.value, 'label') else 'incorrect',
                ground_truth_label=extract_label(m.ground_truth.value, 'label'),
                predicted_label=extract_label(m.prediction.value, 'label'),
                delta_ms=m.delta_ms,
            )
            for m in match_result.matched
        ]
        events += [
            TimelineEvent(
                timestamp_ms=gt.timestamp_ms, kind='missing_prediction',
                ground_truth_label=extract_label(gt.value, 'label'),
            )
            for gt in match_result.unmatched_ground_truth
        ]
        events += [
            TimelineEvent(
                timestamp_ms=pred.timestamp_ms, kind='unmatched_prediction',
                predicted_label=extract_label(pred.value, 'label'),
            )
            for pred in match_result.unmatched_predictions
        ]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    events.sort(key=lambda e: e.timestamp_ms)
    return events
