"""One deadline per request, for the layers that can enforce it (L1 #103, A1).

Only a path that has a deadline sets one (today: `POST /v1/crop-seasons/{id}/questions`, see
`rag_qa.QUESTION_DEADLINE_SECONDS`). Every other request sees `remaining() is None` and keeps its
old behaviour exactly. The value is a `time.monotonic()` instant in a `ContextVar`, so concurrent
requests never share one; a worker thread that should honour it must be given it explicitly
(`bound(at())`), because `CallerSeasonFactsSource` runs its workers in a FRESH context.

Who enforces it:
- `pg_pool.connection`: the checkout waits at most until the deadline (`psycopg_pool.PoolTimeout`).
- `PostgresCarbonRepository._stage` and the question rate-limit store: a transaction-local
  `statement_timeout` (`statement_timeout_ms()`), sent in the same round trip as the statements.
- `supabase_clients`: an httpx request hook lowers every timeout (connect/read/write/pool) of a
  PostgREST or Auth call to what is left, and refuses to start a call once nothing is left.
- `read_repo._retrying`: no transport retry once the deadline has passed.
- `CallerSeasonFactsSource`: waits for its workers until the deadline and never joins a late one.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_deadline: ContextVar[float | None] = ContextVar("agricarbon_request_deadline", default=None)
#: never hand a layer a timeout shorter than this (a call that cannot finish anyway fails fast)
MIN_TIMEOUT_SECONDS = 0.05


class DeadlineExceeded(TimeoutError):
    """The request's deadline passed before this step could start or finish."""


@contextmanager
def bound(at_monotonic: float | None) -> Iterator[None]:
    """Run the block under the deadline `at_monotonic` (None = no deadline)."""
    token = _deadline.set(at_monotonic)
    try:
        yield
    finally:
        _deadline.reset(token)


def at() -> float | None:
    return _deadline.get()


def remaining() -> float | None:
    """Seconds left (may be <= 0), or None without a deadline."""
    deadline = _deadline.get()
    return None if deadline is None else deadline - time.monotonic()


def expired() -> bool:
    left = remaining()
    return left is not None and left <= 0


def check(step: str) -> None:
    """Refuse to START `step` once the deadline has passed."""
    if expired():
        raise DeadlineExceeded(f"request deadline passed before {step}")


def clamp(seconds: float) -> float:
    """`seconds`, or less if the deadline is nearer (never below MIN_TIMEOUT_SECONDS)."""
    left = remaining()
    return seconds if left is None else max(MIN_TIMEOUT_SECONDS, min(seconds, left))


def statement_timeout_ms() -> int | None:
    """The transaction-local Postgres `statement_timeout` for what is left, or None."""
    left = remaining()
    return None if left is None else max(int(MIN_TIMEOUT_SECONDS * 1000), int(left * 1000))
