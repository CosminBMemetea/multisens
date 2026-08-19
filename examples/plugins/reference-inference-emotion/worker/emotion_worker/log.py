"""Structured (key=value), rate-limited logging - identical in shape to
yolo_worker's own log.py (RideSafe bring-up, Phase 28). Duplicated, not
imported cross-package, since each reference worker is meant to be a
genuinely standalone, independently-installable process (see this
package's own pyproject.toml docstring)."""
from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
_logger = logging.getLogger('emotion_worker')

_last_logged_at: dict[str, float] = {}


def log(level: str, event: str, rate_limit_s: float = 0.0, **fields: object) -> None:
    """`rate_limit_s > 0` suppresses repeats of this exact `event` name
    within that window - keyed by the event name alone, not the full
    field set."""
    if rate_limit_s > 0:
        now = time.monotonic()
        last = _last_logged_at.get(event)
        if last is not None and now - last < rate_limit_s:
            return
        _last_logged_at[event] = now
    parts = ' '.join(f'{k}={v!r}' for k, v in fields.items())
    getattr(_logger, level)(f'event={event} {parts}')
