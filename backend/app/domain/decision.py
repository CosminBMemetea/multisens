"""Decision-support domain model (v0.6, Phase 53).

Transport/storage-agnostic like every other domain module - no fastapi,
sqlite3, or rclpy import. Defines the *shape* of a decision policy and
its status outcome, not how sufficiency/minimality/dominance are
actually computed (Phase 54), how requirement transitions/condition
gaps are computed (Phase 55), or how any of this is exposed over HTTP
(Phase 56).

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

# Only value v0.6 supports - "minimize sensor count subject to the
# policy's own coverage/completeness/mandatory criteria being met."
# Future objectives (cost, power, latency, ...) are architected for
# (see DecisionPolicy.objective's Literal, extendable additively) but
# deliberately not implemented until real, semantically reliable data
# for them exists - v0.6 must not fabricate hardware characteristics.
DecisionObjective = Literal['minimize_sensor_count']

# SUFFICIENT / INSUFFICIENT / UNDETERMINED - never a binary
# good/bad. Precise semantics (Phase 54 implements evaluate_policy
# against these, this module only names them):
#
#   - If a configuration's filtered population has zero N/A results,
#     its coverage/completeness are final: SUFFICIENT if every policy
#     criterion is met, INSUFFICIENT if any is violated. No ambiguity.
#
#   - If it has any N/A results, the current coverage/completeness are
#     provisional - a still-unresolved requirement could resolve to
#     pass or fail. Compute the best-case (every N/A -> pass) and
#     worst-case (every N/A -> fail) coverage/completeness/mandatory-
#     status bounds:
#       - worst case still meets the policy -> SUFFICIENT (true no
#         matter how the N/A's eventually resolve).
#       - best case still fails the policy -> INSUFFICIENT (true no
#         matter how they resolve).
#       - otherwise (best case would pass, worst case would fail) ->
#         UNDETERMINED - the real answer depends on evidence that
#         doesn't exist yet. Never silently called INSUFFICIENT just
#         because evidence is incomplete.
#
#   - Zero requirements in the filtered population at all ->
#     UNDETERMINED ("no requirements to evaluate this policy against"),
#     never a vacuous SUFFICIENT.
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
