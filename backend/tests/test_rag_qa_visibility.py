"""V-1b: GET /v1/me `ai_qa_available` -- may the web SHOW the season Q&A panel to this caller?

Visibility only. The decision is the question service's own `in_cohort` (the same instance the
questions route is given), so the panel can never be shown to a caller the route refuses with 403
`question_not_enabled`, or hidden from one it answers. /v1/me reads no quota, calls no model and
reads no season; an invalid JWT stays 401. Every question is still checked on the server.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from rag_qa import RagQuestionService  # noqa: E402
from tests.fixtures.rag_fakes import SEASON_ID  # noqa: E402
from tests.test_rag_qa import Carbon, gate  # noqa: E402
from tests.test_rag_question_cohort import CountingLimiter  # noqa: E402
from tests.test_rag_question_rate_limit import (  # noqa: E402
    AUTH, OTHER_TENANT_SEASON, USER_A, USER_B, CountingReader, app_client, ask, error_code, limiter)

USER_C = "33333333-3333-4333-8333-333333333333"
ME_KEYS = {"user_id", "full_name", "organization_memberships", "farm_memberships", "roles",
           "must_change_password", "ai_qa_available"}


@dataclass
class MeReader(CountingReader):
    """`me()` verifies the token first (like SupabaseReadRepository.me -> Supabase Auth)."""
    must_change: bool = False

    def me(self):
        user = self.user_id()
        return {"user_id": user, "full_name": "QA", "organization_memberships": [], "farm_memberships": [],
                "roles": ["farmer"], "must_change_password": self.must_change}


def service(allowed, rate_limiter=None):
    return RagQuestionService(carbon_service=Carbon(), write_gate=gate(), action_tier_enabled=False,
                              rate_limiter=rate_limiter, allowed_user_ids=allowed)


def me(client):
    return client.get("/v1/me", headers=AUTH)


def no_qa_client(reader):
    """A server where main.py did NOT wire Q&A (RAG_QA_ENABLED unset / not configured)."""
    client = app_client(None, reader)
    client.app.dependency_overrides.pop(api._rag_question_service)
    return client


# -- true / false ---------------------------------------------------------------------------

def test_a_cohort_member_may_see_the_panel():
    response = me(app_client(service(frozenset({USER_A})), MeReader(user=USER_A)))
    assert response.status_code == 200 and response.json()["ai_qa_available"] is True


@pytest.mark.parametrize("allowed", [frozenset({USER_B}), frozenset()], ids=["not_listed", "cohort_empty"])
def test_outside_the_cohort_or_an_empty_cohort_hides_it(allowed):
    response = me(app_client(service(allowed), MeReader(user=USER_A)))
    assert response.status_code == 200 and response.json()["ai_qa_available"] is False


def test_q_and_a_not_enabled_or_not_configured_hides_it():
    response = me(no_qa_client(MeReader(user=USER_A)))
    assert response.status_code == 200 and response.json()["ai_qa_available"] is False


def test_the_default_dependency_that_refuses_with_503_hides_it():
    """Even if the default (not configured) provider were installed as the override."""
    client = app_client(None, MeReader(user=USER_A))
    client.app.dependency_overrides[api._rag_question_service] = api._rag_question_service
    response = me(client)
    assert response.status_code == 200 and response.json()["ai_qa_available"] is False


def test_any_error_deciding_hides_it_and_keeps_me_working(monkeypatch):
    class Broken:
        def in_cohort(self, _user_id):
            raise RuntimeError("cohort unknown")

    class Recorder:
        """Not caplog: another test's logging config can disable `agricarbon.api` in the full suite."""
        def __init__(self):
            self.lines = []

        def warning(self, msg, *args):
            self.lines.append(msg % args)

    recorder = Recorder()
    monkeypatch.setattr(api, "logger", recorder)
    client = app_client(Broken(), MeReader(user=USER_A))
    response = me(client)
    assert response.status_code == 200 and response.json()["ai_qa_available"] is False
    assert recorder.lines == ["rag_question_capability_unavailable type=RuntimeError"]


def test_a_truthy_non_boolean_answer_is_not_true():
    class Odd:
        def in_cohort(self, _user_id):
            return "yes"
    assert me(app_client(Odd(), MeReader(user=USER_A))).json()["ai_qa_available"] is False


def test_a_pending_password_change_hides_it():
    """Every route but /v1/me answers 403 password_change_required then, the questions route too."""
    response = me(app_client(service(frozenset({USER_A})), MeReader(user=USER_A, must_change=True)))
    assert response.status_code == 200 and response.json()["ai_qa_available"] is False


def test_unrestricted_cohort_shows_it_to_every_signed_in_user():
    """`*` is an explicit owner decision for a later level (the L1 deploy preflight refuses it)."""
    assert me(app_client(service(None), MeReader(user=USER_C))).json()["ai_qa_available"] is True


