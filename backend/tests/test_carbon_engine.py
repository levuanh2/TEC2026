"""Unit test Carbon Engine.

Mục tiêu: xác minh IMPLEMENTATION (phép tính, validation, cấu trúc kết quả).
KHÔNG xác minh giá trị khoa học — hệ số thật chưa có (open issue OI-02), nên toàn bộ
test dùng TEST FACTORS là số bịa tròn trịa để tính tay được.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import (  # noqa: E402
    ConflictingWaterRegimeError,
    CropActivityData,
    EmissionFactorSet,
    InvalidWaterRegimeError,
    MissingActivityDataError,
    MissingEmissionFactorError,
    WaterRecord,
    calculate_carbon,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "emission_factors.yaml"


@pytest.fixture
def test_factors() -> EmissionFactorSet:
    return EmissionFactorSet.load(FIXTURES / "test_factors.yaml")


@pytest.fixture
def demo_crop() -> CropActivityData:
    with open(FIXTURES / "demo_crop.json", encoding="utf-8") as fh:
        return CropActivityData.from_dict(json.load(fh))


# -- Test 6: đối chiếu phép tính tay ---------------------------------------
#
# demo_crop + TEST FACTORS, kịch bản AWD:
#   ch4_flooding     = 1.0 ha × 100 ngày × 4.0   =   400.0
#   n2o_fertilizer   = 120 kg × 46% = 55.2 kg N × 2.0 = 110.4
#   fuel_pumping     = 25 lít × 3.0              =    75.0
#   straw_management = 5000 kg × 0.2 (removed)   =  1000.0
#   ------------------------------------------------------
#   tổng                                         =  1585.4 kg CO2e
#   CO2e/kg = 1585.4 / 5200                      =  0.304884615...


def test_manual_calculation_awd(demo_crop, test_factors):
    result = calculate_carbon(demo_crop, "awd", test_factors)

    assert result.co2e_total_kg == pytest.approx(1585.4)
    assert result.co2e_per_kg == pytest.approx(1585.4 / 5200)
    assert result.water_regime_applied == "awd"

    by_source = {e.source: e.co2e_kg for e in result.breakdown}
    assert by_source == pytest.approx(
        {
            "ch4_flooding": 400.0,
            "n2o_fertilizer": 110.4,
            "fuel_pumping": 75.0,
            "straw_management": 1000.0,
        }
    )
    # Tổng các dòng phân rã phải bằng tổng hiển thị (FR-1a-10).
    assert sum(by_source.values()) == pytest.approx(result.co2e_total_kg)


def test_manual_calculation_continuous_flooding(demo_crop, test_factors):
    """Chỉ CH4 đổi; ba nguồn còn lại giữ nguyên."""
    result = calculate_carbon(demo_crop, "continuous_flooding", test_factors)

    assert result.co2e_total_kg == pytest.approx(2185.4)
    assert result.co2e_per_kg == pytest.approx(2185.4 / 5200)
    by_source = {e.source: e.co2e_kg for e in result.breakdown}
    assert by_source["ch4_flooding"] == pytest.approx(1000.0)
    assert by_source["n2o_fertilizer"] == pytest.approx(110.4)


def test_awd_and_continuous_flooding_differ(demo_crop, test_factors):
    """FR-1a-09: cùng Activity Data, hai kịch bản nước ra hai con số khác nhau."""
    awd = calculate_carbon(demo_crop, "awd", test_factors)
    flooded = calculate_carbon(demo_crop, "continuous_flooding", test_factors)

    assert awd.co2e_total_kg < flooded.co2e_total_kg
    assert awd.co2e_per_kg != flooded.co2e_per_kg


def test_as_recorded_uses_recorded_regime(demo_crop, test_factors):
    result = calculate_carbon(demo_crop, "as_recorded", test_factors)
    assert result.water_regime_applied == "awd"  # fixture ghi awd
    assert result.water_regime_scenario == "as_recorded"


# -- Test 1: thiếu sản lượng ------------------------------------------------


def test_missing_yield_returns_none_not_zero(demo_crop, test_factors):
    """NFR-03: thiếu sản lượng → co2e_per_kg = None, KHÔNG phải 0."""
    demo_crop.harvest.yield_kg = None
    result = calculate_carbon(demo_crop, "awd", test_factors)

    assert result.co2e_total_kg == pytest.approx(1585.4)  # tổng vẫn tính được
    assert result.co2e_per_kg is None
    assert result.co2e_per_kg != 0
    assert any("Chưa có sản lượng" in w for w in result.warnings)


def test_zero_yield_returns_none_not_division_error(demo_crop, test_factors):
    demo_crop.harvest.yield_kg = 0
    result = calculate_carbon(demo_crop, "awd", test_factors)
    assert result.co2e_per_kg is None
    assert any("không hợp lệ" in w for w in result.warnings)


# -- Test 2: thiếu hệ số ----------------------------------------------------


def test_missing_factor_fails_clearly(demo_crop):
    """Config thật đang null toàn bộ → engine phải nổ lỗi rõ, không fallback."""
    real_factors = EmissionFactorSet.load(REAL_CONFIG)

    with pytest.raises(MissingEmissionFactorError) as exc:
        calculate_carbon(demo_crop, "awd", real_factors)

    message = str(exc.value)
    assert "methane.awd" in message
    assert "OI-02" in message


def test_missing_factor_message_names_the_path(demo_crop, test_factors):
    """Xoá một hệ số cụ thể → thông báo phải chỉ đúng hệ số nào thiếu."""
    test_factors._factors["straw"]["removed"]["value"] = None

    with pytest.raises(MissingEmissionFactorError) as exc:
        calculate_carbon(demo_crop, "awd", test_factors)
    assert "straw.removed" in str(exc.value)


# -- Test 3: kịch bản nước không hợp lệ -------------------------------------


def test_invalid_water_regime_scenario(demo_crop, test_factors):
    with pytest.raises(InvalidWaterRegimeError) as exc:
        calculate_carbon(demo_crop, "random", test_factors)
    assert "random" in str(exc.value)


def test_invalid_regime_in_water_record(demo_crop, test_factors):
    demo_crop.water = [WaterRecord(regime="flooded_sometimes")]
    with pytest.raises(InvalidWaterRegimeError):
        calculate_carbon(demo_crop, "as_recorded", test_factors)


# -- Test 4: bản ghi nước mâu thuẫn -----------------------------------------


def test_conflicting_water_records(demo_crop, test_factors):
    demo_crop.water = [
        WaterRecord(regime="awd"),
        WaterRecord(regime="continuous_flooding"),
    ]
    with pytest.raises(ConflictingWaterRegimeError) as exc:
        calculate_carbon(demo_crop, "as_recorded", test_factors)
    assert "mâu thuẫn" in str(exc.value)


def test_conflicting_records_fail_even_when_scenario_overrides(demo_crop, test_factors):
    """Dữ liệu mâu thuẫn là lỗi nhập liệu — không né được bằng cách chọn kịch bản khác."""
    demo_crop.water = [
        WaterRecord(regime="awd"),
        WaterRecord(regime="continuous_flooding"),
    ]
    with pytest.raises(ConflictingWaterRegimeError):
        calculate_carbon(demo_crop, "awd", test_factors)


def test_as_recorded_without_water_record_fails(demo_crop, test_factors):
    demo_crop.water = []
    with pytest.raises(MissingActivityDataError):
        calculate_carbon(demo_crop, "as_recorded", test_factors)


# -- Test 5: xác định (deterministic) ---------------------------------------


def test_deterministic(demo_crop, test_factors):
    """Cùng input + cùng hệ số → cùng output (trừ dấu thời gian)."""
    first = calculate_carbon(demo_crop, "awd", test_factors).to_dict()
    second = calculate_carbon(demo_crop, "awd", test_factors).to_dict()
    first.pop("calculated_at")
    second.pop("calculated_at")
    assert first == second


# -- Dữ liệu hoạt động thiếu ------------------------------------------------


def test_missing_n_content_fails(demo_crop, test_factors):
    """Không đoán hàm lượng N."""
    demo_crop.fertilizer[0].n_content_pct = None
    with pytest.raises(MissingActivityDataError) as exc:
        calculate_carbon(demo_crop, "awd", test_factors)
    assert "n_content_pct" in str(exc.value)


def test_missing_cultivation_days_fails(demo_crop, test_factors):
    demo_crop.cultivation_days = None
    with pytest.raises(MissingActivityDataError) as exc:
        calculate_carbon(demo_crop, "awd", test_factors)
    assert "cultivation_days" in str(exc.value)


def test_cultivation_days_derived_from_dates(demo_crop, test_factors):
    demo_crop.cultivation_days = None
    demo_crop.sowing_date = "2026-01-01"
    demo_crop.harvest_date = "2026-04-11"  # 100 ngày
    result = calculate_carbon(demo_crop, "awd", test_factors)
    assert result.co2e_total_kg == pytest.approx(1585.4)


def test_sources_without_activity_data_are_omitted(demo_crop, test_factors):
    """Vụ không bón phân, không ghi nhiên liệu, không ghi rơm → chỉ còn CH4."""
    demo_crop.fertilizer = []
    demo_crop.straw = None
    demo_crop.water = [WaterRecord(regime="awd")]  # bỏ pump_fuel_litre
    result = calculate_carbon(demo_crop, "awd", test_factors)

    assert [e.source for e in result.breakdown] == ["ch4_flooding"]
    assert result.co2e_total_kg == pytest.approx(400.0)


# -- Cấu trúc kết quả -------------------------------------------------------


def test_result_shape_matches_contract(demo_crop, test_factors):
    """Cấu trúc bám SRS §4.2."""
    result = calculate_carbon(demo_crop, "awd", test_factors).to_dict()

    for key in (
        "crop_id",
        "water_regime_scenario",
        "co2e_total_kg",
        "yield_kg",
        "co2e_per_kg",
        "breakdown",
        "ef_config_version",
        "calculated_at",
        "warnings",
    ):
        assert key in result, f"thiếu trường {key}"

    assert result["ef_config_version"] == "TEST-FACTORS-DO-NOT-USE"
    assert result["breakdown"][0]["ef_path"]  # truy vết được về hệ số nào


def test_unverified_factors_produce_warning(demo_crop, test_factors):
    """FR-1a-12 + NFR-02: hệ số chưa VERIFIED phải được cảnh báo rõ."""
    result = calculate_carbon(demo_crop, "awd", test_factors)
    assert any("chưa được xác minh" in w for w in result.warnings)
    assert any("OI-02" in w for w in result.warnings)


def test_real_config_has_no_verified_factor_yet():
    """Chốt trạng thái hiện tại: chưa hệ số nào được xác minh.

    Test này SẼ FAIL khi nhóm điền hệ số thật vào config — lúc đó sửa lại nó,
    đó là dấu hiệu OI-02 đã xong.
    """
    factors = EmissionFactorSet.load(REAL_CONFIG)
    with pytest.raises(MissingEmissionFactorError):
        factors.get("methane", "awd")
    with pytest.raises(MissingEmissionFactorError):
        factors.get("fertilizer_n2o")
