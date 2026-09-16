"""Season-level IPCC methodology inputs (SFw / SFp / cultivation days).

Why this route exists: the Carbon engine reads `ipcc_water_regime`,
`pre_season_water_regime` and `cultivation_days` straight off `crop_seasons`,
but until now only the Flutter app could write them (it upserts `crop_seasons`
through PostgREST). A Farmer Web-only user could therefore never supply SFw/SFp
and never obtain a Carbon result.

No hosted data is mutated here; the write repository is faked and the real
authorization rule (`private.user_can_write_crop`) is covered by the hosted smoke.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import schemas  # noqa: E402
from carbon.models import PRE_SEASON_REGIMES, WATER_REGIMES  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from infrastructure.write_repo import ActivityNotFoundError  # noqa: E402
from service import ActivityWriteService  # noqa: E402

ACTOR, SEASON = "farmer-a", "season-a"

STORED = {
    "id": SEASON, "plot_id": "plot-a", "season_code": "HT-2026", "crop_type": "rice",
    "variety_name": None, "planting_date": None, "expected_harvest_date": None,
    "actual_harvest_date": None, "status": "active",
    "ipcc_water_regime": None, "pre_season_water_regime": None, "cultivation_days": None,
}


class FakeRead:
    def __init__(self, *, role: str = "farmer", visible: bool = True):
        self.role, self.visible = role, visible

    def me(self):
        return {"user_id": ACTOR, "roles": [self.role]}

    def season(self, season_id):
        if not self.visible or season_id != SEASON:
            raise ReadNotFoundError("crop_seasons")
        return dict(STORED)


class FakeWrite:
    """Mirrors the real repository's contract: unknown keys rejected, absent keys
    left alone, explicit None clears, and a permission failure looks like 404."""

    def __init__(self, *, allowed: bool = True, exists: bool = True):
        self.allowed, self.exists = allowed, exists
        self.row = dict(STORED)
        self.calls: list[dict] = []

    def update_crop_season_methodology(self, *, crop_season_id, actor_id, fields):
        allowed_keys = ("ipcc_water_regime", "pre_season_water_regime", "cultivation_days")
        unknown = sorted(set(fields) - set(allowed_keys))
        if unknown:
            raise ValueError(f"unsupported crop season methodology field(s): {', '.join(unknown)}")
        if not self.exists or not self.allowed:
            raise ActivityNotFoundError()
        self.calls.append(dict(fields))
        self.row.update(fields)
        return dict(self.row)


def client(read: FakeRead, write: FakeWrite) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)  # the router already carries the /v1 prefix
    app.dependency_overrides[api._read_repo] = lambda: read
    app.dependency_overrides[api._activity_write_service] = lambda: ActivityWriteService(write)
    return TestClient(app)


def patch(body, *, read=None, write=None):
    w = write or FakeWrite()
    response = client(read or FakeRead(), w).patch(f"/v1/crop-seasons/{SEASON}/methodology", json=body)
    return response, w


# -- the schema cannot drift from the engine or the database ------------------

def test_schema_regimes_match_the_engine_exactly():
    """A value the engine accepts but the API rejects would be an input the user
    can never supply; the reverse would be a 500 from the enum cast."""
    import typing
    assert set(typing.get_args(schemas.IpccWaterRegime)) == set(WATER_REGIMES)
    assert set(typing.get_args(schemas.IpccPreSeasonRegime)) == set(PRE_SEASON_REGIMES)


# -- happy path ---------------------------------------------------------------

def test_records_both_regimes_and_returns_the_updated_season():
    response, write = patch({
        "ipcc_water_regime": "irrigated_multiple_drainage",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d",
        "cultivation_days": 100,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["ipcc_water_regime"] == "irrigated_multiple_drainage"
    assert body["pre_season_water_regime"] == "non_flooded_pre_season_lt_180d"
    assert body["cultivation_days"] == 100
    assert write.calls == [{
        "ipcc_water_regime": "irrigated_multiple_drainage",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d",
        "cultivation_days": 100,
    }]


def test_absent_field_is_not_sent_but_explicit_null_is():
    """`{}` and `{"cultivation_days": null}` must not mean the same thing: one
    keeps the stored value, the other clears it."""
    write = FakeWrite()
    write.row["cultivation_days"] = 95
    patch({"ipcc_water_regime": "upland"}, write=write)
    assert write.calls[-1] == {"ipcc_water_regime": "upland"}
    assert write.row["cultivation_days"] == 95  # untouched

    patch({"cultivation_days": None}, write=write)
    assert write.calls[-1] == {"cultivation_days": None}
    assert write.row["cultivation_days"] is None


def test_partial_update_leaves_the_other_regime_alone():
    write = FakeWrite()
    patch({"ipcc_water_regime": "irrigated_continuous_flooding"}, write=write)
    patch({"pre_season_water_regime": "flooded_pre_season_gt_30d"}, write=write)
    assert write.row["ipcc_water_regime"] == "irrigated_continuous_flooding"
    assert write.row["pre_season_water_regime"] == "flooded_pre_season_gt_30d"


# -- fail closed --------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"ipcc_water_regime": "awd"},                         # scenario name, not a regime
    {"ipcc_water_regime": "continuously_flooded"},        # plausible but not the enum
    {"pre_season_water_regime": "non_flooded"},           # truncated
    {"cultivation_days": 0},                              # DB check constraint is > 0
    {"cultivation_days": -5},
    {"unsupported_field": 1},                             # extra="forbid"
])
def test_invalid_values_are_rejected_before_any_write(body):
    response, write = patch(body)
    assert response.status_code == 422
    assert write.calls == []


def test_zero_is_not_accepted_as_a_stand_in_for_unknown():
    """null means 'chưa ghi nhận'; 0 days would be a fabricated input."""
    assert patch({"cultivation_days": None})[0].status_code == 200
    assert patch({"cultivation_days": 0})[0].status_code == 422


def test_season_outside_read_scope_is_404():
    response, write = patch({"ipcc_water_regime": "upland"}, read=FakeRead(visible=False))
    assert response.status_code == 404
    assert write.calls == []


def test_caller_without_write_authority_is_404_not_403():
    """Same normalization the activity writes use: a read-only member must not be
    able to tell an unauthorized season apart from a nonexistent one."""
    response, write = patch({"ipcc_water_regime": "upland"}, write=FakeWrite(allowed=False))
    assert response.status_code == 404
    assert write.calls == []


def test_cooperative_manager_may_record_methodology():
    """Unlike the journal activities this is not farmer-only: B4 already treats an
    active cooperative_manager as a writer, and the repository asks
    `private.user_can_write_crop` either way."""
    response, write = patch(
        {"ipcc_water_regime": "irrigated_single_drainage"},
        read=FakeRead(role="cooperative_manager"),
    )
    assert response.status_code == 200
    assert write.row["ipcc_water_regime"] == "irrigated_single_drainage"


def test_repository_contract_rejects_unknown_columns():
    """The service only ever passes the three known keys, but the repository is the
    last line before SQL interpolation, so it validates independently."""
    with pytest.raises(ValueError, match="unsupported"):
        FakeWrite().update_crop_season_methodology(
            crop_season_id=SEASON, actor_id=ACTOR, fields={"status": "closed"},
        )


def test_model_rejects_extra_keys_at_the_schema_level():
    with pytest.raises(ValidationError):
        schemas.CropSeasonMethodologyUpdate(status="closed")
