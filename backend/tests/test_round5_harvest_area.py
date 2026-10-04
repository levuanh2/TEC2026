"""Round 5 — `harvested_area_ha` may equal the plot area but never exceed it.

Enforced by the API (every client goes through it), not only by the form.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from service import ActivityWriteService  # noqa: E402
from tests.test_activity_writes import SEASON, FakeRead, FakeTransactionalWriteRepository  # noqa: E402

PLOT_AREA = 1.25


class PlotRead(FakeRead):
    def __init__(self, area=PLOT_AREA, **kw):
        super().__init__(**kw)
        self.area = area

    def season(self, season_id):
        return {**super().season(season_id), "plot_id": "plot-a"}

    def plot(self, plot_id):
        return {"id": plot_id, "area_ha": self.area}


def _client(read):
    writes = FakeTransactionalWriteRepository()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: read
    app.dependency_overrides[api._activity_write_service] = lambda: ActivityWriteService(writes)
    return TestClient(app, headers={"Authorization": "Bearer t"}), writes


def _harvest(client, area):
    return client.post(f"/v1/crop-seasons/{SEASON}/activities", json={
        "activity_type": "harvest", "occurred_at": "2026-09-20T00:00:00+07:00",
        "idempotency_key": str(uuid4()), "data": {"yield_kg": 6000, "harvested_area_ha": area},
    })


def test_harvest_larger_than_plot_is_refused_with_a_field_error():
    client, writes = _client(PlotRead())
    response = _harvest(client, 1.3)
    assert response.status_code == 422
    error = response.json()["detail"]["error"]
    assert error["code"] == "harvested_area_exceeds_plot"
    assert error["field"] == "harvested_area_ha"
    assert error["plot_area_ha"] == PLOT_AREA
    assert "diện tích thửa" in error["message"]
    assert writes.rows == {}  # nothing stored


@pytest.mark.parametrize("area", [PLOT_AREA, 1.0, 0.5])
def test_harvest_up_to_the_plot_area_is_accepted(area):
    client, _ = _client(PlotRead())
    assert _harvest(client, area).status_code == 201


def test_edit_cannot_raise_the_area_above_the_plot():
    client, writes = _client(PlotRead())
    created = _harvest(client, 1.0).json()
    response = client.patch(f"/v1/activities/{created['id']}", json={"data": {"harvested_area_ha": 2.0}})
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "harvested_area_exceeds_plot"
    assert writes.rows[created["id"]]["data"]["harvested_area_ha"] == 1.0


def test_plot_without_a_recorded_area_applies_no_bound():
    client, _ = _client(PlotRead(area=None))
    assert _harvest(client, 3.0).status_code == 201
