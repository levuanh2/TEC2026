"""P0 security contract against the REAL database (M7, B7, B3).

Same technique as `test_activity_rls_policies.py`: one transaction per test that
is always rolled back, statements run as role `authenticated`/`anon` with a real
`request.jwt.claims`. Every row a test needs (a Storage object, a demoted farm
member, an ended membership, a regulator organization + data grant) is created
inside that transaction, so the target database is left unchanged.

Skipped when `SUPABASE_DB_URL` is not configured.

Against the pre-`20260915100000` schema the M7 tests fail (a farmer, a grant
reader and a manager can all SELECT `mrv-exports` objects). The B3 repository
tests fail against the pre-fix `write_repo` (a viewer's insert succeeds).
"""
from __future__ import annotations

import sys
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from infrastructure.config import load_settings  # noqa: E402
from infrastructure.memberships import is_active_membership  # noqa: E402
from infrastructure.write_repo import ActivityWritePermissionError, PostgresActivityWriteRepository  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the RLS tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url

pytestmark = pytest.mark.skipif(
    not _DB_URL,
    reason="SUPABASE_DB_URL is not configured; the security contract needs a real database.",
)

FARM_CODE = "DEMO-FARM-01"


class Tx:
    def __init__(self, conn) -> None:
        self.conn = conn
        self.cur = conn.cursor()

    def one(self, sql: str, params: tuple = ()):
        self.cur.execute(sql, params)
        return self.cur.fetchone()

    def run_as(self, role: str, user: uuid.UUID | None, sql: str, params: tuple = ()):
        """("ok", rows) / ("ok", rowcount) or ("err", sqlstate); savepoint-isolated."""
        self.cur.execute("savepoint stmt")
        try:
            self.cur.execute(f"set local role {role}")
            claims = '{"sub":"%s","role":"%s"}' % (user, role) if user else '{"role":"%s"}' % role
            self.cur.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
            self.cur.execute(sql, params)
            out = self.cur.fetchall() if self.cur.description else self.cur.rowcount
            self.cur.execute("reset role")
            self.cur.execute("release savepoint stmt")
            return ("ok", out)
        except psycopg.Error as exc:
            self.cur.execute("rollback to savepoint stmt")
            return ("err", exc.sqlstate)

    # -- fixtures inside the transaction ----------------------------------

    def demo_scope(self):
        return self.one(
            """
            select f.cooperative_id, f.id, pb.id from public.farms f
            join public.plots p on p.farm_id = f.id
            join public.crop_seasons cs on cs.plot_id = p.id
            join public.production_batches pb on pb.crop_season_id = cs.id
            where f.farm_code = %s and pb.deleted_at is null limit 1
            """,
            (FARM_CODE,),
        )

    def member(self, org, role: str):
        row = self.one(
            """select user_id from public.organization_memberships
               where organization_id = %s and role = %s and (ended_at is null or ended_at > now()) limit 1""",
            (org, role),
        )
        assert row, f"no active {role} in the demo organization"
        return row[0]

    def farm_member_farmer(self, farm):
        row = self.one(
            """select fm.user_id from public.farm_members fm
               join public.farms f on f.id = fm.farm_id
               join public.organization_memberships om on om.user_id = fm.user_id and om.organization_id = f.cooperative_id
               where fm.farm_id = %s and om.role = 'farmer' and (om.ended_at is null or om.ended_at > now()) limit 1""",
            (farm,),
        )
        assert row, "no farmer member on the demo farm"
        return row[0]

    def set_farm_role(self, farm, user, role: str) -> None:
        self.cur.execute("update public.farm_members set farm_role = %s where farm_id = %s and user_id = %s", (role, farm, user))
        assert self.cur.rowcount == 1

    def storage_object(self, bucket: str, org) -> uuid.UUID:
        return self.one(
            "insert into storage.objects (bucket_id, name) values (%s, %s) returning id",
            (bucket, f"{org}/{uuid.uuid4()}/p0-security-test.pdf"),
        )[0]

    def regulator_for(self, source_org) -> uuid.UUID:
        """A profile outside the demo organization, made `regulator` of a new
        government organization that holds a live data grant on it."""
        gov = self.one(
            """insert into public.organizations (organization_code, name, organization_type)
               values (%s, 'P0 test regulator', 'government') returning id""",
            (f"P0-TEST-GOV-{uuid.uuid4().hex[:8]}",),
        )[0]
        user = self.one(
            """select p.id from public.profiles p where not exists (
                 select 1 from public.organization_memberships om
                 where om.user_id = p.id and om.organization_id = %s) limit 1""",
            (source_org,),
        )
        assert user, "need a profile outside the demo organization"
        self.cur.execute(
            "insert into public.organization_memberships (organization_id, user_id, role) values (%s, %s, 'regulator')",
            (gov, user[0]),
        )
        self.cur.execute(
            """insert into public.organization_data_grants (grantee_organization_id, source_organization_id, access_level, valid_from)
               values (%s, %s, 'read', current_date - 1)""",
            (gov, source_org),
        )
        return user[0]

    def device_for(self, user) -> uuid.UUID:
        """A registered device, as Flutter has: mobile rows require one
        (`activities_mobile_device_chk`)."""
        return self.one(
            "insert into public.devices (user_id, installation_id, platform) values (%s, gen_random_uuid(), 'android') returning id",
            (user,),
        )[0]

    def activity_recorded_by(self, batch, user) -> uuid.UUID:
        activity = self.one(
            """insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, note)
               values (%s, 'irrigation', now(), now(), 'web', %s, 'P0-SECURITY-TEST') returning id""",
            (batch, user),
        )[0]
        self.cur.execute(
            "insert into public.irrigation_events (activity_id, method, water_volume_m3) values (%s, 'awd', 1)",
            (activity,),
        )
        return activity


