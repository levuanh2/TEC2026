"""Server-enforced limits on model calls: per-user and project daily quotas, a per-user rate
limit, a daily cost hard stop (+ alert), and a kill switch. No prompt, answer or key is ever
recorded; the audit log carries a salted hash of the user id, counts and cost only.

Environment (server only; defaults are the owner's pilot proposal, adjustable):
  RAG_LLM_KILL_SWITCH                          "true" -> no model call at all (503)
  RAG_LLM_MAX_ACTION_REQUESTS_PER_USER_PER_DAY default 20
  RAG_LLM_MAX_REQUESTS_PER_PROJECT_PER_DAY     default 1000 (every model call, any user)
  RAG_LLM_MAX_REQUESTS_PER_USER_PER_MINUTE     default 5
  RAG_LLM_DAILY_BUDGET_ALERT_USD               default 5  (log `rag_llm_budget_alert` once a day)
  RAG_LLM_DAILY_COST_HARD_STOP_USD             default 10 ("off" disables). With a hard stop, a
                                               provider whose prices are not configured is refused
                                               at start-up: an unknown cost cannot be capped.
Days are UTC. `InProcessQuotaStore` is exact for ONE API process (production runs one
container today) and resets on restart; a multi-instance deployment needs the durable store
of supabase/drafts/rag_llm_usage_daily.sql (draft, not applied anywhere).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("agricarbon.rag.quota")


class QuotaConfigError(ValueError):
    pass


class QuotaRefused(Exception):
    """`code`: kill_switch | user_daily_quota | project_daily_quota | user_rate_limited |
    daily_cost_hard_stop."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class QuotaPolicy:
    kill_switch: bool = False
    user_daily: int = 20
    project_daily: int = 1000
    user_per_minute: int = 5
    budget_alert_usd: float | None = 5.0
    cost_hard_stop_usd: float | None = 10.0

    def __post_init__(self) -> None:
        for value in (self.user_daily, self.project_daily, self.user_per_minute):
            if value < 0:
                raise QuotaConfigError("quota limits must be >= 0")
        for value in (self.budget_alert_usd, self.cost_hard_stop_usd):
            if value is not None and value < 0:
                raise QuotaConfigError("budget limits must be >= 0")


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    return int(raw) if raw else default


def _usd(env: Mapping[str, str], name: str, default: float | None) -> float | None:
    raw = (env.get(name) or "").strip().lower()
    if raw == "off":
        return None
    return float(raw) if raw else default


