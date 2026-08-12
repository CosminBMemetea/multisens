"""Multi-class classification metrics over a matched ground-truth/
prediction set. Pure function - no persistence, no FastAPI, no ROS.

Accuracy is computed over matched_samples only: an unmatched item is a
coverage problem (see sample_count/matched_samples/unmatched_* below), not
a wrong-answer problem, and folding it into accuracy would understate a
model's correctness for a reason that isn't the model's fault.

An "unavailable" metric (a zero denominator - e.g. a class the model never
predicted, so its precision is undefined) is represented as None, never
coerced to 0.0 - see app.domain.models.MetricValue. This is the rule most
likely to get silently violated during implementation, so it has dedicated
tests (test_metrics.py) rather than just this docstring.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.matching import MatchResult
from app.domain.models import MetricValue


@dataclass
class ConfusionMatrix:
    labels: list[str]
    counts: list[list[int]]  # counts[actual_index][predicted_index]


@dataclass
class ClassificationMetrics:
    label_set: list[str]
    sample_count: int
    matched_samples: int
    unmatched_predictions: int
    unmatched_ground_truth: int
    accuracy: MetricValue
    precision_macro: MetricValue
    recall_macro: MetricValue
    f1_macro: MetricValue
    precision_micro: MetricValue
    recall_micro: MetricValue
    f1_micro: MetricValue
    confusion_matrix: ConfusionMatrix


def evaluate_classification(match_result: MatchResult, label_key: str = 'label') -> ClassificationMetrics:
    matched_samples = len(match_result.matched)
    unmatched_ground_truth = len(match_result.unmatched_ground_truth)
    unmatched_predictions = len(match_result.unmatched_predictions)
    sample_count = matched_samples + unmatched_ground_truth

    pairs = [
        (extract_label(m.ground_truth.value, label_key), extract_label(m.prediction.value, label_key))
        for m in match_result.matched
    ]

    # Label set is the union actually seen in the matched set, not every
    # label either input file happens to define - a label that never
    # appears in a match contributes nothing to the confusion matrix.
    label_set = sorted({label for pair in pairs for label in pair})
    index_of = {label: i for i, label in enumerate(label_set)}
    counts = [[0] * len(label_set) for _ in label_set]
    for actual, predicted in pairs:
        counts[index_of[actual]][index_of[predicted]] += 1

    correct = sum(counts[i][i] for i in range(len(label_set)))
    accuracy = (correct / matched_samples) if matched_samples > 0 else None

    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    tp_total = fp_total = fn_total = 0
    for i in range(len(label_set)):
        tp = counts[i][i]
        fp = sum(counts[r][i] for r in range(len(label_set)) if r != i)
        fn = sum(counts[i][c] for c in range(len(label_set)) if c != i)
        tp_total += tp
        fp_total += fp
        fn_total += fn

        precision = (tp / (tp + fp)) if (tp + fp) > 0 else None
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else None
        f1 = _f1(precision, recall)

        # Macro average is a mean over classes where the metric is
        # actually defined - a class excluded here (never predicted, or
        # never true) would otherwise silently drag the average toward a
        # fabricated zero.
        if precision is not None:
            precisions.append(precision)
        if recall is not None:
            recalls.append(recall)
        if f1 is not None:
            f1s.append(f1)

    precision_macro = (sum(precisions) / len(precisions)) if precisions else None
    recall_macro = (sum(recalls) / len(recalls)) if recalls else None
    f1_macro = (sum(f1s) / len(f1s)) if f1s else None

    precision_micro = (tp_total / (tp_total + fp_total)) if (tp_total + fp_total) > 0 else None
    recall_micro = (tp_total / (tp_total + fn_total)) if (tp_total + fn_total) > 0 else None
    f1_micro = _f1(precision_micro, recall_micro)

    return ClassificationMetrics(
        label_set=label_set,
        sample_count=sample_count,
        matched_samples=matched_samples,
        unmatched_predictions=unmatched_predictions,
        unmatched_ground_truth=unmatched_ground_truth,
        accuracy=accuracy,
        precision_macro=precision_macro,
        recall_macro=recall_macro,
        f1_macro=f1_macro,
        precision_micro=precision_micro,
        recall_micro=recall_micro,
        f1_micro=f1_micro,
        confusion_matrix=ConfusionMatrix(labels=label_set, counts=counts),
    )


def extract_label(value: dict, label_key: str) -> str:
    if label_key not in value:
        raise ValueError(f"value {value!r} has no '{label_key}' field - not a classification task?")
    return str(value[label_key])


def _f1(precision: MetricValue, recall: MetricValue) -> MetricValue:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)
