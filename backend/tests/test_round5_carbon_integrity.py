"""Round 5 — Carbon integrity: actual vs scenario, stored provenance, input fingerprint.

Three invariants, each observed broken on staging before this round:

1. A simulated scenario (AWD, continuous flooding) calculated AFTER the actual
   (`as_recorded`) result must never replace it in the default read.
2. A stored calculation read back must carry the same vocabulary as the POST
   response: engine `source` per breakdown line (not `undefined`), the factor-set
   version (not blank), `as_recorded` (not the DB enum `actual`), and which kind
   of result it is.
3. Readiness exposes the fingerprint (`input_hash`) the engine would store for
   an actual calculation now. Cost/note edits leave it unchanged; edits to a
   Carbon input change it; recalculating makes the stored hash match again.

TEST FACTORS only (numbers are made up) — see test_integration_supabase.py.
No formula, factor or GWP is touched here: every number comes from the engine.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from carbon import ParameterSet  # noqa: E402
from infrastructure.mapping import CATEGORY_TO_SOURCE, RawCropBundle, stored_calculation_view  # noqa: E402
from infrastructure.repository import InMemoryCarbonRepository  # noqa: E402
from service import CarbonService  # noqa: E402
from tests.fixtures import supabase_rows as rows  # noqa: E402
from tests.test_integration_supabase import FakeCropAccessChecker, FakeCropPersistChecker  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FACTOR_VERSION = "TEST-FACTORS-DO-NOT-USE"


@pytest.fixture
def params() -> ParameterSet:
    return ParameterSet.load(FIXTURES / "test_factors.yaml")


@pytest.fixture
def bundle() -> RawCropBundle:
    return RawCropBundle(
        crop_season=rows.crop_season(),
        plot=rows.plot(),
        farm={"id": rows.FARM_ID, "name": "Hộ demo"},
        production_batches=rows.production_batches(1),
        activities=copy.deepcopy(rows.activities()),
    )


@pytest.fixture
def repo(bundle) -> InMemoryCarbonRepository:
    return InMemoryCarbonRepository(
        bundles={rows.CROP_ID: bundle},
        factor_sets={FACTOR_VERSION: rows.FACTOR_SET_ID},
        factors={rows.FACTOR_SET_ID: {"ch4_rice.efc": "ef-efc", "fuel.diesel": "ef-diesel"}},
    )


@pytest.fixture
def service(repo, params) -> CarbonService:
    return CarbonService(repo, params)


@pytest.fixture
def client(service) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: service
    app.dependency_overrides[api._access_checker] = lambda: FakeCropAccessChecker()
    app.dependency_overrides[api._persist_checker] = lambda: FakeCropPersistChecker()
    return TestClient(app, headers={"Authorization": "Bearer test-fake-jwt"})


def _calc(client: TestClient, scenario: str) -> dict:
    response = client.post(
        "/v1/carbon/calculate", json={"crop_season_id": rows.CROP_ID, "water_regime_scenario": scenario}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get(client: TestClient, query: str = "") -> dict:
    response = client.get(f"/v1/crop-seasons/{rows.CROP_ID}/carbon{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _activity(bundle: RawCropBundle, activity_type: str) -> dict:
    return next(a for a in bundle.activities if a["activity_type"] == activity_type)


# -- 1. actual vs scenario --------------------------------------------------


def test_scenario_calculated_later_never_replaces_the_actual_result(client, repo):
    actual = _calc(client, "as_recorded")
    before = _get(client)
    _calc(client, "awd")
    flooding = _calc(client, "continuous_flooding")
    # Scenarios are stored strictly later than the actual result.
    for row in repo.calculations:
        if row["scenario"] != "actual":
            row["calculated_at"] = "2099-01-01T00:00:00+00:00"

    after = _get(client)
    assert after["calculation_id"] == actual["calculation_id"] == before["calculation_id"]
    assert after["total_co2e_kg"] == pytest.approx(actual["total_co2e_kg"])
    assert after["co2e_per_kg"] == pytest.approx(actual["co2e_per_kg"])
    assert after["calculated_at"] == before["calculated_at"]
    assert after["calculation_kind"] == "actual"
    assert after["scenario"] == after["water_regime_scenario"] == "as_recorded"
    # The flooding simulation differs from the actual (AWD-recorded) season …
    assert flooding["total_co2e_kg"] != pytest.approx(actual["total_co2e_kg"])
    # … and is still readable, explicitly, as a scenario.
    stored_flooding = _get(client, "?scenario=continuous_flooding")
    assert stored_flooding["calculation_kind"] == "scenario"
    assert stored_flooding["total_co2e_kg"] == pytest.approx(flooding["total_co2e_kg"])
    assert _get(client, "?scenario=awd")["calculation_kind"] == "scenario"


def test_default_read_is_404_when_only_scenarios_exist(client):
    _calc(client, "continuous_flooding")
    response = client.get(f"/v1/crop-seasons/{rows.CROP_ID}/carbon")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "no_calculation"


def test_post_response_names_its_kind(client):
    assert _calc(client, "as_recorded")["calculation_kind"] == "actual"
    assert _calc(client, "awd")["calculation_kind"] == "scenario"


# -- 2. stored provenance ---------------------------------------------------


def test_stored_result_has_engine_sources_factor_version_and_matching_total(client):
    posted = _calc(client, "as_recorded")
    stored = _get(client)

    assert stored["ef_config_version"] == FACTOR_VERSION
    assert stored["engine_version"] == posted["engine_version"]
    assert stored["methodology"] == posted["methodology"]
    assert {b["source"] for b in stored["breakdown"]} == {b["source"] for b in posted["breakdown"]}
    for line in stored["breakdown"]:
        assert line["source"] not in (None, "", "undefined", "other")
        assert isinstance(line["factors_used"], dict) and line["factors_used"]
        assert isinstance(line["provenance"], dict)
    total = sum(float(b["co2e_kg"]) for b in stored["breakdown"])
    assert total == pytest.approx(float(stored["total_co2e_kg"]), abs=0.01)


def test_stored_view_never_invents_a_factor_version():
    view = stored_calculation_view(
        {"id": "c1", "scenario": "actual", "total_co2e_kg": 1.0, "breakdown": []}, ef_config_version=None
    )
    assert view["ef_config_version"] is None
    assert view["scenario"] == "as_recorded" and view["db_scenario"] == "actual"


def test_category_to_source_round_trips_every_mapped_category():
    assert CATEGORY_TO_SOURCE["irrigation_ch4"] == "ch4_rice_cultivation"
    assert CATEGORY_TO_SOURCE["fertilizer_n2o"] == "n2o_fertilizer_direct"
    assert CATEGORY_TO_SOURCE["straw_burning_ch4"] == CATEGORY_TO_SOURCE["straw_burning_n2o"] == "straw_burning"
    fuel = stored_calculation_view(
        {"scenario": "actual", "breakdown": [
            {"category": "fuel", "co2e_kg": 1, "formula_metadata": {"primary_factor_code": "fuel.diesel"}},
        ]},
        ef_config_version="v",
    )
    assert fuel["breakdown"][0]["source"] == "fuel_diesel"


# -- 3. fingerprint / staleness ----------------------------------------------


def _fingerprint(client: TestClient) -> str:
    response = client.get(f"/v1/crop-seasons/{rows.CROP_ID}/carbon/readiness")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ef_config_version"] == FACTOR_VERSION
    assert body["input_hash"] and len(body["input_hash"]) == 64
    return body["input_hash"]


def test_fresh_actual_result_matches_the_current_fingerprint(client):
    _calc(client, "as_recorded")
    assert _get(client)["input_hash"] == _fingerprint(client)


@pytest.mark.parametrize(
    "activity_type, edit",
    [
        ("seeding", lambda d: d.update(cost_vnd=1_250_000)),
        ("fertilizer", lambda d: d.update(total_cost_vnd=900_000)),
        ("irrigation", lambda d: d.update(total_cost_vnd=300_000)),
        ("harvest", lambda d: d.update(total_cost_vnd=100_000)),
        ("straw_management", lambda d: d.update(total_cost_vnd=50_000)),
    ],
    ids=["seeding-cost", "fertilizer-cost", "irrigation-cost", "harvest-cost", "straw-cost"],
)
def test_cost_only_edit_does_not_make_actual_stale(client, bundle, activity_type, edit):
    _calc(client, "as_recorded")
    stored_hash = _get(client)["input_hash"]
    edit(_activity(bundle, activity_type)["detail"])
    assert _fingerprint(client) == stored_hash


def test_note_edit_does_not_make_actual_stale(client, bundle):
    _calc(client, "as_recorded")
    stored_hash = _get(client)["input_hash"]
    for activity in bundle.activities:
        activity["note"] = "ghi chú mới"
    assert _fingerprint(client) == stored_hash


@pytest.mark.parametrize(
    "activity_type, edit",
    [
        ("irrigation", lambda d: d.update(water_volume_m3=8000)),
        ("fertilizer", lambda d: d.update(amount_kg=150)),
        ("straw_management", lambda d: d.update(straw_mass_kg=4000)),
        ("harvest", lambda d: d.update(yield_kg=5000)),
    ],
    ids=["water", "fertilizer", "straw", "yield"],
)
def test_carbon_input_edit_makes_actual_stale_and_recalculation_clears_it(client, bundle, activity_type, edit):
    _calc(client, "as_recorded")
    stored_hash = _get(client)["input_hash"]
    edit(_activity(bundle, activity_type)["detail"])
    current = _fingerprint(client)
    assert current != stored_hash

    _calc(client, "as_recorded")
    assert _get(client)["input_hash"] == current  # stale cleared


def test_scenario_calculation_does_not_make_actual_stale(client):
    _calc(client, "as_recorded")
    fingerprint = _fingerprint(client)
    _calc(client, "awd")
    _calc(client, "continuous_flooding")
    assert _get(client)["input_hash"] == fingerprint == _fingerprint(client)


def test_recalculating_unchanged_inputs_is_idempotent_and_not_stale(client, repo):
    first = _calc(client, "as_recorded")
    again = _calc(client, "as_recorded")
    assert again["calculation_id"] == first["calculation_id"]
    assert len([r for r in repo.calculations if r["scenario"] == "actual"]) == 1
    assert _get(client)["input_hash"] == _fingerprint(client)
