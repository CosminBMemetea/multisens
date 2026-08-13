"""Requirement result / coverage domain model (v0.4, Phase 30).

Derived-evidence shapes, never persisted (see the "recompute, don't
persist" decision on issue #31, mirroring PairwiseComparison's identical
choice in comparison.py) - every RequirementResult/ConfigurationCoverage
is recomputed on request from an EvaluationProfile plus already-persisted
EvaluationResult/Session.metadata evidence. Storing profile *definitions*
is justified (Phase 32); storing their derived results is not.

Deliberately three separate status-bearing shapes, matching the
Evaluation -> Comparison -> Requirement Satisfaction layering this
project keeps distinct: a CriterionResult judges one metric against one
threshold, a RequirementResult judges one requirement's full criteria set
against one piece of selected evidence, and a GroupCoverage/
ConfigurationCoverage aggregates many RequirementResults. None of these
is a compliance/certification verdict - see ComparisonValidity's
docstring in models.py for why this project keeps "evidence-quality
judgment" and "compliance interpretation" strictly separate; the same
separation applies here between "PASS/FAIL/N/A" and any future
requirement-coverage-consuming decision layer.
"""
from __future__ import annotations

import operator as operator_module
from datetime import datetime, timezone
from typing import Callable, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.comparison import ComparisonMetrics, comparison_metrics_from_evaluation_result
from app.domain.evidence import EvidenceBinding, EvidenceSelection, SessionCandidate, select_evidence
from app.domain.models import MetricValue
from app.domain.profiles import (
    AcceptanceCriterion,
    AcceptanceOperator,
    EvaluationProfile,
    Requirement,
    RequirementGroup,
)

RequirementStatus = Literal['pass', 'fail', 'na']


class CriterionResult(BaseModel):
    metric: str
    operator: AcceptanceOperator
    threshold: float
    # None means the metric could not be resolved for this evidence at
    # all (unknown name, or resolved but undefined/zero-denominator) -
    # status is then always 'na', never 'fail'. Never coerced to 0.0 -
    # same MetricValue rule as everywhere else in this codebase.
    observed: MetricValue
    status: RequirementStatus


class EvidenceReference(BaseModel):
    """What RequirementResult.evidence points at. The whole point of this
    field existing is that a PASS/FAIL/N/A can always be traced back to a
    specific session/source/evaluation - never an opaque number."""
    session_id: str
    scenario_id: str
    configuration_id: str
    source_id: str
    evaluation_result_id: str
    matched_samples: int
    sample_count: int
    coverage: MetricValue


class RequirementResult(BaseModel):
    profile_id: str
    profile_version: str
    requirement_id: str
    configuration_id: str
    task: str
    status: RequirementStatus
    # Non-empty whenever status isn't 'pass' - same enforced-reasons
    # pattern as ComparisonValidity, for the same reason: never silently
    # judge a requirement without saying why.
    reasons: list[str] = Field(default_factory=list)
    criteria: list[CriterionResult] = Field(default_factory=list)
    # None only when status is 'na' for lack-of-evidence reasons (no
    # matching session, ambiguous evidence) - never None for a resolved
    # pass/fail, which always has a specific evidence source behind it.
    evidence: EvidenceReference | None = None
    computed_at: datetime

    @model_validator(mode='after')
    def _reasons_required_unless_pass(self) -> RequirementResult:
        if self.status != 'pass' and not self.reasons:
            raise ValueError(f"status '{self.status}' requires at least one reason")
        return self


