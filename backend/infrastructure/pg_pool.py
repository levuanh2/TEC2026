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

Dead connections (P1-B). A pooled connection can be closed from the server
side while it sits idle -- the Supavisor pooler or the network drops it, and a
backend that idled overnight handed one out: the first write then failed with
`psycopg.OperationalError` until the process was restarted. The pool now runs
psycopg_pool's own `ConnectionPool.check_connection` on every checkout, so a
dead connection is discarded and replaced BEFORE any statement is sent. That
is the only kind of retry here, and it is safe because nothing was attempted
on the dead connection. A failure DURING or AFTER a statement is never retried
by this module: whether a COMMIT landed is then unknown, and replaying a write
could duplicate it. Such a failure reaches the client as a 503
`database_unavailable` (see main.py) and the caller's own idempotency decides
whether a retry is safe.

`max_idle` / `max_lifetime` stay at the library defaults (600 s / 3600 s): the
database has `idle_session_timeout = 0`, and nothing in this deployment gives a
lower bound to tune them against. The checkout check does not depend on them.
Measured from a dev machine to hosted Supabase the check costs one round trip
(~110 ms median per checkout, 297 -> 406 ms for checkout + `select 1`); a
backend deployed next to the database pays ~1 RTT of a few ms. Only the psycopg
write/lookup paths use this pool -- the read API goes through PostgREST.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
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
_bound: ContextVar[dict[str, Any] | None] = ContextVar("agricarbon_pg_bound", default=None)


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
        check=ConnectionPool.check_connection,
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
    bound_conn = (_bound.get() or {}).get(conninfo)
    if bound_conn is not None:
        # Inside `bound()`: same connection, same transaction contract — commit
        # on success (free when no transaction is open), roll back on error.
        try:
            yield bound_conn
        except BaseException:
            bound_conn.rollback()
            raise
        bound_conn.commit()
        return
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


@contextmanager
def bound(conninfo: str) -> Iterator[None]:
    """Serve every `connection(conninfo)` inside the block from ONE checkout.

    Round 5.1: a Carbon calculation's write check, bundle read and save each
    checked a connection out, and every checkout costs a liveness round trip
    (the P1-B check). Callers keep their own commit/rollback behaviour; only
    the checkout is shared. Request-scoped through a ContextVar, so concurrent
    requests never share a connection. A nested `bound` reuses the outer one.
    """
    current = _bound.get() or {}
    if conninfo in current:
        yield
        return
    with connection(conninfo) as conn:
        token = _bound.set({**current, conninfo: conn})
        try:
            yield
        finally:
            _bound.reset(token)


def close_all() -> None:
    """Tests and shutdown."""
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()
