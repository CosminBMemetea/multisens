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

POST .../decision-analysis (v0.6, Phase 56) exposes Phase 53-55's policy/
minimality/dominance/gap engine - one consolidated route, not a second
`/gap-analysis` endpoint (the v0.6 architecture review's own §39 challenge):
`gap_analysis` is an optional nested request/response section on the same
call, not a separate route, since it always needs the same evidence this
route already gathered for its `baseline_configuration_id`/
`candidate_configuration_id`. Reuses the exact same
_resolve_sessions/_resolve_configuration_ids/
_compute_requirement_results_by_configuration helpers /coverage and
/analysis already use - no new discovery logic. Never re-decides
PASS/FAIL/N/A and never re-implements v0.5's condition grouping.

POST .../tradeoffs (v0.7, Phase 70) exposes Phase 64-69's resource-
observation/summary/trade-off/constraint/Pareto engine - reuses
_resolve_configuration_ids/_compute_requirement_results_by_configuration
exactly like the routes above, and never re-implements
build_configuration_tradeoff/evaluate_resource_constraint/
find_pareto_front_general at this layer. Resource evidence is inherently
single-session-scoped (see app/domain/resources.py's own module
docstring), so this route takes one required session_id rather than the
optional session_ids list every other route above accepts.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

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
from app.domain.decision import (
    ConfigurationEvidence,
    DecisionObjective,
    DecisionPolicy,
    PolicyStatus,
    analyze_sensor_addition,
    compute_condition_gap_summary,
    evaluate_configurations,
    find_direct_removals,
    find_dominated_configurations,
    find_minimal_sufficient_sets,
    find_pareto_front,
    find_sufficient_configurations,
)
from app.domain.evidence import EvidenceBinding, SessionCandidate
from app.domain.models import Session
from app.domain.profiles import (
    AcceptanceCriterion,
    AcceptanceOperator,
    ConditionValue,
    EvaluationProfile,
    Requirement,
    RequirementGroup,
    validate_profile,
)
from app.domain.resources import (
    SUPPORTED_RESOURCE_METRICS,
    UNKNOWN_PLATFORM_ID,
    ConfigurationResourceProfile,
    ConfigurationTradeoff,
    ParetoDirection,
    ParetoPoint,
    QualificationStatus,
    build_configuration_tradeoff,
    compute_configuration_resource_profile,
    compute_resource_delta,
    evaluate_resource_constraint,
    evaluate_resource_qualification,
    find_pareto_front_general,
)
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


# --- decision support (v0.6, Phase 56) --------------------------------------

class DecisionPolicyRequest(BaseModel):
    # No default on any field - an omitted policy is a 422, never a
    # silently-applied threshold (v0.6 architecture review, §29).
    minimum_requirement_coverage: float
    minimum_evidence_completeness: float
    mandatory_requirements_must_pass: bool
    objective: DecisionObjective


class GapAnalysisRequest(BaseModel):
    baseline_configuration_id: str
    # None -> no sensor-addition/removal comparison computed, just the
    # removal sweep below (if requested).
    candidate_configuration_id: str | None = None
    include_removal_sweep: bool = False
    # Condition dimensions to break the addition/removal delta down by -
    # independent 1D summaries, not a cross-tab, so no 2-dimension cap.
    group_by: list[str] = Field(default_factory=list)


class DecisionAnalysisRequest(BaseModel):
    policy: DecisionPolicyRequest
    filters: AnalysisFilterRequest = Field(default_factory=AnalysisFilterRequest)
    configuration_ids: list[str] | None = None
    session_ids: list[str] | None = None
    requirement_bindings: dict[str, RequirementBindingRequest] = Field(default_factory=dict)
    gap_analysis: GapAnalysisRequest | None = None


class ConfigurationDecisionResponse(BaseModel):
    configuration_id: str
    sensor_ids: list[str]
    sensor_count: int
    summary: AggregateResponse
    # None means NO EVIDENCE - this configuration_id was named but no
    # prediction anywhere has ever used it, so sensor_ids/sensor_count
    # are also empty/zero. Reported explicitly, never silently dropped
    # (v0.6 master prompt §24).
    policy_status: PolicyStatus | None
    dominated: bool
    requirement_results: list[RequirementResult]


class RequirementTransitionsResponse(BaseModel):
    fail_to_pass: list[str]
    na_to_pass: list[str]
    pass_to_fail: list[str]
    pass_to_na: list[str]


class ConditionGapEntryResponse(BaseModel):
    value: ConditionValue
    baseline: AggregateResponse
    candidate: AggregateResponse
    coverage_delta_pp: float | None


class SensorAdditionAnalysisResponse(BaseModel):
    baseline_configuration_id: str
    candidate_configuration_id: str
    added_sensor_ids: list[str]
    removed_sensor_ids: list[str]
    coverage_delta_pp: float | None
    completeness_delta_pp: float | None
    transitions: RequirementTransitionsResponse
    baseline_policy_status: PolicyStatus
    candidate_policy_status: PolicyStatus
    # Keyed by condition dimension name (from the request's group_by) -
    # empty dict if none were requested.
    condition_gap_summaries: dict[str, list[ConditionGapEntryResponse]] = Field(default_factory=dict)


class DirectRemovalResponse(BaseModel):
    removed_sensor_id: str
    # Both None together when this exact removal was never evaluated -
    # NO EVIDENCE, never estimated (v0.6 master prompt §24).
    configuration_id: str | None
    policy_status: PolicyStatus | None


class GapAnalysisResponse(BaseModel):
    addition: SensorAdditionAnalysisResponse | None = None
    removal_sweep: list[DirectRemovalResponse] | None = None


class DecisionAnalysisResponse(BaseModel):
    policy: DecisionPolicyRequest
    configurations: list[ConfigurationDecisionResponse]
    sufficient_configuration_ids: list[str]
    # Deliberately a flat list, not a list of sensor-id groups - each
    # entry names one *evaluated configuration* whose own sensor_ids are
    # already in `configurations` above; several may be returned, tied,
    # never arbitrarily narrowed to one (v0.6 master prompt §9).
    minimal_sufficient_configuration_ids: list[str]
    pareto_front_configuration_ids: list[str]
    gap_analysis: GapAnalysisResponse | None = None


@router.post('/{profile_id}/decision-analysis')
def analyze_decision(
    profile_id: str, body: DecisionAnalysisRequest, conn: sqlite3.Connection = Depends(get_db),
) -> DecisionAnalysisResponse:
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

    criteria = AnalysisFilter(
        conditions=body.filters.conditions, group_id=body.filters.group_id,
        task=body.filters.task, status=body.filters.status,
    )
    requirement_by_id = {r.id: r for r in profile.requirements}
    policy = DecisionPolicy(
        minimum_requirement_coverage=body.policy.minimum_requirement_coverage,
        minimum_evidence_completeness=body.policy.minimum_evidence_completeness,
        mandatory_requirements_must_pass=body.policy.mandatory_requirements_must_pass,
        objective=body.policy.objective,
    )

    # Configurations with no resolvable sensor_ids (named but never
    # evaluated by any real prediction) can't join policy evaluation/
    # minimality/dominance at all - reported directly as NO EVIDENCE
    # rows, never silently dropped.
    no_evidence_responses: list[ConfigurationDecisionResponse] = []
    evidence_list: list[ConfigurationEvidence] = []
    for configuration_id, results in results_by_configuration.items():
        filtered = filter_requirement_results(profile, results, criteria)
        summary = aggregate_requirement_results(filtered)
        sensor_ids = repo.get_sensor_ids_for_configuration(conn, configuration_id)
        if sensor_ids is None:
            no_evidence_responses.append(ConfigurationDecisionResponse(
                configuration_id=configuration_id, sensor_ids=[], sensor_count=0,
                summary=_to_aggregate_response(summary), policy_status=None, dominated=False,
                requirement_results=filtered,
            ))
            continue
        evidence_list.append(ConfigurationEvidence(
            configuration_id=configuration_id, sensor_ids=frozenset(sensor_ids),
            aggregate=summary, requirement_results=filtered,
        ))

    decisions = evaluate_configurations(evidence_list, policy)
    decisions_by_id = {d.configuration_id: d for d in decisions}
    dominated_ids = {d.configuration_id for d in find_dominated_configurations(decisions)}
    minimal_ids = [d.configuration_id for d in find_minimal_sufficient_sets(find_sufficient_configurations(decisions))]
    pareto_ids = [d.configuration_id for d in find_pareto_front(decisions)]

    configurations_response = no_evidence_responses + [
        ConfigurationDecisionResponse(
            configuration_id=d.configuration_id,
            sensor_ids=sorted(d.sensor_ids),
            sensor_count=len(d.sensor_ids),
            summary=_to_aggregate_response(d.aggregate),
            policy_status=d.policy_status,
            dominated=d.configuration_id in dominated_ids,
            requirement_results=d.requirement_results,
        )
        for d in decisions
    ]

    gap_analysis_response = None
    if body.gap_analysis is not None:
        baseline = decisions_by_id.get(body.gap_analysis.baseline_configuration_id)
        if baseline is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"gap_analysis.baseline_configuration_id "
                    f"'{body.gap_analysis.baseline_configuration_id}' has no evidence in this analysis - "
                    'include it via configuration_ids (or leave configuration_ids unset to discover it)'
                ),
            )

        addition_response = None
        if body.gap_analysis.candidate_configuration_id is not None:
            candidate = decisions_by_id.get(body.gap_analysis.candidate_configuration_id)
            if candidate is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"gap_analysis.candidate_configuration_id "
                        f"'{body.gap_analysis.candidate_configuration_id}' has no evidence in this analysis"
                    ),
                )
            addition = analyze_sensor_addition(baseline, candidate)
            condition_gap_summaries = {
                key: [
                    ConditionGapEntryResponse(
                        value=entry.value,
                        baseline=_to_aggregate_response(entry.baseline),
                        candidate=_to_aggregate_response(entry.candidate),
                        coverage_delta_pp=entry.coverage_delta_pp,
                    )
                    for entry in compute_condition_gap_summary(
                        baseline.requirement_results, candidate.requirement_results, requirement_by_id, key,
                    )
                ]
                for key in body.gap_analysis.group_by
            }
            addition_response = SensorAdditionAnalysisResponse(
                baseline_configuration_id=addition.baseline_configuration_id,
                candidate_configuration_id=addition.candidate_configuration_id,
                added_sensor_ids=addition.added_sensor_ids,
                removed_sensor_ids=addition.removed_sensor_ids,
                coverage_delta_pp=addition.coverage_delta_pp,
                completeness_delta_pp=addition.completeness_delta_pp,
                transitions=RequirementTransitionsResponse(
                    fail_to_pass=addition.transitions.fail_to_pass,
                    na_to_pass=addition.transitions.na_to_pass,
                    pass_to_fail=addition.transitions.pass_to_fail,
                    pass_to_na=addition.transitions.pass_to_na,
                ),
                baseline_policy_status=addition.baseline_policy_status,
                candidate_policy_status=addition.candidate_policy_status,
                condition_gap_summaries=condition_gap_summaries,
            )

        removal_sweep_response = None
        if body.gap_analysis.include_removal_sweep:
            configurations_by_sensor_set = {d.sensor_ids: d for d in decisions}
            removal_sweep_response = [
                DirectRemovalResponse(
                    removed_sensor_id=r.removed_sensor_id,
                    configuration_id=r.configuration_id,
                    policy_status=r.policy_status,
                )
                for r in find_direct_removals(baseline, configurations_by_sensor_set)
            ]

        if addition_response is not None or removal_sweep_response is not None:
            gap_analysis_response = GapAnalysisResponse(
                addition=addition_response, removal_sweep=removal_sweep_response,
            )

    return DecisionAnalysisResponse(
        policy=body.policy,
        configurations=configurations_response,
        sufficient_configuration_ids=sorted(d.configuration_id for d in find_sufficient_configurations(decisions)),
        minimal_sufficient_configuration_ids=minimal_ids,
        pareto_front_configuration_ids=pareto_ids,
        gap_analysis=gap_analysis_response,
    )


