"""Structured (key=value), rate-limited logging for the worker process
(RideSafe bring-up, Phase 28). Stdlib `logging` under the hood - this
module only adds a consistent field-based line format and per-event
rate limiting, so e.g. a prolonged RTSP outage logs "reconnecting"
once every `rate_limit_s`, not once per retry attempt forever. Kept
dependency-free (no cv2/ultralytics) so it's importable by the same
pure-logic test suite `state.py`/`server.py`/`detections.py` already
are.
"""
from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
_logger = logging.getLogger('yolo_worker')

_last_logged_at: dict[str, float] = {}


def log(level: str, event: str, rate_limit_s: float = 0.0, **fields: object) -> None:
    """`rate_limit_s > 0` suppresses repeats of this exact `event` name
    within that window - keyed by the event name alone, not the full
    field set, so a repeatedly-failing operation with a changing detail
    (e.g. a byte count) still only logs at most once per window, never
    silently spams because some field happened to differ."""
    if rate_limit_s > 0:
        now = time.monotonic()
        last = _last_logged_at.get(event)
        if last is not None and now - last < rate_limit_s:
            return
        _last_logged_at[event] = now
    parts = ' '.join(f'{k}={v!r}' for k, v in fields.items())
    getattr(_logger, level)(f'event={event} {parts}')
