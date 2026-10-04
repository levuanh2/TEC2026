"""The staging E2E harness (scripts/staging_render_flow.py) against Core V1.

Runs the script's own `main()`/`flow()` with the real `main.app` in-process in
place of the deployed Render API, on a LOCAL Supabase stack (real GoTrue,
PostgREST and RLS). Nothing about authentication or authorization is faked:
the forced first-login password change is exactly what staging enforces.

* the pre-Core-V1 sequence (temporary password -> business API) is refused,
  which is why the old harness failed against a healthy staging;
* the new sequence passes: temporary-password token refused, password
  changed, that token STILL refused, business smoke only with the new token;
* no password or token reaches the script's output;
* cleanup runs, and leaves nothing, when the flow fails half-way.

Creates users and a tenant, so it only runs against a LOCAL stack.
"""
from __future__ import annotations

import importlib
import sys
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


class Recorder:
    """The real app in-process; records which bearer token each call carried,
    the status it got, and the passwords the flow handled (to prove none of
    them is printed). Kept in test memory only."""

    def __init__(self):
        from fastapi.testclient import TestClient

        from main import app

        self.client = TestClient(app, raise_server_exceptions=False)
        self.calls: list[tuple[str, str, str | None, int]] = []
        self.secrets: set[str] = set()

    def request(self, method, path, headers=None, json=None):
        r = self.client.request(method, path, headers=headers or {}, json=json)
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ") or None
        if token:
            self.secrets.add(token)
        if isinstance(json, dict):
            self.secrets.update(v for k, v in json.items() if "password" in k and isinstance(v, str))
        if r.status_code == 201 and path.endswith("/farmers"):
            self.secrets.add(r.json()["temporary_password"])
        self.calls.append((method, path, token, r.status_code))
        return r


@pytest.fixture()
def harness(monkeypatch):
    import scripts.staging_render_flow as flow_module

    mod = importlib.reload(flow_module)  # fresh run tag, results and ids per test
    rec = Recorder()
    monkeypatch.setattr(mod, "CLIENT", rec)
    monkeypatch.setattr(mod, "API", "in-process")
    return mod, rec


def _no_secret_printed(out: str, rec: Recorder) -> list[str]:
    return [f"{len(s)}-char secret" for s in rec.secrets if s and s in out]


def test_the_pre_core_v1_sequence_is_refused(harness):
    """What the old harness did -- business call with the temporary password --
    is refused by Core V1 (403 password_change_required), so the old check
    `farmer_scope_has_provisioned_farm` could only fail on a healthy staging."""
    mod, rec = harness
    try:
        org = mod.admin.table("organizations").insert(
            {"organization_code": mod.TAG, "name": mod.TAG, "organization_type": "cooperative"}).execute().data[0]
        email, password = f"{mod.EMAIL_PREFIX}manager@agricarbon-ci.invalid", "Ci-Old-Sequence-1!A"
        manager = mod.admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        mod.admin.table("organization_memberships").insert(
            {"organization_id": org["id"], "user_id": manager.id, "role": "cooperative_manager"}).execute()
        r = mod.api(mod.sign_in(email, password), "POST", f"/v1/organizations/{org['id']}/farmers", {
            "full_name": "old", "email": f"{mod.EMAIL_PREFIX}farmer@agricarbon-ci.invalid",
            "farm": {"farm_code": f"{mod.TAG}-FARM", "farm_name": mod.TAG},
            "plot": {"plot_code": f"{mod.TAG}-PLOT", "name": mod.TAG, "area_ha": 1.0}})
        assert r.status_code == 201, r.text[:200]
        prov = r.json()
        temp_token = mod.sign_in(f"{mod.EMAIL_PREFIX}farmer@agricarbon-ci.invalid", prov["temporary_password"])
        old = mod.api(temp_token, "GET", "/v1/farmer/scope")  # the old harness's first farmer call
        assert old.status_code == 403 and mod.error_code(old) == "password_change_required"
        assert prov["farm_id"] not in old.text
    finally:
        assert mod.cleanup() == []


def test_the_harness_follows_the_forced_password_sequence(harness, capsys):
    mod, rec = harness
    assert mod.main() == 0
    out = capsys.readouterr().out
    failed = [name for name, ok, _ in mod.results if not ok]
    assert not failed, failed
    names = [name for name, _, _ in mod.results]
    sequence = ["temp_password_me_reports_must_change_password", "temp_password_token_business_access_denied",
                "password_change_200", "old_token_still_denied_after_password_change",
                "new_token_is_a_different_token", "farmer_scope_has_provisioned_farm"]
    assert [n for n in names if n in sequence] == sequence  # in this order
    assert {"cleanup_row_counts_restored", "cleanup_no_auth_users_left"} <= set(names)

    # The temporary-password token (TOKEN_OLD) is the one that changed the
    # password. Outside /v1/me and the change itself it never got anything but
    # 403, and no business call was made with it after the change succeeded.
    change = next(i for i, c in enumerate(rec.calls) if c[:2] == ("POST", "/v1/me/password"))
    token_old = rec.calls[change][2]
    for method, path, token, status in rec.calls:
        if token == token_old and path not in ("/v1/me", "/v1/me/password"):
            assert status == 403, (method, path, status)
    after = rec.calls[change + 1:]
    assert any(t == token_old for _, _, t, _ in after)                       # re-checked after the change...
    assert all(s == 403 for _, p, t, s in after if t == token_old)            # ...and still refused
    farmer_business = [c for c in after if c[2] not in (None, token_old) and "/v1/farmer/scope" in c[1]]
    assert farmer_business and all(c[3] == 200 for c in farmer_business)    # TOKEN_NEW does the smoke

    assert _no_secret_printed(out, rec) == []


def test_cleanup_runs_and_leaves_nothing_when_the_flow_fails(harness, monkeypatch, capsys):
    mod, rec = harness
    real_sign_in = mod.sign_in
    calls = {"n": 0}

    def failing_sign_in(email, password):
        calls["n"] += 1
        if calls["n"] == 3:  # manager, temporary password, then the NEW password: fail here
            raise RuntimeError("simulated outage after the password change")
        return real_sign_in(email, password)

    monkeypatch.setattr(mod, "sign_in", failing_sign_in)
    assert mod.main() == 1
    out = capsys.readouterr().out
    results = {name: ok for name, ok, _ in mod.results}
    assert results["flow_completed_without_exception"] is False
    assert results["cleanup_steps_succeeded"] and results["cleanup_verified"]
    assert results["cleanup_row_counts_restored"] and results["cleanup_no_auth_users_left"]
    assert _no_secret_printed(out, rec) == []
