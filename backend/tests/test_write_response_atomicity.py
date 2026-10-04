"""P1-A write-response atomicity against the REAL database.

Invariant: a mutation never ends with the row committed AND an avoidable
response validation/serialization 500. Every write repository therefore builds
its success representation through `prepare` *inside* its transaction.

Each test runs a real repository on a real Postgres connection whose
transaction is a savepoint inside an outer transaction that is always rolled
back. `prepare` first records proof that the write SQL ran (the new id / the
new value, read back through the same transaction), then raises -- standing in
for a response model rejecting the row. The test then checks that nothing the
write did survived. Skipped when `SUPABASE_DB_URL` is not configured.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schemas  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402
from infrastructure.cv_repo import PostgresCvRepository  # noqa: E402
from infrastructure.mrv_export_repo import PostgresMrvExportRepository  # noqa: E402
from infrastructure.recommendation_repo import PostgresRecommendationRepository  # noqa: E402
from infrastructure.write_repo import PostgresActivityWriteRepository  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the real-database tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url

pytestmark = pytest.mark.skipif(
    not _DB_URL,
    reason="SUPABASE_DB_URL is not configured; the atomicity invariant needs a real database.",
)

FARM_CODE = "DEMO-FARM-01"
NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


class ResponseRejected(Exception):
    """Stands in for a response model refusing the freshly written row."""


@pytest.fixture
def db():
    with psycopg.connect(_DB_URL, autocommit=False, row_factory=dict_row) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


def _one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def _savepoint_factory(conn):
    """A repository `connect` whose transaction is a real savepoint: it commits
    (releases) on success and rolls back on an exception, like the pool."""
    class _Savepoint:
        def __enter__(self):
            self._tx = conn.transaction()
            self._tx.__enter__()
            return type("Bound", (), {"cursor": lambda _self: conn.cursor(row_factory=dict_row)})()

        def __exit__(self, *exc):
            return self._tx.__exit__(*exc)

    return _Savepoint


def _reject(proof: dict, key: str, value_of=lambda x: x):
    def prepare(result):
        proof[key] = value_of(result)
        raise ResponseRejected()
    return prepare


@pytest.fixture
def scope(db):
    row = _one(db, """
        select pb.id::text as batch, pb.crop_season_id::text as season, fm.user_id::text as farmer,
               f.id::text as farm
        from public.farms f
        join public.plots p on p.farm_id = f.id
        join public.crop_seasons cs on cs.plot_id = p.id
        join public.production_batches pb on pb.crop_season_id = cs.id
        join public.farm_members fm on fm.farm_id = f.id and fm.farm_role in ('owner', 'editor')
        join public.organization_memberships om on om.user_id = fm.user_id and om.organization_id = f.cooperative_id
        where f.farm_code = %s and pb.deleted_at is null and om.role = 'farmer'
          and (om.ended_at is null or om.ended_at > now())
        limit 1""", (FARM_CODE,))
    assert row, "no writable farmer scope on the demo farm"
    return row


# -- activities --------------------------------------------------------------

def test_activity_create_rolls_back_when_the_response_is_rejected(db, scope):
    repo = PostgresActivityWriteRepository(settings=None, connect=_savepoint_factory(db))
    key, proof = str(uuid.uuid4()), {}
    with pytest.raises(ResponseRejected):
        repo.create(
            crop_season_id=scope["season"], production_batch_id=scope["batch"], actor_id=scope["farmer"],
            idempotency_key=key, activity_type="irrigation", occurred_at=NOW, note="ATOMICITY-TEST",
            data={"method": "awd", "water_volume_m3": 3, "duration_minutes": None, "water_level_cm": None,
                  "pump_energy_kwh": None, "total_cost_vnd": None},
            prepare=_reject(proof, "id", lambda out: out[0]["id"]),
        )
    assert proof["id"]  # the INSERTs ran and were readable inside the transaction
    assert _one(db, "select count(*) as n from public.activities where id = %s", (proof["id"],))["n"] == 0
    assert _one(db, "select count(*) as n from public.irrigation_events where activity_id = %s", (proof["id"],))["n"] == 0
    assert _one(db, "select count(*) as n from public.activities where web_idempotency_key = %s", (key,))["n"] == 0


def test_activity_update_rolls_back_base_and_subtype_when_the_response_is_rejected(db, scope):
    activity = _one(db, """
        insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, note)
        values (%s, 'straw_management', now(), now(), 'web', %s, 'BEFORE') returning id::text as id""",
        (scope["batch"], scope["farmer"]))["id"]
    db.execute("insert into public.straw_management_events (activity_id, method, straw_mass_kg) values (%s, 'incorporated', 800)", (activity,))
    repo = PostgresActivityWriteRepository(settings=None, connect=_savepoint_factory(db))
    proof = {}
    with pytest.raises(ResponseRejected):
        repo.update(
            activity_id=activity, actor_id=scope["farmer"], occurred_at=None, note="AFTER", update_note=True,
            data={"method": "incorporated", "straw_mass_kg": 800, "total_cost_vnd": None,
                  "days_before_cultivation": 20, "dry_matter_fraction": 0.85, "returned_to_field": True},
            prepare=_reject(proof, "row"),
        )
    assert proof["row"]["note"] == "AFTER" and proof["row"]["data"]["days_before_cultivation"] == 20
    assert _one(db, "select note from public.activities where id = %s", (activity,))["note"] == "BEFORE"
    straw = _one(db, "select days_before_cultivation, dry_matter_fraction from public.straw_management_events where activity_id = %s", (activity,))
    assert straw == {"days_before_cultivation": None, "dry_matter_fraction": None}


def test_crop_season_methodology_rolls_back_when_the_response_is_rejected(db, scope):
    before = _one(db, "select cultivation_days from public.crop_seasons where id = %s", (scope["season"],))
    new_days = (before["cultivation_days"] or 0) + 17
    repo = PostgresActivityWriteRepository(settings=None, connect=_savepoint_factory(db))
    proof = {}
    with pytest.raises(ResponseRejected):
        repo.update_crop_season_methodology(
            crop_season_id=scope["season"], actor_id=scope["farmer"], fields={"cultivation_days": new_days},
            prepare=_reject(proof, "row"),
        )
    assert proof["row"]["cultivation_days"] == new_days
    assert _one(db, "select cultivation_days from public.crop_seasons where id = %s", (scope["season"],)) == before


# -- recommendations --------------------------------------------------------

def _rec(rule_code: str):
    return SimpleNamespace(
        rule_code=rule_code, rule_version="test", engine_version="test", type="data_task", title="t", reason="r",
        compared_to=None, co2e_total_kg_before=None, co2e_total_kg_after=None, co2e_total_kg_delta=None,
        co2e_percent_delta=None, impact_status="unavailable", impact_unavailable_reason="test",
        evidence={}, input_hash="h",
    )


def test_recommendation_generation_rolls_back_the_whole_run_when_the_response_is_rejected(db, scope):
    before = _one(db, "select count(*) as n from public.season_recommendations where crop_season_id = %s", (scope["season"],))
    repo = PostgresRecommendationRepository(settings=None, connect=_savepoint_factory(db))
    proof = {}
    with pytest.raises(ResponseRejected):
        repo.save_generated(
            crop_season_id=scope["season"], recs=[_rec("ATOMICITY_TEST_RULE")], actor_id=scope["farmer"],
            prepare=_reject(proof, "ids", lambda rows: [r["id"] for r in rows]),
        )
    assert len(proof["ids"]) == 1
    assert _one(db, "select count(*) as n from public.season_recommendations where id = %s", (proof["ids"][0],))["n"] == 0
    # The prune of this season's other `generated` rows is undone with it.
    assert _one(db, "select count(*) as n from public.season_recommendations where crop_season_id = %s", (scope["season"],)) == before


def test_recommendation_status_change_rolls_back_when_the_response_is_rejected(db, scope):
    rec_id = _one(db, """
        insert into public.season_recommendations
          (crop_season_id, rule_code, rule_version, type, title, reason, impact_status, input_hash)
        values (%s, 'ATOMICITY_TEST_RULE', 'test', 'data_task', 't', 'r', 'unavailable', 'h') returning id::text as id""",
        (scope["season"],))["id"]
    repo = PostgresRecommendationRepository(settings=None, connect=_savepoint_factory(db))
    proof = {}
    with pytest.raises(ResponseRejected):
        repo.set_status(rec_id, "accepted", actor_id=scope["farmer"], prepare=_reject(proof, "row"))
    assert proof["row"]["status"] == "accepted"
    row = _one(db, "select status::text as status, accepted_at from public.season_recommendations where id = %s", (rec_id,))
    assert row == {"status": "generated", "accepted_at": None}


# -- CV ------------------------------------------------------------------------

def test_cv_inference_rolls_back_when_the_response_is_rejected(db, scope):
    model = _one(db, "select id::text as id from public.cv_model_versions limit 1")
    assert model, "no CV model version to attach an inference to"
    image = _one(db, """
        insert into public.plant_images (crop_season_id, storage_bucket, storage_object_path, mime_type, file_size_bytes, sha256, uploaded_by)
        values (%s, 'plant-images', %s, 'image/jpeg', 10, %s, %s) returning id::text as id""",
        (scope["season"], f"{scope['farm']}/{scope['season']}/{uuid.uuid4()}.jpg", uuid.uuid4().hex * 2, scope["farmer"]))["id"]
    repo = PostgresCvRepository(settings=None, connect=_savepoint_factory(db))
    proof = {}
    with pytest.raises(ResponseRejected):
        repo.create_inference(
            image_id=image, model_version_id=model["id"], predicted_label="healthy",
            confidence=0.9, threshold_used=0.5, actor_id=scope["farmer"], prepare=_reject(proof, "id", lambda row: row["id"]),
        )
    assert _one(db, "select count(*) as n from public.cv_inferences where id = %s", (proof["id"],))["n"] == 0


# -- MRV -----------------------------------------------------------------------

def test_mrv_export_row_rolls_back_when_the_response_is_rejected(db):
    case = _one(db, "select id::text as id, organization_id::text as org from public.mrv_cases limit 1")
    assert case, "no MRV case to export"
    actor = _one(db, "select id::text as id from auth.users limit 1")["id"]
    export_id = str(uuid.uuid4())
    repo = PostgresMrvExportRepository(settings=None, connect=_savepoint_factory(db))
    proof = {}
    with pytest.raises(ResponseRejected):
        repo.create(
            export_id=export_id, mrv_case_id=case["id"], organization_id=case["org"], fmt="json",
            factor_set_id=None, scope_description="ATOMICITY-TEST", data_as_of_at=NOW,
            warning_text="test", storage_object_path=f"{case['org']}/{case['id']}/atomicity-{export_id}.json",
            file_sha256="0" * 64, payload={"k": "v"}, generated_by=actor, generated_at=NOW,
            calculation_ids=[], prepare=_reject(proof, "id", lambda row: row["id"]),
        )
    assert proof["id"] == export_id
    assert _one(db, "select count(*) as n from public.mrv_exports where id = %s", (export_id,))["n"] == 0


# -- the success path: validated AND serialized before commit ----------------------

def test_success_payload_is_plain_json_built_inside_the_transaction(db, scope):
    """UUID, Decimal, datetime, enum text and JSON detail all come out of
    `success_payload` as JSON-safe values, so the route has nothing left that
    can fail after the commit."""
    repo = PostgresActivityWriteRepository(settings=None, connect=_savepoint_factory(db))
    body = repo.create(
        crop_season_id=scope["season"], production_batch_id=scope["batch"], actor_id=scope["farmer"],
        idempotency_key=str(uuid.uuid4()), activity_type="straw_management", occurred_at=NOW, note=None,
        data={"method": "incorporated", "straw_mass_kg": 812.5, "total_cost_vnd": None,
              "days_before_cultivation": 20, "dry_matter_fraction": 0.85, "returned_to_field": None},
        prepare=lambda out: schemas.success_payload(
            schemas.ActivityWriteResponse,
            {**out[0], "idempotent_replay": out[1]},
        ),
    )
    json.dumps(body, allow_nan=False)
    assert isinstance(body["id"], str) and isinstance(body["created_at"], str)
    assert body["created_by"] == scope["farmer"]
    # The re-validation FastAPI still runs on the route cannot reject it.
    assert schemas.ActivityWriteResponse.model_validate(body).id == body["id"]
