# Requirement profile example data

## `cabin-safety-demo.json` + `cabin-safety-demo-data.json`

A deterministic, **entirely synthetic** reference profile and dataset for
exercising the v0.4 requirement-profile/coverage workflow and the v0.5
condition-exploration workflow (facets, filtering, breakdown, cross-tab,
failure/N/A explorers, traceability) end to end.

**`cabin-safety-demo.json`** is the profile document itself (the exact shape
`POST /api/profiles` accepts): "Generic Cabin Safety Demo", version `1.0`,
four generic requirement groups (`Alertness`, `Visibility Robustness`,
`Occupancy`, `Eyewear Robustness`), eight requirements, each keyed to a
`presence` task and an `illumination`/`occlusion`/`eyewear` condition
triple.

**`cabin-safety-demo-data.json`** is the underlying evidence: one shared
scenario and **six sessions**. The original four cover one session per
`(illumination, occlusion)` combination (`day`/`none`, `day`/`partial`,
`night`/`none`, `night`/`partial`), each with `eyewear: none`. Two more
(Phase 50, v0.5) hold occlusion at `none` and vary `eyewear` instead
(`day`/`glasses`, `night`/`glasses`) - deliberately **not** a full
`(illumination x occlusion x eyewear)` Cartesian product, since "partial
occlusion AND glasses" would conflate two visibility-degrading factors into
one meaningless combination. Every session has 100 `presence` ground-truth
samples and predictions from five configurations (`rgb`, `depth`,
`thermal`, `rgb+thermal`, `rgb+depth+thermal`). Conditions live on
`Session.metadata`, not a new table - see the v0.4 architecture review
(issue #31, Q8) for why that's the right binding point. Because every
requirement in this profile names all *three* condition keys, exactly one
session ever matches each requirement - there is no evidence ambiguity
anywhere in this demo.

## Why these numbers

Every accuracy value below is **generated, not measured** - see
[`scripts/generate_profile_demo_data.py`](../../scripts/generate_profile_demo_data.py)
(a fixed set of ground-truth indices is deliberately mislabeled per
session/configuration pair, so accuracy is exact, not a probabilistic
approximation - same technique as `scripts/generate_demo_data.py`). They
are deliberately constructed so each configuration has a genuinely
**different** pass/fail pattern across the profile's eight requirements, not
just a different total:

| Configuration | day/clear | day/occluded | night/clear | night/occluded | day/glasses | night/glasses |
|---|---|---|---|---|---|---|
| `cfg-rgb` | 92% | 75% | 60% | 45% | 90% | 58% |
| `cfg-depth` | 88% | 68% | 88% | 68% | 87% | 87% |
| `cfg-thermal` | 78% | 80% | 85% | 78% | 70% | 75% |
| `cfg-rgb-thermal` | 94% | 88% | 90% | 82% | 91% | 86% |
| `cfg-depth-rgb-thermal` | 97% | 93% | 95% | 90% | 95% | 92% |

The story these numbers tell: `rgb` favors daylight and struggles at night
(camera-based); `depth` is illumination-invariant but occlusion-sensitive
(a physical-obstruction sensor doesn't care about light, but does care
about being blocked); `thermal` is both illumination-invariant and more
occlusion-tolerant than `depth`; `rgb+thermal` fuses complementary
strengths; `rgb+depth+thermal` dominates everywhere. The `glasses` columns
(Phase 50, v0.5) add a third, independent dimension: a mild, roughly-uniform
tax on every configuration except `thermal`, which takes a much larger hit
(glasses lenses attenuating the thermal signature around the eyes) - large
enough at night to flip `cfg-thermal` from **pass** (night/clear, 85% vs.
the night baseline's 85% threshold) to **fail** (night/glasses, 75% vs. the
*same* 85% threshold on `req-night-glasses`) - a condition dimension
changing a pass/fail outcome, not just shifting a number.

Against the profile's eight requirements (two accuracy-≥85% baselines, two
occlusion requirements at 80%/75%, two stricter 95% bars reusing the
baseline conditions, and two glasses variants of the baselines at the same
85% bar) this produces:

