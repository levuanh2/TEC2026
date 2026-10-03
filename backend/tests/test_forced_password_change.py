"""Core V1 closure (3B): forced first-login password change, end to end.

Real `main.app`, real Supabase Auth (GoTrue), real PostgREST and RLS on a LOCAL
stack. The account is provisioned through the API exactly as Management Web
does it, then used three ways:

* FastAPI routes (403 `password_change_required` while the flag is set);
* PostgREST with the user's JWT -- what Flutter does (RLS returns nothing and
  refuses writes, whatever the client shows);
* the SQL helpers with `request.jwt.claims` = {sub} -- what FastAPI's pooled
  paths do (the live flag on auth.users decides) -- and with a token's own
  claims, as PostgREST sets them (a token minted with the temporary password
  stays refused after the change, 20261003090000).

Creates users and a tenant, so it only runs against a LOCAL stack, and deletes
everything it created.
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402

_SETTINGS = load_settings()
_DB_URL = _SETTINGS.supabase_db_url
_LOCAL = {"127.0.0.1", "localhost"}
_REMOTE = bool(_DB_URL) and not (urlparse(_DB_URL).hostname in _LOCAL
                                 and urlparse(_SETTINGS.supabase_url or "").hostname in _LOCAL)
pytestmark = [
    pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured."),
    pytest.mark.skipif(_REMOTE, reason="refusing: creates users; only runs against a LOCAL Supabase stack"),
]


class Stack:
    def __init__(self):
        import httpx
        from fastapi.testclient import TestClient
        from supabase import create_client

        from main import app

        self.httpx = httpx
        self.url, service = _SETTINGS.require_supabase()
        _, self.publishable = _SETTINGS.require_publishable()
        self.admin = create_client(self.url, service)
        self.api = TestClient(app, raise_server_exceptions=False)
        self.run = uuid.uuid4().hex[:8]
        self.users: list[str] = []
        self.orgs: list[str] = []

    # -- Auth ---------------------------------------------------------------------
    def create_user(self, label: str, **extra) -> tuple[str, str, str]:
        email, password = f"fpc-{self.run}-{label}@agricarbon-ci.invalid", f"Fp-{uuid.uuid4().hex}!9A"
        user = self.admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True, **extra}).user
        self.users.append(user.id)
        return user.id, email, password

    def sign_in(self, email: str, password: str):
        return self.httpx.post(f"{self.url}/auth/v1/token?grant_type=password", headers={"apikey": self.publishable},
                               json={"email": email, "password": password}, timeout=30)

    def token(self, email: str, password: str) -> str:
        r = self.sign_in(email, password)
        r.raise_for_status()
        return r.json()["access_token"]

    def flag(self, user_id: str):
        import psycopg

        with psycopg.connect(_DB_URL) as conn:
            return conn.execute("select raw_app_meta_data -> 'must_change_password' from auth.users where id = %s",
                                (user_id,)).fetchone()[0]

    # -- clients ----------------------------------------------------------------
    def get(self, token: str, path: str):
        return self.api.get(path, headers={"Authorization": f"Bearer {token}"})

    def rest(self, token: str, method: str, table: str, **kw):
        return self.httpx.request(method, f"{self.url}/rest/v1/{table}", timeout=30, **kw,
                                  headers={"apikey": self.publishable, "Authorization": f"Bearer {token}",
                                           "Prefer": "return=representation"})

    def helper(self, user_id: str, fn: str, arg: str) -> bool:
        """As FastAPI's pooled paths call it: claims carry only the user id."""
        import psycopg

        with psycopg.connect(_DB_URL) as conn:
            conn.execute("select set_config('request.jwt.claims', %s, true)",
                         (json.dumps({"sub": str(user_id), "role": "authenticated"}),))
            return conn.execute(f"select private.{fn}(%s::uuid)", (arg,)).fetchone()[0]

    def cleanup(self):
        import psycopg

        with psycopg.connect(_DB_URL) as conn:
            farms = "select id from public.farms where cooperative_id = any(%(o)s::uuid[])"
            plots = f"select id from public.plots where farm_id in ({farms})"
            seasons = f"select id from public.crop_seasons where plot_id in ({plots})"
            batches = f"select id from public.production_batches where crop_season_id in ({seasons})"
            for statement in (
                f"delete from public.activities where production_batch_id in ({batches})",
                f"delete from public.production_batches where id in ({batches})",
                f"delete from public.crop_seasons where id in ({seasons})",
                f"delete from public.plots where id in ({plots})",
                f"delete from public.farm_members where farm_id in ({farms})",
                f"delete from public.farms where id in ({farms})",
                "delete from public.organization_memberships where organization_id = any(%(o)s::uuid[])"
                " or user_id = any(%(u)s::uuid[])",
                "delete from public.profiles where id = any(%(u)s::uuid[])",
                "delete from public.organizations where id = any(%(o)s::uuid[])",
            ):
                conn.execute(statement, {"o": self.orgs, "u": [str(u) for u in self.users]})
            conn.commit()
        for user in self.users:
            self.admin.auth.admin.delete_user(user)


