"""Verify the configured RAG provider credential WITHOUT spending tokens and without printing it.

One `models.list` (Gemini) / `GET /models` (DeepSeek) request — no retry: an auth failure is
reported once with its class, never retried or worked around, and no other key is looked
for. Reads the same server-side variables as the API (RAG_LLM_* first, then GEMINI_* or
DEEPSEEK_* for that provider only). RAG_LLM_MODEL is optional here; when set it must be
listed.

  RAG_LLM_PROVIDER=deepseek python backend/scripts/verify_llm_provider.py
  RAG_LLM_PROVIDER=gemini   python backend/scripts/verify_llm_provider.py --flash

Exit 0 = credential valid (and the model listed), 3 = model not listed, 4 = credential or
access failure, 2 = no provider configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.llm_client import (  # noqa: E402
    PROVIDER_KEY_ENV,
    LlmConfigError,
    LlmUnavailable,
    list_models,
    load_llm_settings,
)

ADVICE = {
    "credential_type_unsupported": "the endpoint refuses this credential TYPE (e.g. not an API key of this "
                                   "service). Create a key for this provider's API; do not reuse another service's.",
    "auth_invalid": "the key is not valid for this provider (revoked, mistyped or for another service).",
    "insufficient_balance": "the provider account has no balance.",
    "api_disabled": "the API is not enabled in the key's project.",
    "billing_required": "billing is not enabled for the key's project.",
    "permission_denied": "the key may not use this API/model.",
    "rate_limited": "rate-limited while listing models; try again later (this script does not retry).",
}


def main(argv: list[str] | None = None, env: dict | None = None, http=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--flash", action="store_true", help="print only Flash / Flash-Lite model ids")
    args = parser.parse_args(argv)
    env = dict(os.environ if env is None else env)
    if (env.get("RAG_LLM_PROVIDER") or "").strip() and not ((env.get("RAG_LLM_MODEL") or "").strip()
                                                         or env.get("GEMINI_MODEL") or env.get("DEEPSEEK_MODEL")):
        env["RAG_LLM_MODEL"] = "(listing only)"
    try:
        settings = load_llm_settings(env)
    except LlmConfigError as exc:
        print(json.dumps({"status": "CONFIG_ERROR", "detail": str(exc)}))
        return 4
    if settings is None:
        print(json.dumps({"status": "NO_PROVIDER"}))
        return 2
    report = {"provider": settings.provider, "key_source": settings.key_source,
              "key_length": len(settings.api_key), "endpoint": settings.endpoint_base}
    try:
        models = list_models(settings, http=http)
    except LlmUnavailable as exc:
        report.update(status="CREDENTIAL_FAILED", reason=exc.reason, advice=ADVICE.get(exc.reason, ""),
                      blocked=f"BLOCKED_{settings.provider.upper()}_KEY")
        print(json.dumps(report, ensure_ascii=False))
        return 4
    shown = [m for m in models if "flash" in m.lower()] if args.flash else models
    report.update(status="OK", models=shown, model_count=len(models))
    wanted = settings.model if settings.model != "(listing only)" else None
    if wanted:
        report["configured_model_listed"] = wanted in models
    print(json.dumps(report, ensure_ascii=False))
    return 3 if wanted and wanted not in models else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "PROVIDER_KEY_ENV"]
