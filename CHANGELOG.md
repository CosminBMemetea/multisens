# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Every entry below was verified against a running system, not just a passing
build — that's a project-wide rule, not editorial flourish; see
[docs/development.md](docs/development.md) for how.

## [0.6.0] — v0.6 decision support & minimum sufficient sensor set

Built phase by phase (Phase 53 through Phase 62), same discipline as
v0.1-v0.5: a 25-question architecture review *before* any code, explicit
self-review checkpoints per phase, nothing merged without running
against a real container. Adds a policy-driven decision layer on top of
v0.4's already-computed `RequirementResult`/`AggregateCoverage` evidence
— **never re-decides `PASS`/`FAIL`/`N/A`**, never re-implements v0.5's
condition matching/grouping. No v0.1-v0.5 behavior changed. Full domain
model, algorithm, and API reference:
[docs/decision-support.md](docs/decision-support.md).

### Added

- **`DecisionPolicy`/`PolicyStatus` foundation** (`backend/app/domain/decision.py`,
  Phase 53): `DecisionPolicy` (`minimum_requirement_coverage`,
  `minimum_evidence_completeness`, `mandatory_requirements_must_pass`,
  `objective`) — no default on any field, an omitted policy is always
  `422`, never silently applied. `PolicyStatus`
  (`sufficient`/`insufficient`/`undetermined`) — never a binary good/bad.
  Phase 57 (sensor-identity/ROS migration) reviewed and explicitly
  deferred in the same architecture review: `Prediction.sensor_ids` was
  already a free-form `list[str]` with zero ROS/modality coupling, so
  `front_rgb`/`rear_rgb` needed no new identity model to be separable
  configuration members.
- **Policy/minimality/dominance engine** (Phase 54):
  `evaluate_policy` — completeness checked against the population's
  *real* N/A count (never hypothetically resolved, since it can only
  improve as N/A resolves — a shortfall is always `undetermined`, never
  `insufficient`); coverage/mandatory-pass bounded via best-case/worst-
  case N/A-resolution hypotheticals. `find_minimal_sufficient_sets` —
  strict set-inclusion minimality (`frozenset` proper-subset check), not
  sensor-count sorting; returns every tied minimal configuration, sorted
  deterministically. `find_dominated_configurations`/`find_pareto_front`
  — `A` dominates `B` iff same-or-fewer sensors, same-or-better coverage
  *and* completeness, strictly better in ≥1 dimension; `None` treated as
  strictly worse than any real value, two `None`s tie; O(n²) pairwise,
  bounded by evaluated-configuration count, never a generated power set.
- **Requirement gap engine** (Phase 55): `compute_requirement_transitions`
  — four separately-exposed categories (`fail_to_pass`/`na_to_pass`/
  `pass_to_fail`/`pass_to_na`), never collapsed into one delta; raises on
  a mismatched requirement population rather than diffing a meaningless
  comparison. `compute_condition_gap_summary` — reuses v0.5's
  `group_by_condition` per side, then subtracts bucket-by-bucket, no
  grouping logic duplicated. `find_direct_removals` — scoped wording only
  ("removable without violating the current policy" /
  "policy-critical within this configuration"), `NO EVIDENCE` (both
  `configuration_id`/`policy_status` `None`) for a removal never
  evaluated, never estimated. `analyze_sensor_addition` — composes
  added/removed sensor ids (reusing v0.3's `classify_relationship`
  set-difference directly), coverage/completeness deltas, transitions,
  and both configurations' policy status into one structured result —
  deliberately many small fields, never a single `importance_score`.
- **Decision API** (`backend/app/api/profiles.py`, Phase 56):
  `POST /{profile_id}/decision-analysis` — one consolidated endpoint, not
  a second `/gap-analysis` route; `gap_analysis` is an optional nested
  request/response section reusing `/coverage`/`/analysis`'s exact
  evidence-gathering helpers. A named-but-never-evaluated
  `configuration_id` reports `policy_status: null` with empty
  `sensor_ids` — `NO EVIDENCE`, never silently dropped. A
  `gap_analysis.baseline_configuration_id`/`candidate_configuration_id`
  naming a configuration with no evidence in this analysis is `422`
  (nothing real to compare); the removal sweep instead reports each
  removal, `NO EVIDENCE` and all. `repo.get_sensor_ids_for_configuration`
  added — fetches sensor ids from a representative persisted prediction,
  never reverse-parses the `configuration_id` string itself.
