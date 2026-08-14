# Data Provenance & Evidence Honesty Contract

Every other doc in this project describes one layer's domain model. This
one is different: it's a single, cross-cutting index of **how MultiSens
knows what it knows** - where a number comes from, how confidently it
can be trusted, and what "no data" looks like versus "the data says
zero." It doesn't introduce new behavior; it names and cross-references
a discipline that's already enforced, layer by layer, throughout the
codebase, so a reader (or an auditor) can check the whole system's
honesty posture from one place instead of piecing it together from six
different files.

## Why this document exists

MultiSens is built to be trustworthy about the limits of its own data,
not just about what it reports when things go well. That posture shows
up as a set of small, repeated rules - never fabricate a value, always
report absence explicitly, never blend two different kinds of evidence
into one number, never claim causation from correlation. Each rule is
enforced in exactly one place in the code and tested there; this
document is the map, not a second implementation.

## The four provenance dimensions

MultiSens data carries provenance along four largely independent axes.
A single number - say, one cell in a coverage table - can be described
completely only by naming all four:

| Axis | Question it answers | Where it's decided |
|---|---|---|
| **Source authenticity** | Did this come from a real sensor or a simulated one? | `source_type: physical \| simulated` (`config/sensors.yaml`, v0.1) |
| **Evaluation reality** | Is this ground truth/prediction real experiment data or a synthetic demo? | `metadata.synthetic: true` on every demo profile/session (v0.2+) |
| **Measurement confidence** | Was this value actually measured, human-declared, computed, or missing? | `ResourceQuality` (v0.7) - see [resources.md](resources.md#resourcequality-four-values-never-a-fabricated-number) |
| **Decision confidence** | Is this judgment fully resolved, or could more evidence still change it? | `PASS`/`FAIL`/`N/A` and `PolicyStatus` (v0.4/v0.6) |
| **Evaluator identity** | Which comparison logic produced this number - classification, detection, or regression? | `EvaluationResult.evaluator_type`, self-describing on every row (v0.8) - see [evaluators.md](evaluators.md) |

None of these axes imply each other. Physical-source data can still be
part of a synthetic demo profile (deliberately not the case in this
project's own reference demos, but nothing in the domain model would
stop it). A `measured` resource value can sit right next to a
`declared` one for the same metric without reconciliation. A `PASS`
result can come from either real or synthetic evidence - the requirement
engine doesn't know or care; that distinction lives entirely in the
`synthetic` flag on the profile/session, reported alongside, never
inferred from the result itself.

## Source authenticity: physical vs. simulated (v0.1)

Every sensor in `config/sensors.yaml` declares `source_type: physical`
or `source_type: simulated`, and that value flows untouched through
diagnostics, the ROS graph, and the dashboard's badges. In the reference
setup, `depth`/`thermal` are FFmpeg pseudocolor transforms of a real RGB
feed - visually similar to real depth/thermal output, but never claimed
to be a physical measurement anywhere in the system. See the
[README](../README.md#physical-vs-simulated--a-hard-distinction).

## Evaluation reality: synthetic vs. real evidence (v0.2+)

Every demo profile and dataset shipped with this project carries
`metadata.synthetic: true`, rendered as a standing banner wherever that
profile appears in the UI (e.g. the Decision tab's "SYNTHETIC DECISION
DEMO" banner, see [decision-support.md](decision-support.md#synthetic-decision-demo)).
The distinction is load-bearing, not cosmetic: RideSafe's and
PropertyWatch's own descriptions (v0.7) explicitly state their accuracy
and resource numbers are synthetic and demonstrate functionality only,
never a claim about real hardware performance - see
[deployment-tradeoffs.md](deployment-tradeoffs.md#ridesafe-and-propertywatch-two-worked-examples).

**Every synthetic dataset in this repo is independently re-derivable.**
Each demo ships a deterministic generator script (byte-identical output
across runs, fixed random seeds) and a dedicated backend test file that
recomputes the demo's headline numbers from scratch - nearest-timestamp
matching, plain Python set/dict logic, **zero imports from
`app.domain`** - then cross-checks that against the real running API.
This is the actual audit trail for any number this project claims: not
"trust the code," but "here is a second, independent computation that
agrees with it." See `test_synthetic_demo.py`, `test_profile_demo.py`,
`test_decision_demo.py`, `test_ridesafe_demo.py`,
`test_propertywatch_demo.py`, and (v0.8) `test_ridesafe_detection_demo.py`/
`test_propertywatch_detection_demo.py`/`test_robot_drone_demo.py` - each
of which reimplements IoU/greedy-object-matching or MAE/RMSE/bias/median
from scratch, with zero imports from `app.domain.detection`/
`app.domain.regression`, the same discipline as every classification
demo's own zero-`app.domain`-import recomputation.

## Measurement confidence: `ResourceQuality` (v0.7)

`measured` / `declared` / `estimated` / `unavailable` - the full
contract lives in [resources.md](resources.md#resourcequality-four-values-never-a-fabricated-number).
The rule that matters most for provenance: `value is None` **iff**
`quality == 'unavailable'`, enforced by validation in both directions.
A summary spanning rows of more than one quality tier reports `'mixed'`
rather than picking one - see
[resources.md](resources.md#resource-summaries-meanmedianp95minmax-honest-about-quality).

## Decision confidence: N/A is not a third kind of failure

`RequirementResult.status` is `PASS`/`FAIL`/`N/A` (v0.4) - `N/A` means
"no evidence exists to decide this yet," structurally different from
`FAIL` ("evidence exists and it didn't meet the bar"). This distinction
propagates all the way up: `evaluate_policy` (v0.6) bounds an
undetermined outcome via best-case/worst-case N/A-resolution hypotheses
rather than guessing, and can only ever return `undetermined` (never
`insufficient`) for a pure completeness shortfall, because more testing
can always still resolve it. See
[decision-support.md](decision-support.md#policystatus-three-values-never-a-binary-goodbad).

Resource-constraint `N/A` (v0.7) is a **different**, non-analogous
concept - a missing resource measurement has no "will resolve later"
property the way an unresolved evaluation N/A does, so
`evaluate_resource_qualification` deliberately does not use the same
bounding math. See
[deployment-tradeoffs.md](deployment-tradeoffs.md#qualification-a-direct-3-state-map-deliberately-not-evaluate_policys-bounding)
for why applying one's logic to the other would be a category error, not
a consistency win.

## The cross-cutting rules, and where each is enforced

- **Never fabricate a value.** A missing measurement is `None`/
  `unavailable`/`N/A`, reported explicitly - never `0`, never an
  average that quietly excludes what's missing. Enforced per-layer:
  `RequirementResult` (v0.4), `evaluate_policy` (v0.6),
  `ResourceObservation`'s value/quality cross-validation (v0.7),
  `EvaluatorOutput.metrics`'s `MetricValue` (`float | None`) uniform
  across all three v0.8 evaluators - a detection configuration with zero
  TP/FP has `precision: None`, never a fabricated `0.0`, and that `None`
  survives all the way through `/compare`'s metric deltas unchanged.
- **Never silently drop evidence.** A configuration named but never
  evaluated is reported `NO EVIDENCE`, not omitted (v0.6's
  `/decision-analysis`, v0.7's `/tradeoffs` - including the v0.7
  robustness fix ensuring resource evidence for such a configuration is
  still attached, not dropped just because decision evidence is
  missing).
- **Never blend independent evidence into one score.** No
  `importance_score`/`overall_efficiency_score`/`deployment_score`
  anywhere in this project's domain model - v0.6's decision layer and
  v0.7's trade-off layer both expose many small, structured fields
  instead. Grep-verified after every phase that could plausibly
  introduce one; see
  [decision-support.md](decision-support.md#no-causal-language-no-universal-importance-score-ever)
  and [deployment-tradeoffs.md](deployment-tradeoffs.md#no-combined-score-anywhere-ever).
- **Never claim causation from correlation.** "Configuration B measured
  +0.07 F1 higher than A," never "sensor X caused a +7% improvement" -
  established in v0.3's comparison layer, carried forward unchanged
  through v0.5's condition breakdowns, v0.6's gap analysis, and v0.7's
  resource deltas ("candidate used +5.1 Mbps more than baseline," never
  "cost caused by the added sensor"). See
  [comparison.md](comparison.md#non-causal-by-design).
- **Never merge two evidence sources without saying so.** A `declared`
  resource value coexists with a `measured` one for the same metric
  without auto-reconciliation (v0.7) - the same posture `EvidenceBinding`
  established in v0.4 for ambiguous multi-source evaluation evidence.

## Design provenance: the v0.9 Plugin SDK

This document's four dimensions are about *data* provenance - where a
number came from. One more question is worth answering explicitly for
v0.9's Plugin SDK specifically, since it's the first layer whose own
*design* - not any data it produces - is a new extensibility surface:
**where did this design come from?**

`multisens_sdk`'s shape - a small, closed set of typed `Protocol`
contracts (`SensorConnector`/`PredictionConnector`/`GroundTruthConnector`/
`EvaluatorPlugin`/`ResourceCollector`), Python entry-point discovery
(`importlib.metadata.entry_points`), a `PluginDescriptor`/
`MULTISENS_PLUGIN_API_VERSION` identity/versioning scheme, and a trusted-
code (not sandboxed) execution model - is built entirely from two
sources: **this project's own existing generic architecture**
(`EVALUATOR_REGISTRY`'s v0.8 extensibility pattern, generalized to four
more plugin types the same way; the data-plane/control-plane split
`video_relay.py` already established, reused rather than reinvented -
see [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video))
and **standard Python
packaging conventions** (`pyproject.toml` entry points - the same
mechanism `pytest`, `flake8`, and hundreds of other widely-used Python
tools use for their own plugin discovery, not a MultiSens invention).

No proprietary system, employer codebase, or non-public design was
consulted or reused in any form - verified explicitly during the Phase
92 architecture review before any v0.9 code was written, and re-verified
during Phase 105's robustness/security review. `docs/plugin-sdk.md`
itself is the full decision record.

## How to verify any specific claim

If a number in this project looks surprising, the fastest way to check
it is the same path this project's own development process uses:

1. Find the demo/dataset it came from and read its generator script
   (`scripts/generate_*_demo_data.py`) - every synthetic value is
   constructed from an explicit target, never randomly plausible.
2. Read that demo's independent-verification test
   (`backend/tests/test_*_demo.py`) - it recomputes the same number a
   different way and asserts equality against the real API response.
3. For a resource number specifically, check the observation's own
   `quality`/`source` fields (via `GET /api/sessions/{id}/resource-
   observations`) - `source` names exactly which formula or `psutil`
   call produced it, never an opaque black box.

Nothing in this project's claimed numbers depends on trusting a
narrative description over the data itself - the data always carries
enough provenance to check the description against it.
