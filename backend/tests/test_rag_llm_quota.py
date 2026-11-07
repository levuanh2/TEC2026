"""Model-call limits (infrastructure/llm_quota.py) and their wiring in rag_qa — no network."""
from __future__ import annotations

import logging

import pytest

from infrastructure.llm_client import LlmCompletion, LlmSettings, LlmUnavailable, LlmUsage
from infrastructure.llm_quota import (
    QuotaConfigError,
    QuotaGate,
    QuotaPolicy,
    QuotaRefused,
    build_quota_gate,
    load_quota_policy,
)
from rag_qa import GuardedLlmClient, RagQuestionService, RagQuotaExceeded, http_error
from recommendation.rag import GenerationUnavailable
from tests.test_rag_qa import GOOD_RECOMMEND, Carbon, Llm, _ask, gate

DAY = 1_790_000_000.0  # a fixed UTC instant


class Clock:
    def __init__(self, now=DAY):
        self.now = now

    def __call__(self):
        return self.now


def _gate(**policy):
    return QuotaGate(QuotaPolicy(**policy), clock=Clock())


def test_defaults_match_the_pilot_proposal():
    p = load_quota_policy({})
    assert (p.user_daily, p.project_daily, p.user_per_minute) == (20, 1000, 5)
    assert (p.budget_alert_usd, p.cost_hard_stop_usd, p.kill_switch) == (5.0, 10.0, False)
    assert load_quota_policy({"RAG_LLM_DAILY_COST_HARD_STOP_USD": "off"}).cost_hard_stop_usd is None
    assert load_quota_policy({"RAG_LLM_KILL_SWITCH": "true"}).kill_switch is True
    with pytest.raises(QuotaConfigError):
        QuotaPolicy(user_daily=-1)


def test_per_user_daily_quota_then_the_next_utc_day_resets():
    g = _gate(user_daily=2, user_per_minute=100)
    g.reserve("u1", purpose="action")
    g.reserve("u1", purpose="action")
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u1", purpose="action")
    assert refused.value.code == "user_daily_quota"
    g.reserve("u2", purpose="action")  # another user is unaffected
    g.clock.now += 86_400
    g.reserve("u1", purpose="action")


def test_project_wide_quota_counts_every_user():
    g = _gate(project_daily=3, user_per_minute=100)
    for user in ("a", "b", "c"):
        g.reserve(user, purpose="action")
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("d", purpose="action")
    assert refused.value.code == "project_daily_quota"


def test_per_user_rate_limit_is_a_sliding_minute():
    g = _gate(user_per_minute=2)
    g.reserve("u", purpose="action")
    g.reserve("u", purpose="action")
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u", purpose="action")
    assert refused.value.code == "user_rate_limited"
    g.clock.now += 61
    g.reserve("u", purpose="action")


def test_cost_hard_stop_and_a_single_daily_alert(caplog):
    caplog.set_level(logging.INFO, logger="agricarbon.rag.quota")
    g = _gate(budget_alert_usd=1.0, cost_hard_stop_usd=2.0, user_per_minute=100)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="deepseek", model="m", ok=True, input_tokens=1, output_tokens=1,
             cost_usd=1.5)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="deepseek", model="m", ok=True, input_tokens=1, output_tokens=1,
             cost_usd=0.6)
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u", purpose="action")
    assert refused.value.code == "daily_cost_hard_stop"
    assert sum("rag_llm_budget_alert" in r.getMessage() for r in caplog.records) == 1


def test_kill_switch_refuses_before_counting():
    g = _gate(kill_switch=True)
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u", purpose="action")
    assert refused.value.code == "kill_switch"
    assert g.store.usage("x", g.clock())["project"] == 0


def test_the_audit_never_holds_the_user_id_question_or_key(caplog):
    caplog.set_level(logging.INFO, logger="agricarbon.rag.quota")
    g = _gate()
    key = g.reserve("88888888-real-user-id", purpose="action")
    g.record(key, purpose="action", provider="gemini", model="m", ok=True, input_tokens=10, output_tokens=2,
             cost_usd=None)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "88888888-real-user-id" not in text and key in text and "rag_llm_usage" in text


def test_a_hard_stop_without_prices_is_refused_at_start():
    unpriced = LlmSettings(provider="deepseek", model="deepseek-flash", api_key="k")
    with pytest.raises(QuotaConfigError):
        build_quota_gate(QuotaPolicy(), unpriced)
    assert build_quota_gate(QuotaPolicy(cost_hard_stop_usd=None), unpriced) is not None
    assert build_quota_gate(QuotaPolicy(), None) is None