- **Decision UI** (`ProfileDetail.tsx`'s new Decision tab, Phase 58-60):
  `DecisionPanel.tsx` — an editable policy form (objective shown but
  disabled, since only `minimize_sensor_count` exists), the condition
  facet filters reused from v0.5, and a per-configuration summary table.
  `PolicyStatusBadge.tsx` — four states, `sufficient`/`insufficient`/
  `undetermined`/`null` (rendered "No evidence"), always distinguishing
  "policy not met" from "never evaluated." `MinimalSufficientSets` — one
  card per tied minimal configuration, each showing exactly which policy
  criteria it met and why, never narrowed to one. `ParetoFront` — the
  non-dominated trade-off table shown prominently, dominated
  configurations collapsed underneath and labeled `Dominated`, never
  "bad." `GapAnalysisSection` — baseline/candidate pickers (populated
  only from already-evaluated configurations), a sensor-removal-sweep
  checkbox, the four transition counts as clickable buttons opening a
  drill-down built from the candidate's own `requirement_results` —
  reusing `CellDrillDown`/`RequirementDrillDown` verbatim, never a new
  requirement detail renderer. `SensorChips` renders a `SourceTypeBadge`
  only when a sensor id has a matching `config/sensors.yaml` entry,
  otherwise the id alone with no badge — graceful degradation, never an
  error.
- **Front/rear camera synthetic decision demo** (Phase 61):
  "Generic Exterior Sensing Decision Demo" — a second, genuinely
  different synthetic profile/dataset from the cabin-safety demo, not a
  variant squeezed into it. Four reference sensor ids (`front_rgb`,
  `rear_rgb`, `sim_thermal`, `sim_depth`), four accuracy requirements
  (50%/70%/85%/97%), eight configurations — hand-verified (independently,
  via plain-Python re-derivation with zero `app.domain.decision` imports)
  to produce exactly one minimal sufficient configuration
  (`cfg-front_rgb-rear_rgb-sim_thermal`) and a clean four-point Pareto
  trade-off curve. `front_rgb`/`rear_rgb`/`sim_thermal`/`sim_depth`
  deliberately **not** added to `config/sensors.yaml` — doing so would
  trip the one-sensor-per-modality live-ingestion launch guard
  (`front_rgb`/`rear_rgb` share modality `rgb`;
  `sim_thermal`/`sim_depth` would collide with the already-live
  `thermal`/`depth` entries) — `SensorChips`' graceful no-badge fallback
  covers display instead. A standing "SYNTHETIC DECISION DEMO" banner on
  the Decision tab, gated on the profile's own
  `metadata.synthetic: true`. `scripts/load_decision_demo_data.py` added,
  ending its summary with a `/decision-analysis` call (policy status,
  minimal set, Pareto front) rather than `/coverage`.
- **54 new backend tests** (389 → 443) — the `DecisionPolicy`/
  `PolicyStatus` contract, `evaluate_policy`'s every branch (including
  the completeness-is-always-undetermined case), minimality/dominance
  (subset exclusion, multi-way ties, `None`-handling), the gap engine
  (transitions, condition deltas, direct removals, sensor-addition
  composition), the `/decision-analysis` API's wiring and malformed-
  request handling, the synthetic demo's independent verification, and a
  dedicated Phase 62 robustness pass (a zero-sufficient-configuration
  set, an every-configuration-sufficient set, a three-way disjoint
  minimal-set tie, non-subset identical-coverage dominance, a
  removal-sweep `NO EVIDENCE` case, an N/A-heavy configuration landing
  `undetermined` through the real pipeline, a mandatory-requirement
  failure forcing `insufficient` through the real pipeline, a legacy
  v0.4/v0.5-conditioned profile working unchanged against
  decision-analysis, and two more malformed-request shapes). **No new
  frontend unit tests this release** — the Decision tab's UI was
  live-verified via Playwright against the real running stack at every
  phase instead, same convention as v0.5; frontend suite stays 34/34.
- `docs/decision-support.md` (new); `README.md`, `docs/profiles.md`,
  `docs/coverage.md`, `docs/condition-explorer.md`, `docs/comparison.md`,
  `docs/limitations.md` updated for the decision-support layer.

### Fixed

One real bug, caught by this project's own before-it-ships discipline (a
failing test written to lock in the intended semantics) before the phase
that introduced it was committed:

- **`evaluate_policy`'s initial draft bounded evidence completeness the
  same best-case/worst-case way as coverage.** Because "every N/A
  resolved" always means completeness = 1.0 in *both* hypotheticals, the
  `minimum_evidence_completeness` threshold could never actually fire —
  a 5-pass/0-fail/5-na aggregate against a 0.5/0.95 policy incorrectly
  returned `sufficient` instead of `undetermined`. Fixed by checking
  completeness against the population's real, current N/A count
  directly, before any best/worst-case branching — documented
  permanently as a code comment on `PolicyStatus` itself so the
  reasoning survives past the commit that fixed it.

### Known limitations

`DecisionPolicy.objective` supports only `minimize_sensor_count` (no
cost/power/latency objective exists yet), `mandatory_requirements_must_pass`
is an all-or-nothing population flag rather than a per-requirement scoped
list (`Requirement` still has no `mandatory` field), dominance/Pareto
computation is O(n²) bounded by evaluated-configuration count,
`DecisionAnalysisResponse` is never persisted (recomputed fresh every
call), and sensor-identity/ROS migration for live simultaneous dual-
camera *viewing* remains deferred and unchanged from before v0.6 — this
release's decision-support feature never needed it. Full list:
[docs/limitations.md](docs/limitations.md).

## [0.5.0] — v0.5 condition explorer & evidence analysis

Built phase by phase (Phase 42 through Phase 51), same discipline as
v0.1-v0.4: a 22-question architecture review *before* any code, explicit
self-review checkpoints per phase, nothing merged without running
against a real container. Adds a pure analysis/exploration layer on top
of v0.4's already-computed `RequirementResult`/`GroupCoverage` evidence
— **never re-decides `PASS`/`FAIL`/`N/A`**, only filters, groups,
cross-tabulates, and explains what v0.4 already decided. No v0.1-v0.4
behavior changed; two v0.4.0-tagged files (`evidence.py`, `coverage.py`)
were touched only for behavior-preserving helper extraction, each
re-verified against the full existing test suite plus a live curl check
against real persisted data before and after. Full domain model,
algorithm, and API reference:
[docs/condition-explorer.md](docs/condition-explorer.md).

### Added

- **Filter/facet engine** (`backend/app/domain/analysis.py`):
  `AnalysisFilter` (conditions/group_id/task/status, flat AND-ed
  predicates — no query DSL), `discover_facets` (one pass over
  `profile.requirements[*].conditions`, no evidence needed), and
  `filter_requirement_ids`/`filter_results` — filtering is over a
  requirement's *own declared conditions*, never a resolved session's
  metadata. Missing condition key always excludes, never wildcards.
  Reuses v0.4's exact type-sensitive subset-match rule, extracted from
  `evidence.py`'s private `_values_match`/`matches_conditions` into
  public `values_match`/`conditions_are_subset` (Phase 43) rather than
  reimplementing the bool/int-collision guard a second time.
- **Aggregation + grouping** (Phase 44): `AggregateCoverage` and
  `aggregate_requirement_results` reuse `coverage.py`'s exact
  `status_counts`/`coverage_and_completeness` formulas (promoted to
  public) so a filtered summary can never silently disagree with v0.4's
  own arithmetic. `group_by_condition` (1D breakdown) and
  `cross_tabulate` (2D cross-tab) — a result missing a grouped condition
  key is excluded, never lumped into an "unknown" bucket.
  `failure_breakdown`/`top_failing_groups` reuse the identical recursive
  group-tree walk `compute_configuration_coverage` uses
  (`aggregate_group_tree`, extracted without the "exactly one result per
  requirement" invariant, which doesn't apply to arbitrary filtered
  subsets). `classify_na_reason`/`na_breakdown` pattern-match the real
  free-text reason strings `evidence.py`/`coverage.py` already produce
  — a deliberate, explicitly-stated coupling, guarded by a mandatory
  cross-layer test that constructs every real N/A scenario through the
  actual `select_evidence`/`evaluate_requirement` functions, not
  hand-typed strings.
