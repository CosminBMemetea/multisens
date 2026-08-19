"""Pure-logic tests for detections.py - zero dependency on cv2/
onnxruntime/numpy, runnable without installing this worker's own heavy
requirements.txt at all."""
import pytest
from emotion_worker.detections import build_detections, box_to_normalized_bbox

NEUTRAL_TOP = [0.9, 0.01, 0.01, 0.01, 0.02, 0.01, 0.02, 0.02]      # class 0
HAPPINESS_TOP = [0.02, 0.85, 0.02, 0.02, 0.03, 0.02, 0.02, 0.02]   # class 1
FLAT_LOW_CONFIDENCE = [0.13] * 8                                   # no class clears 0.40


# --- box_to_normalized_bbox --------------------------------------------------

def test_box_to_normalized_bbox_converts_pixel_xywh_to_fractional_coordinates():
    bbox = box_to_normalized_bbox(100, 50, 200, 150, frame_width=1000, frame_height=500)
    assert bbox == pytest.approx({'x': 0.1, 'y': 0.1, 'width': 0.2, 'height': 0.3})


def test_box_to_normalized_bbox_clamps_a_box_that_overhangs_the_frame():
    bbox = box_to_normalized_bbox(-50, -50, 1250, 650, frame_width=1000, frame_height=500)
    assert bbox is not None
    assert bbox['x'] == 0.0 and bbox['y'] == 0.0
    assert bbox['x'] + bbox['width'] <= 1.0
    assert bbox['y'] + bbox['height'] <= 1.0


def test_box_to_normalized_bbox_drops_a_box_entirely_outside_the_frame():
    assert box_to_normalized_bbox(1100, 1100, 100, 100, frame_width=1000, frame_height=500) is None


def test_box_to_normalized_bbox_handles_a_degenerate_zero_size_frame():
    assert box_to_normalized_bbox(0, 0, 10, 10, frame_width=0, frame_height=0) is None


# --- build_detections --------------------------------------------------------

def test_build_detections_returns_empty_when_no_face_found():
    assert build_detections(None, None, frame_width=1000, frame_height=1000) == []


def test_build_detections_maps_top_class_to_its_label():
    detections = build_detections((100, 100, 100, 100), NEUTRAL_TOP, frame_width=1000, frame_height=1000)
    assert detections == pytest.approx(
        [{'label': 'neutral', 'confidence': 0.9, 'bbox': {'x': 0.1, 'y': 0.1, 'width': 0.1, 'height': 0.1}}],
    )


def test_build_detections_picks_whichever_class_actually_has_the_highest_probability():
    detections = build_detections((0, 0, 100, 100), HAPPINESS_TOP, frame_width=1000, frame_height=1000)
    assert detections[0]['label'] == 'happiness'
    assert detections[0]['confidence'] == pytest.approx(0.85)


def test_build_detections_drops_sub_threshold_confidence():
    assert build_detections((0, 0, 100, 100), FLAT_LOW_CONFIDENCE, frame_width=1000, frame_height=1000) == []


def test_build_detections_keeps_exactly_at_threshold():
    probs = [0.40] + [0.60 / 7] * 7
    detections = build_detections((0, 0, 100, 100), probs, frame_width=1000, frame_height=1000)
    assert len(detections) == 1
    assert detections[0]['label'] == 'neutral'


def test_build_detections_respects_a_custom_confidence_threshold():
    detections = build_detections(
        (0, 0, 100, 100), HAPPINESS_TOP, frame_width=1000, frame_height=1000, confidence_threshold=0.9,
    )
    assert detections == []


def test_build_detections_returns_at_most_one_face():
    detections = build_detections((0, 0, 100, 100), NEUTRAL_TOP, frame_width=1000, frame_height=1000)
    assert len(detections) <= 1
