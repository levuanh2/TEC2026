"""Core V1 closure (3B), no database: the API guard and the change service.

The real-stack journey is tests/test_forced_password_change.py; this file pins
the rules that do not need one, so the no-DB CI job covers them too.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import main  # noqa: E402
from infrastructure.auth import claims_for_denial_only  # noqa: E402
from infrastructure.auth_admin import AuthIdentity, must_change_password  # noqa: E402
from service import (  # noqa: E402
    CurrentPasswordIncorrectError,
    PasswordChangeService,
    PasswordChangeUnauthenticatedError,
    PasswordPolicyError,
    password_problem,
)


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def token(**app_metadata) -> str:
    return f"{_b64({'alg': 'HS256'})}.{_b64({'sub': 'u-1', 'app_metadata': app_metadata})}.signature"


class FakeAuth:
    def __init__(self, identity: AuthIdentity | None, current_ok: bool = True):
        self._identity, self._current_ok = identity, current_ok
        self.calls: list[tuple] = []

    def identity(self, tok):
        self.calls.append(("identity", tok))
        return self._identity

    def password_is_current(self, email, password):
        self.calls.append(("verify", email))
        return self._current_ok

    def replace_temporary_password(self, user_id, new_password):
        self.calls.append(("replace", user_id))


FLAGGED = AuthIdentity("u-1", "farmer@example.invalid", True)


# -- flag + claims ------------------------------------------------------------------

def test_only_a_literal_true_counts_as_the_flag():
    assert must_change_password({"must_change_password": True}) is True
    for value in (False, None, "true", 1, {}):
        assert must_change_password({"must_change_password": value}) is False
    assert must_change_password(None) is False and must_change_password({}) is False


def test_claims_reader_never_raises_on_garbage():
    for garbage in ("", "abc", "a.b", "a.!!!.c", "a." + _b64({"x": 1})[:-2] + "@.c", f"a.{base64.urlsafe_b64encode(b'[1]').decode()}.c"):
        assert isinstance(claims_for_denial_only(garbage), dict)
    assert claims_for_denial_only(token(must_change_password=True))["app_metadata"] == {"must_change_password": True}


# -- the API guard -----------------------------------------------------------------

@pytest.fixture
def client():
    saved = dict(main.app.dependency_overrides)
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(saved)


def test_every_business_route_refuses_a_flagged_token(client):
    flagged = {"Authorization": f"Bearer {token(must_change_password=True)}"}
    for method, path in (("GET", "/v1/farms"), ("GET", "/v1/organizations"), ("POST", "/v1/carbon/calculate"),
                         ("GET", "/v1/crop-seasons/00000000-0000-0000-0000-000000000000/carbon"),
                         ("POST", "/v1/organizations/00000000-0000-0000-0000-000000000000/farmers")):
        r = client.request(method, path, headers=flagged, json={})
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json() == {"detail": {"error": {"code": "password_change_required", "message": r.json()["detail"]["error"]["message"]}}}


def test_me_and_the_change_route_stay_reachable(client):
    main.app.dependency_overrides[api._password_change_service] = lambda: PasswordChangeService(FakeAuth(FLAGGED))
    flagged = {"Authorization": f"Bearer {token(must_change_password=True)}"}
    assert api.PASSWORD_CHANGE_ROUTES == {("GET", "/v1/me"), ("POST", "/v1/me/password")}
    r = client.post("/v1/me/password", headers=flagged, json={"current_password": "Temp-Pass-1", "new_password": "Own-Pass-22"})
    assert r.status_code == 200 and r.json() == {"must_change_password": False}
    assert client.get("/v1/me", headers=flagged).status_code != 403


def test_tokens_without_the_flag_and_requests_without_a_token_are_untouched(client):
    for headers in ({"Authorization": f"Bearer {token()}"}, {"Authorization": f"Bearer {token(must_change_password=False)}"},
                    {"Authorization": "Bearer garbage"}, {}):
        assert client.get("/v1/carbon/scenarios", headers=headers).status_code == 200
        assert client.get("/v1/farms", headers=headers).status_code != 403


# -- the change service -------------------------------------------------------------

def test_policy_matches_the_web_rule():
    assert password_problem("Temp-1", "Own-Pass-22") is None
    for new, code in (("short1A", "password_too_weak"), ("alllowercase1", "password_too_weak"),
                      ("ALLUPPERCASE1", "password_too_weak"), ("NoDigitsHere", "password_too_weak"),
                      ("Aa1" + "x" * 70, "password_too_long"), ("Same-Pass-1", "password_unchanged")):
        problem = password_problem("Same-Pass-1", new)
        assert problem is not None and problem.code == code, new


def test_the_flag_is_cleared_only_after_the_current_password_is_verified():
    auth = FakeAuth(FLAGGED)
    assert PasswordChangeService(auth).change("tok", "Temp-Pass-1", "Own-Pass-22") == {"must_change_password": False}
    assert [c[0] for c in auth.calls] == ["identity", "verify", "replace"]

    wrong = FakeAuth(FLAGGED, current_ok=False)
    with pytest.raises(CurrentPasswordIncorrectError):
        PasswordChangeService(wrong).change("tok", "Wrong-Pass-1", "Own-Pass-22")
    assert "replace" not in [c[0] for c in wrong.calls]


def test_policy_failures_and_unknown_users_never_reach_auth_admin():
    weak = FakeAuth(FLAGGED)
    with pytest.raises(PasswordPolicyError):
        PasswordChangeService(weak).change("tok", "Temp-Pass-1", "weak")
    assert [c[0] for c in weak.calls] == ["identity"]
    for identity in (None, AuthIdentity("u-2", None, True)):
        nobody = FakeAuth(identity)
        with pytest.raises(PasswordChangeUnauthenticatedError):
            PasswordChangeService(nobody).change("tok", "Temp-Pass-1", "Own-Pass-22")
        assert [c[0] for c in nobody.calls] == ["identity"]
