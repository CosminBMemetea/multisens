"""Pure box/detection conversion logic - zero dependency on cv2 or
ultralytics, so this (and its tests) never require the heavy runtime
deps that only `capture.py` needs. Reproduces the real RideSafe
one-shot YOLOv8n experiment's own class set and confidence threshold
exactly (issue #123): car/truck/bus/motorcycle at 0.40, matching
`bridge.py`'s own declared `capabilities` in the paired plugin.
"""
from __future__ import annotations

# Standard COCO class indices YOLOv8n's stock weights use.
CLASS_NAME_BY_ID: dict[int, str] = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
DEFAULT_CONFIDENCE_THRESHOLD = 0.40


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def box_to_normalized_bbox(
    x1: float, y1: float, x2: float, y2: float, frame_width: int, frame_height: int,
) -> dict[str, float] | None:
    """Converts one pixel-space `(x1, y1, x2, y2)` box into the
    normalized, frame-bounded `{x, y, width, height}` shape
    `backend/app/domain/detection.py`'s `BoundingBox` requires (`x`/`y`
    in `[0, 1]`, `width`/`height > 0`, `x + width <= 1`,
    `y + height <= 1`). Returns `None` for a box that's entirely
    outside the frame or degenerates to zero area after clamping to the
    frame bounds - dropped rather than reported as a fabricated
    zero-area detection."""
    if frame_width <= 0 or frame_height <= 0:
        return None
    x1c, y1c = _clamp01(x1 / frame_width), _clamp01(y1 / frame_height)
    x2c, y2c = _clamp01(x2 / frame_width), _clamp01(y2 / frame_height)
    width, height = x2c - x1c, y2c - y1c
    if width <= 0 or height <= 0:
        return None
    return {'x': x1c, 'y': y1c, 'width': width, 'height': height}


def build_detections(
    boxes: list[tuple[int, float, float, float, float, float]],
    frame_width: int, frame_height: int,
    class_names: dict[int, str] = CLASS_NAME_BY_ID,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[dict]:
    """`boxes` is `(class_id, confidence, x1, y1, x2, y2)` tuples in
    raw pixel space - the model-library-agnostic shape `capture.py`
    reduces one `ultralytics.engine.results.Results` object down to
    before calling this, so this function itself never imports
    `ultralytics`. Out-of-vocabulary classes and sub-threshold
    detections are dropped silently, matching the real one-shot
    experiment's own car/truck/bus/motorcycle-at-0.40 behavior exactly."""
    detections = []
    for class_id, confidence, x1, y1, x2, y2 in boxes:
        label = class_names.get(class_id)
        if label is None or confidence < confidence_threshold:
            continue
        bbox = box_to_normalized_bbox(x1, y1, x2, y2, frame_width, frame_height)
        if bbox is None:
            continue
        detections.append({'label': label, 'confidence': round(float(confidence), 4), 'bbox': bbox})
    return detections