| Configuration | Requirements passed | Coverage |
|---|---|---|
| `cfg-rgb` | 2 / 8 | 25% |
| `cfg-depth` | 4 / 8 | 50% |
| `cfg-thermal` | 3 / 8 | 38% |
| `cfg-rgb-thermal` | 6 / 8 | 75% |
| `cfg-depth-rgb-thermal` | 8 / 8 | 100% |

Evidence completeness is 100% throughout - every requirement's declared
conditions match exactly one of the six sessions, and every session has
every configuration evaluated, so nothing in this demo is ever N/A. (The
Profiles UI's own live-verification screenshots, taken while building
Phase 38, separately exercise the N/A case with an ad-hoc unreachable
condition - not part of this standing reference profile.)

**If other session data exists in the same MultiSens instance** (e.g. the
standing v0.2/v0.3 evaluation/comparison demo), computing coverage with no
`configuration_ids`/`session_ids` filter will also discover any
configuration that happens to have an evaluated `presence` result
elsewhere - correctly reported as all-N/A for this profile's requirements
(none of its own sessions have that configuration evaluated), not an
error. This is the evidence-discovery algorithm behaving exactly as
designed (see app/domain/evidence.py) - use the Coverage section's
per-configuration checkboxes, or pass an explicit `session_ids` filter
scoped to this demo's six sessions, to see just the five configurations
this profile is actually about.

**Do not read any of this as a claim about real sensor performance** -
same caveat as `examples/evaluation/README.md`: this project's own
reference setup has no real depth/thermal hardware, and even a real
sensor's accuracy depends entirely on the detection model being
evaluated, which this dataset has none of.

## Not a regulatory framework

"Generic Cabin Safety Demo" is deliberately not named after, modeled on,
or claiming equivalence to any real regulatory or industry framework
(NCAP, DMS/OMS certification schemes, etc.). MultiSens's core has no
built-in knowledge of any such framework - a profile representing one is
something an external user could build with the exact same generic
`EvaluationProfile`/`RequirementGroup`/`Requirement` shapes this demo
uses, entirely outside the MultiSens core. The UI never renders
"compliant," "certified," or a "safety score" for this or any profile -
only `PASS`/`FAIL`/`N/A` per requirement and the two coverage numbers
above, both always shown together.

Both the scenario and every session/ground-truth/prediction entry carry
`"metadata": {"synthetic": true}`, and the profile document itself carries
`"metadata": {"synthetic": true}` - the Profiles UI reads this to show a
standing SYNTHETIC DATA banner, so this can't be mistaken for a real
result even after the fact.

## Loading it

```bash
docker compose up -d
python3 scripts/load_profile_demo_data.py
```

Then open the Profiles page and select "Generic Cabin Safety Demo".

## `exterior-decision-demo.json` + `exterior-decision-demo-data.json`

