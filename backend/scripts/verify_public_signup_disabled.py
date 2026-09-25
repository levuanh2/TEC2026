"""Verify the hosted project refuses public sign-up but still provisions.

Product rule: AgriCarbon has no public farmer registration; cooperative
managers provision accounts through FastAPI (Supabase Auth Admin API).

Run:
    python backend/scripts/verify_public_signup_disabled.py

Checks, against the project in backend/.env:
  1. `GET /auth/v1/settings` reports `disable_signup: true` and email sign-in on;
  2. a public `POST /auth/v1/signup` with the publishable key is refused;
  3. the Admin API (service role, what provisioning uses) can still create a
     user who can then sign in with email/password.
Any user created by check 2 (if sign-up were open) or check 3 is deleted.
Nothing secret is printed.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

settings = load_settings()
URL, SERVICE = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
admin = create_client(URL, SERVICE)
TAG = uuid.uuid4().hex[:8]
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def delete_by_email(email: str) -> None:
    for user in admin.auth.admin.list_users(page=1, per_page=1000):
        if (user.email or "").lower() == email:
            admin.auth.admin.delete_user(user.id)


def main() -> int:
    s = httpx.get(f"{URL}/auth/v1/settings", headers={"apikey": PUBLISHABLE}, timeout=30).json()
    check("hosted_disable_signup_is_true", s.get("disable_signup") is True, f"disable_signup={s.get('disable_signup')}")
    check("email_password_sign_in_still_enabled", (s.get("external") or {}).get("email") is True)

    # A syntactically valid domain, so the refusal cannot be "invalid email".
    public_email = f"signup-probe-{TAG}@example.com"
    try:
        r = httpx.post(f"{URL}/auth/v1/signup", headers={"apikey": PUBLISHABLE},
                       json={"email": public_email, "password": f"Probe-{uuid.uuid4().hex}!A1"}, timeout=30)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        # Only GoTrue's own refusal counts: an invalid address or an email rate
        # limit also fails the request, but says nothing about sign-up policy.
        refused = r.status_code in (400, 403, 422) and body.get("error_code") == "signup_disabled"
        check("public_signup_refused", refused, f"HTTP {r.status_code} error_code={body.get('error_code')}")
    finally:
        delete_by_email(public_email)

    admin_email = f"provision-probe-{TAG}@agricarbon.invalid"
    password = f"Pv-{uuid.uuid4().hex}!A1"
    try:
        admin.auth.admin.create_user({"email": admin_email, "password": password, "email_confirm": True})
        check("admin_provisioning_still_creates_users", True)
        login = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                           json={"email": admin_email, "password": password}, timeout=30)
        check("provisioned_user_can_sign_in", login.status_code == 200, f"HTTP {login.status_code}")
    except Exception as exc:  # noqa: BLE001
        check("admin_provisioning_still_creates_users", False, type(exc).__name__)
    finally:
        delete_by_email(admin_email)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
