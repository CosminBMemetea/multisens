"""Evidence selection (v0.4, Phase 33) - the hardest v0.4 architectural
problem per the master prompt: given a requirement (task + conditions)
and a target configuration, deterministically decide which single
already-evaluated session/source is "the evidence," or explain why none
can be chosen.

Pure function - no sqlite3/fastapi import, same discipline as
matching.py/comparison.py. The API/coverage-engine layer fetches
candidate sessions plus their evaluation-result and source-id facts (see
SessionCandidate) and hands them here; this module only decides.

Never guesses. Ambiguity - multiple matching sessions, or multiple
prediction sources within the one matching session - is always N/A with
a reason, unless an explicit EvidenceBinding names exactly which
session/source to use. This is the single most important invariant
carried over from v0.3's `/compare` source-ambiguity rule
(app/api/comparison.py's _resolve_source_id) - reused here, not
reinvented.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import EvaluationResult, Session
from app.domain.profiles import ConditionValue, Requirement


def values_match(evidence_value: object, condition_value: ConditionValue) -> bool:
    """Exact, type-sensitive equality - no coercion, no fuzzy matching.
    Python's `1 == True` and `1.0 == True` are both True (bool is an int
    subclass), which would silently let a numeric condition match a
    boolean one or vice versa - exactly the kind of accidental match the
    v0.4 architecture review's matching rule forbids. Ordinary int/float
    equality (3 == 3.0) is still allowed - that's a JSON round-trip
    detail, not a type mismatch."""
    if isinstance(evidence_value, bool) != isinstance(condition_value, bool):
        return False
    return evidence_value == condition_value


def conditions_are_subset(subset: dict[str, ConditionValue], superset: dict[str, object]) -> bool:
    """Generic form of the matching rule matches_conditions applies to a
    specific Session below: every key in `subset` must be present in
    `superset` with an equal, type-sensitive value (see values_match).
    Extra keys in `superset` are ignored - that's what lets one superset
    satisfy multiple requirement/filter condition maps that only care
    about part of it. A missing key is not a partial match; it's simply
    not a match. An empty `subset` always matches (the vacuous case).

    Reused by matches_conditions (subset=requirement.conditions,
    superset=session.metadata, v0.4's evidence selection) and by v0.5's
    filter_requirement_ids (subset=filter.conditions,
    superset=requirement.conditions, app/domain/analysis.py) - the exact
    same rule applied one layer up, not reimplemented a second time."""
    _missing = object()
    return all(
        values_match(superset.get(key, _missing), value)
        for key, value in subset.items()
    )


def matches_conditions(session: Session, conditions: dict[str, ConditionValue]) -> bool:
    """A requirement's condition map matches a session iff every key in
    `conditions` is present in `session.metadata` with an equal value.
    See conditions_are_subset for the full rule."""
    return conditions_are_subset(conditions, session.metadata)


@dataclass
class SessionCandidate:
    """One session's already-fetched relevant facts for a specific
    (configuration_id, task) pair - everything select_evidence needs to
    judge whether this session is usable evidence, without itself
    touching a database. Only sessions that already have a persisted
    EvaluationResult for this configuration/task should ever become a
    SessionCandidate - a session with no evaluation is not "not evidence
    yet," it's simply not a candidate at all."""
    session: Session
    evaluation_result: EvaluationResult
    # Distinct source_ids with predictions for this configuration_id/task
    # in this session - mirrors what repo.list_distinct_source_ids (v0.3)
    # already computes for the identical ambiguity check in /compare.
    source_ids: list[str]


@dataclass
class EvidenceBinding:
    """A caller-supplied override that names exactly which evidence to
    use for one requirement, bypassing discovery (and condition matching)
    entirely - the only mechanism that lets a profile with genuinely
    ambiguous auto-discovery ever resolve to something other than N/A.
    Request-scoped only; never persisted (see the v0.4 architecture
    review's decision on why)."""
    session_id: str
    source_id: str | None = None


@dataclass
class ResolvedEvidence:
    session: Session
    source_id: str
    evaluation_result: EvaluationResult


@dataclass
class EvidenceSelection:
    """Exactly one of `resolved` or a non-empty `reasons` list - enforced
    by construction in every code path below (this is a plain dataclass,
    not a Pydantic model, so - unlike ComparisonValidity/RequirementResult
    - there is no runtime validator; the invariant is guaranteed by
    select_evidence's own control flow and proven by tests, not the type
    system)."""
    resolved: ResolvedEvidence | None
    reasons: list[str] = field(default_factory=list)


def select_evidence(
    requirement: Requirement,
    candidates: list[SessionCandidate],
    binding: EvidenceBinding | None = None,
) -> EvidenceSelection:
    for candidate in candidates:
        if candidate.evaluation_result.task != requirement.task:
            raise ValueError(
                f"candidate session '{candidate.session.id}' has an evaluation result for task "
                f"'{candidate.evaluation_result.task}', not requirement task '{requirement.task}' - "
                f"caller must only pass candidates already scoped to the requirement's task"
            )

    if binding is not None:
        return _resolve_binding(candidates, binding)
    return _discover(requirement, candidates)


def _resolve_binding(candidates: list[SessionCandidate], binding: EvidenceBinding) -> EvidenceSelection:
    match = next((c for c in candidates if c.session.id == binding.session_id), None)
    if match is None:
        return EvidenceSelection(resolved=None, reasons=[
            f"bound session '{binding.session_id}' has no evaluated result for this configuration/task"
        ])
    # A binding overrides discovery entirely, including condition
    # matching - it says exactly which evidence to use, full stop. Only
    # prediction-source ambiguity within that named session still needs
    # resolving (or is itself resolved by binding.source_id).
    return _resolve_source(match, binding.source_id)


def _discover(requirement: Requirement, candidates: list[SessionCandidate]) -> EvidenceSelection:
    matching = [c for c in candidates if matches_conditions(c.session, requirement.conditions)]
    if not matching:
        return EvidenceSelection(resolved=None, reasons=[
            f"no session matches conditions {requirement.conditions} for task '{requirement.task}'"
        ])
    if len(matching) > 1:
        session_ids = sorted(c.session.id for c in matching)
        return EvidenceSelection(resolved=None, reasons=[
            f'{len(matching)} sessions match conditions {requirement.conditions} - ambiguous, '
            f'provide an explicit binding: {session_ids}'
        ])
    return _resolve_source(matching[0], requested_source_id=None)


def _resolve_source(candidate: SessionCandidate, requested_source_id: str | None) -> EvidenceSelection:
    available = candidate.source_ids
    if requested_source_id is not None:
        if requested_source_id not in available:
            return EvidenceSelection(resolved=None, reasons=[
                f"source_id '{requested_source_id}' not found for session '{candidate.session.id}' - "
                f"available: {available}"
            ])
        source_id = requested_source_id
    elif len(available) == 1:
        source_id = available[0]
    elif not available:
        return EvidenceSelection(resolved=None, reasons=[
            f"no predictions found for session '{candidate.session.id}' for this configuration/task"
        ])
    else:
        return EvidenceSelection(resolved=None, reasons=[
            f"session '{candidate.session.id}' has multiple prediction sources: {available} - "
            f"specify which one explicitly via a binding"
        ])

    return EvidenceSelection(resolved=ResolvedEvidence(
        session=candidate.session, source_id=source_id, evaluation_result=candidate.evaluation_result,
    ))


def discover_condition_values(sessions: list[Session]) -> dict[str, set[ConditionValue]]:
    """Read-only aid for authoring/debugging requirement condition maps
    against real data - what condition key -> observed values exist
    across a set of sessions' metadata. Not used by select_evidence
    itself; flagged as a missing capability in the v0.4 architecture
    review (issue #31, Q3) so profile authors aren't left guessing what
    values sessions actually carry. Not exhaustively type-safe against
    the bool/int collision values_match guards against (a Python set
    conflates True and 1) - acceptable for a debugging aid, unlike
    select_evidence's actual matching decisions."""
    values: dict[str, set[ConditionValue]] = {}
    for session in sessions:
        for key, value in session.metadata.items():
            if isinstance(value, (str, float, int, bool)):
                values.setdefault(key, set()).add(value)
    return values