def load_quota_policy(env: Mapping[str, str] | None = None) -> QuotaPolicy:
    env = os.environ if env is None else env
    return QuotaPolicy(
        kill_switch=(env.get("RAG_LLM_KILL_SWITCH") or "").strip().lower() == "true",
        user_daily=_int(env, "RAG_LLM_MAX_ACTION_REQUESTS_PER_USER_PER_DAY", 20),
        project_daily=_int(env, "RAG_LLM_MAX_REQUESTS_PER_PROJECT_PER_DAY", 1000),
        user_per_minute=_int(env, "RAG_LLM_MAX_REQUESTS_PER_USER_PER_MINUTE", 5),
        budget_alert_usd=_usd(env, "RAG_LLM_DAILY_BUDGET_ALERT_USD", 5.0),
        cost_hard_stop_usd=_usd(env, "RAG_LLM_DAILY_COST_HARD_STOP_USD", 10.0),
    )


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class InProcessQuotaStore:
    """Thread-safe counters keyed by UTC day. A reservation counts immediately (a failed or
    refused provider call still used the quota: the request reached the provider gate)."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _user: dict = field(default_factory=lambda: defaultdict(int))
    _project: dict = field(default_factory=lambda: defaultdict(int))
    _cost: dict = field(default_factory=lambda: defaultdict(float))
    _minute: dict = field(default_factory=lambda: defaultdict(deque))
    _alerted: set = field(default_factory=set)

    def reserve(self, policy: QuotaPolicy, user_key: str, now: float) -> None:
        day = _day(now)
        with self._lock:
            if policy.cost_hard_stop_usd is not None and self._cost[day] >= policy.cost_hard_stop_usd:
                raise QuotaRefused("daily_cost_hard_stop")
            if self._project[day] >= policy.project_daily:
                raise QuotaRefused("project_daily_quota")
            if self._user[(day, user_key)] >= policy.user_daily:
                raise QuotaRefused("user_daily_quota")
            window = self._minute[user_key]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= policy.user_per_minute:
                raise QuotaRefused("user_rate_limited")
            window.append(now)
            self._project[day] += 1
            self._user[(day, user_key)] += 1

    def add_cost(self, policy: QuotaPolicy, cost_usd: float, now: float) -> tuple[float, bool]:
        """(spent today, whether the alert threshold was crossed by this call — once a day)."""
        day = _day(now)
        with self._lock:
            self._cost[day] += cost_usd
            spent = self._cost[day]
            crossed = (policy.budget_alert_usd is not None and spent >= policy.budget_alert_usd
                       and day not in self._alerted)
            if crossed:
                self._alerted.add(day)
            return spent, crossed

    def usage(self, user_key: str, now: float) -> dict:
        day = _day(now)
        with self._lock:
            return {"day": day, "user": self._user[(day, user_key)], "project": self._project[day],
                    "cost_usd": self._cost[day]}


def user_key(user_id: str, salt: str) -> str:
    """Pseudonymous, stable per deployment: the audit never holds the raw user id."""
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:16]


@dataclass
class QuotaGate:
    policy: QuotaPolicy
    store: InProcessQuotaStore = field(default_factory=InProcessQuotaStore)
    salt: str = "agricarbon-rag"
    clock: Callable[[], float] = time.time

    def reserve(self, user_id: str, *, purpose: str) -> str:
        """Before any provider call. Raises QuotaRefused; returns the pseudonymous user key."""
        if self.policy.kill_switch:
            raise QuotaRefused("kill_switch")
        key = user_key(str(user_id), self.salt)
        try:
            self.store.reserve(self.policy, key, self.clock())
        except QuotaRefused as exc:
            logger.warning("rag_llm_quota_refused user=%s purpose=%s code=%s", key, purpose, exc.code)
            raise
        return key

    def record(self, key: str, *, purpose: str, provider: str | None, model: str | None, ok: bool,
               input_tokens: int | None, output_tokens: int | None, cost_usd: float | None) -> None:
        """After the provider call: usage audit (no text, no key) and the cost counter."""
        now = self.clock()
        spent, crossed = self.store.add_cost(self.policy, cost_usd or 0.0, now)
        logger.info("rag_llm_usage user=%s purpose=%s provider=%s model=%s ok=%s input_tokens=%s "
                    "output_tokens=%s cost_usd=%s spent_today_usd=%.6f", key, purpose, provider, model, ok,
                    input_tokens, output_tokens, cost_usd, spent)
        if crossed:
            logger.error("rag_llm_budget_alert spent_today_usd=%.6f threshold_usd=%s", spent, self.policy.budget_alert_usd)


def build_quota_gate(policy: QuotaPolicy, llm_settings) -> QuotaGate | None:
    """None when no provider is configured. Refuses a hard stop that could not be enforced."""
    if llm_settings is None:
        return None
    if policy.cost_hard_stop_usd is not None and (
            llm_settings.price_input_usd_per_mtok is None or llm_settings.price_output_usd_per_mtok is None):
        raise QuotaConfigError("RAG_LLM_DAILY_COST_HARD_STOP_USD needs RAG_LLM_PRICE_* (an unknown cost cannot be "
                               "capped); set the prices or RAG_LLM_DAILY_COST_HARD_STOP_USD=off explicitly")
    return QuotaGate(policy, salt=os.environ.get("RAG_LLM_AUDIT_SALT") or "agricarbon-rag")
