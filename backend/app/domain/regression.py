"""Regression domain model (v0.8, Phase 83). Generic scalar regression -
MAE/RMSE/bias/median-absolute-error, unit-aware. Pure functions/
dataclasses - no persistence, no FastAPI, no ROS, same discipline as
matching.py/metrics.py/detection.py.

## No matching engine of its own

Unlike detection, one already-timestamp-matched `MatchedPair` *is* one
regression sample already - there is no second, object-level matching
pass here. `match_by_timestamp` (matching.py) stays the only association
step, completely untouched.

## Schema: `{"value": <float>, "unit": <str>}`, both sides

Same "never a change to GroundTruth/Prediction" posture as detection.py -
`GroundTruth.value`/`Prediction.value` stay the same generic
`dict[str, Any]` they always were; `parse_regression_value` is this
evaluator's own `extract_label` equivalent, raising `ValueError` for
anything malformed.

## A mismatched unit raises, never silently degrades to N/A

If a matched pair's ground-truth unit and prediction unit differ, or if
the samples that make it into one aggregate span more than one distinct
unit, this raises rather than averaging incompatible quantities - the
exact same rule `compute_resource_metric_summary` (v0.7,
`resources.py`) already applies to mixed-unit resource observations. No
automatic unit conversion exists or is planned.

## No relative/percentage error in v0.8

The master prompt marks `absolute_percentage_error` explicitly optional
(§21) and warns it needs care near a zero ground-truth value ("relative
error may be N/A"). Nothing in this release's own scope (RideSafe/
PropertyWatch/Robot-Drone-Lab's planned `distance_estimation` tasks)
demonstrates a need for it, so it is not implemented - deferred, not
silently dropped. `RegressionMetrics` has no `relative_error`/
`percentage_error` field, grep-verified by a dedicated test the same way
detection.py's own module already verifies "no AP/mAP."

## No vector regression in v0.8

Explicitly deferred (v0.8 architecture review Q21) - nothing in the
planned demos needs it, and `value` staying a plain number keeps adding
it later additive, not breaking. A `value` that's a list is rejected
with a clear, dedicated error message (not just "must be a number") -
§38's "clear errors" requirement.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

from app.domain.evaluator_output import EvaluatorOutput
from app.domain.matching import MatchResult
from app.domain.models import MetricValue
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, MetricDescriptor, PluginDescriptor, PluginType


def _is_number(value: Any) -> bool:
    # bool is a subclass of int in Python - a JSON `true`/`false` must
    # never silently pass as 0/1 here. Same helper as detection.py's own
    # (duplicated, not shared - three lines, not worth a module for).
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class RegressionSample:
    ground_truth_value: float
    prediction_value: float
    unit: str


def parse_regression_value(value: dict[str, Any], context: str) -> tuple[float, str]:
    if 'value' not in value:
        raise ValueError(f"{context} has no 'value' field - not a regression task?")
    raw_value = value['value']
    if isinstance(raw_value, list):
        raise ValueError(
            f'{context}.value is a vector (list) - vector regression is not supported in v0.8, only scalar'
        )
    if not _is_number(raw_value):
        raise ValueError(f'{context}.value must be a number, got {raw_value!r}')
    if 'unit' not in value:
        raise ValueError(f"{context} has no 'unit' field")
    unit = str(value['unit']).strip()
    if not unit:
        raise ValueError(f'{context}.unit must be a non-empty string')
    return float(raw_value), unit


def build_regression_samples(match_result: MatchResult) -> list[RegressionSample]:
    """One `RegressionSample` per already-timestamp-matched pair. Raises
    `ValueError` if a pair's ground-truth and prediction units disagree -
    never silently N/A for that one sample, since a systematic unit bug
    should surface loudly, not hide inside an aggregate (same posture
    `extract_label`'s missing-field error already has)."""
    samples: list[RegressionSample] = []
    for pair in match_result.matched:
        gt_value, gt_unit = parse_regression_value(pair.ground_truth.value, 'ground_truth')
        pred_value, pred_unit = parse_regression_value(pair.prediction.value, 'prediction')
        if gt_unit != pred_unit:
            raise ValueError(f"unit mismatch: ground truth unit '{gt_unit}' != prediction unit '{pred_unit}'")
        samples.append(RegressionSample(ground_truth_value=gt_value, prediction_value=pred_value, unit=gt_unit))
    return samples


@dataclass(frozen=True)
class RegressionMetrics:
    """`None` (never a fabricated zero) whenever `sample_count == 0` -
    same `MetricValue` "no denominator, no answer" rule as everywhere
    else in this codebase. `unit` is `None` only in that same empty case;
    otherwise it is the single shared unit every contributing sample
    agreed on."""
    sample_count: int
    mae: MetricValue
    rmse: MetricValue
    bias: MetricValue
    median_absolute_error: MetricValue
    unit: str | None


def compute_regression_metrics(samples: list[RegressionSample]) -> RegressionMetrics:
    """Raises `ValueError` if the samples span more than one distinct
    unit - averaging metres with centimetres would be silently
    meaningless, the exact same rule `compute_resource_metric_summary`
    (v0.7) already applies to mixed-unit resource observations."""
    if not samples:
        return RegressionMetrics(sample_count=0, mae=None, rmse=None, bias=None, median_absolute_error=None, unit=None)

    units = {s.unit for s in samples}
    if len(units) > 1:
        raise ValueError(f'cannot aggregate regression samples with mixed units: {sorted(units)}')

    errors = [s.prediction_value - s.ground_truth_value for s in samples]
    absolute_errors = sorted(abs(e) for e in errors)
    squared_errors = [e * e for e in errors]

    return RegressionMetrics(
        sample_count=len(samples),
        mae=statistics.fmean(absolute_errors),
        rmse=math.sqrt(statistics.fmean(squared_errors)),
        bias=statistics.fmean(errors),
        median_absolute_error=statistics.median(absolute_errors),
        unit=units.pop(),
    )


class RegressionEvaluator:
    """Registered in `EVALUATOR_REGISTRY['regression']` (evaluators.py).
    `sample_count`/`matched_samples`/`unmatched_predictions`/
    `unmatched_ground_truth` on the returned `EvaluatorOutput` are the
    same frame-level counts every evaluator reports (see evaluators.py's
    own module docstring) - for regression this already coincides with
    the sample count 1:1, since one matched pair is one sample, but the
    fields are still sourced from `match_result` itself, not
    re-derived. `parameters` is accepted (protocol conformance) but
    unused - v0.8's regression evaluator has no configurable
    parameters."""
    evaluator_type = 'regression'
    format_version = '1.0'

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='multisens.builtin.evaluator.regression', name='Regression Evaluator',
            version='1.0.0', plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'evaluator_type': self.evaluator_type}, author='MultiSens', license='Apache-2.0',
            description='Scalar regression - MAE/RMSE/bias/median-absolute-error, unit-aware (v0.8).',
        )

    def metric_descriptors(self) -> list[MetricDescriptor]:
        return [
            MetricDescriptor(id='mae', higher_is_better=False),
            MetricDescriptor(id='rmse', higher_is_better=False),
            # bias has no defined direction - closer to zero is better,
            # neither "higher" nor "lower" is uniformly better, the
            # canonical None example (see MetricDescriptor's own
            # docstring).
            MetricDescriptor(id='bias', higher_is_better=None),
            MetricDescriptor(id='median_absolute_error', higher_is_better=False),
        ]

    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput:
        samples = build_regression_samples(match_result)
        metrics = compute_regression_metrics(samples)

        return EvaluatorOutput(
            sample_count=len(match_result.matched) + len(match_result.unmatched_ground_truth),
            matched_samples=len(match_result.matched),
            unmatched_predictions=len(match_result.unmatched_predictions),
            unmatched_ground_truth=len(match_result.unmatched_ground_truth),
            metrics={
                'mae': metrics.mae,
                'rmse': metrics.rmse,
                'bias': metrics.bias,
                'median_absolute_error': metrics.median_absolute_error,
            },
            details={'unit': metrics.unit} if metrics.unit is not None else None,
        )
