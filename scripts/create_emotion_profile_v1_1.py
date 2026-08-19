#!/usr/bin/env python3
"""Creates Requirement Profile emotion-demo-v1.1 via the real API (v0.9.2,
issue #140) - not a synthetic/example profile, a genuine successor to
emotion-demo-v1.0 built once the per-class metrics from issue #138
existed to make it possible.

v1.0 had two requirements, both keyed on the aggregate `accuracy` metric
- it could say "the model is right N% of the time" but nothing about
*which* emotions it actually recognizes. v1.1 adds one requirement per
emotion actually present in the demo's own live GT (issue #139's posed
capture: neutral/happiness/surprise/anger/no_face), using the new
`recall:<label>` metrics (backend/app/domain/metrics.py,
backend/app/domain/evaluators.py) - plus a `recall_macro` requirement,
which is the metric that actually catches a classifier that collapsed
to "always predict neutral" (see the simulated-depth source's own
result: high raw `accuracy` because most of the dataset is neutral, but
`recall_macro` near zero because every other class has zero recall).

Profiles are immutable by convention (no update endpoint) - this is a
new id, not an edit of emotion-demo-v1.0.

Evaluate the SAME profile against each configuration_id separately
(cfg-emotion_demo_face_rgb vs cfg-emotion_demo_face_depth) to get the
actual RGB-vs-depth comparison - see docs/coverage.md /
POST /api/profiles/{id}/coverage.

    python3 scripts/create_emotion_profile_v1_1.py
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BACKEND = 'http://localhost:8000'

PROFILE = {
    'id': 'emotion-demo-v1.1',
    'name': 'Emotion Demo Requirements v1.1',
    'version': '1.1',
    'description': (
        'Per-emotion requirement coverage for the reference emotion-classification demo '
        '(issue #140), superseding v1.0\'s aggregate-only accuracy requirements. Not a '
        'driver-monitoring/NCAP/DMS compliance claim, not a clinical or psychological '
        'assessment - a reference demonstration of per-class Requirement coverage against '
        'a small, real, live-captured GT set (27 samples: 21 casual + 6 explicitly posed).'
    ),
    'groups': [
        {'id': 'aggregate', 'name': 'Aggregate performance', 'parent_id': None},
        {'id': 'per-emotion', 'name': 'Per-emotion coverage', 'parent_id': None},
    ],
    'requirements': [
        {
            'id': 'req-accuracy',
            'group_id': 'aggregate',
            'name': 'Overall accuracy',
            'description': 'Raw fraction correct across all matched samples, any emotion.',
            'task': 'emotion_classification',
            'acceptance': [{'metric': 'accuracy', 'operator': '>=', 'value': 0.65}],
        },
        {
            'id': 'req-recall-macro',
            'group_id': 'aggregate',
            'name': 'Macro-averaged recall across emotions',
            'description': (
                'Unweighted mean recall over every emotion actually observed in GT - the '
                'metric that catches a classifier that collapsed to one dominant label, '
                'which raw accuracy alone cannot (a class-imbalanced dataset lets a '
                '"always predict the majority class" classifier score deceptively well on '
                'accuracy while recalling ~0 on everything else).'
            ),
            'task': 'emotion_classification',
            'acceptance': [{'metric': 'recall_macro', 'operator': '>=', 'value': 0.5}],
        },
        {
            'id': 'req-recall-neutral',
            'group_id': 'per-emotion',
            'name': 'Recall on neutral',
            'task': 'emotion_classification',
            'acceptance': [{'metric': 'recall:neutral', 'operator': '>=', 'value': 0.8}],
        },
        {
            'id': 'req-recall-happiness',
            'group_id': 'per-emotion',
            'name': 'Recall on happiness',
            'task': 'emotion_classification',
            'acceptance': [{'metric': 'recall:happiness', 'operator': '>=', 'value': 0.4}],
        },
        {
            'id': 'req-recall-surprise',
            'group_id': 'per-emotion',
            'name': 'Recall on surprise',
            'task': 'emotion_classification',
            'acceptance': [{'metric': 'recall:surprise', 'operator': '>=', 'value': 0.4}],
        },
    ],
}


def main() -> None:
    data = json.dumps(PROFILE).encode()
    req = urllib.request.Request(
        f'{BACKEND}/api/profiles', data=data, method='POST', headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(resp.status, json.dumps(json.loads(resp.read()), indent=2))
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())


if __name__ == '__main__':
    main()
