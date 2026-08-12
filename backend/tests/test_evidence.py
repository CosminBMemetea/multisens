"""Phase 33: evidence selection tests. Pure domain logic, no client
fixture needed - Session/EvaluationResult objects are constructed
directly, exactly as the coverage engine (Phase 35) would after fetching
them from the repository."""
from datetime import datetime, timezone

import pytest

from app.domain.evidence import (
    EvidenceBinding,
    SessionCandidate,
    discover_condition_values,
    matches_conditions,
    select_evidence,
)
from app.domain.models import EvaluationResult, Session
from app.domain.profiles import AcceptanceCriterion, Requirement


def _session(**overrides) -> Session:
    defaults = dict(
        id='s1', name='Session 1', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        metadata={'illumination': 'night', 'eyewear': 'glasses'},
    )
    return Session(**{**defaults, **overrides})


def _evaluation_result(**overrides) -> EvaluationResult:
    defaults = dict(
        id='er1', session_id='s1', configuration_id='cfg-rgb', task='presence',
        tolerance_ms=100.0, sample_count=100, matched_samples=95,
        unmatched_predictions=2, unmatched_ground_truth=5,
        metrics={'recall_macro': 0.94}, computed_at=datetime.now(timezone.utc),
    )
    return EvaluationResult(**{**defaults, **overrides})


def _requirement(**overrides) -> Requirement:
    defaults = dict(
        id='req-001', group_id='g1', name='Variant 1', task='presence',
        conditions={'illumination': 'night'},
        acceptance=[AcceptanceCriterion(metric='recall_macro', operator='>=', value=0.9)],
    )
    return Requirement(**{**defaults, **overrides})


def _candidate(session=None, evaluation_result=None, source_ids=None) -> SessionCandidate:
    return SessionCandidate(
        session=session or _session(),
        evaluation_result=evaluation_result or _evaluation_result(),
        source_ids=source_ids if source_ids is not None else ['rgb_model'],
    )


# --- matches_conditions ------------------------------------------------

def test_matches_conditions_exact_subset():
    session = _session(metadata={'illumination': 'night', 'eyewear': 'glasses'})
    assert matches_conditions(session, {'illumination': 'night'}) is True


def test_matches_conditions_ignores_extra_evidence_metadata():
    session = _session(metadata={'illumination': 'night', 'eyewear': 'glasses', 'smoke': False})
    assert matches_conditions(session, {'illumination': 'night', 'eyewear': 'glasses'}) is True


def test_matches_conditions_missing_evidence_key_is_no_match():
    session = _session(metadata={'illumination': 'night'})
    assert matches_conditions(session, {'illumination': 'night', 'eyewear': 'glasses'}) is False


def test_matches_conditions_mismatched_value_is_no_match():
    session = _session(metadata={'illumination': 'day'})
    assert matches_conditions(session, {'illumination': 'night'}) is False


def test_matches_conditions_boolean_vs_numeric_is_type_sensitive():
    # Python's `1 == True` is True - this must NOT be treated as a match.
    session = _session(metadata={'smoke': 1})
    assert matches_conditions(session, {'smoke': True}) is False
    session2 = _session(metadata={'smoke': True})
    assert matches_conditions(session2, {'smoke': 1.0}) is False


def test_matches_conditions_numeric_int_float_equality_still_allowed():
    # Not a type mismatch - both are numbers, this is a JSON round-trip
    # detail (a JSON literal `3` deserializes as Python int, `3.0` as
    # float), not the bool/int collision the previous test guards against.
    session = _session(metadata={'vibration_level': 3})
    assert matches_conditions(session, {'vibration_level': 3.0}) is True


def test_matches_conditions_empty_conditions_matches_any_session():
    session = _session(metadata={})
    assert matches_conditions(session, {}) is True


# --- select_evidence: discovery -----------------------------------------

def test_select_evidence_single_match_resolves():
    candidate = _candidate()
    result = select_evidence(_requirement(), [candidate])
    assert result.resolved is not None
    assert result.resolved.session.id == 's1'
    assert result.resolved.source_id == 'rgb_model'
    assert result.reasons == []


def test_select_evidence_zero_matches_is_na_with_reason():
    session = _session(metadata={'illumination': 'day'})
    result = select_evidence(_requirement(), [_candidate(session=session)])
    assert result.resolved is None
    assert any('no session matches conditions' in r for r in result.reasons)


