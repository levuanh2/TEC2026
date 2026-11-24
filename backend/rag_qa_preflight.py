"""Offline start-up check of the season Q&A pilot configuration. Run it inside the CANDIDATE image,
with the production env-file and no network, BEFORE the running container is replaced:

    docker run --rm --network none --env-file /etc/agricarbon/api.env \
        -v <host file with the approved ids>:/run/cohort.txt:ro --entrypoint python \
        <candidate-image> -m rag_qa_preflight --expect-user-ids-file /run/cohort.txt

It uses the same parsers and the same service factory as main.py (rag_qa.pilot_cohort_from_env,
infrastructure.question_rate_limit, rag_qa.build_question_service), so a value main.py would
refuse at import is refused here first. It opens no connection (the rate-limit store and Auth are
never called) and prints no value from the environment: only names, counts and the approved limits.

A PASS here is a CONFIGURATION check only. It does not prove the database, Auth or the network are
reachable, nor that the API answers: that is the candidate container's start-up log and smoke.

Pilot rules (L1, READ-only): Q&A on, action tier off, LLM kill switch on, no provider configured,
rate-limit store postgres, and an explicit cohort of Auth user ids. "*" (everyone signed in) and an
empty cohort are refused. With --expect-user-ids-file, the cohort must equal that set exactly
(the ids derived from the owner-approved QA matrix); only the counts of missing / extra ids are shown.

Exit 0 = PASS, 1 = FAIL (one `FAIL <reason>` line each), 2 = usage error.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

#: Env names that carry provider credentials. Their presence is refused for the pilot; their values
#: are never read here.
PROVIDER_CREDENTIAL_ENV = ("RAG_LLM_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY")


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() == "true"


def _read_expected_ids(path: Path) -> frozenset[str]:
    """One UUID per line or comma-separated; blank lines and `#` comments ignored."""
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        for part in line.split(","):
            part = part.strip()
            if part:
                ids.add(str(uuid.UUID(part)))
    return frozenset(ids)


def check(*, expected_ids: frozenset[str] | None = None,
          load_settings: Callable[[], Any] | None = None) -> tuple[list[str], dict[str, Any]]:
    """Returns (failures, facts). `facts` holds only names, counts and limits."""
    import rag_qa
    from infrastructure import question_rate_limit as qrl

    failures: list[str] = []
    facts: dict[str, Any] = {}

    # First, as main.py does at import (`settings = load_settings()` before any RAG_* read): it may
    # add values from a backend/.env inside the image to the environment, and everything below must
    # see exactly the environment main.py will see.
    if load_settings is None:
        from infrastructure.config import load_settings
    settings = load_settings()

    if not _flag("RAG_QA_ENABLED"):
        failures.append("RAG_QA_ENABLED is not true (Q&A would stay off: 503 backend_not_configured)")
    if rag_qa.action_tier_enabled_from_env():
        failures.append("RAG_QA_ACTION_TIER_ENABLED is true (the pilot is READ-only)")
    if not _flag("RAG_LLM_KILL_SWITCH"):
        failures.append("RAG_LLM_KILL_SWITCH is not true")
    if (os.environ.get("RAG_LLM_PROVIDER") or "").strip():
        failures.append("RAG_LLM_PROVIDER is set (no provider in the READ-only pilot)")
    present = [name for name in PROVIDER_CREDENTIAL_ENV if (os.environ.get(name) or "").strip()]
    if present:
        failures.append("provider credential variables present: " + ", ".join(present))

    # main.py wires the question service only when all three hold; otherwise Q&A silently stays 503.
    missing = [name for name, ok in (("SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY (Auth)", settings.auth_configured),
                                     ("SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY", settings.supabase_configured),
                                     ("SUPABASE_DB_URL", bool(settings.supabase_db_url))) if not ok]
    if missing:
        failures.append("main.py would not wire Q&A; missing: " + "; ".join(missing))
    # main.py loads the Carbon parameter file at import when Supabase is configured; a bad
    # AGRICARBON_EF_CONFIG stops the whole API there.
    try:
        from carbon import ParameterSet
        ParameterSet.load(settings.ef_config_path)
    except Exception as exc:  # noqa: BLE001 - report the type only, never a path or a value
        failures.append(f"the Carbon parameter file (AGRICARBON_EF_CONFIG) does not load: {type(exc).__name__}")
    raw_score = (os.environ.get("RAG_RETRIEVAL_MIN_FUSED_SCORE") or "").strip()
    if raw_score:
        try:
            float(raw_score)
        except ValueError:
            failures.append("RAG_RETRIEVAL_MIN_FUSED_SCORE is not a number (the service factory would fail)")

    try:
        policy = qrl.load_question_rate_policy()
        facts["per_minute"], facts["per_day"] = policy.per_minute, policy.per_day
    except qrl.QuestionRateConfigError as exc:
        failures.append(f"rate limit: {exc}")
    try:
        store = qrl.store_kind_from_env()
        facts["store"] = store
        if store != "postgres":
            failures.append(f"RAG_QA_RATE_LIMIT_STORE is {store!r}; the pilot needs 'postgres' (durable, shared)")
    except qrl.QuestionRateConfigError as exc:
        failures.append(f"rate limit store: {exc}")

    cohort: frozenset[str] | None = frozenset()
    try:
        cohort = rag_qa.pilot_cohort_from_env()
    except ValueError as exc:
        failures.append(f"cohort: {exc}")
    else:
        if cohort is None:
            failures.append(f"{rag_qa.ALLOWED_USERS_ENV}='*' opens Q&A to every signed-in user; the pilot needs "
                            "the explicit approved ids")
        elif not cohort:
            failures.append(f"{rag_qa.ALLOWED_USERS_ENV} is empty: nobody could ask")
        else:
            facts["cohort_users"] = len(cohort)
            if expected_ids is not None:
                missing_ids, extra_ids = len(expected_ids - cohort), len(cohort - expected_ids)
                if missing_ids or extra_ids:
                    failures.append(f"cohort differs from the approved set: {missing_ids} missing, {extra_ids} extra")

    # Same factory as main.py. READ-only must never build a model client (provider not loaded).
    if not failures:
        try:
            service = rag_qa.build_question_service(carbon_service=object(), write_gate=None, rate_limiter=None,
                                                    allowed_user_ids=cohort)
        except Exception as exc:  # noqa: BLE001 - a traceback could echo an env value; report the type only
            failures.append(f"the service factory failed: {type(exc).__name__}")
            return failures, facts
        if getattr(service, "_llm", None) is not None or getattr(service, "_action_tier_enabled", True):
            failures.append("the service factory built an action tier / model client")
        else:
            facts["tier"], facts["provider"] = "read_only", "not_loaded"
    return failures, facts


def main(argv: Sequence[str] | None = None, *, out: TextIO = sys.stdout,
         load_settings: Callable[[], Any] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rag_qa_preflight", description=__doc__.splitlines()[0])
    parser.add_argument("--expect-user-ids-file", type=Path,
                        help="UUIDs derived from the approved QA matrix; the cohort must equal this set")
    args = parser.parse_args(argv)
    expected = None
    if args.expect_user_ids_file is not None:
        try:
            expected = _read_expected_ids(args.expect_user_ids_file)
        except (OSError, ValueError) as exc:
            print(f"USAGE expected-ids file unreadable or not UUIDs ({type(exc).__name__})", file=out)
            return 2
        if not expected:
            print("USAGE expected-ids file has no id", file=out)
            return 2
    failures, facts = check(expected_ids=expected, load_settings=load_settings)
    for reason in failures:
        print(f"FAIL {reason}", file=out)
    if failures:
        print(f"RAG-QA-PREFLIGHT FAIL ({len(failures)})", file=out)
        return 1
    print("RAG-QA-PREFLIGHT PASS (configuration only) " + " ".join(f"{k}={v}" for k, v in facts.items())
          + (" cohort_matches_approved_set=yes" if expected is not None else ""), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
