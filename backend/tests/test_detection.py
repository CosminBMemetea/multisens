"""Phase 80 (v0.8): object-detection schema/validation only - no IoU,
matching, or metrics yet (Phase 81/82). Every rejection case mirrors
metrics.py's own `extract_label` posture: malformed input raises
`ValueError`, never silently dropped or repaired.
"""
import pytest

from app.domain.detection import (
    BoundingBox,
    DetectionEvaluator,
    DetectionParameters,
    parse_detection_parameters,
    parse_detections,
    parse_ground_truth_objects,
)


def _bbox(x=0.1, y=0.1, width=0.2, height=0.2) -> dict:
    return {'x': x, 'y': y, 'width': width, 'height': height}


# --- BoundingBox ---------------------------------------------------------

def test_bbox_valid_constructs():
    box = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
    assert box.x == 0.1 and box.width == 0.3


@pytest.mark.parametrize('field,value', [('x', -0.1), ('x', 1.1), ('y', -0.1), ('y', 1.1)])
def test_bbox_coordinate_out_of_range_rejected(field, value):
    kwargs = {'x': 0.1, 'y': 0.1, 'width': 0.1, 'height': 0.1, field: value}
    with pytest.raises(ValueError, match=field):
        BoundingBox(**kwargs)


def test_bbox_negative_width_rejected():
    with pytest.raises(ValueError, match='width'):
        BoundingBox(x=0.1, y=0.1, width=-0.1, height=0.1)


def test_bbox_negative_height_rejected():
    with pytest.raises(ValueError, match='height'):
        BoundingBox(x=0.1, y=0.1, width=0.1, height=-0.1)


def test_bbox_zero_width_rejected():
    # Stricter than "negative only" - a zero-area box can never represent
    # a real detected/annotated object (see module docstring).
    with pytest.raises(ValueError, match='width'):
        BoundingBox(x=0.1, y=0.1, width=0.0, height=0.1)


def test_bbox_extending_past_frame_rejected():
    with pytest.raises(ValueError, match='extends past'):
        BoundingBox(x=0.9, y=0.1, width=0.5, height=0.1)


def test_bbox_touching_frame_edge_exactly_is_allowed():
    box = BoundingBox(x=0.5, y=0.5, width=0.5, height=0.5)  # right/bottom edge == 1.0 exactly
    assert box.x + box.width == 1.0


# --- parse_detections (prediction side) -----------------------------------

def test_parse_detections_valid_single():
    value = {'detections': [{'label': 'person', 'confidence': 0.92, 'bbox': _bbox()}]}
    detections = parse_detections(value)
    assert len(detections) == 1
    assert detections[0].label == 'person'
    assert detections[0].confidence == 0.92
    assert detections[0].bbox == BoundingBox(**_bbox())


def test_parse_detections_valid_multiple():
    value = {'detections': [
        {'label': 'person', 'confidence': 0.9, 'bbox': _bbox(0.1, 0.1, 0.2, 0.2)},
        {'label': 'car', 'confidence': 0.8, 'bbox': _bbox(0.5, 0.5, 0.3, 0.3)},
    ]}
    detections = parse_detections(value)
    assert [d.label for d in detections] == ['person', 'car']


def test_parse_detections_empty_list_is_valid():
    assert parse_detections({'detections': []}) == []


def test_parse_detections_missing_detections_key_rejected():
    with pytest.raises(ValueError, match='detections'):
        parse_detections({'value': 1.0})


def test_parse_detections_non_list_rejected():
    with pytest.raises(ValueError, match='list'):
        parse_detections({'detections': 'not-a-list'})


def test_parse_detections_missing_label_rejected():
    with pytest.raises(ValueError, match='label'):
        parse_detections({'detections': [{'confidence': 0.9, 'bbox': _bbox()}]})


def test_parse_detections_empty_label_rejected():
    with pytest.raises(ValueError, match='label'):
        parse_detections({'detections': [{'label': '  ', 'confidence': 0.9, 'bbox': _bbox()}]})


def test_parse_detections_non_numeric_confidence_rejected():
    with pytest.raises(ValueError, match='confidence'):
        parse_detections({'detections': [{'label': 'person', 'confidence': '0.9', 'bbox': _bbox()}]})


def test_parse_detections_confidence_out_of_range_rejected():
    with pytest.raises(ValueError, match='confidence'):
        parse_detections({'detections': [{'label': 'person', 'confidence': 1.5, 'bbox': _bbox()}]})


