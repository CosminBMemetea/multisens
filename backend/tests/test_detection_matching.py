"""Phase 81 (v0.8): object-level IoU matching, strictly within an already-
timestamp-matched frame. `match_by_timestamp` itself (matching.py) is
never imported here in a way that would let object matching influence
frame matching - `compute_detection_evidence` only ever consumes an
already-computed `MatchResult`.
"""
import pytest

from app.domain.detection import (
    BoundingBox,
    Detection,
    DetectedObject,
    compute_detection_evidence,
    compute_iou,
    match_objects_in_frame,
)
from app.domain.matching import MatchedPair, MatchResult, match_by_timestamp
from app.domain.models import GroundTruth, Prediction


def _box(x, y, width=0.2, height=0.2) -> BoundingBox:
    return BoundingBox(x=x, y=y, width=width, height=height)


def _gt_obj(id_, label, box) -> DetectedObject:
    return DetectedObject(id=id_, label=label, bbox=box)


def _det(label, confidence, box) -> Detection:
    return Detection(label=label, confidence=confidence, bbox=box)


# --- compute_iou --------------------------------------------------------

def test_iou_identical_boxes_is_one():
    box = _box(0.1, 0.1)
    assert compute_iou(box, box) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    assert compute_iou(_box(0.0, 0.0, 0.1, 0.1), _box(0.5, 0.5, 0.1, 0.1)) == 0.0


def test_iou_partial_overlap_hand_computed():
    # a: [0.0,0.0]-[0.2,0.2] (area 0.04); b: [0.1,0.1]-[0.3,0.3] (area 0.04)
    # intersection: [0.1,0.1]-[0.2,0.2] = 0.1*0.1 = 0.01
    # union = 0.04 + 0.04 - 0.01 = 0.07
    a = _box(0.0, 0.0, 0.2, 0.2)
    b = _box(0.1, 0.1, 0.2, 0.2)
    assert compute_iou(a, b) == pytest.approx(0.01 / 0.07)


def test_iou_touching_edges_is_zero():
    a = _box(0.0, 0.0, 0.1, 0.1)
    b = _box(0.1, 0.0, 0.1, 0.1)  # shares an edge, zero area overlap
    assert compute_iou(a, b) == 0.0


# --- match_objects_in_frame: single-pair cases ---------------------------

def test_exact_bbox_match():
    box = _box(0.1, 0.1)
    evidence = match_objects_in_frame([_gt_obj('g1', 'person', box)], [_det('person', 0.9, box)], iou_threshold=0.5)
    assert evidence.matched_count == 1
    assert evidence.false_positive_count == 0
    assert evidence.false_negative_count == 0
    assert evidence.mean_iou == pytest.approx(1.0)
    assert evidence.matches[0].ground_truth_object.id == 'g1'


def test_iou_below_threshold_is_fp_and_fn_not_a_low_quality_match():
    gt_box = _box(0.0, 0.0, 0.2, 0.2)
    det_box = _box(0.15, 0.15, 0.2, 0.2)  # small overlap, IoU well below 0.5
    evidence = match_objects_in_frame([_gt_obj('g1', 'person', gt_box)], [_det('person', 0.9, det_box)], iou_threshold=0.5)
    assert evidence.matched_count == 0
    assert evidence.false_positive_count == 1
    assert evidence.false_negative_count == 1
    assert evidence.mean_iou is None


def test_wrong_class_never_matches_even_at_perfect_iou():
    box = _box(0.1, 0.1)
    evidence = match_objects_in_frame([_gt_obj('g1', 'person', box)], [_det('car', 0.9, box)], iou_threshold=0.5)
    assert evidence.matched_count == 0
    assert evidence.false_positive_count == 1
    assert evidence.false_negative_count == 1


