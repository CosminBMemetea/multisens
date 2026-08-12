"""SQLite connection + migration runner.

Together with repository.py, this is the only place in the backend that
imports sqlite3 - everything else deals in the domain model
(app/domain/models.py) or plain dicts, never rows or cursors.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = '/data/multisens.db'
MIGRATIONS_DIR = Path(__file__).parent / 'migrations'


def get_db_path() -> str:
    return os.environ.get('MULTISENS_DB_PATH', DEFAULT_DB_PATH)


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI's sync generator dependencies (see
    # app/api/deps.py) are not guaranteed to yield and get torn down on the
    # same worker thread as the endpoint body that actually uses the
    # connection - confirmed the hard way, via a real browser hitting a
    # real running server (sqlite3.ProgrammingError, "created in a thread
    # can only be used in that same thread"), which TestClient's
    # single-portal-call dispatch never happened to reproduce. Safe here
    # because each connection is still only ever used by one request at a
    # time, sequentially - never concurrently by two requests at once,
    # since get_db() opens a fresh connection per request.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Applies any migration file not yet recorded in schema_migrations, in
    filename order (`NNNN_description.sql`). Safe to call on every startup -
    already-applied versions are skipped, not reapplied."""
    conn.execute(
        'CREATE TABLE IF NOT EXISTS schema_migrations '
        '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)'
    )
    applied = {row[0] for row in conn.execute('SELECT version FROM schema_migrations')}
    for path in sorted(MIGRATIONS_DIR.glob('*.sql')):
        version = int(path.name.split('_', 1)[0])
        if version in applied:
            continue
        conn.executescript(path.read_text())
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        conn.commit()
