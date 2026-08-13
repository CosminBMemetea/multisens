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