@pytest.fixture
def tx():
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        try:
            yield Tx(conn)
        finally:
            conn.rollback()


def visible(tx: Tx, role: str, user, object_id) -> int:
    status, out = tx.run_as(role, user, "select count(*) from storage.objects where id = %s", (object_id,))
    assert status == "ok", out
    return out[0][0]


# -- M7: mrv-exports objects are not reachable by any client ----------------

def test_m7_no_client_role_can_read_an_mrv_export_object(tx):
    org, farm, _batch = tx.demo_scope()
    export_obj = tx.storage_object("mrv-exports", org)
    farmer = tx.farm_member_farmer(farm)
    manager = tx.member(org, "cooperative_manager")
    regulator = tx.regulator_for(org)

    assert visible(tx, "authenticated", farmer, export_obj) == 0
    assert visible(tx, "authenticated", regulator, export_obj) == 0
    assert visible(tx, "authenticated", manager, export_obj) == 0
    assert visible(tx, "anon", None, export_obj) == 0


def test_m7_enterprise_viewer_member_cannot_read_an_mrv_export_object(tx):
    row = tx.one(
        """select organization_id, user_id from public.organization_memberships
           where role = 'enterprise_viewer' and (ended_at is null or ended_at > now()) limit 1"""
    )
    if row is None:
        pytest.skip("no active enterprise_viewer membership on this database")
    export_obj = tx.storage_object("mrv-exports", row[0])
    assert visible(tx, "authenticated", row[1], export_obj) == 0


def test_m7_clients_cannot_upload_overwrite_or_delete_mrv_export_objects(tx):
    org, _farm, _batch = tx.demo_scope()
    manager = tx.member(org, "cooperative_manager")
    export_obj = tx.storage_object("mrv-exports", org)

    status, out = tx.run_as(
        "authenticated", manager,
        "insert into storage.objects (bucket_id, name) values ('mrv-exports', %s)",
        (f"{org}/{uuid.uuid4()}/planted.pdf",),
    )
    assert status == "err" and out == "42501"
    assert tx.run_as("authenticated", manager, "update storage.objects set metadata = '{}' where id = %s", (export_obj,)) == ("ok", 0)
    # A client DELETE is refused either by RLS (no visible row) or by Storage's
    # own `protect_objects_delete` trigger (42501); both leave the object intact.
    assert tx.run_as("authenticated", manager, "delete from storage.objects where id = %s", (export_obj,)) in (("ok", 0), ("err", "42501"))
    assert tx.one("select count(*) from storage.objects where id = %s", (export_obj,))[0] == 1


