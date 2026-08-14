"""Object-detection domain model (v0.8, Phase 80-82). Phase 80 shipped
the schema/validation; Phase 81 added object-level IoU matching within an
already-timestamp-matched frame; Phase 82 aggregates that per-frame
evidence into session-level metrics and completes `DetectionEvaluator.
evaluate()`, finally registering it in `EVALUATOR_REGISTRY`. Pure
functions/dataclasses - no persistence, no FastAPI, no ROS, same
discipline as matching.py/metrics.py.

## `EvaluatorOutput`'s frame-count fields stay frame-level, not object-level

`sample_count`/`matched_samples`/`unmatched_predictions`/
`unmatched_ground_truth` describe the same thing for every evaluator
type - how much of the underlying timestamp-based frame matching
(matching.py) succeeded - never overloaded to mean something
evaluator-specific. For classification these already are frame counts
(one row = one sample); `DetectionEvaluator.evaluate()` reports the
identical frame-level counts read straight off its own `MatchResult`,
not object counts. Object-level TP/FP/FN/precision/recall/F1/
mean_iou_matched - a genuinely different, detection-specific concern -
lives in `metrics`/`details` instead, never overloading the shared
frame-count fields.

## No AP/mAP, anywhere

v0.8 architecture review Q16, confirmed: a simplified/incorrect mAP
would be worse than omitting it. `aggregate_detection_metrics`'s own
output has no `ap`/`map` field, grep-verified by a dedicated test
(`test_no_ap_or_map_field_exists_anywhere_in_detection_output`) the same
way this project already grep-verifies "no magic score" after every
phase that could plausibly introduce one.

## Object matching is a second pass, strictly within an already-frame-matched pair

`compute_detection_evidence` takes a `MatchResult` - matching.py's own,
completely untouched, timestamp-based frame association - and performs
object-level matching *within* each already-matched (one GT row, one
Prediction row) pair. It never re-derives which GT frame corresponds to
which prediction frame; that question stays matching.py's alone (master
prompt §14, confirmed unchanged by grep: `match_by_timestamp` has zero
diff across the whole v0.8 arc so far).

An entire *frame* that timestamp matching couldn't pair at all
(`match_result.unmatched_ground_truth`/`unmatched_predictions`) has no
counterpart to match objects against - every object in an unmatched GT
frame is a false negative, every detection in an unmatched prediction
frame is a false positive. This is reported explicitly per unmatched
frame, not folded into the matched-frame numbers.

## Greedy IoU matching, not Hungarian assignment

Sorted by descending IoU (not prediction-insertion order), deterministic
tie-break by `(gt_index, detection_index)` - v0.8 architecture review
Q12. This project has zero numerical dependencies (no numpy/scipy
anywhere, even v0.7's p95 percentile was hand-rolled to avoid one); a
Hungarian assignment would be this codebase's first. Greedy-with-a-
documented-tiebreak is this project's own established precedent -
`match_by_timestamp` already works exactly this way for frame matching,
and documents its own known limitation honestly rather than hiding it.
The same honesty applies here: in a dense, multi-object frame with
overlapping candidate pairs, greedy assignment can produce a
non-globally-optimal total-IoU match (a case Hungarian would avoid) -
`test_greedy_matching_can_be_locally_suboptimal_by_design` pins this
down explicitly so it's a known, accepted trade-off, never a silent bug.

## Label filtering happens before IoU, not after

A GT object and a detection are only ever candidates for matching if
they share the same `label` - a correctly-localized-but-wrong-label
detection counts as both a miss (the GT object is unmatched -> false
negative) and a false positive (the detection is unmatched), never
partial credit (architecture review Q13). Same posture classification
already has for a wrong label: simply wrong, not a fractional match.

## The IoU threshold gates candidacy, not just a post-hoc label

A same-label pair with IoU below `iou_threshold` is never a matching
*candidate* at all - it cannot be forced into a match just because
nothing else is available. This is what makes "IoU below threshold"
(master prompt §70) produce a false positive + false negative, not a
low-quality match.

## Why this isn't a change to GroundTruth/Prediction

`GroundTruth.value`/`Prediction.value` are deliberately generic
`dict[str, Any]` (models.py) - "task-specific interpretation of value
belongs to the metric engine, not here." Classification never taught
models.py what a `label` is (that lives in `metrics.py`'s own
`extract_label`); detection doesn't either. `parse_detections`/
`parse_ground_truth_objects` below are this evaluator's own `extract_label`
equivalent - they raise a plain `ValueError` for anything malformed,
caught and turned into a `422` the exact same way `evaluate_session`
already handles a missing classification `label` field (generic across
every evaluator since Phase 79, not classification-specific).

## Bbox convention: normalized `[0.0, 1.0]`, top-left `x`/`y`/`width`/`height` - only

One canonical representation, not two divergent modes - matches this
project's existing closed-`Literal` posture elsewhere (`AcceptanceOperator`,
`ResourceQuality`) rather than the master prompt's own "if pixel
coordinates are accepted, resolution must be present" hedge (v0.8
architecture review, Q11). No pixel-coordinate path exists in v0.8;
revisit only if a real, demonstrated need shows up. A box's coordinates
and its own `x + width`/`y + height` must both stay within `[0.0, 1.0]` -
a box hanging off the edge of a normalized frame isn't geometrically
meaningful. `width`/`height` must be strictly positive - stricter than
the master prompt's own literal "reject negative width/height": a
zero-area box can never represent a real detected/annotated object, and
rejecting it now avoids deferring a zero-area IoU edge case to Phase 81
for no real benefit.

## `DetectionEvaluator` is now registered

Phase 78's "the registry only ever contains fully-working entries"
discipline (it started empty rather than holding a classification stub)
is why Phase 80/81 deliberately held off - `evaluate()` didn't exist
yet. It does now, tested, and `EVALUATOR_REGISTRY['object_detection']`
is populated at the bottom of this file, the same way Phase 79 populated
`'classification'`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.evaluator_output import EvaluatorOutput
from app.domain.matching import MatchResult
from app.domain.metrics import compute_f1
from app.domain.models import MetricValue
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, MetricDescriptor, PluginDescriptor, PluginType

_COORDINATE_RANGE = (0.0, 1.0)


def _is_number(value: Any) -> bool:
    # bool is a subclass of int in Python - a JSON `true`/`false` must
    # never silently pass as 0/1 here.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class BoundingBox:
    """Always valid by construction - see this module's own docstring for
    the exact convention. Constructing one from already-untrusted input
    (a raw dict) goes through `_parse_bbox` below, never this
    constructor directly with unchecked values."""
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        lo, hi = _COORDINATE_RANGE
        for name, value in (('x', self.x), ('y', self.y)):
            if not (lo <= value <= hi):
                raise ValueError(f"bbox.{name} must be within [{lo}, {hi}], got {value!r}")
        if self.width <= 0.0:
            raise ValueError(f'bbox.width must be > 0, got {self.width!r}')
        if self.height <= 0.0:
            raise ValueError(f'bbox.height must be > 0, got {self.height!r}')
        if self.x + self.width > hi:
            raise ValueError(
                f'bbox extends past the normalized frame: x ({self.x}) + width ({self.width}) '
                f'= {self.x + self.width} > {hi}'
            )
        if self.y + self.height > hi:
            raise ValueError(
                f'bbox extends past the normalized frame: y ({self.y}) + height ({self.height}) '
                f'= {self.y + self.height} > {hi}'
            )


@dataclass(frozen=True)
class Detection:
    """One predicted object within a single detection Prediction row -
    `Prediction.value['detections']` is a list of these."""
    label: str
    confidence: float
    bbox: BoundingBox


@dataclass(frozen=True)
class DetectedObject:
    """One annotated object within a single detection GroundTruth row -
    `GroundTruth.value['objects']` is a list of these. `id` is scoped to
    one frame (one GroundTruth row), unique within it - not a
    cross-frame tracking identity (see master prompt §62, tracking is
    out of scope for v0.8)."""
    id: str
    label: str
    bbox: BoundingBox


def _parse_bbox(raw: Any, context: str) -> BoundingBox:
    if not isinstance(raw, dict):
        raise ValueError(f'{context}.bbox must be an object, got {raw!r}')
    missing = [key for key in ('x', 'y', 'width', 'height') if key not in raw]
    if missing:
        raise ValueError(f'{context}.bbox is missing field(s): {missing}')
    for key in ('x', 'y', 'width', 'height'):
        if not _is_number(raw[key]):
            raise ValueError(f'{context}.bbox.{key} must be a number, got {raw[key]!r}')
    return BoundingBox(x=float(raw['x']), y=float(raw['y']), width=float(raw['width']), height=float(raw['height']))


def parse_detections(value: dict[str, Any]) -> list[Detection]:
    """Parses `Prediction.value` for a detection task. Raises `ValueError`
    for anything malformed - never silently drops or repairs a bad entry,
    same "reject the whole thing loudly" posture `extract_label` already
    has for classification."""
    if 'detections' not in value:
        raise ValueError(f"value {value!r} has no 'detections' field - not an object-detection task?")
    raw_detections = value['detections']
    if not isinstance(raw_detections, list):
        raise ValueError(f"'detections' must be a list, got {raw_detections!r}")

    detections: list[Detection] = []
    for i, raw in enumerate(raw_detections):
        context = f'detections[{i}]'
        if not isinstance(raw, dict):
            raise ValueError(f'{context} must be an object, got {raw!r}')
        if not str(raw.get('label', '')).strip():
            raise ValueError(f"{context} has no non-empty 'label' field")
        if 'confidence' not in raw or not _is_number(raw['confidence']):
            raise ValueError(f"{context}.confidence must be a number, got {raw.get('confidence')!r}")
        confidence = float(raw['confidence'])
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f'{context}.confidence must be within [0.0, 1.0], got {confidence!r}')
        if 'bbox' not in raw:
            raise ValueError(f"{context} has no 'bbox' field")
        bbox = _parse_bbox(raw['bbox'], context)
        detections.append(Detection(label=str(raw['label']), confidence=confidence, bbox=bbox))
    return detections


def parse_ground_truth_objects(value: dict[str, Any]) -> list[DetectedObject]:
    """Parses `GroundTruth.value` for a detection task. Same
    reject-loudly posture as `parse_detections`. Duplicate object ids
    within one frame are rejected (master prompt §38) - object identity
    must be unique per frame for matching evidence to mean anything."""
    if 'objects' not in value:
        raise ValueError(f"value {value!r} has no 'objects' field - not an object-detection task?")
    raw_objects = value['objects']
    if not isinstance(raw_objects, list):
        raise ValueError(f"'objects' must be a list, got {raw_objects!r}")

    objects: list[DetectedObject] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_objects):
        context = f'objects[{i}]'
        if not isinstance(raw, dict):
            raise ValueError(f'{context} must be an object, got {raw!r}')
        object_id = str(raw.get('id', '')).strip()
        if not object_id:
            raise ValueError(f"{context} has no non-empty 'id' field")
        if object_id in seen_ids:
            raise ValueError(f"duplicate object id '{object_id}' within one frame")
        seen_ids.add(object_id)
        if not str(raw.get('label', '')).strip():
            raise ValueError(f"{context} has no non-empty 'label' field")
        if 'bbox' not in raw:
            raise ValueError(f"{context} has no 'bbox' field")
        bbox = _parse_bbox(raw['bbox'], context)
        objects.append(DetectedObject(id=object_id, label=str(raw['label']), bbox=bbox))
    return objects


# --- object-level IoU matching (v0.8, Phase 81) -----------------------------
#
# Operates strictly *within* an already-timestamp-matched frame - see this
# module's own docstring for why matching.py's frame association is never
# re-derived here.

def compute_iou(a: BoundingBox, b: BoundingBox) -> float:
    """Standard axis-aligned intersection-over-union. `a`/`b` are always
    valid, positive-area boxes by construction (BoundingBox's own
    `__post_init__`), so the union is always > 0 - no zero-denominator
    case to guard against here."""
    x_left = max(a.x, b.x)
    y_top = max(a.y, b.y)
    x_right = min(a.x + a.width, b.x + b.width)
    y_bottom = min(a.y + a.height, b.y + b.height)
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    intersection = (x_right - x_left) * (y_bottom - y_top)
    area_a = a.width * a.height
    area_b = b.width * b.height
    return intersection / (area_a + area_b - intersection)


@dataclass(frozen=True)
class ObjectMatch:
    ground_truth_object: DetectedObject
    detection: Detection
    iou: float


@dataclass(frozen=True)
class FrameDetectionEvidence:
    """One frame's (one already-timestamp-matched GT/prediction pair, or
    one entirely unmatched frame from either side) object-level matching
    result - master prompt §15's bounded per-frame evidence, not massive
    per-object persistence. `mean_iou` is `None` (never a fabricated 0.0)
    whenever `matched_count == 0` - same `MetricValue` "no denominator,
    no answer" rule as everywhere else in this codebase. `matches` is the
    full per-object detail for anyone who needs it (e.g. a UI drill-down,
    Phase 86) - bounded by how many objects/detections one frame actually
    has, never unbounded."""
    predicted_count: int
    ground_truth_count: int
    matched_count: int
    false_positive_count: int
    false_negative_count: int
    mean_iou: float | None
    matches: list[ObjectMatch]
    # The actual leftover objects, not just counts - Phase 82 needs their
    # labels to compute a per-class breakdown; also the raw material for
    # a future UI drill-down (master prompt §45). Still bounded by one
    # frame's own object/detection count, never unbounded.
    unmatched_detections: list[Detection]
    unmatched_ground_truth_objects: list[DetectedObject]


def match_objects_in_frame(
    ground_truth_objects: list[DetectedObject], detections: list[Detection], iou_threshold: float,
) -> FrameDetectionEvidence:
    """Greedy IoU matching, sorted by descending IoU, deterministic
    tie-break by `(gt_index, detection_index)` - explicitly not Hungarian
    assignment (this module's own docstring explains why). A GT object
    and a detection are only ever candidates if they share the same
    `label` *and* their IoU already meets `iou_threshold` - a pair below
    threshold can never be forced into a match just because nothing else
    is available."""
    candidates: list[tuple[float, int, int]] = []
    for gi, gt in enumerate(ground_truth_objects):
        for di, det in enumerate(detections):
            if gt.label != det.label:
                continue
            iou = compute_iou(gt.bbox, det.bbox)
            if iou >= iou_threshold:
                candidates.append((iou, gi, di))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    matched_gt: set[int] = set()
    matched_det: set[int] = set()
    matches: list[ObjectMatch] = []
    for iou, gi, di in candidates:
        if gi in matched_gt or di in matched_det:
            continue
        matched_gt.add(gi)
        matched_det.add(di)
        matches.append(ObjectMatch(ground_truth_object=ground_truth_objects[gi], detection=detections[di], iou=iou))

    matched_count = len(matches)
    return FrameDetectionEvidence(
        predicted_count=len(detections),
        ground_truth_count=len(ground_truth_objects),
        matched_count=matched_count,
        false_positive_count=len(detections) - matched_count,
        false_negative_count=len(ground_truth_objects) - matched_count,
        mean_iou=(sum(m.iou for m in matches) / matched_count) if matched_count > 0 else None,
        matches=matches,
        unmatched_detections=[d for di, d in enumerate(detections) if di not in matched_det],
        unmatched_ground_truth_objects=[gt for gi, gt in enumerate(ground_truth_objects) if gi not in matched_gt],
    )


def compute_detection_evidence(
    match_result: MatchResult, confidence_threshold: float, iou_threshold: float,
) -> list[FrameDetectionEvidence]:
    """The full per-frame evidence for one `MatchResult` (matching.py) -
    one `FrameDetectionEvidence` per matched pair, plus one per entirely
    unmatched frame on either side (their objects/detections have no
    counterpart to match against at all - every GT object in an unmatched
    ground-truth frame is a false negative, every detection in an
    unmatched prediction frame is a false positive, reported explicitly
    rather than folded into the matched-frame numbers). Predictions below
    `confidence_threshold` are dropped before matching, never after."""
    evidence: list[FrameDetectionEvidence] = []

    for pair in match_result.matched:
        ground_truth_objects = parse_ground_truth_objects(pair.ground_truth.value)
        detections = [d for d in parse_detections(pair.prediction.value) if d.confidence >= confidence_threshold]
        evidence.append(match_objects_in_frame(ground_truth_objects, detections, iou_threshold))

    for gt in match_result.unmatched_ground_truth:
        ground_truth_objects = parse_ground_truth_objects(gt.value)
        evidence.append(FrameDetectionEvidence(
            predicted_count=0, ground_truth_count=len(ground_truth_objects), matched_count=0,
            false_positive_count=0, false_negative_count=len(ground_truth_objects),
            mean_iou=None, matches=[],
            unmatched_detections=[], unmatched_ground_truth_objects=ground_truth_objects,
        ))

    for pred in match_result.unmatched_predictions:
        detections = [d for d in parse_detections(pred.value) if d.confidence >= confidence_threshold]
        evidence.append(FrameDetectionEvidence(
            predicted_count=len(detections), ground_truth_count=0, matched_count=0,
            false_positive_count=len(detections), false_negative_count=0,
            mean_iou=None, matches=[],
            unmatched_detections=detections, unmatched_ground_truth_objects=[],
        ))

    return evidence


# --- session-level metrics (v0.8, Phase 82) ---------------------------------

def _precision_recall(true_positives: int, false_positives: int, false_negatives: int) -> tuple[MetricValue, MetricValue]:
    precision = (true_positives / (true_positives + false_positives)) if (true_positives + false_positives) > 0 else None
    recall = (true_positives / (true_positives + false_negatives)) if (true_positives + false_negatives) > 0 else None
    return precision, recall


@dataclass(frozen=True)
class ClassDetectionMetrics:
    """One label's own precision/recall/F1 - `None` (never a fabricated
    zero) wherever the underlying TP/FP or TP/FN denominator is zero,
    same `MetricValue` rule as everywhere else in this codebase."""
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: MetricValue
    recall: MetricValue
    f1: MetricValue


@dataclass(frozen=True)
class DetectionMetrics:
    """Session-level aggregate over every `FrameDetectionEvidence` in one
    `MatchResult`. `per_class` is keyed by label, covering every label
    that appeared anywhere as a true/false positive/negative - a label
    that never appeared in any frame's evidence has no entry at all
    (there's nothing to report, not even an N/A row)."""
    predicted_count: int
    ground_truth_count: int
    matched_count: int
    false_positive_count: int
    false_negative_count: int
    precision: MetricValue
    recall: MetricValue
    f1: MetricValue
    mean_iou_matched: MetricValue
    per_class: dict[str, ClassDetectionMetrics]


def _aggregate_per_class(evidence: list[FrameDetectionEvidence]) -> dict[str, ClassDetectionMetrics]:
    true_positives_by_label: dict[str, int] = {}
    false_positives_by_label: dict[str, int] = {}
    false_negatives_by_label: dict[str, int] = {}

    for frame in evidence:
        for match in frame.matches:
            label = match.ground_truth_object.label  # == match.detection.label, only same-label pairs ever match
            true_positives_by_label[label] = true_positives_by_label.get(label, 0) + 1
        for detection in frame.unmatched_detections:
            false_positives_by_label[detection.label] = false_positives_by_label.get(detection.label, 0) + 1
        for ground_truth_object in frame.unmatched_ground_truth_objects:
            false_negatives_by_label[ground_truth_object.label] = false_negatives_by_label.get(ground_truth_object.label, 0) + 1

    labels = sorted(set(true_positives_by_label) | set(false_positives_by_label) | set(false_negatives_by_label))
    per_class: dict[str, ClassDetectionMetrics] = {}
    for label in labels:
        true_positives = true_positives_by_label.get(label, 0)
        false_positives = false_positives_by_label.get(label, 0)
        false_negatives = false_negatives_by_label.get(label, 0)
        precision, recall = _precision_recall(true_positives, false_positives, false_negatives)
        per_class[label] = ClassDetectionMetrics(
            true_positives=true_positives, false_positives=false_positives, false_negatives=false_negatives,
            precision=precision, recall=recall, f1=compute_f1(precision, recall),
        )
    return per_class


def aggregate_detection_metrics(evidence: list[FrameDetectionEvidence]) -> DetectionMetrics:
    """Pure aggregation over already-computed per-frame evidence - never a
    second stored source of truth, same pattern
    `aggregate_requirement_results`/`compute_resource_metric_summary`
    already use for their own layers. No AP/mAP anywhere - see this
    module's own docstring."""
    predicted_count = sum(frame.predicted_count for frame in evidence)
    ground_truth_count = sum(frame.ground_truth_count for frame in evidence)
    matched_count = sum(frame.matched_count for frame in evidence)
    false_positive_count = sum(frame.false_positive_count for frame in evidence)
    false_negative_count = sum(frame.false_negative_count for frame in evidence)

    precision, recall = _precision_recall(matched_count, false_positive_count, false_negative_count)
    f1 = compute_f1(precision, recall)

    matched_ious = [match.iou for frame in evidence for match in frame.matches]
    mean_iou_matched = (sum(matched_ious) / len(matched_ious)) if matched_ious else None

    return DetectionMetrics(
        predicted_count=predicted_count, ground_truth_count=ground_truth_count, matched_count=matched_count,
        false_positive_count=false_positive_count, false_negative_count=false_negative_count,
        precision=precision, recall=recall, f1=f1, mean_iou_matched=mean_iou_matched,
        per_class=_aggregate_per_class(evidence),
    )


@dataclass(frozen=True)
class DetectionParameters:
    """`object_detection`'s evaluator configuration - both fields
    **required, no default** (v0.8 architecture review Q14): a hidden
    0.5 confidence/IoU threshold would be exactly the "arbitrary
    regulatory-looking default" this project's culture already rejects
    on principle (decision.py's own `DecisionPolicy`)."""
    confidence_threshold: float
    iou_threshold: float


def parse_detection_parameters(parameters: dict[str, Any]) -> DetectionParameters:
    for name in ('confidence_threshold', 'iou_threshold'):
        if name not in parameters:
            raise ValueError(f"object_detection requires an explicit '{name}' parameter - no default")
        if not _is_number(parameters[name]):
            raise ValueError(f"'{name}' must be a number, got {parameters[name]!r}")
        value = float(parameters[name])
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"'{name}' must be within [0.0, 1.0], got {value!r}")
    return DetectionParameters(
        confidence_threshold=float(parameters['confidence_threshold']),
        iou_threshold=float(parameters['iou_threshold']),
    )


