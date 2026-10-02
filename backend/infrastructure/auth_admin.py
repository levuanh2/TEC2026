"""Server-side Supabase Auth administration for farmer provisioning.

The service-role key never leaves the backend: Management Web asks FastAPI,
FastAPI calls the Supabase Auth Admin API. React never talks to it.

Only the operations provisioning and the forced first-login password change
need exist here, so the rest of the admin surface (listing every user,
changing emails, ...) is not reachable through this adapter at all.

`app_metadata.must_change_password` is the authoritative "still on the
temporary password" flag: set at provisioning, cleared only by
`replace_temporary_password`. Users cannot write `app_metadata`; the database
enforces the flag (`private.password_change_pending`, migration 20261002100000).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings

MUST_CHANGE_PASSWORD = "must_change_password"


class AuthUserExistsError(Exception):
    """Supabase Auth already has an identity with this email."""


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    email: str | None
    must_change_password: bool


def must_change_password(app_metadata: dict[str, Any] | None) -> bool:
    return (app_metadata or {}).get(MUST_CHANGE_PASSWORD) is True


class SupabaseAuthAdmin:
    def __init__(self, settings: Settings, client: Any | None = None):
        self._settings = settings
        self._client = client

    def _supabase(self) -> Any:
        if self._client is None:
            from supabase import create_client

            url, key = self._settings.require_supabase()
            self._client = create_client(url, key)
        return self._client

    def _admin(self) -> Any:
        return self._supabase().auth.admin

    def create_user(self, *, email: str, password: str, full_name: str, attempt: str) -> str:
        """Create a confirmed email/password identity; returns its user id.

        `email_confirm`: the cooperative vouches for the address -- there is no
        public sign-up or confirmation mail in this product. `full_name` rides
        in user metadata so the `on_auth_user_created` trigger fills the profile.
        `attempt` marks the identity as this provisioning attempt's own, so a
        compensation after an ambiguous failure can never remove another
        request's identity.
        """
        try:
            response = self._admin().create_user({
                "email": email, "password": password, "email_confirm": True,
                "user_metadata": {"full_name": full_name, "provisioning_attempt": attempt},
                # The manager has seen this password: it must be replaced first.
                "app_metadata": {MUST_CHANGE_PASSWORD: True},
            })
        except Exception as exc:  # noqa: BLE001 - classify, never echo the payload
            code = getattr(exc, "code", None)
            message = str(getattr(exc, "message", "") or exc).lower()
            if code == "email_exists" or "already been registered" in message or "already registered" in message:
                raise AuthUserExistsError() from exc
            raise
        return str(response.user.id)

    def delete_user(self, user_id: str) -> None:
        self._admin().delete_user(user_id)

    def ban_user(self, user_id: str) -> None:
        """Fallback when deleting fails: an identity that cannot sign in."""
        self._admin().update_user_by_id(user_id, {"ban_duration": "876000h"})

    def identity(self, token: str) -> AuthIdentity | None:
        """The live Auth user behind `token` (Supabase Auth verifies it), or None."""
        user = self._supabase().auth.get_user(token).user
        if user is None:
            return None
        return AuthIdentity(str(user.id), user.email, must_change_password(user.app_metadata))

    def password_is_current(self, email: str, password: str) -> bool:
        """Whether `password` signs `email` in right now (Supabase Auth password grant).

        The session that check opens is revoked at once; rate limits are Supabase
        Auth's own. The password is sent only to Supabase Auth, never logged.
        """
        import httpx

        url, _ = self._settings.require_supabase()
        _, publishable = self._settings.require_publishable()
        r = httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": publishable},
                       json={"email": email, "password": password}, timeout=20)
        if r.status_code in (400, 401):
            return False
        r.raise_for_status()
        try:
            httpx.post(f"{url}/auth/v1/logout?scope=local", timeout=20,
                       headers={"apikey": publishable, "Authorization": f"Bearer {r.json()['access_token']}"})
        except httpx.HTTPError:  # the probe session expires on its own; the change must not fail on it
            pass
        return True

    def replace_temporary_password(self, user_id: str, new_password: str) -> None:
        """Set the new password AND clear the flag in one Auth Admin call."""
        self._admin().update_user_by_id(user_id, {"password": new_password, "app_metadata": {MUST_CHANGE_PASSWORD: False}})