def test_empty_ground_truth_all_detections_are_false_positives():
    box = _box(0.1, 0.1)
    evidence = match_objects_in_frame([], [_det('person', 0.9, box), _det('car', 0.8, box)], iou_threshold=0.5)
    assert evidence.matched_count == 0
    assert evidence.false_positive_count == 2
    assert evidence.false_negative_count == 0
    assert evidence.mean_iou is None


def test_empty_predictions_all_ground_truth_are_false_negatives():
    box = _box(0.1, 0.1)
    evidence = match_objects_in_frame([_gt_obj('g1', 'person', box), _gt_obj('g2', 'car', box)], [], iou_threshold=0.5)
    assert evidence.matched_count == 0
    assert evidence.false_positive_count == 0
    assert evidence.false_negative_count == 2


def test_both_empty_is_all_zero_never_a_crash():
    evidence = match_objects_in_frame([], [], iou_threshold=0.5)
    assert evidence == match_objects_in_frame([], [], iou_threshold=0.5)
    assert evidence.matched_count == 0
    assert evidence.false_positive_count == 0
    assert evidence.false_negative_count == 0
    assert evidence.mean_iou is None


# --- multiple objects / duplicate classes ---------------------------------

def test_multiple_objects_matched_independently():
    gt = [_gt_obj('g1', 'person', _box(0.0, 0.0, 0.2, 0.2)), _gt_obj('g2', 'car', _box(0.5, 0.5, 0.2, 0.2))]
    det = [_det('person', 0.9, _box(0.0, 0.0, 0.2, 0.2)), _det('car', 0.8, _box(0.5, 0.5, 0.2, 0.2))]
    evidence = match_objects_in_frame(gt, det, iou_threshold=0.5)
    assert evidence.matched_count == 2
    assert evidence.false_positive_count == 0
    assert evidence.false_negative_count == 0


def test_duplicate_classes_one_to_one_assignment():
    # Two 'person' GT boxes, two 'person' detections - each detection
    # should match its own closest GT box, never double-assigned.
    gt = [_gt_obj('g1', 'person', _box(0.0, 0.0, 0.2, 0.2)), _gt_obj('g2', 'person', _box(0.6, 0.6, 0.2, 0.2))]
    det = [_det('person', 0.9, _box(0.0, 0.0, 0.2, 0.2)), _det('person', 0.8, _box(0.6, 0.6, 0.2, 0.2))]
    evidence = match_objects_in_frame(gt, det, iou_threshold=0.5)
    assert evidence.matched_count == 2
    matched_ids = {m.ground_truth_object.id for m in evidence.matches}
    assert matched_ids == {'g1', 'g2'}


def test_one_extra_detection_is_a_false_positive():
    gt = [_gt_obj('g1', 'person', _box(0.0, 0.0, 0.2, 0.2))]
    det = [_det('person', 0.9, _box(0.0, 0.0, 0.2, 0.2)), _det('person', 0.8, _box(0.6, 0.6, 0.2, 0.2))]
    evidence = match_objects_in_frame(gt, det, iou_threshold=0.5)
    assert evidence.matched_count == 1
    assert evidence.false_positive_count == 1
    assert evidence.false_negative_count == 0


def test_one_missing_ground_truth_is_a_false_negative():
    gt = [_gt_obj('g1', 'person', _box(0.0, 0.0, 0.2, 0.2)), _gt_obj('g2', 'person', _box(0.6, 0.6, 0.2, 0.2))]
    det = [_det('person', 0.9, _box(0.0, 0.0, 0.2, 0.2))]
    evidence = match_objects_in_frame(gt, det, iou_threshold=0.5)
    assert evidence.matched_count == 1
    assert evidence.false_positive_count == 0
    assert evidence.false_negative_count == 1


# --- deterministic tie handling (greedy, not Hungarian) --------------------