class DetectionEvaluator:
    """Registered in `EVALUATOR_REGISTRY['object_detection']`
    (evaluators.py). `sample_count`/`matched_samples`/
    `unmatched_predictions`/`unmatched_ground_truth` on the returned
    `EvaluatorOutput` are frame-level counts read straight off
    `match_result` itself - the same meaning these fields have for every
    evaluator (see evaluators.py's own module docstring) - never object
    counts. Object-level precision/recall/F1/TP/FP/FN/mean_iou_matched
    live in `metrics`; the per-class breakdown and an echo of the
    parameters actually used (master prompt §35 - "do not hide it") live
    in `details`."""
    evaluator_type = 'object_detection'
    format_version = '1.0'

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='multisens.builtin.evaluator.object_detection', name='Object Detection Evaluator',
            version='1.0.0', plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={'evaluator_type': self.evaluator_type}, author='MultiSens', license='Apache-2.0',
            description='Bounding-box IoU matching, precision/recall/F1/mean-IoU, per-class breakdown (v0.8).',
        )

    def metric_descriptors(self) -> list[MetricDescriptor]:
        return [
            MetricDescriptor(id='precision', higher_is_better=True),
            MetricDescriptor(id='recall', higher_is_better=True),
            MetricDescriptor(id='f1', higher_is_better=True),
            MetricDescriptor(id='true_positives', higher_is_better=True),
            MetricDescriptor(id='false_positives', higher_is_better=False),
            MetricDescriptor(id='false_negatives', higher_is_better=False),
            MetricDescriptor(id='mean_iou_matched', higher_is_better=True),
        ]

    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput:
        params = parse_detection_parameters(parameters)
        evidence = compute_detection_evidence(match_result, params.confidence_threshold, params.iou_threshold)
        detection_metrics = aggregate_detection_metrics(evidence)

        return EvaluatorOutput(
            sample_count=len(match_result.matched) + len(match_result.unmatched_ground_truth),
            matched_samples=len(match_result.matched),
            unmatched_predictions=len(match_result.unmatched_predictions),
            unmatched_ground_truth=len(match_result.unmatched_ground_truth),
            metrics={
                'precision': detection_metrics.precision,
                'recall': detection_metrics.recall,
                'f1': detection_metrics.f1,
                'true_positives': float(detection_metrics.matched_count),
                'false_positives': float(detection_metrics.false_positive_count),
                'false_negatives': float(detection_metrics.false_negative_count),
                'mean_iou_matched': detection_metrics.mean_iou_matched,
            },
            details={
                'parameters': {
                    'confidence_threshold': params.confidence_threshold, 'iou_threshold': params.iou_threshold,
                },
                'per_class': {
                    label: {
                        'true_positives': cm.true_positives,
                        'false_positives': cm.false_positives,
                        'false_negatives': cm.false_negatives,
                        'precision': cm.precision,
                        'recall': cm.recall,
                        'f1': cm.f1,
                    }
                    for label, cm in detection_metrics.per_class.items()
                },
            },
        )
