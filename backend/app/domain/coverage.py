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
from app.domain.evidence import EvidenceSelection
from app.domain.models import MetricValue
from app.domain.profiles import AcceptanceCriterion, AcceptanceOperator, Requirement

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

_OPERATORS: dict[AcceptanceOperator, Callable[[float, float], bool]] = {
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
    passed = _OPERATORS[criterion.operator](observed, criterion.value)
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
