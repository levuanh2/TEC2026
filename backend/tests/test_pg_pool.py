"""Pool lifecycle: no connection may stay checked out, whatever happened.

These use psycopg_pool's real ConnectionPool against a fake connection class,
so pool bookkeeping (checkout/return, sizing, close) is the real thing rather
than a stand-in.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure import pg_pool, profiling  # noqa: E402

psycopg_pool = pytest.importorskip("psycopg_pool")


class _FakeConnection:
    """Enough of psycopg's Connection for ConnectionPool to manage it.

    Supplied as the pool's `connection_class` so psycopg_pool's own `_connect`
    runs unmodified (it is what stamps the bookkeeping attributes the pool
    later reads back) — only the socket is fake.
    """

    @classmethod
    def connect(cls, *_a, **_k):
        conn = cls()
        _CREATED.append(conn)
        return conn

    def __init__(self, *_a, **_k):
        self.closed = False
        self.rolled_back = False
        self.committed = False
        self.autocommit = False
        self.pgconn = type("pgconn", (), {"transaction_status": 0})()

    def cursor(self, *_a, **_k):
        return self

    def execute(self, *_a, **_k):
        return self

    def fetchone(self):
        return None

    def close(self):
        self.closed = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


_CREATED: list["_FakeConnection"] = []


@pytest.fixture
def pool():
    """A real ConnectionPool of fake connections, registered as pg_pool's own."""
    _CREATED.clear()
    pg_pool.close_all()
    real = psycopg_pool.ConnectionPool(
        "postgresql://fake", connection_class=_FakeConnection,
        min_size=1, max_size=2, open=True, check=None,
    )
    real.wait(timeout=10)
    pg_pool._pools["fake"] = real
    yield real, _CREATED
    pg_pool.close_all()
    _CREATED.clear()


def test_a_successful_block_returns_its_connection(pool):
    real, _ = pool
    with pg_pool.connection("fake") as conn:
        assert conn is not None
        assert real.get_stats()["pool_available"] == 0
    assert real.get_stats()["pool_available"] == 1


def test_a_failing_block_returns_its_connection(pool):
    """A request that raises mid-transaction must not strand a connection —
    otherwise `max_size` failures deadlock the whole backend."""
    real, _ = pool
    with pytest.raises(RuntimeError):
        with pg_pool.connection("fake"):
            raise RuntimeError("boom")
    assert real.get_stats()["pool_available"] == 1


def test_repeated_failures_never_exhaust_the_pool(pool):
    real, _ = pool
    for _ in range(real.max_size * 5):
        with pytest.raises(ValueError):
            with pg_pool.connection("fake"):
                raise ValueError("boom")
    with pg_pool.connection("fake") as conn:
        assert conn is not None


def test_concurrent_users_never_exceed_max_size(pool):
    real, created = pool
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def use():
        try:
            barrier.wait(timeout=10)
            with pg_pool.connection("fake") as conn:
                assert conn is not None
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=use) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert errors == []
    assert len(created) <= real.max_size
    assert real.get_stats()["pool_available"] <= real.max_size


def test_acquisition_is_attributed_to_the_request(pool):
    profile = profiling.start()
    with pg_pool.connection("fake"):
        pass
    assert [label for label, _, _ in profile.top()] == ["pg acquire"]


def test_shutdown_closes_every_pool(pool):
    real, created = pool
    pg_pool.close_all()
    assert real.closed
    assert all(conn.closed for conn in created)
    assert pg_pool._pools == {}
