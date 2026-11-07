"""Multi-provider adapter (Gemini + DeepSeek) with mock HTTP transports — no network, no key."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.llm_client import (  # noqa: E402
    DeepSeekStructuredClient,
    GeminiStructuredClient,
    LlmConfigError,
    LlmSettings,
    LlmUnavailable,
    build_llm_client,
    classify_http_failure,
    list_models,
    load_llm_settings,
)

KEY = "sk-test-not-real-0000"
GKEY = "g-test-not-real-0000"
SCHEMA = {"type": "OBJECT", "properties": {"status": {"type": "STRING"}}, "required": ["status"]}


def _ds_settings(**overrides):
    base = dict(provider="deepseek", model="deepseek-flash", api_key=KEY, price_input_usd_per_mtok=0.3,
                price_input_cache_hit_usd_per_mtok=0.03, price_output_usd_per_mtok=1.2, retry_backoff_seconds=0.1)
    base.update(overrides)
    return LlmSettings(**base)


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _ds(handler, clock=None, **overrides):
    clock = clock or Clock()
    return DeepSeekStructuredClient(_ds_settings(**overrides), http=httpx.Client(transport=httpx.MockTransport(handler)),
                                    sleep=clock.sleep, clock=clock)


def _ds_ok(content, *, finish="stop", usage=None):
    def handler(request):
        handler.requests.append(request)
        return httpx.Response(200, json={
            "model": "deepseek-flash-2026-10", "choices": [{"message": {"role": "assistant", "content": content},
                                                            "finish_reason": finish}],
            "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
                               "prompt_cache_hit_tokens": 600, "prompt_cache_miss_tokens": 400},
        })
    handler.requests = []
    return handler


# -- configuration and key precedence ------------------------------------------------

def test_rag_llm_variables_take_precedence_over_provider_ones():
    s = load_llm_settings({"RAG_LLM_PROVIDER": "deepseek", "RAG_LLM_MODEL": "deepseek-flash",
                           "RAG_LLM_API_KEY": KEY, "DEEPSEEK_API_KEY": "other", "DEEPSEEK_MODEL": "other"})
    assert (s.model, s.api_key, s.key_source) == ("deepseek-flash", KEY, "RAG_LLM_API_KEY")


def test_provider_specific_variables_are_used_only_for_their_provider():
    s = load_llm_settings({"RAG_LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": KEY, "DEEPSEEK_MODEL": "deepseek-flash"})
    assert (s.api_key, s.key_source, s.model) == (KEY, "DEEPSEEK_API_KEY", "deepseek-flash")
    # a Gemini key in the environment can never reach DeepSeek, and vice versa
    with pytest.raises(LlmConfigError):
        load_llm_settings({"RAG_LLM_PROVIDER": "deepseek", "RAG_LLM_MODEL": "deepseek-flash", "GEMINI_API_KEY": GKEY})
    with pytest.raises(LlmConfigError):
        load_llm_settings({"RAG_LLM_PROVIDER": "gemini", "RAG_LLM_MODEL": "m", "DEEPSEEK_API_KEY": KEY})


@pytest.mark.parametrize("env", [
    {"RAG_LLM_PROVIDER": "deepseek", "RAG_LLM_API_KEY": KEY},                      # no model: never a default
    {"RAG_LLM_PROVIDER": "deepseek", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": KEY, "RAG_LLM_BASE_URL": "http://x"},
    {"RAG_LLM_PROVIDER": "deepseek", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": KEY, "RAG_LLM_THINKING": "maybe"},
    {"RAG_LLM_PROVIDER": "deepseek", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": KEY, "RAG_LLM_MAX_RETRIES": "9"},
    {"RAG_LLM_PROVIDER": "openai", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": KEY},
])
def test_misconfiguration_is_refused(env):
    with pytest.raises(LlmConfigError):
        load_llm_settings(env)


def test_factory_builds_the_configured_provider_only():
    assert isinstance(build_llm_client(_ds_settings(), http=object()), DeepSeekStructuredClient)
    gemini = LlmSettings(provider="gemini", model="m", api_key=GKEY)
    assert isinstance(build_llm_client(gemini, http=object()), GeminiStructuredClient)
    assert build_llm_client(None) is None
    with pytest.raises(LlmConfigError):
        DeepSeekStructuredClient(gemini, http=object())
    assert KEY not in repr(_ds_settings()) and KEY not in str(_ds_settings())


# -- DeepSeek request / response --------------------------------------------------------

def test_deepseek_json_mode_request_shape():
    handler = _ds_ok(json.dumps({"status": "generated"}))
    _ds(handler).complete_json(system="POLICY", user='{"request": "DATA"}', schema=SCHEMA)
    request = handler.requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(request.url)
    assert body["response_format"] == {"type": "json_object"} and body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0 and body["stream"] is False and body["max_tokens"] == 1024
    system, user = body["messages"]
    assert system["role"] == "system" and system["content"].startswith("POLICY") and "json" in system["content"]
    assert '"type": "object"' in system["content"]  # the schema travels with the policy, lower-cased
    assert user == {"role": "user", "content": '{"request": "DATA"}'}  # data stays in the user turn
    assert KEY not in json.dumps(body)


def test_deepseek_thinking_can_be_enabled_or_omitted():
    for mode, expected in (("enabled", {"type": "enabled"}), ("omit", None)):
        handler = _ds_ok(json.dumps({"status": "generated"}))
        _ds(handler, thinking=mode).complete_json(system="s", user="u", schema=SCHEMA)
        assert json.loads(handler.requests[0].content).get("thinking") == expected


def test_deepseek_usage_and_cache_aware_cost():
    completion = _ds(_ds_ok(json.dumps({"status": "generated"}))).complete_json(system="s", user="u", schema=SCHEMA)
    u = completion.usage
    assert (u.input_tokens, u.output_tokens, u.cache_hit_tokens, u.cache_miss_tokens) == (1000, 200, 600, 400)
    assert u.cost_usd == pytest.approx((600 * 0.03 + 400 * 0.3 + 200 * 1.2) / 1e6)
    assert completion.provider == "deepseek" and completion.model_version == "deepseek-flash-2026-10"
    assert completion.data == {"status": "generated"}


def test_cost_is_unknown_without_prices():
    completion = _ds(_ds_ok(json.dumps({"status": "generated"})), price_input_usd_per_mtok=None).complete_json(
        system="s", user="u", schema=SCHEMA)
    assert completion.usage.cost_usd is None  # COST_UNKNOWN, never an estimate


@pytest.mark.parametrize("content, finish, reason", [
    ('{"status": "generated"}', "length", "finish_length"),        # truncated
    ('{"status": "gene', "stop", "invalid_json"),
    ("   \n ", "stop", "empty_output"),
    ("", "stop", "empty_output"),
    ("[1, 2]", "stop", "invalid_json"),
    ('{"status": "generated"}', "content_filter", "finish_content_filter"),
])
def test_deepseek_unusable_output_is_typed(content, finish, reason):
    with pytest.raises(LlmUnavailable) as info:
        _ds(_ds_ok(content, finish=finish)).complete_json(system="s", user="u", schema=SCHEMA)
    assert info.value.reason == reason


def test_deepseek_without_choices_is_no_candidate():
    with pytest.raises(LlmUnavailable, match="no_candidate"):
        _ds(lambda r: httpx.Response(200, json={"choices": []})).complete_json(system="s", user="u", schema=SCHEMA)


# -- shared error mapping and bounded retry -------------------------------------------

@pytest.mark.parametrize("status, payload, reason", [
    (401, {"error": {"status": "UNAUTHENTICATED", "details": [{"reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}},
     "credential_type_unsupported"),
    (401, {"error": {"message": "Authentication Fails", "type": "authentication_error"}}, "auth_invalid"),
    (400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}, "auth_invalid"),
    (402, {"error": {"message": "Insufficient Balance"}}, "insufficient_balance"),
    (403, {"error": {"details": [{"reason": "SERVICE_DISABLED"}]}}, "api_disabled"),
    (403, {"error": {"details": [{"reason": "BILLING_DISABLED"}]}}, "billing_required"),
    (403, {}, "permission_denied"),
    (404, {}, "model_not_found"),
    (429, {}, "rate_limited"),
    (503, None, "http_503"),
])
def test_http_failures_are_classified_the_same_for_every_provider(status, payload, reason):
    assert classify_http_failure(status, payload) == reason


@pytest.mark.parametrize("status", [401, 402, 403, 404, 400])
def test_auth_and_client_errors_are_never_retried(status):
    calls, clock = [], Clock()

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": KEY}})
    with pytest.raises(LlmUnavailable) as info:
        _ds(handler, clock).complete_json(system="s", user="u", schema=SCHEMA)
    assert len(calls) == 1 and clock.sleeps == [] and info.value.attempts == 1
    assert KEY not in str(info.value)  # the provider's message (which may echo input) is never carried


def test_429_is_retried_with_bounded_backoff_then_succeeds():
    clock, responses = Clock(), [httpx.Response(429, json={}), httpx.Response(503, json={})]
    ok = _ds_ok(json.dumps({"status": "generated"}))

    def handler(request):
        return responses.pop(0) if responses else ok(request)
    completion = _ds(handler, clock).complete_json(system="s", user="u", schema=SCHEMA)
    assert completion.attempts == 3 and clock.sleeps == [0.1, 0.2]


def test_retry_after_is_honoured_but_capped():
    clock, responses = Clock(), [httpx.Response(429, json={}, headers={"retry-after": "60"})]
    ok = _ds_ok(json.dumps({"status": "generated"}))
    completion = _ds(lambda r: responses.pop(0) if responses else ok(r), clock).complete_json(
        system="s", user="u", schema=SCHEMA)
    assert completion.attempts == 2 and clock.sleeps == [4.0]


def test_retries_stop_at_the_limit():
    calls, clock = [], Clock()

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={})
    with pytest.raises(LlmUnavailable) as info:
        _ds(handler, clock, max_retries=2).complete_json(system="s", user="u", schema=SCHEMA)
    assert info.value.reason == "http_500" and len(calls) == 3 and info.value.attempts == 3


def test_the_total_deadline_cancels_further_attempts():
    clock = Clock()

    def handler(request):
        clock.now += 19.95          # the first attempt used almost the whole 20 s budget
        return httpx.Response(429, json={})
    with pytest.raises(LlmUnavailable) as info:
        _ds(handler, clock).complete_json(system="s", user="u", schema=SCHEMA)
    assert info.value.reason == "rate_limited" and info.value.attempts == 1 and clock.sleeps == []


def test_transport_timeout_never_echoes_the_key():
    def handler(request):
        raise httpx.ReadTimeout(f"timed out {KEY}", request=request)
    with pytest.raises(LlmUnavailable) as info:
        _ds(handler, max_retries=0).complete_json(system="s", user="u", schema=SCHEMA)
    assert info.value.reason == "timeout" and KEY not in str(info.value) and info.value.__cause__ is None


# -- models.list ------------------------------------------------------------------------

def test_models_list_for_both_providers():
    ds = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "object": "list", "data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-flash"}]})))
    assert list_models(_ds_settings(), http=ds) == ["deepseek-flash", "deepseek-v4-pro"]
    seen = {}

    def gemini(request):
        seen["key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"models": [{"name": "models/gemini-x-flash"}, {"name": "models/gemini-y"}]})
    g = LlmSettings(provider="gemini", model="m", api_key=GKEY)
    assert list_models(g, http=httpx.Client(transport=httpx.MockTransport(gemini))) == ["gemini-x-flash", "gemini-y"]
    assert seen["key"] == GKEY


def test_models_list_reports_the_credential_type_failure_once():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"details": [{"reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}})
    g = LlmSettings(provider="gemini", model="m", api_key=GKEY)
    with pytest.raises(LlmUnavailable, match="credential_type_unsupported"):
        list_models(g, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert calls == [1]


# -- the same RAG gates for DeepSeek output -------------------------------------------------

def test_deepseek_output_goes_through_the_same_grounding_gates():
    from rag_qa import RagQuestionService
    from recommendation.rag import GroundingFailed
    from tests.test_rag_qa import GOOD_RECOMMEND, Carbon, _ask, gate

    good = _ds(_ds_ok(json.dumps(GOOD_RECOMMEND)))
    body = _ask(RagQuestionService(carbon_service=Carbon(), llm_client=good, write_gate=gate()), "recommend")
    assert body["status"] == "generated" and body["provenance"]["answer_source"] == "model_generated"
    invented = {**GOOD_RECOMMEND, "recommendations": [{**GOOD_RECOMMEND["recommendations"][0],
                                                        "rule_code": "pest.spray_now"}]}
    with pytest.raises(GroundingFailed):
        _ask(RagQuestionService(carbon_service=Carbon(), llm_client=_ds(_ds_ok(json.dumps(invented))),
                                write_gate=gate()), "recommend")
    raw_number = {**GOOD_RECOMMEND, "answer": "Phát thải giảm 600 kg."}
    with pytest.raises(GroundingFailed):
        _ask(RagQuestionService(carbon_service=Carbon(), llm_client=_ds(_ds_ok(json.dumps(raw_number))),
                                write_gate=gate()), "recommend")


# -- scripts/verify_llm_provider.py ------------------------------------------------------

def _verify(env, handler, *argv):
    import scripts.verify_llm_provider as verify
    return verify.main(list(argv), env=env, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_verify_reports_a_credential_type_failure_once_without_the_key(capsys):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"details": [{"reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}})
    assert _verify({"RAG_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": GKEY}, handler) == 4
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "credential_type_unsupported" and out["blocked"] == "BLOCKED_GEMINI_KEY"
    assert out["key_source"] == "GEMINI_API_KEY" and GKEY not in json.dumps(out) and calls == [1]


def test_verify_lists_models_and_checks_the_configured_one(capsys):
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]})
    env = {"RAG_LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": KEY, "DEEPSEEK_MODEL": "deepseek-flash"}
    assert _verify(env, handler) == 0
    assert json.loads(capsys.readouterr().out)["configured_model_listed"] is True
    assert _verify({**env, "DEEPSEEK_MODEL": "deepseek-chat"}, handler) == 3  # a model the key cannot use


def test_verify_without_a_deepseek_key_is_a_config_error(capsys):
    assert _verify({"RAG_LLM_PROVIDER": "deepseek", "GEMINI_API_KEY": GKEY},
                   lambda r: httpx.Response(200, json={})) == 4
    assert GKEY not in capsys.readouterr().out