class GroupCoverage(BaseModel):
    """Recursive: a leaf group's counts come directly from its own
    requirements' results; a parent group's counts are the sum of its
    children's (Phase 35) - never an average of child percentages, which
    would misweight groups with different denominators."""
    group_id: str | None  # None = profile root
    name: str
    pass_count: int
    fail_count: int
    na_count: int
    # pass / (pass + fail); None (not 0) if pass + fail == 0 - never a
    # fabricated number when nothing was actually decided.
    requirement_coverage: MetricValue
    # (pass + fail) / total; None if total == 0. Must always be shown
    # alongside requirement_coverage, never alone - a high
    # requirement_coverage over a low evidence_completeness is not the
    # same claim as one over a high evidence_completeness, and hiding the
    # second number would let the first one mislead.
    evidence_completeness: MetricValue
    children: list[GroupCoverage] = Field(default_factory=list)


class ConfigurationCoverage(BaseModel):
    profile_id: str
    profile_version: str
    configuration_id: str
    requirement_results: list[RequirementResult]
    root: GroupCoverage


# --- acceptance engine (v0.4, Phase 34) ------------------------------------
#
# Pure functions - no sqlite3/fastapi import, same discipline as every
# other domain module. Reuses comparison.py's comparison_metrics_from_
# evaluation_result rather than recomputing "coverage" a second way -
# v0.4 consumes v0.3's evidence shape instead of rewriting it (the exact
# same ComparisonMetrics.coverage formula, matched_samples/sample_count,
# None if sample_count is 0).

# Public (not _OPERATORS) since Phase 69 (v0.7) reuses this exact
# mapping for resource constraints - same "promoted to public so a
# later layer can never silently disagree with this one by
# reimplementing operator application a second way" reasoning as
# status_counts/coverage_and_completeness's own v0.5 promotion.
ACCEPTANCE_OPERATORS: dict[AcceptanceOperator, Callable[[float, float], bool]] = {
    '>=': operator_module.ge,
    '<=': operator_module.le,
    '>': operator_module.gt,
    '<': operator_module.lt,
    '==': operator_module.eq,
}


def _resolve_metric(metrics: ComparisonMetrics, metric_name: str) -> MetricValue:
    # "coverage" is a synthetic key, not a member of EvaluationResult.metrics
    # - resolved from ComparisonMetrics.coverage instead, so no fake
    # "coverage" entry ever needs writing into EvaluationResult.metrics at
    # evaluate-time (zero v0.2 schema impact).
    if metric_name == 'coverage':
        return metrics.coverage
    return metrics.metrics.get(metric_name)


def evaluate_criterion(criterion: AcceptanceCriterion, metrics: ComparisonMetrics) -> CriterionResult:
    """A criterion whose metric can't be resolved (unknown name, or
    resolved but undefined - e.g. a zero-denominator precision) is always
    'na', never 'fail' - an unmeasured criterion is not the same claim as
    a measured-and-failing one."""
    observed = _resolve_metric(metrics, criterion.metric)
    if observed is None:
        return CriterionResult(
            metric=criterion.metric, operator=criterion.operator, threshold=criterion.value,
            observed=None, status='na',
        )
    passed = ACCEPTANCE_OPERATORS[criterion.operator](observed, criterion.value)
    return CriterionResult(
        metric=criterion.metric, operator=criterion.operator, threshold=criterion.value,
        observed=observed, status='pass' if passed else 'fail',
    )


