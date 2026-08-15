"""v0.9.1 (issue #120): Evidence Playback - build_evidence_samples().

Reuses match_by_timestamp verbatim (no new matching logic here); this
tests the pivot-by-GT-sample and relationship classification on top of
it. Fixtures deliberately mirror the real RideSafe recorded experiment's
shape (front/rear disjoint windows, a union/combined source, one real
false positive) rather than only synthetic toy data.
"""
from app.domain.evidence_playback import build_evidence_samples
from app.domain.models import GroundTruth, Prediction


def gt(id_: str, ts: float, label: str = 'present') -> GroundTruth:
    return GroundTruth(id=id_, session_id='s1', timestamp_ms=ts, task='vehicle_presence', value={'label': label})


def pred(id_: str, ts: float, label: str, source_id: str = 'det', sensor_ids=None, confidence=None) -> Prediction:
    return Prediction(
        id=id_, session_id='s1', timestamp_ms=ts, source_id=source_id, sensor_ids=sensor_ids or ['rgb'],
        task='vehicle_presence', value={'label': label}, confidence=confidence,
    )


# --- single source ------------------------------------------------------

def test_single_matched_source_reports_the_only_available_relationship():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 102.0, 'present')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert len(samples) == 1
    s = samples[0]
    assert s.gt_sample_id == 'g1'
    assert s.relationship == 'ONLY_ONE_SOURCE_AVAILABLE'
    assert len(s.sources) == 1
    assert s.sources[0].outcome == 'TP'
    assert s.sources[0].match_delta_ms == 2.0


def test_no_matching_prediction_from_any_source_is_no_common_gt_sample():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 5000.0, 'present')]},  # way outside tolerance
        tolerance_ms=50.0, positive_label='present',
    )
    s = samples[0]
    assert s.relationship == 'NO_COMMON_GT_SAMPLE'
    assert s.sources[0].prediction_id is None
    assert s.sources[0].outcome is None


# --- multi-source outcomes -----------------------------------------------

def test_true_positive():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'present')],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 100.0, 'present')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].sources[0].outcome == 'TP'


def test_false_positive():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'absent')],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 100.0, 'present')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].sources[0].outcome == 'FP'


def test_false_negative():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'present')],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 100.0, 'absent')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].sources[0].outcome == 'FN'


def test_true_negative():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'absent')],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 100.0, 'absent')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].sources[0].outcome == 'TN'


# --- multi-source relationships -------------------------------------------

def test_two_sources_agree_positive():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'present')],
        predictions_by_source={
            ('cfg-front', 'det'): [pred('p1', 100.0, 'present', sensor_ids=['front'])],
            ('cfg-rear', 'det'): [pred('p2', 100.0, 'present', sensor_ids=['rear'])],
        },
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].relationship == 'AGREE_POSITIVE'


def test_two_sources_agree_negative():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'absent')],
        predictions_by_source={
            ('cfg-front', 'det'): [pred('p1', 100.0, 'absent', sensor_ids=['front'])],
            ('cfg-rear', 'det'): [pred('p2', 100.0, 'absent', sensor_ids=['rear'])],
        },
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].relationship == 'AGREE_NEGATIVE'


def test_two_sources_disagree():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0, 'present')],
        predictions_by_source={
            ('cfg-front', 'det'): [pred('p1', 100.0, 'present', sensor_ids=['front'])],
            ('cfg-rear', 'det'): [pred('p2', 100.0, 'absent', sensor_ids=['rear'])],
        },
        tolerance_ms=50.0, positive_label='present',
    )
    s = samples[0]
    assert s.relationship == 'DISAGREE'
    front = next(x for x in s.sources if x.configuration_id == 'cfg-front')
    rear = next(x for x in s.sources if x.configuration_id == 'cfg-rear')
    assert front.outcome == 'TP'
    assert rear.outcome == 'FN'


# --- every known source gets a column, even when absent for this sample --

def test_every_known_source_appears_as_a_column_even_when_it_has_no_match_here():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={
            ('cfg-front', 'det'): [pred('p1', 100.0, 'present')],
            ('cfg-rear', 'det'): [],  # rear never predicted anything near this timestamp
        },
        tolerance_ms=50.0, positive_label='present',
    )
    s = samples[0]
    assert {src.configuration_id for src in s.sources} == {'cfg-front', 'cfg-rear'}
    rear = next(x for x in s.sources if x.configuration_id == 'cfg-rear')
    assert rear.prediction_id is None
    assert rear.outcome is None
    assert s.relationship == 'ONLY_ONE_SOURCE_AVAILABLE'


# --- non-classification-shaped value never crashes, never fabricates -----

def test_a_value_without_the_label_key_leaves_outcome_none_not_a_crash():
    weird_pred = Prediction(
        id='p1', session_id='s1', timestamp_ms=100.0, source_id='det', sensor_ids=['rgb'],
        task='vehicle_presence', value={'bbox': [1, 2, 3, 4]},  # no 'label' key
    )
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [weird_pred]},
        tolerance_ms=50.0, positive_label='present',
    )
    s = samples[0]
    assert s.sources[0].prediction_id == 'p1'  # still reported, raw value intact
    assert s.sources[0].value == {'bbox': [1, 2, 3, 4]}
    assert s.sources[0].outcome is None


# --- never fabricates a combined source that wasn't ingested --------------

def test_never_synthesizes_a_source_that_was_never_ingested():
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 100.0, 'present')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert {(src.configuration_id, src.source_id) for src in samples[0].sources} == {('cfg-front', 'det')}


# --- confidence/sensor_ids/timestamps pass through untouched --------------

def test_confidence_and_sensor_ids_pass_through_only_when_actually_ingested():
    with_confidence = pred('p1', 100.0, 'present', confidence=0.84, sensor_ids=['ridesafe_front_rgb'])
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [with_confidence]},
        tolerance_ms=50.0, positive_label='present',
    )
    s = samples[0].sources[0]
    assert s.confidence == 0.84
    assert s.sensor_ids == ['ridesafe_front_rgb']


def test_confidence_is_none_not_fabricated_when_never_ingested():
    without_confidence = pred('p1', 100.0, 'present')  # confidence defaults to None
    samples = build_evidence_samples(
        ground_truth=[gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [without_confidence]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert samples[0].sources[0].confidence is None


# --- multiple GT samples, sorted by timestamp -----------------------------

def test_multiple_samples_sorted_by_timestamp():
    samples = build_evidence_samples(
        ground_truth=[gt('g2', 200.0), gt('g1', 100.0)],
        predictions_by_source={('cfg-front', 'det'): [pred('p1', 100.0, 'present'), pred('p2', 200.0, 'present')]},
        tolerance_ms=50.0, positive_label='present',
    )
    assert [s.gt_sample_id for s in samples] == ['g1', 'g2']
