"""Requirement profile API (v0.4, Phase 32 + Phase 36 addition):
create/list/get - no update, no delete. A profile is immutable once
persisted; a changed profile is a new id/version, never a mutation of an
existing row (see EvaluationProfile's docstring in app/domain/profiles.py).

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
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.domain.coverage import ConfigurationCoverage, compute_configuration_coverage, compute_requirement_results
from app.domain.evidence import EvidenceBinding, SessionCandidate
from app.domain.profiles import EvaluationProfile, Requirement, RequirementGroup, validate_profile
from app.persistence import repository as repo

router = APIRouter(prefix='/api/profiles', tags=['profiles'])


def _require_profile(conn: sqlite3.Connection, profile_id: str) -> EvaluationProfile:
    profile = repo.get_profile(conn, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile '{profile_id}' not found")
    return profile


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

    if body.session_ids is None:
        sessions = repo.list_sessions(conn)
    else:
        sessions = []
        for session_id in body.session_ids:
            session = repo.get_session(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail=f"session '{session_id}' not found")
            sessions.append(session)

    tasks = sorted({r.task for r in profile.requirements})

    if body.configuration_ids is None:
        configuration_ids = sorted({
            cfg_id
            for session in sessions
            for task in tasks
            for cfg_id in repo.list_configuration_ids(conn, session.id, task)
        })
    else:
        configuration_ids = body.configuration_ids

    bindings = {
        requirement_id: EvidenceBinding(session_id=b.session_id, source_id=b.source_id)
        for requirement_id, b in body.requirement_bindings.items()
    }

    configuration_coverages = []
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

        results = compute_requirement_results(profile, configuration_id, candidates_by_task, bindings)
        configuration_coverages.append(compute_configuration_coverage(profile, configuration_id, results))

    return CoverageResponse(configuration_coverages=configuration_coverages)