# --- resource trade-offs (v0.7, Phase 70) ------------------------------------
#
# POST .../tradeoffs joins v0.6's decision evidence with v0.7's resource
# evidence via app.domain.resources.build_configuration_tradeoff - reuses
# _resolve_configuration_ids/_compute_requirement_results_by_configuration
# exactly like /coverage, /analysis, and /decision-analysis already do,
# and never re-implements the trade-off engine's comparability/
# constraint/Pareto logic at this layer. Resource evidence is inherently
# single-session-scoped (Session, not a new ResourceMeasurementRun
# entity - v0.7 architecture review) - unlike /decision-analysis, this
# route takes one required session_id, not an optional session_ids list.

class ResourceConstraintRequest(BaseModel):
    metric: str
    operator: AcceptanceOperator
    value: float


class ResourceComparisonRequest(BaseModel):
    baseline_configuration_id: str
    candidate_configuration_id: str


class TradeoffRequest(BaseModel):
    policy: DecisionPolicyRequest
    session_id: str
    filters: AnalysisFilterRequest = Field(default_factory=AnalysisFilterRequest)
    configuration_ids: list[str] | None = None
    requirement_bindings: dict[str, RequirementBindingRequest] = Field(default_factory=dict)
    # Empty means "no resource evidence requested" - every configuration's
    # resource_profile stays None, distinct from a profile that was
    # sought but found unavailable (see ConfigurationTradeoff's own
    # docstring in app/domain/resources.py).
    resource_metrics: list[str] = Field(default_factory=list)
    resource_constraints: list[ResourceConstraintRequest] = Field(default_factory=list)
    # Dimension name -> minimize/maximize. Keys must each be one of the
    # three decision-side fields or an entry already in resource_metrics -
    # never an unrequested resource metric, which would be silently
    # all-None for every configuration.
    pareto_dimensions: dict[str, ParetoDirection] = Field(default_factory=dict)
    # Optional nested section, not a separate route - same "gap_analysis
    # on /decision-analysis" pattern (v0.6, Phase 56): a resource
    # comparison always needs the same evidence this call already
    # gathered for baseline_configuration_id/candidate_configuration_id.
    resource_comparison: ResourceComparisonRequest | None = None

    @field_validator('resource_metrics')
    @classmethod
    def _metrics_supported(cls, v: list[str]) -> list[str]:
        unsupported = sorted(set(v) - set(SUPPORTED_RESOURCE_METRICS))
        if unsupported:
            raise ValueError(
                f'unsupported resource metric(s): {unsupported} - supported: {sorted(SUPPORTED_RESOURCE_METRICS)}'
            )
        return v

    @field_validator('resource_constraints')
    @classmethod
    def _constraints_reference_supported_metrics(cls, v: list[ResourceConstraintRequest]) -> list[ResourceConstraintRequest]:
        unsupported = sorted({c.metric for c in v} - set(SUPPORTED_RESOURCE_METRICS))
        if unsupported:
            raise ValueError(f'unsupported resource metric(s) in resource_constraints: {unsupported}')
        return v

    @model_validator(mode='after')
    def _pareto_dimensions_reference_requested_or_decision_fields(self) -> TradeoffRequest:
        allowed = {'sensor_count', 'requirement_coverage', 'evidence_completeness'} | set(self.resource_metrics)
        unknown = sorted(set(self.pareto_dimensions) - allowed)
        if unknown:
            raise ValueError(
                f'pareto_dimensions references metric(s) not in resource_metrics or the decision '
                f'fields (sensor_count/requirement_coverage/evidence_completeness): {unknown}'
            )
        return self