def test_m7_other_buckets_keep_their_existing_rules(tx):
    org, farm, _batch = tx.demo_scope()
    farmer = tx.farm_member_farmer(farm)
    manager = tx.member(org, "cooperative_manager")
    regulator = tx.regulator_for(org)
    evidence_obj = tx.storage_object("mrv-evidence", org)
    plant_obj = tx.one(
        "insert into storage.objects (bucket_id, name) values ('plant-images', %s) returning id",
        (f"{farm}/{uuid.uuid4()}/leaf.jpg",),
    )[0]

    # mrv-evidence: unchanged — any organization reader, including a grant reader.
    assert visible(tx, "authenticated", farmer, evidence_obj) == 1
    assert visible(tx, "authenticated", regulator, evidence_obj) == 1
    assert visible(tx, "authenticated", manager, evidence_obj) == 1
    assert visible(tx, "anon", None, evidence_obj) == 0
    # plant-images: unchanged — farm readers.
    assert visible(tx, "authenticated", farmer, plant_obj) == 1


def test_m7_buckets_stay_private(tx):
    tx.cur.execute("select id, public from storage.buckets where id in ('mrv-exports','mrv-evidence','plant-images')")
    assert all(public is False for _id, public in tx.cur.fetchall())


def test_m7_no_storage_policy_mentions_mrv_exports(tx):
    tx.cur.execute(
        """select policyname from pg_policies where schemaname = 'storage' and tablename = 'objects'
           and (coalesce(qual, '') || coalesce(with_check, '')) like '%%mrv-exports%%'"""
    )
    assert tx.cur.fetchall() == []


# -- B7: the Python active-membership rule matches the SQL helpers ----------

@pytest.mark.parametrize("offset", ["-1 second", "0 seconds", "1 second"])
def test_b7_python_active_rule_agrees_with_sql_helpers_at_the_boundary(tx, offset):
    org, _farm, _batch = tx.demo_scope()
    manager = tx.member(org, "cooperative_manager")
    tx.cur.execute(
        """update public.organization_memberships
           set joined_at = now() - interval '10 days', ended_at = now() + %s::interval
           where organization_id = %s and user_id = %s""",
        (offset, org, manager),
    )
    row = tx.one(
        "select ended_at, now() from public.organization_memberships where organization_id = %s and user_id = %s",
        (org, manager),
    )
    ended_at, db_now = row
    status, out = tx.run_as("authenticated", manager, "select private.user_is_org_manager(%s)", (org,))
    assert status == "ok"
    sql_active = out[0][0]
    assert sql_active is (offset == "1 second")
    assert is_active_membership({"ended_at": ended_at}, db_now) is sql_active


# -- B3: farm viewer is read-only on the direct Supabase path ---------------

def test_b3_viewer_can_read_but_not_write_directly(tx):
    _org, farm, batch = tx.demo_scope()
    farmer = tx.farm_member_farmer(farm)
    own = tx.activity_recorded_by(batch, farmer)
    device = tx.device_for(farmer)
    tx.set_farm_role(farm, farmer, "viewer")

    assert tx.run_as("authenticated", farmer, "select count(*) from public.activities where id = %s", (own,)) == ("ok", [(1,)])

    status, out = tx.run_as(
        "authenticated", farmer,
        """insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, device_id, client_event_id)
           values (%s, 'irrigation', now(), now(), 'mobile_offline', %s, %s, gen_random_uuid())""",
        (batch, farmer, device),
    )
    assert (status, out) == ("err", "42501")
    assert tx.run_as("authenticated", farmer, "update public.activities set note = 'x' where id = %s", (own,)) == ("ok", 0)
    assert tx.run_as("authenticated", farmer, "update public.irrigation_events set water_volume_m3 = 9 where activity_id = %s", (own,)) == ("ok", 0)
    assert tx.run_as("authenticated", farmer, "select public.soft_delete_activity(%s)", (own,)) == ("err", "42501")


