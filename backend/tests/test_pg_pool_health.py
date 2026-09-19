"""P1-B: a pooled connection the server has closed is replaced at checkout.

The real-database test terminates ONLY the backend session this test's own
pool opened (identified by `pg_backend_pid()` on that connection), then checks
out again. Before the fix the first statement failed with
`psycopg.errors.AdminShutdown` (an OperationalError) -- the same failure a
backend that sat idle overnight produced. Skipped without `SUPABASE_DB_URL`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure import pg_pool  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the pool tests.")
psycopg_pool = pytest.importorskip("psycopg_pool", reason="the pool is optional; nothing to test without it.")

_DB_URL = load_settings().supabase_db_url
real_db = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


@pytest.fixture
def fresh_pool():
    pg_pool.close_all()
    yield
    pg_pool.close_all()


def test_the_pool_checks_connections_at_checkout():
    pool = pg_pool._pool_for(_DB_URL) if _DB_URL else None
    if pool is None:
        pytest.skip("no database configured")
    try:
        assert pool._check is psycopg_pool.ConnectionPool.check_connection
    finally:
        pg_pool.close_all()


@real_db
def test_a_connection_killed_by_the_server_is_replaced_before_the_next_request(fresh_pool):
    pool = pg_pool._pool_for(_DB_URL)
    pool.wait()
    # Every idle connection this pool holds, so the next checkout cannot
    # dodge the problem by picking a different, healthy one.
    held = [pool.getconn() for _ in range(pool.get_stats()["pool_available"])]
    pids = [conn.execute("select pg_backend_pid() as pid").fetchone()["pid"] for conn in held]
    assert pids, "the pool held no idle connection, so nothing would be killed"
    for conn in held:
        conn.rollback()
        pool.putconn(conn)

    # Kill exactly those sessions -- this test's own -- from an unpooled connection.
    with psycopg.connect(_DB_URL) as admin:
        for pid in pids:
            assert admin.execute("select pg_terminate_backend(%s)", (pid,)).fetchone()[0] is True
    time.sleep(1)

    # First request after the kill: succeeds on a fresh session and can open a
    # write transaction (txid_current assigns a transaction id).
    with pg_pool.connection(_DB_URL) as conn:
        row = conn.execute("select pg_backend_pid() as pid, txid_current() as xid").fetchone()
    assert row["pid"] not in pids and row["xid"] > 0


def _app_raising(exc: BaseException) -> TestClient:
    import main

    app = FastAPI()
    for exc_type in main._database_unavailable_types():
        app.add_exception_handler(exc_type, main.database_unavailable_handler)

    @app.get("/boom")
    def boom():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("exc", [
    psycopg.OperationalError("connection to server at \"db.secret-host.example\" (10.0.0.1), port 5432 failed: password=hunter2"),
    psycopg_pool.PoolTimeout("couldn't get a connection after 30.00 sec"),
])
def test_an_unreachable_database_is_a_controlled_503_that_leaks_nothing(exc):
    response = _app_raising(exc).get("/boom")
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "database_unavailable"
    for secret in ("secret-host", "10.0.0.1", "hunter2", "30.00"):
        assert secret not in response.text
