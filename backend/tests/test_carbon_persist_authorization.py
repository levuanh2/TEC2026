"""B4: persisting a Carbon calculation needs write authority on the crop.

Product decision (P1 sprint): `private.user_can_write_crop` — farm owner/editor or
active cooperative manager. Reading the season is enough to VIEW results; the
Recommendation what-if path (`persist=False`) never writes. No emission factor or
GWP is touched here: the gate runs before the engine, and the engine is stubbed
where a calculation has to "happen".
"""
from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import service as service_module  # noqa: E402
from infrastructure.auth import CropAccessError  # noqa: E402
from infrastructure.persist_access import PostgresCropPersistChecker  # noqa: E402
from service import CalculationOutcome, CarbonService  # noqa: E402

SEASON = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


class Readers:
    """RLS read gate: which seasons the caller can read."""

    def __init__(self, readable: set[str]):
        self.readable = readable

    def assert_can_access(self, token, crop_season_id):
        if crop_season_id not in self.readable:
            raise CropAccessError("not readable")


class Writers:
    """`private.user_can_write_crop` stand-in."""

    def __init__(self, writable: set[str]):
        self.writable, self.calls = writable, []

    def assert_can_persist(self, token, crop_season_id):
        self.calls.append(crop_season_id)
        if crop_season_id not in self.writable:
            raise CropAccessError("not writable")


class RecordingCarbon:
    def __init__(self):
        self.calculated: list[str] = []

    def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True, prepare=None):
        self.calculated.append(crop_season_id)
        result = SimpleNamespace(
            to_dict=lambda: {"scenario": scenario, "total_co2e_kg": 1.0},
            ef_config_version="test", engine_version="test",
        )
        prepared = prepare(result) if prepare is not None else None
        return CalculationOutcome(result=result, calculation_id="calc-1", persisted=persist, prepared=prepared)

    def latest(self, crop_season_id, scenario=None):
        return {"id": "calc-1", "crop_season_id": crop_season_id, "status": "succeeded"}


def client_for(*, readable: set[str], writable: set[str], carbon=None, auth=True):
    carbon = carbon or RecordingCarbon()
    writers = Writers(writable)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: carbon
    app.dependency_overrides[api._access_checker] = lambda: Readers(readable)
    app.dependency_overrides[api._persist_checker] = lambda: writers
    headers = {"Authorization": "Bearer jwt"} if auth else {}
    return TestClient(app, headers=headers), carbon, writers


def post(client, season=SEASON):
    return client.post("/v1/carbon/calculate", json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})


def test_writer_may_persist_a_calculation():
    client, carbon, writers = client_for(readable={SEASON}, writable={SEASON})
    response = post(client)
    assert response.status_code == 200
    assert response.json()["calculation_id"] == "calc-1"
    assert carbon.calculated == [SEASON] and writers.calls == [SEASON]


def test_read_only_user_can_view_but_not_persist():
    client, carbon, _ = client_for(readable={SEASON}, writable=set())
    assert client.get(f"/v1/crop-seasons/{SEASON}/carbon").status_code == 200
    response = post(client)
    assert response.status_code == 404
    assert response.json() == {"detail": {"error": {"code": "crop_not_found", "message": response.json()["detail"]["error"]["message"]}}}
    assert carbon.calculated == []  # the engine never ran, nothing was persisted


def test_cross_scope_is_denied_before_the_write_check():
    client, carbon, writers = client_for(readable={SEASON}, writable={SEASON, OTHER})
    response = post(client, OTHER)
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "crop_not_found"
    assert writers.calls == [] and carbon.calculated == []


def test_unauthenticated_is_401_before_any_check():
    client, carbon, writers = client_for(readable={SEASON}, writable={SEASON}, auth=False)
    response = post(client)
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "missing_authorization"
    assert writers.calls == [] and carbon.calculated == []


def test_unconfigured_persist_checker_fails_closed():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = RecordingCarbon
    app.dependency_overrides[api._access_checker] = lambda: Readers({SEASON})
    response = post(TestClient(app, headers={"Authorization": "Bearer jwt"}))
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "auth_not_configured"


def test_recommendation_simulation_never_persists(monkeypatch):
    class NoWriteRepository:
        def get_crop_bundle(self, crop_season_id):
            return object()

        def resolve_factor_set_id(self, version):
            raise AssertionError("persist=False must not resolve a factor set")

        def factor_ids_by_code(self, factor_set_id):
            raise AssertionError("persist=False must not read factor ids")

        def save_calculation(self, calculation, breakdowns):
            raise AssertionError("persist=False must not write carbon_calculations")

    monkeypatch.setattr(service_module, "map_crop_activity_data", lambda bundle: object())
    monkeypatch.setattr(service_module, "calculate_carbon", lambda data, scenario, params: SimpleNamespace(scenario=scenario))
    outcome = CarbonService(NoWriteRepository(), parameters=None).calculate(SEASON, "awd", persist=False)
    assert outcome.persisted is False and outcome.calculation_id is None


# -- real checker, scripted cursor --------------------------------------------

class ScriptedCursor:
    def __init__(self, allowed: bool):
        self.allowed, self.statements = allowed, []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), list(params or [])))

    def fetchone(self):
        return {"allowed": self.allowed}


def checker_with(cursor, user_id="user-1"):
    connection = type("Conn", (), {"cursor": lambda self: nullcontext(cursor)})()
    return PostgresCropPersistChecker(settings=None, user_id_for=lambda token: user_id, connect=lambda: nullcontext(connection))


def test_checker_evaluates_the_canonical_write_helper_as_the_verified_user():
    cursor = ScriptedCursor(allowed=True)
    checker_with(cursor).assert_can_persist("jwt", SEASON)
    sqls = [sql for sql, _ in cursor.statements]
    assert "set_config('request.jwt.claims'" in sqls[0]
    assert json.loads(cursor.statements[0][1][0]) == {"sub": "user-1", "role": "authenticated"}
    assert "private.user_can_write_crop" in sqls[1] and cursor.statements[1][1] == [SEASON]
    assert "set_config('request.jwt.claims', ''" in sqls[2]


def test_checker_denies_when_the_helper_says_no():
    with pytest.raises(CropAccessError):
        checker_with(ScriptedCursor(allowed=False)).assert_can_persist("jwt", SEASON)


@pytest.mark.parametrize("season", ["not-a-uuid", ""])
def test_checker_rejects_non_uuid_without_touching_the_database(season):
    cursor = ScriptedCursor(allowed=True)
    with pytest.raises(CropAccessError):
        checker_with(cursor).assert_can_persist("jwt", season)
    assert cursor.statements == []


def test_checker_denies_an_unresolvable_user():
    cursor = ScriptedCursor(allowed=True)
    with pytest.raises(CropAccessError):
        checker_with(cursor, user_id=None).assert_can_persist("jwt", SEASON)
    assert cursor.statements == []
