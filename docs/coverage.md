# Coverage Contract (v0.4)

The authoritative reference for how a [requirement profile](profiles.md)
gets turned into evidence-backed `PASS`/`FAIL`/`N/A` results and
aggregated coverage: evidence selection, the acceptance engine,
recursive aggregation, the `/coverage` API, and the frontend. See
[profiles.md](profiles.md) for the profile document this layer consumes,
and [condition-explorer.md](condition-explorer.md) for the v0.5 layer
built directly on top of this one's `RequirementResult`/`GroupCoverage`
output.

## Evidence selection

[`app/domain/evidence.py`](../backend/app/domain/evidence.py) — pure
function, zero `sqlite3`/`fastapi` import. The hardest v0.4 problem:
given a requirement (task + conditions) and a target configuration,
deterministically decide which single already-evaluated session/source
is "the evidence," or explain exactly why none can be chosen.

### Condition matching

`matches_conditions(session, conditions)`: a requirement's condition map
matches a session iff **every key** in `conditions` is present in
`Session.metadata` with an **exactly equal, type-sensitive** value.
Extra keys in `Session.metadata` are ignored (that's what lets one
session satisfy multiple requirements that only care about a subset of
its documented conditions). A missing key is not a partial match — it's
simply not a match. No coercion, no fuzzy matching:

```python
# Python's `1 == True` is True - this must NOT be treated as a match.
_values_match(True, 1)      # False - bool vs non-bool never match
_values_match(3, 3.0)       # True  - ordinary numeric equality is fine
```

An empty `conditions` map matches every session (the vacuous subset
case) — a requirement with no declared conditions is restricted only by
task/evidence availability, not by condition.

### Never guesses

Zero matching sessions, or more than one, is always `N/A` with a
reason — never a silent pick:

- **Zero sessions** → `"no session matches conditions {...} for task '...'"`.
- **More than one session** → `"N sessions match conditions {...} -
  ambiguous, provide an explicit binding: [...]"`, naming every
  candidate.