- **Analysis API** (`backend/app/api/profiles.py`, Phase 45+48):
  `GET /{profile_id}/facets`, `POST /{profile_id}/analysis` — one
  consolidated endpoint (not four separate routes); `group_by`'s length
  (0/1/2) selects filtered-summary/breakdown/cross-tab shape. Reuses
  `/coverage`'s exact evidence-gathering helpers
  (`_resolve_sessions`/`_resolve_configuration_ids`/
  `_compute_requirement_results_by_configuration`, extracted so neither
  route duplicates the other). Each `ConfigurationAnalysis` also carries
  `failure_root` and `na_breakdown`, scoped to the same filtered
  population as everything else on the response. `GET
  /sessions/{id}/profile-usage` (Phase 45) — reverse lookup defined as
  *candidacy* (reuses `matches_conditions` directly), not resolution: a
  session that lost an ambiguity contest still shows up, since "could
  this be evidence" is a different question than "is this the resolved
  evidence."
- **Explorer UI** (`ProfileDetail.tsx` restructured into
  Coverage/Explorer/Failures/Evidence tabs, Phase 46-49): Coverage's
  existing matrix logic moved under a tab unchanged, live-verified
  byte-identical to its pre-v0.5 behavior. `ExplorerPanel.tsx` — dynamic
  filter controls built from `GET .../facets` (no hardcoded condition
  names anywhere), a filtered configuration summary table, a condition
  breakdown section, and a 2D cross-tab section, each fetching via a
  shared `hooks/useAnalysis.ts`. Filter/tab state lives in
  `useSearchParams`, URL-addressable
  (`?tab=explorer&illumination=night&status=fail`), same pattern
  `Comparison.tsx` established. `components/ConditionCrossTab.tsx` — a
  generic row×column grid, reused verbatim for both the single-
  configuration cross-tab and the configuration×condition-value
  "heatmap"; every cell shows its requirement-count denominator (`n=X`)
  always visible, never hover-only. `components/CellDrillDown.tsx` —
  single-match cells reuse `RequirementDrillDown` directly, multi-match
  cells get a plain selectable list, never a second bespoke detail view.
- **Failure + N/A explorer** (Phase 48): `FailuresPanel.tsx` — total
  failure count, a top-failing-groups list, and a failing-requirements
  list. `NABreakdownPanel.tsx` — `na_breakdown` split into "experiment
  never performed" (`no_matching_evidence`) versus "evaluation gap"
  (`ambiguous_evidence`/`missing_metric`/`other`), per the master
  prompt's own framing of why that distinction matters. Every list row
  shows its evidence quality (`matched_samples`/`sample_count`/
  `coverage`) directly alongside its `StatusBadge`, always visible — no
  derived "LIMITED EVIDENCE" badge or threshold, per the architecture
  review's explicit rejection of one.
- **Evidence traceability** (Phase 49): `RequirementDrillDown` enhanced
  to render the full Profile → Group → Requirement → Conditions →
  Evidence → Session → Scenario → Configuration → Prediction source →
  Evaluation result → Sample counts → Acceptance criteria → Result
  chain — real scenario/session *names* (not raw ids, resolved via the
  same `GET /api/scenarios`/`GET /api/sessions/{id}` calls
  `SessionDetail.tsx` already made) and a link to the session's own
  page. Zero new backend fields — every field was already on
  `RequirementResult`/`EvidenceReference`. `SessionDetail.tsx` gained a
  "Used by profiles" section calling `GET .../profile-usage`, listing
  each matching profile and the specific requirement *names* referencing
  this session; zero matches renders a clean explanatory message, not an
  error.
- **Multidimensional synthetic demo** (Phase 50): `cabin-safety-demo.json`
  / `cabin-safety-demo-data.json` extended **in place** (not a second
  profile) with a third condition dimension, `eyewear` (none/glasses) —
  2 new sessions, 2 new requirements, a new "Eyewear Robustness" group.
  Deliberately not a full Cartesian product with `occlusion`. The
  original 4 sessions' ground truth/predictions are byte-identical to
  before — only metadata gained a key. Glasses accuracy targets tell a
  clean story: a mild uniform tax on every configuration except thermal,
  which flips from `pass` to `fail` at night under the *same* threshold
  — a condition dimension changing an outcome, not just a number.
  `scripts/generate_profile_demo_data.py` verified byte-identical across
  runs; `test_profile_demo.py`'s independent verification now covers all
  40 requirement×configuration cells (was 30).
- **80 new backend tests** (309 → 389) — filter/facet engine,
  aggregation/grouping, the analysis API, the failure/N/A explorer, the
  extended synthetic demo's independent verification, and a dedicated
  Phase 51 robustness pass (a zero-condition-dimension profile, an
  undeclared-condition-key filter, mixed boolean/string condition
  values, a 2000-requirement profile's responsiveness, an ordinary
  v0.4-only profile, missing `Session.metadata`, and four `/analysis`
  malformed-request shapes). **No new frontend unit tests this release**
  — v0.5's page-level UI was live-verified via Playwright against the
  real running stack at every phase instead, matching this project's
  existing convention that only pure functions (`format.ts`,
  `groupTree.ts`) get `vitest` coverage; frontend suite stays 34/34.
- `docs/condition-explorer.md` (new); `docs/profiles.md`,
  `docs/coverage.md`, `docs/comparison.md`, `docs/evaluation.md`,
  `README.md`, `docs/limitations.md` updated for the condition-
  exploration layer.

### Fixed

Three real bugs, each caught by this project's own live-verification
discipline (Playwright against the real running stack, or a mandatory
cross-layer test) before the phase that introduced them was committed —
listed here because the catching mechanism is the actual guard, and a
future contributor should be able to see it worked, not just that the
code looks right in hindsight:

