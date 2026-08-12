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

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.models import MetricValue
from app.domain.profiles import AcceptanceOperator

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