@pytest.fixture(scope="module")
def stack():
    s = Stack()
    try:
        org = s.admin.table("organizations").insert({
            "organization_code": f"FPC-{s.run}", "name": f"FPC-{s.run}", "organization_type": "cooperative"}).execute().data[0]["id"]
        s.orgs.append(org)
        manager_id, manager_email, manager_password = s.create_user("manager")
        s.admin.table("organization_memberships").insert(
            {"organization_id": org, "user_id": manager_id, "role": "cooperative_manager"}).execute()
        s.org, s.manager_id = org, manager_id
        s.manager = s.token(manager_email, manager_password)
        yield s
    finally:
        s.cleanup()


def _provision(s: Stack, label: str) -> dict:
    r = s.api.post(f"/v1/organizations/{s.org}/farmers", headers={"Authorization": f"Bearer {s.manager}"}, json={
        "full_name": f"FPC {label}", "email": f"fpc-{s.run}-{label}@agricarbon-ci.invalid",
        "farm": {"farm_code": f"FPC-{s.run}-{label}", "farm_name": f"FPC {label}"},
        "plot": {"plot_code": f"FPC-{s.run}-{label}", "name": f"FPC {label}", "area_ha": 1.0},
    })
    assert r.status_code == 201, r.text[:300]
    body = r.json()
    s.users.append(body["user_id"])
    body["email"] = f"fpc-{s.run}-{label}@agricarbon-ci.invalid"
    return body


def _season(s: Stack, plot_id: str) -> str:
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        season = conn.execute("insert into public.crop_seasons (plot_id, season_code, status) values (%s, %s, 'active')"
                              " returning id", (plot_id, f"FPC-{uuid.uuid4().hex[:6]}")).fetchone()[0]
        batch = conn.execute("insert into public.production_batches (crop_season_id, batch_code) values (%s, 'default')"
                             " returning id", (season,)).fetchone()[0]
        conn.commit()
    return str(batch)


def _forge(token: str, **app_metadata) -> str:
    """Same header and signature, payload edited: what a client could try."""
    head, payload, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["app_metadata"] = {**claims.get("app_metadata", {}), **app_metadata}
    return ".".join([head, base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("="), sig])


BUSINESS_ROUTES = ["/v1/farms", "/v1/farmer/scope", "/v1/organizations"]