# -- wiring: through RagQuestionService ---------------------------------------------------

def _service(llm, quota):
    return RagQuestionService(carbon_service=Carbon(), llm_client=llm, write_gate=gate(), quota=quota)


def test_quota_exceeded_is_429_and_the_provider_is_not_called():
    llm = Llm(GOOD_RECOMMEND)
    quota = _gate(user_daily=1, user_per_minute=100)
    assert _ask(_service(llm, quota), "recommend")["status"] == "generated"
    with pytest.raises(RagQuotaExceeded) as info:
        _ask(_service(llm, quota), "recommend")
    assert len(llm.requests) == 1
    status, code, message = http_error(info.value)
    assert (status, code) == (429, "quota_exceeded") and "user_daily_quota" not in message


def test_kill_switch_is_generation_unavailable():
    llm = Llm(GOOD_RECOMMEND)
    with pytest.raises(GenerationUnavailable):
        _ask(_service(llm, _gate(kill_switch=True)), "recommend")
    assert llm.requests == []


def test_read_intents_and_no_rule_cases_never_consume_quota():
    quota = _gate(user_daily=1)
    llm = Llm(GOOD_RECOMMEND)
    for intent in ("explain", "data_gap", "evidence", "compare"):
        _ask(_service(llm, quota), intent)
    from tests.test_rag_qa import Reader
    _ask(_service(llm, quota), "recommend", reader=Reader(signals=[]))   # no_rule_signal: no provider
    _ask(_service(llm, quota), "recommend", reader=Reader(chunks=[]))    # no evidence: no provider
    assert quota.store.usage("x", quota.clock())["project"] == 0 and llm.requests == []


def test_a_failed_provider_call_still_counts_and_is_audited(caplog):
    caplog.set_level(logging.INFO, logger="agricarbon.rag.quota")
    quota = _gate(user_daily=5, user_per_minute=100)
    with pytest.raises(GenerationUnavailable):
        _ask(_service(Llm(error=LlmUnavailable("rate_limited")), quota), "recommend")
    assert quota.store.usage("x", quota.clock())["project"] == 1
    assert any("ok=False" in r.getMessage() for r in caplog.records)


def test_guarded_client_records_tokens_and_cost():
    quota = _gate()

    class Inner:
        def complete_json(self, **_):
            return LlmCompletion(data={}, usage=LlmUsage(100, 20, 120, 0.25), latency_ms=1, model="m",
                                 finish_reason="STOP", provider="deepseek")
    GuardedLlmClient(Inner(), quota, user_id="u").complete_json(system="s", user="u", schema={})
    assert quota.store.usage("x", quota.clock())["cost_usd"] == 0.25


# -- mutation-testing follow-ups: exact env names, boundaries, price combinations -----------

def test_every_limit_is_read_from_its_own_variable():
    p = load_quota_policy({"RAG_LLM_MAX_ACTION_REQUESTS_PER_USER_PER_DAY": "7",
                           "RAG_LLM_MAX_REQUESTS_PER_PROJECT_PER_DAY": "70",
                           "RAG_LLM_MAX_REQUESTS_PER_USER_PER_MINUTE": "3",
                           "RAG_LLM_DAILY_BUDGET_ALERT_USD": "1.5", "RAG_LLM_DAILY_COST_HARD_STOP_USD": "2.5",
                           "RAG_LLM_KILL_SWITCH": " TRUE "})
    assert (p.user_daily, p.project_daily, p.user_per_minute) == (7, 70, 3)
    assert (p.budget_alert_usd, p.cost_hard_stop_usd, p.kill_switch) == (1.5, 2.5, True)
    assert load_quota_policy({"RAG_LLM_KILL_SWITCH": "yes"}).kill_switch is False   # only "true" switches off
    assert load_quota_policy({"RAG_LLM_DAILY_BUDGET_ALERT_USD": "OFF"}).budget_alert_usd is None
    with pytest.raises(Exception):
        QuotaPolicy().user_daily = 99                                              # policy is immutable
    for bad in ({"budget_alert_usd": -1.0}, {"cost_hard_stop_usd": -0.01}, {"project_daily": -1},
                {"user_per_minute": -1}):
        with pytest.raises(QuotaConfigError):
            QuotaPolicy(**bad)


def test_spending_exactly_the_hard_stop_stops():
    g = _gate(cost_hard_stop_usd=1.0, budget_alert_usd=None, user_per_minute=100)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="p", model="m", ok=True, input_tokens=1, output_tokens=1, cost_usd=1.0)
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u", purpose="action")
    assert refused.value.code == "daily_cost_hard_stop"


