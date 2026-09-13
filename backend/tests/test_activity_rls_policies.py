"""Regression tests for the `public.activities` ownership + soft-delete contract.

These run against a REAL PostgreSQL/Supabase database, as role `authenticated`
with a real `request.jwt.claims`, because that is the only place the contract
actually lives: RLS policies, the `private.*` helpers they call, and the
PostgreSQL rule that applies SELECT policies to the new row of an UPDATE. A fake
cannot reproduce any of it.

Every test runs inside one transaction that is always rolled back, and every row
is created by the test itself, so the target database is left unchanged.

Skipped when `SUPABASE_DB_URL` is not configured (backend/.env or environment).

Against the pre-`20260913090000` schema these fail:
  * `public.soft_delete_activity` does not exist (undefined_function);
  * a caller can reassign `recorded_by`, retype an activity and rewrite the
    offline idempotency key.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from infrastructure.config import load_settings  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the RLS tests.")

_DB_URL = load_settings().supabase_db_url

pytestmark = pytest.mark.skipif(
    not _DB_URL,
    reason="SUPABASE_DB_URL is not configured; the RLS contract needs a real database.",
)

FARM_CODE = "DEMO-FARM-01"
CROSS_FARM_CODE = "DEMO-FARM-02"


class Session:
    """One rolled-back transaction plus the helpers the tests need."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.cur = conn.cursor()

    # -- fixtures inside the transaction ----------------------------------

    def batch_for(self, farm_code: str) -> uuid.UUID:
        self.cur.execute(
            """
            select pb.id from public.production_batches pb
            join public.crop_seasons cs on cs.id = pb.crop_season_id
            join public.plots p on p.id = cs.plot_id
            join public.farms f on f.id = p.farm_id
            where f.farm_code = %s
            limit 1
            """,
            (farm_code,),
        )
        row = self.cur.fetchone()
        assert row, f"no production batch under {farm_code}"
        return row[0]

    def a_user_with_write_access_to(self, farm_code: str) -> uuid.UUID:
        """A plain farmer scoped to this farm.

        Deliberately not "any owner/editor": an organization manager is also a
        writer on every farm of their cooperative, so picking one would make the
        cross-scope assertions vacuous. The isolation contract is about the
        farmer persona, so that is who these tests run as.
        """
        self.cur.execute(
            """
            select fm.user_id from public.farm_members fm
            join public.farms f on f.id = fm.farm_id
            join public.organization_memberships om
              on om.user_id = fm.user_id
             and om.organization_id = f.cooperative_id
            where f.farm_code = %s
              and fm.farm_role in ('owner','editor')
              and om.role = 'farmer'
              and (om.ended_at is null or om.ended_at > now())
            limit 1
            """,
            (farm_code,),
        )
        row = self.cur.fetchone()
        assert row, f"no scoped farmer member on {farm_code}"
        return row[0]

    def a_different_user(self, not_this_one: uuid.UUID) -> uuid.UUID:
        self.cur.execute(
            "select id from public.profiles where id <> %s limit 1", (not_this_one,)
        )
        row = self.cur.fetchone()
        assert row, "expected at least two profiles"
        return row[0]

    def make_activity(self, batch: uuid.UUID, recorder: uuid.UUID | None) -> uuid.UUID:
        self.cur.execute(
            "insert into public.devices (user_id, installation_id, platform) "
            "values (%s, gen_random_uuid(), 'android') returning id",
            (recorder or self.a_user_with_write_access_to(FARM_CODE),),
        )
        device = self.cur.fetchone()[0]
        self.cur.execute(
            """
            insert into public.activities
              (production_batch_id, activity_type, occurred_at, recorded_at, source,
               recorded_by, device_id, client_event_id, note)
            values (%s,'irrigation',now(),now(),'mobile_offline',%s,%s,gen_random_uuid(),
                    'RLS-CONTRACT-TEST')
            returning id
            """,
            (batch, recorder, device),
        )
        activity = self.cur.fetchone()[0]
        self.cur.execute(
            "insert into public.irrigation_events (activity_id, method, water_volume_m3) "
            "values (%s, 'continuous_flooding', 2.0)",
            (activity,),
        )
        return activity

    # -- running statements as a real caller ------------------------------

    def as_user(self, user: uuid.UUID, sql: str, params: tuple = (), fetch: bool = False):
        """Run one statement as role `authenticated` with `sub` = user.

        Returns ("ok", rows|rowcount) or ("err", sqlstate). A denial is rolled
        back to a savepoint so the transaction stays usable.
        """
        self.cur.execute("savepoint stmt")
        try:
            self.cur.execute("set local role authenticated")
            self.cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                ('{"sub":"%s","role":"authenticated"}' % user,),
            )
            self.cur.execute(sql, params)
            out = self.cur.fetchall() if fetch else self.cur.rowcount
            self.cur.execute("reset role")
            self.cur.execute("release savepoint stmt")
            return ("ok", out)
        except psycopg.Error as exc:
            self.cur.execute("rollback to savepoint stmt")
            return ("err", exc.sqlstate)

    def deleted_at_of(self, activity: uuid.UUID):
        self.cur.execute("select deleted_at from public.activities where id=%s", (activity,))
        row = self.cur.fetchone()
        return row[0] if row else None


