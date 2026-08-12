import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app
from app.persistence import db as db_module


@pytest.fixture
def client(tmp_path):
    """DB-backed TestClient shared by every evaluation-API test module.

    Mirrors deps.get_db's real per-request-connection behavior (each
    request runs in its own threadpool worker thread - a single shared
    connection object raises sqlite3.ProgrammingError across threads, a
    bug this exact fixture caught during Phase 12), just pointed at a tmp
    file instead of MULTISENS_DB_PATH. Deliberately does NOT use
    `with TestClient(app)` (see test_main.py's docstring) - lifespan would
    call bridge.start(), a real rclpy.init(), which none of these tests
    need.
    """
    db_path = str(tmp_path / 'test.db')

    def _get_db():
        conn = db_module.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_db]
