"""P1 lifecycle + active-membership rules at the DATABASE, for every client.

Real Postgres, real RLS: statements run as role `authenticated` with
`request.jwt.claims`, exactly as PostgREST runs a Flutter request. One
transaction per test, always rolled back; every row is created inside it.

If the target database does not have migration 20260926090000 yet, the test
applies it INSIDE the rolled-back transaction first -- so the rules can be
verified before the migration is deployed, and nothing persists either way.

Skipped without SUPABASE_DB_URL.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from infrastructure.config import load_settings  # noqa: E402
from tests._lifecycle_migration import ensure_lifecycle_migration  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the RLS tests.")

_DB_URL = load_settings().supabase_db_url
pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


class Tx:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()
        ensure_lifecycle_migration(conn)
        tag = uuid.uuid4().hex[:8]
        self.coop = self.one("insert into public.organizations (organization_code, name, organization_type) values (%s, %s, 'cooperative') returning id", (f"LC-{tag}", f"LC-{tag}"))
        self.other = self.one("insert into public.organizations (organization_code, name, organization_type) values (%s, %s, 'cooperative') returning id", (f"LC-O-{tag}", f"LC-O-{tag}"))
        self.owner = self.user(self.coop, "farmer")
        self.former = self.user(self.coop, "farmer")
        self.viewer = self.user(self.coop, "farmer")
        self.manager = self.user(self.coop, "cooperative_manager")
        self.expired_manager = self.user(self.coop, "cooperative_manager")
        self.outsider = self.user(self.other, "farmer")
        self.farm = self.one("insert into public.farms (cooperative_id, farm_code, farm_name) values (%s, %s, 'LC') returning id", (self.coop, f"LC-F-{tag}"))
        for u, role in ((self.owner, "owner"), (self.former, "owner"), (self.viewer, "viewer")):
            self.cur.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, %s)", (self.farm, u, role))
        other_farm = self.one("insert into public.farms (cooperative_id, farm_code, farm_name) values (%s, %s, 'LC-O') returning id", (self.other, f"LC-OF-{tag}"))
        self.cur.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, 'owner')", (other_farm, self.outsider))
        # The membership ends after the farm role exists: the role outlives it.
        self.cur.execute("update public.organization_memberships set joined_at = now() - interval '9 days', ended_at = now() - interval '1 day' where user_id in (%s, %s)", (self.former, self.expired_manager))
        self.plot = self.one("insert into public.plots (farm_id, plot_code, name, area_ha) values (%s, %s, 'LC', 1) returning id", (self.farm, f"LC-P-{tag}"))
        self.seasons, self.batches = {}, {}
        for status in ("active", "harvested", "closed", "cancelled", "planned"):
            s = self.one("insert into public.crop_seasons (plot_id, season_code, status) values (%s, %s, %s) returning id", (self.plot, f"LC-{status}", status))
            self.seasons[status] = s
            self.batches[status] = self.one("insert into public.production_batches (crop_season_id, batch_code) values (%s, 'default') returning id", (s,))

    def one(self, sql, params=()):
        self.cur.execute(sql, params)
        return self.cur.fetchone()[0]

    def user(self, org, role):
        uid = uuid.uuid4()
        self.cur.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated', 'authenticated', now())", (uid, f"lc-{uid.hex[:8]}@agricarbon-test.invalid"))
        self.cur.execute("insert into public.organization_memberships (organization_id, user_id, role, joined_at) values (%s, %s, %s, now() - interval '10 days')", (org, uid, role))
        return uid

    def activity(self, status, recorded_by=None):
        """Recorded earlier (backend session, no RLS), with its detail row."""
        a = self.one("""insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, note)
                        values (%s, 'irrigation', now(), now(), 'web', %s, 'LC') returning id""", (self.batches[status], recorded_by or self.owner))
        self.cur.execute("insert into public.irrigation_events (activity_id, method, water_volume_m3) values (%s, 'awd', 1)", (a,))
        return a

    def as_user(self, user, sql, params=()):
        """('ok', rowcount) or ('err', sqlstate) -- savepoint-isolated, role authenticated."""
        self.cur.execute("savepoint s")
        try:
            self.cur.execute("set local role authenticated")
            self.cur.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s","role":"authenticated"}' % user,))
            self.cur.execute(sql, params)
            n = self.cur.rowcount
            self.cur.execute("reset role")
            self.cur.execute("release savepoint s")
            return ("ok", n)
        except psycopg.Error as exc:
            self.cur.execute("rollback to savepoint s")
            return ("err", exc.sqlstate)

    def insert_as(self, user, status):
        return self.as_user(user, """insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, note)
                                     values (%s, 'irrigation', now(), now(), 'web', %s, 'LC-client')""", (self.batches[status], user))


@pytest.fixture
def tx():
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        try:
            yield Tx(conn)
        finally:
            conn.rollback()


NOT_OPEN = ["harvested", "closed", "cancelled", "planned"]


# ---------------------------------------------------------------- lifecycle

def test_active_season_writer_can_insert_update_and_delete(tx):
    assert tx.insert_as(tx.owner, "active") == ("ok", 1)
    a = tx.activity("active")
    assert tx.as_user(tx.owner, "update public.activities set note = 'x' where id = %s", (a,)) == ("ok", 1)
    assert tx.as_user(tx.owner, "update public.irrigation_events set water_volume_m3 = 2 where activity_id = %s", (a,)) == ("ok", 1)
    assert tx.as_user(tx.owner, "select public.soft_delete_activity(%s)", (a,))[0] == "ok"


@pytest.mark.parametrize("status", NOT_OPEN)
def test_not_open_season_refuses_every_activity_mutation_loudly(tx, status):
    assert tx.insert_as(tx.owner, status) == ("err", "55000")
    a = tx.activity(status)
    # An error, never a silent 0-row update the Flutter client would take as synced.
    assert tx.as_user(tx.owner, "update public.activities set note = 'x' where id = %s", (a,)) == ("err", "55000")
    assert tx.as_user(tx.owner, "select public.soft_delete_activity(%s)", (a,)) == ("err", "55000")


@pytest.mark.parametrize("status", NOT_OPEN)
def test_detail_tables_are_not_a_side_door(tx, status):
    a = tx.activity(status)
    upsert = """insert into public.irrigation_events (activity_id, method, water_volume_m3) values (%s, 'awd', 5)
                on conflict (activity_id) do update set water_volume_m3 = excluded.water_volume_m3"""
    assert tx.as_user(tx.owner, upsert, (a,)) == ("err", "55000")
    assert tx.as_user(tx.owner, "update public.irrigation_events set water_volume_m3 = 9 where activity_id = %s", (a,)) == ("err", "55000")
    # Direct detail deletes are not a client operation at all (20260926110000).
    assert tx.as_user(tx.owner, "delete from public.irrigation_events where activity_id = %s", (a,)) == ("err", "42501")


def test_a_closed_batch_in_an_active_season_is_closed_too(tx):
    tx.cur.execute("update public.production_batches set status = 'closed' where id = %s", (tx.batches["active"],))
    assert tx.insert_as(tx.owner, "active") == ("err", "55000")


def test_a_soft_deleted_season_takes_no_activity(tx):
    tx.cur.execute("update public.crop_seasons set deleted_at = now() where id = %s", (tx.seasons["active"],))
    assert tx.insert_as(tx.owner, "active")[0] == "err"


def test_an_activity_cannot_be_moved_into_another_batch(tx):
    # A second open batch of the same active season: only immutability can refuse the move.
    b2 = tx.one("insert into public.production_batches (crop_season_id, batch_code) values (%s, 'second') returning id", (tx.seasons["active"],))
    a = tx.activity("active")
    assert tx.as_user(tx.owner, "update public.activities set production_batch_id = %s where id = %s", (b2, a)) == ("err", "42501")


# ------------------------------------------------------- membership revocation

@pytest.mark.parametrize("who", ["former", "expired_manager", "viewer", "outsider"])
def test_non_writers_are_refused_loudly_on_update(tx, who):
    """An error, not a silent 0-row match (migration 20260926100000)."""
    a = tx.activity("active")
    res = tx.as_user(getattr(tx, who), "update public.activities set note = 'x' where id = %s", (a,))
    if who in ("outsider", "expired_manager"):
        # Cannot even read the row: nothing to match, nothing leaked.
        assert res == ("ok", 0)
    else:
        assert res == ("err", "42501")
        detail = tx.as_user(getattr(tx, who), "update public.irrigation_events set water_volume_m3 = 9 where activity_id = %s", (a,))
        assert detail == ("err", "42501")


def test_a_detail_row_cannot_be_moved_to_another_activity(tx):
    a, b = tx.activity("active"), tx.activity("active")
    tx.cur.execute("delete from public.irrigation_events where activity_id = %s", (b,))
    assert tx.as_user(tx.owner, "update public.irrigation_events set activity_id = %s where activity_id = %s", (b, a)) == ("err", "42501")


@pytest.mark.parametrize("who", ["former", "expired_manager", "viewer", "outsider"])
def test_non_writers_cannot_insert(tx, who):
    assert tx.insert_as(getattr(tx, who), "active")[0] == "err"


def test_current_owner_and_active_manager_can_write(tx):
    assert tx.insert_as(tx.owner, "active") == ("ok", 1)
    assert tx.insert_as(tx.manager, "active") == ("ok", 1)


@pytest.mark.parametrize("who", ["former", "expired_manager", "outsider"])
def test_non_writers_cannot_create_seasons(tx, who):
    res = tx.as_user(getattr(tx, who), "insert into public.crop_seasons (plot_id, season_code, status) values (%s, %s, 'active')", (tx.plot, f"LC-{who}"))
    assert res == ("err", "42501")


def test_helpers_answer_the_membership_rule(tx):
    for fn, arg in (("user_can_write_farm", tx.farm), ("user_can_write_batch", tx.batches["active"])):
        tx.cur.execute("set local role authenticated")
        for user, expected in ((tx.owner, True), (tx.manager, True), (tx.former, False), (tx.expired_manager, False), (tx.viewer, False), (tx.outsider, False)):
            tx.cur.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s","role":"authenticated"}' % user,))
            tx.cur.execute(f"select private.{fn}(%s)", (arg,))
            assert tx.cur.fetchone()[0] is expected, (fn, user)
        tx.cur.execute("reset role")


def test_a_deleted_farm_grants_no_write(tx):
    tx.cur.execute("update public.farms set deleted_at = now() where id = %s", (tx.farm,))
    assert tx.insert_as(tx.manager, "active")[0] == "err"


# ------------------------------------------------------------ season lifecycle

@pytest.mark.parametrize(("start", "to", "ok"), [
    ("planned", "active", True), ("active", "harvested", True), ("active", "closed", True), ("harvested", "closed", True),
    ("harvested", "active", False), ("closed", "active", False), ("closed", "planned", False),
    ("active", "planned", False), ("cancelled", "active", False),
])
def test_client_season_transitions(tx, start, to, ok):
    res = tx.as_user(tx.owner, "update public.crop_seasons set status = %s where id = %s", (to, tx.seasons[start]))
    assert (res == ("ok", 1)) if ok else (res == ("err", "55000"))


def test_editing_a_closed_season_without_changing_status_is_allowed(tx):
    """Flutter re-sends the whole row (status unchanged) when editing methodology."""
    assert tx.as_user(tx.owner, "update public.crop_seasons set cultivation_days = 100 where id = %s", (tx.seasons["closed"],)) == ("ok", 1)


@pytest.mark.parametrize(("status", "ok"), [("active", True), ("planned", True), ("closed", False), ("harvested", False)])
def test_clients_create_only_planned_or_active_seasons(tx, status, ok):
    res = tx.as_user(tx.owner, "insert into public.crop_seasons (plot_id, season_code, status) values (%s, %s, %s)", (tx.plot, f"LC-new-{status}", status))
    assert (res == ("ok", 1)) if ok else (res == ("err", "55000"))


def test_backend_sessions_are_not_subject_to_client_triggers(tx):
    """Seeds, imports and cleanup run without RLS and are unchanged."""
    a = tx.activity("closed")
    tx.cur.execute("delete from public.irrigation_events where activity_id = %s", (a,))
    tx.cur.execute("delete from public.activities where id = %s", (a,))


# -------------------------------------------------- batches (20260926110000)

@pytest.mark.parametrize(("status", "ok"), [("active", True), ("planned", True), ("harvested", False), ("closed", False), ("cancelled", False)])
def test_clients_create_or_touch_batches_only_in_an_open_season(tx, status, ok):
    upsert = """insert into public.production_batches (crop_season_id, batch_code) values (%s, 'default')
                on conflict (crop_season_id, batch_code) do update set batch_code = excluded.batch_code"""
    res = tx.as_user(tx.owner, upsert, (tx.seasons[status],))
    assert (res == ("ok", 1)) if ok else (res == ("err", "55000"))


def test_a_batch_cannot_be_moved_to_another_season(tx):
    res = tx.as_user(tx.owner, "update public.production_batches set crop_season_id = %s where id = %s",
                     (tx.seasons["planned"], tx.batches["active"]))
    assert res == ("err", "42501")


def test_no_client_deletes_detail_rows_directly(tx):
    a = tx.activity("active")
    for who in (tx.owner, tx.viewer, tx.former):
        assert tx.as_user(who, "delete from public.irrigation_events where activity_id = %s", (a,)) == ("err", "42501")
    # The supported removal still works: soft delete of the parent.
    assert tx.as_user(tx.owner, "select public.soft_delete_activity(%s)", (a,))[0] == "ok"
