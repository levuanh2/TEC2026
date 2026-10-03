"""Round 5.1: the pooled-Postgres Carbon repository against the REAL database.

* Equivalence: for every live crop season, the bundle (rows AND order), every
  scenario's engine output or refusal, readiness (with `input_hash`) and the
  stored views are identical to what the PostgREST repository returns. Order
  matters because fertilizer/straw/fuel lists are hashed in read order.
* Atomicity: calculation + breakdown are one transaction; a failing breakdown
  leaves no calculation behind; the same calculation sent twice is one row.
* Actual vs scenario and fingerprint staleness hold on real rows.

Every write happens inside a savepoint of an outer transaction that is always
rolled back, so nothing survives a run. Skipped without `SUPABASE_DB_URL`; the
equivalence test also needs the service-role key for the PostgREST side.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import ParameterSet, compute_input_hash  # noqa: E402
from carbon.errors import CarbonEngineError  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402
from infrastructure.mapping import breakdown_rows, calculation_row, map_crop_activity_data  # noqa: E402
from infrastructure.pg_carbon_repo import PostgresCarbonRepository  # noqa: E402
from infrastructure.supabase_repo import DETAIL_TABLES, SupabaseCarbonRepository  # noqa: E402
from service import CarbonService  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the real-database tests.")
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

_SETTINGS = load_settings()
_DB_URL = _SETTINGS.supabase_db_url
_PARAMS = ParameterSet.load(_SETTINGS.ef_config_path)
SCENARIOS = ("as_recorded", "awd", "continuous_flooding")

pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


@pytest.fixture
def db():
    with psycopg.connect(_DB_URL, autocommit=False, row_factory=dict_row) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


def _savepoints(conn):
    """A repository `connect` whose transaction is a real savepoint."""
    class _Savepoint:
        def __enter__(self):
            self._tx = conn.transaction()
            self._tx.__enter__()
            return type("Bound", (), {"cursor": lambda _self: conn.cursor(row_factory=dict_row)})()

        def __exit__(self, *exc):
            return self._tx.__exit__(*exc)

    return _Savepoint


def _live_seasons(conn) -> list[str]:
    return [r["id"] for r in conn.execute(
        "select id::text as id from public.crop_seasons where deleted_at is null order by id"
    ).fetchall()]


def _outcome(service: CarbonService, season: str, scenario: str):
    try:
        result = service.calculate(season, scenario, persist=False).result.to_dict()
        result.pop("calculated_at")
        return ("ok", result)
    except CarbonEngineError as exc:
        return (type(exc).__name__, str(exc))


def _has_fertilizer(conn, season: str) -> bool:
    return conn.execute(
        "select 1 from public.fertilizer_applications d join public.activities a on a.id = d.activity_id"
        " join public.production_batches b on b.id = a.production_batch_id"
        " where b.crop_season_id = %s and a.deleted_at is null limit 1",
        (season,),
    ).fetchone() is not None


def _first_calculable(conn, service: CarbonService, with_fertilizer: bool) -> str | None:
    for season in _live_seasons(conn):
        if with_fertilizer and not _has_fertilizer(conn, season):
            continue
        if _outcome(service, season, "as_recorded")[0] == "ok":
            return season
    return None


def _calculable(conn, service: CarbonService, with_fertilizer: bool = False) -> str:
    season = _first_calculable(conn, service, with_fertilizer)
    if season is not None:
        return season
    # The CI seed (scripts/ci/seed_ci_db.py) has an active demo season with
    # seeding, fertilizer and harvest records but no declared water regimes and
    # no cultivation days (it is still active: no actual harvest date), so
    # `as_recorded` refuses it. Declare them inside this test's transaction
    # (always rolled back) rather than skip: CI allows no skip here.
    conn.execute(
        "update public.crop_seasons"
        " set ipcc_water_regime = coalesce(ipcc_water_regime, 'irrigated_continuous_flooding'),"
        "     pre_season_water_regime = coalesce(pre_season_water_regime, 'non_flooded_pre_season_lt_180d'),"
        "     cultivation_days = coalesce(cultivation_days, 100)"
        " where deleted_at is null and status = 'active'"
    )
    season = _first_calculable(conn, service, with_fertilizer)
    assert season is not None, "no live crop season in this database can be calculated as recorded"
    return season


# -- equivalence ---------------------------------------------------------------

# Without a database the module mark skips it under the allowlisted reason; a
# function mark is evaluated first, so it must not fire then.
@pytest.mark.skipif(bool(_DB_URL) and not _SETTINGS.supabase_configured,
                    reason="PostgREST side needs the service-role key.")
def test_every_season_reads_and_calculates_identically_to_the_postgrest_repository(db):
    postgrest = SupabaseCarbonRepository(_SETTINGS)
    pooled = PostgresCarbonRepository(_SETTINGS)
    before, after = CarbonService(postgrest, _PARAMS), CarbonService(pooled, _PARAMS)
    seasons = _live_seasons(db)
    assert seasons
    for season in seasons:
        assert asdict(pooled.get_crop_bundle(season)) == asdict(postgrest.get_crop_bundle(season)), season
        for scenario in SCENARIOS:
            assert _outcome(after, season, scenario) == _outcome(before, season, scenario), (season, scenario)
            assert pooled.latest_calculation(season, scenario) == postgrest.latest_calculation(season, scenario)
        assert after.readiness(season) == before.readiness(season), season
        assert after.stored(season) == before.stored(season), season
    version = _PARAMS.version
    assert pooled.resolve_factor_set_id(version) == postgrest.resolve_factor_set_id(version)
    set_id = pooled.resolve_factor_set_id(version)
    assert pooled.factor_ids_by_code(set_id) == postgrest.factor_ids_by_code(set_id)
    assert pooled.factor_set_version(set_id) == postgrest.factor_set_version(set_id) == version


def test_unknown_or_malformed_season_is_not_found(db):
    repo = PostgresCarbonRepository(None, connect=_savepoints(db))
    for season in (str(uuid.uuid4()), "not-a-uuid"):
        with pytest.raises(CarbonEngineError):
            repo.get_crop_bundle(season)
        assert repo.latest_calculation(season) is None


# -- atomic write --------------------------------------------------------------

def _fresh_rows(repo: PostgresCarbonRepository, season: str, scenario: str = "as_recorded", salt: str = ""):
    """A real engine result for `season`, under an input hash no stored row has."""
    service = CarbonService(repo, _PARAMS)
    bundle = repo.get_crop_bundle(season)
    data = map_crop_activity_data(bundle)
    result = service.calculate(season, scenario, persist=False).result
    result.input_hash = hashlib.sha256(f"round51-test|{uuid.uuid4()}|{salt}".encode()).hexdigest()
    set_id = repo.resolve_factor_set_id(result.ef_config_version)
    calc = calculation_row(
        result, crop_season_id=season, factor_set_id=set_id, area_ha=data.area_ha,
        cultivation_days=data.recorded_cultivation_days, pre_season_water_regime=data.pre_season_water_regime,
    )
    return calc, breakdown_rows(result, repo.factor_ids_by_code(set_id))


def test_a_calculation_is_written_with_every_breakdown_and_its_provenance(db):
    repo = PostgresCarbonRepository(None, connect=_savepoints(db))
    season = _calculable(db, CarbonService(repo, _PARAMS))
    calc, breakdowns = _fresh_rows(repo, season)
    assert breakdowns
    calc_id = repo.save_calculation(calc, breakdowns)

    row = db.execute("select * from public.carbon_calculations where id = %s", (calc_id,)).fetchone()
    assert row["input_hash"] == calc["input_hash"] and row["status"] == "succeeded"
    assert float(row["total_co2e_kg"]) == pytest.approx(calc["total_co2e_kg"], abs=5e-7)  # numeric(…, 6)
    assert row["warnings"] == calc["warnings"]
    stored = db.execute(
        "select * from public.carbon_breakdowns where calculation_id = %s", (calc_id,)
    ).fetchall()
    assert len(stored) == len(breakdowns)
    assert sum(float(b["co2e_kg"]) for b in stored) == pytest.approx(calc["total_co2e_kg"], abs=0.01)
    assert all(b["formula_metadata"]["provenance"] for b in stored)
    key = lambda r: json.dumps([r["category"], r["gas"], r["formula_metadata"]["provenance"]], sort_keys=True)
    assert sorted(map(key, stored)) == sorted(map(key, breakdowns))


def test_a_failing_breakdown_rolls_the_calculation_back(db):
    repo = PostgresCarbonRepository(None, connect=_savepoints(db))
    season = _calculable(db, CarbonService(repo, _PARAMS))
    calc, breakdowns = _fresh_rows(repo, season)
    # A factor that is not in the calculation's factor set: the DB trigger refuses it.
    broken = [{**breakdowns[0], "emission_factor_id": str(uuid.uuid4())}, *breakdowns[1:]]
    with pytest.raises(psycopg.Error):
        repo.save_calculation(calc, broken)
    left = db.execute(
        "select count(*) as n from public.carbon_calculations where input_hash = %s", (calc["input_hash"],)
    ).fetchone()["n"]
    assert left == 0


def test_the_same_calculation_sent_twice_is_one_row(db):
    repo = PostgresCarbonRepository(None, connect=_savepoints(db))
    season = _calculable(db, CarbonService(repo, _PARAMS))
    calc, breakdowns = _fresh_rows(repo, season)
    first = repo.save_calculation(calc, breakdowns)
    second = repo.save_calculation(calc, breakdowns)
    assert first == second
    counts = db.execute(
        "select count(*) as n, (select count(*) from public.carbon_breakdowns where calculation_id = %s) as b"
        " from public.carbon_calculations where input_hash = %s", (first, calc["input_hash"]),
    ).fetchone()
    assert counts["n"] == 1 and counts["b"] == len(breakdowns)


# -- actual vs scenario, fingerprint staleness on real rows ---------------------

def test_a_scenario_saved_later_never_replaces_the_actual_result(db):
    repo = PostgresCarbonRepository(None, connect=_savepoints(db))
    service = CarbonService(repo, _PARAMS)
    season = _calculable(db, service)
    actual = service.calculate(season, "as_recorded")
    for scenario in ("awd", "continuous_flooding"):
        calc, breakdowns = _fresh_rows(repo, season, scenario, salt=scenario)
        repo.save_calculation({**calc, "calculated_at": "2999-01-01T00:00:00+00:00"}, breakdowns)
    stored = service.stored(season, "as_recorded")
    assert stored["calculation_id"] == actual.calculation_id
    assert stored["scenario"] == "as_recorded"
    assert service.stored(season, "awd")["scenario"] == "awd"


def _clone_as_active(db, season: str) -> str:
    """Copy a calculable (closed) season into a fresh ACTIVE one, rows in read order.

    Hosted's calculable seasons are all harvested, and the lifecycle triggers
    forbid editing their records. The copy lives only in the rolled-back
    transaction.
    """
    def rows(sql, params):
        return [r["r"] for r in db.execute(sql, params).fetchall()]

    def insert(table, data):
        cols = ", ".join(data)
        db.execute(f"insert into public.{table} ({cols}) select {cols}"
                   f" from jsonb_populate_record(null::public.{table}, %s)", [Jsonb(data)])

    source = rows("select to_jsonb(t) as r from public.crop_seasons t where t.id = %s", [season])[0]
    clone = str(uuid.uuid4())
    insert("crop_seasons", {**source, "id": clone, "status": "active", "actual_harvest_date": None,
                            "season_code": f"{source['season_code']}-R51T"})
    for batch in rows("select to_jsonb(t) as r from public.production_batches t"
                      " where t.crop_season_id = %s and t.deleted_at is null", [season]):
        new_batch = str(uuid.uuid4())
        insert("production_batches", {k: v for k, v in {**batch, "id": new_batch, "crop_season_id": clone}.items()
                                      if k not in ("status", "closed_on")})
        for activity in rows("select to_jsonb(t) as r from public.activities t where t.production_batch_id = %s",
                             [batch["id"]]):
            if activity.get("deleted_at") is not None:
                continue
            new_activity = str(uuid.uuid4())
            insert("activities", {**activity, "id": new_activity, "production_batch_id": new_batch,
                                  "client_event_id": str(uuid.uuid4()) if activity.get("client_event_id") else None,
                                  "web_idempotency_key": None, "source_record_key": None, "ingestion_batch_id": None})
            table = DETAIL_TABLES.get(activity["activity_type"])
            for detail in rows(f"select to_jsonb(t) as r from public.{table} t where t.activity_id = %s",
                               [activity["id"]]) if table else []:
                insert(table, {**detail, "activity_id": new_activity})
    return clone


def test_fingerprint_ignores_cost_follows_carbon_inputs_and_recalculation_clears_it(db):
    repo = PostgresCarbonRepository(None, connect=_savepoints(db))
    service = CarbonService(repo, _PARAMS)
    season = _clone_as_active(db, _calculable(db, service, with_fertilizer=True))
    fertilizer = db.execute(
        "select d.activity_id from public.fertilizer_applications d join public.activities a on a.id = d.activity_id"
        " join public.production_batches b on b.id = a.production_batch_id where b.crop_season_id = %s limit 1",
        (season,),
    ).fetchone()
    assert fertilizer is not None, "the clone lost the source season's fertilizer record"
    fertilizer = fertilizer["activity_id"]
    service.calculate(season, "as_recorded")
    current = service.readiness(season)["input_hash"]
    assert service.stored(season)["input_hash"] == current  # fresh

    db.execute("update public.fertilizer_applications set total_cost_vnd = coalesce(total_cost_vnd, 0) + 1000"
               " where activity_id = %s", (fertilizer,))
    db.execute("update public.activities set note = 'round51 note edit' where id = %s", (fertilizer,))
    assert service.readiness(season)["input_hash"] == current  # cost/note only: not stale

    service.calculate(season, "awd")
    assert service.readiness(season)["input_hash"] == current  # a scenario: not stale

    db.execute("update public.fertilizer_applications set amount_kg = amount_kg + 5 where activity_id = %s",
               (fertilizer,))
    changed = service.readiness(season)["input_hash"]
    assert changed != current and service.stored(season)["input_hash"] == current  # carbon input: stale

    service.calculate(season, "as_recorded")
    assert service.stored(season)["input_hash"] == changed == compute_input_hash(
        map_crop_activity_data(repo.get_crop_bundle(season)), "as_recorded", _PARAMS)  # recalculated: fresh


# -- batch status (Management) ----------------------------------------------------

def test_batch_status_equals_per_season_answers_on_real_rows(db):
    service = CarbonService(PostgresCarbonRepository(None, connect=_savepoints(db)), _PARAMS)
    seasons = _live_seasons(db)
    batch = service.status_many(seasons + [str(uuid.uuid4())])
    for season in seasons:
        assert batch[season]["readiness"] == service.readiness(season), season
        assert batch[season]["actual"] == service.stored(season, "as_recorded"), season
    unknown = [s for s in batch if s not in seasons][0]
    assert isinstance(batch[unknown]["readiness"], CarbonEngineError) and batch[unknown]["actual"] is None


def test_batch_round_trips_do_not_grow_with_the_number_of_seasons(db):
    from infrastructure import profiling

    service = CarbonService(PostgresCarbonRepository(None, connect=_savepoints(db)), _PARAMS)
    seasons = _live_seasons(db)
    service.status_many(seasons)  # the factor-set version is looked up once per process
    counts = []
    for subset in (seasons[:1], seasons):
        profile = profiling.start()
        service.status_many(subset)
        counts.append(profile.calls)
    assert counts[0] == counts[1] <= 3, counts  # season bundle, activities, latest results


# -- one checkout per calculation request (pg_pool.bound) -------------------------

def test_bound_serves_every_connection_from_one_checkout_and_keeps_rollback():
    from infrastructure import pg_pool

    with pg_pool.bound(_DB_URL):
        with pg_pool.connection(_DB_URL) as first, pg_pool.connection(_DB_URL) as second:
            assert first is second
        with pytest.raises(RuntimeError), pg_pool.connection(_DB_URL) as conn:
            conn.execute("create temporary table round51_bound_probe (x int) on commit drop")
            raise RuntimeError("roll back")
        with pg_pool.connection(_DB_URL) as conn:
            assert conn.execute("select to_regclass('pg_temp.round51_bound_probe') as t").fetchone()["t"] is None
        with pg_pool.bound(_DB_URL), pg_pool.connection(_DB_URL) as nested:
            assert nested is first


def _rls_can_read(conn, user_id: str, season: str) -> bool:
    """Ground truth for "may read": the real `crop_seasons_select` policy, as the
    PostgREST read check evaluated it (role `authenticated`, the caller's claims)."""
    with conn.transaction(force_rollback=True):
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claims', %s, true)",
                     [json.dumps({"sub": user_id, "role": "authenticated"})])
        return conn.execute("select count(*) as n from public.crop_seasons where id = %s::uuid", [season]).fetchone()["n"] == 1


