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

from app.domain.coverage import (
    GroupCoverage,
    RequirementResult,
    RequirementStatus,
    aggregate_group_tree,
    coverage_and_completeness,
    status_counts,
)
from app.domain.evidence import conditions_are_subset
from app.domain.models import MetricValue
from app.domain.profiles import ConditionValue, EvaluationProfile, Requirement


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


# --- facet discovery + filtering engine (v0.5, Phase 43) -------------------
#
# Pure functions - no sqlite3/fastapi import. Consume an already-fetched
# EvaluationProfile and (for filter_results) an already-computed
# list[RequirementResult] - v0.5 analyzes results, it never re-decides
# PASS/FAIL/N/A itself (that stays Phase 34's job).

def discover_facets(profile: EvaluationProfile) -> list[Facet]:
    """One pass over profile.requirements[*].conditions - no evidence or
    RequirementResult needed at all, so this is always cheap and never
    depends on anything having been evaluated yet."""
    counts: dict[str, dict[ConditionValue, int]] = {}
    for requirement in profile.requirements:
        for key, value in requirement.conditions.items():
            per_value = counts.setdefault(key, {})
            # dict keys use Python equality/hash, so True and 1 would
            # collide as dict keys the same way they collide in a set
            # (see evidence.py's discover_condition_values) - acceptable
            # here since this is a discovery/display aid, not a matching
            # decision (those go through conditions_are_subset, which
            # does guard against exactly this collision).
            per_value[value] = per_value.get(value, 0) + 1

    return [
        Facet(
            key=key,
            values=[
                FacetValue(value=value, requirement_count=count)
                for value, count in sorted(per_value.items(), key=lambda item: str(item[0]))
            ],
        )
        for key, per_value in sorted(counts.items())
    ]


def _descendant_group_ids(profile: EvaluationProfile, group_id: str) -> set[str]:
    """`group_id` plus every descendant, walked via the same parent_id
    adjacency list compute_configuration_coverage (Phase 35) already
    builds for its own tree - not re-derived from a different structure."""
    children_by_parent: dict[str | None, list[str]] = {}
    for group in profile.groups:
        children_by_parent.setdefault(group.parent_id, []).append(group.id)

    collected = {group_id}
    frontier = [group_id]
    while frontier:
        current = frontier.pop()
        for child_id in children_by_parent.get(current, []):
            if child_id not in collected:
                collected.add(child_id)
                frontier.append(child_id)
    return collected


def filter_requirement_ids(profile: EvaluationProfile, criteria: AnalysisFilter) -> set[str]:
    """Requirement-level predicates only (conditions/group/task) - never
    status, which requires a RequirementResult (see filter_results).
    A requirement missing a filtered condition key is excluded, never
    treated as a wildcard or a false match - conditions_are_subset
    already enforces this (the same rule v0.4's evidence selection uses,
    reused here rather than reimplemented)."""
    eligible_group_ids = (
        _descendant_group_ids(profile, criteria.group_id) if criteria.group_id is not None else None
    )

    matching: set[str] = set()
    for requirement in profile.requirements:
        if not conditions_are_subset(criteria.conditions, requirement.conditions):
            continue
        if eligible_group_ids is not None and requirement.group_id not in eligible_group_ids:
            continue
        if criteria.task is not None and requirement.task != criteria.task:
            continue
        matching.add(requirement.id)
    return matching


def filter_results(
    results: list[RequirementResult],
    requirement_ids: set[str],
    status: RequirementStatus | None = None,
) -> list[RequirementResult]:
    """Intersects an already-computed RequirementResult list against a
    requirement-id set (from filter_requirement_ids) plus an optional
    status filter - the one predicate that genuinely needs a computed
    result, not just the profile document."""
    return [
        result for result in results
        if result.requirement_id in requirement_ids and (status is None or result.status == status)
    ]


def filter_requirement_results(
    profile: EvaluationProfile,
    results: list[RequirementResult],
    criteria: AnalysisFilter,
) -> list[RequirementResult]:
    """Convenience composition of filter_requirement_ids + filter_results
    - the shape Phase 44/45 will actually call most often."""
    requirement_ids = filter_requirement_ids(profile, criteria)
    return filter_results(results, requirement_ids, criteria.status)


# --- aggregation + grouping (v0.5, Phase 44) --------------------------------
#
# Pure functions over an arbitrary (already filtered, if the caller
# wants) list[RequirementResult]. Never re-decides PASS/FAIL/N/A - only
# tallies and buckets what Phase 34 already decided.

@dataclass
class AggregateCoverage:
    """A flat (non-hierarchical) P/F/N tally plus the same two coverage
    formulas GroupCoverage uses - the shape a filtered summary, a
    group_by_condition bucket, or a cross_tabulate cell all reduce to.
    Both percentages always travel together, same as GroupCoverage -
    never one without the other."""
    pass_count: int
    fail_count: int
    na_count: int
    requirement_coverage: MetricValue
    evidence_completeness: MetricValue

    @property
    def total(self) -> int:
        return self.pass_count + self.fail_count + self.na_count


