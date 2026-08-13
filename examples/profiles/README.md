# Requirement profile example data

## `sensor-lab-demo.json` + `sensor-lab-demo-data.json`

A deterministic, **entirely synthetic** reference profile and dataset for
exercising the v0.4 requirement-profile/coverage workflow and the v0.5
condition-exploration workflow (facets, filtering, breakdown, cross-tab,
failure/N/A explorers, traceability) end to end.

**`sensor-lab-demo.json`** is the profile document itself (the exact shape
`POST /api/profiles` accepts): "Generic Sensor Evaluation Lab", version `1.0`,
four generic requirement groups (`Baseline Detection`, `Visibility Robustness`,
`Strict Accuracy`, `Weather Robustness`), eight requirements, each keyed to a
`presence` task and an `illumination`/`occlusion`/`weather` condition
triple.

**`sensor-lab-demo-data.json`** is the underlying evidence: one shared
scenario and **six sessions**. The original four cover one session per
`(illumination, occlusion)` combination (`day`/`none`, `day`/`partial`,
`night`/`none`, `night`/`partial`), each with `weather: clear`. Two more
(Phase 50, v0.5) hold occlusion at `none` and vary `weather` instead
(`day`/`rain`, `night`/`rain`) - deliberately **not** a full
`(illumination x occlusion x weather)` Cartesian product, since "partial
occlusion AND rain" would conflate two visibility-degrading factors into
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

| Configuration | day/clear | day/occluded | night/clear | night/occluded | day/rain | night/rain |
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
strengths; `rgb+depth+thermal` dominates everywhere. The `rain` columns
(Phase 50, v0.5) add a third, independent dimension: a mild, roughly-uniform
tax on every configuration except `thermal`, which takes a much larger hit
(moisture on the lens/housing attenuating the thermal signature) - large
enough at night to flip `cfg-thermal` from **pass** (night/clear, 85% vs.
the night baseline's 85% threshold) to **fail** (night/rain, 75% vs. the
*same* 85% threshold on `req-night-rain`) - a condition dimension
changing a pass/fail outcome, not just shifting a number.

Against the profile's eight requirements (two accuracy-≥85% baselines, two
occlusion requirements at 80%/75%, two stricter 95% bars reusing the
baseline conditions, and two rain variants of the baselines at the same
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

## Synthetic data labeling

Both the scenario and every session/ground-truth/prediction entry carry
`"metadata": {"synthetic": true}`, and the profile document itself carries
`"metadata": {"synthetic": true}` - the Profiles UI reads this to show a
standing SYNTHETIC DATA banner, so this can't be mistaken for a real
result even after the fact. The UI never renders "compliant," "certified,"
or a "safety score" for this or any profile - only `PASS`/`FAIL`/`N/A`
per requirement and the two coverage numbers above, both always shown
together.

## Loading it

```bash
docker compose up -d
python3 scripts/load_profile_demo_data.py
```

Then open the Profiles page and select "Generic Sensor Evaluation Lab".

## `exterior-decision-demo.json` + `exterior-decision-demo-data.json`

