"""API contract hardening: error envelope + status semantics on EVERY route,
finite quantities, schema boundaries, malformed input, log safety.

Route sweeps enumerate the app's generated OpenAPI paths, so a new endpoint is
covered the day it is added -- no hand-maintained list to forget. (Not
`app.routes`: FastAPI >= 0.141 nests included routers in private wrappers, which a
flat walk silently misses. No /v1 route uses include_in_schema=False.)
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402
from main import app  # noqa: E402
from schemas import ActivityCreateRequest, CropSeasonCreateRequest, validate_activity_data  # noqa: E402
from tests._markers import requires_supabase_config  # noqa: E402

UUID = "00000000-0000-4000-8000-000000000001"
CONFIGURED = load_settings().auth_configured
# Intentionally public: the static list of Carbon scenario names, no tenant data.
PUBLIC_ROUTES = {("GET", "/v1/carbon/scenarios")}
# Unconfigured app only: these Carbon routes resolve the repository (503) before
# the caller's token. With configuration (CI DB job) they must answer 401 too.
UNCONFIGURED_503_BEFORE_AUTH = {("POST", "/v1/carbon/calculate"), ("GET", "/v1/crop-seasons/{crop_season_id}/carbon"),
                                ("GET", "/v1/crop-seasons/{crop_season_id}/carbon/readiness")}


def v1_operations():
    for path, item in app.openapi()["paths"].items():
        if path.startswith("/v1"):
            for method in item:
                if method in {"get", "post", "put", "patch", "delete"}:
                    yield method.upper(), path


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", UUID, path)


def is_envelope(response) -> bool:
    try:
        err = response.json()["detail"]["error"]
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(err, dict) and isinstance(err.get("code"), str) and isinstance(err.get("message"), str)


OPERATIONS = sorted(set(v1_operations()))


def test_the_route_sweep_sees_the_whole_api():
    # A broken route enumeration must not make every sweep below vacuously pass.
    assert len(OPERATIONS) >= 50


@pytest.mark.parametrize(("method", "path"), OPERATIONS, ids=[f"{m} {p}" for m, p in OPERATIONS])
def test_unauthenticated_request_gets_the_standard_error_envelope(method, path):
    if (method, path) in PUBLIC_ROUTES:  # EXC-API-01
        assert TestClient(app).request(method, concrete(path)).status_code == 200
        return
    response = TestClient(app, raise_server_exceptions=False).request(method, concrete(path), json={})
    assert response.status_code != 500, f"{method} {path} crashed without a token: {response.text[:200]}"
    assert is_envelope(response), f"{method} {path} -> {response.status_code} without the error envelope: {response.text[:200]}"
    allowed = {401, 503} if (method, path) in UNCONFIGURED_503_BEFORE_AUTH and not CONFIGURED else {401}
    assert response.status_code in allowed, f"{method} {path} -> {response.status_code}, expected {sorted(allowed)}"


@requires_supabase_config
@pytest.mark.parametrize(("method", "path"), OPERATIONS, ids=[f"{m} {p}" for m, p in OPERATIONS])
def test_configured_app_answers_401_for_every_protected_route(method, path):
    if (method, path) in PUBLIC_ROUTES:
        return
    response = TestClient(app, raise_server_exceptions=False).request(method, concrete(path), json={})
    assert response.status_code == 401 and is_envelope(response), f"{method} {path} -> {response.status_code} {response.text[:200]}"
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


@requires_supabase_config
@pytest.mark.parametrize("body", [{}, {"activity_type": "not-a-type"}, {"idempotency_key": "not-a-uuid"}])
def test_invalid_write_body_is_422_with_the_validation_envelope(body):
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/v1/crop-seasons/{UUID}/activities", json=body, headers={"Authorization": "Bearer x"})
    assert response.status_code == 422 and is_envelope(response)
    assert response.json()["detail"]["error"]["code"] == "validation_error"


# ------------------------------------------------------------ finite numbers
NUMERIC_FIELDS = {
    "fertilizer": ({"fertilizer_name": "Urea", "amount_kg": 10}, ["amount_kg", "nitrogen_percent", "total_cost_vnd"]),
    "irrigation": ({"method": "awd"}, ["water_volume_m3", "water_level_cm", "pump_energy_kwh", "total_cost_vnd"]),
    "harvest": ({"yield_kg": 100}, ["yield_kg", "harvested_area_ha", "moisture_percent", "total_cost_vnd"]),
    "seeding": ({"seed_kg": 5}, ["seed_kg", "cost_vnd"]),
    "pesticide": ({"product_name": "X", "amount": 1, "unit": "l"}, ["amount", "total_cost_vnd"]),
    "straw_management": ({"method": "removed"}, ["straw_mass_kg", "total_cost_vnd", "dry_matter_fraction"]),
}
NON_FINITE = [float("inf"), float("-inf"), float("nan")]


@pytest.mark.parametrize("kind", sorted(NUMERIC_FIELDS))
def test_activity_quantities_reject_non_finite_numbers(kind):
    base, fields = NUMERIC_FIELDS[kind]
    validate_activity_data(kind, dict(base))  # the valid baseline is accepted
    for field in fields:
        for value in NON_FINITE:
            with pytest.raises(ValidationError):
                validate_activity_data(kind, {**base, field: value})


def test_json_infinity_literal_in_a_request_body_is_rejected():
    # Python's json module parses the non-standard literals a client could send.
    raw = json.loads('{"idempotency_key": "%s", "activity_type": "irrigation", "occurred_at": "2026-09-01T00:00:00Z",'
                     ' "data": {"method": "awd", "water_volume_m3": Infinity}}' % UUID)
    with pytest.raises(ValidationError, match="finite"):
        ActivityCreateRequest.model_validate(raw)


# -------------------------------------------------------------- boundaries
@pytest.mark.parametrize(("length", "ok"), [(1, True), (63, True), (64, True), (65, False), (0, False)])
def test_season_code_length_boundary(length, ok):
    body = {"season_code": "S" * length}
    if ok:
        assert CropSeasonCreateRequest.model_validate(body).season_code == "S" * length
    else:
        with pytest.raises(ValidationError):
            CropSeasonCreateRequest.model_validate(body)


@pytest.mark.parametrize(("value", "ok"), [(0, True), (100, True), (100.0001, False), (-0.0001, False)])
def test_percentage_boundaries(value, ok):
    body = {"fertilizer_name": "NPK", "amount_kg": 1, "nitrogen_percent": value}
    if ok:
        validate_activity_data("fertilizer", body)
    else:
        with pytest.raises(ValidationError):
            validate_activity_data("fertilizer", body)


@pytest.mark.parametrize("data", [
    {"method": "not-a-method"},
    {"method": "awd", "water_volume_m3": -1},
    {"method": "awd", "water_volume_m3": "lots"},
    {"method": "awd", "duration_minutes": 1.5},
])
def test_malformed_activity_data_is_rejected(data):
    with pytest.raises(ValidationError):
        validate_activity_data("irrigation", data)


@pytest.mark.parametrize("key", ["", "not-a-uuid", "0" * 36, "' or 1=1 --"])
def test_idempotency_key_must_be_a_uuid(key):
    with pytest.raises(ValidationError):
        ActivityCreateRequest.model_validate({"idempotency_key": key, "activity_type": "irrigation",
                                              "occurred_at": "2026-09-01T00:00:00Z", "data": {"method": "awd"}})


def test_unicode_and_long_text_do_not_break_validation():
    data = validate_activity_data("fertilizer", {"fertilizer_name": "Phân bón NPK 20-20-15 🌾" + "ạ" * 2000, "amount_kg": 1})
    assert data.fertilizer_name.startswith("Phân bón")


def test_occurred_at_keeps_its_timezone_offset():
    # Vietnam local time must not be reinterpreted in the machine's timezone.
    req = ActivityCreateRequest.model_validate({"idempotency_key": UUID, "activity_type": "irrigation",
                                                "occurred_at": "2026-09-05T06:30:00+07:00", "data": {"method": "awd"}})
    assert req.occurred_at.utcoffset().total_seconds() == 7 * 3600
    assert req.occurred_at.isoformat() == "2026-09-05T06:30:00+07:00"


# ------------------------------------------------------------- log safety
def test_bearer_tokens_and_passwords_never_reach_the_logs(caplog, capsys):
    secret_token = "SYNTHETIC-TOKEN-7f3c9e2b-DO-NOT-LOG"
    secret_password = "Synthetic-Pw-9d41!DoNotLog"
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        client.get("/v1/me", headers={"Authorization": f"Bearer {secret_token}"})
        client.post(f"/v1/organizations/{UUID}/farmers", headers={"Authorization": f"Bearer {secret_token}"},
                    json={"full_name": "X", "email": "x@example.invalid", "password": secret_password})
        client.post(f"/v1/crop-seasons/{UUID}/activities", headers={"Authorization": f"Bearer {secret_token}"},
                    json={"note": secret_password})
    captured = caplog.text + capsys.readouterr().out + capsys.readouterr().err
    assert secret_token not in captured
    assert secret_password not in captured
