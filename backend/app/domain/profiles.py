"""Requirement profile domain model (v0.4, Phase 30).

Transport/storage-agnostic like models.py and comparison.py: no fastapi,
sqlite3, or rclpy import. Defines the *shape* of a profile document, not
how it's validated (Phase 31), matched to evidence (Phase 33), evaluated
(Phase 34), or aggregated (Phase 35).

Conditions are a flat, open dict[str, str | float | bool] - never a fixed
set of columns (illumination/eyewear/smoke/...). A private profile can
introduce any new condition dimension (weather, vibration, ...) without a
core code change - this is a non-negotiable v0.4 requirement, not a
convenience. See docs/profiles.md once Phase 41 writes it.

No `mandatory` or `weight` field on Requirement/RequirementGroup: neither
has an aggregation semantic defined in v0.4 (see the architecture review
on issue #31) - an unused field would only invite premature use before
that semantic exists. Adding either later is an additive migration, not
a breaking one.

`EvaluationProfile` is immutable by convention, not merely by omission:
there is deliberately no update endpoint (Phase 32) - a changed profile
is a new id/version, never a mutation of an existing one, so every
RequirementResult stays reproducible against the exact
profile_id/profile_version that produced it.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AcceptanceOperator = Literal['>=', '<=', '>', '<', '==']

# A condition value is a single flat scalar - never nested - so the
# subset-matching rule (Phase 33) stays a total, unambiguous equality
# check per key, never a fuzzy or recursive one.
ConditionValue = str | float | bool


class AcceptanceCriterion(BaseModel):
    metric: str
    operator: AcceptanceOperator
    value: float


class Requirement(BaseModel):
    id: str
    # Every requirement belongs to a real group - no loose top-level
    # requirements - so profile-level aggregation (Phase 35) is always a
    # clean sum over groups, never a mixed sum over groups and stragglers.
    # Cross-referential validity (does this group_id actually exist) is
    # Phase 31's job, not this model's.
    group_id: str
    name: str
    description: str = ''
    task: str
    conditions: dict[str, ConditionValue] = Field(default_factory=dict)
    acceptance: list[AcceptanceCriterion]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator('acceptance')
    @classmethod
    def _acceptance_non_empty(cls, v: list[AcceptanceCriterion]) -> list[AcceptanceCriterion]:
        if not v:
            raise ValueError(
                'acceptance must not be empty - a requirement with no criteria can never be evaluated'
            )
        return v


class RequirementGroup(BaseModel):
    id: str
    parent_id: str | None = None  # None = top-level group
    name: str
    description: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationProfile(BaseModel):
    id: str
    name: str
    version: str
    description: str = ''
    format_version: str = '1.0'
    groups: list[RequirementGroup]
    requirements: list[Requirement]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


def validate_profile(profile: EvaluationProfile) -> list[str]:
    """Collects every structural/semantic error in a profile, never stops
    at the first one - "do not partially accept a malformed profile"
    means a caller sees everything wrong in one round trip, not a
    fix-and-resubmit loop. Empty list means valid.

    Deliberately separate from Pydantic's own field-level validation
    (AcceptanceCriterion's operator Literal, Requirement's non-empty
    acceptance list, ...) - those already reject malformed input at
    parse time, before an EvaluationProfile instance can even exist.
    This function only checks what parsing alone cannot: relationships
    *between* fields - duplicate ids, dangling references, cycles.
    """
    errors: list[str] = []

    group_ids = [g.id for g in profile.groups]
    group_id_set = set(group_ids)
    for gid in sorted({g for g in group_ids if group_ids.count(g) > 1}):
        errors.append(f"duplicate group id '{gid}'")

    requirement_ids = [r.id for r in profile.requirements]
    for rid in sorted({r for r in requirement_ids if requirement_ids.count(r) > 1}):
        errors.append(f"duplicate requirement id '{rid}'")

    groups_by_id = {g.id: g for g in profile.groups}
    for group in profile.groups:
        if group.parent_id is not None and group.parent_id not in group_id_set:
            errors.append(f"group '{group.id}' references unknown parent group '{group.parent_id}'")

    # Cycle detection: walk each group's ancestor chain toward the root
    # (parent_id points up the tree). A well-formed chain terminates at
    # None within len(groups) hops; revisiting a node first means a
    # cycle (a self-loop is a 1-hop cycle). A dangling parent reference
    # (already reported above) is treated as a dead end here, not a
    # second error for the same problem.
    for group in profile.groups:
        visited: set[str] = set()
        current: str | None = group.id
        for _ in range(len(profile.groups) + 1):
            if current is None:
                break
            if current in visited:
                errors.append(f"group '{group.id}' is part of a parent-group cycle")
                break
            visited.add(current)
            parent = groups_by_id.get(current)
            current = parent.parent_id if parent is not None else None

    for requirement in profile.requirements:
        if requirement.group_id not in group_id_set:
            errors.append(f"requirement '{requirement.id}' references unknown group '{requirement.group_id}'")
        if not requirement.task.strip():
            errors.append(f"requirement '{requirement.id}' has no task")
        for criterion in requirement.acceptance:
            if not criterion.metric.strip():
                errors.append(f"requirement '{requirement.id}' has a criterion with no metric name")
            if not math.isfinite(criterion.value):
                errors.append(
                    f"requirement '{requirement.id}' criterion '{criterion.metric}' has a "
                    f"non-finite threshold ({criterion.value!r})"
                )

    if not profile.requirements:
        errors.append('profile has no requirements')

    return errors
