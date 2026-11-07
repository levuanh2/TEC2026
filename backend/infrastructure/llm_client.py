"""Provider adapters for structured (JSON) model output — I/O only, no RAG policy.

The RAG policy (system prompt, what the model may see, how the answer is validated) lives in
`rag_qa.py` and `recommendation/rag/`; this module only sends one request to one provider and
returns the parsed JSON object plus usage. It knows nothing about seasons, facts or tenants,
holds no database client and never logs prompt text, evidence or keys. Every provider's output
goes through the SAME downstream chain (Pydantic schema -> D8 capability gate -> fact references
-> citations -> grounding -> trusted rendering); a JSON object that parses is never "grounded".

Providers (one interface, `StructuredLlmClient.complete_json`):
  gemini    Gemini Developer API `generateContent`, `x-goog-api-key` header,
            `responseMimeType=application/json` + `responseSchema`.
  deepseek  DeepSeek Chat Completions (`{base}/chat/completions`), `Authorization: Bearer`,
            `response_format={"type": "json_object"}` (the system prompt states the schema and
            the word JSON, as JSON mode requires); thinking disabled unless configured.

Configuration is server-side environment only (never a request field, never a default model):

  RAG_LLM_PROVIDER            ""/unset = disabled | "gemini" | "deepseek"
  RAG_LLM_MODEL               model id; else GEMINI_MODEL / DEEPSEEK_MODEL for THAT provider
  RAG_LLM_API_KEY             key; else GEMINI_API_KEY / DEEPSEEK_API_KEY for THAT provider
                              (precedence: RAG_LLM_* first; a provider never reads the other
                              provider's variable, so a Gemini key cannot reach DeepSeek)
  RAG_LLM_BASE_URL            optional https override (default per provider)
  RAG_LLM_TIMEOUT_SECONDS     default 20 — TOTAL deadline across retries (cancellation)
  RAG_LLM_MAX_RETRIES         default 2 — only for 429 / 5xx / timeout / transport, bounded
                              backoff, Retry-After honoured within the deadline; never for auth
  RAG_LLM_MAX_OUTPUT_TOKENS   default 1024
  RAG_LLM_MAX_INPUT_CHARS     default 24000 (system + user text; larger requests are refused)
  RAG_LLM_THINKING_BUDGET     gemini 2.x: optional int (0 disables where supported)
  RAG_LLM_THINKING_LEVEL      gemini 3.x: optional level (e.g. minimal | low | high); never both
  RAG_LLM_THINKING            deepseek: "disabled" (default) | "enabled" | "omit"
  RAG_LLM_PRICE_INPUT_USD_PER_MTOK / RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK
  RAG_LLM_PRICE_INPUT_CACHE_HIT_USD_PER_MTOK   optional (DeepSeek cache-hit input price)
                              cost accounting only; any missing price -> cost unknown (None)
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

SUPPORTED_PROVIDERS = frozenset({"gemini", "deepseek"})
DEFAULT_BASE_URLS = {"gemini": "https://generativelanguage.googleapis.com/v1beta",
                     "deepseek": "https://api.deepseek.com"}
#: Provider-specific fallbacks, read ONLY for that provider (see precedence above).
PROVIDER_KEY_ENV = {"gemini": "GEMINI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
PROVIDER_MODEL_ENV = {"gemini": "GEMINI_MODEL", "deepseek": "DEEPSEEK_MODEL"}
DEEPSEEK_THINKING = frozenset({"disabled", "enabled", "omit"})
# Kept for callers that formatted the Gemini URL themselves.
GEMINI_ENDPOINT = DEFAULT_BASE_URLS["gemini"] + "/models/{model}:generateContent"

#: Failures worth another attempt; everything else (auth, permission, billing, unknown model,
#: bad request, unusable output) fails at once.
RETRYABLE = frozenset({"rate_limited", "timeout", "transport_error", "http_500", "http_502", "http_503",
                       "http_504"})
_BACKOFF_CAP_SECONDS = 4.0


class LlmUnavailable(Exception):
    """The provider could not produce a usable structured answer. `reason` is a short stable
    code (see `classify_http_failure` and the parsers); `attempts` how many requests were sent."""

    def __init__(self, reason: str, attempts: int = 1):
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts


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
    price_input_cache_hit_usd_per_mtok: float | None = None
    base_url: str | None = None
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    thinking: str = "disabled"
    thinking_level: str | None = None
    #: Which environment variable the key came from (a NAME, never the value).
    key_source: str = "RAG_LLM_API_KEY"

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise LlmConfigError(f"unsupported provider {self.provider!r}")
        if not self.model.strip() or not self.api_key.strip():
            raise LlmConfigError("a model and an API key are required for the configured provider")
        if not (0 < self.timeout_seconds <= 120):
            raise LlmConfigError("timeout must be in (0, 120] seconds")
        if not (64 <= self.max_output_tokens <= 8192) or not (1000 <= self.max_input_chars <= 200_000):
            raise LlmConfigError("token/char budget out of range")
        if not (0 <= self.max_retries <= 5) or not (0 <= self.retry_backoff_seconds <= 5):
            raise LlmConfigError("retries must be in [0, 5] with a backoff in [0, 5] s")
        if self.thinking_budget is not None and self.thinking_level is not None:
            raise LlmConfigError("set RAG_LLM_THINKING_BUDGET or RAG_LLM_THINKING_LEVEL, not both (Gemini 400)")
        if self.thinking not in DEEPSEEK_THINKING:
            raise LlmConfigError("RAG_LLM_THINKING must be disabled, enabled or omit")
        if self.base_url is not None and not self.base_url.startswith("https://"):
            raise LlmConfigError("RAG_LLM_BASE_URL must be https")
        for price in (self.price_input_usd_per_mtok, self.price_output_usd_per_mtok,
                      self.price_input_cache_hit_usd_per_mtok):
            if price is not None and (not math.isfinite(price) or price < 0):
                raise LlmConfigError("prices must be finite and non-negative")

    @property
    def endpoint_base(self) -> str:
        return (self.base_url or DEFAULT_BASE_URLS[self.provider]).rstrip("/")

    def __repr__(self) -> str:  # never print the key
        return (f"LlmSettings(provider={self.provider!r}, model={self.model!r}, api_key=***, "
                f"key_source={self.key_source!r})")

    __str__ = __repr__


def _optional_float(env: Mapping[str, str], name: str) -> float | None:
    raw = (env.get(name) or "").strip()
    return float(raw) if raw else None


def _first(env: Mapping[str, str], *names: str) -> tuple[str, str]:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value, name
    return "", names[0]


def load_llm_settings(env: Mapping[str, str] | None = None) -> LlmSettings | None:
    """None when no provider is configured (the feature stays off)."""
    env = os.environ if env is None else env
    provider = (env.get("RAG_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        return None
    if provider not in SUPPORTED_PROVIDERS:
        raise LlmConfigError(f"unsupported provider {provider!r}")
    api_key, key_source = _first(env, "RAG_LLM_API_KEY", PROVIDER_KEY_ENV[provider])
    model, _ = _first(env, "RAG_LLM_MODEL", PROVIDER_MODEL_ENV[provider])
    thinking = (env.get("RAG_LLM_THINKING_BUDGET") or "").strip()
    return LlmSettings(
        provider=provider, model=model, api_key=api_key, key_source=key_source,
        timeout_seconds=float(env.get("RAG_LLM_TIMEOUT_SECONDS") or 20),
        max_output_tokens=int(env.get("RAG_LLM_MAX_OUTPUT_TOKENS") or 1024),
        max_input_chars=int(env.get("RAG_LLM_MAX_INPUT_CHARS") or 24000),
        max_retries=int(env.get("RAG_LLM_MAX_RETRIES") or 2),
        thinking_budget=int(thinking) if thinking else None,
        thinking=(env.get("RAG_LLM_THINKING") or "disabled").strip().lower(),
        thinking_level=(env.get("RAG_LLM_THINKING_LEVEL") or "").strip().lower() or None,
        base_url=(env.get("RAG_LLM_BASE_URL") or "").strip() or None,
        price_input_usd_per_mtok=_optional_float(env, "RAG_LLM_PRICE_INPUT_USD_PER_MTOK"),
        price_output_usd_per_mtok=_optional_float(env, "RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK"),
        price_input_cache_hit_usd_per_mtok=_optional_float(env, "RAG_LLM_PRICE_INPUT_CACHE_HIT_USD_PER_MTOK"),
    )


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    #: Input tokens served from / missing the provider's prompt cache (DeepSeek reports both).
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None


@dataclass(frozen=True)
class LlmCompletion:
    data: dict[str, Any]
    usage: LlmUsage
    latency_ms: int
    model: str
    finish_reason: str | None
    #: What the provider says actually answered (e.g. Gemini `modelVersion`, DeepSeek `model`).
    model_version: str | None = None
    provider: str | None = None
    attempts: int = 1


class StructuredLlmClient(Protocol):
    def complete_json(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmCompletion: ...


def compute_cost(settings: LlmSettings, input_tokens: int | None, output_tokens: int | None, *,
                 cache_hit_tokens: int | None = None, cache_miss_tokens: int | None = None) -> float | None:
    """USD for one call, or None (COST_UNKNOWN) when a needed price or count is missing.
    Cache-hit input is priced separately only when its price is configured and the provider
    reported the split; otherwise every input token is billed at the (miss) input price."""
    if settings.price_input_usd_per_mtok is None or settings.price_output_usd_per_mtok is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None
    out = output_tokens * settings.price_output_usd_per_mtok
    if (settings.price_input_cache_hit_usd_per_mtok is not None and cache_hit_tokens is not None
            and cache_miss_tokens is not None):
        inp = (cache_hit_tokens * settings.price_input_cache_hit_usd_per_mtok
               + cache_miss_tokens * settings.price_input_usd_per_mtok)
    else:
        inp = input_tokens * settings.price_input_usd_per_mtok
    return (inp + out) / 1e6


def _error_reasons(payload: Any) -> tuple[str, str]:
    """(google `status`, joined `details[].reason`) or the DeepSeek/OpenAI error type/code."""
    if not isinstance(payload, Mapping):
        return "", ""
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return "", ""
    reasons = [str(d.get("reason")) for d in error.get("details") or () if isinstance(d, Mapping) and d.get("reason")]
    reasons += [str(error[k]) for k in ("type", "code") if isinstance(error.get(k), str)]
    return str(error.get("status") or ""), " ".join(reasons)


def classify_http_failure(status: int, payload: Any) -> str:
    """One stable, secret-free code per failure class, the same for every provider."""
    google_status, reasons = _error_reasons(payload)
    if status == 401:
        return "credential_type_unsupported" if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in reasons else "auth_invalid"
    if status == 402:
        return "insufficient_balance"
    if status == 403:
        if "SERVICE_DISABLED" in reasons or "API_DISABLED" in reasons:
            return "api_disabled"
        if "BILLING" in reasons.upper():
            return "billing_required"
        return "permission_denied"
    if status == 404:
        return "model_not_found"
    if status == 429:
        return "rate_limited"
    if status == 400 and "API_KEY_INVALID" in reasons:
        return "auth_invalid"
    return f"http_{status}"


def _schema_for_prompt(schema: Any) -> Any:
    """Gemini-style schema (OBJECT/STRING) rendered as plain JSON-schema type names."""
    if isinstance(schema, Mapping):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _schema_for_prompt(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_schema_for_prompt(item) for item in schema]
    return schema


@dataclass
class _HttpJsonClient:
    """Shared request loop: input budget, total deadline, bounded retries, error mapping."""

    settings: LlmSettings
    http: Any | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    provider: ClassVar[str] = ""

    def __post_init__(self) -> None:
        if self.settings.provider != self.provider:
            raise LlmConfigError(f"{type(self).__name__} needs provider {self.provider!r}")
        if self.http is None:
            import httpx
            self.http = httpx.Client(timeout=self.settings.timeout_seconds)

    # -- provider hooks ------------------------------------------------------------------
    def _request(self, system: str, user: str, schema: Mapping[str, Any]) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def _parse(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], LlmUsage, str | None, str | None]:
        raise NotImplementedError

    # -- shared loop -----------------------------------------------------------------------
    def complete_json(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmCompletion:
        settings = self.settings
        if len(system) + len(user) > settings.max_input_chars:
            raise LlmUnavailable("input_budget_exceeded", attempts=0)
        url, body, headers = self._request(system, user, schema)
        deadline = self.clock() + settings.timeout_seconds
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise LlmUnavailable("timeout", attempts=attempt - 1)
            started = time.perf_counter()
            reason, retry_after, response = None, None, None
            try:
                response = self.http.post(url, json=body, headers=headers, timeout=remaining)
            except Exception as exc:  # noqa: BLE001 - transport boundary: the class name only, never URL/key
                reason = "timeout" if "Timeout" in type(exc).__name__ else "transport_error"
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response is not None and response.status_code >= 400:
                try:
                    error_payload = response.json()
                except ValueError:
                    error_payload = None
                reason = classify_http_failure(response.status_code, error_payload)
                retry_after = _retry_after(response)
            if reason is None:
                break
            if reason not in RETRYABLE or attempt > settings.max_retries:
                raise LlmUnavailable(reason, attempts=attempt)
            wait = min(_BACKOFF_CAP_SECONDS, retry_after if retry_after is not None
                       else settings.retry_backoff_seconds * (2 ** (attempt - 1)))
            if self.clock() + wait >= deadline:
                raise LlmUnavailable(reason, attempts=attempt)
            self.sleep(wait)
        try:
            payload = response.json()
        except ValueError:
            raise LlmUnavailable("non_json_response", attempts=attempt) from None
        data, usage, finish, model_version = self._parse(payload)
        return LlmCompletion(data=data, usage=usage, latency_ms=latency_ms, model=settings.model,
                             finish_reason=finish, model_version=model_version, provider=self.provider,
                             attempts=attempt)


def _retry_after(response: Any) -> float | None:
    raw = (getattr(response, "headers", {}) or {}).get("retry-after")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def _json_object(text: str, *, attempts: int = 1) -> dict[str, Any]:
    if not text or not text.strip():
        raise LlmUnavailable("empty_output", attempts=attempts)
    try:
        data = json.loads(text)
    except ValueError:
        raise LlmUnavailable("invalid_json", attempts=attempts) from None
    if not isinstance(data, dict):
        raise LlmUnavailable("invalid_json", attempts=attempts)
    return data


class GeminiStructuredClient(_HttpJsonClient):
    """Gemini Developer API `generateContent` with `responseMimeType=application/json` +
    `responseSchema`. Policy goes in `systemInstruction`; request data (question, facts,
    evidence) in the user turn as one JSON document, so retrieved text never becomes
    instructions. `http` is an injectable `httpx.Client` (tests use a mock transport)."""

    provider = "gemini"

    def __init__(self, settings: LlmSettings, http: Any | None = None, **kwargs: Any) -> None:
        super().__init__(settings, http, **kwargs)

    def _request(self, system, user, schema):
        settings = self.settings
        config: dict[str, Any] = {"responseMimeType": "application/json", "responseSchema": dict(schema),
                                  "maxOutputTokens": settings.max_output_tokens, "temperature": 0}
        if settings.thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": settings.thinking_budget}
        elif settings.thinking_level is not None:
            config["thinkingConfig"] = {"thinkingLevel": settings.thinking_level}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": config}
        url = f"{settings.endpoint_base}/models/{settings.model}:generateContent"
        return url, body, {"x-goog-api-key": settings.api_key}

    def _parse(self, payload):
        meta = payload.get("usageMetadata") or {}
        input_tokens, output_tokens = meta.get("promptTokenCount"), meta.get("candidatesTokenCount")
        if output_tokens is not None and meta.get("thoughtsTokenCount"):
            output_tokens += meta["thoughtsTokenCount"]  # billed as output
        cached = meta.get("cachedContentTokenCount")
        usage = LlmUsage(input_tokens, output_tokens, meta.get("totalTokenCount"),
                         compute_cost(self.settings, input_tokens, output_tokens), cache_hit_tokens=cached)
        candidates = payload.get("candidates") or []
        if not candidates:
            raise LlmUnavailable("no_candidate")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish not in (None, "STOP"):
            raise LlmUnavailable(f"finish_{str(finish).lower()}")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, Mapping) and not part.get("thought"))
        return _json_object(text), usage, finish, payload.get("modelVersion")


DEEPSEEK_JSON_INSTRUCTION = (
    "\n\nĐịnh dạng đầu ra: chỉ một đối tượng JSON hợp lệ (json), không có văn bản nào khác, theo lược đồ sau:\n"
)


class DeepSeekStructuredClient(_HttpJsonClient):
    """DeepSeek Chat Completions in JSON mode. The schema is stated in the system message
    (JSON mode does not enforce one); the result is validated downstream like any provider's.
    Thinking is disabled by default (`RAG_LLM_THINKING`): low-latency RAG answers."""

    provider = "deepseek"

    def __init__(self, settings: LlmSettings, http: Any | None = None, **kwargs: Any) -> None:
        super().__init__(settings, http, **kwargs)

    def _request(self, system, user, schema):
        settings = self.settings
        instruction = system + DEEPSEEK_JSON_INSTRUCTION + json.dumps(_schema_for_prompt(schema), ensure_ascii=False)
        body: dict[str, Any] = {
            "model": settings.model,
            "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "max_tokens": settings.max_output_tokens,
            "temperature": 0,
            "stream": False,
        }
        if settings.thinking != "omit":
            body["thinking"] = {"type": settings.thinking}
        return (f"{settings.endpoint_base}/chat/completions", body,
                {"Authorization": f"Bearer {settings.api_key}"})

    def _parse(self, payload):
        meta = payload.get("usage") or {}
        input_tokens, output_tokens = meta.get("prompt_tokens"), meta.get("completion_tokens")
        hit, miss = meta.get("prompt_cache_hit_tokens"), meta.get("prompt_cache_miss_tokens")
        usage = LlmUsage(input_tokens, output_tokens, meta.get("total_tokens"),
                         compute_cost(self.settings, input_tokens, output_tokens, cache_hit_tokens=hit,
                                      cache_miss_tokens=miss),
                         cache_hit_tokens=hit, cache_miss_tokens=miss)
        choices = payload.get("choices") or []
        if not choices:
            raise LlmUnavailable("no_candidate")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish not in (None, "stop"):
            raise LlmUnavailable(f"finish_{str(finish).lower()}")  # "length" = truncated
        content = (choice.get("message") or {}).get("content")
        return _json_object(content if isinstance(content, str) else ""), usage, finish, payload.get("model")


CLIENTS: dict[str, type[_HttpJsonClient]] = {"gemini": GeminiStructuredClient, "deepseek": DeepSeekStructuredClient}


def build_llm_client(settings: LlmSettings | None, **kwargs: Any) -> StructuredLlmClient | None:
    """Provider factory. No automatic fallback to another provider: a request is never resent
    to a second provider (its data-processing terms are approved separately)."""
    if settings is None:
        return None
    return CLIENTS[settings.provider](settings, **kwargs)


def list_models(settings: LlmSettings, http: Any | None = None) -> list[str]:
    """Model ids the configured credential may use (Gemini `models.list`, DeepSeek `GET /models`).
    Costs no tokens. One request, no retry: an auth failure is reported, not retried."""
    if http is None:
        import httpx
        http = httpx.Client(timeout=settings.timeout_seconds)
    if settings.provider == "gemini":
        url, headers, params = f"{settings.endpoint_base}/models", {"x-goog-api-key": settings.api_key}, {"pageSize": 1000}
    else:
        url, headers, params = f"{settings.endpoint_base}/models", {"Authorization": f"Bearer {settings.api_key}"}, None
    try:
        response = http.get(url, headers=headers, params=params, timeout=settings.timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        raise LlmUnavailable("timeout" if "Timeout" in type(exc).__name__ else "transport_error") from None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400:
        raise LlmUnavailable(classify_http_failure(response.status_code, payload))
    if settings.provider == "gemini":
        return sorted(str(m.get("name", "")).removeprefix("models/") for m in (payload or {}).get("models", []))
    return sorted(str(m.get("id", "")) for m in (payload or {}).get("data", []))