def aggregate_requirement_results(results: list[RequirementResult]) -> AggregateCoverage:
    """The one place v0.5 computes P/F/N + both coverage numbers - reuses
    coverage.py's exact status_counts/coverage_and_completeness rather
    than a second formula, so a filtered summary can never silently
    disagree with v0.4's own arithmetic."""
    pass_count, fail_count, na_count = status_counts(results)
    coverage, completeness = coverage_and_completeness(pass_count, fail_count, na_count)
    return AggregateCoverage(pass_count, fail_count, na_count, coverage, completeness)


def group_by_condition(
    results: list[RequirementResult],
    requirement_by_id: dict[str, Requirement],
    key: str,
) -> dict[ConditionValue, AggregateCoverage]:
    """Buckets results by the observed value of one condition dimension.
    A result whose requirement lacks `key` entirely is excluded from the
    breakdown - never lumped into an "unknown"/"other" bucket, which
    would misrepresent "this condition was never declared" as if it were
    an observed value in its own right."""
    _missing = object()
    buckets: dict[ConditionValue, list[RequirementResult]] = {}
    for result in results:
        requirement = requirement_by_id.get(result.requirement_id)
        if requirement is None:
            continue
        value = requirement.conditions.get(key, _missing)
        if value is _missing:
            continue
        buckets.setdefault(value, []).append(result)
    return {value: aggregate_requirement_results(rs) for value, rs in buckets.items()}


def cross_tabulate(
    results: list[RequirementResult],
    requirement_by_id: dict[str, Requirement],
    row_key: str,
    col_key: str,
) -> dict[tuple[ConditionValue, ConditionValue], AggregateCoverage]:
    """Two-dimensional version of group_by_condition - a result needs
    BOTH condition keys present to land in any cell; missing either
    excludes it from the whole cross-tab, not just one axis. The
    configuration x condition "heatmap" case (Phase 47) is not a special
    case of this function - it's group_by_condition called once per
    configuration's own result set, reusing the 1D primitive rather than
    inventing a second axis type here."""
    _missing = object()
    buckets: dict[tuple[ConditionValue, ConditionValue], list[RequirementResult]] = {}
    for result in results:
        requirement = requirement_by_id.get(result.requirement_id)
        if requirement is None:
            continue
        row_value = requirement.conditions.get(row_key, _missing)
        col_value = requirement.conditions.get(col_key, _missing)
        if row_value is _missing or col_value is _missing:
            continue
        buckets.setdefault((row_value, col_value), []).append(result)
    return {cell: aggregate_requirement_results(rs) for cell, rs in buckets.items()}


def failure_breakdown(profile: EvaluationProfile, results: list[RequirementResult]) -> GroupCoverage:
    """The same group-tree aggregation coverage.py already uses for full
    coverage (Phase 35's aggregate_group_tree), over whatever result
    subset the caller already filtered. Deliberately does NOT pre-filter
    to fail-only results - each group's pass/na counts stay visible
    alongside fail_count, since "8 failures" means little without
    knowing whether that's 8 of 10 or 8 of 400 (see
    top_failing_groups for the actual failure-sorted view)."""
    return aggregate_group_tree(profile, results)


def top_failing_groups(root: GroupCoverage) -> list[GroupCoverage]:
    """Flattens the group tree and sorts by fail_count descending - the
    "top failing groups" list from the failure-explorer mockup. Includes
    every group, even ones with zero failures; the caller slices for
    display."""
    flattened: list[GroupCoverage] = []

    def walk(node: GroupCoverage) -> None:
        flattened.append(node)
        for child in node.children:
            walk(child)

    walk(root)
    return sorted(flattened, key=lambda g: g.fail_count, reverse=True)


# N/A reason categories, matched against the *exact* free-text reason
# strings evidence.py/coverage.py already produce (v0.4, unchanged) -
# not a new structured field on RequirementResult. Deliberate coupling,
# stated explicitly rather than hidden: if either module's wording ever
# changes, this table must be updated in lockstep - guarded by a
# dedicated cross-layer test that constructs each real reason-producing
# scenario end to end (via the actual select_evidence/evaluate_requirement
# functions, not hand-typed strings) and asserts it still classifies
# correctly. That test caught a real gap while this table was being
# written: the multi-prediction-source case's message ("has multiple
# prediction sources: ... specify which one explicitly via a binding")
# never actually contains the word "ambiguous", unlike the multi-session
# case - both needles are required below, not one.
_NA_REASON_RULES: list[tuple[str, tuple[str, ...]]] = [
    ('no_matching_evidence', ('no session matches conditions',)),
    ('ambiguous_evidence', ('ambiguous', 'multiple prediction sources')),
    ('missing_metric', ('is unavailable for this evidence',)),
]


def classify_na_reason(reason: str) -> str:
    for category, needles in _NA_REASON_RULES:
        if any(needle in reason for needle in needles):
            return category
    return 'other'


def na_breakdown(results: list[RequirementResult]) -> dict[str, int]:
    """Groups N/A results by classify_na_reason. Every na-status
    RequirementResult in practice carries reasons from exactly one
    source (either evidence-selection's single reason, or one-per-
    unresolvable-criterion reasons that all classify identically) - see
    evidence.py/coverage.py - so classifying by the first reason is
    representative, and counts sum to the na total, never more."""
    counts: dict[str, int] = {}
    for result in results:
        if result.status != 'na':
            continue
        category = classify_na_reason(result.reasons[0]) if result.reasons else 'other'
        counts[category] = counts.get(category, 0) + 1
    return counts
