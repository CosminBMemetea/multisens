# Regression Evaluation Contract (v0.8)

The authoritative reference for the `regression` evaluator: the scalar
value/unit schema, MAE/RMSE/bias/median-absolute-error, unit handling
(both the per-pair and cross-sample rules), and the deliberate
deferrals (relative/percentage error, vector regression). See
[evaluators.md](evaluators.md) for the generic `Evaluator`
interface/registry this plugs into, and
[detection-evaluation.md](detection-evaluation.md) for the other new
v0.8 evaluator.

## What this layer answers

> For a continuous quantity - distance, range, a physical measurement -
> how far off are the predictions from ground truth, on average and at
> the extremes?

The generic v0.8 architecture already answers this without any new
domain entity: `distance_estimation` (Robot/Drone Sensing demo) is a
**task profile over this evaluator**, not a hardcoded `range_estimation`
concept - the same "introduce a value schema, never new evaluator logic
per task name" discipline detection's own `obstacle_detection` follows.

## No matching engine of its own

Unlike detection, one already-timestamp-matched pair from
[`matching.py`](../backend/app/domain/matching.py) **is** one regression
sample already - there is no second, object-level matching pass here.
`match_by_timestamp` stays the only association step, completely
untouched.

## Schema: `{"value": <float>, "unit": <str>}`, both sides

Same "never a change to `GroundTruth`/`Prediction`" posture as
detection: `parse_regression_value` is this evaluator's own
`extract_label` equivalent, raising `ValueError` for anything malformed.

```json
// GroundTruth.value and Prediction.value - identical shape
{"value": 3.25, "unit": "m"}
```

- **`value`** must be a plain number. A list is rejected with a
  dedicated, clear message (`"value is a vector (list) - vector
  regression is not supported in v0.8, only scalar"`) - not just a
  generic "must be a number," since a caller sending a vector is making
  a different, understandable mistake that deserves a different answer.
- **`unit`** must be a non-empty string. Fully open vocabulary at
  ingestion - `"m"`, `"meters"`, `"ft"` are all accepted as distinct
  strings; nothing infers unit equivalence or converts between them (the
  same open-unit posture `ResourceObservation.unit` already has, v0.7).

## A mismatched unit raises, never silently degrades to N/A

Two distinct rules, two distinct failure points, both proven at the real
HTTP API level (Phase 90's robustness pass):

- **Per-pair mismatch** (`build_regression_samples`): if one matched
  ground-truth/prediction pair's units disagree (`gt.unit != pred.unit`),
  that's a systematic bug in the data itself - it raises immediately,
  never silently drops that one sample from the aggregate.
- **Cross-sample mismatch** (`compute_regression_metrics`): if the
  samples that make it into one aggregate span more than one *agreed*
  unit (e.g. one matched pair used `"m"` throughout, another used `"ft"`
  throughout), averaging them would be silently meaningless - this
  raises too, the exact same rule
  `compute_resource_metric_summary` (v0.7) already applies to
  mixed-unit resource observations.

Both cases become a clean `422`, never an unhandled `500` and never a
quietly-wrong average.

## Metrics

`compute_regression_metrics`, over `errors[i] = prediction[i] - ground_truth[i]`:

- **MAE** (mean absolute error) = mean(`|error|`).
- **RMSE** (root mean squared error) = sqrt(mean(`error²`)).
- **`bias`** = mean(`error`) - signed, so a systematic over/under-estimate
  is visible directly (positive = predictions run high), distinct from
  MAE's magnitude-only view.
- **`median_absolute_error`** = median(`|error|`) - robust to outliers
  MAE/RMSE would be pulled around by.
- **`unit`** (in `details`, not `metrics`) - the single shared unit every
  contributing sample agreed on; `None` only in the empty-sample case.

All four numeric fields are `None` (never a fabricated `0.0`) whenever
`sample_count == 0` - the same `MetricValue` rule as everywhere else in
this codebase.

## No relative/percentage error in v0.8

Deliberately deferred, not silently dropped: relative error needs care
near a zero ground-truth value (it can blow up or become undefined
exactly where it matters least), and nothing in this release's planned
demos (RideSafe/PropertyWatch/Robot-Drone-Lab) demonstrated a real need
for it. `RegressionMetrics` has no `relative_error`/`percentage_error`
field anywhere - grep-verified by a dedicated test
(`test_no_relative_or_percentage_error_field_exists`), the same
discipline detection's own "no AP/mAP" guard uses.

## No vector regression in v0.8

Also an explicit architecture-review deferral: nothing in the planned
demos needs multi-dimensional regression (e.g. a 3D position estimate),
and keeping `value` a plain scalar number now means adding vector
support later is additive, not a breaking schema change. A `value` that
arrives as a list is rejected with a clear, dedicated error message (see
above) rather than a generic type error.

## No configurable parameters

Unlike detection, `RegressionEvaluator.evaluate()` accepts a
`parameters` argument for protocol conformance but never reads it -
there is no confidence/IoU-style threshold concept for a continuous
value. `/evaluate` and `/compare` both work with `parameters` entirely
omitted for this evaluator, proven explicitly
(`test_compare_regression_configurations_needs_no_parameters`).

## `EvaluatorOutput`'s frame-count fields

`sample_count`/`matched_samples`/`unmatched_predictions`/
`unmatched_ground_truth` are the same frame-level counts every evaluator
reports (see [evaluators.md](evaluators.md)) - for regression this
already coincides with the sample count 1:1 (one matched pair is one
sample), but the fields are still sourced from `match_result` itself,
never re-derived from the metrics. A comparison's `common_set` therefore
has no frame-vs-object distinction to make at all here, unlike
detection's own common-set semantics - pinned down explicitly by
`test_compare_common_set_sample_count_for_regression_equals_shared_matched_pairs`.

## API surface

Same generic `/evaluate`/`/compare` endpoints every evaluator shares
(see [evaluators.md](evaluators.md#api-surface)):

```json
POST /api/sessions/{id}/evaluate
{"task": "distance_estimation", "evaluator_type": "regression"}
```

## Frontend

`EvaluationPanel`'s regression-specific note
(`RegressionUnitNote`, [`frontend/src/components/EvaluationPanel.tsx`](../frontend/src/components/EvaluationPanel.tsx))
shows the shared unit alongside the MAE/RMSE/bias/median summary
columns. `/timeline` is gated off entirely for regression results (see
[evaluators.md](evaluators.md#api-surface)).

## Reference demo

Robot/Drone Sensing's `distance_estimation` task: a dedicated range
sensor (MAE 0.06 m) versus a depth-camera-derived estimate (MAE 0.30 m),
both configurations' error patterns built from a fixed, deterministic
5-value error cycle (never randomness) so every number is exactly
hand-computable - see
[examples/profiles/README.md](../examples/profiles/README.md) and
`backend/tests/test_robot_drone_demo.py`.

## Known limitations

See [limitations.md](limitations.md) for the current authoritative list;
the ones specific to this evaluator: no relative/percentage error (by
design, see above), no vector regression (by design, see above), no
per-quantile or full-distribution reporting beyond MAE/RMSE/bias/median.
