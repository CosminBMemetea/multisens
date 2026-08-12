"""Configuration comparison engine (v0.3, Phase 21). Pure functions - no
persistence, no FastAPI, no ROS - same discipline as matching.py/metrics.py.

Never a causal layer (see PairwiseComparison's docstring in models.py).
This module answers "how did baseline and candidate measure differently
under stated conditions," nothing more - no contribution score, no
importance ranking, no compliance/requirement verdict.

Two comparison sides are always computed together, never a caller-chosen
either/or:

- `reported`: diffs the two already-persisted EvaluationResults exactly as
  they were computed (each side may have used a different tolerance_ms).
- `common_set`: filters both configurations' already-matched pairs down to
  the ground-truth ids *both* matched (by GroundTruth.id, never by
  re-running match_by_timestamp on a filtered subset - a subset re-match
  isn't guaranteed to reproduce the pairs the original full-population
  match found, if two ground-truth points had been competing for the same
  prediction), then re-evaluates each side over exactly that population
  using the existing, unmodified evaluate_classification.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from app.domain.matching import MatchResult, match_by_timestamp
from app.domain.metrics import ClassificationMetrics, evaluate_classification
from app.domain.models import (
    ComparisonMetrics,
    ComparisonSide,
    ComparisonValidity,
    EvaluationResult,
    GroundTruth,
    MetricDelta,
    MetricValue,
    PairwiseComparison,
    Prediction,
)

# Heuristic, not evidence-based - same honesty treatment as the matching
# tolerance default (see matching.py / docs/evaluation.md): there is no
# measured "right" threshold for either of these, only a starting point to
# tune per scenario.
DEFAULT_COVERAGE_WARNING_THRESHOLD_PP = 5.0
DEFAULT_MIN_COMMON_SAMPLE_COUNT = 20

Relationship = Literal['direct_addition', 'direct_removal', 'general']


def classify_relationship(
    baseline_sensor_ids: list[str], candidate_sensor_ids: list[str],
) -> tuple[list[str], list[str], Relationship]:
    """Set difference, nothing more - works for any sensor names, since it
    never inspects a configuration_id string (see derive_configuration_id
    in models.py for why that string isn't safe to reverse-parse)."""
    baseline_set = set(baseline_sensor_ids)
    candidate_set = set(candidate_sensor_ids)
    added = sorted(candidate_set - baseline_set)
    removed = sorted(baseline_set - candidate_set)

    if len(added) == 1 and not removed:
        relationship: Relationship = 'direct_addition'
    elif len(removed) == 1 and not added:
        relationship = 'direct_removal'
    else:
        relationship = 'general'
    return added, removed, relationship


def compute_metric_delta(baseline: MetricValue, candidate: MetricValue) -> MetricDelta:
    absolute = candidate - baseline if baseline is not None and candidate is not None else None
    relative = (absolute / abs(baseline)) if absolute is not None and baseline else None
    return MetricDelta(baseline=baseline, candidate=candidate, absolute=absolute, relative=relative)


def _coverage(matched_samples: int, sample_count: int) -> MetricValue:
    return (matched_samples / sample_count) if sample_count > 0 else None


def comparison_metrics_from_evaluation_result(result: EvaluationResult) -> ComparisonMetrics:
    return ComparisonMetrics(
        sample_count=result.sample_count,
        matched_samples=result.matched_samples,
        unmatched_predictions=result.unmatched_predictions,
        unmatched_ground_truth=result.unmatched_ground_truth,
        coverage=_coverage(result.matched_samples, result.sample_count),
        metrics=dict(result.metrics),
    )


def comparison_metrics_from_classification(cm: ClassificationMetrics) -> ComparisonMetrics:
    return ComparisonMetrics(
        sample_count=cm.sample_count,
        matched_samples=cm.matched_samples,
        unmatched_predictions=cm.unmatched_predictions,
        unmatched_ground_truth=cm.unmatched_ground_truth,
        coverage=_coverage(cm.matched_samples, cm.sample_count),
        metrics={
            'accuracy': cm.accuracy,
            'precision_macro': cm.precision_macro,
            'recall_macro': cm.recall_macro,
            'f1_macro': cm.f1_macro,
            'precision_micro': cm.precision_micro,
            'recall_micro': cm.recall_micro,
            'f1_micro': cm.f1_micro,
        },
    )


def build_comparison_side(
    baseline: ComparisonMetrics, candidate: ComparisonMetrics, common_sample_count: int | None = None,
) -> ComparisonSide:
    metric_keys = sorted(set(baseline.metrics) | set(candidate.metrics))
    metric_deltas = {
        key: compute_metric_delta(baseline.metrics.get(key), candidate.metrics.get(key))
        for key in metric_keys
    }
    coverage_delta_pp = (
        (candidate.coverage - baseline.coverage) * 100
        if candidate.coverage is not None and baseline.coverage is not None
        else None
    )
    return ComparisonSide(
        common_sample_count=common_sample_count,
        baseline=baseline,
        candidate=candidate,
        metric_deltas=metric_deltas,
        coverage_delta_pp=coverage_delta_pp,
        matched_sample_delta=candidate.matched_samples - baseline.matched_samples,
    )


def intersect_matched_ground_truth_ids(baseline: MatchResult, candidate: MatchResult) -> set[str]:
    baseline_ids = {m.ground_truth.id for m in baseline.matched}
    candidate_ids = {m.ground_truth.id for m in candidate.matched}
    return baseline_ids & candidate_ids


def filter_matched_by_ground_truth_ids(match_result: MatchResult, gt_ids: set[str]) -> MatchResult:
    """Everything in the returned MatchResult is, by construction, matched
    - unmatched_ground_truth/unmatched_predictions are always empty here,
    since the restricted population is defined as exactly what both sides
    matched. Coverage within this view is therefore always 100%; the
    number that actually matters is common_sample_count relative to each
    side's original (unfiltered) matched_samples, carried separately on
    ComparisonSide."""
    filtered = [m for m in match_result.matched if m.ground_truth.id in gt_ids]
    return MatchResult(matched=filtered, unmatched_ground_truth=[], unmatched_predictions=[])


def assess_validity(
    reported: ComparisonSide,
    common_set: ComparisonSide,
    coverage_warning_threshold_pp: float = DEFAULT_COVERAGE_WARNING_THRESHOLD_PP,
    min_common_sample_count: int = DEFAULT_MIN_COMMON_SAMPLE_COUNT,
) -> ComparisonValidity:
    """Evidence-quality verdict only - see ComparisonValidity's docstring
    for why this is never a compliance/requirement judgment. Deliberately
    NOT checking "different session"/"different task": both are
    structurally impossible given how compare_configurations is called
    (one session, one task, by construction), not something worth a
    runtime check. Also deliberately NOT checking "matched label sets
    differ" yet - that needs confusion-matrix data ComparisonMetrics
    doesn't carry; noted as a known gap rather than rushed in with an
    under-justified threshold."""
    reasons: list[str] = []

    if common_set.common_sample_count == 0:
        return ComparisonValidity(status='invalid', reasons=['no common samples in common-set mode'])

    if common_set.common_sample_count is not None and common_set.common_sample_count < min_common_sample_count:
        reasons.append(
            f'common sample count ({common_set.common_sample_count}) is below the '
            f'minimum ({min_common_sample_count})'
        )

    if reported.coverage_delta_pp is not None and abs(reported.coverage_delta_pp) > coverage_warning_threshold_pp:
        reasons.append(f'coverage differs by {abs(reported.coverage_delta_pp):.1f} pp')

    status = 'valid_with_warnings' if reasons else 'valid'
    return ComparisonValidity(status=status, reasons=reasons)


def compare_configurations(
    *,
    session_id: str,
    task: str,
    baseline_configuration_id: str,
    candidate_configuration_id: str,
    baseline_source_id: str,
    candidate_source_id: str,
    baseline_sensor_ids: list[str],
    candidate_sensor_ids: list[str],
    ground_truth: list[GroundTruth],
    baseline_predictions: list[Prediction],
    candidate_predictions: list[Prediction],
    baseline_evaluation_result: EvaluationResult,
    candidate_evaluation_result: EvaluationResult,
    tolerance_ms: float,
    coverage_warning_threshold_pp: float = DEFAULT_COVERAGE_WARNING_THRESHOLD_PP,
    min_common_sample_count: int = DEFAULT_MIN_COMMON_SAMPLE_COUNT,
) -> PairwiseComparison:
    """The one place all of the above composes into a PairwiseComparison.
    Takes already-fetched domain objects - no sqlite3/fastapi import here;
    Phase 22's API layer owns fetching baseline_evaluation_result etc. from
    the repository and resolving source_id ambiguity before calling this."""
    added_sensors, removed_sensors, relationship = classify_relationship(
        baseline_sensor_ids, candidate_sensor_ids,
    )

    reported_side = build_comparison_side(
        comparison_metrics_from_evaluation_result(baseline_evaluation_result),
        comparison_metrics_from_evaluation_result(candidate_evaluation_result),
    )

    baseline_match = match_by_timestamp(ground_truth, baseline_predictions, tolerance_ms)
    candidate_match = match_by_timestamp(ground_truth, candidate_predictions, tolerance_ms)
    common_gt_ids = intersect_matched_ground_truth_ids(baseline_match, candidate_match)

    baseline_common_cm = evaluate_classification(filter_matched_by_ground_truth_ids(baseline_match, common_gt_ids))
    candidate_common_cm = evaluate_classification(filter_matched_by_ground_truth_ids(candidate_match, common_gt_ids))

    common_side = build_comparison_side(
        comparison_metrics_from_classification(baseline_common_cm),
        comparison_metrics_from_classification(candidate_common_cm),
        common_sample_count=len(common_gt_ids),
    )

    if baseline_configuration_id == candidate_configuration_id:
        # A self-comparison is still computed - never hidden, per the
        # "never silently compare incomparable configurations" rule - but
        # it isn't a real comparison, so it's unconditionally invalid
        # regardless of what assess_validity's threshold-based rules
        # would otherwise conclude.
        validity = ComparisonValidity(
            status='invalid', reasons=['baseline and candidate are the same configuration'],
        )
    else:
        validity = assess_validity(reported_side, common_side, coverage_warning_threshold_pp, min_common_sample_count)

    return PairwiseComparison(
        session_id=session_id,
        task=task,
        baseline_configuration_id=baseline_configuration_id,
        candidate_configuration_id=candidate_configuration_id,
        baseline_source_id=baseline_source_id,
        candidate_source_id=candidate_source_id,
        tolerance_ms=tolerance_ms,
        added_sensors=added_sensors,
        removed_sensors=removed_sensors,
        relationship=relationship,
        reported=reported_side,
        common_set=common_side,
        validity=validity,
        computed_at=datetime.now(timezone.utc),
    )