@pytest.mark.parametrize("value", ["", "not-a-uuid", "*", USER_A.upper(), "{" + USER_A + "}"])
def test_in_cohort_normalises_like_the_gate_and_fails_closed(value):
    expected = value in (USER_A.upper(), "{" + USER_A + "}")
    assert service(frozenset({USER_A})).in_cohort(value) is expected


# -- authentication stays as it was ------------------------------------------------------------

@pytest.mark.parametrize("allowed", [frozenset({USER_A}), frozenset(), None])
def test_invalid_jwt_is_still_401_never_a_200_with_false(allowed):
    response = me(app_client(service(allowed), MeReader(user=USER_A, reject_token=True)))
    assert response.status_code == 401 and error_code(response) == "unauthenticated"


# -- what /v1/me does NOT do -------------------------------------------------------------------

def test_me_uses_no_quota_no_model_and_reads_no_season(monkeypatch):
    counting = CountingLimiter(limiter())
    svc = service(frozenset({USER_A}), counting)

    def must_not_answer(**_kwargs):
        raise AssertionError("/v1/me must not run a question")
    monkeypatch.setattr(svc, "answer", must_not_answer)
    reader = MeReader(user=USER_A)
    for _ in range(3):
        assert me(app_client(svc, reader)).json()["ai_qa_available"] is True
    assert counting.counted == []
    assert set(reader.used) <= {"me", "user_id"}, reader.used  # no season / Carbon / knowledge read
    assert svc._llm is None  # READ-only: no model client exists to call


def test_me_says_nothing_about_other_accounts():
    response = me(app_client(service(frozenset({USER_A, USER_B, USER_C})), MeReader(user=USER_A)))
    body = response.json()
    assert set(body) == ME_KEYS
    text = json.dumps(body)
    assert USER_B not in text and USER_C not in text and "cohort" not in text.lower()
    assert body["ai_qa_available"] is True  # a bare boolean, no count, no list


def test_the_response_model_declares_a_boolean_defaulting_to_false():
    field = schemas.MeResponse.model_fields["ai_qa_available"]
    assert field.annotation is bool and field.default is False


# -- one cohort decision: /v1/me and the questions route agree ---------------------------------

@pytest.mark.parametrize("allowed", [frozenset({USER_A}), frozenset({USER_B}), frozenset(), frozenset({USER_A, USER_B}), None])
@pytest.mark.parametrize("user", [USER_A, USER_B])
def test_visibility_equals_what_the_route_answers(allowed, user):
    svc = service(allowed, limiter())
    shown = me(app_client(svc, MeReader(user=user))).json()["ai_qa_available"]
    answered = ask(app_client(svc, MeReader(user=user)))
    refused_by_cohort = answered.status_code == 403 and error_code(answered) == "question_not_enabled"
    assert shown is (not refused_by_cohort), (shown, answered.status_code)
    if shown:
        assert answered.status_code == 200


def test_visible_is_not_authorization_for_another_tenant():
    svc = service(frozenset({USER_A}), limiter())
    assert me(app_client(svc, MeReader(user=USER_A))).json()["ai_qa_available"] is True
    # RLS hides another tenant's season from this caller (the fake: visible=False)
    response = ask(app_client(svc, MeReader(user=USER_A, visible=False)), season=OTHER_TENANT_SEASON)
    assert response.status_code == 404 and error_code(response) == "not_found"


def test_outsider_calling_the_api_directly_is_still_403_without_quota():
    counting = CountingLimiter(limiter())
    svc = service(frozenset({USER_B}), counting)
    reader = MeReader(user=USER_A)
    assert me(app_client(svc, reader)).json()["ai_qa_available"] is False
    response = ask(app_client(svc, reader))
    assert response.status_code == 403 and error_code(response) == "question_not_enabled"
    assert counting.counted == []


@pytest.mark.parametrize("intent", ["recommend", "what_if"])
def test_the_action_tier_stays_locked_for_a_visible_cohort_member(intent):
    svc = service(frozenset({USER_A}), limiter())
    assert me(app_client(svc, MeReader(user=USER_A))).json()["ai_qa_available"] is True
    extra = {"what_if_scenario": "awd"} if intent == "what_if" else {}
    response = ask(app_client(svc, MeReader(user=USER_A)), intent=intent, **extra)
    assert response.status_code == 503 and error_code(response) == "action_tier_disabled"


def test_read_answer_for_a_visible_member_makes_no_model_call():
    svc = service(frozenset({USER_A}), limiter())
    response = ask(app_client(svc, MeReader(user=USER_A)))
    assert response.status_code == 200
    assert response.json()["provenance"]["llm_calls"] == 0
    assert response.json()["provenance"]["answer_source"] == "system_composed"
    assert SEASON_ID  # the fixture season the route answered for
