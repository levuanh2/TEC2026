"""Integration test: Supabase rows -> adapter -> Carbon Engine -> persistence -> API.

CHƯA KẾT NỐI SUPABASE THẬT. Dùng InMemoryCarbonRepository với fixture có hình dạng
đúng schema thật. Không giả vờ đã kết nối — repository thật
(`SupabaseCarbonRepository`) dùng CÙNG hợp đồng nên khi có credential chỉ cần đổi
implementation, không đổi test.

Toàn bộ hệ số là TEST FACTORS (số bịa). Xem docstring của test_carbon_engine.py.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import ParameterSet  # noqa: E402
from carbon.errors import (  # noqa: E402
    ConflictingWaterRegimeError,
    MethodologyGapError,
    MissingActivityDataError,
    MissingEmissionFactorError,
)
from infrastructure.mapping import (  # noqa: E402
    CalculationScopeError,
    RawCropBundle,
    map_crop_activity_data,
    resolve_calculation_batch,
)
from infrastructure.repository import (  # noqa: E402
    FactorSetNotFoundError,
    InMemoryCarbonRepository,
)
from service import CarbonService  # noqa: E402
from tests.fixtures import supabase_rows as rows  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "emission_factors.yaml"

AWD_TOTAL = 2920.8
CF_TOTAL = 5435.4
YIELD = 5200.0


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
        factor_sets={"TEST-FACTORS-DO-NOT-USE": rows.FACTOR_SET_ID},
        factors={
            rows.FACTOR_SET_ID: {
                "ch4_rice.efc": "ef-efc",
                "n2o_fertilizer.ef1fr.single_and_multiple_drainage": "ef-n2o-awd",
                "n2o_fertilizer.ef1fr.continuous_flooding": "ef-n2o-cf",
                "straw_burning.gef_ch4": "ef-straw-ch4",
                "straw_burning.gef_n2o": "ef-straw-n2o",
                "fuel.diesel": "ef-diesel",
            }
        },
    )


@pytest.fixture
def service(repo, params) -> CarbonService:
    return CarbonService(repo, params)


@pytest.fixture
def client(service) -> TestClient:
    import api

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: service
    return TestClient(app)


# ===========================================================================
# Test 1 — farm -> plot -> crop -> batch -> activities đọc thành CropActivityData
# ===========================================================================


def test_bundle_maps_to_activity_data(bundle):
    data = map_crop_activity_data(bundle)

    assert data.crop_id == rows.CROP_ID
    assert data.area_ha == pytest.approx(1.0)
    assert data.cultivation_days == 100
    assert data.water_regime == "irrigated_multiple_drainage"
    assert data.pre_season_water_regime == "non_flooded_pre_season_lt_180d"
    assert data.yield_kg == pytest.approx(YIELD)
    assert len(data.fertilizer) == 1
    assert len(data.straw) == 1
    assert len(data.fuel) == 1


# ===========================================================================
# Test 2 — fertilizer mapping: kg phân + %N -> kg N
# ===========================================================================


def test_fertilizer_mapping_keeps_nitrogen_percent(bundle):
    data = map_crop_activity_data(bundle)
    application = data.fertilizer[0]

    assert application.amount_kg == pytest.approx(120)
    assert application.n_content_pct == pytest.approx(46)
    assert data.total_nitrogen_kg == pytest.approx(55.2)


def test_fertilizer_without_nitrogen_percent_fails_at_engine(bundle, service):
    for activity in bundle.activities:
        if activity["activity_type"] == "fertilizer":
            activity["detail"]["nitrogen_percent"] = None

    with pytest.raises(Exception) as exc:
        service.calculate(rows.CROP_ID, "awd")
    assert "n_content_pct" in str(exc.value)


# ===========================================================================
# Test 3 — nhiều bản ghi tưới cùng chế độ
# ===========================================================================


def test_multiple_irrigation_records_same_regime(bundle):
    bundle.crop_season["ipcc_water_regime"] = None  # buộc suy từ activity
    extra = copy.deepcopy(bundle.activities[2])
    extra["id"] = "a3b"
    extra["detail"]["activity_id"] = "a3b"
    bundle.activities.append(extra)

    data = map_crop_activity_data(bundle)
    assert data.water_regime == "irrigated_multiple_drainage"
    assert len(data.irrigation) == 2


# ===========================================================================
# Test 4 — bản ghi tưới mâu thuẫn
# ===========================================================================


def test_conflicting_irrigation_regimes(bundle):
    bundle.crop_season["ipcc_water_regime"] = None
    conflicting = copy.deepcopy(bundle.activities[2])
    conflicting["id"] = "a3c"
    conflicting["detail"]["activity_id"] = "a3c"
    conflicting["detail"]["method"] = "continuous_flooding"
    bundle.activities.append(conflicting)

    with pytest.raises(ConflictingWaterRegimeError) as exc:
        map_crop_activity_data(bundle)
    assert "mâu thuẫn" in str(exc.value)


def test_ambiguous_irrigation_method_not_guessed(bundle):
    """'alternate' KHÔNG được đoán thành AWD — single vs multiple drainage lệch ~29% CH4."""
    bundle.crop_season["ipcc_water_regime"] = None
    bundle.activities[2]["detail"]["method"] = "alternate"

    with pytest.raises(MethodologyGapError) as exc:
        map_crop_activity_data(bundle)
    assert "alternate" in str(exc.value)


def test_default_irrigation_method_does_not_mask_activity_data(bundle):
    """default_irrigation_method là khai báo đầu vụ, không phải cái đã xảy ra."""
    bundle.crop_season["ipcc_water_regime"] = None
    bundle.crop_season["default_irrigation_method"] = "continuous_flooding"
    bundle.activities[2]["detail"]["method"] = "awd"

    data = map_crop_activity_data(bundle)
    assert data.water_regime == "irrigated_multiple_drainage"  # theo activity, không theo default


# ===========================================================================
# Test 5 — thiếu pre-season water
# ===========================================================================


def test_missing_pre_season_water_is_not_defaulted(bundle, service):
    bundle.crop_season["pre_season_water_regime"] = None

    data = map_crop_activity_data(bundle)
    assert data.pre_season_water_regime is None  # adapter KHÔNG điền thay

    with pytest.raises(MethodologyGapError) as exc:
        service.calculate(rows.CROP_ID, "awd")
    assert "SFp" in str(exc.value)


# ===========================================================================
# Test 6 — thiếu dry matter của rơm
# ===========================================================================


def test_missing_straw_dry_matter_fails(bundle, service):
    for activity in bundle.activities:
        if activity["activity_type"] == "straw_management":
            activity["detail"]["dry_matter_fraction"] = None

    with pytest.raises(MethodologyGapError) as exc:
        service.calculate(rows.CROP_ID, "awd")
    assert "dry_matter_fraction" in str(exc.value)


def test_straw_removed_creates_no_emission(bundle, service):
    for activity in bundle.activities:
        if activity["activity_type"] == "straw_management":
            activity["detail"]["method"] = "removed"

    outcome = service.calculate(rows.CROP_ID, "awd")
    sources = {e.source for e in outcome.result.breakdown}
    assert "straw_burning" not in sources
    ch4 = next(e for e in outcome.result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(1.0)


def test_straw_burned_goes_to_burning_pathway_only(bundle, service):
    for activity in bundle.activities:
        if activity["activity_type"] == "straw_management":
            activity["detail"]["method"] = "burned"

    outcome = service.calculate(rows.CROP_ID, "awd")
    ch4 = next(e for e in outcome.result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(1.0), "rơm đốt không vào SFo"
    assert any(e.source == "straw_burning" for e in outcome.result.breakdown)


# ===========================================================================
# Test 7 — thiếu sản lượng
# ===========================================================================


def test_missing_yield_gives_null_per_kg(bundle, service):
    bundle.activities = [a for a in bundle.activities if a["activity_type"] != "harvest"]

    outcome = service.calculate(rows.CROP_ID, "awd")
    assert outcome.result.total_co2e_kg == pytest.approx(AWD_TOTAL)
    assert outcome.result.co2e_per_kg is None
    assert any("Chưa có sản lượng" in w for w in outcome.result.warnings)


def test_multiple_harvest_events_are_summed_not_duplicated(bundle, service):
    second = copy.deepcopy(bundle.activities[-1])
    second["id"] = "a6b"
    second["detail"]["activity_id"] = "a6b"
    second["detail"]["yield_kg"] = 800
    bundle.activities.append(second)

    outcome = service.calculate(rows.CROP_ID, "awd")
    assert outcome.result.yield_kg == pytest.approx(6000.0)
    assert outcome.result.co2e_per_kg == pytest.approx(AWD_TOTAL / 6000.0)


def test_deleted_activity_is_ignored(bundle, service):
    for activity in bundle.activities:
        if activity["activity_type"] == "harvest":
            activity["deleted_at"] = "2026-05-01T00:00:00+07:00"

    outcome = service.calculate(rows.CROP_ID, "awd")
    assert outcome.result.yield_kg is None


# ===========================================================================
# Test 8 — thiếu GWP (config production)
# ===========================================================================


def test_production_config_fails_closed_on_missing_gwp(repo):
    """Fail-closed: config thật thiếu GWP -> lỗi, KHÔNG trả 0."""
    production = ParameterSet.load(REAL_CONFIG)
    service = CarbonService(repo, production)

    with pytest.raises(MissingEmissionFactorError) as exc:
        service.calculate(rows.CROP_ID, "awd")
    assert "gwp.ch4" in str(exc.value)
    assert repo.calculations == []  # không ghi gì khi tính thất bại


# ===========================================================================
# Test 9 — tính thành công với TEST FACTORS
# ===========================================================================


def test_successful_calculation_matches_engine_hand_calc(service):
    awd = service.calculate(rows.CROP_ID, "awd", persist=False)
    cf = service.calculate(rows.CROP_ID, "continuous_flooding", persist=False)

    assert awd.result.total_co2e_kg == pytest.approx(AWD_TOTAL)
    assert cf.result.total_co2e_kg == pytest.approx(CF_TOTAL)
    assert awd.result.co2e_per_kg == pytest.approx(AWD_TOTAL / YIELD)


def test_as_recorded_uses_recorded_regime(service):
    outcome = service.calculate(rows.CROP_ID, "as_recorded", persist=False)
    assert outcome.result.water_regime_applied == "irrigated_multiple_drainage"


# ===========================================================================
# Test 10 — persist calculation + breakdown
# ===========================================================================


def test_persist_calculation_and_breakdown(repo, service):
    outcome = service.calculate(rows.CROP_ID, "awd")

    assert outcome.persisted
    assert len(repo.calculations) == 1
    row = repo.calculations[0]

    assert row["production_batch_id"] == rows.BATCH_ID
    assert row["crop_season_id"] == rows.CROP_ID
    assert row["scenario"] == "awd"
    assert row["factor_set_id"] == rows.FACTOR_SET_ID
    assert row["engine_version"] == outcome.result.engine_version
    assert len(row["input_hash"]) == 64
    assert row["total_co2e_kg"] == pytest.approx(AWD_TOTAL)
    assert row["yield_kg"] == pytest.approx(YIELD)
    assert row["status"] == "succeeded"
    assert row["mrv_compliant"] is False
    assert row["area_ha_used"] == pytest.approx(1.0)
    assert row["cultivation_days_used"] == 100
    assert row["water_regime_applied"] == "irrigated_multiple_drainage"
    assert row["warnings"]

    breakdowns = repo.breakdowns[outcome.calculation_id]
    assert len(breakdowns) == len(outcome.result.breakdown)

    ch4 = next(b for b in breakdowns if b["category"] == "irrigation_ch4")
    assert ch4["gas"] == "ch4"
    assert ch4["emission_factor_id"] == "ef-efc"
    assert ch4["gas_kg"] == pytest.approx(262.5)
    assert ch4["co2e_kg"] == pytest.approx(2625.0)
    # factor_value_used = EFi hiệu dụng, không phải giá trị thô của EFc
    assert ch4["factor_value_used"] == pytest.approx(2.625)
    metadata = ch4["formula_metadata"]
    assert metadata["derived"]["sfo"] == pytest.approx(5.25)
    assert metadata["provenance"]
    assert metadata["parameter_status"]
    assert metadata["primary_factor_code"] == "ch4_rice.efc"


def test_as_recorded_persists_as_actual(repo, service):
    """Enum DB dùng 'actual', engine dùng 'as_recorded'."""
    service.calculate(rows.CROP_ID, "as_recorded")
    assert repo.calculations[0]["scenario"] == "actual"


def test_factor_set_not_imported_blocks_persistence(bundle, params):
    repo = InMemoryCarbonRepository(bundles={rows.CROP_ID: bundle})  # chưa có factor set
    service = CarbonService(repo, params)

    with pytest.raises(FactorSetNotFoundError):
        service.calculate(rows.CROP_ID, "awd")
    assert repo.calculations == []


# ===========================================================================
# Test 11 — đọc lại qua GET API
# ===========================================================================


def test_post_then_get_roundtrip(client):
    post = client.post(
        "/v1/carbon/calculate",
        json={"crop_id": rows.CROP_ID, "water_regime_scenario": "awd"},
    )
    assert post.status_code == 200, post.text
    body = post.json()
    assert body["co2e_total_kg"] == pytest.approx(AWD_TOTAL)
    assert body["water_regime_scenario"] == "awd"
    assert body["ef_config_version"] == "TEST-FACTORS-DO-NOT-USE"
    assert body["methodology"]["name"].startswith("TEST ONLY")
    assert len(body["input_hash"]) == 64
    assert body["breakdown"]

    get = client.get(f"/v1/crops/{rows.CROP_ID}/carbon?scenario=awd")
    assert get.status_code == 200, get.text
    stored = get.json()
    assert stored["total_co2e_kg"] == pytest.approx(AWD_TOTAL)
    assert stored["breakdown"]


def test_get_without_calculation_returns_404(client):
    response = client.get(f"/v1/crops/{rows.CROP_ID}/carbon")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "no_calculation"


def test_get_never_returns_failed_calculation(repo, client):
    repo.calculations.append(
        {
            "id": "calc-failed",
            "crop_season_id": rows.CROP_ID,
            "scenario": "awd",
            "status": "failed",
            "failure_reason": "gwp.ch4 missing",
            "total_co2e_kg": None,
            "calculated_at": "2099-01-01T00:00:00+00:00",
        }
    )
    response = client.get(f"/v1/crops/{rows.CROP_ID}/carbon?scenario=awd")
    assert response.status_code == 404


def test_api_invalid_scenario_rejected(client):
    response = client.post(
        "/v1/carbon/calculate",
        json={"crop_id": rows.CROP_ID, "water_regime_scenario": "random"},
    )
    assert response.status_code == 422  # pydantic chặn trước khi vào engine


def test_api_missing_gwp_returns_422(bundle, repo):
    import api
    from fastapi import FastAPI

    production = ParameterSet.load(REAL_CONFIG)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: CarbonService(repo, production)

    response = TestClient(app).post(
        "/v1/carbon/calculate",
        json={"crop_id": rows.CROP_ID, "water_regime_scenario": "awd"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "missing_emission_factor"
    assert "gwp.ch4" in detail["message"]


def test_api_crop_not_found(client):
    response = client.post(
        "/v1/carbon/calculate",
        json={"crop_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "crop_not_found"


def test_api_conflicting_water_returns_409(bundle, client):
    bundle.crop_season["ipcc_water_regime"] = None
    conflicting = copy.deepcopy(bundle.activities[2])
    conflicting["id"] = "a3d"
    conflicting["detail"]["activity_id"] = "a3d"
    conflicting["detail"]["method"] = "continuous_flooding"
    bundle.activities.append(conflicting)

    response = client.post(
        "/v1/carbon/calculate",
        json={"crop_id": rows.CROP_ID, "water_regime_scenario": "as_recorded"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "conflicting_water_records"


# ===========================================================================
# Test 12 — input hash deterministic
# ===========================================================================


def test_input_hash_deterministic_across_calls(service):
    first = service.calculate(rows.CROP_ID, "awd", persist=False).result.input_hash
    second = service.calculate(rows.CROP_ID, "awd", persist=False).result.input_hash
    assert first == second


def test_input_hash_stable_under_activity_row_order(bundle, params):
    """Thứ tự hàng trả về từ DB không ổn định — hash không được phụ thuộc vào nó."""
    ordered = copy.deepcopy(bundle)
    shuffled = copy.deepcopy(bundle)
    shuffled.activities.reverse()

    def hash_of(b):
        repo = InMemoryCarbonRepository(bundles={rows.CROP_ID: b})
        return CarbonService(repo, params).calculate(
            rows.CROP_ID, "awd", persist=False
        ).result.input_hash

    assert hash_of(ordered) == hash_of(shuffled)


def test_input_hash_changes_with_scenario(service):
    awd = service.calculate(rows.CROP_ID, "awd", persist=False).result.input_hash
    cf = service.calculate(rows.CROP_ID, "continuous_flooding", persist=False).result.input_hash
    assert awd != cf


# ===========================================================================
# Test 13 — phạm vi tính toán (double counting cấp vụ)
# ===========================================================================


def test_multiple_batches_rejected(bundle):
    """CH4 tính trên diện tích thửa × ngày canh tác của cả vụ.

    Nhiều lô thu hoạch -> tính riêng từng lô sẽ đếm trọn diện tích nhiều lần.
    Backend từ chối thay vì tự chia. Xem migration 20260908b.
    """
    bundle.production_batches = rows.production_batches(2)
    with pytest.raises(CalculationScopeError) as exc:
        resolve_calculation_batch(bundle)
    assert "diện tích" in str(exc.value)


def test_no_batch_rejected(bundle):
    bundle.production_batches = []
    with pytest.raises(CalculationScopeError):
        resolve_calculation_batch(bundle)


def test_missing_plot_area_fails(bundle):
    bundle.plot["area_ha"] = None
    with pytest.raises(MissingActivityDataError):
        map_crop_activity_data(bundle)
