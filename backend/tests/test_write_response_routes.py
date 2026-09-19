"""P1-A: a success representation that cannot be produced must not follow a commit.

Route- and service-level companions to `test_write_response_atomicity.py` (which
proves the rollback on real Postgres). Each forces the response to be invalid
AFTER the write itself succeeded and checks two things: the client gets a
controlled error, and nothing was persisted (or the side effect was undone).
Before P1-A the write committed first and FastAPI rejected the response after.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from infrastructure.repository import InMemoryCarbonRepository  # noqa: E402
from service import ActivityWriteService, CarbonService  # noqa: E402
from tests.test_activity_writes import (  # noqa: E402
    SEASON, FakeRead, FakeTransactionalWriteRepository, _seed_straw, request_body,
)
from tests.test_carbon_persist_authorization import Readers, Writers  # noqa: E402
from tests.test_mrv_export import CASE, FakeCarbon, FakeExportStore, FakeRead as MrvRead  # noqa: E402
from service import MrvExportService  # noqa: E402


def _broken_response(monkeypatch):
    """The written row is fine; its API representation is not."""
    real = ActivityWriteService._response
    monkeypatch.setattr(ActivityWriteService, "_response",
                        staticmethod(lambda row, replay=False: {**real(row, replay=replay), "activity_type": "not-a-type"}))


def _activity_client(repo):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: FakeRead()
    app.dependency_overrides[api._activity_write_service] = lambda: ActivityWriteService(repo)
    return TestClient(app, raise_server_exceptions=False)


def test_activity_patch_with_an_unrepresentable_result_saves_nothing(monkeypatch):
    repo = FakeTransactionalWriteRepository()
    activity_id = _seed_straw(repo)
    _broken_response(monkeypatch)
    response = _activity_client(repo).patch(f"/v1/activities/{activity_id}", json={"data": {"days_before_cultivation": 20}})
    assert response.status_code == 500
    assert repo.rows[activity_id]["data"]["days_before_cultivation"] is None  # rolled back, not "500 but saved"


def test_activity_post_with_an_unrepresentable_result_creates_nothing_and_a_retry_succeeds(monkeypatch):
    repo = FakeTransactionalWriteRepository()
    client = _activity_client(repo)
    _broken_response(monkeypatch)
    assert client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body()).status_code == 500
    assert repo.rows == {} and repo.keys == {}
    monkeypatch.undo()
    # The same idempotency key is still free: the retry creates exactly one row.
    retry = client.post(f"/v1/crop-seasons/{SEASON}/activities", json=request_body())
    assert retry.status_code == 201 and retry.json()["idempotent_replay"] is False
    assert len(repo.rows) == 1


# -- Carbon ------------------------------------------------------------------------

def _carbon_service():
    from tests.test_carbon_real_factors import REAL, _bundle_without_fuel, _repository
    repo = _repository(_bundle_without_fuel("irrigated_multiple_drainage"))
    return CarbonService(repo, REAL), repo


def test_carbon_prepare_runs_before_anything_is_saved():
    service, repo = _carbon_service()
    from tests.fixtures import supabase_rows as rows

    def reject(result):
        assert repo.calculations == []  # nothing written yet when the payload is built
        raise ValueError("unrepresentable")

    with pytest.raises(ValueError):
        service.calculate(rows.CROP_ID, "as_recorded", prepare=reject)
    assert repo.calculations == [] and repo.breakdowns == {}


def test_carbon_route_refuses_a_non_json_result_without_saving(monkeypatch):
    service, repo = _carbon_service()
    from tests.fixtures import supabase_rows as rows

    monkeypatch.setattr(api, "_payload", lambda result, calculation_id: {"total_co2e_kg": float("nan"), "calculation_id": calculation_id})
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: service
    app.dependency_overrides[api._access_checker] = lambda: Readers({rows.CROP_ID})
    app.dependency_overrides[api._persist_checker] = lambda: Writers({rows.CROP_ID})
    client = TestClient(app, raise_server_exceptions=False, headers={"Authorization": "Bearer jwt"})
    response = client.post("/v1/carbon/calculate", json={"crop_season_id": rows.CROP_ID, "water_regime_scenario": "as_recorded"})
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "internal_error"  # controlled envelope, no raw value
    assert repo.calculations == []


def test_carbon_route_success_returns_the_prebuilt_payload_with_the_new_id():
    service, repo = _carbon_service()
    from tests.fixtures import supabase_rows as rows

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: service
    app.dependency_overrides[api._access_checker] = lambda: Readers({rows.CROP_ID})
    app.dependency_overrides[api._persist_checker] = lambda: Writers({rows.CROP_ID})
    body = TestClient(app, headers={"Authorization": "Bearer jwt"}).post(
        "/v1/carbon/calculate", json={"crop_season_id": rows.CROP_ID, "water_regime_scenario": "as_recorded"},
    ).json()
    assert body["calculation_id"] == repo.calculations[0]["id"]
    assert body["co2e_total_kg"] == body["total_co2e_kg"] > 0


def test_carbon_breakdown_failure_does_not_leave_a_succeeded_calculation_behind():
    """PostgREST repository: two requests, so a failed breakdown insert must
    delete the calculation it just inserted (breakdowns cascade)."""
    from infrastructure.supabase_repo import SupabaseCarbonRepository

    calls: list[tuple] = []

    class Query:
        def __init__(self, table):
            self.table = table

        def insert(self, rows):
            calls.append(("insert", self.table))
            if self.table == "carbon_breakdowns":
                self._fail = True
            self._rows = rows
            return self

        def delete(self):
            calls.append(("delete", self.table))
            return self

        def eq(self, column, value):
            calls.append(("eq", self.table, column, value))
            return self

        def execute(self):
            if getattr(self, "_fail", False):
                raise RuntimeError("breakdown insert failed")
            return type("R", (), {"data": [{"id": "calc-new"}]})()

    client = type("Client", (), {"table": lambda self, name: Query(name)})()
    repo = SupabaseCarbonRepository(settings=None, client=client)
    with pytest.raises(RuntimeError):
        repo.save_calculation({"crop_season_id": "s"}, [{"category": "x"}])
    assert ("delete", "carbon_calculations") in calls
    assert ("eq", "carbon_calculations", "id", "calc-new") in calls


# -- MRV -----------------------------------------------------------------------

def test_mrv_render_with_an_unrepresentable_result_leaves_no_row_and_no_object(monkeypatch):
    store = FakeExportStore()
    service, repo = MrvExportService(store, FakeCarbon()), MrvRead()
    snapshot = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")
    rows_before = set(store.rows)
    real_view = MrvExportService._export_view
    monkeypatch.setattr(MrvExportService, "_export_view",
                        staticmethod(lambda row: {**real_view(row), "is_finalized": "not-a-bool"}))
    with pytest.raises(Exception):
        service.render(read_repository=repo, export_id=snapshot["export_id"], fmt="xlsx")
    assert set(store.rows) == rows_before, "the rendered row must not be stored"
    assert store.objects == {}, "the uploaded object must be removed"


def test_mrv_json_snapshot_with_an_unrepresentable_result_is_not_stored(monkeypatch):
    store = FakeExportStore()
    service, repo = MrvExportService(store, FakeCarbon()), MrvRead()
    real_view = MrvExportService._export_view
    monkeypatch.setattr(MrvExportService, "_export_view",
                        staticmethod(lambda row: {**real_view(row), "is_finalized": "not-a-bool"}))
    with pytest.raises(Exception):
        service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")
    assert store.rows == {}


def test_success_payload_output_survives_the_routes_own_revalidation():
    body = schemas.success_payload(schemas.RecommendationResponse, {
        "id": "r", "crop_season_id": "s", "rule_code": "c", "rule_version": "1", "type": "data_task",
        "status": "generated", "title": "t", "reason": "r", "impact_status": "unavailable",
        "generated_at": "2026-09-20T00:00:00+00:00", "co2e_total_kg_before": None,
    })
    assert isinstance(body["generated_at"], str)
    assert schemas.RecommendationResponse.model_validate(body).model_dump(mode="json") == body
