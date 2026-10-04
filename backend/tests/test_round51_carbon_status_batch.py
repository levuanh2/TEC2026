"""Round 5.1: `GET /v1/organizations/{id}/carbon-status` — one request, many seasons.

Management used to ask for readiness and the actual result once PER SEASON.
The batch endpoint must be the same answers, fewer requests:

* `items[id].readiness` equals `GET /v1/crop-seasons/{id}/carbon/readiness`;
  `items[id].actual` equals `GET /v1/crop-seasons/{id}/carbon` (null where that
  route answers 404 `no_calculation`) — for 1, 6 and 30 seasons.
* Scope is the caller's RLS scope of the organization; an id outside it is
  never answered, even when asked for by name; an invisible organization 404s.
* One season failing is reported on that season only.

TEST FACTORS only; every number comes from the engine.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from carbon import ParameterSet  # noqa: E402
from infrastructure.api_errors import error_detail  # noqa: E402
from infrastructure.auth import MissingAuthError, extract_bearer_token  # noqa: E402
from infrastructure.mapping import RawCropBundle  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from infrastructure.repository import InMemoryCarbonRepository  # noqa: E402
from service import CarbonService  # noqa: E402
from tests.fixtures import supabase_rows as rows  # noqa: E402
from tests.test_integration_supabase import FakeCropAccessChecker, FakeCropPersistChecker  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FACTOR_VERSION = "TEST-FACTORS-DO-NOT-USE"
ORG = "00000000-0000-0000-0000-00000000a001"
FOREIGN_SEASON = "00000000-0000-0000-0000-00000000f00f"


def _season_id(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def _bundle(season_id: str, variant: int) -> RawCropBundle:
    """Seasons that differ the way real ones do: complete, missing harvest,
    missing fertilizer, missing water regime."""
    crop = {**rows.crop_season(), "id": season_id}
    activities = copy.deepcopy(rows.activities())
    if variant % 4 == 1:
        activities = [a for a in activities if a["activity_type"] != "harvest"]
    elif variant % 4 == 2:
        activities = [a for a in activities if a["activity_type"] != "fertilizer"]
    elif variant % 4 == 3:
        crop["ipcc_water_regime"] = None
    return RawCropBundle(
        crop_season=crop, plot=rows.plot(), farm={"id": rows.FARM_ID, "name": "Hộ demo"},
        production_batches=rows.production_batches(1), activities=activities,
    )


class OrgReadRepo:
    def __init__(self, seasons: list[str]):
        self.seasons = seasons

    def organization_season_ids(self, organization_id: str) -> list[str]:
        if organization_id != ORG:
            raise ReadNotFoundError("organizations")
        return list(self.seasons)


class CountingRepo(InMemoryCarbonRepository):
    """Batch-capable repository; counts how often each read is issued."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls: dict[str, int] = {}

    def _count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def get_crop_bundles(self, ids):
        self._count("get_crop_bundles")
        out = {}
        for sid in ids:
            try:
                out[sid] = InMemoryCarbonRepository.get_crop_bundle(self, sid)
            except Exception as exc:  # noqa: BLE001
                out[sid] = exc
        return out

    def latest_calculations(self, ids, scenario=None):
        self._count("latest_calculations")
        return {sid: InMemoryCarbonRepository.latest_calculation(self, sid, scenario) for sid in ids}


def _read_repo_like_main(repo: OrgReadRepo):
    """Production's `_read_repo`: no bearer token -> 401 `unauthenticated`."""
    def dependency(authorization: str | None = Header(default=None)) -> OrgReadRepo:
        try:
            extract_bearer_token(authorization)
        except MissingAuthError as exc:
            raise HTTPException(status_code=401, detail=error_detail("unauthenticated", str(exc))) from exc
        return repo
    return dependency


