"""Request-scoped read profiling.

Counts the backend→Supabase round trips one API request actually issues, and
how long they took, so a latency claim can be checked against the real fan-out
instead of estimated from the code. This only observes: it never changes what
is read, who may read it, or in which order.

The counter lives in a `ContextVar` so concurrent requests never share one.
`read_repo._concurrent` copies the calling context into its worker threads, so
round trips issued in parallel are still attributed to the request that made
them.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RequestProfile:
    """Totals for one HTTP request. Mutated from worker threads, so guarded."""

    calls: int = 0
    db_ms: float = 0.0
    by_label: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, label: str, elapsed_ms: float) -> None:
        with self._lock:
            self.calls += 1
            self.db_ms += elapsed_ms
            self.by_label.setdefault(label, []).append(elapsed_ms)

    def top(self, limit: int = 6) -> list[tuple[str, int, float]]:
        """(label, call count, total ms) for the slowest labels."""
        with self._lock:
            rows = [(label, len(xs), sum(xs)) for label, xs in self.by_label.items()]
        return sorted(rows, key=lambda x: x[2], reverse=True)[:limit]


_current: ContextVar[RequestProfile | None] = ContextVar("agricarbon_profile", default=None)


def start() -> RequestProfile:
    profile = RequestProfile()
    _current.set(profile)
    return profile


def current() -> RequestProfile | None:
    return _current.get()


@contextmanager
def observe(label: str):
    """Time one round trip and attribute it to the in-flight request, if any."""
    profile = _current.get()
    if profile is None:
        yield
        return
    started = time.monotonic()
    try:
        yield
    finally:
        profile.record(label, (time.monotonic() - started) * 1000)
