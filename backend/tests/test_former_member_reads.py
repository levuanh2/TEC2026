"""Core V1 closure (3A): who still READS a farm after the cooperative membership ends.

Real Postgres, real RLS: statements run as role `authenticated` with
`request.jwt.claims`, as PostgREST runs a Flutter request or a FastAPI read
forwarded with the caller's JWT. One transaction per test, always rolled back.

Reuses the lifecycle harness (`Tx`), where `former` is a farm OWNER whose
membership ended. Product decision (2026-10-03, docs/CORE_V1_CLOSURE.md):

* a former farm OWNER keeps READ-ONLY access to the history of the farm they own,
  and nothing else: no write, no other farm, no organization-scoped record;
* a former farm editor/viewer loses every read that came from the membership
  (migration 20261002090000);
* across cooperatives, only an independent membership/ownership grants access.

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


def _farm_in(rx: Readers, org, code: str, members: tuple = ()):
    """A farm with one plot and an active season; `members` are (user, role) given
    while the user's membership is active, as validate_farm_member requires."""
    farm = rx.one("insert into public.farms (cooperative_id, farm_code, farm_name) values (%s, %s, 'FMR') returning id",
                  (org, f"{code}-{uuid.uuid4().hex[:6]}"))
    for user, role in members:
        rx.cur.execute("update public.organization_memberships set ended_at = null where user_id = %s and organization_id = %s",
                       (user, org))
        rx.cur.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, %s)", (farm, user, role))
    plot = rx.one("insert into public.plots (farm_id, plot_code, name, area_ha) values (%s, %s, 'FMR', 1) returning id",
                  (farm, f"{code}-P"))
    season = rx.one("insert into public.crop_seasons (plot_id, season_code, status) values (%s, %s, 'active') returning id",
                    (plot, f"{code}-S"))
    return farm, plot, season


def _farm_reads(rx: Readers, who, farm, plot, season) -> dict[str, int]:
    return {
        "farms": rx.visible(who, "select 1 from public.farms where id = %s", (farm,)),
        "plots": rx.visible(who, "select 1 from public.plots where id = %s", (plot,)),
        "crop_seasons": rx.visible(who, "select 1 from public.crop_seasons where id = %s", (season,)),
        "user_can_read_farm": int(rx.helper(who, "user_can_read_farm", farm)),
    }


# -- A. active owner ------------------------------------------------------------

def test_active_owner_reads_and_writes_while_the_season_is_open(rx):
    assert all(n >= 1 for n in _reads(rx, rx.owner).values())
    assert rx.insert_as(rx.owner, "active") == ("ok", 1)
    # The lifecycle still decides: a closed season refuses the same owner.
    assert rx.insert_as(rx.owner, "closed") == ("err", "55000")
    assert rx.helper(rx.owner, "user_can_write_farm", rx.farm) is True


# -- B. former owner ------------------------------------------------------------

def test_former_owner_reads_own_farm_history(rx):
    """Product decision 2026-10-03: a farmer who left the HTX keeps READ-ONLY
    access to the history of the farm they own."""
    reads = _reads(rx, rx.former)
    assert all(n >= 1 for n in reads.values()), reads
    assert rx.helper(rx.former, "user_can_read_farm", rx.farm) is True
    assert rx.helper(rx.former, "user_can_read_crop", rx.seasons["active"]) is True
    assert rx.helper(rx.former, "user_can_read_batch", rx.batches["active"]) is True


def test_former_owner_writes_nothing_on_own_farm(rx):
    a = rx.activity("active")
    assert rx.insert_as(rx.former, "active")[0] == "err"
    # Refused loudly (20260926100000), never a silent 0-row update.
    assert rx.as_user(rx.former, "update public.activities set note = 'x' where id = %s", (a,)) == ("err", "42501")
    assert rx.as_user(rx.former, "select public.soft_delete_activity(%s)", (a,))[0] == "err"
    assert rx.as_user(rx.former, "insert into public.plots (farm_id, plot_code, name, area_ha) values (%s, 'X', 'X', 1)",
                      (rx.farm,))[0] == "err"
    assert rx.as_user(rx.former, "update public.crop_seasons set season_code = 'x' where id = %s",
                      (rx.seasons["active"],)) == ("ok", 0)
    assert rx.as_user(rx.former, "update public.farm_members set farm_role = 'editor' where farm_id = %s and user_id = %s",
                      (rx.farm, rx.viewer)) == ("ok", 0)
    assert rx.as_user(rx.former, "delete from public.farm_members where farm_id = %s", (rx.farm,)) == ("ok", 0)
    for fn in ("user_can_write_farm", "user_can_manage_farm_members"):
        assert rx.helper(rx.former, fn, rx.farm) is False, fn
    assert rx.helper(rx.former, "user_can_write_crop", rx.seasons["active"]) is False


