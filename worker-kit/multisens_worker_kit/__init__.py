"""multisens-worker-kit - the small, dependency-free HTTP/state/logging
toolkit shared by every reference inference worker process (YOLO,
emotion, and any future preset). See README.md for the protocol this
package implements: `GET /latest` + `GET /health` over a lock-guarded
"latest finished frame" snapshot.

Deliberately NOT part of `multisens_sdk`: the SDK is what a
backend-loaded `PredictionConnector` bridge depends on, and its own
boundary test (see the reference plugins' `tests/test_boundary.py`)
enforces that a bridge imports nothing beyond it - mixing a worker-only
package in there would blur that line. A worker process is not a
MultiSens plugin (no entry_points, never installed into the backend
image) and is free to depend on this package without weakening that
boundary at all.
"""