def _can_write(conn, user_id: str, season: str) -> bool:
    """Ground truth for "may write": exactly `assert_can_persist`'s rule."""
    with conn.transaction(force_rollback=True):
        conn.execute("select set_config('request.jwt.claims', %s, true)",
                     [json.dumps({"sub": user_id, "role": "authenticated"})])
        return bool(conn.execute("select private.user_can_write_crop(%s::uuid) as w", [season]).fetchone()["w"])


def test_authorized_read_is_the_rls_read_and_write_rules_and_leaks_nothing(db, monkeypatch):
    """Round 5.1: `get_crop_bundle_as` = old PostgREST read check + write check + read.

    For every live season and every user with a membership (plus an unknown
    id): allowed exactly when the real RLS read policy AND the write rule allow,
    and then the bundle is identical to the unguarded read; refused otherwise,
    with every bundle statement having returned NO row.
    """
    from infrastructure.auth import CropAccessError

    repo = PostgresCarbonRepository(_SETTINGS, connect=_savepoints(db))
    users = [r["id"] for r in db.execute(
        "select distinct user_id::text as id from public.farm_members"
        " union select distinct user_id::text from public.organization_memberships"
    ).fetchall()] + [str(uuid.uuid4())]
    captured: list = []
    real_stage = PostgresCarbonRepository._stage

    def spy(conn, label, statements, *, last=False):
        results = real_stage(conn, label, statements, last=last)
        captured.append(results)
        return results

    monkeypatch.setattr(PostgresCarbonRepository, "_stage", staticmethod(spy))
    allowed = refused = 0
    for season in _live_seasons(db):
        plain = asdict(repo.get_crop_bundle(season))
        for user in users:
            expected = _rls_can_read(db, user, season) and _can_write(db, user, season)
            captured.clear()
            if expected:
                assert asdict(repo.get_crop_bundle_as(season, user)) == plain
                allowed += 1
            else:
                with pytest.raises(CropAccessError):
                    repo.get_crop_bundle_as(season, user)
                bundle_rows = captured[-1][2:-1]
                assert all(rows == [] for rows in bundle_rows), "a refused caller received bundle rows"
                refused += 1
    assert allowed and refused  # both paths really ran on this data
