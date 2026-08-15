"""Background poll loop for pull-based connectors (v0.9, Phase 97). Same
"background thread, kept separate from uvicorn's event loop" pattern
`ros_bridge.py` already establishes - `poll()` is a potentially-blocking,
synchronous plugin call and must never run on the FastAPI event loop.

Forwards through the *existing* `repository.insert_batch_with_partial_failure`
- a connector is a code-driven way to call an endpoint that already
exists, not a new ingestion mechanism. Each poll cycle opens and closes
its own short-lived SQLite connection (the same "one connection per unit
of work, never shared across threads" discipline every request handler
already follows - `db.py`'s own module docstring).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Callable

from app.persistence import db as db_module
from app.persistence import repository as repo

DEFAULT_POLL_INTERVAL_S = 1.0


def _default_connect() -> sqlite3.Connection:
    return db_module.connect(db_module.get_db_path())


class PollRunner:
    def __init__(
        self, poll: Callable[[], list[Any]], bulk_insert: Callable[[Any, list[Any]], None],
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        connect: Callable[[], sqlite3.Connection] = _default_connect,
    ):
        self._poll = poll
        self._bulk_insert = bulk_insert
        self._poll_interval_s = poll_interval_s
        # Injectable so tests (and a future multi-database setup) never
        # need to depend on MULTISENS_DB_PATH - defaults to the exact
        # same connection every request handler already uses.
        self._connect = connect
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.total_ingested = 0
        self.total_rejected = 0
        self.last_error: str | None = None
        # None until start() actually launches the thread - genuinely
        # "no rate yet," never a fabricated 0.0 (v1.0-RC issue #124,
        # dashboard inference-FPS display - see predictions_per_sec below).
        self._started_monotonic: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            return  # idempotent no-op, same convention as ConnectorInstance.start()
        self._stop_event.clear()
        self._started_monotonic = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def predictions_per_sec(self) -> float | None:
        """A real measured rate (total_ingested over wall-clock time
        since this runner actually started), not a fabricated number -
        `None` before start() has ever run, matching this project's
        "no denominator, no fabricated value" discipline elsewhere
        (e.g. ResourceObservation's own quality semantics)."""
        if self._started_monotonic is None:
            return None
        elapsed = time.monotonic() - self._started_monotonic
        return self.total_ingested / elapsed if elapsed > 0 else 0.0

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_s * 2)
        self._thread = None

    def poll_once(self) -> None:
        """The actual unit of work - public and directly callable so
        tests never need to spin up a real background thread just to
        exercise the forwarding logic."""
        try:
            items = self._poll()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code, must never crash the loop
            self.last_error = str(e)
            return
        if not items:
            return

        try:
            conn = self._connect()
        except Exception as e:  # noqa: BLE001 - a transient DB problem (e.g. "database is
            # locked") must never kill this thread - the same discipline the
            # self._poll() call above already has. Without this, one bad
            # cycle stops the connector forever with no visible sign.
            self.last_error = str(e)
            return

        try:
            indexed = list(enumerate(items))
            errors = repo.insert_batch_with_partial_failure(conn, indexed, self._bulk_insert)
        except Exception as e:  # noqa: BLE001 - same reasoning as above
            self.last_error = str(e)
            return
        finally:
            conn.close()

        self.total_ingested += len(items) - len(errors)
        self.total_rejected += len(errors)
        self.last_error = errors[0][1] if errors else None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self._poll_interval_s)
