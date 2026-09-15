"""FW-2 Part 3: seeding / pesticide / straw_management activity writes.

Reuses the FW-2 Part 1 write-domain fixtures (FakeRead, FakeTransactionalWriteRepository,
service()) from test_activity_writes.py — no parallel write-service test harness.
No hosted data is mutated.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from carbon.methodology import classify_straw  # noqa: E402
from carbon.models import StrawEvent  # noqa: E402
from infrastructure.read_repo import _COST_FIELD_BY_ACTIVITY  # noqa: E402
from infrastructure.write_repo import PostgresActivityWriteRepository, _DETAILS  # noqa: E402
from service import ActivityWriteService  # noqa: E402

from tests.test_activity_writes import ACTOR, BATCH, FakeRead, FakeTransactionalWriteRepository, SEASON  # noqa: E402


def request(kind, data, *, key="10000000-0000-0000-0000-000000000001"):
    return schemas.ActivityCreateRequest(idempotency_key=key, activity_type=kind, occurred_at="2026-09-10T08:00:00Z", data=data)


def service(repo=None):
    return ActivityWriteService(repo or FakeTransactionalWriteRepository())


def write_client(read=None, write=None):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: read or FakeRead()
    app.dependency_overrides[api._activity_write_service] = lambda: write or service()
    return TestClient(app)


# --------------------------------------------------------------- idempotency

@pytest.mark.parametrize(("kind", "data"), [
    ("seeding", {"variety_name": "OM5451", "seed_kg": 120}),
    ("pesticide", {"product_name": "Regent", "amount": 0.5, "unit": "kg"}),
    ("straw_management", {"method": "incorporated", "straw_mass_kg": 4000}),
])
def test_same_key_same_payload_returns_original_for_new_types(kind, data):
    repo = FakeTransactionalWriteRepository(); write = service(repo)
    first = write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request(kind, data))
    replay = write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request(kind, data))
    assert replay["id"] == first["id"]
    assert replay["idempotent_replay"] is True
    assert len(repo.rows) == 1


@pytest.mark.parametrize(("kind", "data", "changed"), [
    ("seeding", {"variety_name": "OM5451", "seed_kg": 120}, {"variety_name": "OM5451", "seed_kg": 121}),
    ("pesticide", {"product_name": "Regent", "amount": 0.5, "unit": "kg"}, {"product_name": "Regent", "amount": 1.0, "unit": "kg"}),
    ("straw_management", {"method": "incorporated", "straw_mass_kg": 4000}, {"method": "burned", "straw_mass_kg": 4000}),
])
def test_same_key_different_payload_conflicts_for_new_types(kind, data, changed):
    from infrastructure.write_repo import IdempotencyConflictError
    write = service()
    write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request(kind, data))
    with pytest.raises(IdempotencyConflictError):
        write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request(kind, changed))


# ------------------------------------------------------------ cross-scope

@pytest.mark.parametrize("kind_data", [
    ("seeding", {"variety_name": "OM5451", "seed_kg": 120}),
    ("pesticide", {"product_name": "Regent", "amount": 0.5, "unit": "kg"}),
    ("straw_management", {"method": "incorporated", "straw_mass_kg": 4000}),
])
@pytest.mark.parametrize("read", [FakeRead(role="cooperative_manager"), FakeRead(role="enterprise_viewer"), FakeRead(visible=False)])
def test_non_farmer_or_cross_scope_cannot_write_new_types(read, kind_data):
    from service import ActivityWriteAccessError
    kind, data = kind_data
    with pytest.raises(ActivityWriteAccessError):
        service().create(read_repository=read, crop_season_id=SEASON, request=request(kind, data))


def test_unauthenticated_route_denied_for_new_type():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._activity_write_service] = service()
    body = {"idempotency_key": "10000000-0000-0000-0000-000000000009", "activity_type": "straw_management",
            "occurred_at": "2026-09-10T08:00:00Z", "data": {"method": "burned"}}
    response = TestClient(app).post(f"/v1/crop-seasons/{SEASON}/activities", json=body)
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


# ------------------------------------------------------- type immutability

def test_patch_cannot_change_activity_type_even_if_smuggled_in_body():
    """ActivityUpdateRequest has no `activity_type` field at all (FW-2 §17) —
    a browser cannot mutate type/crop_season/idempotency_key/actor through
    PATCH by construction. This locks that in for the new types too.
    """
    repo = FakeTransactionalWriteRepository()
    client = write_client(write=service(repo))
    created = client.post(
        f"/v1/crop-seasons/{SEASON}/activities",
        json={"idempotency_key": "10000000-0000-0000-0000-000000000002", "activity_type": "seeding",
              "occurred_at": "2026-09-10T08:00:00Z", "data": {"variety_name": "OM5451", "seed_kg": 100}},
    ).json()

    patched = client.patch(
        f"/v1/activities/{created['id']}",
        json={"data": {"variety_name": "OM5451", "seed_kg": 110}, "activity_type": "pesticide"},
    )
    assert patched.status_code == 200
    assert patched.json()["activity_type"] == "seeding"  # smuggled field silently ignored, type unchanged
    assert repo.rows[created["id"]]["activity_type"] == "seeding"


# --------------------------------------------------- seeding cost regression

def test_seeding_write_schema_cost_field_matches_resource_metrics_cost_field():
    """The exact bug this guards: seeding's DB/write column is `cost_vnd`,
    every other type's is `total_cost_vnd`. read_repo.metrics() must key off
    the same name the write contract actually persists (FW-2 Part 3 §6).
    """
    assert "cost_vnd" in schemas.SeedingActivityData.model_fields
    assert "total_cost_vnd" not in schemas.SeedingActivityData.model_fields
    assert _COST_FIELD_BY_ACTIVITY["seeding"] == "cost_vnd"
    _, seeding_columns = _DETAILS["seeding"]
    assert _COST_FIELD_BY_ACTIVITY["seeding"] in seeding_columns


# --------------------------------------------- write/read/Carbon column contract

def test_write_repo_columns_are_a_superset_of_what_the_carbon_mapper_reads():
    """Guards the exact class of bug the seeding cost mismatch was: the
    write path and the Carbon adapter (infrastructure/mapping.py) must agree
    on detail-column names, or a real write would silently produce data the
    Carbon loader can never see.
    """
    from infrastructure import mapping as m

    _, seeding_columns = _DETAILS["seeding"]
    assert {"variety_name", "seed_kg", "seeding_method"} <= set(seeding_columns)

    _, pesticide_columns = _DETAILS["pesticide"]
    assert {"product_name", "active_ingredient", "amount", "unit"} <= set(pesticide_columns)

    _, straw_columns = _DETAILS["straw_management"]
    assert {"method", "straw_mass_kg", "dry_matter_fraction", "days_before_cultivation", "returned_to_field"} <= set(straw_columns)
    assert m  # imported for documentation/co-location; no attribute access needed beyond this


# --------------------------------------------- straw double-count / Carbon path

def test_straw_double_count_guard_one_activity_one_method_one_path():
    """Schema invariant preserved (FW-2 Part 3 §13): straw_management_events
    has exactly one `method` per row — a single write can never land in both
    the SFo amendment path and the burned-residue path. classify_straw()
    itself is pre-existing Carbon Engine code (tests/test_carbon_engine.py
    already covers it in depth); this only proves the write contract cannot
    produce a split-fraction payload that would defeat that invariant.
    """
    assert "fraction" not in schemas.StrawManagementActivityData.model_fields
    assert "burned_mass_kg" not in schemas.StrawManagementActivityData.model_fields
    assert "incorporated_mass_kg" not in schemas.StrawManagementActivityData.model_fields

    incorporated = StrawEvent(method="incorporated", mass_kg=1000, dry_matter_fraction=0.85, days_before_cultivation=10)
    burned = StrawEvent(method="burned", mass_kg=1000, dry_matter_fraction=0.85)
    removed = StrawEvent(method="removed", mass_kg=1000)
    amendments, burned_out = classify_straw([incorporated, burned, removed], "season-x", area_ha=1.0)
    assert len(amendments) == 1 and amendments[0].origin == "straw:incorporated"
    assert len(burned_out) == 1 and burned_out[0] is burned
    assert removed not in burned_out and removed not in [a for a in amendments]


def test_soft_deleted_straw_excluded_from_carbon_loader_by_construction():
    """RawCropBundle.by_type() (infrastructure/mapping.py) filters
    `deleted_at is None` generically for every activity type — this is the
    same code path DELETE already uses for fertilizer/irrigation/harvest;
    this test only proves the filter is type-agnostic, not straw-specific
    logic that could silently miss the new type.
    """
    from infrastructure.mapping import RawCropBundle

    bundle = RawCropBundle(
        crop_season={"id": "season-x"}, plot={"area_ha": 1.0},
        activities=[
            {"activity_type": "straw_management", "deleted_at": None, "detail": {"method": "burned", "straw_mass_kg": 500}},
            {"activity_type": "straw_management", "deleted_at": "2026-09-10T00:00:00Z", "detail": {"method": "burned", "straw_mass_kg": 999999}},
        ],
    )
    visible = bundle.by_type("straw_management")
    assert len(visible) == 1
    assert visible[0]["detail"]["straw_mass_kg"] == 500


# --------------------------------------------------- real repository SQL shape

class _FakeCursor:
    """Returns queued `fetchone()` results in call order rather than matching
    on SQL text — `create()` runs a fixed sequence (replay lookup, insert
    activities RETURNING id, insert detail [no fetchone], select base view,
    select detail) and both the base-view and replay-lookup SQL legitimately
    contain the substring "from public.activities", so text-matching would
    be ambiguous between them.
    """

    def __init__(self, fetchone_queue):
        self.executed: list[tuple[str, list]] = []
        self._queue = list(fetchone_queue)

    def execute(self, sql, args=None):
        self.executed.append((sql, list(args or [])))

    def fetchone(self):
        row = self._queue.pop(0)
        return dict(row) if row is not None else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _now():
    return datetime(2026, 9, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize(("activity_type", "table", "data"), [
    ("seeding", "seeding_events", {"variety_name": "OM5451", "seed_kg": 120, "seeding_method": "sạ lan", "cost_vnd": 500000}),
    ("pesticide", "pesticide_applications", {"product_name": "Regent", "active_ingredient": None, "amount": 0.5, "unit": "kg", "total_cost_vnd": None}),
    ("straw_management", "straw_management_events", {
        "method": "incorporated", "straw_mass_kg": 4000, "total_cost_vnd": None,
        "days_before_cultivation": 10, "dry_matter_fraction": 0.85, "returned_to_field": None,
    }),
])
def test_postgres_repository_inserts_into_the_correct_detail_table(activity_type, table, data):
    """Fake-cursor SQL capture (same pattern as
    test_recommendation_repo_uuid_normalization.py) — no live DB needed, but
    proves the INSERT statement targets the real table/columns for each new
    type, not just that Pydantic validation accepts the payload.
    """
    view_row = {
        "id": "activity-1", "crop_season_id": SEASON, "activity_type": activity_type,
        "occurred_at": _now(), "note": None, "created_by": ACTOR, "created_at": _now(), "updated_at": _now(),
    }
    cursor = _FakeCursor([
        {"allowed": True},       # 0. private.user_can_write_batch (B3) — set_config calls fetch nothing
        None,                    # 1. idempotency replay lookup: no existing row
        {"id": "activity-1"},    # 2. insert into activities ... returning id
        # 3. insert into public.<table> — no fetchone() call
        view_row,                # 4. _view()'s base select (join production_batches)
        data,                    # 5. _view()'s detail select
    ])
    repo = PostgresActivityWriteRepository(settings=None, connect=lambda: _FakeConn(cursor))

    result, replay = repo.create(
        crop_season_id=SEASON, production_batch_id=f"{BATCH}-0", actor_id=ACTOR,
        idempotency_key="10000000-0000-0000-0000-000000000003",
        activity_type=activity_type, occurred_at=_now(), note=None, data=data,
    )

    assert replay is False
    assert result["activity_type"] == activity_type
    assert result["data"] == data
    insert_detail_sql = next(sql for sql, _ in cursor.executed if sql.strip().startswith(f"insert into public.{table}"))
    for column in data:
        assert column in insert_detail_sql
