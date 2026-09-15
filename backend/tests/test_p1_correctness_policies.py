"""B4 against the REAL database: the persist checker asks `private.user_can_write_crop`.

One rolled-back transaction per test; role changes, a regulator organization and
data grant, an ended membership are all created inside it. Skipped without
`SUPABASE_DB_URL`. The checker's database connection is bound to the test
transaction and the verified-user lookup is replaced by the chosen profile id,
so this exercises exactly the SQL the API runs.
"""
from __future__ import annotations

import sys
import uuid
from contextlib import nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.auth import CropAccessError  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402
from infrastructure.persist_access import PostgresCropPersistChecker  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the RLS tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url
pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")

FARM_CODE = "DEMO-FARM-01"


@pytest.fixture
def conn():
    with psycopg.connect(_DB_URL, autocommit=False) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def scope(conn):
    return one(conn, """
        select f.cooperative_id, f.id, cs.id from public.farms f
        join public.plots p on p.farm_id = f.id
        join public.crop_seasons cs on cs.plot_id = p.id
        where f.farm_code = %s and cs.deleted_at is null limit 1""", (FARM_CODE,))


def farmer_on(conn, farm):
    return one(conn, """
        select fm.user_id from public.farm_members fm join public.farms f on f.id = fm.farm_id
        join public.organization_memberships om on om.user_id = fm.user_id and om.organization_id = f.cooperative_id
        where fm.farm_id = %s and om.role = 'farmer' and (om.ended_at is null or om.ended_at > now()) limit 1""", (farm,))[0]


def manager_of(conn, org):
    return one(conn, """select user_id from public.organization_memberships where organization_id = %s
                        and role = 'cooperative_manager' and (ended_at is null or ended_at > now()) limit 1""", (org,))[0]


def checker(conn, user_id) -> PostgresCropPersistChecker:
    bound = type("Bound", (), {"cursor": lambda self: conn.cursor(row_factory=dict_row)})()
    return PostgresCropPersistChecker(settings=None, user_id_for=lambda token: str(user_id), connect=lambda: nullcontext(bound))


def allowed(conn, user_id, season) -> bool:
    try:
        checker(conn, user_id).assert_can_persist("jwt", str(season))
        return True
    except CropAccessError:
        return False


def set_farm_role(conn, farm, user, role):
    with conn.cursor() as cur:
        cur.execute("update public.farm_members set farm_role = %s where farm_id = %s and user_id = %s", (role, farm, user))
        assert cur.rowcount == 1


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_farm_writers_may_persist(conn, role):
    org, farm, season = scope(conn)
    farmer = farmer_on(conn, farm)
    set_farm_role(conn, farm, farmer, role)
    assert allowed(conn, farmer, season) is True


def test_farm_viewer_may_not_persist(conn):
    org, farm, season = scope(conn)
    farmer = farmer_on(conn, farm)
    set_farm_role(conn, farm, farmer, "viewer")
    assert allowed(conn, farmer, season) is False


def test_active_cooperative_manager_may_persist_and_ended_one_may_not(conn):
    org, farm, season = scope(conn)
    manager = manager_of(conn, org)
    # Isolate the manager path: a demo manager may also be a farm member, which
    # would keep write authority through `farm_members` regardless of the
    # organization membership under test.
    with conn.cursor() as cur:
        cur.execute("delete from public.farm_members where farm_id = %s and user_id = %s", (farm, manager))
    assert allowed(conn, manager, season) is True
    with conn.cursor() as cur:
        cur.execute("""update public.organization_memberships set joined_at = now() - interval '10 days',
                       ended_at = now() - interval '1 second' where organization_id = %s and user_id = %s""", (org, manager))
    assert allowed(conn, manager, season) is False


def test_grant_reader_may_not_persist(conn):
    org, farm, season = scope(conn)
    with conn.cursor() as cur:
        cur.execute("""insert into public.organizations (organization_code, name, organization_type)
                       values (%s, 'P1 test regulator', 'government') returning id""", (f"P1-TEST-GOV-{uuid.uuid4().hex[:8]}",))
        gov = cur.fetchone()[0]
        cur.execute("""select p.id from public.profiles p where not exists (select 1 from public.organization_memberships om
                       where om.user_id = p.id and om.organization_id = %s) limit 1""", (org,))
        outsider = cur.fetchone()[0]
        cur.execute("insert into public.organization_memberships (organization_id, user_id, role) values (%s, %s, 'regulator')", (gov, outsider))
        cur.execute("""insert into public.organization_data_grants (grantee_organization_id, source_organization_id, access_level, valid_from)
                       values (%s, %s, 'read', current_date - 1)""", (gov, org))
        cur.execute("select private.user_can_read_organization(%s)", (org,))
    # Reads through the grant but cannot persist.
    with conn.cursor() as cur:
        cur.execute("select set_config('request.jwt.claims', %s, true)", ('{"sub":"%s","role":"authenticated"}' % outsider,))
        cur.execute("select private.user_can_read_crop(%s)", (season,))
        assert cur.fetchone()[0] is True
        cur.execute("select set_config('request.jwt.claims', '', true)")
    assert allowed(conn, outsider, season) is False