def evaluate_requirement(
    requirement: Requirement,
    profile_id: str,
    profile_version: str,
    configuration_id: str,
    selection: EvidenceSelection,
) -> RequirementResult:
    """Status priority (never re-ordered):
    1. na - no evidence could be selected at all (selection.resolved is None).
    2. na - evidence selected, but *any* criterion is na. Deliberately
       stricter than "AND over only the known criteria": silently
       dropping an unresolvable criterion from the AND would let a
       requirement pass despite one of its stated conditions never
       actually having been checked.
    3. fail - every criterion resolved, at least one is fail.
    4. pass - every criterion resolved and passed.
    """
    computed_at = datetime.now(timezone.utc)

    if selection.resolved is None:
        return RequirementResult(
            profile_id=profile_id, profile_version=profile_version, requirement_id=requirement.id,
            configuration_id=configuration_id, task=requirement.task, status='na',
            reasons=list(selection.reasons), criteria=[], evidence=None, computed_at=computed_at,
        )

    resolved = selection.resolved
    metrics = comparison_metrics_from_evaluation_result(resolved.evaluation_result)
    criteria_results = [evaluate_criterion(c, metrics) for c in requirement.acceptance]

    evidence = EvidenceReference(
        session_id=resolved.session.id, scenario_id=resolved.session.scenario_id,
        configuration_id=configuration_id, source_id=resolved.source_id,
        evaluation_result_id=resolved.evaluation_result.id,
        matched_samples=resolved.evaluation_result.matched_samples,
        sample_count=resolved.evaluation_result.sample_count,
        coverage=metrics.coverage,
    )

    na_criteria = [c for c in criteria_results if c.status == 'na']
    if na_criteria:
        status: RequirementStatus = 'na'
        reasons = [f"metric '{c.metric}' is unavailable for this evidence (undefined)" for c in na_criteria]
    else:
        failed_criteria = [c for c in criteria_results if c.status == 'fail']
        if failed_criteria:
            status = 'fail'
            reasons = [
                f'{c.metric} {c.operator} {c.threshold} failed: observed {c.observed:.3f}'
                for c in failed_criteria
            ]
        else:
            status = 'pass'
            reasons = []

    return RequirementResult(
        profile_id=profile_id, profile_version=profile_version, requirement_id=requirement.id,
        configuration_id=configuration_id, task=requirement.task, status=status, reasons=reasons,
        criteria=criteria_results, evidence=evidence, computed_at=computed_at,
    )


# --- coverage engine (v0.4, Phase 35) --------------------------------------
#
# Wires Phases 33+34 together (compute_requirement_results) and performs
# the recursive group aggregation (compute_configuration_coverage). Both
# are pure functions over already-fetched data - no sqlite3/fastapi
# import - matching every other domain module.

def compute_requirement_results(
    profile: EvaluationProfile,
    configuration_id: str,
    candidates_by_task: dict[str, list[SessionCandidate]],
    bindings: dict[str, EvidenceBinding] | None = None,
) -> list[RequirementResult]:
    """One RequirementResult per requirement in the profile, in profile
    order. `candidates_by_task` is keyed by task (not requirement id) -
    the caller fetches candidate sessions once per distinct task used
    across the profile, not once per requirement, since two requirements
    sharing a task share the same candidate pool. `bindings` is keyed by
    requirement id and is entirely optional - a requirement with no
    binding falls through to ordinary discovery."""
    bindings = bindings or {}
    results: list[RequirementResult] = []
    for requirement in profile.requirements:
        candidates = candidates_by_task.get(requirement.task, [])
        selection = select_evidence(requirement, candidates, bindings.get(requirement.id))
        results.append(
            evaluate_requirement(requirement, profile.id, profile.version, configuration_id, selection)
        )
    return results


def status_counts(results: list[RequirementResult]) -> tuple[int, int, int]:
    """Public since Phase 44 (app/domain/analysis.py) needs the identical
    tally for arbitrary filtered/grouped result subsets, not just whole
    groups - reused directly rather than reimplemented a second time."""
    pass_count = sum(1 for r in results if r.status == 'pass')
    fail_count = sum(1 for r in results if r.status == 'fail')
    na_count = sum(1 for r in results if r.status == 'na')
    return pass_count, fail_count, na_count


def coverage_and_completeness(pass_count: int, fail_count: int, na_count: int) -> tuple[MetricValue, MetricValue]:
    """Public since Phase 44 needs the identical formula for arbitrary
    filtered/grouped/cross-tabbed populations, not just whole groups -
    reused directly rather than reimplemented a second time."""
    decided = pass_count + fail_count
    total = decided + na_count
    # None (not 0) when nothing was decided, or nothing exists at all -
    # an empty group must read as "nothing here," never as "0% coverage,"
    # which would misrepresent an absence of requirements as a failure.
    requirement_coverage = (pass_count / decided) if decided > 0 else None
    evidence_completeness = (decided / total) if total > 0 else None
    return requirement_coverage, evidence_completeness


