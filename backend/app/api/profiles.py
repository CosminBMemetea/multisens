"""Requirement profile API (v0.4, Phase 32): create/list/get only - no
update, no delete. A profile is immutable once persisted; a changed
profile is a new id/version, never a mutation of an existing row (see
EvaluationProfile's docstring in app/domain/profiles.py).

Validation happens once, at create time, in two layers: FastAPI/Pydantic
rejects structurally malformed input (unknown operator, empty acceptance
list, wrong types) before a ProfileCreateRequest can even exist; then
validate_profile (Phase 31) rejects cross-field problems (duplicate ids,
dangling references, cycles). Creation *is* the validation gate - there
is no separate /validate route, and no partial acceptance: either both
layers pass and the profile is persisted, or nothing is.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.domain.profiles import EvaluationProfile, Requirement, RequirementGroup, validate_profile
from app.persistence import repository as repo

router = APIRouter(prefix='/api/profiles', tags=['profiles'])


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
    created_at: datetime


def _to_summary(profile: EvaluationProfile) -> ProfileSummary:
    return ProfileSummary(
        id=profile.id, name=profile.name, version=profile.version,
        description=profile.description, requirement_count=len(profile.requirements),
        created_at=profile.created_at,
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
    profile = repo.get_profile(conn, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile '{profile_id}' not found")
    return profile
