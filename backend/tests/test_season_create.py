"""Web crop-season creation: POST /v1/plots/{plot_id}/crop-seasons.

Two layers:

* HTTP contract with fakes -- auth, error mapping, replay status. No database.
* The repository against the REAL database (skipped without SUPABASE_DB_URL).
  One transaction per test, always rolled back; every row a test needs --
  auth users, two cooperatives, a farm with owner/editor/viewer members, a plot
  -- is created inside it, so the target database is left unchanged. The
  repository runs inside a savepoint of that transaction, exactly as it would
  run inside its own pooled transaction.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from infrastructure.season_repo import (  # noqa: E402
    DEFAULT_BATCH_CODE,
    ActiveSeasonExistsError,
    PostgresSeasonRepository,
    SeasonCodeTakenError,
    SeasonScopeError,
)
from infrastructure.write_repo import PostgresActivityWriteRepository  # noqa: E402
from service import SeasonService  # noqa: E402

PLOT = str(uuid.uuid4())


# ---------------------------------------------------------------- HTTP layer

class FakeRead:
    def __init__(self, *, signed_in: bool = True):
        self.signed_in = signed_in

    def user_id(self):
        if not self.signed_in:
            raise ReadNotFoundError("user")
        return "actor"


class FakeRepo:
    def __init__(self, *, error: Exception | None = None, replay: bool = False):
        self.error, self.replay, self.calls = error, replay, []

    def create(self, *, prepare=None, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        row = {
            "id": "season-1", "plot_id": kwargs["plot_id"], "season_code": kwargs["season_code"],
            "crop_type": "rice", "variety_name": kwargs["variety_name"],
            "planting_date": None if kwargs["planting_date"] is None else str(kwargs["planting_date"]),
            "expected_harvest_date": None, "actual_harvest_date": None, "status": "active",
            "ipcc_water_regime": None, "pre_season_water_regime": None, "cultivation_days": None,
            "default_production_batch_id": "batch-1",
        }
        return prepare((row, self.replay))


def client(repo=None, read=None, *, with_read=True):
    app = FastAPI()
    app.include_router(api.router)
    if with_read:
        app.dependency_overrides[api._read_repo] = lambda: read or FakeRead()
    app.dependency_overrides[api._season_service] = lambda: SeasonService(repo or FakeRepo())
    return TestClient(app)


BODY = {"season_code": "HT-2026", "variety_name": "OM5451", "planting_date": "2026-05-18"}


def test_unauthenticated_request_is_401_before_any_write():
    repo = FakeRepo()
    response = client(repo, with_read=False).post(f"/v1/plots/{PLOT}/crop-seasons", json=BODY)
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"
    assert repo.calls == []


def test_created_season_comes_back_with_its_default_batch():
    response = client().post(f"/v1/plots/{PLOT}/crop-seasons", json=BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["default_production_batch_id"] == "batch-1"
    assert body["idempotent_replay"] is False


def test_a_repeated_identical_request_is_200_replay_not_a_second_season():
    response = client(FakeRepo(replay=True)).post(f"/v1/plots/{PLOT}/crop-seasons", json=BODY)
    assert response.status_code == 200
    assert response.json()["idempotent_replay"] is True


@pytest.mark.parametrize(("error", "status", "code"), [
    (SeasonScopeError(), 404, "not_found"),
    (ActiveSeasonExistsError(), 409, "active_season_exists"),
    (SeasonCodeTakenError(), 409, "season_code_exists"),
])
def test_repository_refusals_map_to_the_api_error_contract(error, status, code):
    response = client(FakeRepo(error=error)).post(f"/v1/plots/{PLOT}/crop-seasons", json=BODY)
    assert response.status_code == status
    assert response.json()["detail"]["error"]["code"] == code


def test_a_malformed_plot_id_is_the_same_404_as_an_unknown_plot():
    repo = FakeRepo()
    response = client(repo).post("/v1/plots/not-a-uuid/crop-seasons", json=BODY)
    assert response.status_code == 404
    assert repo.calls == []


@pytest.mark.parametrize("body", [
    {},                                              # season_code is required
    {"season_code": "   "},                          # blank after trimming
    {"season_code": "HT", "status": "closed"},       # status is not the client's to choose
    {"season_code": "HT", "production_batch_id": "x"},
    {"season_code": "HT", "planting_date": "2026-05-18", "expected_harvest_date": "2026-05-01"},
])
def test_invalid_bodies_are_422_and_never_reach_the_repository(body):
    repo = FakeRepo()
    response = client(repo).post(f"/v1/plots/{PLOT}/crop-seasons", json=body)
    assert response.status_code == 422
    assert repo.calls == []


# ------------------------------------------------------------ real database

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the real-database tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url
real_db = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


def _savepoint_factory(conn):
    class _Savepoint:
        def __enter__(self):
            self._tx = conn.transaction()
            self._tx.__enter__()
            return type("Bound", (), {"cursor": lambda _self: conn.cursor(row_factory=dict_row)})()

        def __exit__(self, *exc):
            return self._tx.__exit__(*exc)

    return _Savepoint


class World:
    """Everything one test needs, created inside the rolled-back transaction."""

    def __init__(self, conn):
        self.conn = conn
        tag = uuid.uuid4().hex[:8]
        self.coop = self._org(f"SEASON-TEST-{tag}")
        self.other_coop = self._org(f"SEASON-TEST-OTHER-{tag}")
        self.owner = self._user("farmer", self.coop)
        self.editor = self._user("farmer", self.coop)
        self.viewer = self._user("farmer", self.coop)
        self.manager = self._user("cooperative_manager", self.coop)
        self.other_manager = self._user("cooperative_manager", self.other_coop)
        self.enterprise = self._user("enterprise_viewer", self.coop)
        self.regulator = self._user("regulator", self.coop)
        self.ended_manager = self._user("cooperative_manager", self.coop, ended=True)
        self.farm = self._one(
            "insert into public.farms (cooperative_id, farm_code, farm_name) values (%s, %s, 'Season test farm') returning id::text as id",
            (self.coop, f"SEASON-TEST-FARM-{tag}"),
        )["id"]
        for user, role in ((self.owner, "owner"), (self.editor, "editor"), (self.viewer, "viewer")):
            conn.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, %s)", (self.farm, user, role))
        self.plot = self._one(
            "insert into public.plots (farm_id, plot_code, name, area_ha) values (%s, %s, 'Season test plot', 1.25) returning id::text as id",
            (self.farm, f"SEASON-TEST-PLOT-{tag}"),
        )["id"]

    def _one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def _org(self, code):
        return self._one(
            "insert into public.organizations (organization_code, name, organization_type) values (%s, %s, 'cooperative') returning id::text as id",
            (code, code),
        )["id"]

    def _user(self, role, org, *, ended=False):
        user = str(uuid.uuid4())
        self.conn.execute(
            "insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
            (user, f"season-test-{user[:8]}@agricarbon-test.invalid"),
        )
        self.conn.execute(
            "insert into public.organization_memberships (organization_id, user_id, role, joined_at, ended_at) "
            "values (%s, %s, %s, now() - interval '2 days', case when %s then now() - interval '1 day' end)",
            (org, user, role, ended),
        )
        return user

    def seasons(self):
        return self.conn.execute(
            "select id::text as id, status::text as status from public.crop_seasons where plot_id = %s and deleted_at is null",
            (self.plot,),
        ).fetchall()

    def batches(self, season_id):
        return self.conn.execute(
            "select id::text as id, batch_code, status::text as status from public.production_batches "
            "where crop_season_id = %s and deleted_at is null",
            (season_id,),
        ).fetchall()


@pytest.fixture
def world():
    if not _DB_URL:
        pytest.skip("SUPABASE_DB_URL is not configured.")
    with psycopg.connect(_DB_URL, autocommit=False, row_factory=dict_row) as conn:
        try:
            yield World(conn)
        finally:
            conn.rollback()


def repo_for(world, cls=PostgresSeasonRepository):
    return cls(settings=None, connect=_savepoint_factory(world.conn))


def create(world, actor, *, code="HT-2026", repo=None, **extra):
    fields = {"variety_name": "OM5451", "planting_date": date(2026, 5, 18), "expected_harvest_date": None, **extra}
    return (repo or repo_for(world)).create(plot_id=world.plot, actor_id=actor, season_code=code, **fields)


@real_db
@pytest.mark.parametrize("who", ["owner", "editor", "manager"])
def test_writers_start_an_active_season_with_exactly_one_default_batch(world, who):
    season, replay = create(world, getattr(world, who))
    assert replay is False
    assert season["status"] == "active"
    batches = world.batches(season["id"])
    assert [(b["batch_code"], b["id"]) for b in batches] == [(DEFAULT_BATCH_CODE, season["default_production_batch_id"])]
    assert batches[0]["status"] not in {"closed", "cancelled"}


@real_db
@pytest.mark.parametrize("who", ["viewer", "other_manager", "enterprise", "regulator", "ended_manager"])
def test_non_writers_are_refused_and_nothing_is_written(world, who):
    with pytest.raises(SeasonScopeError):
        create(world, getattr(world, who))
    assert world.seasons() == []


@real_db
def test_an_unknown_or_deleted_plot_is_the_same_scope_error(world):
    repo = repo_for(world)
    with pytest.raises(SeasonScopeError):
        repo.create(plot_id=str(uuid.uuid4()), actor_id=world.owner, season_code="HT",
                    variety_name=None, planting_date=None, expected_harvest_date=None)
    world.conn.execute("update public.plots set deleted_at = now() where id = %s", (world.plot,))
    with pytest.raises(SeasonScopeError):
        create(world, world.owner)


@real_db
def test_a_failed_batch_insert_rolls_the_season_back(world):
    class BrokenBatch(PostgresSeasonRepository):
        _INSERT_BATCH_SQL = "insert into public.production_batches (crop_season_id, batch_code, no_such_column) values (%s, %s, 1) returning id"

    with pytest.raises(psycopg.errors.UndefinedColumn):
        create(world, world.owner, repo=repo_for(world, BrokenBatch))
    assert world.seasons() == []


@real_db
def test_a_rejected_response_rolls_both_rows_back(world):
    proof = {}

    def reject(out):
        proof["season"] = out[0]["id"]
        raise RuntimeError("response rejected")

    with pytest.raises(RuntimeError):
        repo_for(world).create(plot_id=world.plot, actor_id=world.owner, season_code="HT", variety_name=None,
                               planting_date=None, expected_harvest_date=None, prepare=reject)
    assert proof["season"]
    assert world.seasons() == []
    assert world.batches(proof["season"]) == []


@real_db
def test_a_double_submit_returns_the_same_season_and_writes_nothing_more(world):
    first, _ = create(world, world.owner)
    again, replay = create(world, world.owner)
    assert replay is True
    assert again["id"] == first["id"]
    assert again["default_production_batch_id"] == first["default_production_batch_id"]
    assert len(world.seasons()) == 1
    assert len(world.batches(first["id"])) == 1


@real_db
def test_the_same_code_with_different_details_is_a_conflict_not_a_replay(world):
    create(world, world.owner)
    with pytest.raises(SeasonCodeTakenError):
        create(world, world.owner, variety_name="ST25")


@real_db
def test_a_second_active_season_on_the_plot_is_refused(world):
    create(world, world.owner, code="HT-2026")
    with pytest.raises(ActiveSeasonExistsError):
        create(world, world.manager, code="DX-2026")
    assert len(world.seasons()) == 1


@real_db
def test_a_new_season_can_start_once_the_previous_one_is_harvested(world):
    first, _ = create(world, world.owner, code="HT-2026")
    world.conn.execute("update public.crop_seasons set status = 'harvested' where id = %s", (first["id"],))
    second, _ = create(world, world.owner, code="DX-2026")
    assert second["status"] == "active"
    assert {s["status"] for s in world.seasons()} == {"harvested", "active"}


@real_db
def test_a_soft_deleted_season_code_cannot_be_reused(world):
    first, _ = create(world, world.owner)
    world.conn.execute("update public.crop_seasons set deleted_at = now() where id = %s", (first["id"],))
    with pytest.raises(SeasonCodeTakenError):
        create(world, world.owner)


@real_db
def test_an_activity_can_be_recorded_on_the_new_season_immediately(world):
    season, _ = create(world, world.owner)
    # What ActivityWriteService._write_batch requires before any journal write.
    open_batches = [b for b in world.batches(season["id"]) if b["status"] not in {"closed", "cancelled"}]
    assert season["status"] == "active" and len(open_batches) == 1
    writes = PostgresActivityWriteRepository(settings=None, connect=_savepoint_factory(world.conn))
    row, replay = writes.create(
        crop_season_id=season["id"], production_batch_id=open_batches[0]["id"], actor_id=world.owner,
        idempotency_key=str(uuid.uuid4()), activity_type="irrigation",
        occurred_at=datetime(2026, 5, 20, tzinfo=timezone.utc), note="SEASON-TEST",
        data={"method": "awd", "water_volume_m3": 3, "duration_minutes": None, "water_level_cm": None,
              "pump_energy_kwh": None, "total_cost_vnd": None},
    )
    assert replay is False
    assert row["crop_season_id"] == season["id"]
    batch = world.conn.execute("select production_batch_id::text as b from public.activities where id = %s", (row["id"],)).fetchone()
    assert batch["b"] == season["default_production_batch_id"]


def test_create_response_schema_requires_the_batch():
    with pytest.raises(Exception):
        schemas.CropSeasonCreateResponse.model_validate({
            "id": "s", "plot_id": "p", "season_code": "c", "crop_type": "rice", "status": "active",
        })


# -- Codex review hardening ----------------------------------------------------

from infrastructure.write_repo import ActivityWritePermissionError, SeasonNotOpenError  # noqa: E402

IRRIGATION = {"method": "awd", "water_volume_m3": 3, "duration_minutes": None, "water_level_cm": None,
              "pump_energy_kwh": None, "total_cost_vnd": None}


def _record(world, batch, actor):
    writes = PostgresActivityWriteRepository(settings=None, connect=_savepoint_factory(world.conn))
    return writes.create(
        crop_season_id="unused", production_batch_id=batch, actor_id=actor, idempotency_key=str(uuid.uuid4()),
        activity_type="irrigation", occurred_at=datetime(2026, 5, 20, tzinfo=timezone.utc), note="SEASON-TEST",
        data=IRRIGATION,
    )


@real_db
@pytest.mark.parametrize("status", ["harvested", "closed", "cancelled", "planned"])
def test_the_write_transaction_itself_refuses_a_season_that_is_no_longer_active(world, status):
    """The service reads the status through PostgREST before the write; a season
    closed in between must still be refused, inside the write's transaction."""
    season, _ = create(world, world.owner)
    world.conn.execute("update public.crop_seasons set status = %s where id = %s", (status, season["id"]))
    with pytest.raises(SeasonNotOpenError):
        _record(world, season["default_production_batch_id"], world.owner)
    assert world.conn.execute("select count(*) as n from public.activities a join public.production_batches pb "
                              "on pb.id = a.production_batch_id where pb.crop_season_id = %s", (season["id"],)).fetchone()["n"] == 0


