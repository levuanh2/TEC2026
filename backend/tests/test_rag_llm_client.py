"""Provider adapter (infrastructure/llm_client.py) with a mock HTTP transport — no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.llm_client import (  # noqa: E402
    GeminiStructuredClient,
    LlmConfigError,
    LlmSettings,
    LlmUnavailable,
    load_llm_settings,
)

KEY = "test-key-not-real"


def _settings(**overrides):
    base = dict(provider="gemini", model="model-under-test", api_key=KEY, price_input_usd_per_mtok=0.5,
                price_output_usd_per_mtok=2.0)
    base.update(overrides)
    return LlmSettings(**base)


def _client(handler, **overrides):
    return GeminiStructuredClient(_settings(**overrides), http=httpx.Client(transport=httpx.MockTransport(handler)))


def _ok(data, *, finish="STOP", usage=None):
    def handler(request):
        handler.request = request
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}, "finishReason": finish}],
            "usageMetadata": usage or {"promptTokenCount": 1000, "candidatesTokenCount": 200, "totalTokenCount": 1200},
        })
    return handler


def test_disabled_without_a_provider():
    assert load_llm_settings({}) is None
    assert load_llm_settings({"RAG_LLM_PROVIDER": "  "}) is None


@pytest.mark.parametrize("env", [
    {"RAG_LLM_PROVIDER": "gemini"},
    {"RAG_LLM_PROVIDER": "gemini", "RAG_LLM_MODEL": "m"},
    {"RAG_LLM_PROVIDER": "openrouter", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": "k"},
    {"RAG_LLM_PROVIDER": "gemini", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": "k", "RAG_LLM_TIMEOUT_SECONDS": "0"},
    {"RAG_LLM_PROVIDER": "gemini", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": "k", "RAG_LLM_MAX_OUTPUT_TOKENS": "9"},
    {"RAG_LLM_PROVIDER": "gemini", "RAG_LLM_MODEL": "m", "RAG_LLM_API_KEY": "k",
     "RAG_LLM_PRICE_INPUT_USD_PER_MTOK": "-1", "RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK": "1"},
])
def test_misconfiguration_is_refused(env):
    with pytest.raises(LlmConfigError):
        load_llm_settings(env)


def test_settings_never_print_the_key():
    assert KEY not in repr(_settings()) and KEY not in str(_settings())


def test_policy_goes_to_the_instruction_channel_and_data_to_the_user_turn():
    handler = _ok({"status": "generated", "answer": "x"})
    _client(handler).complete_json(system="POLICY", user='{"request": "DATA"}', schema={"type": "OBJECT"})
    body = json.loads(handler.request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "POLICY"
    assert body["contents"][0]["parts"][0]["text"] == '{"request": "DATA"}'
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0
    assert handler.request.headers["x-goog-api-key"] == KEY and KEY not in str(handler.request.url)


def test_usage_and_cost_are_accounted():
    completion = _client(_ok({"status": "generated", "answer": "x"})).complete_json(system="s", user="u", schema={})
    assert completion.usage.input_tokens == 1000 and completion.usage.output_tokens == 200
    assert completion.usage.cost_usd == pytest.approx((1000 * 0.5 + 200 * 2.0) / 1e6)


def test_thinking_tokens_are_billed_as_output():
    usage = {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 7, "totalTokenCount": 22}
    completion = _client(_ok({"a": 1}, usage=usage)).complete_json(system="s", user="u", schema={})
    assert completion.usage.output_tokens == 12


def test_cost_is_unknown_without_prices():
    client = _client(_ok({"a": 1}), price_input_usd_per_mtok=None, price_output_usd_per_mtok=None)
    assert client.complete_json(system="s", user="u", schema={}).usage.cost_usd is None


def test_input_budget_is_enforced_before_any_request():
    def handler(request):
        raise AssertionError("must not be sent")
    with pytest.raises(LlmUnavailable, match="input_budget_exceeded"):
        _client(handler, max_input_chars=1000).complete_json(system="s" * 600, user="u" * 600, schema={})


@pytest.mark.parametrize("response, reason", [
    (httpx.Response(429, json={}), "rate_limited"),
    (httpx.Response(500, json={}), "http_500"),
    (httpx.Response(200, text="not json"), "non_json_response"),
    (httpx.Response(200, json={"candidates": []}), "no_candidate"),
    (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "MAX_TOKENS"}]}),
     "finish_max_tokens"),
    (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "SAFETY"}]}),
     "finish_safety"),
    (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "[1]"}]}, "finishReason": "STOP"}]}),
     "invalid_json"),
    (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{bad"}]}, "finishReason": "STOP"}]}),
     "invalid_json"),
])
def test_provider_failures_are_typed(response, reason):
    with pytest.raises(LlmUnavailable) as info:
        _client(lambda request: response).complete_json(system="s", user="u", schema={})
    assert info.value.reason == reason


def test_timeouts_are_typed_and_never_echo_the_key():
    def handler(request):
        raise httpx.ReadTimeout(f"timed out {KEY}", request=request)
    with pytest.raises(LlmUnavailable) as info:
        _client(handler).complete_json(system="s", user="u", schema={})
    assert info.value.reason == "timeout" and KEY not in str(info.value) and info.value.__cause__ is None
