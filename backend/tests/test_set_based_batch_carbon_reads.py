"""Migration 20261105090000: set-based SELECT policies on production_batches and carbon_calculations.

production_batches_select now tests `crop_season_id in (select private.readable_crop_ids())`
and the two carbon_calculations policies test membership in readable_batch_ids() /
readable_crop_ids(), instead of calling private.user_can_read_crop / user_can_read_batch
once per row. This pins that the change is a PLAN change only: for every kind of reader
the lifecycle harness builds (owner, viewer, manager, former owner, former/expired
members, an outsider from another cooperative), exactly the rows the per-row helpers
admit are visible -- a soft-deleted batch stays hidden, a season-scoped calculation
(no batch) is readable through its season only -- and no SELECT policy on these
tables calls the per-row helpers again.

Real Postgres, role `authenticated` with `request.jwt.claims`, one transaction per
test, always rolled back. Skipped without SUPABASE_DB_URL.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.test_db_lifecycle_rls import _DB_URL, Tx, psycopg

pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")

READERS = ("owner", "former", "viewer", "manager", "expired_manager", "outsider")
TABLES = ("production_batches", "carbon_calculations")


class Reads(Tx):
    def __init__(self, conn):
        super().__init__(conn)
        # A second, soft-deleted batch in the active season.
        self.deleted_batch = self.one("insert into public.production_batches (crop_season_id, batch_code, deleted_at)"
                                      " values (%s, 'deleted', now()) returning id", (self.seasons["active"],))
        self.all_batches = [*self.batches.values(), self.deleted_batch]
        factor_set = self.one("""insert into public.emission_factor_sets (version_code, name, methodology_name, source_name, status)
                                 values (%s, 'set-based RLS test', 'TEST ONLY', 'rls-test', 'draft') returning id""",
                              (f"RLS-SET-{uuid.uuid4().hex[:8]}",))
        # Per season: one season-scoped calculation (no batch) and one tied to its batch.
        self.calcs = []
        for status, season in self.seasons.items():
            for batch in (None, self.batches[status]):
                self.calcs.append(self.one(
                    """insert into public.carbon_calculations (crop_season_id, production_batch_id, scenario, factor_set_id,
                         engine_version, input_hash, total_co2e_kg, status)
                       values (%s, %s, 'actual', %s, 'rls-test', %s, 1, 'succeeded') returning id""",
                    (season, batch, factor_set, uuid.uuid4().hex + uuid.uuid4().hex)))

    def ids_as(self, who, sql, params=()):
        self.cur.execute("savepoint r")
        try:
            self.cur.execute("set local role authenticated")
            self.cur.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s","role":"authenticated"}' % who,))
            self.cur.execute(sql, params)
            return {str(r[0]) for r in self.cur.fetchall()}
        finally:
            self.cur.execute("rollback to savepoint r")

    def _helper(self, who, fn, arg) -> bool:
        return bool(self.ids_as(who, f"select 'y' where private.{fn}(%s)", (arg,)))

    def expected_batches(self, who) -> set[str]:
        """The per-row definition: live, and user_can_read_crop(its season)."""
        out = set()
        for b in self.all_batches:
            self.cur.execute("select crop_season_id, deleted_at is null from public.production_batches where id = %s", (b,))
            season, live = self.cur.fetchone()
            if live and self._helper(who, "user_can_read_crop", season):
                out.add(str(b))
        return out

    def expected_calcs(self, who) -> set[str]:
        """The per-row definition: user_can_read_batch(batch) OR user_can_read_crop(season)."""
        out = set()
        for c in self.calcs:
            self.cur.execute("select production_batch_id, crop_season_id from public.carbon_calculations where id = %s", (c,))
            batch, season = self.cur.fetchone()
            if (batch is not None and self._helper(who, "user_can_read_batch", batch)) or self._helper(who, "user_can_read_crop", season):
                out.add(str(c))
        return out

    def visible(self, who):
        return (self.ids_as(who, "select id from public.production_batches where id = any(%s)", (self.all_batches,)),
                self.ids_as(who, "select id from public.carbon_calculations where id = any(%s)", (self.calcs,)))


@pytest.fixture
def rx():
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        try:
            yield Reads(conn)
        finally:
            conn.rollback()


@pytest.mark.parametrize("who", READERS)
def test_visible_batches_equal_the_per_row_helper(rx, who):
    user = getattr(rx, who)
    batches, _ = rx.visible(user)
    assert batches == rx.expected_batches(user), who
    assert str(rx.deleted_batch) not in batches


@pytest.mark.parametrize("who", READERS)
def test_visible_calculations_equal_the_per_row_helpers(rx, who):
    user = getattr(rx, who)
    _, calcs = rx.visible(user)
    assert calcs == rx.expected_calcs(user), who


@pytest.mark.parametrize("who", READERS)
def test_readable_crop_ids_is_the_set_form_of_user_can_read_crop(rx, who):
    user = getattr(rx, who)
    got = rx.ids_as(user, "select c::text from private.readable_crop_ids() as c where c = any(%s)", (list(rx.seasons.values()),))
    assert got == {str(s) for s in rx.seasons.values() if rx._helper(user, "user_can_read_crop", s)}, who


def test_the_manager_reads_live_rows_and_the_outsider_none(rx):
    # Guards the parametrized tests against a vacuous "both empty" pass.
    batches, calcs = rx.visible(rx.manager)
    assert len(batches) == len(rx.batches) and len(calcs) == len(rx.calcs)
    assert rx.visible(rx.outsider) == (set(), set())


def _select_quals(rx):
    rx.cur.execute("select tablename, policyname, qual from pg_policies where schemaname = 'public' and cmd = 'SELECT'"
                   " and tablename = any(%s)", (list(TABLES),))
    return {(t, p): q for t, p, q in rx.cur.fetchall()}


def test_no_select_policy_on_these_tables_calls_a_per_row_helper(rx):
    quals = _select_quals(rx)
    assert set(quals) == {("production_batches", "production_batches_select"),
                          ("carbon_calculations", "carbon_calculations_select"),
                          ("carbon_calculations", "carbon_calculations_select_crop_season")}
    for key, qual in quals.items():
        assert "user_can_read_" not in qual, key
        assert "readable_crop_ids" in qual or "readable_batch_ids" in qual, key


def test_the_set_function_is_not_callable_by_anon(rx):
    rx.cur.execute("select has_function_privilege('anon', 'private.readable_crop_ids()', 'execute'),"
                   " has_function_privilege('authenticated', 'private.readable_crop_ids()', 'execute')")
    assert rx.cur.fetchone() == (False, True)


# --------------------------------------------------------------- guards kept
# readable_crop_ids() reaches every guard through private.user_can_read_farm, per STATEMENT.

@pytest.mark.parametrize("who", ("owner", "viewer", "manager"))
def test_a_pending_password_change_hides_every_row(rx, who):
    user = getattr(rx, who)
    assert rx.visible(user)[0], who  # not vacuous
    rx.cur.execute("update auth.users set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb)"
                   " || '{\"must_change_password\": true}'::jsonb where id = %s", (user,))
    assert rx.visible(user) == (set(), set()), who
    assert rx.ids_as(user, "select c::text from private.readable_crop_ids() as c") == set(), who


def test_removing_the_farm_role_revokes_reads_in_the_next_statement(rx):
    assert rx.visible(rx.viewer)[0]
    rx.cur.execute("delete from public.farm_members where farm_id = %s and user_id = %s", (rx.farm, rx.viewer))
    assert rx.visible(rx.viewer) == (set(), set())
    assert rx.expected_batches(rx.viewer) == set() == rx.expected_calcs(rx.viewer)


def test_ending_the_manager_membership_revokes_reads_in_the_next_statement(rx):
    assert rx.visible(rx.manager)[0]
    rx.cur.execute("update public.organization_memberships set ended_at = now() - interval '1 second'"
                   " where user_id = %s and organization_id = %s", (rx.manager, rx.coop))
    assert rx.visible(rx.manager) == (set(), set())


def test_anon_reads_nothing(rx):
    for table in TABLES:
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
_REPO = Path(__file__).resolve().parents[2]
_UP = _REPO / "supabase/migrations/20261105090000_set_based_batch_carbon_read_policies.sql"
_DOWN = _REPO / "supabase/rollbacks/20261105090000_set_based_batch_carbon_read_policies.down.sql"


def _snapshot(rx):
    return {who: rx.visible(getattr(rx, who)) for who in READERS}


def test_rollback_restores_the_per_row_policies_with_the_same_access_and_reapplies(rx):
    """down.sql then the migration again, inside the (rolled back) test transaction."""
    with_set = _snapshot(rx)

    rx.cur.execute(_DOWN.read_text(encoding="utf-8"))
    quals = _select_quals(rx)
    assert len(quals) == 3
    assert all("user_can_read_" in q and "readable_crop_ids" not in q for q in quals.values()), quals
    rx.cur.execute("select to_regprocedure('private.readable_crop_ids()')")
    assert rx.cur.fetchone()[0] is None
    assert _snapshot(rx) == with_set

    rx.cur.execute(_UP.read_text(encoding="utf-8"))
    quals = _select_quals(rx)
    assert all("user_can_read_" not in q for q in quals.values()), quals
    assert _snapshot(rx) == with_set
