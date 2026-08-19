"""Pure-logic tests for detections.py - zero dependency on cv2/
mediapipe, runnable without installing this worker's own heavy
requirements.txt at all (same discipline as the sibling yolo_worker/
emotion_worker test suites)."""
import pytest
from mediapipe_worker.detections import box_to_normalized_bbox, build_detections


# --- box_to_normalized_bbox --------------------------------------------------

def test_box_to_normalized_bbox_converts_pixel_to_fractional_coordinates():
    bbox = box_to_normalized_bbox(100, 50, 300, 200, frame_width=1000, frame_height=500)
    assert bbox == pytest.approx({'x': 0.1, 'y': 0.1, 'width': 0.3, 'height': 0.4})


def test_box_to_normalized_bbox_clamps_a_box_that_overhangs_the_frame():
    bbox = box_to_normalized_bbox(-50, -50, 1200, 600, frame_width=1000, frame_height=500)
    assert bbox is not None
    assert bbox['x'] == 0.0 and bbox['y'] == 0.0
    assert bbox['x'] + bbox['width'] <= 1.0
    assert bbox['y'] + bbox['height'] <= 1.0


def test_box_to_normalized_bbox_drops_a_box_entirely_outside_the_frame():
    assert box_to_normalized_bbox(1100, 1100, 200, 200, frame_width=1000, frame_height=500) is None


def test_box_to_normalized_bbox_handles_a_degenerate_zero_size_frame():
    assert box_to_normalized_bbox(0, 0, 10, 10, frame_width=0, frame_height=0) is None


# --- build_detections --------------------------------------------------------

def test_build_detections_maps_a_face_score_to_a_face_label():
    faces = [(0.91, 205, 130, 215, 215)]
    detections = build_detections(faces, frame_width=640, frame_height=480)
    assert detections == [
        {'label': 'face', 'confidence': 0.91, 'bbox': pytest.approx(
            {'x': 205 / 640, 'y': 130 / 480, 'width': 215 / 640, 'height': 215 / 480},
        )},
    ]


def test_build_detections_drops_sub_threshold_confidence():
    faces = [(0.49, 0, 0, 100, 100)]  # below the 0.50 default threshold
    assert build_detections(faces, frame_width=1000, frame_height=1000) == []


def test_build_detections_keeps_exactly_at_threshold():
    faces = [(0.50, 0, 0, 100, 100)]
    assert len(build_detections(faces, frame_width=1000, frame_height=1000)) == 1


def test_build_detections_respects_a_custom_confidence_threshold():
    faces = [(0.6, 0, 0, 100, 100)]
    assert build_detections(faces, frame_width=1000, frame_height=1000, confidence_threshold=0.7) == []


def test_build_detections_handles_multiple_faces_independently():
    faces = [
        (0.9, 0, 0, 100, 100),        # kept
        (0.3, 50, 50, 100, 100),      # below threshold - dropped
        (0.6, 200, 200, 300, 300),    # kept
    ]
    detections = build_detections(faces, frame_width=1000, frame_height=1000)
    assert len(detections) == 2
    assert all(d['label'] == 'face' for d in detections)


def test_build_detections_returns_empty_list_for_no_faces():
    assert build_detections([], frame_width=1000, frame_height=1000) == []
