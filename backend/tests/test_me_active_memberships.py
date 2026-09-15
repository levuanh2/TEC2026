"""B7: `/v1/me` never advertises a role from an ended organization membership.

Uses the same RLS-result fake as `test_read_repository.py`: RLS lets a user read
their own membership rows even after `ended_at`, so the fake returns them too and
the repository must drop them. The clock is pinned.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure import memberships  # noqa: E402
from infrastructure.read_repo import SupabaseReadRepository  # noqa: E402
from service import MrvExportService  # noqa: E402
from tests.test_read_repository import DUMMY_SETTINGS, FakeSupabaseClient  # noqa: E402

USER = "user-1"
NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
PAST, EXACT, FUTURE = "2026-09-15T11:59:59Z", "2026-09-15T12:00:00Z", "2026-09-15T12:00:01Z"


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setattr(memberships, "utcnow", lambda: NOW)


def me_for(org_rows, farm_rows=()):
    rows = {
        "profiles": [{"id": USER, "full_name": "QA"}],
        "organization_memberships": [{"user_id": USER, **row} for row in org_rows],
        "farm_members": [{"user_id": USER, **row} for row in farm_rows],
    }
    return SupabaseReadRepository(DUMMY_SETTINGS, "token", client=FakeSupabaseClient(rows, USER)).me()


def test_active_cooperative_manager_is_reported():
    me = me_for([{"organization_id": "org-1", "role": "cooperative_manager", "ended_at": None}])
    assert me["roles"] == ["cooperative_manager"]
    assert [m["organization_id"] for m in me["organization_memberships"]] == ["org-1"]


def test_ended_cooperative_manager_is_not_reported():
    me = me_for([{"organization_id": "org-1", "role": "cooperative_manager", "ended_at": PAST}])
    assert "cooperative_manager" not in me["roles"]
    assert me["organization_memberships"] == []


def test_ended_manager_with_active_farmer_membership_keeps_only_valid_roles():
    me = me_for(
        [
            {"organization_id": "org-old", "role": "cooperative_manager", "ended_at": PAST},
            {"organization_id": "org-new", "role": "farmer", "ended_at": None},
        ],
        [{"farm_id": "farm-1", "farm_role": "owner"}],
    )
    assert me["roles"] == ["farmer", "owner"]
    assert [m["organization_id"] for m in me["organization_memberships"]] == ["org-new"]
    # The web picks the organization from the first membership; an ended one
    # must not be first.
    assert me["organization_memberships"][0]["role"] == "farmer"


def test_no_active_organization_role_leaves_only_farm_roles():
    # Current contract: `roles` is simply the union of what remains; the web
    # falls back to the Farmer shell when no organization role matches.
    me = me_for(
        [{"organization_id": "org-1", "role": "farmer", "ended_at": PAST}],
        [{"farm_id": "farm-1", "farm_role": "editor"}],
    )
    assert me["roles"] == ["editor"]
    assert me["organization_memberships"] == []


@pytest.mark.parametrize(("ended_at", "reported"), [(PAST, False), (EXACT, False), (FUTURE, True), (None, True)])
def test_end_boundary_matches_sql_strict_greater_than(ended_at, reported):
    me = me_for([{"organization_id": "org-1", "role": "cooperative_manager", "ended_at": ended_at}])
    assert ("cooperative_manager" in me["roles"]) is reported


@pytest.mark.parametrize(("ended_at", "manages"), [(PAST, False), (EXACT, False), (FUTURE, True), (None, True)])
def test_mrv_management_check_agrees_with_me(ended_at, manages):
    actor = {"organization_memberships": [
        {"organization_id": "org-1", "role": "cooperative_manager", "ended_at": ended_at},
    ]}
    assert MrvExportService._manages(actor, "org-1") is manages
    me = me_for(actor["organization_memberships"])
    assert ("cooperative_manager" in me["roles"]) is manages
