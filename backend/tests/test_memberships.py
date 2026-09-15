"""B7: one definition of an active organization membership.

Mirrors the SQL rule used by every `private.*` membership helper:
`ended_at is null or ended_at > now()`. Clock is always pinned.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.memberships import active_memberships, is_active_membership  # noqa: E402

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_membership_without_end_is_active():
    assert is_active_membership({"ended_at": None}, NOW)
    assert is_active_membership({}, NOW)


def test_past_end_is_inactive():
    assert not is_active_membership({"ended_at": NOW - timedelta(microseconds=1)}, NOW)
    assert not is_active_membership({"ended_at": "2026-01-01T00:00:00Z"}, NOW)


def test_end_exactly_now_is_inactive_like_sql_strict_greater_than():
    assert not is_active_membership({"ended_at": NOW}, NOW)
    assert not is_active_membership({"ended_at": "2026-09-15T12:00:00+00:00"}, NOW)


def test_future_end_is_still_active():
    assert is_active_membership({"ended_at": NOW + timedelta(microseconds=1)}, NOW)
    assert is_active_membership({"ended_at": "2099-01-01T00:00:00Z"}, NOW)


def test_offsets_are_compared_as_instants():
    # 19:00+07:00 == 12:00Z -> exactly now -> inactive; 19:00:01+07:00 -> active.
    assert not is_active_membership({"ended_at": "2026-09-15T19:00:00+07:00"}, NOW)
    assert is_active_membership({"ended_at": "2026-09-15T19:00:01+07:00"}, NOW)


def test_naive_timestamp_is_read_as_utc():
    assert not is_active_membership({"ended_at": datetime(2026, 9, 15, 12, 0, 0)}, NOW)
    assert is_active_membership({"ended_at": datetime(2026, 9, 15, 12, 0, 1)}, NOW)


def test_active_memberships_keeps_order_and_drops_only_ended_rows():
    rows = [
        {"id": 1, "ended_at": None},
        {"id": 2, "ended_at": "2026-01-01T00:00:00Z"},
        {"id": 3, "ended_at": "2099-01-01T00:00:00Z"},
    ]
    assert [r["id"] for r in active_memberships(rows, NOW)] == [1, 3]
