# Object Detection Evaluation Contract (v0.8)

The authoritative reference for the `object_detection` evaluator: the
bounding-box convention, IoU, the greedy per-frame matching algorithm and
why it isn't Hungarian assignment, thresholds, session-level metrics, and
the deliberate absence of AP/mAP. See
[evaluators.md](evaluators.md) for the generic `Evaluator`
interface/registry this plugs into, and
[regression-evaluation.md](regression-evaluation.md) for the other new
v0.8 evaluator.

## What this layer answers

> For a set of detected objects per frame, how well do they match the
> annotated ground-truth objects in that same frame?

Detection is a genuinely different question from classification's
single-label-per-sample comparison: a frame can contain zero, one, or
many objects on either side, and a prediction can be right about
*whether* something is there but wrong about *where*. This evaluator
answers it with object-level precision/recall/F1 and mean matched IoU -
deliberately not AP/mAP (see below).

## Schema: `{"objects": [...]}` / `{"detections": [...]}`, never a change to `GroundTruth`/`Prediction`

Same posture `regression.py` and classification's own `extract_label`
already established: `GroundTruth.value`/`Prediction.value` stay the
same generic `dict[str, Any]` they always were.
[`backend/app/domain/detection.py`](../backend/app/domain/detection.py)'s
`parse_ground_truth_objects`/`parse_detections` are this evaluator's own
`extract_label` equivalent - they raise a plain `ValueError` for
anything malformed, turned into a `422` the same generic way every
evaluator's parse errors are.

```json
// GroundTruth.value
{"objects": [{"id": "o1", "label": "vehicle", "bbox": {"x": 0.3, "y": 0.3, "width": 0.2, "height": 0.2}}]}

// Prediction.value
{"detections": [{"label": "vehicle", "confidence": 0.92, "bbox": {"x": 0.35, "y": 0.3, "width": 0.2, "height": 0.2}}]}
```

- **`objects[].id`** is scoped to one frame, unique within it - a
  duplicate id within one frame is rejected. It is **not** a cross-frame
  tracking identity; object tracking across frames is explicitly out of
  scope for v0.8 (see [limitations.md](limitations.md)).
- **`detections[].confidence`** is required, `[0.0, 1.0]`.

## Bbox convention: normalized `[0.0, 1.0]`, top-left `x`/`y`/`width`/`height` - only

One canonical representation, not two divergent modes - matching this
project's existing closed-`Literal` posture elsewhere (`AcceptanceOperator`,
`ResourceQuality`) rather than hedging with an alternate pixel-coordinate
mode gated on a resolution field. No pixel-coordinate path exists in
v0.8; revisit only if a real, demonstrated need shows up.

A `BoundingBox` is always valid by construction:

- `x`, `y` within `[0.0, 1.0]`.
- `width`, `height` strictly positive - a zero-area box can never
  represent a real detected/annotated object, stricter than "reject only
  negative width/height."
- `x + width <= 1.0` and `y + height <= 1.0` - a box hanging off the edge
  of a normalized frame isn't geometrically meaningful. Touching the edge
  exactly (`x + width == 1.0`) is allowed.

## IoU

Standard axis-aligned intersection-over-union, no dependencies:

```python
def compute_iou(a: BoundingBox, b: BoundingBox) -> float:
    x_left, y_top = max(a.x, b.x), max(a.y, b.y)
    x_right, y_bottom = min(a.x + a.width, b.x + b.width), min(a.y + a.height, b.y + b.height)
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    intersection = (x_right - x_left) * (y_bottom - y_top)
    return intersection / (a.width * a.height + b.width * b.height - intersection)
```

Two boxes only touching at an edge (zero-area intersection) return
`0.0`, not a division-by-zero guard - `BoundingBox`'s own construction
guarantee (always positive area) means the union denominator can never
be zero.

## Object matching is a second pass, strictly within an already-frame-matched pair

