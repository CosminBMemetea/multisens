# Evaluation example data

## `classification-demo.json`

A deterministic, **entirely synthetic** dataset for exercising the v0.2
evaluation workflow and the v0.3 comparison/ablation workflow end to end -
100 `presence` ground-truth samples (50/50 `present`/`absent`, seeded
shuffle) and 100 predictions each from seven independent configurations -
every non-empty subset of `{rgb, depth, thermal}` - each with a
different, deliberately-chosen accuracy:

| Configuration | Sensors | Accuracy (by construction) |
|---|---|---|
| `cfg-rgb` | rgb | 90% |
| `cfg-depth` | depth | 83% |
| `cfg-thermal` | thermal | 87% |
| `cfg-depth-rgb` | rgb + depth | 93% |
| `cfg-rgb-thermal` | rgb + thermal | 95% |
| `cfg-depth-thermal` | depth + thermal | 90% |
| `cfg-depth-rgb-thermal` | rgb + depth + thermal | 97% |

The targets deliberately form a clean lattice: every configuration
strictly outperforms every configuration whose sensor set it is a
superset of (single < pair < all three), so the Comparison page's
Sensor Addition and Ablation sections always show an improvement/penalty
in the intuitive direction - there is no "removing a sensor helped" case
anywhere in this dataset. Every configuration also gets an on-time
prediction for all 100 ground-truth points, so any pairwise comparison
between two of these configurations shares the full 100-point common
set and shows `VALID`, never `VALID_WITH_WARNINGS`, by construction.

These numbers are **generated, not measured** - see
[`scripts/generate_demo_data.py`](../../scripts/generate_demo_data.py) for
exactly how (a fixed set of ground-truth indices is deliberately
mislabeled per configuration, so the resulting accuracy is exact, not a
probabilistic approximation). They exist only to produce a comparison
table with clearly different, orderable rows. **Do not read them as a
claim about real sensor performance** - the depth and thermal "sensors"
in this project's own reference setup are `ffmpeg` transforms of a
webcam feed (see the main [README](../../README.md#physical-vs-simulated--a-hard-distinction)),
not real depth/thermal hardware, and even a real depth/thermal sensor's
accuracy would depend entirely on the actual detection model being
evaluated, which this dataset has none of. In particular, the fact that
removing `rgb` from the full configuration costs more accuracy (-7pp)
than removing `thermal` (-4pp) is a property of these constructed
numbers, not a claim that rgb sensors are inherently more valuable than
thermal ones.

Both the `scenario` and every `ground_truth`/`prediction` entry carry
`"metadata": {"synthetic": true}`, and the scenario's `tags` include
`"synthetic"` - the dashboard reads this to show a standing SYNTHETIC DATA
banner on the session, so this can't be mistaken for a real result even
after the fact.

## Format (`format_version: "1.0"`)

```json
{
  "format_version": "1.0",
  "session": { "id": "...", "name": "...", "scenario_id": "...", "metadata": {} },
  "scenario": { "id": "...", "name": "...", "description": "...", "tags": [], "metadata": {} },
  "ground_truth": [
    { "id": "...", "timestamp_ms": 0.0, "task": "presence", "value": {"label": "present"}, "metadata": {} }
  ],
  "predictions": [
    { "id": "...", "timestamp_ms": 2.0, "source_id": "...", "sensor_ids": ["rgb"],
      "task": "presence", "value": {"label": "present"}, "confidence": 0.91, "metadata": {} }
  ]
}
```

`ground_truth`/`predictions` entries are exactly the shape the batch
ingestion endpoints already accept
(`POST /api/sessions/{id}/ground-truth/batch` and `.../predictions/batch`)
- `session_id` is never repeated per item because it comes from the URL.
`id` is optional on every entry (the server generates one if omitted);
this file sets them explicitly so the dataset is reproducible byte-for-
byte across regenerations.

There is currently no dedicated file-import API endpoint - loading this
file *is* four ordinary API calls (create scenario, create session, two
batches), which is exactly what
[`scripts/load_demo_data.py`](../../scripts/load_demo_data.py) does. See
that script rather than this doc for the authoritative field list; this
format will get its own section in `docs/evaluation.md` once more than
one example file exists.

## Loading it

```bash
docker compose up -d
python3 scripts/load_demo_data.py
```

Then open the Sessions page and select "Demo Presence Classification".