def test_the_alert_fires_at_exactly_the_threshold(caplog):
    caplog.set_level(logging.INFO, logger="agricarbon.rag.quota")
    g = _gate(budget_alert_usd=1.0, cost_hard_stop_usd=None, user_per_minute=100)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="p", model="m", ok=True, input_tokens=1, output_tokens=1, cost_usd=1.0)
    assert any("rag_llm_budget_alert" in r.getMessage() for r in caplog.records)


def test_the_rate_window_is_exactly_sixty_seconds():
    g = _gate(user_per_minute=1)
    g.reserve("u", purpose="action")
    g.clock.now += 59.9
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u", purpose="action")
    assert refused.value.code == "user_rate_limited"
    g.clock.now += 0.1                                                            # 60.0 s after the first
    g.reserve("u", purpose="action")


def test_usage_reports_the_counters():
    g = _gate(user_per_minute=100)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="p", model="m", ok=True, input_tokens=1, output_tokens=1, cost_usd=0.5)
    usage = g.store.usage(key, g.clock())
    assert usage == {"day": "2026-09-21", "user": 1, "project": 1, "cost_usd": 0.5}


@pytest.mark.parametrize("prices", [(0.1, None), (None, 0.4), (None, None)])
def test_any_missing_price_blocks_a_hard_stop(prices):
    settings = LlmSettings(provider="deepseek", model="m", api_key="k", price_input_usd_per_mtok=prices[0],
                           price_output_usd_per_mtok=prices[1])
    with pytest.raises(QuotaConfigError):
        build_quota_gate(QuotaPolicy(), settings)


def test_the_audit_salt_comes_from_the_environment(monkeypatch):
    priced = LlmSettings(provider="deepseek", model="m", api_key="k", price_input_usd_per_mtok=0.1,
                         price_output_usd_per_mtok=0.4)
    monkeypatch.setenv("RAG_LLM_AUDIT_SALT", "deployment-salt")
    assert build_quota_gate(QuotaPolicy(), priced).salt == "deployment-salt"
    monkeypatch.delenv("RAG_LLM_AUDIT_SALT")
    assert build_quota_gate(QuotaPolicy(), priced).salt == "agricarbon-rag"


def test_refusal_codes_are_exact():
    cases = [(_gate(user_daily=0), "user_daily_quota"), (_gate(project_daily=0), "project_daily_quota"),
             (_gate(user_per_minute=0), "user_rate_limited"), (_gate(kill_switch=True), "kill_switch")]
    for g, code in cases:
        with pytest.raises(QuotaRefused) as refused:
            g.reserve("u", purpose="action")
        assert refused.value.code == code and str(refused.value) == code
    g = _gate(cost_hard_stop_usd=0.0)                       # a zero limit is valid and refuses everything
    with pytest.raises(QuotaRefused) as refused:
        g.reserve("u", purpose="action")
    assert refused.value.code == "daily_cost_hard_stop"
    assert QuotaPolicy(user_daily=0, budget_alert_usd=0.0, cost_hard_stop_usd=0.0).user_daily == 0


def test_the_dataclass_defaults_equal_the_environment_defaults():
    assert QuotaPolicy() == load_quota_policy({})
    gate = QuotaGate(QuotaPolicy())
    assert gate.salt == "agricarbon-rag" and gate.reserve("u", purpose="action")  # the default clock works


def test_an_unknown_cost_adds_nothing_to_the_daily_spend():
    g = _gate(user_per_minute=100)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="p", model="m", ok=True, input_tokens=1, output_tokens=1, cost_usd=None)
    assert g.store.usage(key, g.clock())["cost_usd"] == 0.0


def test_user_keys_are_a_salted_sha256_prefix():
    import hashlib
    from infrastructure.llm_quota import user_key
    assert user_key("u1", "s") == hashlib.sha256(b"s:u1").hexdigest()[:16]


def test_log_lines_start_with_their_alerting_names(caplog):
    caplog.set_level(logging.INFO, logger="agricarbon.rag.quota")
    g = _gate(user_daily=1, budget_alert_usd=0.5, cost_hard_stop_usd=None, user_per_minute=100)
    key = g.reserve("u", purpose="action")
    g.record(key, purpose="action", provider="p", model="m", ok=True, input_tokens=1, output_tokens=1, cost_usd=1.0)
    with pytest.raises(QuotaRefused):
        g.reserve("u", purpose="action")
    messages = [r.getMessage() for r in caplog.records]
    for prefix in ("rag_llm_usage ", "rag_llm_budget_alert ", "rag_llm_quota_refused "):
        assert any(m.startswith(prefix) for m in messages), prefix
