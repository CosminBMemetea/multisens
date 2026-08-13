"""Phase 82 (v0.8): aggregating Phase 81's per-frame evidence into
session-level detection metrics, and DetectionEvaluator.evaluate() -
now registered in EVALUATOR_REGISTRY. No AP/mAP anywhere (architecture
review Q16) - a dedicated test locks that down explicitly.
"""
import dataclasses

import pytest

from app.domain.detection import (
    BoundingBox,
    ClassDetectionMetrics,
    Detection,
    DetectedObject,
    DetectionEvaluator,
    DetectionMetrics,
    aggregate_detection_metrics,
    match_objects_in_frame,
)
from app.domain.evaluators import EVALUATOR_REGISTRY
from app.domain.matching import match_by_timestamp
from app.domain.models import GroundTruth, Prediction


def _box(x, y, width=0.2, height=0.2) -> BoundingBox:
    return BoundingBox(x=x, y=y, width=width, height=height)


def _gt_obj(id_, label, box) -> DetectedObject:
    return DetectedObject(id=id_, label=label, bbox=box)


def _det(label, confidence, box) -> Detection:
    return Detection(label=label, confidence=confidence, bbox=box)


# --- aggregate_detection_metrics: overall ----------------------------------

def test_aggregate_hand_computed_across_multiple_frames():
    box = _box(0.1, 0.1)
    # frame 1: 1 TP (person)
    frame1 = match_objects_in_frame([_gt_obj('g1', 'person', box)], [_det('person', 0.9, box)], iou_threshold=0.5)
    # frame 2: 1 TP (car) + 1 FP (person, extra detection)
    frame2 = match_objects_in_frame(
        [_gt_obj('g2', 'car', box)],
        [_det('car', 0.9, box), _det('person', 0.8, _box(0.6, 0.6))],
        iou_threshold=0.5,
    )
    # frame 3: 1 FN (car, never detected)
    frame3 = match_objects_in_frame([_gt_obj('g3', 'car', box)], [], iou_threshold=0.5)

    metrics = aggregate_detection_metrics([frame1, frame2, frame3])
    assert metrics.matched_count == 2  # 2 true positives
    assert metrics.false_positive_count == 1
    assert metrics.false_negative_count == 1
    assert metrics.precision == pytest.approx(2 / 3)   # 2 / (2 + 1)
    assert metrics.recall == pytest.approx(2 / 3)       # 2 / (2 + 1)
    assert metrics.f1 == pytest.approx(2 / 3)
    assert metrics.mean_iou_matched == pytest.approx(1.0)  # both TPs are exact matches


def test_aggregate_empty_evidence_is_all_na_not_zero():
    metrics = aggregate_detection_metrics([])
    assert metrics.matched_count == 0
    assert metrics.precision is None
    assert metrics.recall is None
    assert metrics.f1 is None
    assert metrics.mean_iou_matched is None
    assert metrics.per_class == {}


def test_aggregate_mean_iou_matched_only_averages_real_matches():
    box_a = _box(0.0, 0.0, 0.2, 0.2)
    box_b = _box(0.05, 0.0, 0.2, 0.2)  # partial overlap, not identical
    frame = match_objects_in_frame([_gt_obj('g1', 'person', box_a)], [_det('person', 0.9, box_b)], iou_threshold=0.1)
    metrics = aggregate_detection_metrics([frame])
    assert metrics.matched_count == 1
    assert metrics.mean_iou_matched == pytest.approx(frame.matches[0].iou)
    assert metrics.mean_iou_matched < 1.0  # a genuine, non-trivial partial overlap


# --- per-class breakdown ----------------------------------------------------

def test_per_class_breakdown_only_includes_labels_that_appeared():
    box = _box(0.1, 0.1)
    frame = match_objects_in_frame([_gt_obj('g1', 'person', box)], [_det('person', 0.9, box)], iou_threshold=0.5)
    metrics = aggregate_detection_metrics([frame])
    assert set(metrics.per_class) == {'person'}
    assert metrics.per_class['person'] == ClassDetectionMetrics(
        true_positives=1, false_positives=0, false_negatives=0, precision=1.0, recall=1.0, f1=1.0,
    )


def test_per_class_na_precision_when_label_never_predicted():
    # 'car' only ever appears as a missed ground-truth object - never a
    # false positive - so its precision denominator (TP+FP) is 0.
    box = _box(0.1, 0.1)
    frame = match_objects_in_frame([_gt_obj('g1', 'car', box)], [], iou_threshold=0.5)
    metrics = aggregate_detection_metrics([frame])
    car = metrics.per_class['car']
    assert car.true_positives == 0 and car.false_positives == 0 and car.false_negatives == 1
    assert car.precision is None  # 0/0, never a fabricated 0.0
    assert car.recall == 0.0      # 0/1, a real, defined zero
    assert car.f1 is None


