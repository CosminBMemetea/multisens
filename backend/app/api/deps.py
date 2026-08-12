"""Shared FastAPI dependencies for the evaluation API.

get_db() opens a fresh connection per request rather than sharing one
long-lived connection: FastAPI runs sync endpoint functions in a
threadpool, and sqlite3.Connection objects are bound to the thread that
created them - a single shared connection raised
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be
used in that same thread` under exactly this ingestion API's own test
suite, which is what caught it. SQLite's per-connection open cost is
negligible at this project's target scale (a few thousand events, a
single dashboard user - see docs/limitations.md).
"""
from collections.abc import Iterator
import sqlite3

from fastapi import HTTPException

from app.domain.models import Session
from app.persistence import db as db_module
from app.persistence import repository as repo


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db_module.connect(db_module.get_db_path())
    try:
        yield conn
    finally:
        conn.close()


def require_session(conn: sqlite3.Connection, session_id: str) -> Session:
    """Shared by every router that nests under /sessions/{id}/... - a
    session-scoped route with an unknown session_id is a 404, not a route
    that silently operates on nothing."""
    session = repo.get_session(conn, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session '{session_id}' not found")
    return session
