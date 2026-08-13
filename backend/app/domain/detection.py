"""Object-detection domain model (v0.8, Phase 80). Shapes and validation
only - IoU/matching is Phase 81's job, metrics are Phase 82's. Pure
functions/dataclasses - no persistence, no FastAPI, no ROS, same
discipline as matching.py/metrics.py.

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

## `DetectionEvaluator` is deliberately not registered yet

A class with `evaluator_type`/`format_version` exists below so Phase 81
has a concrete home to add `evaluate()` to, but it is **not** added to
`EVALUATOR_REGISTRY` this phase - same "the registry only ever contains
fully-working entries" discipline Phase 78 established (it started
empty rather than holding a stub). An `evaluator_type` listed as
"supported" in `/evaluate`'s own error message that immediately crashed
on use would be exactly the kind of dishonesty this project's culture
rejects. Phase 81 adds the registration line once `evaluate()` is real
and tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    """Not yet registered in `EVALUATOR_REGISTRY` - see this module's own
    docstring for why. `evaluate()` (matching + metrics) is Phase 81/82's
    job."""
    evaluator_type = 'object_detection'
    format_version = '1.0'