@pytest.fixture
def db():
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        try:
            yield Session(conn)
        finally:
            conn.rollback()


@pytest.fixture
def farmer(db: Session) -> uuid.UUID:
    return db.a_user_with_write_access_to(FARM_CODE)


@pytest.fixture
def own_batch(db: Session) -> uuid.UUID:
    return db.batch_for(FARM_CODE)


@pytest.fixture
def cross_batch(db: Session) -> uuid.UUID:
    return db.batch_for(CROSS_FARM_CODE)


# --------------------------------------------------------------------------
# The failure this contract exists to fix
# --------------------------------------------------------------------------


def test_client_update_of_deleted_at_is_still_rejected(db, farmer, own_batch):
    """The reason there is an RPC at all.

    PostgreSQL applies SELECT policies to the NEW row of an UPDATE that needs
    read access, and `activities_select` requires `deleted_at is null`. So a
    client setting `deleted_at` itself fails 42501 no matter what the UPDATE
    policy allows. If this ever starts passing, the RPC can be reconsidered --
    it would mean the SELECT policy stopped hiding deleted rows.
    """
    activity = db.make_activity(own_batch, farmer)

    assert db.as_user(farmer, "update public.activities set note='ok' where id=%s", (activity,)) == ("ok", 1)

    status, state = db.as_user(
        farmer, "update public.activities set deleted_at=now() where id=%s", (activity,)
    )
    assert (status, state) == ("err", "42501")
    assert db.deleted_at_of(activity) is None


# --------------------------------------------------------------------------
# Own soft delete
# --------------------------------------------------------------------------


def test_owner_can_soft_delete_own_activity(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)

    assert db.as_user(
        farmer, "select public.soft_delete_activity(%s)", (activity,), fetch=True
    ) == ("ok", [(True,)])
    assert db.deleted_at_of(activity) is not None


def test_soft_deleted_row_is_hidden_from_a_normal_select(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)
    db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,), fetch=True)

    assert db.as_user(
        farmer, "select id from public.activities where id=%s", (activity,), fetch=True
    ) == ("ok", [])
    # ...but the row is still there for a privileged reader.
    db.cur.execute("select count(*) from public.activities where id=%s", (activity,))
    assert db.cur.fetchone()[0] == 1


def test_soft_delete_is_idempotent(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)
    first = db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,), fetch=True)
    deleted_at = db.deleted_at_of(activity)
    second = db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,), fetch=True)

    assert first == second == ("ok", [(True,)])
    # The second call must not re-stamp the row, so the audit keeps one event.
    assert db.deleted_at_of(activity) == deleted_at
    db.cur.execute("select row_version from public.activities where id=%s", (activity,))
    assert db.cur.fetchone()[0] == 2


def test_soft_delete_keeps_the_subtype_row(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)
    db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,), fetch=True)

    db.cur.execute(
        "select count(*) from public.irrigation_events where activity_id=%s", (activity,)
    )
    assert db.cur.fetchone()[0] == 1, "a soft delete must not cascade to the detail row"


def test_a_soft_deleted_row_cannot_be_resurrected_by_its_owner(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)
    db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,), fetch=True)

    # Invisible to the caller, so the UPDATE matches nothing rather than undeleting.
    assert db.as_user(
        farmer, "update public.activities set deleted_at=null where id=%s", (activity,)
    ) == ("ok", 0)
    assert db.deleted_at_of(activity) is not None


# --------------------------------------------------------------------------
# Ownership isolation
# --------------------------------------------------------------------------


def test_soft_delete_of_another_users_activity_is_denied(db, farmer, own_batch):
    other = db.a_different_user(farmer)
    activity = db.make_activity(own_batch, other)

    assert db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,))[1] == "42501"
    assert db.deleted_at_of(activity) is None


def test_soft_delete_across_scope_is_denied(db, farmer, cross_batch):
    activity = db.make_activity(cross_batch, None)

    assert db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,))[1] == "42501"
    assert db.deleted_at_of(activity) is None


def test_soft_delete_of_an_unowned_row_is_denied(db, farmer, own_batch):
    """`recorded_by is null` is not "everyone's"; it is nobody's."""
    activity = db.make_activity(own_batch, None)

    assert db.as_user(farmer, "select public.soft_delete_activity(%s)", (activity,))[1] == "42501"
    assert db.deleted_at_of(activity) is None


def test_an_unauthenticated_caller_cannot_soft_delete(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)

    db.cur.execute("savepoint anon_stmt")
    db.cur.execute("set local role anon")
    db.cur.execute("select set_config('request.jwt.claims', '{\"role\":\"anon\"}', true)")
    with pytest.raises(psycopg.Error) as excinfo:
        db.cur.execute("select public.soft_delete_activity(%s)", (activity,))
    db.cur.execute("rollback to savepoint anon_stmt")

    assert excinfo.value.sqlstate == "42501"
    assert db.deleted_at_of(activity) is None


