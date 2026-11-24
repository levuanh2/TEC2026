"""`python -m rag_qa_preflight`: offline pilot configuration check run in the candidate image.

The L1 pilot must never start with "*" (everyone signed in), an empty cohort, the action tier,
a provider, or a non-durable rate-limit store, and a malformed value must be caught before the
running API container is replaced (main.py raises at import on it, which takes the whole API down).
Every test builds Settings from a dotenv path that does not exist, so no backend/.env is read.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag_qa_preflight  # noqa: E402
from infrastructure import config  # noqa: E402

USER_A = "11111111-2222-3333-4444-555555555555"
USER_B = "66666666-7777-8888-9999-aaaaaaaaaaaa"
SECRET_DB_URL = "postgresql://api_login:pw-must-never-print@db.invalid:5432/postgres"
SECRET_KEY = "sb_secret_must_never_print"

PILOT_ENV = {
    "RAG_QA_ENABLED": "true",
    "RAG_LLM_KILL_SWITCH": "true",
    "RAG_QA_RATE_LIMIT_STORE": "postgres",
    "RAG_QA_RATE_LIMIT_PER_MINUTE": "10",
    "RAG_QA_RATE_LIMIT_PER_DAY": "100",
    "RAG_QA_ALLOWED_USER_IDS": f"{USER_A},{USER_B}",
    "SUPABASE_URL": "https://project.invalid",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
    "SUPABASE_SERVICE_ROLE_KEY": SECRET_KEY,
    "SUPABASE_DB_URL": SECRET_DB_URL,
}
CLEARED = ("RAG_QA_ACTION_TIER_ENABLED", "RAG_LLM_PROVIDER", "RAG_LLM_API_KEY", "GEMINI_API_KEY",
           "DEEPSEEK_API_KEY", "RAG_RETRIEVAL_MIN_FUSED_SCORE")


@pytest.fixture
def pilot_env(monkeypatch):
    for name in (*PILOT_ENV, *CLEARED):
        monkeypatch.delenv(name, raising=False)
    for name, value in PILOT_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def run(tmp_path: Path, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = rag_qa_preflight.main(list(argv), out=out,
                                 load_settings=lambda: config.load_settings(dotenv_path=tmp_path / "absent.env"))
    text = out.getvalue()
    assert SECRET_DB_URL not in text and "pw-must-never-print" not in text and SECRET_KEY not in text
    return code, text


def test_approved_pilot_configuration_passes(pilot_env, tmp_path):
    code, text = run(tmp_path)
    assert code == 0, text
    assert text.startswith("RAG-QA-PREFLIGHT PASS (configuration only)")
    for fact in ("per_minute=10", "per_day=100", "store=postgres", "cohort_users=2", "tier=read_only",
                 "provider=not_loaded"):
        assert fact in text
    assert USER_A not in text and USER_B not in text  # counts only, never the ids


@pytest.mark.parametrize("name,value,reason", [
    ("RAG_QA_ALLOWED_USER_IDS", "*", "opens Q&A to every signed-in user"),
    ("RAG_QA_ALLOWED_USER_IDS", "", "is empty: nobody could ask"),
    ("RAG_QA_ALLOWED_USER_IDS", " , ", "is empty: nobody could ask"),
    ("RAG_QA_ALLOWED_USER_IDS", f"{USER_A}x", "must be '*' or comma-separated UUIDs"),
    ("RAG_QA_ALLOWED_USER_IDS", f"*,{USER_A}", "must be '*' or comma-separated UUIDs"),
    ("RAG_QA_ALLOWED_USER_IDS", "qa01@example.invalid", "must be '*' or comma-separated UUIDs"),
    ("RAG_QA_RATE_LIMIT_PER_MINUTE", "0", "rate limit"),
    ("RAG_QA_RATE_LIMIT_PER_DAY", "ten", "rate limit"),
    ("RAG_QA_RATE_LIMIT_STORE", "memory", "needs 'postgres'"),
    ("RAG_QA_RATE_LIMIT_STORE", "redis", "rate limit store"),
    ("RAG_QA_ACTION_TIER_ENABLED", "true", "the pilot is READ-only"),
    ("RAG_QA_ENABLED", "false", "Q&A would stay off"),
    ("RAG_LLM_KILL_SWITCH", "", "RAG_LLM_KILL_SWITCH is not true"),
    ("RAG_LLM_PROVIDER", "gemini", "RAG_LLM_PROVIDER is set"),
    ("GEMINI_API_KEY", "AIza-never-print", "provider credential variables present: GEMINI_API_KEY"),
    ("DEEPSEEK_API_KEY", "sk-never-print", "provider credential variables present: DEEPSEEK_API_KEY"),
    ("SUPABASE_DB_URL", "", "missing: SUPABASE_DB_URL"),
    ("SUPABASE_PUBLISHABLE_KEY", "", "(Auth)"),
])
def test_each_unsafe_or_broken_setting_fails(pilot_env, tmp_path, name, value, reason):
    pilot_env.setenv(name, value)
    code, text = run(tmp_path)
    assert code == 1, text
    assert reason in text
    assert "RAG-QA-PREFLIGHT FAIL" in text and "PASS" not in text
    assert "never-print" not in text


def test_cohort_must_equal_the_approved_set(pilot_env, tmp_path):
    approved = tmp_path / "cohort.txt"
    approved.write_text(f"# derived from the approved A-1 matrix\n{USER_B.upper()}\n{USER_A}\n", encoding="utf-8")
    code, text = run(tmp_path, "--expect-user-ids-file", str(approved))
    assert code == 0 and "cohort_matches_approved_set=yes" in text, text

    approved.write_text(f"{USER_A}\n", encoding="utf-8")  # the env has one id more than approved
    code, text = run(tmp_path, "--expect-user-ids-file", str(approved))
    assert code == 1 and "0 missing, 1 extra" in text, text

    pilot_env.setenv("RAG_QA_ALLOWED_USER_IDS", USER_A)
    approved.write_text(f"{USER_A},{USER_B}\n", encoding="utf-8")
    code, text = run(tmp_path, "--expect-user-ids-file", str(approved))
    assert code == 1 and "1 missing, 0 extra" in text, text


@pytest.mark.parametrize("content", ["", "# nothing\n", "not-a-uuid\n"])
def test_unusable_expected_ids_file_is_a_usage_error(pilot_env, tmp_path, content):
    approved = tmp_path / "cohort.txt"
    approved.write_text(content, encoding="utf-8")
    code, text = run(tmp_path, "--expect-user-ids-file", str(approved))
    assert code == 2 and "USAGE" in text and "PASS" not in text


def test_the_check_never_builds_a_rate_limit_store_or_reads_provider_settings(pilot_env, tmp_path, monkeypatch):
    from infrastructure import llm_client, question_rate_limit

    def refuse(*_a, **_k):
        raise AssertionError("must not be called by the offline preflight")

    monkeypatch.setattr(question_rate_limit, "PostgresQuestionRateStore", refuse)
    monkeypatch.setattr(question_rate_limit, "build_question_rate_limiter", refuse)
    monkeypatch.setattr(llm_client, "load_llm_settings", refuse)
    monkeypatch.setattr(llm_client, "build_llm_client", refuse)
    code, text = run(tmp_path)
    assert code == 0, text


def test_all_failures_are_reported_at_once(pilot_env, tmp_path):
    pilot_env.setenv("RAG_QA_ALLOWED_USER_IDS", "*")
    pilot_env.setenv("RAG_QA_RATE_LIMIT_STORE", "memory")
    pilot_env.setenv("RAG_QA_ACTION_TIER_ENABLED", "true")
    code, text = run(tmp_path)
    assert code == 1 and "RAG-QA-PREFLIGHT FAIL (3)" in text, text
