"""Active organization membership — the one Python copy of the SQL rule.

Every RLS helper that looks at `organization_memberships`
(`private.user_is_org_member`, `private.user_is_org_manager`,
`private.user_can_read_organization`, ...) treats a membership as active when

    ended_at is null or ended_at > now()

`joined_at` is not part of that rule, so it is not part of this one either. Code
that decides something from membership rows it already holds (the `roles` of
`/v1/me`, the MRV management check) must use this module instead of
re-deriving the rule, so the API can never advertise or honour a role the
database has already retired.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def utcnow() -> datetime:
    """Current instant; a module function so tests can pin the clock."""
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        # `ended_at` is timestamptz; PostgREST always sends an offset. A naive
        # value can only come from a caller, and is read as UTC like Postgres.
        value = value.replace(tzinfo=timezone.utc)
    return value


def is_active_membership(membership: dict[str, Any], now: datetime | None = None) -> bool:
    ended = membership.get("ended_at")
    if ended is None:
        return True
    return _as_utc(ended) > (now or utcnow())


def active_memberships(rows: Iterable[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    at = now or utcnow()
    return [row for row in rows if is_active_membership(row, at)]