`compute_detection_evidence` takes a `MatchResult` -
[`matching.py`](../backend/app/domain/matching.py)'s own, completely
untouched, timestamp-based frame association - and performs object-level
matching **within** each already-matched (one GT row, one Prediction
row) pair. It never re-derives which GT frame corresponds to which
prediction frame; that question stays `match_by_timestamp`'s alone. An
entire frame that timestamp matching couldn't pair at all
(`unmatched_ground_truth`/`unmatched_predictions`) has no counterpart to
match objects against at all - every object in an unmatched GT frame is
a false negative, every detection in an unmatched prediction frame is a
false positive, reported per unmatched frame explicitly, never folded
into the matched-frame numbers.

## Greedy IoU matching, not Hungarian assignment

Sorted by descending IoU (not prediction-insertion order), with a
deterministic tie-break by `(gt_index, detection_index)`:

```python
candidates.sort(key=lambda c: (-c[0], c[1], c[2]))  # (iou, gt_index, det_index)
```

This project has zero numerical dependencies anywhere (no numpy/scipy -
even v0.7's p95 percentile was hand-rolled to avoid one); a Hungarian
assignment would be this codebase's first. Greedy-with-a-documented-
tiebreak is this project's own established precedent -
`match_by_timestamp` already works exactly this way for frame matching.
The trade-off is honest, not hidden: in a dense, multi-object frame with
overlapping candidate pairs, greedy assignment can produce a
non-globally-optimal total-IoU match (a case Hungarian would avoid) -
`test_greedy_matching_can_be_locally_suboptimal_by_design` pins this
down explicitly as a known, accepted limitation, never a silent bug.

## Label filtering happens before IoU, not after

A GT object and a detection are only ever matching *candidates* if they
share the same `label` - a correctly-localized-but-wrong-label detection
counts as both a miss (the GT object is unmatched -> false negative) and
a false positive (the detection is unmatched), never partial credit.
Same posture classification already has for a wrong label: simply wrong.

## Thresholds: both required, no default

```python
@dataclass(frozen=True)
class DetectionParameters:
    confidence_threshold: float
    iou_threshold: float
```

Neither has a hidden `0.5` fallback - a silent default would be exactly
the "arbitrary regulatory-looking default" this project's culture
already rejects on principle (`DecisionPolicy` has no default either).
Omitting either from `/evaluate`'s `parameters` is a clean `422`
(`"object_detection requires an explicit 'confidence_threshold'
parameter - no default"`), never a silently-assumed value.

**`confidence_threshold` gates candidacy before matching, never after** -
predictions below it are dropped entirely before the greedy matching
pass runs, so a filtered-out detection contributes neither a true
positive nor a false positive; it simply doesn't exist for this call.

**`iou_threshold` gates candidacy, not just a post-hoc label** - a
same-label pair with IoU below threshold is never a matching candidate
at all; it cannot be forced into a match just because nothing else is
available. This is what makes "IoU below threshold" produce a false
positive *and* a false negative (both sides genuinely unmatched), never
a low-quality match reported as correct.

## Session-level metrics

`aggregate_detection_metrics` sums every frame's evidence:

- **`precision`** = TP / (TP + FP), **`recall`** = TP / (TP + FN),
  **`f1`** via the shared `compute_f1` (the exact same formula
  classification's own macro-F1 already uses, promoted to a reusable
  function rather than duplicated).
- **`mean_iou_matched`** = mean IoU over matched pairs only - `None`
  (never a fabricated `0.0`) whenever nothing matched, the same
  `MetricValue` "no denominator, no answer" rule as everywhere else.
- **`true_positives`/`false_positives`/`false_negatives`** carried as
  plain metric floats alongside the ratios, so a summary table can show
  raw counts without a second API call.

## Per-class breakdown lives in `details`, not `metrics`

`details.per_class` keys by label, one `{true_positives, false_positives,
false_negatives, precision, recall, f1}` block per label that appeared
anywhere as a TP/FP/FN - a label that never appeared has no entry at all
(nothing to report, not even an N/A row). `details.parameters` echoes
the `confidence_threshold`/`iou_threshold` actually used, so a result
row is self-describing without a second lookup - "do not hide the
parameters that produced this number" (see
[provenance.md](provenance.md)).