def test_select_evidence_multiple_matches_is_na_never_silently_picks():
    s1 = _session(id='s1', metadata={'illumination': 'night'})
    s2 = _session(id='s2', metadata={'illumination': 'night'})
    candidates = [
        _candidate(session=s1, evaluation_result=_evaluation_result(session_id='s1')),
        _candidate(session=s2, evaluation_result=_evaluation_result(session_id='s2')),
    ]
    result = select_evidence(_requirement(), candidates)
    assert result.resolved is None
    assert any('ambiguous' in r and 's1' in r and 's2' in r for r in result.reasons)


def test_select_evidence_extra_condition_key_does_not_prevent_match():
    session = _session(metadata={'illumination': 'night', 'eyewear': 'glasses', 'smoke': True})
    result = select_evidence(_requirement(conditions={'illumination': 'night'}), [_candidate(session=session)])
    assert result.resolved is not None


# --- select_evidence: source ambiguity ----------------------------------

def test_select_evidence_multiple_sources_no_binding_is_na():
    candidate = _candidate(source_ids=['rgb_model', 'rgb_model_v2'])
    result = select_evidence(_requirement(), [candidate])
    assert result.resolved is None
    assert any('multiple prediction sources' in r for r in result.reasons)


def test_select_evidence_no_sources_is_na():
    candidate = _candidate(source_ids=[])
    result = select_evidence(_requirement(), [candidate])
    assert result.resolved is None
    assert any('no predictions found' in r for r in result.reasons)


# --- select_evidence: explicit binding ----------------------------------

def test_select_evidence_binding_resolves_regardless_of_ambiguity():
    s1 = _session(id='s1', metadata={'illumination': 'night'})
    s2 = _session(id='s2', metadata={'illumination': 'night'})
    candidates = [
        _candidate(session=s1, evaluation_result=_evaluation_result(session_id='s1')),
        _candidate(session=s2, evaluation_result=_evaluation_result(session_id='s2')),
    ]
    result = select_evidence(_requirement(), candidates, binding=EvidenceBinding(session_id='s2'))
    assert result.resolved is not None
    assert result.resolved.session.id == 's2'


def test_select_evidence_binding_skips_condition_matching_entirely():
    # The bound session's metadata doesn't match the requirement's
    # conditions at all - the binding is an override, not a tiebreak
    # within the auto-discovered set.
    session = _session(metadata={'illumination': 'day'})
    result = select_evidence(_requirement(), [_candidate(session=session)], binding=EvidenceBinding(session_id='s1'))
    assert result.resolved is not None


def test_select_evidence_binding_to_unknown_session_is_na():
    result = select_evidence(_requirement(), [_candidate()], binding=EvidenceBinding(session_id='does-not-exist'))
    assert result.resolved is None
    assert any('does-not-exist' in r for r in result.reasons)


def test_select_evidence_binding_with_explicit_source_resolves_ambiguity():
    candidate = _candidate(source_ids=['rgb_model', 'rgb_model_v2'])
    result = select_evidence(
        _requirement(), [candidate], binding=EvidenceBinding(session_id='s1', source_id='rgb_model_v2'),
    )
    assert result.resolved is not None
    assert result.resolved.source_id == 'rgb_model_v2'


def test_select_evidence_binding_with_unknown_source_is_na():
    candidate = _candidate(source_ids=['rgb_model'])
    result = select_evidence(
        _requirement(), [candidate], binding=EvidenceBinding(session_id='s1', source_id='does-not-exist'),
    )
    assert result.resolved is None
    assert any('not found' in r for r in result.reasons)


# --- task guard ----------------------------------------------------------

def test_select_evidence_rejects_candidate_with_mismatched_task():
    candidate = _candidate(evaluation_result=_evaluation_result(task='drowsiness'))
    with pytest.raises(ValueError, match='not requirement task'):
        select_evidence(_requirement(task='presence'), [candidate])


# --- discover_condition_values --------------------------------------------

def test_discover_condition_values_collects_observed_keys_and_values():
    sessions = [
        _session(id='s1', metadata={'illumination': 'night', 'eyewear': 'glasses'}),
        _session(id='s2', metadata={'illumination': 'day'}),
    ]
    values = discover_condition_values(sessions)
    assert values['illumination'] == {'night', 'day'}
    assert values['eyewear'] == {'glasses'}


def test_discover_condition_values_empty_for_no_sessions():
    assert discover_condition_values([]) == {}
