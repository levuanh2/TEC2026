"""B3: a farm member with `farm_role = viewer` is read-only through FastAPI.

Service/API tests reuse the FW-2 fakes and add the one thing they did not model:
the repository's write-permission answer. A second group drives the REAL
`PostgresActivityWriteRepository` against a scripted cursor, to pin that the
permission check is issued inside the write transaction and *before* any row is
touched. The same rule against the hosted database lives in
`test_p0_security_policies.py`.
"""
from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schemas  # noqa: E402
from infrastructure.write_repo import (  # noqa: E402
    ActivityNotFoundError,
    ActivityWritePermissionError,
    PostgresActivityWriteRepository,
)
from service import ActivityWriteAccessError, ActivityWriteService  # noqa: E402
from tests.test_activity_writes import (  # noqa: E402
    ACTOR,
    SEASON,
    FakeRead,
    FakeTransactionalWriteRepository,
    request,
    request_body,
    write_client,
)


class PermissionAwareRepository(FakeTransactionalWriteRepository):
    """Answers like `private.user_can_write_batch` for the actor's farm role."""

    def __init__(self, farm_role: str):
        super().__init__()
        self.farm_role = farm_role

    def _deny_unless_writer(self):
        if self.farm_role not in {"owner", "editor"}:
            raise ActivityWritePermissionError()

    def create(self, **payload):
        self._deny_unless_writer()
        return super().create(**payload)

    def update(self, **kwargs):
        self._deny_unless_writer()
        return super().update(**kwargs)

    def soft_delete(self, **kwargs):
        self._deny_unless_writer()
        return super().soft_delete(**kwargs)


def reader(farm_role: str) -> FakeRead:
    read = FakeRead()
    read.me = lambda: {"user_id": ACTOR, "roles": ["farmer", farm_role]}
    return read


def seeded(farm_role_now: str):
    """An activity the actor recorded while still a writer, then a role change."""
    repo = PermissionAwareRepository("owner")
    row, _ = repo.create(
        crop_season_id=SEASON, production_batch_id="batch-a-0", actor_id=ACTOR,
        idempotency_key="00000000-0000-0000-0000-00000000000a", activity_type="irrigation",
        occurred_at=datetime(2026, 9, 10, tzinfo=timezone.utc), note=None, data={"method": "awd"},
    )
    repo.farm_role = farm_role_now
    return repo, row["id"]


# -- service ------------------------------------------------------------------

@pytest.mark.parametrize("farm_role", ["owner", "editor"])
def test_owner_and_editor_can_create_update_and_delete(farm_role):
    repo = PermissionAwareRepository(farm_role)
    write = ActivityWriteService(repo)
    read = reader(farm_role)
    created = write.create(read_repository=read, crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}))
    updated = write.update(read_repository=read, activity_id=created["id"], request=schemas.ActivityUpdateRequest(note="ok"))
    assert updated["note"] == "ok"
    write.delete(read_repository=read, activity_id=created["id"])
    assert repo.rows[created["id"]]["deleted"] is True


def test_viewer_cannot_create():
    repo = PermissionAwareRepository("viewer")
    with pytest.raises(ActivityWriteAccessError):
        ActivityWriteService(repo).create(
            read_repository=reader("viewer"), crop_season_id=SEASON, request=request("irrigation", {"method": "awd"}),
        )
    assert repo.rows == {}


def test_viewer_cannot_update_even_their_own_earlier_activity():
    repo, activity_id = seeded("viewer")
    with pytest.raises(ActivityWriteAccessError):
        ActivityWriteService(repo).update(
            read_repository=reader("viewer"), activity_id=activity_id,
            request=schemas.ActivityUpdateRequest(note="changed"),
        )
    assert repo.rows[activity_id]["note"] is None


def test_viewer_cannot_complete_an_unattributed_record():
    repo = PermissionAwareRepository("viewer")
    repo.rows["seeded"] = {
        "id": "seeded", "crop_season_id": SEASON, "activity_type": "irrigation",
        "occurred_at": datetime(2026, 9, 8, tzinfo=timezone.utc), "note": None, "data": {"method": "awd"},
        "created_by": None, "created_at": datetime(2026, 9, 8, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 8, tzinfo=timezone.utc), "deleted": False,
    }
    with pytest.raises(ActivityWriteAccessError):
        ActivityWriteService(repo).update(
            read_repository=reader("viewer"), activity_id="seeded",
            request=schemas.ActivityUpdateRequest(note="changed"),
        )
    assert repo.rows["seeded"]["note"] is None


