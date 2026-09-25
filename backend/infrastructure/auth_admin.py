"""Server-side Supabase Auth administration for farmer provisioning.

The service-role key never leaves the backend: Management Web asks FastAPI,
FastAPI calls the Supabase Auth Admin API. React never talks to it.

Only the three operations provisioning needs exist here, so the rest of the
admin surface (listing every user, changing emails, ...) is not reachable
through this adapter at all.
"""
from __future__ import annotations

from typing import Any

from .config import Settings


class AuthUserExistsError(Exception):
    """Supabase Auth already has an identity with this email."""


class SupabaseAuthAdmin:
    def __init__(self, settings: Settings, client: Any | None = None):
        self._settings = settings
        self._client = client

    def _admin(self) -> Any:
        if self._client is None:
            from supabase import create_client

            url, key = self._settings.require_supabase()
            self._client = create_client(url, key)
        return self._client.auth.admin

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