def _setup(n: int, *, calculated_every: int = 2, batch_repo: bool = True):
    params = ParameterSet.load(FIXTURES / "test_factors.yaml")
    ids = [_season_id(i) for i in range(1, n + 1)]
    kind = CountingRepo if batch_repo else InMemoryCarbonRepository
    repo = kind(
        bundles={sid: _bundle(sid, i) for i, sid in enumerate(ids)},
        factor_sets={FACTOR_VERSION: rows.FACTOR_SET_ID},
        factors={rows.FACTOR_SET_ID: {"ch4_rice.efc": "ef-efc", "fuel.diesel": "ef-diesel"}},
    )
    service = CarbonService(repo, params)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: service
    app.dependency_overrides[api._access_checker] = lambda: FakeCropAccessChecker()
    app.dependency_overrides[api._persist_checker] = lambda: FakeCropPersistChecker()
    app.dependency_overrides[api._read_repo] = _read_repo_like_main(OrgReadRepo(ids))
    client = TestClient(app, headers={"Authorization": "Bearer test-fake-jwt"})
    for i, sid in enumerate(ids):
        if i % calculated_every == 0:
            for scenario in ("as_recorded", "awd"):
                client.post("/v1/carbon/calculate", json={"crop_season_id": sid, "water_regime_scenario": scenario})
    if batch_repo:
        repo.calls.clear()
    return client, repo, ids


def _single(client: TestClient, sid: str) -> tuple[dict, dict | None]:
    readiness = client.get(f"/v1/crop-seasons/{sid}/carbon/readiness")
    assert readiness.status_code == 200, readiness.text
    actual = client.get(f"/v1/crop-seasons/{sid}/carbon")
    if actual.status_code == 404:
        assert actual.json()["detail"]["error"]["code"] == "no_calculation"
        return readiness.json(), None
    assert actual.status_code == 200, actual.text
    return readiness.json(), actual.json()


def _batch(client: TestClient, *season_ids: str) -> dict:
    response = client.get(f"/v1/organizations/{ORG}/carbon-status", params={"crop_season_id": list(season_ids)} if season_ids else None)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("n", [1, 6, 30])
@pytest.mark.parametrize("batch_repo", [True, False])
def test_every_batch_item_equals_the_per_season_endpoints(n, batch_repo):
    client, repo, ids = _setup(n, batch_repo=batch_repo)
    body = _batch(client)
    assert body["organization_id"] == ORG
    assert [item["crop_season_id"] for item in body["items"]] == ids
    for item in body["items"]:
        readiness, actual = _single(client, item["crop_season_id"])
        assert item["readiness"] == readiness and item["readiness_error"] is None
        assert item["actual"] == actual and item["actual_error"] is None
    # Actual only: a scenario stored later never shows up as the season's result.
    assert all(item["actual"] is None or item["actual"]["calculation_kind"] == "actual" for item in body["items"])
    assert any(item["actual"] for item in body["items"])
    assert any(not item["readiness"]["can_calculate"] for item in body["items"]) or n == 1


@pytest.mark.parametrize("n", [1, 6, 30])
def test_reads_do_not_grow_with_the_number_of_seasons(n):
    client, repo, _ = _setup(n)
    _batch(client)
    assert repo.calls == {"get_crop_bundles": 1, "latest_calculations": 1}


def test_a_season_outside_the_callers_scope_is_never_answered():
    client, repo, ids = _setup(6)
    body = _batch(client, ids[0], FOREIGN_SEASON)
    assert [item["crop_season_id"] for item in body["items"]] == [ids[0]]


def test_an_organization_the_caller_cannot_read_is_404():
    client, _, _ = _setup(2)
    response = client.get("/v1/organizations/00000000-0000-0000-0000-00000000dead/carbon-status")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "not_found"


def test_one_failing_season_leaves_the_others_intact():
    client, repo, ids = _setup(6)
    before = _batch(client)
    del repo.bundles[ids[2]]  # this season now fails to load
    after = _batch(client)
    for b, a in zip(before["items"], after["items"]):
        if a["crop_season_id"] == ids[2]:
            assert a["readiness"] is None and a["readiness_error"]["code"] == "crop_not_found"
        else:
            assert a == b


def test_unauthenticated_is_401():
    client, _, _ = _setup(1)
    response = client.get(f"/v1/organizations/{ORG}/carbon-status", headers={"Authorization": ""})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"