## `EvaluatorOutput`'s frame-count fields stay frame-level, not object-level

`sample_count`/`matched_samples`/`unmatched_predictions`/
`unmatched_ground_truth` describe how much of `match_by_timestamp`'s own
frame matching succeeded - the same meaning every evaluator's output
gives these fields (see [evaluators.md](evaluators.md)), never
overloaded to mean object counts here. A comparison's `common_set`
therefore counts **shared matched GT frames**, not shared matched
objects - proven explicitly by
`test_common_set_comparison_means_same_matched_gt_frames_for_detection`
(one frame with two GT objects still counts as one common sample).

## No AP/mAP, anywhere

The v0.8 architecture review considered and explicitly rejected Average
Precision/mean Average Precision: a simplified or incorrect
implementation would be worse than omitting it entirely, and this
project has no interpolation/PR-curve infrastructure to build a correct
one on short notice. `aggregate_detection_metrics`'s own output has no
`ap`/`map` field anywhere - grep-verified by a dedicated test
(`test_no_ap_or_map_field_exists_anywhere_in_detection_output`), the
same discipline this project already uses to verify "no magic score"
after every phase that could plausibly introduce one (see
[provenance.md](provenance.md#the-cross-cutting-rules-and-where-each-is-enforced)).

## Registered as of Phase 82, not before

`EVALUATOR_REGISTRY['object_detection']` was populated only once
`evaluate()` was complete and tested (Phase 82) - the schema (Phase 80)
and per-frame matching (Phase 81) shipped first but deliberately stayed
unregistered, honoring the registry's own "only ever holds fully-working
entries" rule (see [evaluators.md](evaluators.md)).

## API surface

Same generic `/evaluate`/`/compare` endpoints every evaluator shares
(see [evaluators.md](evaluators.md#api-surface)); this evaluator's own
required request shape:

```json
POST /api/sessions/{id}/evaluate
{"task": "obstacle_detection", "evaluator_type": "object_detection",
 "parameters": {"confidence_threshold": 0.5, "iou_threshold": 0.5}}
```

`/compare`'s common-set re-evaluation needs the same `parameters` (each
side's *original* `/evaluate` call may have used different values, the
same "each side may use a different `tolerance_ms`" posture the reported
comparison already has) - a real bug caught before this evaluator ever
shipped a comparison feature: the common-set path used to call
`evaluate(match_result, {})` unconditionally, crashing any
`object_detection` comparison with an unhandled `500` until
`CompareRequest.parameters` was added (Phase 84).

## Frontend

`EvaluationPanel`'s detection-specific view
(`DetectionPerClassView`, [`frontend/src/components/EvaluationPanel.tsx`](../frontend/src/components/EvaluationPanel.tsx))
renders the per-class table - never a confusion matrix, a fundamentally
different question (which classes get confused for which) that
object-level TP/FP/FN doesn't answer. `/timeline` is gated off entirely
for detection results (see [evaluators.md](evaluators.md#api-surface)).

## Reference demos

RideSafe (front vs. rear camera detection quality, F1 0.80 vs. 0.57),
PropertyWatch (entrance/storage/indoor, F1 0.821/0.667/0.529), and
Robot/Drone Sensing (camera vs. depth-derived detection, F1 0.757 vs.
0.611) - see [examples/profiles/README.md](../examples/profiles/README.md)
for the full by-construction derivation of every number, independently
re-derived in each demo's own `backend/tests/test_*_demo.py`.

## Known limitations

See [limitations.md](limitations.md) for the current authoritative list;
the ones specific to this evaluator: no AP/mAP (by design, see above),
greedy matching can be locally suboptimal in dense multi-object frames
(by design, see above), no cross-frame object tracking, no segmentation
masks, no oriented/rotated bounding boxes, no pixel-coordinate input
mode.
