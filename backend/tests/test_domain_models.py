from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.models import (
    EvaluationResult,
    GroundTruth,
    Prediction,
    Scenario,
    Session,
    derive_configuration_id,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_configuration_id_is_order_independent():
    assert derive_configuration_id(['rgb', 'depth']) == derive_configuration_id(['depth', 'rgb'])


def test_configuration_id_derived_when_omitted():
    p = Prediction(
        id='p1', session_id='s1', timestamp_ms=0.0, source_id='det',
        sensor_ids=['depth', 'rgb'], task='presence', value={'label': 'present'},
    )
    assert p.configuration_id == 'cfg-depth-rgb'


def test_configuration_id_mismatch_rejected():
    with pytest.raises(ValidationError):
        Prediction(
            id='p1', session_id='s1', timestamp_ms=0.0, source_id='det',
            sensor_ids=['rgb'], configuration_id='cfg-depth', task='presence',
            value={'label': 'present'},
        )


def test_prediction_requires_nonempty_sensor_ids():
    with pytest.raises(ValidationError):
        Prediction(
            id='p1', session_id='s1', timestamp_ms=0.0, source_id='det',
            sensor_ids=[], task='presence', value={'label': 'present'},
        )


@pytest.mark.parametrize('confidence', [-0.01, 1.01, 5.0])
def test_prediction_confidence_out_of_range_rejected(confidence):
    with pytest.raises(ValidationError):
        Prediction(
            id='p1', session_id='s1', timestamp_ms=0.0, source_id='det',
            sensor_ids=['rgb'], task='presence', value={'label': 'present'},
            confidence=confidence,
        )


def test_prediction_confidence_none_allowed():
    p = Prediction(
        id='p1', session_id='s1', timestamp_ms=0.0, source_id='det',
        sensor_ids=['rgb'], task='presence', value={'label': 'present'},
    )
    assert p.confidence is None


def test_prediction_value_shape_is_generic_not_classification_specific():
    # A hypothetical future detection task must fit through the exact same
    # `value: dict` field a classification task uses today - no schema
    # change for GroundTruth/Prediction when detection/regression arrive.
    p = Prediction(
        id='p1', session_id='s1', timestamp_ms=0.0, source_id='det',
        sensor_ids=['rgb'], task='bbox_detection',
        value={'bbox': [10, 20, 100, 200], 'class': 'person'},
    )
    assert p.value['bbox'] == [10, 20, 100, 200]

    gt = GroundTruth(
        id='g1', session_id='s1', timestamp_ms=0.0, task='bbox_detection',
        value={'bbox': [12, 18, 98, 205], 'class': 'person'},
    )
    assert gt.value['class'] == 'person'


def test_session_defaults_to_created_status():
    s = Session(id='s1', name='demo', scenario_id='sc1', started_at=_now())
    assert s.status == 'created'


def test_session_rejects_invalid_status():
    with pytest.raises(ValidationError):
        Session(id='s1', name='demo', scenario_id='sc1', started_at=_now(), status='bogus')


def test_scenario_defaults_are_empty_not_none():
    sc = Scenario(id='sc1', name='demo')
    assert sc.tags == []
    assert sc.metadata == {}


def test_evaluation_result_na_metric_is_none_not_zero():
    # An unavailable metric must be distinguishable from a calculated zero.
    result = EvaluationResult(
        id='e1', session_id='s1', configuration_id='cfg-rgb', task='presence',
        sample_count=0, matched_samples=0, unmatched_predictions=0,
        unmatched_ground_truth=0,
        metrics={'accuracy': None, 'precision_macro': 0.0},
        computed_at=_now(),
    )
    assert result.metrics['accuracy'] is None
    assert result.metrics['precision_macro'] == 0.0
    assert result.metrics['accuracy'] is not result.metrics['precision_macro']
