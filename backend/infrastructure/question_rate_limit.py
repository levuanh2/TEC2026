"""Per-user rate limit for `POST /v1/crop-seasons/{id}/questions` (READ-only pilot, A12).

Every question costs 26-41 sequential database statements, so one user or one script must
not be able to load the database. The limit is checked once per question:

* AFTER Supabase Auth has verified the caller's JWT (`reader.user_id()`: expired, invalid,
  logged-out and revoked sessions are 401 before any quota is touched), and
* BEFORE any season, Carbon, knowledge or provider read: an over-limit request costs one
  statement and gets the same 429 for every `crop_season_id`, so it reveals nothing about
  seasons of other tenants and cannot be dodged by changing the season id.

The key is the verified auth user id. Never a request field, never an IP address (several
farm households can share one network) and never a season id.

Environment (server only; defaults are the PROPOSED pilot values, not owner-approved):
  RAG_QA_RATE_LIMIT_PER_MINUTE   default 10  (sliding 60 s window)
  RAG_QA_RATE_LIMIT_PER_DAY      default 100 (sliding 24 h window)
  RAG_QA_RATE_LIMIT_STORE        "postgres" (default) | "memory"

There is no "off": a limit must be an integer >= 1, and a store that cannot answer refuses
the question (503 `question_rate_limit_unavailable`), never lets it through.

Stores:
* `postgres` — durable and atomic: `private.consume_rag_question_quota` (migration
  20261106090000) serialises each user's questions under a per-user advisory lock, so the
  limit holds across API processes, containers and restarts.
* `memory` — exact for ONE API process only. Each process keeps its own counts and a
  restart forgets them, so N processes allow up to N x the limit and a restart opens a
  fresh window. Use it only where a single process is proven, e.g. before the migration is
  approved for a database.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from . import request_deadline

logger = logging.getLogger("agricarbon.rag.rate_limit")

PER_MINUTE_ENV = "RAG_QA_RATE_LIMIT_PER_MINUTE"
PER_DAY_ENV = "RAG_QA_RATE_LIMIT_PER_DAY"
STORE_ENV = "RAG_QA_RATE_LIMIT_STORE"
DEFAULT_PER_MINUTE = 10
DEFAULT_PER_DAY = 100
STORES = ("postgres", "memory")
MINUTE_SECONDS = 60.0
DAY_SECONDS = 86_400.0


class QuestionRateConfigError(ValueError):
    pass


class QuestionRateLimited(Exception):
    """Over the limit. `rag_qa` maps it to 429 `question_rate_limited` + Retry-After."""

    def __init__(self, message: str, *, retry_after_seconds: int, window: str | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.window = window


class QuestionRateLimitUnavailable(Exception):
    """The store could not answer. `rag_qa` maps it to 503 (fail closed)."""


@dataclass(frozen=True)
class QuestionRatePolicy:
    per_minute: int = DEFAULT_PER_MINUTE
    per_day: int = DEFAULT_PER_DAY

    def __post_init__(self) -> None:
        for value in (self.per_minute, self.per_day):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise QuestionRateConfigError("question rate limits must be integers >= 1")


@dataclass(frozen=True)
class QuestionRateDecision:
    allowed: bool
    window: str | None = None          # "minute" | "day" when refused
    retry_after_seconds: int = 0


class QuestionRateStore(Protocol):
    def consume(self, user_id: str, policy: QuestionRatePolicy) -> QuestionRateDecision: ...


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise QuestionRateConfigError(f"{name} must be an integer >= 1") from exc


def load_question_rate_policy(env: Mapping[str, str] | None = None) -> QuestionRatePolicy:
    env = os.environ if env is None else env
    return QuestionRatePolicy(per_minute=_positive_int(env, PER_MINUTE_ENV, DEFAULT_PER_MINUTE),
                              per_day=_positive_int(env, PER_DAY_ENV, DEFAULT_PER_DAY))


def store_kind_from_env(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    kind = (env.get(STORE_ENV) or "postgres").strip().lower()
    if kind not in STORES:
        raise QuestionRateConfigError(f"{STORE_ENV} must be one of {', '.join(STORES)}")
    return kind


def _retry_after(expires_at: float, now: float) -> int:
    return max(1, math.ceil(expires_at - now))


class InProcessQuestionRateStore:
    """Sliding windows in this process's memory. Exact for one process (see module doc)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def consume(self, user_id: str, policy: QuestionRatePolicy) -> QuestionRateDecision:
        with self._lock:
            now = self._clock()
            events = self._events[user_id]
            while events and events[0] <= now - DAY_SECONDS:
                events.popleft()
            if len(events) >= policy.per_day:
                return QuestionRateDecision(False, "day", _retry_after(
                    events[len(events) - policy.per_day] + DAY_SECONDS, now))
            recent = [t for t in events if t > now - MINUTE_SECONDS]
            if len(recent) >= policy.per_minute:
                return QuestionRateDecision(False, "minute", _retry_after(
                    recent[len(recent) - policy.per_minute] + MINUTE_SECONDS, now))
            events.append(now)
            return QuestionRateDecision(True)