def _export_with_calculation(conn, *, in_scope: bool, same_factor_set: bool = True):
    """Inside the rolled-back transaction: a draft factor set, a crop-season-scoped
    succeeded calculation (production_batch_id NULL, as the backend writes it),
    an MRV export, then the link row the trigger validates."""
    with conn.cursor() as cur:
        cur.execute("select id, organization_id from public.mrv_cases limit 1")
        case = cur.fetchone()
        assert case, "need an MRV case"
        cur.execute("""select pb.crop_season_id from public.mrv_case_batches mcb
                       join public.production_batches pb on pb.id = mcb.production_batch_id
                       where mcb.mrv_case_id = %s limit 1""", (case[0],))
        linked = cur.fetchone()
        assert linked, "the MRV case must link at least one batch"
        season = linked[0]
        if not in_scope:
            cur.execute("""select cs.id from public.crop_seasons cs where not exists (
                             select 1 from public.production_batches pb join public.mrv_case_batches mcb
                             on mcb.production_batch_id = pb.id where pb.crop_season_id = cs.id and mcb.mrv_case_id = %s)
                           limit 1""", (case[0],))
            season = cur.fetchone()[0]
        factor_sets = []
        for n in (1, 2):
            cur.execute("""insert into public.emission_factor_sets (version_code, name, methodology_name, source_name, status)
                           values (%s, 'P1 trigger test', 'TEST ONLY', 'p1-test', 'draft') returning id""", (f"P1-TRIGGER-{uuid.uuid4().hex[:8]}-{n}",))
            factor_sets.append(cur.fetchone()[0])
        cur.execute("""insert into public.carbon_calculations (crop_season_id, scenario, factor_set_id, engine_version, input_hash,
                         total_co2e_kg, status) values (%s, 'actual', %s, 'p1-test', %s, 1, 'succeeded') returning id, production_batch_id""",
                    (season, factor_sets[0], uuid.uuid4().hex + uuid.uuid4().hex))
        calc_id, batch = cur.fetchone()
        assert batch is None
        export_id = uuid.uuid4()
        cur.execute("""insert into public.mrv_exports (id, mrv_case_id, format, factor_set_id, scope_description, data_as_of_at,
                         contains_sample_data, is_finalized, warning_text, storage_object_path, export_payload, generated_at)
                       values (%s, %s, 'json', %s, 'p1 trigger test', now(), false, false, 'TEST', %s, '{}'::jsonb, now())""",
                    (export_id, case[0], factor_sets[0] if same_factor_set else factor_sets[1],
                     f"{case[1]}/{case[0]}/p1-trigger-test-{export_id}.json"))
        cur.execute("savepoint link")
        try:
            cur.execute("insert into public.mrv_export_calculations (mrv_export_id, carbon_calculation_id) values (%s, %s)", (export_id, calc_id))
            return None
        except psycopg.Error as exc:
            cur.execute("rollback to savepoint link")
            return str(exc)


def test_mrv_export_can_link_a_crop_season_scoped_calculation_in_case_scope(conn):
    assert _export_with_calculation(conn, in_scope=True) is None


def test_mrv_export_still_rejects_a_calculation_outside_case_scope(conn):
    error = _export_with_calculation(conn, in_scope=False)
    assert error and "inside the MRV case scope" in error


def test_mrv_export_still_rejects_a_different_factor_set(conn):
    error = _export_with_calculation(conn, in_scope=True, same_factor_set=False)
    assert error and "factor-set version" in error


def test_unrelated_user_may_not_persist(conn):
    org, farm, season = scope(conn)
    stranger = one(conn, """select p.id from public.profiles p where not exists (
        select 1 from public.farm_members fm where fm.user_id = p.id and fm.farm_id = %s) and not exists (
        select 1 from public.organization_memberships om where om.user_id = p.id and om.organization_id = %s) limit 1""", (farm, org))
    if stranger is None:
        pytest.skip("no profile outside the demo farm and cooperative")
    assert allowed(conn, stranger[0], season) is False
