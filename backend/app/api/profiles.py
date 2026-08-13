"""Requirement profile API (v0.4, Phase 32 + Phase 36 addition; v0.5,
Phase 45 addition): create/list/get - no update, no delete. A profile is
immutable once persisted; a changed profile is a new id/version, never a
mutation of an existing row (see EvaluationProfile's docstring in
app/domain/profiles.py).

Validation happens once, at create time, in two layers: FastAPI/Pydantic
rejects structurally malformed input (unknown operator, empty acceptance
list, wrong types) before a ProfileCreateRequest can even exist; then
validate_profile (Phase 31) rejects cross-field problems (duplicate ids,
dangling references, cycles). Creation *is* the validation gate - there
is no separate /validate route, and no partial acceptance: either both
layers pass and the profile is persisted, or nothing is.

POST .../coverage (added while building Phase 36's frontend, which needs
a real endpoint to call - no phase's issue explicitly scoped it, flagged
and folded in here rather than left for Phase 37 to discover missing)
is the one derivation route, collapsing "evaluate" and "coverage" into a
single call per the architecture review's Q19 - fetches already-persisted
sessions/evaluation-results/source-ids and calls Phase 35's
compute_requirement_results + compute_configuration_coverage. Never
persists its result (see coverage.py's module docstring).

GET .../facets and POST .../analysis (v0.5, Phase 45) expose Phase 43/44's
filtering/aggregation engine. /analysis reuses the exact same evidence-
gathering helpers /coverage uses (_resolve_sessions/_resolve_configuration_ids/
_compute_requirement_results_by_configuration, extracted this phase so
neither route duplicates the other's logic) - v0.5 never re-decides
PASS/FAIL/N/A, it only filters/groups what Phase 34 already decided.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.domain.analysis import (
    AggregateCoverage,
    AnalysisFilter,
    aggregate_requirement_results,
    cross_tabulate,
    discover_facets,
    failure_breakdown,
    filter_requirement_results,
    group_by_condition,
    na_breakdown,
)
from app.domain.coverage import (
    ConfigurationCoverage,
    GroupCoverage,
    RequirementResult,
    RequirementStatus,
    compute_configuration_coverage,
    compute_requirement_results,
)
from app.domain.evidence import EvidenceBinding, SessionCandidate
from app.domain.models import Session
from app.domain.profiles import ConditionValue, EvaluationProfile, Requirement, RequirementGroup, validate_profile
from app.persistence import repository as repo

router = APIRouter(prefix='/api/profiles', tags=['profiles'])


def _require_profile(conn: sqlite3.Connection, profile_id: str) -> EvaluationProfile:
    profile = repo.get_profile(conn, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile '{profile_id}' not found")
    return profile


def _resolve_sessions(conn: sqlite3.Connection, session_ids: list[str] | None) -> list[Session]:
    if session_ids is None:
        return repo.list_sessions(conn)
    sessions = []
    for session_id in session_ids:
        session = repo.get_session(conn, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"session '{session_id}' not found")
        sessions.append(session)
    return sessions


def _resolve_configuration_ids(
    conn: sqlite3.Connection, sessions: list[Session], tasks: list[str], configuration_ids: list[str] | None,
) -> list[str]:
    if configuration_ids is not None:
        return configuration_ids
    return sorted({
        cfg_id
        for session in sessions
        for task in tasks
        for cfg_id in repo.list_configuration_ids(conn, session.id, task)
    })


def _compute_requirement_results_by_configuration(
    conn: sqlite3.Connection,
    profile: EvaluationProfile,
    sessions: list[Session],
    tasks: list[str],
    configuration_ids: list[str],
    bindings: dict[str, EvidenceBinding],
) -> dict[str, list[RequirementResult]]:
    """Shared by /coverage and /analysis - the same evidence-gathering
    pass (candidate sessions per task, per configuration) either route
    would otherwise duplicate."""
    results_by_configuration: dict[str, list[RequirementResult]] = {}
    for configuration_id in configuration_ids:
        # Rebuilt per configuration_id, not shared across configurations -
        # an EvaluationResult (and therefore a SessionCandidate) is always
        # scoped to one specific configuration_id.
        candidates_by_task: dict[str, list[SessionCandidate]] = {}
        for task in tasks:
            candidates = []
            for session in sessions:
                evaluation_result = repo.get_evaluation_result(conn, session.id, configuration_id, task)
                if evaluation_result is None:
                    continue
                source_ids = repo.list_distinct_source_ids(conn, session.id, configuration_id, task)
                candidates.append(SessionCandidate(
                    session=session, evaluation_result=evaluation_result, source_ids=source_ids,
                ))
            candidates_by_task[task] = candidates
        results_by_configuration[configuration_id] = compute_requirement_results(
            profile, configuration_id, candidates_by_task, bindings,
        )
    return results_by_configuration


class ProfileCreateRequest(BaseModel):
    id: str
    name: str
    version: str
    description: str = ''
    format_version: str = '1.0'
    groups: list[RequirementGroup]
    requirements: list[Requirement]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileSummary(BaseModel):
    id: str
    name: str
    version: str
    description: str
    requirement_count: int
    # Carried through so the list page can show a SYNTHETIC DATA badge
    # without fetching every full profile document - same convention as
    # Scenario/Session, whose metadata is likewise exposed at list level.
    metadata: dict[str, Any]
    created_at: datetime


def _to_summary(profile: EvaluationProfile) -> ProfileSummary:
    return ProfileSummary(
        id=profile.id, name=profile.name, version=profile.version,
        description=profile.description, requirement_count=len(profile.requirements),
        metadata=profile.metadata, created_at=profile.created_at,
    )


@router.post('', status_code=201)
def create_profile(body: ProfileCreateRequest, conn: sqlite3.Connection = Depends(get_db)) -> EvaluationProfile:
    # created_at is server-assigned, same convention as Session.started_at
    # - a profile document has no natural "created_at" of its own until
    # the server actually persists it.
    profile = EvaluationProfile(**body.model_dump(), created_at=datetime.now(timezone.utc))

    errors = validate_profile(profile)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    if repo.get_profile(conn, profile.id) is not None:
        raise HTTPException(status_code=409, detail=f"profile '{profile.id}' already exists")

    repo.create_profile(conn, profile)
    return profile


@router.get('')
def list_profiles(conn: sqlite3.Connection = Depends(get_db)) -> list[ProfileSummary]:
    return [_to_summary(p) for p in repo.list_profiles(conn)]


@router.get('/{profile_id}')
def get_profile(profile_id: str, conn: sqlite3.Connection = Depends(get_db)) -> EvaluationProfile:
    return _require_profile(conn, profile_id)


class RequirementBindingRequest(BaseModel):
    session_id: str
    source_id: str | None = None


class CoverageRequest(BaseModel):
    # None means "every configuration with at least one evaluated result
    # for any of this profile's tasks" - discovered, not enumerated,
    # unless the caller overrides - same convention as /compare's
    # candidate_configuration_ids.
    configuration_ids: list[str] | None = None
    # None means "search every session" - still gated by condition
    # matching and the ambiguity rule, so this is less dangerous than it
    # sounds (see app/domain/evidence.py).
    session_ids: list[str] | None = None
    # Keyed by requirement id, request-scoped only - never persisted (see
    # EvidenceBinding's docstring for why).
    requirement_bindings: dict[str, RequirementBindingRequest] = Field(default_factory=dict)


class CoverageResponse(BaseModel):
    configuration_coverages: list[ConfigurationCoverage]


@router.post('/{profile_id}/coverage')
def compute_profile_coverage(
    profile_id: str, body: CoverageRequest, conn: sqlite3.Connection = Depends(get_db),
) -> CoverageResponse:
    profile = _require_profile(conn, profile_id)
    sessions = _resolve_sessions(conn, body.session_ids)
    tasks = sorted({r.task for r in profile.requirements})
    configuration_ids = _resolve_configuration_ids(conn, sessions, tasks, body.configuration_ids)
    bindings = {
        requirement_id: EvidenceBinding(session_id=b.session_id, source_id=b.source_id)
        for requirement_id, b in body.requirement_bindings.items()
    }
    results_by_configuration = _compute_requirement_results_by_configuration(
        conn, profile, sessions, tasks, configuration_ids, bindings,
    )

    configuration_coverages = [
        compute_configuration_coverage(profile, configuration_id, results)
        for configuration_id, results in results_by_configuration.items()
    ]
    return CoverageResponse(configuration_coverages=configuration_coverages)


# --- condition analysis (v0.5, Phase 45) -----------------------------------

class FacetValueResponse(BaseModel):
    value: ConditionValue
    requirement_count: int


class FacetResponse(BaseModel):
    key: str
    values: list[FacetValueResponse]


@router.get('/{profile_id}/facets')
def get_profile_facets(profile_id: str, conn: sqlite3.Connection = Depends(get_db)) -> list[FacetResponse]:
    """From profile.requirements only - no evidence/RequirementResult
    computation, so this is always cheap regardless of whether anything
    has been evaluated yet."""
    profile = _require_profile(conn, profile_id)
    return [
        FacetResponse(
            key=facet.key,
            values=[FacetValueResponse(value=v.value, requirement_count=v.requirement_count) for v in facet.values],
        )
        for facet in discover_facets(profile)
    ]


class AnalysisFilterRequest(BaseModel):
    conditions: dict[str, ConditionValue] = Field(default_factory=dict)
    group_id: str | None = None
    task: str | None = None
    status: RequirementStatus | None = None


class AnalysisRequest(BaseModel):
    configuration_ids: list[str] | None = None
    session_ids: list[str] | None = None
    requirement_bindings: dict[str, RequirementBindingRequest] = Field(default_factory=dict)
    filters: AnalysisFilterRequest = Field(default_factory=AnalysisFilterRequest)
    # 0 dims = filtered summary only, 1 = per-condition breakdown, 2 =
    # cross-tab - one endpoint, not three separate routes.
    group_by: list[str] = Field(default_factory=list)


class AggregateResponse(BaseModel):
    pass_count: int
    fail_count: int
    na_count: int
    requirement_coverage: float | None
    evidence_completeness: float | None


def _to_aggregate_response(agg: AggregateCoverage) -> AggregateResponse:
    return AggregateResponse(
        pass_count=agg.pass_count, fail_count=agg.fail_count, na_count=agg.na_count,
        requirement_coverage=agg.requirement_coverage, evidence_completeness=agg.evidence_completeness,
    )


class GroupCell(BaseModel):
    # Length matches len(group_by): one value for a 1D breakdown, two
    # (row, col) for a 2D cross-tab.
    key: list[ConditionValue]
    aggregate: AggregateResponse


class ConfigurationAnalysis(BaseModel):
    configuration_id: str
    # Over the filtered population, independent of group_by - always
    # present so a UI can render the configuration summary table without
    # needing group_by at all.
    summary: AggregateResponse
    groups: list[GroupCell] = Field(default_factory=list)
    # The filtered results themselves - so a failure/N/A list can render
    # directly from this one response, no second round trip.
    requirement_results: list[RequirementResult]
    # Same group tree compute_configuration_coverage builds (Phase 44's
    # aggregate_group_tree, reused via failure_breakdown), over the
    # filtered population - the Failures tab's top-failing-groups list
    # (Phase 48) flattens/sorts this client-side rather than a second
    # API field, since that ordering carries no domain logic of its own.
    failure_root: GroupCoverage
    # classify_na_reason counts (Phase 44/48) - real backend classification,
    # never reimplemented client-side, so the UI can never silently drift
    # from evidence.py/coverage.py's actual reason strings.
    na_breakdown: dict[str, int]


class AnalysisResponse(BaseModel):
    configurations: list[ConfigurationAnalysis]


@router.post('/{profile_id}/analysis')
def analyze_profile(
    profile_id: str, body: AnalysisRequest, conn: sqlite3.Connection = Depends(get_db),
) -> AnalysisResponse:
    profile = _require_profile(conn, profile_id)
    if len(body.group_by) > 2:
        raise HTTPException(status_code=422, detail='group_by supports at most 2 dimensions')

    sessions = _resolve_sessions(conn, body.session_ids)
    tasks = sorted({r.task for r in profile.requirements})
    configuration_ids = _resolve_configuration_ids(conn, sessions, tasks, body.configuration_ids)
    bindings = {
        requirement_id: EvidenceBinding(session_id=b.session_id, source_id=b.source_id)
        for requirement_id, b in body.requirement_bindings.items()
    }
    results_by_configuration = _compute_requirement_results_by_configuration(
        conn, profile, sessions, tasks, configuration_ids, bindings,
    )

    criteria = AnalysisFilter(
        conditions=body.filters.conditions, group_id=body.filters.group_id,
        task=body.filters.task, status=body.filters.status,
    )
    requirement_by_id = {r.id: r for r in profile.requirements}

    configurations = []
    for configuration_id, results in results_by_configuration.items():
        filtered = filter_requirement_results(profile, results, criteria)
        summary = aggregate_requirement_results(filtered)

        groups: list[GroupCell] = []
        if len(body.group_by) == 1:
            buckets = group_by_condition(filtered, requirement_by_id, body.group_by[0])
            groups = [
                GroupCell(key=[value], aggregate=_to_aggregate_response(agg))
                for value, agg in buckets.items()
            ]
        elif len(body.group_by) == 2:
            cells = cross_tabulate(filtered, requirement_by_id, body.group_by[0], body.group_by[1])
            groups = [
                GroupCell(key=[row, col], aggregate=_to_aggregate_response(agg))
                for (row, col), agg in cells.items()
            ]

        configurations.append(ConfigurationAnalysis(
            configuration_id=configuration_id,
            summary=_to_aggregate_response(summary),
            groups=groups,
            requirement_results=filtered,
            failure_root=failure_breakdown(profile, filtered),
            na_breakdown=na_breakdown(filtered),
        ))

    return AnalysisResponse(configurations=configurations)
