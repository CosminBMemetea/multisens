import pytest

from app.domain.matching import MatchedPair, MatchResult
from app.domain.metrics import evaluate_classification
from app.domain.models import GroundTruth, Prediction


def _gt(label: str, ts: float = 0.0) -> GroundTruth:
    return GroundTruth(id=f'g-{ts}-{label}', session_id='s1', timestamp_ms=ts, task='presence', value={'label': label})


def _pred(label: str, ts: float = 0.0) -> Prediction:
    return Prediction(
        id=f'p-{ts}-{label}', session_id='s1', timestamp_ms=ts, source_id='det', sensor_ids=['rgb'],
        task='presence', value={'label': label},
    )


def _match_result(pairs: list[tuple[str, str]], unmatched_gt: int = 0, unmatched_pred: int = 0) -> MatchResult:
    matched = [
        MatchedPair(ground_truth=_gt(actual, i), prediction=_pred(predicted, i), delta_ms=0.0)
        for i, (actual, predicted) in enumerate(pairs)
    ]
    return MatchResult(
        matched=matched,
        unmatched_ground_truth=[_gt('present', 1000 + i) for i in range(unmatched_gt)],
        unmatched_predictions=[_pred('present', 2000 + i) for i in range(unmatched_pred)],
    )


def test_perfect_predictions_binary():
    result = _match_result([('present', 'present'), ('absent', 'absent'), ('present', 'present')])
    metrics = evaluate_classification(result)
    assert metrics.accuracy == 1.0
    assert metrics.precision_macro == 1.0
    assert metrics.recall_macro == 1.0
    assert metrics.f1_macro == 1.0
    assert metrics.matched_samples == 3
    assert metrics.sample_count == 3


def test_completely_wrong_predictions_binary_f1_na_when_precision_and_recall_both_zero():
    result = _match_result([('present', 'absent'), ('absent', 'present')])
    metrics = evaluate_classification(result)
    assert metrics.accuracy == 0.0
    assert metrics.precision_macro == 0.0  # both classes: defined (denom=1) but zero
    assert metrics.recall_macro == 0.0
    assert metrics.f1_macro is None  # 2*0*0/(0+0) is undefined, not 0.0


def test_empty_dataset_all_metrics_na():
    result = _match_result([])
    metrics = evaluate_classification(result)
    assert metrics.sample_count == 0
    assert metrics.matched_samples == 0
    assert metrics.accuracy is None
    assert metrics.precision_macro is None
    assert metrics.recall_macro is None
    assert metrics.f1_macro is None
    assert metrics.precision_micro is None
    assert metrics.confusion_matrix.labels == []
    assert metrics.confusion_matrix.counts == []


def test_precision_undefined_for_never_predicted_class():
    # model always predicts 'a'; 'b' and 'c' are true classes it never
    # outputs - their precision has a zero denominator (never predicted),
    # but their recall is well-defined (it just always misses).
    #
    # Per-class, by hand: a: tp=1, fp=2 (b and c both misclassified as a),
    # fn=0 -> precision=1/3, recall=1.0. b: tp=0, fp=0 (never predicted),
    # fn=1 -> precision=None (0/0), recall=0.0. c: symmetric to b.
    result = _match_result([('a', 'a'), ('b', 'a'), ('c', 'a')])
    metrics = evaluate_classification(result)

    assert metrics.confusion_matrix.labels == ['a', 'b', 'c']
    assert metrics.accuracy == pytest.approx(1 / 3)
    # macro precision averages only over 'a' (the one defined value) -
    # 'b' and 'c' are None and excluded, not counted as zero.
    assert metrics.precision_macro == pytest.approx(1 / 3)
    assert metrics.recall_macro == pytest.approx((1.0 + 0.0 + 0.0) / 3)


def test_micro_metrics_equal_accuracy_for_single_label_multiclass():
    result = _match_result([('a', 'a'), ('a', 'b'), ('b', 'b'), ('c', 'a'), ('c', 'c')])
    metrics = evaluate_classification(result)
    assert metrics.precision_micro == pytest.approx(metrics.accuracy)
    assert metrics.recall_micro == pytest.approx(metrics.accuracy)
    assert metrics.f1_micro == pytest.approx(metrics.accuracy)


def test_unmatched_samples_counted_but_excluded_from_accuracy():
    result = _match_result([('present', 'present')], unmatched_gt=3, unmatched_pred=2)
    metrics = evaluate_classification(result)
    assert metrics.matched_samples == 1
    assert metrics.unmatched_ground_truth == 3
    assert metrics.unmatched_predictions == 2
    assert metrics.sample_count == 4  # matched + unmatched ground truth
    assert metrics.accuracy == 1.0  # not diluted by the 3 unmatched GT points


def test_confusion_matrix_is_not_hardcoded_to_binary():
    result = _match_result([('a', 'a'), ('b', 'c'), ('c', 'c'), ('d', 'a')])
    metrics = evaluate_classification(result)
    assert metrics.confusion_matrix.labels == ['a', 'b', 'c', 'd']
    assert len(metrics.confusion_matrix.counts) == 4
    assert all(len(row) == 4 for row in metrics.confusion_matrix.counts)


def test_missing_label_key_raises_clear_error():
    matched = [MatchedPair(
        ground_truth=GroundTruth(id='g1', session_id='s1', timestamp_ms=0.0, task='presence', value={}),
        prediction=_pred('present'),
        delta_ms=0.0,
    )]
    result = MatchResult(matched=matched, unmatched_ground_truth=[], unmatched_predictions=[])
    with pytest.raises(ValueError, match='label'):
        evaluate_classification(result)


def test_custom_label_key():
    matched = [MatchedPair(
        ground_truth=GroundTruth(id='g1', session_id='s1', timestamp_ms=0.0, task='cls', value={'class': 'cat'}),
        prediction=Prediction(
            id='p1', session_id='s1', timestamp_ms=0.0, source_id='det', sensor_ids=['rgb'],
            task='cls', value={'class': 'cat'},
        ),
        delta_ms=0.0,
    )]
    result = MatchResult(matched=matched, unmatched_ground_truth=[], unmatched_predictions=[])
    metrics = evaluate_classification(result, label_key='class')
    assert metrics.accuracy == 1.0