- **`classify_na_reason`'s initial rule table** assumed the multi-
  prediction-source ambiguity message contained the word "ambiguous" —
  it doesn't (only the multi-session case does). Caught immediately by
  the mandatory cross-layer test, which constructs the scenario via real
  `select_evidence` calls rather than hand-typed strings.
- **`ConditionCrossTab`'s column headers** showed only the dimension
  name (e.g. "OCCLUSION") spanning every column, with no per-column
  value label ("none"/"partial") underneath — cells were visually
  indistinguishable by column. Caught via a live screenshot during
  Phase 47 verification; fixed by adding a second header row.
- **The Failures tab's top-failing-groups list** included the synthetic
  group-tree aggregation root (`group_id: null`) as if it were a real
  named group. Caught via live hand-verification against the Cabin
  Safety Demo during Phase 48; fixed by excluding `group_id === null`,
  the same exclusion `CoverageMatrix.tsx` already applied.

### Known limitations

`/analysis`'s `group_by` supports at most 2 dimensions (no simultaneous
3+-dimension cross-tab), `classify_na_reason` is coupled to
`evidence.py`/`coverage.py`'s exact free-text reason strings, filter/tab
state lives only in the URL (no saved/named presets), `AnalysisResponse`
is never persisted (recomputed fresh every call, same decision as
`RequirementResult`), reverse session lookup is candidacy — not
resolution, and not a full dependency-graph visualization. Full list:
[docs/limitations.md](docs/limitations.md).

## [0.4.0] — v0.4 requirement profiles & coverage

Built phase by phase (Phase 30 through Phase 40), same discipline as
v0.1-v0.3: an architecture review and 24-question self-review *before*
any code, explicit self-review checkpoints per phase, nothing merged
without running against a real container. Adds a requirement-profile
layer entirely inside the existing `backend` container, consuming v0.2's
`EvaluationResult`s and reusing v0.3's exact multi-source-ambiguity rule
rather than rewriting either — no v0.1/v0.2/v0.3 behavior changed. Full
domain model, algorithm, and API reference:
[docs/profiles.md](docs/profiles.md) / [docs/coverage.md](docs/coverage.md).

### Added

- **Profile domain model** (`backend/app/domain/profiles.py`):
  `EvaluationProfile`, `RequirementGroup` (adjacency-list hierarchy,
  arbitrary depth), `Requirement`, `AcceptanceCriterion`. Conditions are
  an open `dict[str, str | float | bool]` — never a fixed column set —
  proven by tests using domain-unrelated condition keys alongside the
  spec's own examples with zero code differences. No `mandatory`/
  `weight` field (neither has an aggregation semantic defined yet — an
  unused field would invite premature use). `validate_profile` collects
  every structural problem (duplicate ids, dangling references, parent-
  group cycles, blank tasks, non-finite thresholds, an empty profile) in
  one pass, never fails fast.
- **Profile persistence + API** (`backend/app/api/profiles.py`,
  migration `0003_profiles.sql`): one JSON document per profile, not
  normalized into group/requirement tables — a profile is always read
  whole, never queried partially. `POST /api/profiles` (two-layer
  validation — Pydantic structural checks, then `validate_profile` for
  cross-field problems — either both pass or nothing persists; 409 on
  duplicate id), `GET /api/profiles`, `GET /api/profiles/{id}`. No
  update, no delete — profiles are immutable; a changed profile is a new
  id/version.
