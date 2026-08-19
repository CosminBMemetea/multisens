"""Pure face-bbox/emotion-label conversion logic - zero dependency on
cv2 or onnxruntime, so this (and its tests) never require the heavy
runtime deps that only `capture.py` needs.

Class order is the emotion-ferplus model's own documented output order
(ONNX Model Zoo, Microsoft FER+ - `Plus692_Output_0`, 8 classes) - not
guessed, this is the model's own training/export convention.
"""
from __future__ import annotations

CLASS_NAME_BY_INDEX: dict[int, str] = {
    0: 'neutral', 1: 'happiness', 2: 'surprise', 3: 'sadness',
    4: 'anger', 5: 'disgust', 6: 'fear', 7: 'contempt',
}
DEFAULT_CONFIDENCE_THRESHOLD = 0.40


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def box_to_normalized_bbox(
    x: float, y: float, w: float, h: float, frame_width: int, frame_height: int,
) -> dict[str, float] | None:
    """Converts one pixel-space `(x, y, w, h)` face box (OpenCV's own
    `detectMultiScale` return shape) into the normalized, frame-bounded
    `{x, y, width, height}` shape `backend/app/domain/detection.py`'s
    `BoundingBox` requires - identical contract to yolo_worker's own
    `box_to_normalized_bbox`, just a different input box format.
    Returns `None` for a box entirely outside the frame or that
    degenerates to zero area after clamping, dropped rather than
    reported as a fabricated zero-area detection."""
    if frame_width <= 0 or frame_height <= 0:
        return None
    x1c, y1c = _clamp01(x / frame_width), _clamp01(y / frame_height)
    x2c, y2c = _clamp01((x + w) / frame_width), _clamp01((y + h) / frame_height)
    width, height = x2c - x1c, y2c - y1c
    if width <= 0 or height <= 0:
        return None
    return {'x': x1c, 'y': y1c, 'width': width, 'height': height}


def build_detections(
    face_box: tuple[float, float, float, float] | None,
    class_probabilities: list[float] | None,
    frame_width: int, frame_height: int,
    class_names: dict[int, str] = CLASS_NAME_BY_INDEX,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[dict]:
    """`face_box` is `(x, y, w, h)` pixel space or `None` (no face found
    this frame) - the model-library-agnostic shape `capture.py` reduces
    OpenCV's own face-detector output to before calling this.
    `class_probabilities` is the model's raw 8-value softmax output, or
    `None` if no face was found (never called with a face but no
    probabilities, or vice versa - `capture.py` only calls this once
    both exist or neither does). Returns a 0-or-1-length list - at most
    one face is classified per frame, matching this reference worker's
    own single-face scope (not a multi-face detector)."""
    if face_box is None or class_probabilities is None:
        return []
    top_index = max(range(len(class_probabilities)), key=lambda i: class_probabilities[i])
    confidence = float(class_probabilities[top_index])
    if confidence < confidence_threshold:
        return []
    label = class_names.get(top_index)
    if label is None:
        return []
    bbox = box_to_normalized_bbox(*face_box, frame_width, frame_height)
    if bbox is None:
        return []
    return [{'label': label, 'confidence': round(confidence, 4), 'bbox': bbox}]