A deterministic, **entirely synthetic** reference profile and dataset for
exercising the v0.6 decision-support workflow (minimum sufficient sensor
sets, Pareto/dominance analysis, requirement gap closure, redundancy/
policy-critical sweeps) end to end. This is a genuinely different scenario
from `cabin-safety-demo.json`, not a variant squeezed into it (v0.6
architecture review, issue #54, Q23): the cabin-safety demo asks "does
this evidence satisfy a requirement," this demo asks "which sensor
combination is minimally sufficient." Deliberately no condition
dimensions - every requirement's `conditions` is empty, since this demo is
about the sensor-combination space v0.6 reasons over, not a second
condition-exploration showcase.

**`exterior-decision-demo.json`** is the profile document ("Generic
Exterior Sensing Decision Demo", version `1.0`): two groups (`Baseline
Detection`, `Advanced Detection`), four `object_presence` requirements at
accuracy thresholds 50% / 70% / 85% / 97%.

**`exterior-decision-demo-data.json`** is the underlying evidence: one
scenario, one session, 100 `object_presence` ground-truth samples, and
predictions from **eight** configurations spanning four reference sensor
ids - `front_rgb` and `rear_rgb` (two separate physical RGB camera
positions, never merged just because they share modality `rgb`) plus
simulated `sim_thermal`/`sim_depth`:

| Configuration | Sensors | Accuracy |
|---|---|---|
| `cfg-front_rgb` | front_rgb | 60% |
| `cfg-rear_rgb` | rear_rgb | 55% |
| `cfg-front_rgb-rear_rgb` | front_rgb, rear_rgb | 72% |
| `cfg-front_rgb-sim_thermal` | front_rgb, sim_thermal | 88% |
| `cfg-front_rgb-sim_depth` | front_rgb, sim_depth | 70% |
| `cfg-front_rgb-rear_rgb-sim_thermal` | front_rgb, rear_rgb, sim_thermal | 98% |
| `cfg-front_rgb-rear_rgb-sim_depth` | front_rgb, rear_rgb, sim_depth | 85% |
| `cfg-front_rgb-rear_rgb-sim_depth-sim_thermal` | all four | 98% |

Every value is **generated, not measured** - see
[`scripts/generate_decision_demo_data.py`](../../scripts/generate_decision_demo_data.py)
(same fixed-mislabel-index technique as the cabin-safety demo's
generator). The story: `front_rgb` and `rear_rgb` alone are both weak
baselines (ordinary cameras); combining them helps modestly (redundant
viewpoints, same modality); adding `sim_thermal` helps much more (a
genuinely different sensing modality); `sim_depth` on its own alongside
`front_rgb` helps about as much as `rear_rgb` does (also a modest,
non-modality-changing addition); the three-sensor
`front_rgb+rear_rgb+sim_thermal` combination reaches every requirement in
this profile; adding `sim_depth` on top changes nothing further - the
"some sensors add no additional requirement coverage" case the whole
decision-support layer exists to catch.

Against the profile's four requirements this produces:

| Configuration | Requirements passed | Coverage |
|---|---|---|
| `cfg-front_rgb` | 1 / 4 | 25% |
| `cfg-rear_rgb` | 1 / 4 | 25% |
| `cfg-front_rgb-rear_rgb` | 2 / 4 | 50% |
| `cfg-front_rgb-sim_thermal` | 3 / 4 | 75% |
| `cfg-front_rgb-sim_depth` | 2 / 4 | 50% |
| `cfg-front_rgb-rear_rgb-sim_thermal` | 4 / 4 | 100% |
| `cfg-front_rgb-rear_rgb-sim_depth` | 3 / 4 | 75% |
| `cfg-front_rgb-rear_rgb-sim_depth-sim_thermal` | 4 / 4 | 100% |

Under the demo policy shown in the Decision tab (100% coverage, 95%
completeness, mandatory-pass off), exactly **one** configuration is
minimally sufficient - `cfg-front_rgb-rear_rgb-sim_thermal` - and the
Pareto front (trading sensor count against coverage/completeness) is the
four-point curve `cfg-front_rgb`, `cfg-rear_rgb`,
`cfg-front_rgb-sim_thermal`, `cfg-front_rgb-rear_rgb-sim_thermal`; every
other configuration is dominated. All of the above is independently
re-derived by hand and cross-checked against the live API in
`backend/tests/test_decision_demo.py`, using no imports from
`app.domain.decision` itself.

**`config/sensors.yaml` was deliberately NOT extended** with
`front_rgb`/`rear_rgb`/`sim_thermal`/`sim_depth` entries. Every entry in
that file spawns a real `rtsp_ingestion_node`, and the ROS launch layer
rejects two sensors sharing a `modality` at startup (`front_rgb` and
`rear_rgb` would both be `modality: rgb`); `sim_thermal`/`sim_depth`
would likewise collide with the already-configured live `thermal`/`depth`
entries powering the cabin-safety-demo dashboard. Adding them purely for
display would require either bypassing that guard or fabricating a live
source that doesn't exist - so these four ids are evaluation-only for
this demo, and the Sensors tab's `SourceTypeBadge` correctly renders no
badge at all for an unmapped sensor id (already-built graceful
degradation, not an error) rather than a fabricated source type. The
Decision tab additionally shows a standing "SYNTHETIC DECISION DEMO"
banner (driven by this profile's `metadata.synthetic: true`) making clear
these outcomes demonstrate functionality only and are not a claim about
real or simulated sensor performance.

### Loading it

```bash
docker compose up -d
python3 scripts/load_decision_demo_data.py
```

Then open the Profiles page, select "Generic Exterior Sensing Decision
Demo", and open its Decision tab.