A deterministic, **entirely synthetic** reference profile and dataset for
exercising the v0.6 decision-support workflow (minimum sufficient sensor
sets, Pareto/dominance analysis, requirement gap closure, redundancy/
policy-critical sweeps) end to end. This is a genuinely different scenario
from `sensor-lab-demo.json`, not a variant squeezed into it (v0.6
architecture review, issue #54, Q23): the sensor-lab demo asks "does
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
(same fixed-mislabel-index technique as the sensor-lab demo's
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
entries powering the sensor-lab-demo dashboard. Adding them purely for
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

## `ridesafe-demo.json` + `ridesafe-demo-data.json`

A deterministic, **entirely synthetic** reference profile and dataset for
the MultiSens v0.7 deployment/resource-tradeoff workflow, built around a
personal front/rear dashcam setup (reference hardware: 70mai). **RideSafe
is ride monitoring and incident-evidence capture** - it is not a safety-
certification, driver-monitoring, or occupant-monitoring system, and
MultiSens itself never claims to guarantee passenger safety or prevent
incidents. This is the first of two v0.7 demos (a second, PropertyWatch,
follows in Phase 74) marking this project's deliberate pivot away from
cabin/occupant-style examples toward independent personal-camera
scenarios.

**`ridesafe-demo.json`** is the profile document: two groups (`Scene
Visibility`, `Journey Recording`), four `scene_visibility` requirements
across an `illumination: day | night` condition dimension - the same
condition-exploration mechanism `sensor-lab-demo.json` uses, with zero
occupant/driver-monitoring framing: this dimension only asks whether a
camera *sees the road scene*, never who or what is in it.

**`ridesafe-demo-data.json`** is the underlying evidence: one scenario,
**two sessions** (`ridesafe-day-session`, `ridesafe-night-session`), 100
`scene_visibility` ground-truth samples each, and predictions from three
configurations across two reference sensor ids - `ridesafe_front_rgb` and
`ridesafe_rear_rgb` (two separate physical camera positions, reusing the
exact sensor-instance-not-modality precedent `front_rgb`/`rear_rgb`
already established in v0.6 - no new sensor-identity work needed):

| Configuration | Sensors | Day accuracy | Night accuracy |
|---|---|---|---|
| `cfg-ridesafe_front_rgb` | front | 72% | 48% |
| `cfg-ridesafe_rear_rgb` | rear | 68% | 52% |
| `cfg-ridesafe_front_rgb-ridesafe_rear_rgb` | front+rear | 95% | 78% |

The story: front and rear cameras have complementary, not identical,
strengths (front slightly favors daylight, rear slightly favors low
light) - only the combined configuration reliably clears every bar, day
and night. Against the profile's four requirements (two baselines at
70%/50%, two stricter "full journey recording" bars at 90%/65%) this
produces:

| Configuration | Requirements passed | Coverage |
|---|---|---|
| `cfg-ridesafe_front_rgb` | 1 / 4 | 25% |
| `cfg-ridesafe_rear_rgb` | 1 / 4 | 25% |
| `cfg-ridesafe_front_rgb-ridesafe_rear_rgb` | 4 / 4 | 100% |

Under the standard demo policy (100% coverage, 95% completeness,
mandatory-pass off) evaluated across **both** sessions, exactly **one**
configuration is minimally sufficient - `cfg-ridesafe_front_rgb-
ridesafe_rear_rgb` - and all three configurations sit on the Pareto
front (front/rear tie on sensor count and coverage; the combined
configuration trades more sensors for strictly higher coverage - a
genuine trade-off, not a dominated point). Independently re-derived by
hand and cross-checked against the live API in
`backend/tests/test_ridesafe_demo.py`, with no imports from
`app.domain.decision`/`coverage`/`analysis`/`resources` themselves.

### SYNTHETIC RESOURCE DATA (v0.7)

The dataset also carries resource observations for the **daylight
session only** - CPU/memory/network/latency/FPS numbers chosen to tell a
clean "two cameras cost more but reach full coverage" story, never
measured from real 70mai/webcam hardware:

| Configuration | CPU | RAM | Network | Latency |
|---|---|---|---|---|
| `cfg-ridesafe_front_rgb` | 18.2% | 580 MB | 4.5↓/1.1↑ Mbps | 32 ms |
| `cfg-ridesafe_rear_rgb` | 17.4% | 575 MB | 4.3↓/1.0↑ Mbps | 33 ms |
| `cfg-ridesafe_front_rgb-ridesafe_rear_rgb` | 29.8% | 825 MB | 8.6↓/2.0↑ Mbps | 39 ms |

**Because resource evidence is inherently single-session-scoped** (see
`backend/app/domain/resources.py`'s own module docstring), opening the
Resources tab and selecting the daylight session only ever sees the 2
day-conditioned requirements - the
other 2 (night-conditioned) are genuinely N/A within that one session,
so real evidence completeness there is exactly 50%. Under the tabs' own
standard 95%-completeness policy this means every configuration's
`policy_status` badge reads **UNDETERMINED** in that view - not a bug,
an honest consequence of a single-session view genuinely not having
night evidence, while the underlying coverage percentages (0% / 50% /
100%) still tell the differentiated story. `scripts/load_ridesafe_demo_data.py`
uses its own looser illustrative policy for its printed CLI summary
specifically (documented in the script itself) so that output reads
cleanly; the live UI is not changed to match it.

Real, physically MEASURED resource numbers are only ever obtainable by
running `POST /api/sessions/{id}/resource-observations/batch` locally
against actual connected 70mai/webcam hardware and a real collector -
never shipped as committed demo content (v0.7 architecture review, Q25).

### Loading it

```bash
docker compose up -d
python3 scripts/load_ridesafe_demo_data.py
```

Then open the Profiles page, select "RideSafe — Ride Monitoring Demo",
and open its Decision or Resources tab.

## `ridesafe-detection-demo-data.json`

A deterministic, **entirely synthetic** object-detection dataset (v0.8,
Phase 87) - the first real exercise of the v0.8 detection evaluator,
extending the RideSafe reference story above with two new tasks,
`front_scene_object_detection` and `rear_scene_object_detection`, one per
camera position. No profile/requirements/resources - this is a
standalone evaluator demo, viewed directly on the session detail page's
Evaluation panel (v0.8, Phase 86), not through the Decision/Resources
tabs. Same ride-monitoring-and-incident-evidence framing as
`ridesafe-demo.json` - no face recognition, driver monitoring, occupant
classification, or regulatory use case.

One session (`ridesafe-detection-demo-session`), 100 ground-truth frames
per task (`vehicle`/`pedestrian` objects, alternating by frame index),
evaluated with `confidence_threshold=0.5`/`iou_threshold=0.5`. Every
frame falls into one of five hand-constructed categories - see
`scripts/generate_ridesafe_detection_demo_data.py`'s own docstring for
the exact bbox geometry:

| Category | What happens | Frames (front / rear) |
|---|---|---|
| A - clean hit | same-label detection, IoU 0.6 (above threshold) | 70 / 45 |
| B - too imprecise | same-label detection, IoU 0.25 (below threshold) | 10 / 20 |
| C - filtered by confidence | perfect IoU=1.0 but confidence 0.30 (below threshold) | 5 / 15 |
| D - missing prediction | no Prediction row for this frame at all | 5 / 15 |
| E - clean hit + spurious extra | one matching detection plus one non-overlapping extra | 10 / 5 |

By construction, front camera detection is notably stronger than rear -
the same "genuinely different pattern per configuration" discipline
`ridesafe-demo-data.json`'s own front/rear split already uses:

| Task | Config | Precision | Recall | F1 | Mean IoU (matched) |
|---|---|---|---|---|---|
| `front_scene_object_detection` | `cfg-ridesafe_front_rgb` | 0.80 | 0.80 | 0.80 | 0.65 |
| `rear_scene_object_detection` | `cfg-ridesafe_rear_rgb` | 0.667 | 0.50 | 0.571 | 0.64 |

Independently re-derived - a completely separate reimplementation of IoU
and greedy per-frame object matching, zero imports from
`app.domain.detection` - and cross-checked against the live `/evaluate`
API in `backend/tests/test_ridesafe_detection_demo.py`.

### Loading it

```bash
docker compose up -d
python3 scripts/load_ridesafe_detection_demo_data.py
```

Then open `http://localhost:8080/sessions/ridesafe-detection-demo-session`
and select either detection task in the Evaluation panel.

## `propertywatch-demo.json` + `propertywatch-demo-data.json`

A deterministic, **entirely synthetic** reference profile and dataset for
the MultiSens v0.7 deployment/resource-tradeoff workflow, built around a
personal multi-camera property monitoring setup - a **home, garage,
workshop, storage space, or small warehouse**, deliberately never
hardcoded to one building type. **No surveillance-identification or
face-recognition features of any kind** - every task here is plain area
visibility (present/absent-style classification), nothing more. This is
the second of the two v0.7 demos (see `ridesafe-demo.json`, Phase 73)
marking this project's deliberate pivot away from cabin/occupant-style
examples toward independent personal-camera scenarios.

**`propertywatch-demo.json`** is the profile document: two groups (`Area
Coverage`, `Reliability`), four requirements. Unlike `ridesafe-demo.json`,
each area has its **own task** (`entrance_visibility`/
`storage_visibility`/`indoor_visibility`) rather than one task shared
across sensors - a configuration only ever produces evidence for a task
if it actually includes that area's camera, so a camera-less area is
genuinely **N/A**, never a fabricated fail.

**`propertywatch-demo-data.json`** is the underlying evidence: one
scenario, one session, 300 `*_visibility` ground-truth samples (100 per
task) and predictions from three **nested** configurations across three
reference sensor ids - `property_entrance_rgb`, `property_storage_rgb`,
`property_indoor_rgb` (three separate physical camera positions, reusing
the same sensor-instance-not-modality precedent every prior v0.6/v0.7
demo already established):

| Configuration | Entrance | Storage | Indoor |
|---|---|---|---|
| `cfg-property_entrance_rgb` | 78% | — | — |
| `cfg-property_entrance_rgb-property_storage_rgb` | 85% | 72% | — |
| `cfg-property_entrance_rgb-property_indoor_rgb-property_storage_rgb` | 92% | 80% | 88% |

("—" means that configuration never produced any predictions for that
task at all - no camera, no evidence, not a measured 0%.) Against the
profile's four requirements (three 70% area-visibility baselines, one
stricter 90% "reliability" bar on the entrance area) this produces:

| Configuration | Requirements passed | Coverage | Completeness |
|---|---|---|---|
| `cfg-property_entrance_rgb` | 1 / 2 decided | 50% | 50% |
| `cfg-property_entrance_rgb-property_storage_rgb` | 2 / 3 decided | 67% | 75% |
| `cfg-property_entrance_rgb-property_indoor_rgb-property_storage_rgb` | 4 / 4 decided | 100% | 100% |

Under the standard demo policy (100% coverage, 95% completeness,
mandatory-pass off), exactly **one** configuration is minimally
sufficient - the fully-equipped one - and the two partial configurations
report **UNDETERMINED**, never INSUFFICIENT: real evidence completeness
is genuinely below the bar (a camera-less area's evidence could always
still arrive later by adding that camera, unlike a measured-and-failing
result). All **three** configurations sit on the Pareto front - a
genuine 3-point staircase where every additional camera costs more
sensors but also reaches strictly more coverage, never a dominated
point. This is the flagship "is the third camera worth its resource
load" worked example this whole layer exists to answer, composing a
v0.6 minimal-sufficient-set question with a v0.7 resource-cost question.
Independently re-derived by hand and cross-checked against the live API
in `backend/tests/test_propertywatch_demo.py`, with no imports from
`app.domain.decision`/`coverage`/`analysis`/`resources` themselves.

### SYNTHETIC RESOURCE DATA (v0.7)

The dataset also carries resource observations for its one session -
CPU/memory/network/latency/FPS numbers scaling roughly **linearly per
added camera** (a deliberately different shape from `ridesafe-demo`'s
"two cameras share some overhead" story), never measured from real
hardware:

| Configuration | CPU | RAM | Network | Latency |
|---|---|---|---|---|
| `cfg-property_entrance_rgb` | 15.0% | 480 MB | 3.8↓/0.9↑ Mbps | 28 ms |
| `cfg-property_entrance_rgb-property_storage_rgb` | 26.5% | 730 MB | 7.5↓/1.8↑ Mbps | 34 ms |
| `cfg-property_entrance_rgb-property_indoor_rgb-property_storage_rgb` | 38.0% | 980 MB | 11.4↓/2.7↑ Mbps | 41 ms |

Real, physically MEASURED resource numbers are only ever obtainable by
running `POST /api/sessions/{id}/resource-observations/batch` locally
against actual connected camera hardware and a real collector - never
shipped as committed demo content (v0.7 architecture review, Q25).

### Loading it

```bash
docker compose up -d
python3 scripts/load_propertywatch_demo_data.py
```

Then open the Profiles page, select "PropertyWatch — Property Monitoring
Demo", and open its Decision or Resources tab.