class PostgresQuestionRateStore:
    """`private.consume_rag_question_quota` over the backend-only pooled connection."""

    def __init__(self, conninfo: str, connection: Callable[[str], Any] | None = None) -> None:
        if not conninfo:
            raise QuestionRateConfigError("the postgres question rate store needs the backend DB URL")
        if connection is None:
            from infrastructure import pg_pool
            connection = pg_pool.connection
        self._conninfo = conninfo
        self._connection = connection

    def consume(self, user_id: str, policy: QuestionRatePolicy) -> QuestionRateDecision:
        try:
            with self._connection(self._conninfo) as conn, conn.cursor() as cur:
                sql = ("select allowed, limit_window, retry_after_seconds "
                       "from private.consume_rag_question_quota(%s::uuid, %s, %s)")
                params = (user_id, policy.per_minute, policy.per_day)
                timeout_ms = request_deadline.statement_timeout_ms()
                if timeout_ms is not None and hasattr(conn, "pipeline"):
                    # L1 #103 A1: bounded by the request deadline, in the same round trip. A timeout is a
                    # store failure like any other: refused below (fail closed), never let through.
                    with conn.pipeline():
                        conn.execute("select set_config('statement_timeout', %s, true)", [str(timeout_ms)])
                        cur.execute(sql, params)
                else:
                    cur.execute(sql, params)
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001 - any store failure refuses (fail closed)
            logger.error("rag_question_rate_store_error type=%s", type(exc).__name__)
            raise QuestionRateLimitUnavailable("the question rate limit store is unavailable") from exc
        if row is None:
            logger.error("rag_question_rate_store_error type=EmptyResult")
            raise QuestionRateLimitUnavailable("the question rate limit store returned nothing")
        if isinstance(row, Mapping):
            allowed, window, retry = row["allowed"], row["limit_window"], row["retry_after_seconds"]
        else:
            allowed, window, retry = row
        return QuestionRateDecision(bool(allowed), window, int(retry or 0))


class QuestionRateLimiter:
    """Refuses with `QuestionRateLimited` (429) or `QuestionRateLimitUnavailable` (503)."""

    def __init__(self, policy: QuestionRatePolicy, store: QuestionRateStore, *, store_kind: str) -> None:
        self.policy = policy
        self.store_kind = store_kind
        self._store = store

    def consume(self, user_id: str, *, request_id: str | None = None) -> None:
        if not user_id:
            raise QuestionRateLimitUnavailable("no verified user id")
        decision = self._store.consume(user_id, self.policy)
        if decision.allowed:
            return
        # No user id, token, question or season in the log line: the request id traces it.
        logger.warning("rag_question_rate_limited request_id=%s window=%s retry_after_s=%s",
                       request_id, decision.window, decision.retry_after_seconds)
        raise QuestionRateLimited("question rate limit reached",
                                  retry_after_seconds=decision.retry_after_seconds, window=decision.window)


def build_question_rate_limiter(*, db_url: str | None,
                                env: Mapping[str, str] | None = None) -> QuestionRateLimiter:
    """Composition root. Raises `QuestionRateConfigError` on a bad setting (start-up fails)."""
    policy = load_question_rate_policy(env)
    kind = store_kind_from_env(env)
    store: QuestionRateStore = (PostgresQuestionRateStore(db_url or "") if kind == "postgres"
                                else InProcessQuestionRateStore())
    logger.info("rag_question_rate_limit store=%s per_minute=%s per_day=%s",
                kind, policy.per_minute, policy.per_day)
    return QuestionRateLimiter(policy, store, store_kind=kind)