def test_former_owner_reads_no_other_farm(rx):
    # Same HTX, owned by someone else; same HTX, where the former owner was a
    # viewer; another HTX. Owning ONE farm reaches no further.
    others = [
        _farm_in(rx, rx.coop, "FMR-A", ((rx.owner, "owner"),)),
        _farm_in(rx, rx.coop, "FMR-B", ((rx.owner, "owner"), (rx.former, "viewer"))),
        _farm_in(rx, rx.other, "FMR-C", ((rx.outsider, "viewer"),)),
    ]
    rx.cur.execute("update public.organization_memberships set ended_at = now() - interval '1 day'"
                   " where user_id = %s and organization_id = %s", (rx.former, rx.coop))
    for farm, plot, season in others:
        assert _farm_reads(rx, rx.former, farm, plot, season) == dict.fromkeys(
            ("farms", "plots", "crop_seasons", "user_can_read_farm"), 0)
    # Control: the active owner does read the first one.
    assert all(_farm_reads(rx, rx.owner, *others[0]).values())


def test_former_owner_reads_no_organization_scoped_record(rx):
    for table, column in (("organizations", "id"), ("organization_data_grants", "source_organization_id")):
        assert rx.visible(rx.former, f"select 1 from public.{table} where {column} = %s", (rx.coop,)) == 0, table
    # Only their own (ended) membership row, never the other members'.
    assert rx.visible(rx.former, "select 1 from public.organization_memberships where organization_id = %s"
                      " and user_id <> %s", (rx.coop, rx.former)) == 0
    # Fellow farm members' profiles stay hidden.
    assert rx.visible(rx.former, "select 1 from public.profiles where id in (%s, %s, %s)",
                      (rx.owner, rx.viewer, rx.manager)) == 0
    # Controls: the rows exist and an active member sees them.
    assert rx.visible(rx.manager, "select 1 from public.profiles where id in (%s, %s)", (rx.owner, rx.viewer)) == 2
    assert rx.visible(rx.owner, "select 1 from public.organization_memberships where organization_id = %s"
                      " and user_id <> %s", (rx.coop, rx.owner)) >= 1
    for fn in ("user_can_read_organization", "user_is_org_member", "user_is_org_manager"):
        assert rx.helper(rx.former, fn, rx.coop) is False, fn


# -- C. former editor/viewer: farm reads are in DENIED above -----------------------

@pytest.mark.parametrize("who", ["former_viewer", "former_editor"])
def test_former_editor_viewer_read_no_organization_record(rx, who):
    user = getattr(rx, who)
    assert rx.visible(user, "select 1 from public.organizations where id = %s", (rx.coop,)) == 0
    assert rx.helper(user, "user_can_read_organization", rx.coop) is False
    assert rx.helper(user, "user_can_write_farm", rx.farm) is False


# -- D. cross-organization ----------------------------------------------------------

def test_cross_org_access_needs_an_independent_membership_or_ownership(rx):
    farm, plot, season = _farm_in(rx, rx.other, "FMR-X", ((rx.outsider, "owner"),))
    # The outsider owns a farm in the other HTX: that farm only.
    assert all(_farm_reads(rx, rx.outsider, farm, plot, season).values())
    assert all(n == 0 for n in _reads(rx, rx.outsider).values())
    # Members of this HTX, active or not, read nothing of the other HTX's farm.
    for who in ("owner", "viewer", "manager", "former"):
        assert not any(_farm_reads(rx, getattr(rx, who), farm, plot, season).values()), who