class ResourceMetricSummaryResponse(BaseModel):
    mean: float
    median: float
    p95: float
    min: float
    max: float
    sample_count: int
    unit: str


class ConfigurationResourceProfileResponse(BaseModel):
    configuration_id: str
    session_id: str
    platform_id: str
    metrics: dict[str, ResourceMetricSummaryResponse]
    measurement_window: tuple[datetime, datetime] | None
    validity: Literal['complete', 'partial', 'unavailable']
    warnings: list[str]


class ResourceConstraintResultResponse(BaseModel):
    metric: str
    operator: AcceptanceOperator
    threshold: float
    observed: float | None
    status: Literal['pass', 'fail', 'na']


class ConfigurationTradeoffResponse(BaseModel):
    configuration_id: str
    sensor_count: int
    requirement_coverage: float | None
    evidence_completeness: float | None
    # Both None together only for a named-but-never-evaluated
    # configuration_id (NO EVIDENCE) - same convention
    # ConfigurationDecisionResponse already established in Phase 56.
    policy_status: PolicyStatus | None
    resource_profile: ConfigurationResourceProfileResponse | None
    resource_validity: Literal['complete', 'partial', 'unavailable'] | None
    constraint_results: list[ResourceConstraintResultResponse]
    qualification: QualificationStatus


