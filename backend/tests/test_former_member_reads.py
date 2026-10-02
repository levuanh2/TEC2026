"""Core V1 closure (3A): who still READS a farm after the cooperative membership ends.

Real Postgres, real RLS: statements run as role `authenticated` with
`request.jwt.claims`, as PostgREST runs a Flutter request or a FastAPI read
forwarded with the caller's JWT. One transaction per test, always rolled back.

Reuses the lifecycle harness (`Tx`), where `former` is a farm OWNER whose
membership ended. Migration 20261002090000: a farm editor/viewer needs an active
membership in the farm's cooperative to read it. A former OWNER still reads
their own farm -- unchanged, pending a product decision (docs/CORE_V1_CLOSURE.md);
the test that pins it says so, so the decision flips one assertion.

Skipped without SUPABASE_DB_URL.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_db_lifecycle_rls import _DB_URL, Tx, psycopg

pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


class Readers(Tx):
    def __init__(self, conn):
        super().__init__(conn)
        self.former_viewer = self.farm_member("viewer", ended="now() - interval '1 day'")
        self.former_editor = self.farm_member("editor", ended="now() - interval '1 day'")
        # Ends exactly at the statement's instant: `ended_at > now()` is false -> ended.
        self.revoked_now = self.farm_member("viewer", ended="now()")
        # Still a member until tomorrow.
        self.leaving = self.farm_member("viewer", ended="now() + interval '1 day'")
        # Left this cooperative, is an active member of another one, kept the farm row.
        self.moved = self.farm_member("viewer", ended="now() - interval '1 day'")
        self.cur.execute("insert into public.organization_memberships (organization_id, user_id, role, joined_at)"
                         " values (%s, %s, 'farmer', now() - interval '1 day')", (self.other, self.moved))
        self.act = self.activity("active")

    def farm_member(self, farm_role, ended):
        uid = self.user(self.coop, "farmer")
        self.cur.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, %s)",
                         (self.farm, uid, farm_role))
        self.cur.execute(f"update public.organization_memberships set ended_at = {ended} where user_id = %s", (uid,))
        return uid

    def visible(self, who, sql, params):
        res = self.as_user(who, sql, params)
        assert res[0] == "ok", res
        return res[1]

    def helper(self, who, fn, arg):
        self.cur.execute("savepoint h")
        self.cur.execute("set local role authenticated")
        self.cur.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s","role":"authenticated"}' % who,))
        self.cur.execute(f"select private.{fn}(%s)", (arg,))
        answer = self.cur.fetchone()[0]
        self.cur.execute("rollback to savepoint h")
        return answer


@pytest.fixture
def rx():
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        try:
            yield Readers(conn)
        finally:
            conn.rollback()


def _reads(rx: Readers, who) -> dict[str, int]:
    """Rows of the farm's hierarchy `who` can see, table by table."""
    season, batch = rx.seasons["active"], rx.batches["active"]
    return {
        "farms": rx.visible(who, "select 1 from public.farms where id = %s", (rx.farm,)),
        "farm_members": rx.visible(who, "select 1 from public.farm_members where farm_id = %s", (rx.farm,)),
        "plots": rx.visible(who, "select 1 from public.plots where id = %s", (rx.plot,)),
        "crop_seasons": rx.visible(who, "select 1 from public.crop_seasons where id = %s", (season,)),
        "production_batches": rx.visible(who, "select 1 from public.production_batches where id = %s", (batch,)),
        "activities": rx.visible(who, "select 1 from public.activities where id = %s", (rx.act,)),
        "irrigation_events": rx.visible(who, "select 1 from public.irrigation_events where activity_id = %s", (rx.act,)),
    }


DENIED = ["former_viewer", "former_editor", "revoked_now", "moved", "expired_manager", "outsider"]
ALLOWED = ["owner", "viewer", "manager", "leaving"]


@pytest.mark.parametrize("who", DENIED)
def test_no_row_of_the_farm_is_visible_after_the_membership_ended(rx, who):
    reads = _reads(rx, getattr(rx, who))
    assert reads == {table: 0 for table in reads}, who


@pytest.mark.parametrize("who", ALLOWED)
def test_active_members_and_the_manager_still_read_every_level(rx, who):
    reads = _reads(rx, getattr(rx, who))
    assert all(n >= 1 for n in reads.values()), (who, reads)


@pytest.mark.parametrize("who", DENIED)
def test_read_helpers_refuse_former_members(rx, who):
    # Carbon results, recommendations, plant images (table AND Storage) and CV
    # results are read through these helpers, not through a table above.
    user = getattr(rx, who)
    assert rx.helper(user, "user_can_read_farm", rx.farm) is False
    assert rx.helper(user, "user_can_read_crop", rx.seasons["active"]) is False
    assert rx.helper(user, "user_can_read_batch", rx.batches["active"]) is False


def test_a_former_member_reads_no_organization_scoped_record(rx):
    # Organization-level reads already required an active membership; pinned here.
    for who in ("former", "former_viewer", "moved"):
        user = getattr(rx, who)
        assert rx.visible(user, "select 1 from public.organizations where id = %s", (rx.coop,)) == 0, who
        assert rx.helper(user, "user_can_read_organization", rx.coop) is False, who
    assert rx.visible(rx.moved, "select 1 from public.organizations where id = %s", (rx.other,)) == 1


def test_an_unknown_farm_and_a_revoked_farm_look_the_same(rx):
    # No existence leak: a former member gets the same nothing as for a random id.
    for farm in (rx.farm, uuid.uuid4()):
        assert rx.visible(rx.former_viewer, "select 1 from public.farms where id = %s", (farm,)) == 0


def test_writes_stay_refused_for_every_former_member(rx):
    for who in ("former", "former_viewer", "former_editor", "moved"):
        assert rx.insert_as(getattr(rx, who), "active")[0] == "err", who


def test_former_owner_still_reads_own_farm_pending_product_decision(rx):
    """PRODUCT DECISION REQUIRED (docs/CORE_V1_CLOSURE.md, 3A).

    A farmer removed from the HTX still reads their own farm's history. This
    pins the CURRENT behaviour so a change is deliberate; it is not an
    endorsement. Writes are refused (test above)."""
    reads = _reads(rx, rx.former)
    assert all(n >= 1 for n in reads.values()), reads
