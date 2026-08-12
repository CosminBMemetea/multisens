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

from app.persistence import db as db_module


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db_module.connect(db_module.get_db_path())
    try:
        yield conn
    finally:
        conn.close()
