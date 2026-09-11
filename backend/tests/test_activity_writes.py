"""FW-2 Part 1 write-domain tests; no hosted data is mutated."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from infrastructure.write_repo import ActivityNotFoundError, IdempotencyConflictError  # noqa: E402
from service import ActivityWriteAccessError, ActivityWriteService, InvalidCropSeasonStateError  # noqa: E402


ACTOR, SEASON, BATCH = "farmer-a", "season-a", "batch-a"


class FakeRead:
    def __init__(self, *, role: str = "farmer", visible: bool = True, status: str = "active", batches: int = 1):
        self.role, self.visible, self.status, self.batches = role, visible, status, batches

    def me(self):
        return {"user_id": ACTOR, "roles": [self.role]}

    def season(self, season_id):
        if not self.visible or season_id != SEASON:
            raise ReadNotFoundError("crop_seasons")
        return {"id": SEASON, "status": self.status}

    def production_batches(self, season_id):
        self.season(season_id)
        return [{"id": f"{BATCH}-{i}", "status": "active"} for i in range(self.batches)]

    def activity(self, activity_id):
        if not self.visible:
            raise ReadNotFoundError("activities")
        return {"id": activity_id}


class FakeTransactionalWriteRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.keys: dict[tuple[str, str], str] = {}
        self._next = 1

    def _view(self, activity_id, *, actor_id=None):
        row = self.rows.get(activity_id)
        if not row or row.get("deleted") or (actor_id and row["created_by"] != actor_id):
            raise ActivityNotFoundError()
        return deepcopy(row)

    def get_for_actor(self, activity_id, actor_id):
        return self._view(activity_id, actor_id=actor_id)

    def create(self, **payload):
        key = (payload["actor_id"], payload["idempotency_key"])
        if key in self.keys:
            if self.rows[self.keys[key]].get("deleted"):
                raise IdempotencyConflictError()
            row = self._view(self.keys[key], actor_id=payload["actor_id"])
            requested = {key: payload[key] for key in ("crop_season_id", "activity_type", "occurred_at", "note", "data")}
            if {key: row[key] for key in requested} != requested:
                raise IdempotencyConflictError()
            return row, True
        activity_id = f"activity-{self._next}"; self._next += 1
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        row = {
            "id": activity_id, "crop_season_id": payload["crop_season_id"],
            "activity_type": payload["activity_type"], "occurred_at": payload["occurred_at"],
            "note": payload["note"], "data": deepcopy(payload["data"]),
            "created_by": payload["actor_id"], "created_at": now, "updated_at": now,
            "deleted": False,
        }
        self.rows[activity_id] = row; self.keys[key] = activity_id
        return self._view(activity_id, actor_id=payload["actor_id"]), False

    def update(self, *, activity_id, actor_id, occurred_at, note, update_note, data):
        row = self.rows[activity_id]
        if row["created_by"] != actor_id or row["deleted"]:
            raise ActivityNotFoundError()
        if occurred_at is not None: row["occurred_at"] = occurred_at
        if update_note: row["note"] = note
        if data is not None: row["data"] = deepcopy(data)
        row["updated_at"] = datetime(2026, 9, 11, tzinfo=timezone.utc)
        return self._view(activity_id, actor_id=actor_id)

    def soft_delete(self, *, activity_id, actor_id):
        row = self.rows.get(activity_id)
        if not row or row["created_by"] != actor_id or row["deleted"]:
            raise ActivityNotFoundError()
        row["deleted"] = True


def request(kind, data, *, key="00000000-0000-0000-0000-000000000001"):
    return schemas.ActivityCreateRequest(
        idempotency_key=key, activity_type=kind,
        occurred_at="2026-09-10T08:00:00Z", data=data,
    )


def service(repo=None):
    return ActivityWriteService(repo or FakeTransactionalWriteRepository())


def write_client(read=None, write=None):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: read or FakeRead()
    app.dependency_overrides[api._activity_write_service] = lambda: write or service()
    return TestClient(app)


def request_body(kind="fertilizer", data=None, *, key="00000000-0000-0000-0000-000000000001"):
    return {
        "idempotency_key": key,
        "activity_type": kind,
        "occurred_at": "2026-09-10T08:00:00Z",
        "data": data or {"fertilizer_name": "Urea", "amount_kg": 120},
    }


@pytest.mark.parametrize(("kind", "data"), [
    ("fertilizer", {"fertilizer_name": "Urea", "amount_kg": 120, "nitrogen_percent": 46}),
    ("irrigation", {"method": "awd", "water_volume_m3": 32}),
    ("harvest", {"yield_kg": 3100, "moisture_percent": 14}),
])
def test_farmer_can_create_each_supported_activity_type(kind, data):
    result = service().create(read_repository=FakeRead(), crop_season_id=SEASON, request=request(kind, data))
    assert result["activity_type"] == kind
    assert {key: result["data"][key] for key in data} == data
    assert result["idempotent_replay"] is False


def test_same_key_same_payload_returns_original_activity_without_duplicate():
    repo = FakeTransactionalWriteRepository(); write = service(repo)
    first = write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("harvest", {"yield_kg": 100}))
    replay = write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("harvest", {"yield_kg": 100}))
    assert replay["id"] == first["id"]
    assert replay["idempotent_replay"] is True
    assert len(repo.rows) == 1  # one activity implies one harvest_events source row in real repository


def test_same_key_different_payload_conflicts():
    write = service()
    write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("fertilizer", {"fertilizer_name": "Urea", "amount_kg": 1}))
    with pytest.raises(IdempotencyConflictError):
        write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("fertilizer", {"fertilizer_name": "Urea", "amount_kg": 2}))


def test_deleted_activity_key_cannot_silently_recreate_a_second_logical_event():
    write = service()
    created = write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}))
    write.delete(read_repository=FakeRead(), activity_id=created["id"])
    with pytest.raises(IdempotencyConflictError):
        write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}))


def test_harvest_update_changes_the_same_denominator_source_and_soft_delete_excludes_it():
    repo = FakeTransactionalWriteRepository(); write = service(repo)
    created = write.create(read_repository=FakeRead(), crop_season_id=SEASON, request=request("harvest", {"yield_kg": 100}))
    updated = write.update(
        read_repository=FakeRead(), activity_id=created["id"],
        request=schemas.ActivityUpdateRequest(data={"yield_kg": 125}),
    )
    assert updated["data"]["yield_kg"] == 125
    write.delete(read_repository=FakeRead(), activity_id=created["id"])
    with pytest.raises(ActivityNotFoundError):
        repo.get_for_actor(created["id"], ACTOR)


@pytest.mark.parametrize("bad", [
    ("fertilizer", {"fertilizer_name": "Urea", "amount_kg": -1}),
    ("fertilizer", {"fertilizer_name": "Urea", "amount_kg": 1, "nitrogen_percent": 101}),
    ("irrigation", {"method": "awd", "water_volume_m3": -1}),
    ("harvest", {"yield_kg": 0}),
])
def test_payload_validation_rejects_invalid_domain_values(bad):
    kind, data = bad
    with pytest.raises(Exception):
        request(kind, data)


@pytest.mark.parametrize("read", [FakeRead(role="cooperative_manager"), FakeRead(role="enterprise_viewer"), FakeRead(visible=False)])
def test_non_farmer_or_cross_scope_cannot_write(read):
    with pytest.raises(ActivityWriteAccessError):
        service().create(read_repository=read, crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}))


def test_closed_season_and_ambiguous_batch_are_rejected():
    with pytest.raises(InvalidCropSeasonStateError):
        service().create(read_repository=FakeRead(status="closed"), crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}))
    with pytest.raises(InvalidCropSeasonStateError):
        service().create(read_repository=FakeRead(batches=2), crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}))


def test_write_error_mapping_uses_frozen_envelope():
    with pytest.raises(HTTPException) as caught:
        api._write_or_http(lambda: (_ for _ in ()).throw(IdempotencyConflictError()))
    assert caught.value.status_code == 409
    assert caught.value.detail["error"]["code"] == "duplicate_event"


def test_post_route_returns_normalized_activity_and_idempotent_replay():
    repository = FakeTransactionalWriteRepository()
    client = write_client(write=service(repository))
    first = client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body())
    replay = client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body())
    assert first.status_code == 201
    assert first.json()["activity_type"] == "fertilizer"
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["idempotent_replay"] is True
    assert len(repository.rows) == 1


def test_post_route_conflict_and_scope_denial_use_domain_statuses():
    repository = FakeTransactionalWriteRepository()
    writer = service(repository)
    client = write_client(write=writer)
    assert client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body()).status_code == 201
    conflict = client.post(
        f"/v1/crop-seasons/{SEASON}/activities",
        json=request_body(data={"fertilizer_name": "Urea", "amount_kg": 121}),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"]["code"] == "duplicate_event"
    denied = write_client(read=FakeRead(role="cooperative_manager"), write=writer).post(
        f"/v1/crop-seasons/{SEASON}/activities", json=request_body(key="00000000-0000-0000-0000-000000000002")
    )
    assert denied.status_code == 404
    assert denied.json()["detail"]["error"]["code"] == "not_found"


def test_write_routes_require_bearer_authentication_before_service_access():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._activity_write_service] = service()
    response = TestClient(app).post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body())
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


def test_empty_patch_is_rejected_instead_of_a_noop_update():
    with pytest.raises(ValidationError):
        schemas.ActivityUpdateRequest()