def _build_group_coverage(
    group_id: str | None,
    name: str,
    results_by_group: dict[str, list[RequirementResult]],
    child_groups_by_parent: dict[str | None, list[RequirementGroup]],
) -> GroupCoverage:
    own_results = results_by_group.get(group_id, [])
    own_pass, own_fail, own_na = status_counts(own_results)

    children = [
        _build_group_coverage(child.id, child.name, results_by_group, child_groups_by_parent)
        for child in child_groups_by_parent.get(group_id, [])
    ]

    # Leaf-count aggregation, never an average of child percentages -
    # a parent with children of very different sizes would otherwise be
    # misweighted (a 1-requirement 100%-coverage child and a
    # 99-requirement 10%-coverage child do not average to a meaningful
    # "55%" for the parent).
    pass_count = own_pass + sum(c.pass_count for c in children)
    fail_count = own_fail + sum(c.fail_count for c in children)
    na_count = own_na + sum(c.na_count for c in children)
    requirement_coverage, evidence_completeness = coverage_and_completeness(pass_count, fail_count, na_count)

    return GroupCoverage(
        group_id=group_id, name=name, pass_count=pass_count, fail_count=fail_count, na_count=na_count,
        requirement_coverage=requirement_coverage, evidence_completeness=evidence_completeness,
        children=children,
    )


def aggregate_group_tree(profile: EvaluationProfile, results: list[RequirementResult]) -> GroupCoverage:
    """The recursive group-tree walk, over an arbitrary - possibly
    partial or filtered - result list. Deliberately does NOT enforce
    compute_configuration_coverage's "one result per requirement"
    invariant: a result list missing some requirements simply makes
    those requirements contribute nothing to the tree, which is exactly
    right for a filtered subset (v0.5's analysis.py reuses this directly
    for failure/condition breakdowns over an already-filtered result
    list) but would silently undercount a *full* coverage computation -
    that invariant is compute_configuration_coverage's job, checked
    before it delegates here, not this function's."""
    requirements_by_id = {r.id: r for r in profile.requirements}
    results_by_group: dict[str, list[RequirementResult]] = {}
    for result in results:
        requirement = requirements_by_id.get(result.requirement_id)
        if requirement is None:
            continue
        results_by_group.setdefault(requirement.group_id, []).append(result)

    child_groups_by_parent: dict[str | None, list[RequirementGroup]] = {}
    for group in profile.groups:
        child_groups_by_parent.setdefault(group.parent_id, []).append(group)

    return _build_group_coverage(None, profile.name, results_by_group, child_groups_by_parent)


def compute_configuration_coverage(
    profile: EvaluationProfile,
    configuration_id: str,
    requirement_results: list[RequirementResult],
) -> ConfigurationCoverage:
    """requirement_results must contain exactly one result per requirement
    in the profile - a caller bug that silently omits one would otherwise
    produce a coverage number that's quietly undercounted rather than
    visibly wrong, exactly the kind of hidden error this project's N/A
    discipline exists to prevent."""
    requirement_ids = {r.id for r in profile.requirements}
    result_ids = {r.requirement_id for r in requirement_results}
    if requirement_ids != result_ids:
        missing = requirement_ids - result_ids
        unexpected = result_ids - requirement_ids
        raise ValueError(
            f'requirement_results must have exactly one result per profile requirement - '
            f'missing: {sorted(missing)}, unexpected: {sorted(unexpected)}'
        )

    root = aggregate_group_tree(profile, requirement_results)

    return ConfigurationCoverage(
        profile_id=profile.id, profile_version=profile.version, configuration_id=configuration_id,
        requirement_results=requirement_results, root=root,
    )