def test_deterministic_tie_prefers_lower_gt_then_detection_index():
    # Constructed so two GT boxes tie for the exact same IoU against one
    # detection - greedy must pick the lower gt_index deterministically,
    # every time, not whichever happens to iterate first in a set/dict.
    shared_det_box = _box(0.0, 0.0, 0.2, 0.2)
    gt = [_gt_obj('g0', 'person', shared_det_box), _gt_obj('g1', 'person', shared_det_box)]
    det = [_det('person', 0.9, shared_det_box)]
    results = [match_objects_in_frame(gt, det, iou_threshold=0.5) for _ in range(5)]
    assert all(r.matches[0].ground_truth_object.id == 'g0' for r in results)
    assert all(r.false_negative_count == 1 for r in results)  # g1 stays unmatched every time


def test_greedy_matching_can_be_locally_suboptimal_by_design():
    # A real, documented trade-off (this module's own docstring), hand-
    # verified here - not a bug and not hidden. Geometry (all boxes
    # 0.3x0.3, hand-computed IoUs):
    #   IoU(gt_a, det_1) = 1.0    (identical boxes - greedy's top pick)
    #   IoU(gt_a, det_2) = 0.066/0.114 ~= 0.579  (a's fallback, above threshold)
    #   IoU(gt_b, det_1) = 0.066/0.114 ~= 0.579  (b's only viable candidate)
    #   IoU(gt_b, det_2) = 0.0484/0.1316 ~= 0.368  (below threshold - excluded)
    # The globally optimal assignment (gt_a-det_2, gt_b-det_1) would match
    # both objects. Greedy instead takes the single highest-IoU pair
    # (gt_a-det_1) first, which blocks det_1 from gt_b - and gt_b has no
    # other candidate above threshold - so greedy leaves gt_b/det_2 both
    # unmatched where an optimal (Hungarian) assignment would not have.
    gt_a = _gt_obj('a', 'person', _box(0.00, 0.00, 0.3, 0.3))
    gt_b = _gt_obj('b', 'person', _box(0.00, 0.08, 0.3, 0.3))
    det_1 = _det('person', 0.9, _box(0.00, 0.00, 0.3, 0.3))
    det_2 = _det('person', 0.9, _box(0.08, 0.00, 0.3, 0.3))

    evidence = match_objects_in_frame([gt_a, gt_b], [det_1, det_2], iou_threshold=0.5)
    assert evidence.matched_count == 1
    assert evidence.matches[0].ground_truth_object.id == 'a'
    assert evidence.matches[0].detection is det_1
    assert evidence.matches[0].iou == pytest.approx(1.0)
    assert evidence.false_negative_count == 1  # gt_b, even though b-det_1 alone would have cleared threshold
    assert evidence.false_positive_count == 1  # det_2, even though a-det_2 alone would have cleared threshold


# --- compute_detection_evidence: full MatchResult, incl. unmatched frames --

def _session_gt(id_, ts, objects) -> GroundTruth:
    return GroundTruth(
        id=id_, session_id='s1', timestamp_ms=ts, task='object_detection',
        value={'objects': [{'id': o.id, 'label': o.label,
                             'bbox': {'x': o.bbox.x, 'y': o.bbox.y, 'width': o.bbox.width, 'height': o.bbox.height}}
                            for o in objects]},
    )


def _session_pred(id_, ts, detections) -> Prediction:
    return Prediction(
        id=id_, session_id='s1', timestamp_ms=ts, source_id='det', sensor_ids=['rgb'], task='object_detection',
        value={'detections': [{'label': d.label, 'confidence': d.confidence,
                                'bbox': {'x': d.bbox.x, 'y': d.bbox.y, 'width': d.bbox.width, 'height': d.bbox.height}}
                               for d in detections]},
    )


def test_matched_frame_then_object_match():
    box = _box(0.1, 0.1)
    gt = _session_gt('g1', 0.0, [_gt_obj('o1', 'person', box)])
    pred = _session_pred('p1', 1.0, [_det('person', 0.9, box)])
    match_result = match_by_timestamp([gt], [pred], tolerance_ms=50.0)
    assert len(match_result.matched) == 1  # frame-level matching succeeded first

    evidence = compute_detection_evidence(match_result, confidence_threshold=0.5, iou_threshold=0.5)
    assert len(evidence) == 1
    assert evidence[0].matched_count == 1


