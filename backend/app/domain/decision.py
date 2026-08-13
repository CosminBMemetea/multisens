"""Decision-support domain model + engine (v0.6, Phase 53-55).

Transport/storage-agnostic like every other domain module - no fastapi,
sqlite3, or rclpy import. Phase 53 defined the shape (`DecisionPolicy`,
`PolicyStatus`); Phase 54 added the pure policy/minimality/dominance
functions; Phase 55 adds requirement-transition and condition-level gap
summaries - comparing two already-evaluated configurations, a separate
concern from evaluating one against a policy. None of this is exposed
over HTTP yet (Phase 56).

Decision support consumes v0.4's already-computed `RequirementResult`/
`AggregateCoverage`-shaped evidence (see coverage.py / analysis.py) -
it never re-decides PASS/FAIL/N/A and never re-implements v0.5's
condition matching/grouping. A `DecisionPolicy` only says what counts
as "good enough"; a configuration's actual coverage numbers come from
what v0.4/v0.5 already computed.

No sensor-identity/registry change lives here. Reviewed and explicitly
deferred in the v0.6 architecture review (issue #54) and Phase 57
(issue #58, closed) - `Prediction.sensor_ids` is already a free-form
`list[str]` with zero coupling to ROS topics/modality, so
`front_rgb`/`rear_rgb` are already separable configuration members
today; nothing in this module or its consumers needs a new identity
model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.analysis import AggregateCoverage, group_by_condition
from app.domain.comparison import classify_relationship
from app.domain.coverage import RequirementResult, coverage_and_completeness
from app.domain.profiles import ConditionValue, Requirement

# Only value v0.6 supports - "minimize sensor count subject to the
# policy's own coverage/completeness/mandatory criteria being met."
# Future objectives (cost, power, latency, ...) are architected for
# (see DecisionPolicy.objective's Literal, extendable additively) but
# deliberately not implemented until real, semantically reliable data
# for them exists - v0.6 must not fabricate hardware characteristics.
DecisionObjective = Literal['minimize_sensor_count']

# SUFFICIENT / INSUFFICIENT / UNDETERMINED - never a binary
# good/bad. Precise semantics, implemented by evaluate_policy below.
# The two policy criteria behave fundamentally differently under
# unresolved N/A's, and are evaluated differently on purpose:
#
#   - Zero requirements in the filtered population at all ->
#     UNDETERMINED ("no requirements to evaluate this policy against"),
#     never a vacuous SUFFICIENT.
#
#   - `minimum_evidence_completeness` is checked against the population's
#     REAL, current N/A count - never hypothetically resolved.
#     Completeness = decided / total can only ever *improve* as more
#     N/A's get resolved (in either direction - pass or fail both count
#     as "decided"), reaching exactly 1.0 once every requirement is
#     decided. So a completeness shortfall is always a "not enough
#     evidence has been gathered yet" situation, in principle always
#     fixable by more testing - it can NEVER be a permanent violation,
#     and therefore can only ever produce UNDETERMINED, never
#     INSUFFICIENT. (An earlier draft of this function bounded
#     completeness the same way as coverage below and found it was dead
#     code as a result - because "every N/A resolved" always means
#     completeness = 1.0 in *both* the best- and worst-case hypotheticals,
#     the threshold could never actually fire. Caught by
#     test_evaluate_policy_insufficient_when_completeness_below_threshold
#     failing before this shipped.)
#
#   - `minimum_requirement_coverage` and `mandatory_requirements_must_pass`
#     DO depend on how any remaining N/A's eventually resolve (each one
#     could become a pass or a fail), so they're bounded via best-case
#     (every N/A -> pass) and worst-case (every N/A -> fail):
#       - worst case still meets both -> SUFFICIENT (true no matter how
#         the N/A's eventually resolve).
#       - best case still fails either -> INSUFFICIENT (true no matter
#         how they resolve).
#       - otherwise (best case would pass, worst case would fail) ->
#         UNDETERMINED - the real answer depends on evidence that
#         doesn't exist yet.
#
#   - Both checks must independently allow SUFFICIENT: completeness
#     already met, AND the worst-case coverage/mandatory bound met.
PolicyStatus = Literal['sufficient', 'insufficient', 'undetermined']


@dataclass
class DecisionPolicy:
    """What "good enough" means for one decision-analysis call. Every
    field is required - there is deliberately no default anywhere on
    this class (see the v0.6 architecture review, issue #54, Q4/§29):
    a 100%-coverage/95%-completeness/mandatory-pass bar is exactly the
    kind of arbitrary, regulatory-looking default this project refuses
    to apply silently. The frontend's demo form may pre-fill one
    clearly-labeled example policy, but the API itself never assumes
    one - an omitted policy is a 422, not a silent default.

    `mandatory_requirements_must_pass` is a plain boolean meaning
    "every requirement in the filtered population must be PASS (zero
    fail, zero na)" - not a per-requirement scoped list. Resolved this
    way deliberately in the architecture review: `Requirement` carries
    no `mandatory` field (v0.4 never defined one - see
    docs/limitations.md), and a scoped "these specific requirements are
    mandatory" policy would need one. That's a real, plausible v0.7+
    extension, not built here because nothing in v0.6's own scope
    demonstrates the need for it yet.
    """
    minimum_requirement_coverage: float
    minimum_evidence_completeness: float
    mandatory_requirements_must_pass: bool
    objective: DecisionObjective


@dataclass
class ConfigurationEvidence:
    """Input to the decision engine: one configuration's sensor
    membership, its already-computed aggregate coverage under whatever
    filter the caller applied, and the filtered `RequirementResult`s
    themselves (v0.5's `AggregateCoverage`/v0.4's `RequirementResult`,
    reused directly - the decision engine never recomputes pass/fail/na
    itself). `requirement_results` is only needed by Phase 55's gap
    functions (minimality/dominance never look at it); carried here
    anyway so a `ConfigurationDecision` is the one complete row Phase 56
    hands to both. `sensor_ids` is a `frozenset` deliberately, not a
    `list` - minimality/dominance are set operations, and set membership
    order was never meaningful."""
    configuration_id: str
    sensor_ids: frozenset[str]
    aggregate: AggregateCoverage
    requirement_results: list[RequirementResult]


@dataclass
class ConfigurationDecision:
    """One `ConfigurationEvidence` plus its computed `policy_status` -
    the engine's one enrichment step. Everything downstream (minimal
    sets, Pareto front, gap analysis) operates on lists of these."""
    configuration_id: str
    sensor_ids: frozenset[str]
    aggregate: AggregateCoverage
    requirement_results: list[RequirementResult]
    policy_status: PolicyStatus


def _meets_coverage_and_mandatory(pass_count: int, fail_count: int, policy: DecisionPolicy) -> bool:
    """Coverage and mandatory-pass only - deliberately NOT completeness,
    which `evaluate_policy` checks separately against the real N/A
    count (see `PolicyStatus`'s docstring for why). Reuses
    coverage.py's exact coverage formula via `coverage_and_completeness`,
    never reimplemented; only its first element is used here."""
    coverage, _completeness = coverage_and_completeness(pass_count, fail_count, na_count=0)
    if coverage is None:
        return False
    if coverage < policy.minimum_requirement_coverage:
        return False
    if policy.mandatory_requirements_must_pass and fail_count > 0:
        return False
    return True


def evaluate_policy(aggregate: AggregateCoverage, policy: DecisionPolicy) -> PolicyStatus:
    """See `PolicyStatus`'s own docstring for the exact semantics this
    implements."""
    pass_count, fail_count, na_count = aggregate.pass_count, aggregate.fail_count, aggregate.na_count
    total = pass_count + fail_count + na_count
    if total == 0:
        return 'undetermined'

    decided = pass_count + fail_count
    completeness = decided / total
    if completeness < policy.minimum_evidence_completeness:
        return 'undetermined'

    if na_count == 0:
        return 'sufficient' if _meets_coverage_and_mandatory(pass_count, fail_count, policy) else 'insufficient'

    best_case = _meets_coverage_and_mandatory(pass_count + na_count, fail_count, policy)  # every N/A -> pass
    worst_case = _meets_coverage_and_mandatory(pass_count, fail_count + na_count, policy)  # every N/A -> fail

    if worst_case:
        return 'sufficient'
    if not best_case:
        return 'insufficient'
    return 'undetermined'


def evaluate_configurations(
    configurations: list[ConfigurationEvidence], policy: DecisionPolicy,
) -> list[ConfigurationDecision]:
    return [
        ConfigurationDecision(
            configuration_id=c.configuration_id,
            sensor_ids=c.sensor_ids,
            aggregate=c.aggregate,
            requirement_results=c.requirement_results,
            policy_status=evaluate_policy(c.aggregate, policy),
        )
        for c in configurations
    ]


def find_sufficient_configurations(decisions: list[ConfigurationDecision]) -> list[ConfigurationDecision]:
    return [d for d in decisions if d.policy_status == 'sufficient']


def find_minimal_sufficient_sets(sufficient: list[ConfigurationDecision]) -> list[ConfigurationDecision]:
    """Set-inclusion minimality, not sensor-count sorting - stronger and
    more useful (v0.6 architecture review, Q6/Q10): a sufficient
    configuration `C` is minimal iff no other sufficient configuration's
    sensor set is a *strict subset* of `C`'s. May return several tied
    configurations - never arbitrarily narrowed to one - sorted
    deterministically by `configuration_id` for stable output."""
    minimal = [
        c for c in sufficient
        if not any(other.sensor_ids < c.sensor_ids for other in sufficient if other is not c)
    ]
    return sorted(minimal, key=lambda c: c.configuration_id)


def _ge_treating_none_as_worst(x: float | None, y: float | None) -> bool:
    if x is None and y is None:
        return True
    if x is None:
        return False
    if y is None:
        return True
    return x >= y


def _gt_treating_none_as_worst(x: float | None, y: float | None) -> bool:
    if x is None:
        return False
    if y is None:
        return True
    return x > y


def _dominates(a: ConfigurationDecision, b: ConfigurationDecision) -> bool:
    """`a` dominates `b` iff same-or-fewer sensors, same-or-better
    coverage, same-or-better completeness, and strictly better in at
    least one dimension - per the master prompt's own definition. A
    `None` coverage/completeness (zero decided requirements) is treated
    as strictly worse than any real value on that dimension; two
    `None`s tie on that dimension - an honest way to compare a
    completely-undecided configuration without crashing."""
    a_sensors, b_sensors = len(a.sensor_ids), len(b.sensor_ids)
    a_cov, b_cov = a.aggregate.requirement_coverage, b.aggregate.requirement_coverage
    a_comp, b_comp = a.aggregate.evidence_completeness, b.aggregate.evidence_completeness

    if a_sensors > b_sensors:
        return False
    if not _ge_treating_none_as_worst(a_cov, b_cov):
        return False
    if not _ge_treating_none_as_worst(a_comp, b_comp):
        return False

    return (
        a_sensors < b_sensors
        or _gt_treating_none_as_worst(a_cov, b_cov)
        or _gt_treating_none_as_worst(a_comp, b_comp)
    )


def find_dominated_configurations(decisions: list[ConfigurationDecision]) -> list[ConfigurationDecision]:
    """The subset of `decisions` dominated by at least one other member
    of the same list. No optimization library - O(n^2) pairwise, which
    is fine at the realistic scale here: configuration *count* is
    bounded by evaluated evidence (never a generated power set, see the
    master prompt's own §23), realistically dozens, not thousands."""
    return [
        candidate for candidate in decisions
        if any(_dominates(other, candidate) for other in decisions if other is not candidate)
    ]


def find_pareto_front(decisions: list[ConfigurationDecision]) -> list[ConfigurationDecision]:
    """The non-dominated subset - what a Pareto summary displays
    prominently (dominated configurations are shown collapsed below,
    per the master prompt's §37, not part of this function's job)."""
    dominated_ids = {d.configuration_id for d in find_dominated_configurations(decisions)}
    return [d for d in decisions if d.configuration_id not in dominated_ids]


# --- requirement gap engine (v0.6, Phase 55) --------------------------------
#
# Compares two already-evaluated configurations - never re-decides
# PASS/FAIL/N/A, never re-implements v0.5's condition grouping. A
# separate concern from evaluate_policy above: that judges ONE
# configuration against a policy; this compares TWO configurations
# against each other.

@dataclass
class RequirementTransitions:
    """Four separately-exposed transition categories, never collapsed
    into one delta (master prompt §13: "do not reduce all of this to a
    single delta"). Each list holds requirement ids, sorted."""
    fail_to_pass: list[str]
    na_to_pass: list[str]
    pass_to_fail: list[str]
    pass_to_na: list[str]


def compute_requirement_transitions(
    baseline_results: list[RequirementResult], candidate_results: list[RequirementResult],
) -> RequirementTransitions:
    """Both sides must cover the exact same requirement population (same
    profile, same filter) - a precondition, not silently reconciled;
    diffing two different populations would produce a meaningless
    result. Pure status-dict comparison, nothing else."""
    baseline_by_id = {r.requirement_id: r.status for r in baseline_results}
    candidate_by_id = {r.requirement_id: r.status for r in candidate_results}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError(
            'baseline and candidate requirement_results must cover the exact same requirement '
            f'population - baseline has {len(baseline_by_id)} requirements, '
            f'candidate has {len(candidate_by_id)}'
        )

    fail_to_pass: list[str] = []
    na_to_pass: list[str] = []
    pass_to_fail: list[str] = []
    pass_to_na: list[str] = []
    for requirement_id in sorted(baseline_by_id):
        before, after = baseline_by_id[requirement_id], candidate_by_id[requirement_id]
        if before == 'fail' and after == 'pass':
            fail_to_pass.append(requirement_id)
        elif before == 'na' and after == 'pass':
            na_to_pass.append(requirement_id)
        elif before == 'pass' and after == 'fail':
            pass_to_fail.append(requirement_id)
        elif before == 'pass' and after == 'na':
            pass_to_na.append(requirement_id)
    return RequirementTransitions(fail_to_pass, na_to_pass, pass_to_fail, pass_to_na)


@dataclass
class ConditionGapEntry:
    """One condition value's observed coverage on each side plus the
    delta, in percentage points - same `coverage_delta_pp` convention
    v0.3's `ComparisonSide` already established, not a new one. Never
    causal language anywhere this is rendered (master prompt §15)."""
    value: ConditionValue
    baseline: AggregateCoverage
    candidate: AggregateCoverage
    coverage_delta_pp: float | None


_EMPTY_AGGREGATE = AggregateCoverage(pass_count=0, fail_count=0, na_count=0, requirement_coverage=None, evidence_completeness=None)


def compute_condition_gap_summary(
    baseline_results: list[RequirementResult],
    candidate_results: list[RequirementResult],
    requirement_by_id: dict[str, Requirement],
    condition_key: str,
) -> list[ConditionGapEntry]:
    """Reuses v0.5's `group_by_condition` directly for each side, then
    subtracts bucket-by-bucket - no grouping/aggregation logic
    duplicated (master prompt §40/§15: "integrate v0.5 condition
    metadata... do not duplicate condition analysis from v0.5"). A
    condition value present on only one side gets an empty aggregate on
    the other, never silently dropped from the summary."""
    baseline_buckets = group_by_condition(baseline_results, requirement_by_id, condition_key)
    candidate_buckets = group_by_condition(candidate_results, requirement_by_id, condition_key)

    entries = []
    for value in sorted(set(baseline_buckets) | set(candidate_buckets), key=str):
        baseline_agg = baseline_buckets.get(value, _EMPTY_AGGREGATE)
        candidate_agg = candidate_buckets.get(value, _EMPTY_AGGREGATE)
        coverage_delta_pp = (
            (candidate_agg.requirement_coverage - baseline_agg.requirement_coverage) * 100
            if candidate_agg.requirement_coverage is not None and baseline_agg.requirement_coverage is not None
            else None
        )
        entries.append(ConditionGapEntry(value, baseline_agg, candidate_agg, coverage_delta_pp))
    return entries


@dataclass
class DirectRemoval:
    """One sensor's removal outcome from a configuration. Scoped
    wording only - "removable without violating the current policy" /
    "policy-critical within this configuration" - never "redundant
    sensor" or "necessary sensor" as an intrinsic property (master
    prompt §11/§12, v0.6 architecture review Q10). `configuration_id`/
    `policy_status` are both `None` together when this exact removal was
    never evaluated - reported as unknown, never estimated (§24)."""
    removed_sensor_id: str
    configuration_id: str | None
    policy_status: PolicyStatus | None


def find_direct_removals(
    configuration: ConfigurationDecision,
    configurations_by_sensor_set: dict[frozenset[str], ConfigurationDecision],
) -> list[DirectRemoval]:
    """For each sensor in `configuration`, looks up whether the actual
    direct-removal configuration was evaluated - `configurations_by_
    sensor_set` is built by the caller from every discovered
    configuration, keyed by its own `sensor_ids`, so this never
    estimates or interpolates a removal that doesn't exist in evidence."""
    removals = []
    for sensor_id in sorted(configuration.sensor_ids):
        remaining = configuration.sensor_ids - {sensor_id}
        match = configurations_by_sensor_set.get(remaining)
        if match is None:
            removals.append(DirectRemoval(sensor_id, None, None))
        else:
            removals.append(DirectRemoval(sensor_id, match.configuration_id, match.policy_status))
    return removals


@dataclass
class SensorAdditionAnalysis:
    """Deliberately many small, structured fields - never a single
    magic `importance_score` (master prompt §16). Works for any
    baseline/candidate pair, not only a clean one-sensor addition -
    `added_sensor_ids`/`removed_sensor_ids` (v0.3's exact
    `classify_relationship` set-difference, reused rather than
    reimplemented) may both be non-empty for a "general" comparison."""
    baseline_configuration_id: str
    candidate_configuration_id: str
    added_sensor_ids: list[str]
    removed_sensor_ids: list[str]
    coverage_delta_pp: float | None
    completeness_delta_pp: float | None
    transitions: RequirementTransitions
    baseline_policy_status: PolicyStatus
    candidate_policy_status: PolicyStatus


def analyze_sensor_addition(baseline: ConfigurationDecision, candidate: ConfigurationDecision) -> SensorAdditionAnalysis:
    """`baseline`/`candidate` must already carry filtered
    `requirement_results` over the same population (see
    `compute_requirement_transitions`'s precondition) - this function
    only composes what's already been computed, it doesn't fetch or
    filter anything itself."""
    added, removed, _relationship = classify_relationship(
        sorted(baseline.sensor_ids), sorted(candidate.sensor_ids),
    )
    transitions = compute_requirement_transitions(baseline.requirement_results, candidate.requirement_results)

    b_cov, c_cov = baseline.aggregate.requirement_coverage, candidate.aggregate.requirement_coverage
    coverage_delta_pp = (c_cov - b_cov) * 100 if b_cov is not None and c_cov is not None else None

    b_comp, c_comp = baseline.aggregate.evidence_completeness, candidate.aggregate.evidence_completeness
    completeness_delta_pp = (c_comp - b_comp) * 100 if b_comp is not None and c_comp is not None else None

    return SensorAdditionAnalysis(
        baseline_configuration_id=baseline.configuration_id,
        candidate_configuration_id=candidate.configuration_id,
        added_sensor_ids=added,
        removed_sensor_ids=removed,
        coverage_delta_pp=coverage_delta_pp,
        completeness_delta_pp=completeness_delta_pp,
        transitions=transitions,
        baseline_policy_status=baseline.policy_status,
        candidate_policy_status=candidate.policy_status,
    )
