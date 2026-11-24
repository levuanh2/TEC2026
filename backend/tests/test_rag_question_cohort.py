"""Pilot cohort gate for POST /v1/crop-seasons/{id}/questions (L1: only the approved QA accounts).

`RAG_QA_ALLOWED_USER_IDS` is read in main.py; unset/empty = nobody (fail closed), "*" = every
signed-in user (an owner decision), otherwise only the listed Supabase Auth user ids. The gate runs
after the READ-only tier lock and the Auth verification, and BEFORE the rate limit and any read.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag_qa  # noqa: E402
from infrastructure import question_rate_limit as qrl  # noqa: E402
from rag_qa import RagQuestionService  # noqa: E402
from tests.fixtures.rag_fakes import SEASON_ID  # noqa: E402
from tests.test_rag_qa import Carbon, gate  # noqa: E402
from tests.test_rag_question_rate_limit import (  # noqa: E402
    OTHER_TENANT_SEASON, USER_A, USER_B, CountingReader, app_client, ask, error_code, limiter)

NOT_ENABLED = "Tính năng hỏi đáp đang thử nghiệm và chưa mở cho tài khoản này."


class CountingLimiter:
    """Wraps a real limiter and records which users were counted."""

    def __init__(self, inner):
        self.inner, self.counted = inner, []

    def consume(self, user_id, *, request_id=None):
        self.counted.append(user_id)
        return self.inner.consume(user_id, request_id=request_id)


def service(allowed, rate_limiter=None):
    return RagQuestionService(carbon_service=Carbon(), write_gate=gate(), action_tier_enabled=False,
                              rate_limiter=rate_limiter, allowed_user_ids=allowed)


# -- configuration -----------------------------------------------------------------

def test_unset_or_empty_means_nobody(caplog):
    with caplog.at_level(logging.INFO, logger=rag_qa.logger.name):
        assert rag_qa.pilot_cohort_from_env({}) == frozenset()
        assert rag_qa.pilot_cohort_from_env({rag_qa.ALLOWED_USERS_ENV: "  "}) == frozenset()
        assert rag_qa.pilot_cohort_from_env({rag_qa.ALLOWED_USERS_ENV: " , ,"}) == frozenset()
    assert "rag_question_cohort mode=closed users=0" in caplog.text


def test_list_is_normalised_and_counted_without_printing_ids(caplog):
    with caplog.at_level(logging.INFO, logger=rag_qa.logger.name):
        got = rag_qa.pilot_cohort_from_env({rag_qa.ALLOWED_USERS_ENV: f" {USER_A.upper()} ,{USER_B},{USER_A}"})
    assert got == frozenset({USER_A, USER_B})
    assert "mode=allow_list users=2" in caplog.text and USER_A not in caplog.text


def test_star_is_an_explicit_open_mode_and_is_logged_as_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=rag_qa.logger.name):
        assert rag_qa.pilot_cohort_from_env({rag_qa.ALLOWED_USERS_ENV: "*"}) is None
    assert "mode=open_to_all_signed_in_users" in caplog.text


@pytest.mark.parametrize("value", ["all", "true", "qa@example.com", "1234", f"{USER_A},nope", "**"])
def test_anything_else_fails_start_up(value):
    with pytest.raises(ValueError):
        rag_qa.pilot_cohort_from_env({rag_qa.ALLOWED_USERS_ENV: value})


def test_main_always_passes_the_env_cohort_to_the_question_service():
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    call = source[source.index("rag_qa.build_question_service("):]
    call = call[:call.index("\n    app.dependency_overrides")]
    assert "allowed_user_ids=rag_qa.pilot_cohort_from_env()" in call


def test_factory_passes_the_cohort_in_both_tiers(monkeypatch):
    monkeypatch.delenv("RAG_QA_ACTION_TIER_ENABLED", raising=False)
    assert rag_qa.build_question_service(carbon_service=Carbon(), write_gate=gate(),
                                         allowed_user_ids=frozenset()).cohort_restricted
    monkeypatch.setenv("RAG_QA_ACTION_TIER_ENABLED", "true")
    monkeypatch.delenv("RAG_LLM_PROVIDER", raising=False)
    assert rag_qa.build_question_service(carbon_service=Carbon(), write_gate=gate(),
                                         allowed_user_ids=frozenset({USER_A})).cohort_restricted


# -- the route ---------------------------------------------------------------------

def test_closed_cohort_refuses_everyone_before_quota_and_before_any_read():
    counting = CountingLimiter(limiter())
    reader = CountingReader(user=USER_A)
    response = ask(app_client(service(frozenset(), counting), reader))
    assert response.status_code == 403
    assert error_code(response) == "question_not_enabled"
    assert response.json()["detail"]["error"]["message"] == NOT_ENABLED
    assert reader.used == ["user_id"]  # Auth verification only
    assert counting.counted == []      # no quota used


def test_listed_user_is_answered_and_counted():
    counting = CountingLimiter(limiter())
    reader = CountingReader(user=USER_A)
    response = ask(app_client(service(frozenset({USER_A}), counting), reader))
    assert response.status_code == 200, response.text
    provenance = response.json()["provenance"]
    assert provenance["answer_source"] == "system_composed" and provenance["llm_calls"] == 0
    assert counting.counted == [USER_A]


def test_unlisted_user_is_refused_identically_for_every_season():
    counting = CountingLimiter(limiter())
    reader = CountingReader(user=USER_B)
    client = app_client(service(frozenset({USER_A}), counting), reader)
    bodies = []
    for season in (SEASON_ID, OTHER_TENANT_SEASON, "00000000-0000-4000-8000-00000000dead"):
        reader.used.clear()
        response = ask(client, season=season)
        assert response.status_code == 403 and reader.used == ["user_id"]
        bodies.append(response.json())
    assert bodies[0] == bodies[1] == bodies[2]
    assert counting.counted == []


def test_cohort_gate_works_without_a_rate_limiter():
    reader = CountingReader(user=USER_B)
    response = ask(app_client(service(frozenset({USER_A}), None), reader))
    assert response.status_code == 403 and reader.used == ["user_id"]


def test_invalid_token_is_still_401_not_403():
    reader = CountingReader(user=USER_A, reject_token=True)
    response = ask(app_client(service(frozenset({USER_A}), limiter()), reader))
    assert response.status_code == 401


def test_action_intent_is_locked_first_even_for_a_listed_user():
    counting = CountingLimiter(limiter())
    reader = CountingReader(user=USER_A)
    response = ask(app_client(service(frozenset({USER_A}), counting), reader), intent="recommend")
    assert response.status_code == 503 and error_code(response) == "action_tier_disabled"
    assert reader.used == [] and counting.counted == []


def test_no_restriction_when_none_keeps_previous_behaviour():
    reader = CountingReader(user=USER_B)
    response = ask(app_client(service(None, limiter()), reader))
    assert response.status_code == 200


def test_quota_of_a_listed_user_still_applies():
    shared = limiter(per_minute=1)
    reader = CountingReader(user=USER_A)
    client = app_client(service(frozenset({USER_A}), shared), reader)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 429


def test_error_code_is_mapped_in_the_public_tables():
    assert rag_qa.HTTP_STATUS["question_not_enabled"] == 403
    assert rag_qa.PUBLIC_MESSAGES["question_not_enabled"] == NOT_ENABLED
    assert qrl  # module stays importable alongside the gate
