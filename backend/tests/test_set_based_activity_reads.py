"""Migration 20261104090000: set-based SELECT policies on activities + detail tables.

The policies now test `production_batch_id in (select private.readable_batch_ids())`
instead of calling private.user_can_read_batch once per row. This pins that the
change is a PLAN change only: for every kind of reader the lifecycle harness
builds (owner, viewer, manager, former owner, former/expired members, an
outsider from another cooperative), exactly the rows the per-row helper admits
are visible -- including that a soft-deleted activity and its detail rows stay
hidden -- and that no policy on these tables calls the per-row helper again.

Real Postgres, role `authenticated` with `request.jwt.claims`, one transaction
per test, always rolled back. Skipped without SUPABASE_DB_URL.
"""
from __future__ import annotations

import pytest

from tests.test_db_lifecycle_rls import _DB_URL, Tx, psycopg

pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")

DETAIL_TABLES = (
    "seeding_events", "fertilizer_applications", "irrigation_events", "pesticide_applications",
    "fuel_usages", "straw_management_events", "harvest_events",
)
READERS = ("owner", "former", "viewer", "manager", "expired_manager", "outsider")


class Reads(Tx):
    def __init__(self, conn):
        super().__init__(conn)
        # One live activity per season status, plus one soft-deleted one.
        self.acts = {status: self.activity(status) for status in self.batches}
        self.deleted = self.activity("active")
        self.cur.execute("update public.activities set deleted_at = now() where id = %s", (self.deleted,))
        self.all_acts = [*self.acts.values(), self.deleted]

    def ids_as(self, who, sql, params=()):
        self.cur.execute("savepoint r")
        try:
            self.cur.execute("set local role authenticated")
            self.cur.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s","role":"authenticated"}' % who,))
            self.cur.execute(sql, params)
            return {str(r[0]) for r in self.cur.fetchall()}
        finally:
            self.cur.execute("rollback to savepoint r")

    def expected_activities(self, who) -> set[str]:
        """What the per-row definition admits: live, and user_can_read_batch."""
        out = set()
        for a in self.all_acts:
            self.cur.execute("select production_batch_id, deleted_at is null from public.activities where id = %s", (a,))
            batch, live = self.cur.fetchone()
            readable = self.ids_as(who, "select %s::text where private.user_can_read_batch(%s)", (str(batch), batch))
            if live and readable:
                out.add(str(a))
        return out


@pytest.fixture
def rx():
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        try:
            yield Reads(conn)
        finally:
            conn.rollback()


@pytest.mark.parametrize("who", READERS)
def test_visible_activities_equal_the_per_row_helper(rx, who):
    user = getattr(rx, who)
    seen = rx.ids_as(user, "select id from public.activities where id = any(%s)", (rx.all_acts,))
    assert seen == rx.expected_activities(user), who
    assert str(rx.deleted) not in seen


@pytest.mark.parametrize("who", READERS)
def test_detail_rows_follow_their_visible_activity(rx, who):
    user = getattr(rx, who)
    expected = rx.expected_activities(user)
    for table in DETAIL_TABLES:
        seen = rx.ids_as(user, f"select activity_id from public.{table} where activity_id = any(%s)", (rx.all_acts,))
        # The harness writes irrigation rows; every other table must show none
        # it does not hold, and irrigation exactly the visible activities.
        if table == "irrigation_events":
            assert seen == expected, (who, table)
        else:
            assert seen <= expected, (who, table)


def test_the_manager_reads_live_rows_and_the_outsider_none(rx):
    # Guards the parametrized tests against a vacuous "both empty" pass.
    assert len(rx.ids_as(rx.manager, "select id from public.activities where id = any(%s)", (rx.all_acts,))) == len(rx.acts)
    assert rx.ids_as(rx.outsider, "select id from public.activities where id = any(%s)", (rx.all_acts,)) == set()


def test_no_select_policy_on_these_tables_calls_the_per_row_helper(rx):
    rx.cur.execute(
        "select tablename, qual from pg_policies where schemaname = 'public' and cmd = 'SELECT' and tablename = any(%s)",
        (["activities", *DETAIL_TABLES],),
    )
    rows = rx.cur.fetchall()
    assert {t for t, _ in rows} == {"activities", *DETAIL_TABLES}
    for table, qual in rows:
        assert "user_can_read_batch" not in qual, table
        assert "readable_batch_ids" in qual, table


def test_the_set_function_is_not_callable_by_anon(rx):
    rx.cur.execute("select has_function_privilege('anon', 'private.readable_batch_ids()', 'execute'),"
                   " has_function_privilege('authenticated', 'private.readable_batch_ids()', 'execute')")
    assert rx.cur.fetchone() == (False, True)