def test_parse_detections_missing_bbox_rejected():
    with pytest.raises(ValueError, match='bbox'):
        parse_detections({'detections': [{'label': 'person', 'confidence': 0.9}]})


def test_parse_detections_invalid_bbox_rejected():
    with pytest.raises(ValueError, match='width'):
        parse_detections({'detections': [{'label': 'person', 'confidence': 0.9, 'bbox': _bbox(width=-0.1)}]})


def test_parse_detections_bbox_missing_field_rejected():
    with pytest.raises(ValueError, match='bbox'):
        parse_detections({'detections': [{'label': 'person', 'confidence': 0.9, 'bbox': {'x': 0.1, 'y': 0.1}}]})


# --- parse_ground_truth_objects (ground-truth side) -----------------------

def test_parse_ground_truth_objects_valid():
    value = {'objects': [{'id': 'gt-1', 'label': 'person', 'bbox': _bbox()}]}
    objects = parse_ground_truth_objects(value)
    assert len(objects) == 1
    assert objects[0].id == 'gt-1'
    assert objects[0].label == 'person'


def test_parse_ground_truth_objects_empty_list_is_valid():
    assert parse_ground_truth_objects({'objects': []}) == []


def test_parse_ground_truth_objects_missing_objects_key_rejected():
    with pytest.raises(ValueError, match='objects'):
        parse_ground_truth_objects({'value': 1.0})


def test_parse_ground_truth_objects_missing_id_rejected():
    with pytest.raises(ValueError, match='id'):
        parse_ground_truth_objects({'objects': [{'label': 'person', 'bbox': _bbox()}]})


def test_parse_ground_truth_objects_missing_label_rejected():
    with pytest.raises(ValueError, match='label'):
        parse_ground_truth_objects({'objects': [{'id': 'gt-1', 'bbox': _bbox()}]})


def test_parse_ground_truth_objects_duplicate_id_within_frame_rejected():
    value = {'objects': [
        {'id': 'gt-1', 'label': 'person', 'bbox': _bbox(0.1, 0.1, 0.2, 0.2)},
        {'id': 'gt-1', 'label': 'car', 'bbox': _bbox(0.5, 0.5, 0.2, 0.2)},
    ]}
    with pytest.raises(ValueError, match='duplicate object id'):
        parse_ground_truth_objects(value)


def test_parse_ground_truth_objects_missing_bbox_rejected():
    with pytest.raises(ValueError, match='bbox'):
        parse_ground_truth_objects({'objects': [{'id': 'gt-1', 'label': 'person'}]})


# --- DetectionParameters ---------------------------------------------------

def test_parse_detection_parameters_valid():
    params = parse_detection_parameters({'confidence_threshold': 0.5, 'iou_threshold': 0.5})
    assert params == DetectionParameters(confidence_threshold=0.5, iou_threshold=0.5)


def test_parse_detection_parameters_missing_confidence_threshold_rejected():
    with pytest.raises(ValueError, match='confidence_threshold'):
        parse_detection_parameters({'iou_threshold': 0.5})


def test_parse_detection_parameters_missing_iou_threshold_rejected():
    with pytest.raises(ValueError, match='iou_threshold'):
        parse_detection_parameters({'confidence_threshold': 0.5})


def test_parse_detection_parameters_no_default_for_either():
    # There is deliberately no way to get a DetectionParameters without
    # naming both thresholds explicitly - confirms the "no default"
    # requirement isn't accidentally satisfiable with an empty dict.
    with pytest.raises(ValueError):
        parse_detection_parameters({})


def test_parse_detection_parameters_out_of_range_rejected():
    with pytest.raises(ValueError, match='confidence_threshold'):
        parse_detection_parameters({'confidence_threshold': 1.5, 'iou_threshold': 0.5})


def test_parse_detection_parameters_non_numeric_rejected():
    with pytest.raises(ValueError, match='confidence_threshold'):
        parse_detection_parameters({'confidence_threshold': 'high', 'iou_threshold': 0.5})


# --- DetectionEvaluator scope boundary (Phase 80) --------------------------

def test_detection_evaluator_declares_its_identity():
    assert DetectionEvaluator.evaluator_type == 'object_detection'
    assert DetectionEvaluator.format_version == '1.0'


def test_detection_evaluator_registered_as_of_phase_82():
    from app.domain.evaluators import EVALUATOR_REGISTRY
    assert isinstance(EVALUATOR_REGISTRY['object_detection'], DetectionEvaluator)