- **The one matched session has multiple prediction sources** for the
  target configuration/task → reuses v0.3's exact ambiguity rule and
  message shape (`_resolve_source_id` in
  [comparison.md](comparison.md#multi-source-prediction-ambiguity)) —
  not reinvented.

### Explicit bindings override discovery entirely

`EvidenceBinding(session_id, source_id=None)` — request-scoped only,
**never persisted** (a binding is "how I want to run this report today,"
not a durable profile fact). A binding skips condition matching
entirely, not just ambiguity resolution — it names exactly which
evidence to use, full stop. Without bindings, any two sessions sharing
identical condition maps for the same task+configuration make that
requirement permanently unresolvable through discovery alone; a real
profile with hundreds of condition combinations will need these.

## Acceptance engine

[`app/domain/coverage.py`](../backend/app/domain/coverage.py) —
`evaluate_criterion` and `evaluate_requirement`.

### Metric lookup

Reuses [`comparison_metrics_from_evaluation_result`](comparison.md) (the
exact v0.3 coverage formula) rather than recomputing "coverage" a second
way. `"coverage"` is a synthetic key resolved from
`ComparisonMetrics.coverage` — never a fake entry written into
`EvaluationResult.metrics` at evaluate-time, so v0.4 has zero schema
impact on v0.2. Any other metric name looks up
`ComparisonMetrics.metrics`.

### Per-criterion status

A criterion whose metric can't be resolved (unknown name, or present but
`None`/undefined) is always `na` — **never `fail`**. An unmeasured
criterion is not the same claim as a measured-and-failing one.

### Per-requirement status: priority order, never re-ordered

1. **`na`** — no evidence could be selected at all.
2. **`na`** — evidence selected, but *any* criterion is `na`.
   Deliberately stricter than "AND over only the known criteria": if a
   requirement's other three criteria passed but a fourth's metric was
   undefined, silently dropping that fourth criterion from the AND would
   let the requirement pass despite one of its stated conditions never
   actually being checked.
3. **`fail`** — every criterion resolved, at least one is `fail`.
4. **`pass`** — every criterion resolved and passed.

`RequirementResult.evidence` (an `EvidenceReference`: session, scenario,
prediction source, matched samples, sample count, coverage) is populated
whenever evidence was actually selected — **including** the
na-because-a-criterion-was-unresolvable case — and is `None` only when
selection itself failed. A `PASS`/`FAIL`/`N/A` is always traceable back
to its evidence except when there genuinely was none to trace to.

## Coverage aggregation

[`compute_requirement_results`](../backend/app/domain/coverage.py) wires
evidence selection and the acceptance engine across an entire profile
(one result per requirement, `candidates_by_task` keyed by task since
requirements sharing a task share the same candidate pool).
[`compute_configuration_coverage`](../backend/app/domain/coverage.py)
performs the recursive aggregation, walking the group tree via its
`parent_id` adjacency list.

### Formulas

Let `P` = pass count, `F` = fail count, `N` = N/A count, `T = P + F + N`.

```
requirement_coverage   = P / (P + F)   — None (not 0) if P + F == 0
evidence_completeness  = (P + F) / T   — None (not 0) if T == 0
```

**Always shown together, never one alone.** A high
`requirement_coverage` over a low `evidence_completeness` is not the
same claim as one over a high `evidence_completeness`, and hiding the
second number would let the first one mislead — the single hardest
UI rule in this layer, enforced structurally in the frontend (see
below), not left as a convention someone could forget.

### Leaf-count aggregation, never an average of percentages

A group's `pass_count`/`fail_count`/`na_count` are its own requirements'
counts **plus the sum of its children's** — recursively down to leaves.
`requirement_coverage`/`evidence_completeness` are then *derived* from
those summed counts at every level, never averaged as percentages. A
1-requirement 100%-coverage group and a 10-requirement 10%-coverage
group do not average to a meaningful "55%" for their parent; leaf-count
aggregation correctly reports `2 / 11 ≈ 18.2%`.

### No profile-level status

There is deliberately no rolled-up profile-level `PASS`/`FAIL`/
`INCOMPLETE` — only raw counts and the two percentages above, at every
group level including the root. A single scalar "profile status" is
exactly the kind of nuance-hiding shortcut this whole layer's design
works to avoid; nothing before a future decision-support layer needs
one.

### Defensive invariant

`compute_configuration_coverage` raises if `requirement_results` doesn't
contain exactly one result per profile requirement — a silently dropped
result would otherwise produce a quietly *undercounted* number instead
of a visibly wrong one, exactly the failure mode this project's N/A
discipline exists to prevent.

## API surface

```
POST /api/profiles/{id}/coverage
```

The one derivation route — `mode`, a separate `/evaluate`, and a
separate `/results` route were all considered and rejected in favor of
one call that always does discovery, evidence selection, acceptance
evaluation, and aggregation together.

```json
{
  "configuration_ids": null,
  "session_ids": null,
  "requirement_bindings": {"req-001": {"session_id": "s-1", "source_id": null}}
}
```

`configuration_ids: null` discovers every configuration with at least
one evaluated result for any of the profile's tasks — same "discovered
unless overridden" convention `/compare` established. `session_ids:
null` searches every session (still gated by condition matching and the
ambiguity rule, so this is less dangerous than it sounds). An explicitly
named `configuration_ids` entry with no evidence anywhere is not an
error — it correctly produces an all-`N/A` `ConfigurationCoverage`.
Rebuilt per `configuration_id`, not shared across configurations: an
`EvaluationResult` (and therefore a candidate) is always scoped to one
specific configuration.

**Caveat, not a bug:** an unfiltered call also discovers any
configuration with an evaluated result for the profile's task(s)
*anywhere in the database* — including unrelated standing demo
sessions. Correctly reported as all-`N/A` for requirements none of its
own evidence matches. Use `session_ids` or the frontend's
per-configuration checkboxes to scope a coverage view to just the
sessions you mean. See
[examples/profiles/README.md](../examples/profiles/README.md) for a
concrete illustration.

Response: one `ConfigurationCoverage` per resolved configuration, each
carrying its full `requirement_results` list plus a recursive `root:
GroupCoverage`.

## Frontend

`ProfileDetail.tsx`'s Coverage section: a "Compute coverage" button,
per-configuration visibility checkboxes, a search box, and
`components/CoverageMatrix.tsx` — configurations as columns, the
group/requirement tree as rows (`groupTree.ts`, shared with the plain
hierarchy view). Group summary rows render via a dedicated
`GroupCoverageCell` that *always* emits both percentages together,
structurally, so there is no code path capable of showing one without
the other. Collapsing a group hides its descendant rows but keeps its
own summary row visible; search hides only groups with zero matching
descendants, never an empty group when search is inactive.

Each requirement-row status cell is a button opening
`components/RequirementDrillDown.tsx` — the first modal in this
codebase (backdrop-click and Escape both close it), sourced entirely
from fields already present on `RequirementResult`, no second backend
call. Shows the requirement, its conditions, an explicit "why it
failed"/"why N/A" reasons block whenever status isn't `pass`, the full
evidence reference, and every criterion's
metric/operator/threshold/observed/status. A `PASS`/`FAIL`/`N/A` badge
is never shown without also showing why — directly closing the
"invisible N/A cause" risk identified in the v0.4 architecture review.
Group summary cells stay non-interactive (aggregates, not a single
traceable decision).

`components/StatusBadge.tsx` — a compact 3-state badge sharing
`ComparisonValidityBadge`'s emerald/red/slate visual language but
distinct semantics: this judges one requirement's acceptance criteria
against selected evidence, never a compliance or certification claim.

## Known coverage-layer limitations

See [limitations.md](limitations.md) for the current authoritative
list; summarized here: no weighted or mandatory-requirement
aggregation, an unfiltered `/coverage` call can surface unrelated
configurations as all-`N/A` (see the API caveat above), `metric`
lookup is limited to whatever `ComparisonMetrics` already exposes
(`accuracy`/`precision_macro`/`recall_macro`/`f1_macro`/`precision_micro`/
`recall_micro`/`f1_micro`/`coverage` — no custom-metric registration).
Condition-value filtering (not just requirement name/task) now exists -
see [condition-explorer.md](condition-explorer.md), v0.5.
