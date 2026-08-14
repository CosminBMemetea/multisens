"""Timestamp association between ground truth and predictions.

Pure function: no persistence, no FastAPI, no ROS - just
list[GroundTruth]/list[Prediction] in, a MatchResult out. Matching is
greedy one-to-one nearest-neighbor: each ground-truth point is matched (in
increasing timestamp order) to the closest not-yet-consumed prediction
within `tolerance_ms`, and every prediction is consumed by at most one
ground-truth point. Unmatched items on either side are reported, never
silently dropped.

Complexity: both inputs are sorted once (O(g log g + p log p)), then a
pointer over predictions only ever advances - a prediction more than
tolerance_ms older than the current ground-truth point can never match
this or any later one, since ground truth is processed in increasing
timestamp order. In the expected case (tolerance smaller than the typical
gap between samples, so each ground-truth point has O(1) prediction
candidates in its window) this makes the matching pass itself O(g + p).
A pathological input - tolerance much larger than the sample rate, so many
predictions fall in every window - degrades toward O(g * w) where w is the
window's candidate count; still trivial at this project's target scale
(a few thousand events, see docs/limitations.md).

**v0.9 (Phase 93) note**: `MatchedPair`/`MatchResult` are no longer
defined here - they're re-exported from `multisens_sdk.matching`, which
now owns the data shapes (an `EvaluatorPlugin.evaluate()` call receives a
`MatchResult`). `match_by_timestamp` itself - the actual algorithm - stays
here, backend-only; no plugin ever re-derives frame association.
"""
from __future__ import annotations

from app.domain.models import GroundTruth, Prediction
from multisens_sdk.matching import MatchedPair, MatchResult

__all__ = ['MatchedPair', 'MatchResult', 'match_by_timestamp']


def match_by_timestamp(
    ground_truth: list[GroundTruth],
    predictions: list[Prediction],
    tolerance_ms: float,
) -> MatchResult:
    if tolerance_ms < 0:
        raise ValueError(f'tolerance_ms must be >= 0, got {tolerance_ms}')

    gt_sorted = sorted(ground_truth, key=lambda g: g.timestamp_ms)
    pred_sorted = sorted(predictions, key=lambda p: p.timestamp_ms)
    consumed = [False] * len(pred_sorted)

    matched: list[MatchedPair] = []
    unmatched_gt: list[GroundTruth] = []

    pred_start = 0
    n_pred = len(pred_sorted)

    for gt in gt_sorted:
        lower_bound = gt.timestamp_ms - tolerance_ms
        upper_bound = gt.timestamp_ms + tolerance_ms

        # Predictions before pred_start are permanently too old for this
        # (and thus every later, since gt is sorted ascending) ground-truth
        # point - never revisited again regardless of consumed state.
        while pred_start < n_pred and pred_sorted[pred_start].timestamp_ms < lower_bound:
            pred_start += 1

        best_index: int | None = None
        best_delta: float | None = None
        j = pred_start
        while j < n_pred and pred_sorted[j].timestamp_ms <= upper_bound:
            if not consumed[j]:
                delta = abs(pred_sorted[j].timestamp_ms - gt.timestamp_ms)
                # Scanning in increasing timestamp order means the first
                # candidate found at the minimum delta is already the
                # earliest-timestamp one - the documented tie-break.
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best_index = j
            j += 1

        if best_index is not None:
            consumed[best_index] = True
            matched.append(MatchedPair(
                ground_truth=gt, prediction=pred_sorted[best_index], delta_ms=best_delta,
            ))
        else:
            unmatched_gt.append(gt)

    unmatched_preds = [p for i, p in enumerate(pred_sorted) if not consumed[i]]

    return MatchResult(
        matched=matched, unmatched_ground_truth=unmatched_gt, unmatched_predictions=unmatched_preds,
    )
