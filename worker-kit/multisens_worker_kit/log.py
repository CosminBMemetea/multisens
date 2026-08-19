"""Structured (key=value), rate-limited logging for an inference worker
process. Stdlib `logging` under the hood - this module only adds a
consistent field-based line format and per-event rate limiting, so e.g.
a prolonged RTSP outage logs "reconnecting" once every `rate_limit_s`,
not once per retry attempt forever. Kept dependency-free (no
cv2/ultralytics/onnxruntime) so it's importable by the same pure-logic
test suite `state.py`/`server.py` already are.

Extracted from the reference YOLO/emotion workers (issue #141) - see
`state.py`'s own docstring for why. `make_logger(name)` is a factory,
not a single module-level `log`, so each worker keeps its own
`logging.getLogger(...)` name and its own independent rate-limit
tracking (workers run as separate processes, so this only matters for
tests that might import more than one worker's logger in the same
process) - a worker package re-exports a bound `log` via a one-line
shim (`log = make_logger('emotion_worker')`), so every existing
`from emotion_worker.log import log` call site is unaffected.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def make_logger(name: str) -> Callable[..., None]:
    logger = logging.getLogger(name)
    last_logged_at: dict[str, float] = {}

    def log(level: str, event: str, rate_limit_s: float = 0.0, **fields: object) -> None:
        """`rate_limit_s > 0` suppresses repeats of this exact `event` name
        within that window - keyed by the event name alone, not the full
        field set, so a repeatedly-failing operation with a changing detail
        (e.g. a byte count) still only logs at most once per window, never
        silently spams because some field happened to differ."""
        if rate_limit_s > 0:
            now = time.monotonic()
            last = last_logged_at.get(event)
            if last is not None and now - last < rate_limit_s:
                return
            last_logged_at[event] = now
        parts = ' '.join(f'{k}={v!r}' for k, v in fields.items())
        getattr(logger, level)(f'event={event} {parts}')

    return log