@real_db
def test_a_closed_batch_is_refused_inside_the_transaction(world):
    season, _ = create(world, world.owner)
    world.conn.execute("update public.production_batches set status = 'closed' where id = %s", (season["default_production_batch_id"],))
    with pytest.raises(SeasonNotOpenError):
        _record(world, season["default_production_batch_id"], world.owner)


@real_db
def test_a_farm_role_that_outlived_its_membership_grants_nothing(world):
    """`user_can_write_farm` accepts a stale owner row; the FastAPI writes do not."""
    season, _ = create(world, world.owner)
    world.conn.execute("update public.organization_memberships set ended_at = now() - interval '1 hour' "
                       "where user_id = %s", (world.editor,))
    with pytest.raises(SeasonScopeError):
        world.conn.execute("update public.crop_seasons set status = 'harvested' where id = %s", (season["id"],))
        create(world, world.editor, code="DX-2026")
    world.conn.execute("update public.crop_seasons set status = 'active' where id = %s", (season["id"],))
    with pytest.raises(ActivityWritePermissionError):
        _record(world, season["default_production_batch_id"], world.editor)


@real_db
def test_a_deleted_farm_takes_no_new_season(world):
    world.conn.execute("update public.farms set deleted_at = now() where id = %s", (world.farm,))
    with pytest.raises(SeasonScopeError):
        create(world, world.manager)