# --------------------------------------------------------------- guards kept
# readable_batch_ids() reaches every guard through private.user_can_read_farm.
# These pin that the guards still bite through the new policies, and that they
# bite per STATEMENT: a change made earlier in the same transaction (a
# revocation, a flag) is seen by the next read, nothing is cached across them.

def _visible(rx, user):
    acts = rx.ids_as(user, "select id from public.activities where id = any(%s)", (rx.all_acts,))
    details = {t: rx.ids_as(user, f"select activity_id from public.{t} where activity_id = any(%s)", (rx.all_acts,))
               for t in DETAIL_TABLES}
    return acts, details


@pytest.mark.parametrize("who", ("owner", "viewer", "manager"))
def test_a_pending_password_change_hides_every_row(rx, who):
    user = getattr(rx, who)
    assert rx.ids_as(user, "select id from public.activities where id = any(%s)", (rx.all_acts,)), who  # not vacuous
    rx.cur.execute("update auth.users set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb)"
                   " || '{\"must_change_password\": true}'::jsonb where id = %s", (user,))
    acts, details = _visible(rx, user)
    assert acts == set() == rx.expected_activities(user), who
    assert all(v == set() for v in details.values()), (who, details)
    assert rx.ids_as(user, "select id::text from private.readable_batch_ids()") == set(), who


def test_removing_the_farm_role_revokes_reads_in_the_next_statement(rx):
    assert rx.ids_as(rx.viewer, "select id from public.activities where id = any(%s)", (rx.all_acts,))
    rx.cur.execute("delete from public.farm_members where farm_id = %s and user_id = %s", (rx.farm, rx.viewer))
    acts, details = _visible(rx, rx.viewer)
    assert acts == set() == rx.expected_activities(rx.viewer)
    assert all(v == set() for v in details.values()), details


def test_ending_the_manager_membership_revokes_reads_in_the_next_statement(rx):
    assert rx.ids_as(rx.manager, "select id from public.activities where id = any(%s)", (rx.all_acts,))
    rx.cur.execute("update public.organization_memberships set ended_at = now() - interval '1 second'"
                   " where user_id = %s and organization_id = %s", (rx.manager, rx.coop))
    acts, details = _visible(rx, rx.manager)
    assert acts == rx.expected_activities(rx.manager) == set()
    assert all(v == set() for v in details.values()), details


def test_anon_reads_nothing(rx):
    for table in ("activities", *DETAIL_TABLES):
        rx.cur.execute("savepoint a")
        try:
            rx.cur.execute("set local role anon")
            rx.cur.execute("select set_config('request.jwt.claims', '{\"role\":\"anon\"}', true)")
            rx.cur.execute(f"select count(*) from public.{table}")
            assert rx.cur.fetchone()[0] == 0, table
        except psycopg.errors.InsufficientPrivilege:
            pass  # no grant at all is also "nothing"
        finally:
            rx.cur.execute("rollback to savepoint a")


# --------------------------------------------------------------- rollback
from pathlib import Path  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_UP = _REPO / "supabase/migrations/20261104090000_set_based_activity_read_policies.sql"
_DOWN = _REPO / "supabase/rollbacks/20261104090000_set_based_activity_read_policies.down.sql"


def _snapshot(rx):
    return {who: _visible(rx, getattr(rx, who)) for who in READERS}


def _select_quals(rx):
    rx.cur.execute("select tablename, qual from pg_policies where schemaname = 'public' and cmd = 'SELECT'"
                   " and tablename = any(%s)", (["activities", *DETAIL_TABLES],))
    return dict(rx.cur.fetchall())


def test_rollback_restores_the_per_row_policies_with_the_same_access_and_reapplies(rx):
    """down.sql then the migration again, inside the (rolled back) test transaction."""
    with_set = _snapshot(rx)

    rx.cur.execute(_DOWN.read_text(encoding="utf-8"))
    quals = _select_quals(rx)
    assert set(quals) == {"activities", *DETAIL_TABLES}
    assert all("user_can_read_batch" in q and "readable_batch_ids" not in q for q in quals.values()), quals
    rx.cur.execute("select to_regprocedure('private.readable_batch_ids()')")
    assert rx.cur.fetchone()[0] is None
    assert _snapshot(rx) == with_set

    rx.cur.execute(_UP.read_text(encoding="utf-8"))
    quals = _select_quals(rx)
    assert all("readable_batch_ids" in q and "user_can_read_batch" not in q for q in quals.values()), quals
    assert _snapshot(rx) == with_set