class ResourceMetricDeltaResponse(BaseModel):
    metric: str
    unit: str
    baseline: float | None
    candidate: float | None
    delta: float | None


class ComparabilityResponse(BaseModel):
    comparable: bool
    warnings: list[str]


class ResourceComparisonResponse(BaseModel):
    baseline_configuration_id: str
    candidate_configuration_id: str
    comparability: ComparabilityResponse
    metric_deltas: list[ResourceMetricDeltaResponse]


class TradeoffResponse(BaseModel):
    policy: DecisionPolicyRequest
    session_id: str
    configurations: list[ConfigurationTradeoffResponse]
    pareto_front_configuration_ids: list[str]
    resource_comparison: ResourceComparisonResponse | None = None


def _to_resource_profile_response(profile: ConfigurationResourceProfile) -> ConfigurationResourceProfileResponse:
    return ConfigurationResourceProfileResponse(
        configuration_id=profile.configuration_id, session_id=profile.session_id, platform_id=profile.platform_id,
        metrics={
            metric: ResourceMetricSummaryResponse(
                mean=s.mean, median=s.median, p95=s.p95, min=s.min, max=s.max,
                sample_count=s.sample_count, unit=s.unit,
            )
            for metric, s in profile.metrics.items()
        },
        measurement_window=profile.measurement_window, validity=profile.validity, warnings=profile.warnings,
    )


