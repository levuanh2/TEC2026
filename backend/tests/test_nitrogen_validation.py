"""B5: a fertilizer application without nitrogen content is a client data error.

It must surface as `422 missing_activity_data` (existing envelope), be detected
before any emission-factor lookup, and never be defaulted or guessed. Zero is a
known value. The write schema's existing 0–100 range is unchanged. Production
parameters (GWP still null) are used only to prove ordering — no factor is set.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from carbon import ParameterSet, calculate_carbon  # noqa: E402
from carbon.errors import MissingActivityDataError, MissingEmissionFactorError  # noqa: E402
from infrastructure.mapping import map_crop_activity_data  # noqa: E402
from service import CarbonService  # noqa: E402
from tests.fixtures import supabase_rows as rows  # noqa: E402
from tests.test_integration_supabase import (  # noqa: E402,F401 - fixtures
    MISSING_GWP_CONFIG,
    REAL_CONFIG,
    FakeCropAccessChecker,
    FakeCropPersistChecker,
    bundle,
    params,
    repo,
)


def _set_nitrogen(bundle, value):
    touched = 0
    for activity in bundle.activities:
        if activity["activity_type"] == "fertilizer":
            activity["detail"]["nitrogen_percent"] = value
            touched += 1
    assert touched, "fixture must contain a fertilizer application"


def test_missing_nitrogen_is_missing_activity_data(bundle, params):
    _set_nitrogen(bundle, None)
    with pytest.raises(MissingActivityDataError) as exc:
        calculate_carbon(map_crop_activity_data(bundle), "awd", params)
    assert "nitrogen_percent" in str(exc.value)
    assert "kg N" in str(exc.value)


def test_missing_nitrogen_is_reported_before_any_factor_lookup(bundle):
    production = ParameterSet.load(MISSING_GWP_CONFIG)  # a factor gap that would otherwise surface
    _set_nitrogen(bundle, None)
    with pytest.raises(MissingActivityDataError):
        calculate_carbon(map_crop_activity_data(bundle), "awd", production)


def test_valid_nitrogen_proceeds_to_the_next_legitimate_gate(bundle):
    production = ParameterSet.load(MISSING_GWP_CONFIG)
    _set_nitrogen(bundle, 46)
    with pytest.raises(MissingEmissionFactorError):
        calculate_carbon(map_crop_activity_data(bundle), "awd", production)


def test_zero_nitrogen_is_a_known_value(bundle, params):
    _set_nitrogen(bundle, 0)
    result = calculate_carbon(map_crop_activity_data(bundle), "awd", params)
    assert not any(entry.source.startswith("n2o_fertilizer") for entry in result.breakdown)


def test_total_nitrogen_property_raises_the_same_domain_error(bundle):
    _set_nitrogen(bundle, None)
    with pytest.raises(MissingActivityDataError):
        map_crop_activity_data(bundle).total_nitrogen_kg


def _client(repo, parameters):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: CarbonService(repo, parameters)
    app.dependency_overrides[api._access_checker] = lambda: FakeCropAccessChecker()
    app.dependency_overrides[api._persist_checker] = lambda: FakeCropPersistChecker()
    return TestClient(app, headers={"Authorization": "Bearer test-fake-jwt"})


@pytest.mark.parametrize("production", [False, True])
def test_api_missing_nitrogen_returns_422_envelope(bundle, repo, params, production):
    _set_nitrogen(bundle, None)
    parameters = ParameterSet.load(REAL_CONFIG) if production else params
    response = _client(repo, parameters).post(
        "/v1/carbon/calculate", json={"crop_season_id": rows.CROP_ID, "water_regime_scenario": "awd"},
    )
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"} and set(body["detail"]) == {"error"}
    assert body["detail"]["error"]["code"] == "missing_activity_data"
    message = body["detail"]["error"]["message"]
    assert "nitrogen_percent" in message
    assert "Traceback" not in message and "request_id" not in body["detail"]["error"]
    assert repo.calculations == []  # nothing persisted


@pytest.mark.parametrize("value", [-1, 100.5, 101])
def test_write_schema_rejects_out_of_range_nitrogen(value):
    with pytest.raises(PydanticValidationError):
        schemas.FertilizerActivityData(fertilizer_name="Urea", amount_kg=10, nitrogen_percent=value)


@pytest.mark.parametrize("value", [0, 46, 100, None])
def test_write_schema_accepts_in_range_or_absent_nitrogen(value):
    # Absent stays allowed at write time (Farmer Web contract); the Carbon
    # calculation, not the journal, is where it becomes a required input.
    assert schemas.FertilizerActivityData(fertilizer_name="Urea", amount_kg=10, nitrogen_percent=value).nitrogen_percent == value


def test_fixture_bundle_is_not_shared_between_tests(bundle):
    snapshot = copy.deepcopy(bundle.activities)
    _set_nitrogen(bundle, None)
    assert snapshot != bundle.activities