def test_unmatched_ground_truth_frame_is_all_false_negatives():
    gt = _session_gt('g1', 0.0, [_gt_obj('o1', 'person', _box(0.1, 0.1)), _gt_obj('o2', 'car', _box(0.5, 0.5))])
    match_result = match_by_timestamp([gt], [], tolerance_ms=50.0)
    assert len(match_result.unmatched_ground_truth) == 1

    evidence = compute_detection_evidence(match_result, confidence_threshold=0.5, iou_threshold=0.5)
    assert len(evidence) == 1
    assert evidence[0].predicted_count == 0
    assert evidence[0].false_negative_count == 2
    assert evidence[0].false_positive_count == 0
    assert evidence[0].mean_iou is None


def test_unmatched_prediction_frame_is_all_false_positives():
    pred = _session_pred('p1', 0.0, [_det('person', 0.9, _box(0.1, 0.1))])
    match_result = match_by_timestamp([], [pred], tolerance_ms=50.0)
    assert len(match_result.unmatched_predictions) == 1

    evidence = compute_detection_evidence(match_result, confidence_threshold=0.5, iou_threshold=0.5)
    assert len(evidence) == 1
    assert evidence[0].ground_truth_count == 0
    assert evidence[0].false_positive_count == 1
    assert evidence[0].false_negative_count == 0


def test_timestamp_tolerance_boundary_still_separate_from_object_matching():
    box = _box(0.1, 0.1)
    gt = _session_gt('g1', 0.0, [_gt_obj('o1', 'person', box)])
    # Just outside tolerance - frame matching itself must reject this,
    # before object matching ever gets a chance to run.
    pred = _session_pred('p1', 51.0, [_det('person', 0.9, box)])
    match_result = match_by_timestamp([gt], [pred], tolerance_ms=50.0)
    assert match_result.matched == []
    assert len(match_result.unmatched_ground_truth) == 1
    assert len(match_result.unmatched_predictions) == 1

    evidence = compute_detection_evidence(match_result, confidence_threshold=0.5, iou_threshold=0.5)
    # Two frames, both entirely unmatched - never merged into one
    # "almost matched" object-level comparison.
    assert len(evidence) == 2
    assert {e.false_negative_count for e in evidence} == {0, 1}
    assert {e.false_positive_count for e in evidence} == {0, 1}


def test_multiple_frames_each_evaluated_independently():
    box = _box(0.1, 0.1)
    gts = [_session_gt('g1', 0.0, [_gt_obj('o1', 'person', box)]), _session_gt('g2', 1000.0, [])]
    preds = [_session_pred('p1', 1.0, [_det('person', 0.9, box)]), _session_pred('p2', 1001.0, [])]
    match_result = match_by_timestamp(gts, preds, tolerance_ms=50.0)
    assert len(match_result.matched) == 2

    evidence = compute_detection_evidence(match_result, confidence_threshold=0.5, iou_threshold=0.5)
    assert len(evidence) == 2
    assert evidence[0].matched_count == 1
    assert evidence[1].predicted_count == 0 and evidence[1].ground_truth_count == 0


# --- confidence filtering happens before matching --------------------------

def test_confidence_below_threshold_dropped_before_matching():
    box = _box(0.1, 0.1)
    gt = _session_gt('g1', 0.0, [_gt_obj('o1', 'person', box)])
    pred = _session_pred('p1', 1.0, [_det('person', 0.3, box)])  # below the 0.5 confidence_threshold
    match_result = match_by_timestamp([gt], [pred], tolerance_ms=50.0)

    evidence = compute_detection_evidence(match_result, confidence_threshold=0.5, iou_threshold=0.5)
    assert evidence[0].predicted_count == 0  # dropped entirely, not just unmatched
    assert evidence[0].false_negative_count == 1
    assert evidence[0].false_positive_count == 0