def _extract_pareto_value(tradeoff: ConfigurationTradeoff, dimension: str) -> float | None:
    if dimension == 'sensor_count':
        return float(tradeoff.sensor_count)
    if dimension == 'requirement_coverage':
        return tradeoff.requirement_coverage
    if dimension == 'evidence_completeness':
        return tradeoff.evidence_completeness
    if tradeoff.resource_profile is None:
        return None
    summary = tradeoff.resource_profile.metrics.get(dimension)
    return summary.mean if summary is not None else None


@router.post('/{profile_id}/tradeoffs')
def compute_profile_tradeoffs(
    profile_id: str, body: TradeoffRequest, conn: sqlite3.Connection = Depends(get_db),
) -> TradeoffResponse:
    profile = _require_profile(conn, profile_id)
    session = repo.get_session(conn, body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session '{body.session_id}' not found")

    sessions = [session]
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
    policy = DecisionPolicy(
        minimum_requirement_coverage=body.policy.minimum_requirement_coverage,
        minimum_evidence_completeness=body.policy.minimum_evidence_completeness,
        mandatory_requirements_must_pass=body.policy.mandatory_requirements_must_pass,
        objective=body.policy.objective,
    )

    no_evidence_ids: list[str] = []
    evidence_list: list[ConfigurationEvidence] = []
    for configuration_id, results in results_by_configuration.items():
        filtered = filter_requirement_results(profile, results, criteria)
        summary = aggregate_requirement_results(filtered)
        sensor_ids = repo.get_sensor_ids_for_configuration(conn, configuration_id)
        if sensor_ids is None:
            no_evidence_ids.append(configuration_id)
            continue
        evidence_list.append(ConfigurationEvidence(
            configuration_id=configuration_id, sensor_ids=frozenset(sensor_ids),
            aggregate=summary, requirement_results=filtered,
        ))

    decisions = evaluate_configurations(evidence_list, policy)
    constraint_criteria = [
        AcceptanceCriterion(metric=c.metric, operator=c.operator, value=c.value)
        for c in body.resource_constraints
    ]

    tradeoffs: list[ConfigurationTradeoff] = []
    # One representative ResourceObservation.metadata per configuration -
    # comparability needs resolution/target_fps, which live on the raw
    # observation, not on ConfigurationResourceProfile itself (see
    # check_comparability's own docstring for why it stays a
    # caller-supplied parameter rather than growing that shape).
    metadata_by_configuration_id: dict[str, dict[str, Any]] = {}
    configurations_response: list[ConfigurationTradeoffResponse] = []

    for decision in decisions:
        resource_profile = None
        if body.resource_metrics:
            observations = repo.list_resource_observations(
                conn, body.session_id, configuration_id=decision.configuration_id,
            )
            platform_ids = {o.platform_id for o in observations}
            platform_id = platform_ids.pop() if len(platform_ids) == 1 else UNKNOWN_PLATFORM_ID
            resource_profile = compute_configuration_resource_profile(
                session_id=body.session_id, configuration_id=decision.configuration_id, platform_id=platform_id,
                requested_metrics=body.resource_metrics, observations=observations,
            )
            metadata_by_configuration_id[decision.configuration_id] = observations[0].metadata if observations else {}

        tradeoff = build_configuration_tradeoff(decision, resource_profile)
        tradeoffs.append(tradeoff)

        constraint_results = (
            [evaluate_resource_constraint(c, resource_profile) for c in constraint_criteria]
            if resource_profile is not None else []
        )
        qualification = evaluate_resource_qualification(constraint_results)

        configurations_response.append(ConfigurationTradeoffResponse(
            configuration_id=tradeoff.configuration_id,
            sensor_count=tradeoff.sensor_count,
            requirement_coverage=tradeoff.requirement_coverage,
            evidence_completeness=tradeoff.evidence_completeness,
            policy_status=tradeoff.policy_status,
            resource_profile=_to_resource_profile_response(resource_profile) if resource_profile is not None else None,
            resource_validity=tradeoff.resource_validity if resource_profile is not None else None,
            constraint_results=[
                ResourceConstraintResultResponse(
                    metric=r.criterion.metric, operator=r.criterion.operator, threshold=r.criterion.value,
                    observed=r.observed, status=r.status,
                )
                for r in constraint_results
            ],
            qualification=qualification,
        ))

    for configuration_id in no_evidence_ids:
        configurations_response.append(ConfigurationTradeoffResponse(
            configuration_id=configuration_id, sensor_count=0, requirement_coverage=None,
            evidence_completeness=None, policy_status=None, resource_profile=None, resource_validity=None,
            constraint_results=[], qualification='undetermined',
        ))

    pareto_front_ids: list[str] = []
    if body.pareto_dimensions:
        points = [
            ParetoPoint(id=t.configuration_id, values={
                dim: _extract_pareto_value(t, dim) for dim in body.pareto_dimensions
            })
            for t in tradeoffs
        ]
        pareto_front_ids = sorted(p.id for p in find_pareto_front_general(points, body.pareto_dimensions))

    resource_comparison_response = None
    if body.resource_comparison is not None:
        tradeoffs_by_id = {t.configuration_id: t for t in tradeoffs}
        baseline = tradeoffs_by_id.get(body.resource_comparison.baseline_configuration_id)
        if baseline is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"resource_comparison.baseline_configuration_id "
                    f"'{body.resource_comparison.baseline_configuration_id}' has no evidence in this analysis"
                ),
            )
        candidate = tradeoffs_by_id.get(body.resource_comparison.candidate_configuration_id)
        if candidate is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"resource_comparison.candidate_configuration_id "
                    f"'{body.resource_comparison.candidate_configuration_id}' has no evidence in this analysis"
                ),
            )
        delta = compute_resource_delta(
            baseline, metadata_by_configuration_id.get(baseline.configuration_id, {}),
            candidate, metadata_by_configuration_id.get(candidate.configuration_id, {}),
        )
        resource_comparison_response = ResourceComparisonResponse(
            baseline_configuration_id=delta.baseline_configuration_id,
            candidate_configuration_id=delta.candidate_configuration_id,
            comparability=ComparabilityResponse(
                comparable=delta.comparability.comparable, warnings=delta.comparability.warnings,
            ),
            metric_deltas=[
                ResourceMetricDeltaResponse(metric=d.metric, unit=d.unit, baseline=d.baseline,
                                             candidate=d.candidate, delta=d.delta)
                for d in delta.metric_deltas
            ],
        )

    return TradeoffResponse(
        policy=body.policy, session_id=body.session_id,
        configurations=configurations_response, pareto_front_configuration_ids=pareto_front_ids,
        resource_comparison=resource_comparison_response,
    )
