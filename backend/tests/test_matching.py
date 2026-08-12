from app.domain.matching import match_by_timestamp
from app.domain.models import GroundTruth, Prediction


def gt(id_: str, ts: float) -> GroundTruth:
    return GroundTruth(id=id_, session_id='s1', timestamp_ms=ts, task='presence', value={'label': 'present'})


def pred(id_: str, ts: float) -> Prediction:
    return Prediction(
        id=id_, session_id='s1', timestamp_ms=ts, source_id='det', sensor_ids=['rgb'],
        task='presence', value={'label': 'present'},
    )


def test_exact_match_within_tolerance():
    result = match_by_timestamp([gt('g1', 100.0)], [pred('p1', 104.0)], tolerance_ms=25.0)
    assert len(result.matched) == 1
    assert result.matched[0].delta_ms == 4.0
    assert not result.unmatched_ground_truth
    assert not result.unmatched_predictions


def test_match_at_exact_tolerance_boundary_is_inclusive():
    result = match_by_timestamp([gt('g1', 100.0)], [pred('p1', 125.0)], tolerance_ms=25.0)
    assert len(result.matched) == 1


def test_no_match_just_outside_tolerance():
    result = match_by_timestamp([gt('g1', 100.0)], [pred('p1', 125.01)], tolerance_ms=25.0)
    assert not result.matched
    assert result.unmatched_ground_truth == [gt('g1', 100.0)]
    assert result.unmatched_predictions == [pred('p1', 125.01)]


def test_empty_ground_truth_all_predictions_unmatched():
    predictions = [pred('p1', 100.0), pred('p2', 200.0)]
    result = match_by_timestamp([], predictions, tolerance_ms=25.0)
    assert result.matched == []
    assert result.unmatched_ground_truth == []
    assert len(result.unmatched_predictions) == 2


def test_empty_predictions_all_ground_truth_unmatched():
    ground_truth = [gt('g1', 100.0), gt('g2', 200.0)]
    result = match_by_timestamp(ground_truth, [], tolerance_ms=25.0)
    assert result.matched == []
    assert len(result.unmatched_ground_truth) == 2
    assert result.unmatched_predictions == []


def test_both_empty():
    result = match_by_timestamp([], [], tolerance_ms=25.0)
    assert result.matched == result.unmatched_ground_truth == result.unmatched_predictions == []


def test_nearest_prediction_chosen_among_multiple_candidates():
    predictions = [pred('far', 90.0), pred('near', 103.0), pred('other', 115.0)]
    result = match_by_timestamp([gt('g1', 100.0)], predictions, tolerance_ms=25.0)
    assert result.matched[0].prediction.id == 'near'
    assert {p.id for p in result.unmatched_predictions} == {'far', 'other'}


def test_tie_break_prefers_earlier_timestamp():
    # Both 95.0 and 105.0 are exactly 5ms from gt at 100.0 - earlier wins.
    predictions = [pred('later', 105.0), pred('earlier', 95.0)]
    result = match_by_timestamp([gt('g1', 100.0)], predictions, tolerance_ms=25.0)
    assert result.matched[0].prediction.id == 'earlier'


def test_greedy_one_to_one_prediction_consumed_only_once():
    # Two ground-truth points both want the single nearby prediction;
    # earlier-processed (lower timestamp) gt claims it, the other goes
    # unmatched rather than double-counting the same prediction.
    ground_truth = [gt('g1', 100.0), gt('g2', 101.0)]
    predictions = [pred('p1', 100.5)]
    result = match_by_timestamp(ground_truth, predictions, tolerance_ms=25.0)
    assert len(result.matched) == 1
    assert result.matched[0].ground_truth.id == 'g1'
    assert result.unmatched_ground_truth == [gt('g2', 101.0)]


def test_duplicate_ground_truth_timestamps_matched_independently():
    ground_truth = [gt('g1', 100.0), gt('g2', 100.0)]
    predictions = [pred('p1', 100.0), pred('p2', 100.0)]
    result = match_by_timestamp(ground_truth, predictions, tolerance_ms=25.0)
    assert len(result.matched) == 2
    assert not result.unmatched_ground_truth
    assert not result.unmatched_predictions


def test_unsorted_input_still_matches_correctly():
    ground_truth = [gt('g2', 200.0), gt('g1', 100.0)]
    predictions = [pred('p2', 201.0), pred('p1', 99.0)]
    result = match_by_timestamp(ground_truth, predictions, tolerance_ms=25.0)
    matched_ids = {(m.ground_truth.id, m.prediction.id) for m in result.matched}
    assert matched_ids == {('g1', 'p1'), ('g2', 'p2')}


def test_negative_tolerance_rejected():
    import pytest
    with pytest.raises(ValueError):
        match_by_timestamp([], [], tolerance_ms=-1.0)


def test_zero_tolerance_requires_exact_timestamp():
    result = match_by_timestamp([gt('g1', 100.0)], [pred('p1', 100.0), pred('p2', 100.001)], tolerance_ms=0.0)
    assert result.matched[0].prediction.id == 'p1'
    assert result.unmatched_predictions == [pred('p2', 100.001)]
