"""Provider adapter for structured (JSON-schema) model output — I/O only, no RAG policy.

The RAG policy (system prompt, what the model may see, how the answer is validated) lives in
`rag_qa.py` and `recommendation/rag/`; this module only sends one request to one provider and
returns the parsed JSON object plus usage. It knows nothing about seasons, facts or tenants,
holds no database client and never logs prompt text, evidence or keys.

Configuration is server-side environment only (never a request field, never a default model
name in the domain layer):

  RAG_LLM_PROVIDER            ""/unset = disabled | "gemini"
  RAG_LLM_MODEL               required when a provider is set
  RAG_LLM_API_KEY             required when a provider is set
  RAG_LLM_TIMEOUT_SECONDS     default 20
  RAG_LLM_MAX_OUTPUT_TOKENS   default 1024
  RAG_LLM_MAX_INPUT_CHARS     default 24000 (system + user text; larger requests are refused)
  RAG_LLM_THINKING_BUDGET     optional int (provider "thinking" tokens; 0 disables where supported)
  RAG_LLM_PRICE_INPUT_USD_PER_MTOK / RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK
                              optional, for cost accounting only; unset -> cost is unknown
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SUPPORTED_PROVIDERS = frozenset({"gemini"})


class LlmUnavailable(Exception):
    """The provider could not produce a usable structured answer (timeout, HTTP error,
    blocked or truncated output, non-JSON, budget). `reason` is a short stable code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LlmConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    model: str
    api_key: str
    timeout_seconds: float = 20.0
    max_output_tokens: int = 1024
    max_input_chars: int = 24000
    thinking_budget: int | None = None
    price_input_usd_per_mtok: float | None = None
    price_output_usd_per_mtok: float | None = None

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise LlmConfigError(f"unsupported provider {self.provider!r}")
        if not self.model.strip() or not self.api_key.strip():
            raise LlmConfigError("RAG_LLM_MODEL and RAG_LLM_API_KEY are required")
        if not (0 < self.timeout_seconds <= 120):
            raise LlmConfigError("timeout must be in (0, 120] seconds")
        if not (64 <= self.max_output_tokens <= 8192) or not (1000 <= self.max_input_chars <= 200_000):
            raise LlmConfigError("token/char budget out of range")
        for price in (self.price_input_usd_per_mtok, self.price_output_usd_per_mtok):
            if price is not None and (not math.isfinite(price) or price < 0):
                raise LlmConfigError("prices must be finite and non-negative")

    def __repr__(self) -> str:  # never print the key
        return f"LlmSettings(provider={self.provider!r}, model={self.model!r}, api_key=***)"


def _optional_float(env: Mapping[str, str], name: str) -> float | None:
    raw = (env.get(name) or "").strip()
    return float(raw) if raw else None


def load_llm_settings(env: Mapping[str, str] | None = None) -> LlmSettings | None:
    """None when no provider is configured (the feature stays off)."""
    env = os.environ if env is None else env
    provider = (env.get("RAG_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        return None
    thinking = (env.get("RAG_LLM_THINKING_BUDGET") or "").strip()
    return LlmSettings(
        provider=provider, model=(env.get("RAG_LLM_MODEL") or "").strip(),
        api_key=(env.get("RAG_LLM_API_KEY") or "").strip(),
        timeout_seconds=float(env.get("RAG_LLM_TIMEOUT_SECONDS") or 20),
        max_output_tokens=int(env.get("RAG_LLM_MAX_OUTPUT_TOKENS") or 1024),
        max_input_chars=int(env.get("RAG_LLM_MAX_INPUT_CHARS") or 24000),
        thinking_budget=int(thinking) if thinking else None,
        price_input_usd_per_mtok=_optional_float(env, "RAG_LLM_PRICE_INPUT_USD_PER_MTOK"),
        price_output_usd_per_mtok=_optional_float(env, "RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK"),
    )


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None


@dataclass(frozen=True)
class LlmCompletion:
    data: dict[str, Any]
    usage: LlmUsage
    latency_ms: int
    model: str
    finish_reason: str | None


class StructuredLlmClient(Protocol):
    def complete_json(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmCompletion: ...


def _cost(settings: LlmSettings, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if settings.price_input_usd_per_mtok is None or settings.price_output_usd_per_mtok is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * settings.price_input_usd_per_mtok + output_tokens * settings.price_output_usd_per_mtok) / 1e6


class GeminiStructuredClient:
    """Gemini `generateContent` with `responseMimeType=application/json` + `responseSchema`.

    Policy text goes in `systemInstruction`; the request data (question, facts, evidence) goes
    in the user turn as one JSON document, so retrieved text never becomes instructions.
    `http` is an injectable `httpx.Client` (tests use a mock transport).
    """

    def __init__(self, settings: LlmSettings, http: Any | None = None) -> None:
        if settings.provider != "gemini":
            raise LlmConfigError("GeminiStructuredClient needs provider 'gemini'")
        self._settings = settings
        if http is None:
            import httpx
            http = httpx.Client(timeout=settings.timeout_seconds)
        self._http = http

    def complete_json(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmCompletion:
        settings = self._settings
        if len(system) + len(user) > settings.max_input_chars:
            raise LlmUnavailable("input_budget_exceeded")
        config: dict[str, Any] = {"responseMimeType": "application/json", "responseSchema": dict(schema),
                                  "maxOutputTokens": settings.max_output_tokens, "temperature": 0}
        if settings.thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": settings.thinking_budget}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": config}
        started = time.perf_counter()
        try:
            response = self._http.post(GEMINI_ENDPOINT.format(model=settings.model), json=body,
                                       headers={"x-goog-api-key": settings.api_key},
                                       timeout=settings.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - transport boundary; the class name only, never the URL/key
            name = type(exc).__name__
            raise LlmUnavailable("timeout" if "Timeout" in name else "transport_error") from None
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429:
            raise LlmUnavailable("rate_limited")
        if response.status_code >= 400:
            raise LlmUnavailable(f"http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise LlmUnavailable("non_json_response") from None
        meta = payload.get("usageMetadata") or {}
        input_tokens, output_tokens = meta.get("promptTokenCount"), meta.get("candidatesTokenCount")
        if output_tokens is not None and meta.get("thoughtsTokenCount"):
            output_tokens += meta["thoughtsTokenCount"]  # billed as output
        usage = LlmUsage(input_tokens, output_tokens, meta.get("totalTokenCount"),
                         _cost(settings, input_tokens, output_tokens))
        candidates = payload.get("candidates") or []
        if not candidates:
            raise LlmUnavailable("no_candidate")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish not in (None, "STOP"):
            raise LlmUnavailable(f"finish_{str(finish).lower()}")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, Mapping) and not part.get("thought"))
        try:
            data = json.loads(text)
        except ValueError:
            raise LlmUnavailable("invalid_json") from None
        if not isinstance(data, dict):
            raise LlmUnavailable("invalid_json")
        return LlmCompletion(data=data, usage=usage, latency_ms=latency_ms, model=settings.model, finish_reason=finish)


def build_llm_client(settings: LlmSettings | None) -> StructuredLlmClient | None:
    if settings is None:
        return None
    return GeminiStructuredClient(settings)
