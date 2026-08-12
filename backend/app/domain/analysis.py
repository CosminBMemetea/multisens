"""Condition analysis domain model (v0.5, Phase 42).

Transport/storage-agnostic like every other domain module - no fastapi,
sqlite3, or rclpy import. Defines the *shape* of a filter/facet, not how
requirements are discovered/filtered (Phase 43), aggregated/grouped
(Phase 44), or exposed over HTTP (Phase 45).

Filtering is over Requirement.conditions (the profile's own declared
conditions), never over a resolved evidence session's Session.metadata.
The two coincide whenever evidence resolves cleanly - v0.4's evidence
selection already guarantees any resolved session's metadata is a
superset of the requirement's own conditions (see evidence.py's
matches_conditions) - but the *mechanism* here is requirement-
conditions-based: facet discovery and filtering never need to look at
evidence or RequirementResult at all, only at the profile document
itself (see the v0.5 architecture review, issue #43, Q3/Q6).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.coverage import RequirementStatus
from app.domain.profiles import ConditionValue


@dataclass
class AnalysisFilter:
    """Every field is an independent AND-ed predicate - a requirement
    must satisfy all of them to be included in a filtered population.
    Deliberately flat and structured, not a query language: no operator
    tree, no free-text query string (the v0.5 architecture review
    explicitly rejects a generic query DSL)."""
    conditions: dict[str, ConditionValue] = field(default_factory=dict)
    # This group OR any of its descendants - not just an exact group_id
    # match. Walking the tree to resolve "descendants" is Phase 43's job;
    # this field only names the starting point.
    group_id: str | None = None
    task: str | None = None
    status: RequirementStatus | None = None


@dataclass
class FacetValue:
    value: ConditionValue
    # How many requirements in the profile declare this exact key/value
    # pair - lets a UI show "night (38)" rather than a bare value with
    # no sense of how much evidence-worth of requirements it represents.
    requirement_count: int


@dataclass
class Facet:
    """One discovered condition dimension. `key` is whatever a profile
    author happened to name it (illumination, weather, vibration, ...) -
    never a fixed enum of known keys. Discovered fresh from whatever a
    given profile's requirements actually declare (Phase 43), so a
    profile with a condition dimension this module has never seen before
    works with zero code changes here."""
    key: str
    values: list[FacetValue]
