"""Shared backend-only Postgres connections.

Opening a connection to hosted Supabase Postgres measured ~700-740ms (TLS +
pooler auth). Every psycopg repository here opened one per statement, so a
Farmer CV preview — one `select` returning a few rows — cost 2.4s, of which
the query itself was 300ms, and a recommendation run paid it once per rule.

Pooling changes nothing about trust or transactions: the same backend-only
service-role connection string, and `pool.connection()` has exactly the
semantics `with psycopg.connect(...)` had (commit on success, roll back on
exception) — it returns the connection to the pool instead of closing it.

If `psycopg_pool` is not installed the module falls back to the previous
connect-per-statement behaviour, so this is a performance dependency, never a
correctness one.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from . import profiling

MIN_SIZE = 1
# Well under uvicorn's default 40-thread pool; hosted Postgres connections are
# a scarce shared resource, and the read path does not touch this at all.
MAX_SIZE = 8
# Waiting is still far cheaper than opening a new connection.
TIMEOUT_SECONDS = 30.0

_lock = threading.Lock()
_pools: dict[str, Any] = {}


def _pool_for(conninfo: str) -> Any | None:
    with _lock:
        pool = _pools.get(conninfo)
        if pool is not None:
            return pool
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except Exception:  # noqa: BLE001 - optional; caller falls back
        return None
    pool = ConnectionPool(
        conninfo, min_size=MIN_SIZE, max_size=MAX_SIZE,
        kwargs={"row_factory": dict_row}, timeout=TIMEOUT_SECONDS, open=True,
    )
    with _lock:
        existing = _pools.get(conninfo)
        if existing is not None:
            pool.close()
            return existing
        _pools[conninfo] = pool
    return pool


def _record(label: str, started: float) -> None:
    profile = profiling.current()
    if profile is not None:
        profile.record(label, (time.monotonic() - started) * 1000)


@contextmanager
def connection(conninfo: str) -> Iterator[Any]:
    """One pooled connection, in a transaction, returned to the pool after.

    Both branches are a plain `with`, so the connection goes back to the pool
    (or is closed) on every exit path — success, exception, or the caller's
    generator being torn down. Acquisition is timed separately from the
    statements: a slow acquire means the pool is saturated or still opening,
    which is a different problem from a slow query.
    """
    pool = _pool_for(conninfo)
    started = time.monotonic()
    if pool is None:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(conninfo, row_factory=dict_row) as conn:
            _record("pg connect", started)
            yield conn
        return
    with pool.connection() as conn:
        _record("pg acquire", started)
        yield conn


def close_all() -> None:
    """Tests and shutdown."""
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()
