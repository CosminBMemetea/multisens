# Evaluator Interface Contract (v0.8)

The authoritative reference for the generic evaluator abstraction
introduced in v0.8: the `Evaluator` protocol, `EvaluatorOutput`, the
static registry, `evaluator_type` persistence, and backward
compatibility with every pre-v0.8 classification workflow. See
[evaluation.md](evaluation.md) for the timestamp-matching layer this
sits on top of (unchanged since v0.2),
[detection-evaluation.md](detection-evaluation.md) and
[regression-evaluation.md](regression-evaluation.md) for the two new
evaluators this release adds, and
[comparison.md](comparison.md)/[decision-support.md](decision-support.md)
for how the rest of the system consumes any evaluator's output without
knowing which one produced it.

## What this layer answers

> Beyond classification, what other kinds of ground-truth/prediction
> comparison can MultiSens score, and how do they plug in without
> forking the matching, comparison, coverage, or decision engines?

Through v0.7, `evaluate_classification` was the only metric engine that
existed - a real gap, since `GroundTruth.value`/`Prediction.value` were
already generic dicts (v0.2's own design). v0.8 closes it with a small,
closed interface that any future evaluator implements, plus the first
two real implementations beyond classification: object detection and
scalar regression.

## The `Evaluator` protocol

[`backend/app/domain/evaluators.py`](../backend/app/domain/evaluators.py):

```python
class Evaluator(Protocol):
    evaluator_type: str
    format_version: str
    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput: ...
```

- **`match_result`** is `matching.py`'s own `MatchResult` - the exact
  same timestamp-matched output classification, detection, and
  regression all consume identically. No evaluator re-derives which GT
  frame corresponds to which prediction frame; that question stays
  `match_by_timestamp`'s alone, completely untouched since v0.2.
- **`parameters`** is a caller-supplied `dict[str, Any]`, opaque to
  everything except the evaluator that reads it. Classification and
  regression ignore it entirely (protocol conformance only);
  `object_detection` requires `confidence_threshold`/`iou_threshold`
  inside it, both **required, no default** - see
  [detection-evaluation.md](detection-evaluation.md#thresholds-both-required-no-default).
- **`evaluate()` raises `ValueError`** for any malformed matched value
  (a missing `'label'` field, an invalid bbox, a unit mismatch, a
  missing required parameter) - never a crash. Every API caller catches
  this generically and returns `422`, the identical treatment
  classification's own missing-label case already had since v0.2.

## `EvaluatorOutput`: one shape, three producers

[`backend/app/domain/evaluator_output.py`](../backend/app/domain/evaluator_output.py)
(extracted from `evaluators.py` mid-development to break a circular
import with `detection.py`; re-exported from `evaluators.py` for every
existing import):

```python
@dataclass(frozen=True)
class EvaluatorOutput:
    sample_count: int
    matched_samples: int
    unmatched_predictions: int
    unmatched_ground_truth: int
    metrics: dict[str, MetricValue]       # MetricValue = float | None
    details: dict[str, Any] | None = None
```

**The four count fields stay frame-level for every evaluator, always** -
they describe how much of the underlying `match_by_timestamp` frame
association succeeded, never something evaluator-specific. For
classification these already are frame counts (one row = one sample);
`DetectionEvaluator` reports the identical frame-level counts read
straight off its own `MatchResult`, never object-level TP/FP/FN counts,
which live in `metrics`/`details` instead. Overloading these fields to
mean something different per evaluator was explicitly rejected in the
v0.8 architecture review - a `sample_count` that means "frames" for one
evaluator and "objects" for another would make every downstream
consumer (coverage, comparison, the frontend) evaluator-aware just to
read a count correctly.

**`metrics` values are always `MetricValue` (`float | None`)** - the
same "no denominator, no fabricated zero" rule every prior layer in this
project already enforces (see
[provenance.md](provenance.md#the-cross-cutting-rules-and-where-each-is-enforced)),
now uniform across all three evaluators.

**`details` is evaluator-specific, structured, and optional** -
classification's confusion matrix, detection's per-class breakdown and
parameter echo, regression's shared unit. Never inspected generically by
any consumer; each evaluator's own `evaluate_session` caller (or
frontend component) reads it only when it already knows which evaluator
produced it (via `evaluator_type`).

## `EVALUATOR_REGISTRY`: a static dict, only ever holding working entries

```python
EVALUATOR_REGISTRY: dict[str, Evaluator] = {
    'classification': ClassificationEvaluator(),
    'object_detection': DetectionEvaluator(),
    'regression': RegressionEvaluator(),
}
```

Started **empty** when the protocol/`EvaluatorOutput` shipped (Phase 78)
and was populated one evaluator at a time only once each one's
`evaluate()` was real and tested - `DetectionEvaluator` was deliberately
**not** registered the moment its schema/matching code existed (Phases
80-81), only once session-level aggregation was complete (Phase 82).
The registry never holds a stub. An `evaluator_type` string not present
as a key is always a clean `422` (`unknown evaluator_type '...' -
supported: [...]`), **never** a silent fallback to classification - the
one behavior this whole layer is built around never doing.

## `evaluator_type` on `EvaluationResult`: explicit per call, not a registry entity

A `TaskDefinition` registry entity (task name -> evaluator type,
persisted once and looked up on every subsequent call) was considered
and rejected in the architecture review, the same "don't add an entity
before scope demonstrates the need" discipline that rejected v0.3's
`Experiment` and v0.7's `ResourceMeasurementRun`. Instead,
`evaluator_type` is stated explicitly on every `/evaluate` call (mirroring
`tolerance_ms`'s own no-silent-default posture) and recorded directly on
the resulting `EvaluationResult` row, which is therefore fully
self-describing - reading one row never requires a second lookup to know
what produced it.

```python
class EvaluateRequest(BaseModel):
    task: str
    configuration_ids: list[str] | None = None
    tolerance_ms: float = DEFAULT_TOLERANCE_MS
    evaluator_type: str = 'classification'   # backward-compat default, not a guess
    parameters: dict[str, Any] = {}
```

`evaluator_type` defaults to `'classification'` **specifically because**
that is what every pre-v0.8 caller already got before this field
existed - not an arbitrary choice. Every migrated request body that
omits it entirely keeps working byte-for-byte unchanged.

## Persistence: two new nullable/defaulted columns, not new tables

Migration `0005_evaluation_result_evaluator_type.sql`, the exact same
pattern migration `0002` used to add `tolerance_ms`:

```sql
ALTER TABLE evaluation_results ADD COLUMN evaluator_type TEXT NOT NULL DEFAULT 'classification';
ALTER TABLE evaluation_results ADD COLUMN details TEXT;  -- nullable JSON
```

Every pre-v0.8 row automatically becomes `evaluator_type='classification'`
on migration - no backfill script needed, no data loss, no behavior
change for anything already stored. A dedicated per-evaluator table
(`DetectionResult`, `RegressionResult`, ...) was considered and rejected:
`metrics`/`details` are already generic JSON columns capable of holding
any evaluator's shape, and a separate table per evaluator would mean
every future consumer (comparison, coverage, the frontend) needs a
type-specific join instead of one uniform `EvaluationResult` read.

## Backward compatibility: proven, not assumed

Three separate guarantees, each with a dedicated test:

- **The default.** Omitting `evaluator_type` in a request body still
  evaluates as classification, identical output shape
  (`test_evaluate_omitted_evaluator_type_defaults_to_classification`).
- **The byte-for-byte match.** `ClassificationEvaluator.evaluate()`
  produces output identical to the pre-v0.8 `evaluate_classification`
  call it wraps, field by field
  (`test_classification_evaluator_matches_evaluate_classification_byte_for_byte`).
- **The full old-style round trip.** A complete evaluate+compare
  workflow using zero v0.8 request fields anywhere - no `evaluator_type`,
  no `parameters`, on either call - still defaults to classification and
  matches pre-v0.8 behavior exactly, proven at the real HTTP API level
  in Phase 90's robustness pass
  (`test_pre_v0_8_classification_workflow_unchanged_with_no_v0_8_fields_in_any_request`).

## Every downstream layer is already evaluator-blind

`coverage.py`, `analysis.py`, `decision.py`, and `resources.py` read
`EvaluationResult.metrics[metric_name]` by string key - none of them
ever branched on evaluator type, because the acceptance-criterion
grammar (`metric`/`operator`/`value`, v0.4) never needed to know where a
metric came from. The v0.8 architecture review's own code-reading
confirmed this by grep, and Phase 85 proved it end to end with a single
mixed-task profile (classification + detection + regression requirements
on the same two configurations) run through `/coverage`,
`/decision-analysis`, `/tradeoffs`, and `/compare` - zero engine code
changed to make it work. See
[comparison.md](comparison.md#generic-across-evaluator-types-v08) for
how the comparison layer specifically handles a mismatched evaluator-type
pair.

## API surface

```
POST   /api/sessions/{id}/evaluate      # body: {task, configuration_ids?, tolerance_ms?, evaluator_type?, parameters?}
GET    /api/sessions/{id}/evaluation    # every persisted result, any evaluator_type, together
GET    /api/sessions/{id}/timeline      # classification-only - see below
```

`/timeline` is explicitly checked against the persisted
`evaluator_type` and returns a clear, dedicated `422` for anything else
(`"/timeline only supports classification results - ... evaluated with
evaluator_type 'object_detection'"`) - a real, documented scope boundary
(a label-vs-label strip has no detection/regression analogue in v0.8),
never an accidental failure inside `extract_label`.

## Frontend: a discriminated union, not a generic blob

[`frontend/src/types.ts`](../frontend/src/types.ts) types
`EvaluationResult` as a discriminated union
(`ClassificationEvaluationResult | DetectionEvaluationResult |
RegressionEvaluationResult | GenericEvaluationResult`) keyed on
`evaluator_type`, with `isClassificationResult`/`isDetectionResult`/
`isRegressionResult` type guards - no `any` anywhere in the evaluation
display path. An `evaluator_type` this frontend build doesn't recognize
(a hypothetical future evaluator shipped by a newer backend) falls
through to the open `GenericEvaluationResult` variant: the summary table
still renders every raw metric key generically
(`summaryColumnsFor`'s sorted-key fallback,
[`frontend/src/evaluationColumns.ts`](../frontend/src/evaluationColumns.ts)),
and the detail panel shows an explicit "no evaluator-specific
visualization available" message - never a broken page. This forward-
compatibility path has no live route through the current backend
(`EVALUATOR_REGISTRY` structurally prevents ever persisting an unknown
type), so it's covered by a dedicated unit test against a hand-built
mock object instead of Playwright
(`frontend/src/evaluationResult.test.ts`).

## Known evaluator-layer limitations

See [limitations.md](limitations.md) for the current authoritative list;
the ones specific to this layer: no `TaskDefinition` registry (evaluator
type is stated per call, not remembered), no result history (re-running
`/evaluate` still overwrites, unchanged since v0.2), and the two
evaluator-specific limitation sets documented in
[detection-evaluation.md](detection-evaluation.md#known-limitations) and
[regression-evaluation.md](regression-evaluation.md#known-limitations).