def test_provisioned_account_is_restricted_until_the_password_is_changed(stack):
    s = stack
    farmer = _provision(s, "first")
    batch = _season(s, farmer["plot_id"])
    # 1. the flag starts true, server-side
    assert s.flag(farmer["user_id"]) is True
    # 2. the temporary password signs in
    temp_session = s.sign_in(farmer["email"], farmer["temporary_password"]).json()
    token = temp_session["access_token"]
    me = s.get(token, "/v1/me")
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    # 3. API: business routes refuse, with the explicit code
    for path in BUSINESS_ROUTES + [f"/v1/farms/{farmer['farm_id']}"]:
        r = s.get(token, path)
        assert r.status_code == 403 and r.json()["detail"]["error"]["code"] == "password_change_required", path
    # 3. PostgREST (the Flutter path): RLS shows nothing and refuses writes
    assert s.rest(token, "GET", "farms", params={"select": "id"}).json() == []
    assert s.rest(token, "GET", "plots", params={"select": "id"}).json() == []
    write = s.rest(token, "POST", "activities", json={
        "production_batch_id": batch, "activity_type": "irrigation", "occurred_at": "2026-06-01T00:00:00Z",
        "recorded_at": "2026-06-01T00:00:00Z", "source": "mobile_offline", "recorded_by": farmer["user_id"],
        "device_id": None, "client_event_id": str(uuid.uuid4())})
    assert write.status_code in (401, 403), write.text[:200]
    # 3. pooled paths: the live flag decides even when the claims carry only the id
    assert s.helper(farmer["user_id"], "user_can_read_farm", farmer["farm_id"]) is False
    assert s.helper(farmer["user_id"], "user_can_write_farm", farmer["farm_id"]) is False

    # 4. wrong current password / weak / unchanged are refused, nothing changes
    for current, new, code in (
        ("Wrong-123x", "Brand-New-9x", "current_password_incorrect"),
        (farmer["temporary_password"], "short", "password_too_weak"),
        (farmer["temporary_password"], farmer["temporary_password"], "password_unchanged"),
    ):
        r = s.api.post("/v1/me/password", headers={"Authorization": f"Bearer {token}"},
                       json={"current_password": current, "new_password": new})
        assert r.status_code == 422 and r.json()["detail"]["error"]["code"] == code, r.text[:200]
    assert s.flag(farmer["user_id"]) is True

    new_password = f"Own-{uuid.uuid4().hex[:10]}A1"
    r = s.api.post("/v1/me/password", headers={"Authorization": f"Bearer {token}"},
                   json={"current_password": farmer["temporary_password"], "new_password": new_password})
    assert r.status_code == 200 and r.json() == {"must_change_password": False}
    assert r.headers["cache-control"] == "no-store"
    assert farmer["temporary_password"] not in r.text and new_password not in r.text
    # 5. cleared server-side
    assert s.flag(farmer["user_id"]) is False
    # the temporary password is dead, and so is every session opened with it
    # (e.g. by whoever saw it): changing the password revokes the refresh tokens
    assert s.sign_in(farmer["email"], farmer["temporary_password"]).status_code == 400
    refresh = s.httpx.post(f"{s.url}/auth/v1/token?grant_type=refresh_token", headers={"apikey": s.publishable},
                           json={"refresh_token": temp_session["refresh_token"]}, timeout=30)
    assert refresh.status_code == 400, refresh.text[:200]
    # 6. a fresh token has normal access on every layer
    fresh = s.token(farmer["email"], new_password)
    assert s.get(fresh, "/v1/me").json()["must_change_password"] is False
    assert farmer["farm_id"] in {f["id"] for f in s.get(fresh, "/v1/farms").json()["items"]}
    assert [f["id"] for f in s.rest(fresh, "GET", "farms", params={"select": "id"}).json()] == [farmer["farm_id"]]
    assert s.helper(farmer["user_id"], "user_can_write_farm", farmer["farm_id"]) is True
    # the token issued before the change still carries the old claim: refused
    # until the client refreshes -- never the other way round
    assert s.get(token, "/v1/farms").status_code == 403


