"""Thin re-export of the shared worker-side toolkit (multisens_worker_kit,
issue #141) - state.py/server.py/log.py used to be duplicated verbatim
between this package and the sibling emotion_worker; both now point at
one shared, dependency-free implementation (see worker-kit/README.md
for why). Kept as a same-named module, not a call-site rewrite, so
every existing `from yolo_worker.state import ...` in this package/its
tests stays unchanged.
"""
from multisens_worker_kit.state import (
    LatestFrameSnapshot,
    SharedState,
    build_health_payload,
    build_latest_payload,
)

__all__ = ['LatestFrameSnapshot', 'SharedState', 'build_health_payload', 'build_latest_payload']