def test_per_class_na_recall_when_label_never_in_ground_truth():
    # 'person' only ever appears as an extra detection - never a real GT
    # object - so its recall denominator (TP+FN) is 0.
    box = _box(0.1, 0.1)
    frame = match_objects_in_frame([], [_det('person', 0.9, box)], iou_threshold=0.5)
    metrics = aggregate_detection_metrics([frame])
    person = metrics.per_class['person']
    assert person.true_positives == 0 and person.false_positives == 1 and person.false_negatives == 0
    assert person.recall is None  # 0/0, never a fabricated 0.0
    assert person.precision == 0.0
    assert person.f1 is None


def test_per_class_two_labels_never_conflated():
    box = _box(0.1, 0.1)
    frame = match_objects_in_frame(
        [_gt_obj('g1', 'person', box), _gt_obj('g2', 'car', box)],
        [_det('person', 0.9, box)],  # car goes undetected
        iou_threshold=0.5,
    )
    metrics = aggregate_detection_metrics([frame])
    assert metrics.per_class['person'].true_positives == 1
    assert metrics.per_class['car'].false_negatives == 1
    assert metrics.per_class['car'].true_positives == 0


# --- no AP/mAP anywhere ------------------------------------------------------

def test_no_ap_or_map_field_exists_anywhere_in_detection_output():
    metrics_fields = {f.name.lower() for f in dataclasses.fields(DetectionMetrics)}
    class_fields = {f.name.lower() for f in dataclasses.fields(ClassDetectionMetrics)}
    forbidden = {'ap', 'map', 'average_precision', 'mean_average_precision'}
    assert not (metrics_fields & forbidden)
    assert not (class_fields & forbidden)

    evaluator_output_keys = {
        'precision', 'recall', 'f1', 'true_positives', 'false_positives', 'false_negatives', 'mean_iou_matched',
    }
    box = _box(0.1, 0.1)
    match_result = match_by_timestamp(
        [GroundTruth(id='g1', session_id='s1', timestamp_ms=0.0, task='object_detection',
                      value={'objects': [{'id': 'o1', 'label': 'person',
                                           'bbox': {'x': box.x, 'y': box.y, 'width': box.width, 'height': box.height}}]})],
        [Prediction(id='p1', session_id='s1', timestamp_ms=1.0, source_id='det', sensor_ids=['rgb'],
                     task='object_detection',
                     value={'detections': [{'label': 'person', 'confidence': 0.9,
                                             'bbox': {'x': box.x, 'y': box.y, 'width': box.width, 'height': box.height}}]})],
        tolerance_ms=50.0,
    )
    output = DetectionEvaluator().evaluate(match_result, {'confidence_threshold': 0.5, 'iou_threshold': 0.5})
    assert set(output.metrics) == evaluator_output_keys
    assert not (set(output.metrics) & forbidden)


# --- DetectionEvaluator.evaluate() end to end -------------------------------

def _gt(id_, ts, objects) -> GroundTruth:
    return GroundTruth(
        id=id_, session_id='s1', timestamp_ms=ts, task='object_detection',
        value={'objects': [{'id': o.id, 'label': o.label,
                             'bbox': {'x': o.bbox.x, 'y': o.bbox.y, 'width': o.bbox.width, 'height': o.bbox.height}}
                            for o in objects]},
    )


def _pred(id_, ts, detections) -> Prediction:
    return Prediction(
        id=id_, session_id='s1', timestamp_ms=ts, source_id='det', sensor_ids=['rgb'], task='object_detection',
        value={'detections': [{'label': d.label, 'confidence': d.confidence,
                                'bbox': {'x': d.bbox.x, 'y': d.bbox.y, 'width': d.bbox.width, 'height': d.bbox.height}}
                               for d in detections]},
    )


def test_evaluator_registered_and_dispatchable():
    assert EVALUATOR_REGISTRY['object_detection'].evaluator_type == 'object_detection'


def test_evaluate_missing_parameters_raises_value_error():
    box = _box(0.1, 0.1)
    match_result = match_by_timestamp(
        [_gt('g1', 0.0, [_gt_obj('o1', 'person', box)])], [_pred('p1', 1.0, [_det('person', 0.9, box)])],
        tolerance_ms=50.0,
    )
    with pytest.raises(ValueError, match='confidence_threshold'):
        DetectionEvaluator().evaluate(match_result, {})