# --------------------------------------------------------------------------
# Ownership and scope cannot be moved to get around the above
# --------------------------------------------------------------------------


def test_ownership_cannot_be_reassigned(db, farmer, own_batch):
    """Without this, "delete only your own row" is worthless: claim, then delete."""
    other = db.a_different_user(farmer)
    activity = db.make_activity(own_batch, other)

    assert db.as_user(
        farmer, "update public.activities set recorded_by=%s where id=%s", (farmer, activity)
    )[1] == "42501"

    db.cur.execute("select recorded_by from public.activities where id=%s", (activity,))
    assert db.cur.fetchone()[0] == other


def test_an_owner_cannot_hand_their_row_to_someone_else(db, farmer, own_batch):
    other = db.a_different_user(farmer)
    activity = db.make_activity(own_batch, farmer)

    assert db.as_user(
        farmer, "update public.activities set recorded_by=%s where id=%s", (other, activity)
    )[1] == "42501"


def test_an_unowned_row_may_only_be_claimed_by_the_caller_themselves(db, farmer, own_batch):
    other = db.a_different_user(farmer)
    activity = db.make_activity(own_batch, None)

    assert db.as_user(
        farmer, "update public.activities set recorded_by=%s where id=%s", (other, activity)
    )[1] == "42501"
    assert db.as_user(
        farmer, "update public.activities set recorded_by=%s where id=%s", (farmer, activity)
    ) == ("ok", 1)


def test_scope_cannot_be_changed_cross_farm(db, farmer, own_batch, cross_batch):
    activity = db.make_activity(own_batch, farmer)

    assert db.as_user(
        farmer,
        "update public.activities set production_batch_id=%s where id=%s",
        (cross_batch, activity),
    )[1] == "42501"


def test_activity_type_and_offline_key_are_immutable(db, farmer, own_batch):
    activity = db.make_activity(own_batch, farmer)

    assert db.as_user(
        farmer, "update public.activities set activity_type='fuel' where id=%s", (activity,)
    )[1] == "42501"
    assert db.as_user(
        farmer,
        "update public.activities set client_event_id=gen_random_uuid() where id=%s",
        (activity,),
    )[1] == "42501"


def test_a_normal_edit_that_resends_the_same_row_still_works(db, farmer, own_batch):
    """What the mobile sync actually sends: the whole row, unchanged identity."""
    activity = db.make_activity(own_batch, farmer)

    assert db.as_user(
        farmer,
        "update public.activities set note=%s, recorded_by=%s where id=%s",
        ("edited on the phone", farmer, activity),
    ) == ("ok", 1)


# --------------------------------------------------------------------------
# Cross-scope reads and writes, unchanged by this migration
# --------------------------------------------------------------------------


def test_cross_scope_rows_are_neither_readable_nor_writable(db, farmer, cross_batch):
    activity = db.make_activity(cross_batch, None)

    assert db.as_user(
        farmer, "select id from public.activities where id=%s", (activity,), fetch=True
    ) == ("ok", [])
    assert db.as_user(
        farmer, "update public.activities set note='x' where id=%s", (activity,)
    ) == ("ok", 0)
    assert db.as_user(
        farmer,
        "insert into public.activities "
        "(production_batch_id,activity_type,occurred_at,recorded_at,source,recorded_by) "
        "values (%s,'irrigation',now(),now(),'web',%s)",
        (cross_batch, farmer),
    )[1] == "42501"


# --------------------------------------------------------------------------
# Server-side paths must keep working
# --------------------------------------------------------------------------


def test_the_backend_soft_delete_statement_works_on_a_mobile_row(db, farmer, own_batch):
    """`ActivityWriteRepository.soft_delete`, verbatim, on a mobile-created row.

    This is what P1-4 unblocks: with `recorded_by` populated, the FastAPI
    endpoint can remove a row the phone created.
    """
    activity = db.make_activity(own_batch, farmer)

    db.cur.execute(
        "update public.activities set deleted_at=now(), updated_at=now(), "
        "row_version=row_version+1 where id=%s and recorded_by=%s and deleted_at is null",
        (activity, farmer),
    )
    assert db.cur.rowcount == 1


def test_privileged_maintenance_keeps_real_delete_and_free_updates(db, farmer, own_batch):
    """Seed/cleanup scripts run as service role and must not be constrained.

    The immutability trigger stands down when row-level security is not active
    for the caller, and nothing here converts a privileged DELETE into a soft
    delete -- `cleanup_demo_data.py` depends on both.
    """
    other = db.a_different_user(farmer)
    activity = db.make_activity(own_batch, farmer)

    db.cur.execute(
        "update public.activities set recorded_by=%s, activity_type='fuel' where id=%s",
        (other, activity),
    )
    assert db.cur.rowcount == 1

    db.cur.execute("delete from public.irrigation_events where activity_id=%s", (activity,))
    db.cur.execute("delete from public.activities where id=%s", (activity,))
    assert db.cur.rowcount == 1
    db.cur.execute("select count(*) from public.activities where id=%s", (activity,))
    assert db.cur.fetchone()[0] == 0