def test_b3_editor_keeps_direct_write_access(tx):
    _org, farm, batch = tx.demo_scope()
    farmer = tx.farm_member_farmer(farm)
    device = tx.device_for(farmer)
    tx.set_farm_role(farm, farmer, "editor")

    status, out = tx.run_as(
        "authenticated", farmer,
        """insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, device_id, client_event_id, note)
           values (%s, 'irrigation', now(), now(), 'mobile_offline', %s, %s, gen_random_uuid(), 'P0-SECURITY-TEST') returning id""",
        (batch, farmer, device),
    )
    assert status == "ok", out
    new_id = out[0][0]
    assert tx.run_as("authenticated", farmer, "update public.activities set note = 'edited' where id = %s", (new_id,)) == ("ok", 1)
    assert tx.run_as("authenticated", farmer, "select public.soft_delete_activity(%s)", (new_id,)) == ("ok", [(True,)])


def _repository_on(tx: Tx) -> PostgresActivityWriteRepository:
    conn = tx.conn
    bound = type("Bound", (), {"cursor": lambda self: conn.cursor(row_factory=dict_row)})()
    return PostgresActivityWriteRepository(settings=None, connect=lambda: nullcontext(bound))


def _create(repo, batch, actor, key):
    return repo.create(
        crop_season_id="unused-by-sql", production_batch_id=str(batch), actor_id=str(actor),
        idempotency_key=key, activity_type="irrigation",
        occurred_at=datetime(2026, 9, 15, tzinfo=timezone.utc), note="P0-SECURITY-TEST",
        data={"method": "awd", "water_volume_m3": 1, "duration_minutes": None, "water_level_cm": None,
              "pump_energy_kwh": None, "total_cost_vnd": None},
    )


def test_b3_backend_repository_denies_a_viewer_and_allows_owner_editor(tx):
    _org, farm, batch = tx.demo_scope()
    farmer = tx.farm_member_farmer(farm)
    repo = _repository_on(tx)
    count = lambda: tx.one("select count(*) from public.activities where recorded_by = %s and note = 'P0-SECURITY-TEST'", (farmer,))[0]

    tx.set_farm_role(farm, farmer, "viewer")
    tx.cur.execute("savepoint viewer_write")
    with pytest.raises(ActivityWritePermissionError):
        _create(repo, batch, farmer, str(uuid.uuid4()))
    tx.cur.execute("rollback to savepoint viewer_write")
    assert count() == 0

    for role in ("editor", "owner"):
        tx.set_farm_role(farm, farmer, role)
        row, replay = _create(repo, batch, farmer, str(uuid.uuid4()))
        assert replay is False and row["created_by"] == str(farmer)
    assert count() == 2

    # The claim used for the check does not leak into the rest of the transaction.
    assert tx.one("select auth.uid()")[0] is None


def test_b3_backend_repository_denies_viewer_update_and_delete(tx):
    _org, farm, batch = tx.demo_scope()
    farmer = tx.farm_member_farmer(farm)
    own = tx.activity_recorded_by(batch, farmer)
    tx.set_farm_role(farm, farmer, "viewer")
    repo = _repository_on(tx)

    for call in (
        lambda: repo.update(activity_id=str(own), actor_id=str(farmer), occurred_at=None, note="changed", update_note=True, data=None),
        lambda: repo.soft_delete(activity_id=str(own), actor_id=str(farmer)),
    ):
        tx.cur.execute("savepoint viewer_write")
        with pytest.raises(ActivityWritePermissionError):
            call()
        tx.cur.execute("rollback to savepoint viewer_write")
    assert tx.one("select note, deleted_at from public.activities where id = %s", (own,)) == ("P0-SECURITY-TEST", None)
