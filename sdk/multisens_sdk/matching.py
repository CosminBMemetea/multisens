"""`MatchedPair`/`MatchResult` - the data shapes an `EvaluatorPlugin.evaluate()`
call receives (relocated from `backend/app/domain/matching.py`, v0.9 Phase
93). Data only - the actual `match_by_timestamp` algorithm stays
backend-only; no plugin contract ever re-derives frame association, it only
ever consumes an already-computed `MatchResult`.
"""
from __future__ import annotations

from dataclasses import dataclass

from multisens_sdk.models import GroundTruth, Prediction


@dataclass
class MatchedPair:
    ground_truth: GroundTruth
    prediction: Prediction
    delta_ms: float


@dataclass
class MatchResult:
    matched: list[MatchedPair]
    unmatched_ground_truth: list[GroundTruth]
    unmatched_predictions: list[Prediction]