- **Evidence selection** (`backend/app/domain/evidence.py`): a
  requirement's condition map matches a session iff every key is present
  in `Session.metadata` with an exactly equal, type-sensitive value
  (Python's `1 == True` explicitly guarded against). Zero or multiple
  matching sessions is always `N/A` with a reason — never a silent pick.
  Reuses v0.3's exact prediction-source-ambiguity rule for the
  single-session-multiple-sources case. An explicit `EvidenceBinding`
  overrides discovery (and condition matching) entirely — request-scoped
  only, never persisted.
- **Acceptance engine** (`backend/app/domain/coverage.py`): all five
  operators; `"coverage"` resolves from the same `ComparisonMetrics`
  v0.3 already computes, not a second formula; an unresolvable metric is
  always `na`, never `fail`. Requirement-level status priority: `na` (no
  evidence) → `na` (any unresolvable criterion, even with everything
  else passing — deliberately stricter than "AND over only the known
  criteria") → `fail` (any failed criterion) → `pass`.
- **Coverage engine**: recursive leaf-count group aggregation via the
  group tree's adjacency list — a group's counts are its own
  requirements' counts plus the sum of its children's, never an average
  of child percentages (proven by a dedicated test: a 1-requirement
  100%-coverage group and a 10-requirement 10%-coverage group aggregate
  to ~18.2%, not the naive ~55% average). `requirement_coverage` =
  pass/(pass+fail); `evidence_completeness` = (pass+fail)/total — both
  `None`, never a fabricated 0, when their denominator is 0. No
  profile-level `PASS`/`FAIL`/`INCOMPLETE` status anywhere — raw counts
  and both percentages only, at every level.
- **Profile UI** (`frontend/src/pages/Profiles.tsx`,
  `ProfileDetail.tsx`): list with JSON-paste import (validation errors
  render as one bullet per problem — fixed a real bug during
  verification where two errors were rendering as one malformed run-on
  line), a read-only arbitrary-depth hierarchy tree
  (`frontend/src/groupTree.ts`).
- **Coverage Matrix UI** (`components/CoverageMatrix.tsx`): configurations
  as columns, the requirement tree as rows, `PASS`/`FAIL`/`N/A` cells via
  a new `StatusBadge`. Group summary rows always show raw counts
  alongside *both* coverage percentages together — never one alone.
  Collapsing a group hides its descendants but keeps its own summary
  row visible; search hides only groups with zero matching descendants.
- **Evidence drill-down** (`components/RequirementDrillDown.tsx`): the
  first modal in this codebase. Sourced entirely from fields already on
  `RequirementResult` — no second backend call. Shows the requirement,
  an explicit "why it failed"/"why N/A" reasons block whenever status
  isn't `pass`, the full evidence reference, and every criterion's
  observed/threshold/status — a `PASS`/`FAIL`/`N/A` badge is never shown
  without also showing why.
- **Synthetic reference profile** ("Generic Cabin Safety Demo" —
  deliberately not NCAP or any regulatory framework):
  `examples/profiles/cabin-safety-demo.json` +
  `cabin-safety-demo-data.json`, four sessions (one per
  `illumination`×`occlusion` combination), five configurations, six
  requirements across three groups, every accuracy exact by
  construction. Targets deliberately give each configuration a
  genuinely different pass/fail pattern: `rgb` 1/6 (17%), `depth` 2/6
  (33%), `thermal` 3/6 (50%), `rgb+thermal` 4/6 (67%),
  `rgb+depth+thermal` 6/6 (100%). Independently verified — all 30
  requirement×configuration cells recomputed in plain Python without
  importing any production coverage code, cross-checked against the real
  API, same rigor as the v0.2/v0.3 demo guards.
- **137 new backend tests** (172 → 309), **10 new frontend tests** (24 →
  34) — profile models/validation, persistence/API, evidence selection,
  acceptance engine, coverage aggregation, UI, drill-down, the synthetic
  demo, and a dedicated robustness pass (malformed profiles at the API
  layer, ambiguous prediction sources, unknown metrics, partial evidence
  mixing resolved and N/A requirements in one call, a legacy pre-v0.4
  session with empty `Session.metadata` degrading to N/A cleanly, and
  two profile versions coexisting independently).
- `docs/profiles.md`, `docs/coverage.md` (new); `docs/evaluation.md`,
  `docs/comparison.md`, `README.md`, `docs/limitations.md` updated for
  the requirement-profile layer.

### Fixed

- **Profile import validation errors rendered as one malformed run-on
  bullet** instead of one bullet per problem (`"duplicate group id
  'g1',profile has no requirements"`, no space, single `<li>`) — caused
  by re-splitting an already array-stringified error message on `", "`
  instead of reading the parsed JSON `detail` array directly. Found
  during Playwright verification, fixed with a dedicated fetch in the
  import form that preserves the structured error list.

### Known limitations

Conditions are flat scalars only (no nested condition maps), no
weighted/mandatory-requirement aggregation, `RequirementResult`s are
never persisted (recomputed fresh on every `/coverage` call), an
unfiltered `/coverage` call can surface unrelated configurations from
other standing demo data as all-N/A (correct discovery behavior, but
visually noisy — use `session_ids`/the frontend checkboxes to scope it),
no condition-exploration UI yet (the metadata a later release would need
already exists). Full list: [docs/limitations.md](docs/limitations.md).

## [0.3.0] — v0.3 configuration comparison

Built phase by phase (Phase 20 through Phase 28), same discipline as
v0.1/v0.2: explicit self-review checkpoints per phase, nothing merged
without running against a real container. Adds a comparison layer
entirely inside the existing `backend` container, consuming v0.2's
already-persisted `EvaluationResult`s rather than rewriting anything —
no v0.1/v0.2 behavior changed. Full domain model, algorithm, and API
reference: [docs/comparison.md](docs/comparison.md).

### Added

- **Comparison domain model** (`backend/app/domain/models.py`):
  `PairwiseComparison`, `ComparisonValidity`, `ComparisonSide`,
  `ComparisonMetrics`, `MetricDelta`. `reported` and `common_set` share
  one `ComparisonSide` shape and are always both computed together — no
  caller-selected mode. `ComparisonValidity` enforces its own invariant
  at construction (`status != 'valid'` requires a non-empty `reasons`),
  so a silently-flagged-but-unexplained warning can't happen even by
  omission. `baseline_source_id`/`candidate_source_id` were added after
  an expanded self-review found the original shape resolved a source
  internally but never carried it onto the output, breaking full
  evidence traceability. No `Experiment` entity (a comparison request's
  own fields already are what one would hold) and no persistence
  (recomputed fresh from already-persisted evidence on every call) —
  both decisions recorded directly in the module docstring.
- **Comparison engine** (`backend/app/domain/comparison.py`): pure
  functions, zero `fastapi`/`sqlite3`/`rclpy` imports.
  `classify_relationship` (`direct_addition`/`direct_removal`/`general`
  via plain `sensor_ids` set difference, never a `configuration_id`
  string parse); `compute_metric_delta` (absolute/relative, `None` on
  either missing input or a zero baseline — never a `ZeroDivisionError`);
  common-set intersection by `GroundTruth.id` on already-matched pairs
  (deliberately not a re-run of `match_by_timestamp` on a subset, which
  isn't guaranteed to reproduce the original match); `assess_validity`
  (invalid on zero common samples or self-comparison, warning on a low
  common-sample count or large coverage difference — both thresholds
  heuristic and documented as such).
- **Comparison API** (`backend/app/api/comparison.py`): `GET
  .../configurations` (sensor_ids, distinct source_ids, nullable sample
  counts before evaluation), `POST .../compare` (one derivation route —
  `mode`, a separate `/ablation`, and an `/evaluate`-then-`/coverage`
  split were all considered and rejected). A configuration with more
  than one distinct prediction source for a task is a hard 422 listing
  every available source — never a guess, never a silent average.
- **Ablation as a comparison view, not a separate concept.** Baseline =
  the full configuration; the frontend filters the same `/compare`
  response by `relationship == 'direct_removal'`. Zero new domain code,
  zero new endpoint — proven by a dedicated test asserting `GET
  .../ablation` is a 404.
- **Comparison UI** (`frontend/src/pages/Comparison.tsx`): session/task/
  baseline pickers round-tripped through URL search params (so Session
  Detail's "Compare configurations →" link, shown only when ≥2
  configurations have results, can pre-fill state); a configuration
  comparison table; Sensor Addition, Ablation, and General Comparison
  card sections sharing a `ComparisonMetricTable` component; a metric
  selector sorting all three sections by delta magnitude. Three
  deliberately distinct formatters (`formatDelta`/`formatDeltaPp`/
  `formatRelativeDelta`) keep absolute deltas, percentage-point deltas,
  and relative-percentage deltas — three different quantities — from
  ever being confused at a call site, the exact mistake the v0.3
  specification warned against.
- **Expanded synthetic demo** (`scripts/generate_demo_data.py`,
  `examples/evaluation/classification-demo.json`): grown from three
  single-sensor configurations to all seven non-empty subsets of `{rgb,
  depth, thermal}`, accuracy targets forming a clean lattice (single <
  pair < all three) so every comparison in the demo is `VALID` by
  construction and no sensor removal ever "helps." Cross-checked by a
  test that hand-verifies the three direct-removal-from-full accuracy
  deltas (−7pp/−4pp/−2pp) through the real `/compare` API.
- **172 new backend tests**, **24 new frontend tests** — comparison
  models, engine, API, ablation-reuse, UI, expanded-demo, and a
  dedicated robustness pass (zero-ground-truth tasks, the N/A/no-
  divide-by-zero path through the real API, five malformed-request
  shapes, and a legacy pre-v0.3 single-configuration session comparing
  cleanly — proving v0.3 added no migration or field an old session
  would be missing).
- `docs/comparison.md` (new); `docs/evaluation.md`, `README.md`,
  `docs/limitations.md` updated for the comparison layer.

### Fixed

- **Self-comparison wasn't actually rejected.** The Phase 20 architecture
  review specified that comparing a configuration against itself must
  always be `invalid`, but Phase 21's engine never implemented the
  check — found while building the API layer on top of it, fixed at
  the correct layer (`compare_configurations`) with both a domain-level
  and an API-level regression test.
- **Float-precision test failures** (`(1.0 - 0.8) * 100 ==
  19.999999999999996`, not `20.0`) — fixed with `pytest.approx` on
  computed values; exact-equality assertions on raw literal values were
  left as-is since those round-trip exactly through JSON.

### Known limitations

No matched-label-set-divergence or reported-vs-common-set-divergence
validity checks (both documented gaps, not silent omissions), a
comparison spans exactly one session, no comparison history (recomputed
fresh, nothing persisted). Full list:
[docs/limitations.md](docs/limitations.md).

## [0.2.0] — v0.2 evaluation core

Built phase by phase (Phase 10 through Phase 19), same discipline as
v0.1: explicit self-review checkpoints per phase, nothing merged without
running against a real container. Adds an evaluation layer entirely
inside the existing `backend` container — no new service, no v0.1
behavior changed. Full domain model, algorithm, and API reference:
[docs/evaluation.md](docs/evaluation.md).

### Added

- **Evaluation domain model** (`backend/app/domain/models.py`): `Session`,
  `Scenario`, `GroundTruth`, `Prediction`, `EvaluationResult` as plain
  Pydantic models with zero `fastapi`/`sqlite3`/`rclpy` imports.
  `GroundTruth`/`Prediction.value` is a generic dict, not a
  classification-specific field, so detection/regression can reuse the
  same shape later without a schema rewrite. `configuration_id` is
  derived from sorted `sensor_ids`, never chosen independently, which
  keeps sensor identity (`sensor_ids`) and prediction-source identity
  (`source_id`) from ever collapsing into one field.
- **SQLite persistence** behind a repository boundary
  (`backend/app/persistence/`) — plain versioned `.sql` migrations, no
  migration framework, for five tables. Backed by a named Docker volume
  (`backend-data`), survives a container rebuild.
- **Prediction/ground-truth ingestion API**: scenario/session CRUD,
  `POST .../ground-truth/batch` and `.../predictions/batch` with
  per-item partial-failure reporting (one malformed item doesn't reject
  an otherwise-valid batch), a primary-key-collision fallback for
  retried/duplicate ids.
- **Matching + classification metric engine**
  (`backend/app/domain/matching.py`, `metrics.py`): sorted two-pointer
  timestamp association within a configurable tolerance; accuracy,
  macro/micro precision/recall/F1, and a dynamically-labeled confusion
  matrix (never hardcoded to binary). An unavailable metric (zero
  denominator) is always `None`/`N/A`, never a fabricated `0.0` — the
  rule most likely to get silently violated, so it's tested at every
  layer: engine, API, and frontend formatter.
- **Evaluation API**: `POST .../evaluate` (discovers configurations from
  ingested predictions when not named explicitly, persists one
  `EvaluationResult` per configuration), `GET .../evaluation`, and
  `GET .../timeline` (per-sample correct/incorrect/missing/unmatched
  detail, computed fresh on every call rather than persisted — the
  aggregate result stays a pure aggregate).
- **Sessions and Session Detail UI** (`frontend/src/pages/`), routed with
  `react-router-dom` (the only new frontend dependency this release):
  session list with a working create-session form, scenario/
  configuration/data-coverage sections, a comparison table, a dynamic
  confusion matrix, and a lightweight timeline strip — all derived from
  real API data, nothing hardcoded.
- **Synthetic reference demo**
  (`examples/evaluation/classification-demo.json`,
  `scripts/generate_demo_data.py`, `scripts/load_demo_data.py`): 100
  deterministic ground-truth samples, three prediction configurations at
  exact-by-construction accuracies (90%/83%/87%) landing in visibly
  different bands. Every layer marks itself synthetic — API metadata,
  scenario tags, and a standing amber banner on the session detail page —
  so it can never be mistaken for a real measurement. Cross-checked by a
  backend test that independently recomputes expected accuracy from the
  raw JSON in plain Python (no `app.domain` import) against a real
  `POST /evaluate` response.
- **108 new backend tests**, **13 new frontend tests** (all pure-function
  or API-level — no ROS/RTSP mocking needed for any of it, same
  philosophy as v0.1's test suite).
- `docs/evaluation.md` (new); `docs/architecture.md`,
  `docs/configuration.md`, `docs/limitations.md` updated for the
  evaluation layer.

### Fixed

Real bugs found during verification, not just features shipped clean —
several caught specifically because of this project's rule that nothing
ships without running against a real container or a real browser, not
just passing `tsc`/pytest:

- **Cross-thread SQLite crash under real concurrent requests.** A single
  connection shared via `app.state` (the first design) raised
  `sqlite3.ProgrammingError: SQLite objects created in a thread can only
  be used in that same thread` — FastAPI's sync generator dependencies
  are not guaranteed to run on the same worker thread as the endpoint
  body using the connection they yield. `TestClient`'s synchronous
  single-portal dispatch never reproduced this; a live browser hitting a
  real running server did. Fixed with a fresh connection per request
  (`check_same_thread=False`, safe since a connection is still only ever
  used by one request at a time) plus a deterministic regression test
  using a real thread directly, not relying on FastAPI's own scheduling
  to trigger the failure.
- **Missing SPA fallback in nginx.** Direct navigation to `/sessions` (a
  client-side route added this release) 404'd in the production build —
  confirmed via `curl` before and after. Fixed with
  `try_files ... /index.html` in a dedicated `frontend/nginx.conf`.
- **Latent IPv6 healthcheck bug in nginx**, surfaced (not caused) by
  adding that same `nginx.conf`: `wget http://localhost:80` failed with
  `Connection refused` because nginx never binds `[::]:80`, and
  BusyBox's resolver picked the `::1` `/etc/hosts` entry first. Confirmed
  this predates this release entirely — the *unmodified* stock
  `nginx:alpine` config reproduces it identically — rather than being
  introduced by the new config. Fixed with a dual-stack `listen`.
- **`EvaluationPanel`'s task selector got permanently stuck on `""`.**
  `useState(tasks[0] ?? "")` only read the `tasks` prop once, before the
  parent page's async ground-truth fetch had populated it. Fixed with a
  `useEffect` that resyncs the selected task whenever `tasks` changes.
- **`repository.py`'s `EvaluationResult` was missing `tolerance_ms`** in
  the first cut of the schema — a result's matched/unmatched split isn't
  reproducible or auditable without recording what tolerance produced
  it. Added before any real data depended on the old shape (migration
  `0002`).
- **A hand-computed test expectation was wrong, not the code.** Writing
  `test_precision_undefined_for_never_predicted_class`, a manually
  worked-out macro-precision value missed counting cross-class false
  positives. The test failed; the expectation got corrected, not the
  implementation — recorded here because it's a real example of a test
  catching the test author, not just the code.
- **`CHANGELOG.md` was missing a `[0.1.1]` entry** despite that release's
  own notes saying "full details: CHANGELOG.md" — added retroactively
  below, discovered while preparing this entry.

### Known limitations

Classification-only, `tolerance_ms` not evidence-based (no shared clock
to measure against, unlike the ROS sync default), synchronous
`/evaluate` with no result history, no file-import API endpoint. Full
list: [docs/limitations.md](docs/limitations.md).

## [0.1.1] — release hardening

No new product functionality — a full audit-and-hardening pass on top of
v0.1.0, verified against the same "run it for real, don't just claim it"
rule as everything else in this project.

### Fixed

- Dead historical launch files and orphaned placeholder nodes removed.
- `rtsp_ingestion_node`'s `rtsp_url` no longer defaults to a
  simulator-specific host — required explicitly now, fails clearly if
  missing.
- Subprocess lifecycle hardening in the MJPEG relay (`stdin=DEVNULL`,
  explicit `stdout.close()`).
- FastAPI backend: replaced the deprecated `@app.on_event('startup')`
  with `lifespan`, added graceful `rclpy.shutdown()` on backend shutdown
  (previously nothing called it).
- Multi-stage `ros2_ws` Docker build — measured, not assumed: negligible
  image-size impact (the real weight is `cv_bridge`'s opencv-dev
  dependency chain, not build tooling), kept for the correctness win
  (no dangling-symlink risk in a shipped image) rather than a size win.
- Frontend sensor list now retries whenever the WebSocket (re)connects,
  not just once on page load.
- `frontend/tsconfig.app.json`: TypeScript `strict` mode was never
  actually enabled in the default Vite-generated config — the code was
  already clean, so turning it on was a zero-cost gap closure.

### Added

- 32 new automated tests across frontend (Vitest), backend (pytest), and
  ROS pure-logic modules (`sensor_config.py`, `sync_logic.py` — zero
  `rclpy` imports, plain pytest) — deliberately not mocking the entire
  ROS/RTSP world; see [docs/development.md](docs/development.md).
- Real 30-minute memory soak test: no monotonic growth trend observed in
  `ros`, `backend`, or `frontend` containers, across an injected full
  RTSP outage/recovery and an injected ingestion-process kill/recovery.
- New docs: `docs/configuration.md`, `docs/diagnostics.md`,
  `docs/development.md`, `docs/limitations.md`;
  `docs/architecture.md`'s diagram redone with explicit labeled
  transport planes.
- README rewritten to a clean pitch/architecture/quick-start structure;
  the detailed phase-by-phase v0.1 development history moved into this
  file.

## [0.1.0] — v0.1 release

Built phase by phase (Phase 0 through Phase 9). Ingestion, synchronization,
diagnostics, and a dashboard — no perception, fusion, ML, or ground-truth
evaluation, by design (see [docs/limitations.md](docs/limitations.md)).

### Added

- **Config-driven RTSP ingestion** (`config/sensors.yaml`): one generic
  `rtsp_ingestion_node`, instantiated N times from config — no per-sensor
  code. Adding a sensor is a config entry.
- **ROS 2 Humble in Docker** (`ros` container, arm64), cross-process and
  cross-*container* DDS pub/sub verified live, not assumed.
- **Per-sensor self-reported diagnostics** (`connection_state`,
  `fps_received`, `reconnect_count`, etc.) and **global system diagnostics**
  (CPU/RAM/uptime/connected count), both on `/multisens/diagnostics`. Every
  field is real or explicitly `"unavailable"` — see
  [docs/diagnostics.md](docs/diagnostics.md).
- **Cross-sensor timestamp synchronization** (`multisens_sync`) via
  `message_filters.ApproximateTimeSynchronizer` over a lightweight
  `sensor_msgs/TimeReference` companion topic (`frame_stamp`) rather than
  the full image topic — see the throughput bug below for why. Default
  `tolerance_ms=25.0` set from measured real skew (0.2–3.5ms baseline on the
  reference setup), not guessed.
- **FastAPI backend** (`backend` container, separate from `ros`): REST +
  WebSocket bridge translating ROS diagnostics into plain JSON
  (`ros_bridge.py` is the only file that imports a ROS message type), plus
  an independent MJPEG video relay (ffmpeg `mpjpeg` muxer) that never
  touches ROS/DDS.
- **React/TypeScript/Vite/Tailwind dashboard** (`frontend` container,
  joined `docker-compose.yml` only once there was a UI to serve): live
  video panels, PHYSICAL/SIMULATED badges, sync/system health.
- **Disconnect/reconnect handling**: per-node RTSP reconnect loop, verified
  under a real single-sensor outage (not just "kill everything at once").
- **ROS process respawn** (`respawn=True` on every launch `Node`): recovers
  from a *process* crash, not just a dropped RTSP connection.
- **Backend stale-data expiry**: `/api/status` excludes any sensor/system/
  sync entry not updated in the last 5s, rather than repeating frozen data
  forever.
- **Automated tests**: frontend (Vitest), backend (pytest against a real
  `RosBridge`/FastAPI `TestClient`, no live ROS graph needed), and ROS
  pure-logic (`sensor_config.py`, `sync_logic.py` — zero rclpy imports,
  plain pytest). Deliberately not a full ROS/RTSP mock — see
  [docs/development.md](docs/development.md).
- Standing docs: `docs/architecture.md`, `docs/topics.md`,
  `docs/configuration.md`, `docs/diagnostics.md`, `docs/connector-api.md`,
  `docs/development.md`, `docs/limitations.md`.

### Fixed

Real bugs found during verification, not just features shipped clean:

- **Sync node measuring its own processing lag, not real skew.**
  Subscribing directly to `image_raw` (~900KB/frame) made
  `synchronized_group_rate_hz` sit near 0–3Hz against a true ~30Hz rate,
  with reported skew swinging 1ms–460ms — an artifact of the subscriber
  falling behind, not sensor behavior. A multi-threaded executor only
  partially helped (CPython's GIL doesn't parallelize CPU-bound
  deserialization). Fixed by adding the `frame_stamp` companion topic
  (header only, no pixels) for the sync node to subscribe to instead.
- **`message_filters` silently matching nothing.** The first attempt at
  the lightweight topic used a bare `std_msgs/Header`, which produced
  exactly 0 synchronized groups, ever, with no error —
  `ApproximateTimeSynchronizer` reads `msg.header.stamp`, which needs a
  *nested* header. Switched to `sensor_msgs/TimeReference`.
- **System diagnostics double-counting itself.** `system_diagnostics_node`
  subscribed to the same topic it publishes to, received its own "system"
  status back, and briefly reported `connected_sensor_count: 4` against a
  `total_sensor_count: 3`. Fixed by filtering to known sensor hardware_ids
  only.
- **Backend showing a dead sensor as alive forever.** With an ingestion
  node's *process* killed (not just its RTSP source), `/api/status` kept
  reporting it `"connected"` with a frozen-fresh `fps_received` — nothing
  was ever going to arrive to correct it, and `ros_bridge.py` was the one
  place that hadn't replicated the staleness-watchdog pattern already used
  in `system_diagnostics_node`/`sync_status_node`. Fixed with a 5s
  staleness expiry in `RosBridge.snapshot()`.
- **No recovery path for a process-level crash.** A killed ingestion node
  stayed dead forever — its own reconnect loop only covers the RTSP
  *connection* dying, not its own process dying. Fixed with `respawn=True`
  on every launch `Node` (ROS 2 launch's own mechanism).
- **Frontend rendering `"unavailablems"`.** Sync offsets and per-sensor
  latency/last-frame-age fields string-concatenated the `"unavailable"`
  sentinel with a hardcoded `"ms"` suffix, because the original code only
  checked JS truthiness. Fixed once with a shared `formatMs()` helper.
- **`ROS_DOMAIN_ID`/`RMW_IMPLEMENTATION` duplication.** Previously hardcoded
  separately in `ros2_ws/Dockerfile` and `docker-compose.yml`. Single-sourced
  in a repo-root `.env`, referenced by both services.
- **Dead historical launch files and placeholder nodes** (`phase1_graph.launch.py`,
  `phase2_rgb.launch.py`, `placeholder_talker.py`, `placeholder_listener.py`)
  removed during the v0.1 release audit — kept during development as
  harmless artifacts, not appropriate to ship.
- **Simulator-specific default baked into a "generic" node.**
  `rtsp_ingestion_node`'s `rtsp_url` parameter defaulted to
  `rtsp://host.docker.internal:8554/rgb` — a host- and simulator-specific
  value with no business being a default in a node meant to work with any
  RTSP source. Now required explicitly, fails clearly if missing.
- **`ros2_ws` image shipping build-only tooling.** `python3-colcon-common-extensions`
  (needed to *build* the workspace, not to run it) was present in the final
  image. Converted to a multi-stage build; the runtime stage never installs
  it. Also dropped `--symlink-install` for the production build — a
  self-contained `install/` is more correct for a distributed image than
  symlinks pointing back into a `src/` tree the final image no longer ships.
  Measured, not assumed: this made almost no difference to final image size
  (490,318,679 → 490,321,039 bytes, effectively unchanged) — the image's
  real weight is `ros-humble-cv-bridge`'s opencv-dev dependency chain, a
  genuine runtime need, not colcon tooling. Kept for correctness (no
  dangling-symlink risk in a shipped image, cleaner build/runtime
  separation), reported honestly as not a size win.
- **Frontend sensor list never retried.** `GET /api/sensors` was fetched
  once on mount; if the backend wasn't ready yet at page load, the
  dashboard would show "failed to load" forever without a manual reload,
  even though the WebSocket itself reconnects fine. Now refetches whenever
  the WebSocket (re)connects.
- **`video_relay.py` subprocess lifecycle hardening.** Added `stdin=DEVNULL`
  and explicit `stdout.close()` on the ffmpeg subprocess — not a known bug,
  but tightens a real gap found during the release audit.
- **Deprecated FastAPI startup hook.** `@app.on_event('startup')` replaced
  with the `lifespan` context manager, which also now calls
  `rclpy.shutdown()` on backend shutdown (previously nothing did).
- **TypeScript `strict` mode was never actually enabled** in the default
  Vite-generated `tsconfig.app.json` — the code happened to already be
  strict-clean, so turning it on was a zero-cost gap closure, not a fix
  requiring code changes.

### Known limitations

See [docs/limitations.md](docs/limitations.md) for the full, current list —
scope boundaries, environment-specific assumptions, and honestly-reported
gaps (no CI, soak testing is real but time-bounded, single-dashboard-user
scale only).
