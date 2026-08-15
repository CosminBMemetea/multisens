"""Pure-logic tests for detections.py - zero dependency on cv2/
ultralytics/torch, runnable without installing this worker's own heavy
requirements.txt at all (same "pure-Python core, tested independently
of the heavy runtime" discipline the ROS ingestion side already
follows for its own sync_logic.py)."""
import pytest
from yolo_worker.detections import build_detections, box_to_normalized_bbox


# --- box_to_normalized_bbox --------------------------------------------------

def test_box_to_normalized_bbox_converts_pixel_to_fractional_coordinates():
    bbox = box_to_normalized_bbox(100, 50, 300, 200, frame_width=1000, frame_height=500)
    assert bbox == pytest.approx({'x': 0.1, 'y': 0.1, 'width': 0.2, 'height': 0.3})


def test_box_to_normalized_bbox_clamps_a_box_that_overhangs_the_frame():
    bbox = box_to_normalized_bbox(-50, -50, 1200, 600, frame_width=1000, frame_height=500)
    assert bbox is not None
    assert bbox['x'] == 0.0 and bbox['y'] == 0.0
    assert bbox['x'] + bbox['width'] <= 1.0
    assert bbox['y'] + bbox['height'] <= 1.0


def test_box_to_normalized_bbox_drops_a_box_entirely_outside_the_frame():
    assert box_to_normalized_bbox(1100, 1100, 1200, 1200, frame_width=1000, frame_height=500) is None


def test_box_to_normalized_bbox_handles_a_degenerate_zero_size_frame():
    assert box_to_normalized_bbox(0, 0, 10, 10, frame_width=0, frame_height=0) is None


# --- build_detections --------------------------------------------------------

def test_build_detections_maps_known_class_ids_to_labels():
    boxes = [(2, 0.9, 100, 100, 200, 200)]  # class 2 == car
    detections = build_detections(boxes, frame_width=1000, frame_height=1000)
    assert detections == pytest.approx(
        [{'label': 'car', 'confidence': 0.9, 'bbox': {'x': 0.1, 'y': 0.1, 'width': 0.1, 'height': 0.1}}],
    )


def test_build_detections_drops_out_of_vocabulary_classes():
    boxes = [(0, 0.99, 0, 0, 100, 100)]  # class 0 == person in COCO, not a vehicle class
    assert build_detections(boxes, frame_width=1000, frame_height=1000) == []


def test_build_detections_drops_sub_threshold_confidence():
    boxes = [(2, 0.39, 0, 0, 100, 100)]  # below the 0.40 default threshold
    assert build_detections(boxes, frame_width=1000, frame_height=1000) == []


def test_build_detections_keeps_exactly_at_threshold():
    boxes = [(2, 0.40, 0, 0, 100, 100)]
    assert len(build_detections(boxes, frame_width=1000, frame_height=1000)) == 1


def test_build_detections_respects_a_custom_confidence_threshold():
    boxes = [(2, 0.5, 0, 0, 100, 100)]
    assert build_detections(boxes, frame_width=1000, frame_height=1000, confidence_threshold=0.6) == []


def test_build_detections_handles_multiple_boxes_independently():
    boxes = [
        (2, 0.9, 0, 0, 100, 100),      # car - kept
        (0, 0.9, 0, 0, 100, 100),      # person - dropped (out of vocabulary)
        (7, 0.3, 0, 0, 100, 100),      # truck below threshold - dropped
        (5, 0.6, 200, 200, 300, 300),  # bus - kept
    ]
    detections = build_detections(boxes, frame_width=1000, frame_height=1000)
    assert {d['label'] for d in detections} == {'car', 'bus'}