def test_evaluate_frame_counts_are_frame_level_not_object_level():
    # Two frames, each with 2 objects - EvaluatorOutput's own
    # sample_count/matched_samples must report 2 (frames), never 4
    # (objects) - object-level counts live in metrics/details instead.
    box = _box(0.1, 0.1)
    gts = [
        _gt('g1', 0.0, [_gt_obj('o1', 'person', box), _gt_obj('o2', 'car', box)]),
        _gt('g2', 1000.0, [_gt_obj('o3', 'person', box), _gt_obj('o4', 'car', box)]),
    ]
    preds = [
        _pred('p1', 1.0, [_det('person', 0.9, box), _det('car', 0.9, box)]),
        _pred('p2', 1001.0, [_det('person', 0.9, box), _det('car', 0.9, box)]),
    ]
    match_result = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    output = DetectionEvaluator().evaluate(match_result, {'confidence_threshold': 0.5, 'iou_threshold': 0.5})

    assert output.sample_count == 2
    assert output.matched_samples == 2
    assert output.unmatched_predictions == 0
    assert output.unmatched_ground_truth == 0
    assert output.metrics['true_positives'] == 4.0  # object-level, lives in metrics instead


def test_evaluate_details_carries_parameters_echo_and_per_class():
    box = _box(0.1, 0.1)
    match_result = match_by_timestamp(
        [_gt('g1', 0.0, [_gt_obj('o1', 'person', box)])], [_pred('p1', 1.0, [_det('person', 0.9, box)])],
        tolerance_ms=50.0,
    )
    output = DetectionEvaluator().evaluate(match_result, {'confidence_threshold': 0.4, 'iou_threshold': 0.6})
    assert output.details['parameters'] == {'confidence_threshold': 0.4, 'iou_threshold': 0.6}
    assert output.details['per_class']['person']['true_positives'] == 1


# --- independent verification (zero imports from the production evaluator) -

def _iou_independent(box_a: dict, box_b: dict) -> float:
    x_left = max(box_a['x'], box_b['x'])
    y_top = max(box_a['y'], box_b['y'])
    x_right = min(box_a['x'] + box_a['width'], box_b['x'] + box_b['width'])
    y_bottom = min(box_a['y'] + box_a['height'], box_b['y'] + box_b['height'])
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    intersection = (x_right - x_left) * (y_bottom - y_top)
    area_a = box_a['width'] * box_a['height']
    area_b = box_b['width'] * box_b['height']
    return intersection / (area_a + area_b - intersection)


def test_independent_verification_of_detection_evaluator_output():
    # Deliberately re-implemented from scratch here (plain dicts, no
    # BoundingBox/Detection/DetectedObject, no compute_iou/
    # match_objects_in_frame imports) - a second, independent computation
    # of the same synthetic scenario, cross-checked against the real
    # production evaluator's own output. Scenario: 2 frames.
    #   frame 1: person exact match (IoU 1.0), extra 'car' FP.
    #   frame 2: 'person' missed entirely (FN) - no detections at all.
    gt_box = {'x': 0.1, 'y': 0.1, 'width': 0.2, 'height': 0.2}
    fp_box = {'x': 0.6, 'y': 0.6, 'width': 0.1, 'height': 0.1}

    gts = [
        _gt('g1', 0.0, [_gt_obj('o1', 'person', BoundingBox(**gt_box))]),
        _gt('g2', 1000.0, [_gt_obj('o2', 'person', BoundingBox(**gt_box))]),
    ]
    preds = [
        _pred('p1', 1.0, [
            _det('person', 0.9, BoundingBox(**gt_box)),
            _det('car', 0.8, BoundingBox(**fp_box)),
        ]),
        _pred('p2', 1001.0, []),
    ]

    # --- independent recomputation, plain Python + dicts only ---
    independent_iou = _iou_independent(gt_box, gt_box)
    assert independent_iou == pytest.approx(1.0)
    expected_tp, expected_fp, expected_fn = 1, 1, 1  # person matched, car FP, frame-2 person FN
    expected_precision = expected_tp / (expected_tp + expected_fp)
    expected_recall = expected_tp / (expected_tp + expected_fn)
    expected_f1 = 2 * expected_precision * expected_recall / (expected_precision + expected_recall)
    expected_mean_iou = independent_iou  # only one real match, at IoU 1.0

    # --- production evaluator ---
    match_result = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    output = DetectionEvaluator().evaluate(match_result, {'confidence_threshold': 0.5, 'iou_threshold': 0.5})

    assert output.metrics['true_positives'] == expected_tp
    assert output.metrics['false_positives'] == expected_fp
    assert output.metrics['false_negatives'] == expected_fn
    assert output.metrics['precision'] == pytest.approx(expected_precision)
    assert output.metrics['recall'] == pytest.approx(expected_recall)
    assert output.metrics['f1'] == pytest.approx(expected_f1)
    assert output.metrics['mean_iou_matched'] == pytest.approx(expected_mean_iou)