def test_the_flag_cannot_be_cleared_by_the_client(stack):
    s = stack
    farmer = _provision(s, "forger")
    token = s.token(farmer["email"], farmer["temporary_password"])
    # 7a. user_metadata is client-writable, but it is not where the flag lives
    r = s.httpx.put(f"{s.url}/auth/v1/user", timeout=30, json={"data": {"must_change_password": False}},
                    headers={"apikey": s.publishable, "Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # 7b. app_metadata is not client-writable
    s.httpx.put(f"{s.url}/auth/v1/user", timeout=30, json={"app_metadata": {"must_change_password": False}},
                headers={"apikey": s.publishable, "Authorization": f"Bearer {token}"})
    assert s.flag(farmer["user_id"]) is True
    refreshed = s.token(farmer["email"], farmer["temporary_password"])
    assert s.get(refreshed, "/v1/farms").status_code == 403
    assert s.rest(refreshed, "GET", "farms", params={"select": "id"}).json() == []
    # 7c. an edited token: the guard lets it pass, but the signature does not
    forged = _forge(refreshed, must_change_password=False)
    r = s.get(forged, "/v1/farms")
    assert r.status_code == 401, r.text[:200]
    assert s.rest(forged, "GET", "farms", params={"select": "id"}).status_code == 401
    r = s.api.post("/v1/me/password", headers={"Authorization": f"Bearer {forged}"},
                   json={"current_password": farmer["temporary_password"], "new_password": "Forged-Pass9"})
    assert r.status_code == 401
    assert s.flag(farmer["user_id"]) is True


def test_accounts_without_the_flag_are_unaffected(stack):
    s = stack
    # 9. the manager (no flag) works as before
    assert s.flag(s.manager_id) is None
    assert s.get(s.manager, "/v1/me").json()["must_change_password"] is False
    assert s.get(s.manager, f"/v1/organizations/{s.org}/farmers").status_code == 200
    # 8. an existing farmer account created before this change (no flag at all)
    user_id, email, password = s.create_user("legacy")
    s.admin.table("organization_memberships").insert({"organization_id": s.org, "user_id": user_id, "role": "farmer"}).execute()
    farm = s.admin.table("farms").insert({"cooperative_id": s.org, "farm_code": f"FPC-{s.run}-L", "farm_name": "legacy"}).execute().data[0]["id"]
    s.admin.table("farm_members").insert({"farm_id": farm, "user_id": user_id, "farm_role": "owner"}).execute()
    token = s.token(email, password)
    assert s.get(token, "/v1/me").json()["must_change_password"] is False
    assert farm in {f["id"] for f in s.get(token, "/v1/farms").json()["items"]}
    # the same endpoint changes a normal account's password too, and sets no flag
    r = s.api.post("/v1/me/password", headers={"Authorization": f"Bearer {token}"},
                   json={"current_password": password, "new_password": "Legacy-Own-77"})
    assert r.status_code == 200 and s.flag(user_id) is False


def test_missing_or_invalid_sessions_get_the_standard_401(stack):
    s = stack
    body = {"current_password": "Whatever-1a", "new_password": "Another-2b"}
    r = s.api.post("/v1/me/password", json=body)
    assert r.status_code == 401 and r.json()["detail"]["error"]["code"] == "unauthenticated"
    r = s.api.post("/v1/me/password", headers={"Authorization": "Bearer not-a-jwt"}, json=body)
    assert r.status_code == 401 and r.json()["detail"]["error"]["code"] == "unauthenticated"
    # 10. a signed-out (revoked) session can no longer change the password
    farmer = _provision(s, "revoked")
    token = s.token(farmer["email"], farmer["temporary_password"])
    s.httpx.post(f"{s.url}/auth/v1/logout?scope=global", timeout=30,
                 headers={"apikey": s.publishable, "Authorization": f"Bearer {token}"})
    r = s.api.post("/v1/me/password", headers={"Authorization": f"Bearer {token}"},
                   json={"current_password": farmer["temporary_password"], "new_password": "After-Logout-9"})
    assert r.status_code == 401 and r.json()["detail"]["error"]["code"] == "unauthenticated"
    assert s.flag(farmer["user_id"]) is True


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_a_token_minted_with_the_temporary_password_stays_refused_after_the_change(stack):
    """TOKEN_OLD (minted while the flag was true) is refused on every layer
    BEFORE and AFTER the change, until it expires; TOKEN_NEW gets normal access
    (migration 20261003090000). Whoever saw the temporary password and signed in
    early must not inherit the farmer's access once the farmer changes it."""
    import psycopg

    s = stack
    farmer = _provision(s, "stale")                                   # 1. flag = true
    batch = _season(s, farmer["plot_id"])
    old = s.token(farmer["email"], farmer["temporary_password"])       # 2. TOKEN_OLD
    assert _claims(old)["app_metadata"]["must_change_password"] is True

    def activity(token):
        return s.rest(token, "POST", "activities", json={
            "production_batch_id": batch, "activity_type": "irrigation", "occurred_at": "2026-06-01T00:00:00Z",
            "recorded_at": "2026-06-01T00:00:00Z", "source": "web", "recorded_by": farmer["user_id"]})

    def refused_everywhere(token):
        for table in ("farms", "plots", "crop_seasons", "production_batches", "activities"):
            assert s.rest(token, "GET", table, params={"select": "id"}).json() == [], table
        assert activity(token).status_code in (401, 403)
        renamed = s.rest(token, "PATCH", "plots", params={"id": f"eq.{farmer['plot_id']}"}, json={"name": "STALE"})
        assert renamed.status_code in (200, 401, 403) and (renamed.status_code != 200 or renamed.json() == [])
        assert s.get(token, "/v1/farms").status_code == 403
        # The SQL helpers with the token's own claims, as PostgREST sets them.
        with psycopg.connect(_DB_URL) as conn:
            conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(_claims(token)),))
            for fn in ("user_can_read_farm", "user_can_write_farm"):
                assert conn.execute(f"select private.{fn}(%s::uuid)", (farmer["farm_id"],)).fetchone()[0] is False, fn

    refused_everywhere(old)                                            # 3. before the change

    new_password = f"Own-{uuid.uuid4().hex[:10]}A1"                    # 4. change
    r = s.api.post("/v1/me/password", headers={"Authorization": f"Bearer {old}"},
                   json={"current_password": farmer["temporary_password"], "new_password": new_password})
    assert r.status_code == 200
    assert s.flag(farmer["user_id"]) is False                          # 5. authoritative flag cleared

    refused_everywhere(old)                                            # 6. TOKEN_OLD still refused

    new = s.token(farmer["email"], new_password)                       # 7. TOKEN_NEW
    assert not _claims(new).get("app_metadata", {}).get("must_change_password")
    assert [f["id"] for f in s.rest(new, "GET", "farms", params={"select": "id"}).json()] == [farmer["farm_id"]]
    created = activity(new)                                            # 8. normal permissions
    assert created.status_code == 201, created.text[:200]
    activity_id = created.json()[0]["id"]
    assert farmer["farm_id"] in {f["id"] for f in s.get(new, "/v1/farms").json()["items"]}
    # TOKEN_OLD can neither see nor touch what TOKEN_NEW wrote.
    assert s.rest(old, "GET", "activities", params={"select": "id", "id": f"eq.{activity_id}"}).json() == []
    s.rest(old, "DELETE", "activities", params={"id": f"eq.{activity_id}"})
    assert [a["id"] for a in s.rest(new, "GET", "activities", params={"select": "id", "id": f"eq.{activity_id}"}).json()] \
        == [activity_id]
    with psycopg.connect(_DB_URL) as conn:
        assert conn.execute("select name from public.plots where id = %s", (farmer["plot_id"],)).fetchone()[0] != "STALE"

    forged = _forge(old, must_change_password=False)                   # 9. edited claim: signature fails
    assert s.rest(forged, "GET", "farms", params={"select": "id"}).status_code == 401
    assert s.get(forged, "/v1/farms").status_code == 401