def test_viewer_cannot_delete_even_their_own_earlier_activity():
    repo, activity_id = seeded("viewer")
    with pytest.raises(ActivityWriteAccessError):
        ActivityWriteService(repo).delete(read_repository=reader("viewer"), activity_id=activity_id)
    assert repo.rows[activity_id]["deleted"] is False


# -- HTTP contract ------------------------------------------------------------

def test_viewer_write_routes_return_the_normalized_404_envelope():
    repo, activity_id = seeded("viewer")
    client = write_client(read=reader("viewer"), write=ActivityWriteService(repo))
    responses = [
        client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body(key="00000000-0000-0000-0000-0000000000b1")),
        client.patch(f"/v1/activities/{activity_id}", json={"note": "changed"}),
        client.delete(f"/v1/activities/{activity_id}"),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": {"error": {
            "code": "not_found", "message": "Activity not found or outside your scope.",
        }}}
    assert repo.rows[activity_id]["deleted"] is False and repo.rows[activity_id]["note"] is None


@pytest.mark.parametrize("farm_role", ["owner", "editor"])
def test_owner_and_editor_write_routes_succeed(farm_role):
    repo = PermissionAwareRepository(farm_role)
    client = write_client(read=reader(farm_role), write=ActivityWriteService(repo))
    created = client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body())
    assert created.status_code == 201
    activity_id = created.json()["id"]
    assert client.patch(f"/v1/activities/{activity_id}", json={"note": "ok"}).status_code == 200
    assert client.delete(f"/v1/activities/{activity_id}").status_code == 204


@pytest.mark.parametrize(("method", "path"), [
    ("patch", "/v1/activities/activity-1"),
    ("delete", "/v1/activities/activity-1"),
])
def test_patch_and_delete_require_bearer_authentication(method, path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import api

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._activity_write_service] = lambda: ActivityWriteService(PermissionAwareRepository("owner"))
    kwargs = {"json": {"note": "x"}} if method == "patch" else {}
    response = getattr(TestClient(app), method)(path, **kwargs)
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


# -- real repository, scripted cursor -----------------------------------------

class ScriptedCursor:
    """Records statements; answers the few reads the repository makes."""

    def __init__(self, *, allowed: bool, activity: dict | None = None):
        self.allowed = allowed
        self.activity = activity
        self.statements: list[tuple[str, list]] = []
        self._next = None
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), list(params or [])))
        text = sql.lower()
        if "user_can_write_batch" in text:
            # The same query also reports the season/batch state it locked.
            self._next = {"allowed": self.allowed, "season_status": "active", "season_live": True, "batch_status": "planned"}
        elif "select production_batch_id" in text:
            self._next = {"production_batch_id": "batch-1"} if self.activity else None
        elif "from public.activities a" in text:
            self._next = self.activity
        elif "from public.irrigation_events" in text:
            self._next = {"method": "awd"}
        else:
            self._next = None

    def fetchone(self):
        return self._next


def repository_with(cursor: ScriptedCursor) -> PostgresActivityWriteRepository:
    connection = type("Conn", (), {"cursor": lambda self: nullcontext(cursor)})()
    return PostgresActivityWriteRepository(settings=None, connect=lambda: nullcontext(connection))


def mutating(cursor: ScriptedCursor) -> list[str]:
    return [sql for sql, _ in cursor.statements if sql.lower().startswith(("insert", "update"))]


def test_repository_create_checks_write_permission_before_any_read_or_write():
    cursor = ScriptedCursor(allowed=False)
    with pytest.raises(ActivityWritePermissionError):
        repository_with(cursor).create(
            crop_season_id=SEASON, production_batch_id="batch-1", actor_id="user-1",
            idempotency_key="k", activity_type="irrigation",
            occurred_at=datetime(2026, 9, 10, tzinfo=timezone.utc), note=None, data={"method": "awd"},
        )
    sqls = [sql for sql, _ in cursor.statements]
    assert "set_config('request.jwt.claims'" in sqls[0]
    assert json.loads(cursor.statements[0][1][0]) == {"sub": "user-1", "role": "authenticated"}
    assert "private.user_can_write_batch" in sqls[1] and cursor.statements[1][1] == ["batch-1"]
    assert "set_config('request.jwt.claims', ''" in sqls[2]  # claim cleared again
    assert len(sqls) == 3 and mutating(cursor) == []


