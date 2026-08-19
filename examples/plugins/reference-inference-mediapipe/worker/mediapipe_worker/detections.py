"""Pure box/detection conversion logic - zero dependency on cv2 or
mediapipe, so this (and its tests) never require the heavy runtime deps
that only `capture.py` needs. Mirrors yolo_worker's own detections.py
shape exactly (multi-detection, pixel-space boxes reduced to a
model-library-agnostic tuple before this function is ever called).

Single class ('face') - `FaceDetector` from MediaPipe's Tasks API
(`blaze_face_short_range`) is a face *detector*, not a classifier; it
has nothing analogous to YOLO's COCO class set to filter by, only a
detection score per face.
"""
from __future__ import annotations

DEFAULT_CONFIDENCE_THRESHOLD = 0.50


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def box_to_normalized_bbox(
    x: float, y: float, w: float, h: float, frame_width: int, frame_height: int,
) -> dict[str, float] | None:
    """Converts one pixel-space `(x, y, w, h)` face box (MediaPipe's own
    `BoundingBox.origin_x/origin_y/width/height`) into the normalized,
    frame-bounded `{x, y, width, height}` shape
    `backend/app/domain/detection.py`'s `BoundingBox` requires -
    identical contract to yolo_worker's/emotion_worker's own
    `box_to_normalized_bbox`, just a third input box format. Returns
    `None` for a box entirely outside the frame or that degenerates to
    zero area after clamping, dropped rather than reported as a
    fabricated zero-area detection."""
    if frame_width <= 0 or frame_height <= 0:
        return None
    x1c, y1c = _clamp01(x / frame_width), _clamp01(y / frame_height)
    x2c, y2c = _clamp01((x + w) / frame_width), _clamp01((y + h) / frame_height)
    width, height = x2c - x1c, y2c - y1c
    if width <= 0 or height <= 0:
        return None
    return {'x': x1c, 'y': y1c, 'width': width, 'height': height}


def build_detections(
    faces: list[tuple[float, float, float, float, float]],
    frame_width: int, frame_height: int,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[dict]:
    """`faces` is `(score, origin_x, origin_y, width, height)` tuples in
    raw pixel space - the model-library-agnostic shape `capture.py`
    reduces one MediaPipe `FaceDetectorResult` down to before calling
    this, so this function itself never imports `mediapipe`. Zero, one,
    or several faces per frame - unlike the emotion worker's own
    single-face scope, this is a genuine multi-detection model, same as
    yolo_worker's own build_detections."""
    detections = []
    for score, x, y, w, h in faces:
        if score < confidence_threshold:
            continue
        bbox = box_to_normalized_bbox(x, y, w, h, frame_width, frame_height)
        if bbox is None:
            continue
        detections.append({'label': 'face', 'confidence': round(float(score), 4), 'bbox': bbox})
    return detections
