"""Evidence Playback (v0.9.1, issue #120): per-ground-truth-sample
evidence, joined across every `(configuration_id, source_id)` pair
active in a session for a task.

`match_by_timestamp` (matching.py) already computes exactly this
per-sample detail internally - `/evaluate` (api/evaluation.py) just
aggregates it away into metrics and discards the per-sample pairs. This
module reuses `match_by_timestamp` verbatim, once per `(configuration_id,
source_id)` pair, then pivots the results so each ground-truth sample
becomes one row with one column per source - never new matching logic,
never a second way to decide what "matched" means.

**Never infers a combined/fused value.** A "source" here is always
exactly one already-ingested `Prediction` stream, identified by its own
`(configuration_id, source_id)`. A combined/union prediction is only
ever visible here because a real `Prediction` row with that `source_id`
was ingested - this module has no fusion logic anywhere, does not
average, vote, or OR two sources together. See `docs/resources.md`-style
"never fabricate" discipline applied to a new layer.

**Relationship classification is computed once, here - never left for
the frontend to infer from raw values**, matching `/compare`'s own
`validity: {status, reasons}` precedent (comparison.py): a UI computing
its own "did these agree" logic from raw numbers is exactly the kind of
place a subtly-wrong client-side reimplementation could drift from the
server's own answer.

`positive_label` is a required argument, not defaulted - which label
counts as "the event of interest" (e.g. `'present'`) is a modeling
decision this module was never told and must never guess, the same
"required, never silently defaulted" posture object_detection's
`confidence_threshold`/`iou_threshold` already have (no default,
evaluation.py's own EvaluateRequest).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.matching import match_by_timestamp
from app.domain.metrics import extract_label
from app.domain.models import GroundTruth, Prediction

Relationship = Literal[
    'AGREE_POSITIVE', 'AGREE_NEGATIVE', 'DISAGREE', 'ONLY_ONE_SOURCE_AVAILABLE', 'NO_COMMON_GT_SAMPLE',
]

Outcome = Literal['TP', 'FP', 'FN', 'TN']


@dataclass
class SourceEvidence:
    """One `(configuration_id, source_id)` pair's evidence for one
    ground-truth sample - present for every known source in the session,
    even when that source had no matching prediction (`prediction_id is
    None`), so "this source never even attempted this moment" stays
    visible rather than silently absent."""
    configuration_id: str
    source_id: str
    sensor_ids: list[str]
    prediction_id: str | None = None
    prediction_timestamp_ms: float | None = None
    value: dict[str, Any] | None = None
    confidence: float | None = None
    match_delta_ms: float | None = None
    # None whenever there's no match, or the matched value has no
    # `label_key` field (not a classification-shaped task) - never a
    # guessed TP/FP/FN/TN for data this module can't actually classify.
    outcome: Outcome | None = None


@dataclass
class EvidenceSample:
    gt_sample_id: str
    gt_timestamp_ms: float
    task: str
    gt_value: dict[str, Any]
    sources: list[SourceEvidence] = field(default_factory=list)
    relationship: Relationship = 'NO_COMMON_GT_SAMPLE'


def _outcome(actual_label: str, predicted_label: str, positive_label: str) -> Outcome:
    actual_positive = actual_label == positive_label
    predicted_positive = predicted_label == positive_label
    if actual_positive and predicted_positive:
        return 'TP'
    if actual_positive and not predicted_positive:
        return 'FN'
    if not actual_positive and predicted_positive:
        return 'FP'
    return 'TN'


def build_evidence_samples(
    ground_truth: list[GroundTruth],
    predictions_by_source: dict[tuple[str, str], list[Prediction]],
    tolerance_ms: float,
    positive_label: str,
    label_key: str = 'label',
) -> list[EvidenceSample]:
    """`predictions_by_source` is keyed by `(configuration_id, source_id)`
    - the caller (the API layer, which already knows how to enumerate
    every distinct pair via `repository.list_configuration_ids`/
    `list_distinct_source_ids`) decides which sources exist; this
    function only joins and classifies. Every key present in
    `predictions_by_source` gets its own `SourceEvidence` column on every
    returned `EvidenceSample`, whether or not that source matched this
    particular ground-truth point."""
    sources = sorted(predictions_by_source)

    # match_by_timestamp per source - the exact same call /evaluate
    # itself makes per configuration_id, just also split by source_id.
    matched_by_source: dict[tuple[str, str], dict[str, tuple[Prediction, float]]] = {}
    for key in sources:
        match_result = match_by_timestamp(ground_truth, predictions_by_source[key], tolerance_ms=tolerance_ms)
        matched_by_source[key] = {
            pair.ground_truth.id: (pair.prediction, pair.delta_ms) for pair in match_result.matched
        }

    samples: list[EvidenceSample] = []
    for gt in sorted(ground_truth, key=lambda g: g.timestamp_ms):
        source_evidences: list[SourceEvidence] = []
        predicted_labels: list[str] = []

        for configuration_id, source_id in sources:
            match = matched_by_source[(configuration_id, source_id)].get(gt.id)
            if match is None:
                source_evidences.append(SourceEvidence(
                    configuration_id=configuration_id, source_id=source_id, sensor_ids=[],
                ))
                continue

            prediction, delta_ms = match
            outcome: Outcome | None = None
            try:
                actual_label = extract_label(gt.value, label_key)
                predicted_label = extract_label(prediction.value, label_key)
                outcome = _outcome(actual_label, predicted_label, positive_label)
                predicted_labels.append(predicted_label)
            except ValueError:
                pass  # not a classification-shaped value - outcome stays None, raw value still reported

            source_evidences.append(SourceEvidence(
                configuration_id=configuration_id, source_id=source_id, sensor_ids=prediction.sensor_ids,
                prediction_id=prediction.id, prediction_timestamp_ms=prediction.timestamp_ms,
                value=prediction.value, confidence=prediction.confidence, match_delta_ms=delta_ms,
                outcome=outcome,
            ))

        matched_count = sum(1 for s in source_evidences if s.prediction_id is not None)
        if matched_count == 0:
            relationship: Relationship = 'NO_COMMON_GT_SAMPLE'
        elif matched_count == 1:
            relationship = 'ONLY_ONE_SOURCE_AVAILABLE'
        elif len(set(predicted_labels)) == 1 and len(predicted_labels) == matched_count:
            relationship = 'AGREE_POSITIVE' if predicted_labels[0] == positive_label else 'AGREE_NEGATIVE'
        else:
            # Also covers the case where a matched source's value has no
            # `label_key` (predicted_labels has fewer entries than
            # matched_count) - never claim verified agreement when it
            # can't actually be verified for every matched source.
            relationship = 'DISAGREE'

        samples.append(EvidenceSample(
            gt_sample_id=gt.id, gt_timestamp_ms=gt.timestamp_ms, task=gt.task, gt_value=gt.value,
            sources=source_evidences, relationship=relationship,
        ))

    return samples