_OWN_ACTIVITY = {
    "id": "act-1", "crop_season_id": SEASON, "activity_type": "irrigation",
    "occurred_at": datetime(2026, 9, 10, tzinfo=timezone.utc), "note": None, "created_by": "user-1",
    "created_at": datetime(2026, 9, 10, tzinfo=timezone.utc), "updated_at": datetime(2026, 9, 10, tzinfo=timezone.utc),
}


def test_repository_update_is_denied_without_writing():
    cursor = ScriptedCursor(allowed=False, activity=_OWN_ACTIVITY)
    with pytest.raises(ActivityWritePermissionError):
        repository_with(cursor).update(
            activity_id="act-1", actor_id="user-1", occurred_at=None, note="x", update_note=True, data=None,
        )
    assert mutating(cursor) == []


def test_repository_soft_delete_is_denied_without_writing():
    cursor = ScriptedCursor(allowed=False, activity=_OWN_ACTIVITY)
    with pytest.raises(ActivityWritePermissionError):
        repository_with(cursor).soft_delete(activity_id="act-1", actor_id="user-1")
    assert mutating(cursor) == []


def test_repository_permission_error_is_still_a_not_found_for_existing_callers():
    assert issubclass(ActivityWritePermissionError, ActivityNotFoundError)


def test_repository_allowed_writer_proceeds_to_the_update():
    cursor = ScriptedCursor(allowed=True, activity=_OWN_ACTIVITY)
    repository_with(cursor).update(
        activity_id="act-1", actor_id="user-1", occurred_at=None, note="x", update_note=True, data=None,
    )
    writes = mutating(cursor)
    assert len(writes) == 1 and writes[0].startswith("update public.activities set occurred_at")


def _base_view_sql(cursor: ScriptedCursor) -> str:
    return next(sql for sql, _ in cursor.statements if "from public.activities a" in sql.lower())


def test_repository_update_accepts_unattributed_rows_like_the_update_policy():
    """`activities_update` WITH CHECK allows `recorded_by is null`; the service
    must not be stricter, or a seeded record can never be completed."""
    cursor = ScriptedCursor(allowed=True, activity={**_OWN_ACTIVITY, "created_by": None})
    repository_with(cursor).update(
        activity_id="act-1", actor_id="user-1", occurred_at=None, note="x", update_note=True, data=None,
    )
    assert "(a.recorded_by = %s or a.recorded_by is null)" in _base_view_sql(cursor)


def test_repository_soft_delete_stays_own_only():
    cursor = ScriptedCursor(allowed=True, activity=_OWN_ACTIVITY)
    repository_with(cursor).soft_delete(activity_id="act-1", actor_id="user-1")
    assert "recorded_by is null" not in _base_view_sql(cursor)
    delete_sql = next(sql for sql in mutating(cursor) if "deleted_at=now()" in sql)
    assert "recorded_by=%s" in delete_sql and "recorded_by is null" not in delete_sql


def test_repository_update_writes_every_detail_column_and_fails_when_no_detail_row():
    cursor = ScriptedCursor(allowed=True, activity=_OWN_ACTIVITY)
    data = {"method": "awd", "water_volume_m3": 3, "duration_minutes": None,
            "water_level_cm": None, "pump_energy_kwh": None, "total_cost_vnd": None}
    repository_with(cursor).update(
        activity_id="act-1", actor_id="user-1", occurred_at=None, note=None, update_note=False, data=data,
    )
    detail_sql, params = next((sql, p) for sql, p in cursor.statements if sql.startswith("update public.irrigation_events"))
    assert params == [*data.values(), "act-1"]

    cursor = ScriptedCursor(allowed=True, activity=_OWN_ACTIVITY)
    cursor.rowcount = 0  # detail row missing: the write did not land
    with pytest.raises(ActivityNotFoundError):
        repository_with(cursor).update(
            activity_id="act-1", actor_id="user-1", occurred_at=None, note=None, update_note=False, data=data,
        )
