"""Unit test Carbon Engine.

Mục tiêu: xác minh IMPLEMENTATION (phép tính, phân luồng, validation, provenance).
KHÔNG xác minh giá trị khoa học — toàn bộ test dùng TEST FACTORS là số bịa tròn trịa.
Giá trị khoa học thật được xác minh bằng trích dẫn trong docs/CARBON_METHOD_SOURCES.md.

Bảng tính tay cho demo_crop + TEST FACTORS (sfo_exponent = 1.0):

    area 1,0 ha · 100 ngày · yield 5200 kg
    phân: 120 kg urea × 46% N            = 55,2 kg N
    rơm vùi: 5000 kg × 0,85 DM / 1 ha    = 4,25 tấn DM/ha, CFOA(<30d) = 1,0
    SFo = 1 + 4,25 × 1,0                 = 5,25

    AWD (SFw 0,5 · SFp 1,0):
      EFi   = 1,0 × 0,5 × 1,0 × 5,25     = 2,625 kgCH4/ha/ngày
      CH4   = 2,625 × 100 × 1,0          = 262,5 kg   -> CO2e 2625,0
      N2O-N = 55,2 × 0,02                = 1,104 kg
      N2O   = 1,104 × 2,0                = 2,208 kg   -> CO2e  220,8
      diesel= 25 × 3,0                                -> CO2e   75,0
      tổng                                            = 2920,8

    Ngập liên tục (SFw 1,0 · EF1FR 0,01):
      CH4   = 5,25 × 100                 = 525 kg     -> CO2e 5250,0
      N2O   = 55,2 × 0,01 × 2,0 = 1,104 kg            -> CO2e  110,4
      diesel                                          -> CO2e   75,0
      tổng                                            = 5435,4
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import (  # noqa: E402
    ConflictingWaterRegimeError,
    CropActivityData,
    DoubleCountingError,
    FertilizerApplication,
    FuelUsage,
    InvalidWaterRegimeError,
    MethodologyGapError,
    MissingActivityDataError,
    MissingEmissionFactorError,
    OrganicAmendment,
    ParameterSet,
    StrawEvent,
    assert_consistent_water_records,
    calculate_carbon,
    classify_straw,
    compute_input_hash,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "emission_factors.yaml"
# Real config with gwp.ch4 removed — keeps the "no GWP -> fail closed" guarantee testable now that the
# real file carries AR5 GWP.
MISSING_GWP_CONFIG = FIXTURES / "factor_sets" / "missing_gwp.yaml"

AWD_TOTAL = 2920.8
CF_TOTAL = 5435.4
YIELD = 5200


@pytest.fixture
def params() -> ParameterSet:
    return ParameterSet.load(FIXTURES / "test_factors.yaml")


@pytest.fixture
def raw_demo() -> dict:
    with open(FIXTURES / "demo_crop.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def demo(raw_demo) -> CropActivityData:
    return CropActivityData.from_dict(copy.deepcopy(raw_demo))


def by_source(result) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in result.breakdown:
        out[f"{entry.source}:{entry.gas}"] = out.get(f"{entry.source}:{entry.gas}", 0.0) + entry.co2e_kg
    return out


# ===========================================================================
# Test 1 — Fertilizer mass -> N content -> N input
# ===========================================================================


def test_fertilizer_mass_to_nitrogen_input(demo):
    """120 kg urea × 46% = 55,2 kg N. Hệ số áp lên kg N, KHÔNG phải kg phân."""
    assert demo.total_nitrogen_kg == pytest.approx(55.2)


def test_nitrogen_without_content_pct_fails(demo, params):
    """Không đoán hàm lượng N từ tên phân."""
    demo.fertilizer[0].n_content_pct = None
    with pytest.raises(Exception) as exc:
        calculate_carbon(demo, "awd", params)
    assert "n_content_pct" in str(exc.value)
    assert "kg N" in str(exc.value)


# ===========================================================================
# Test 2 — N input -> N2O-N -> N2O -> CO2e
# ===========================================================================


def test_n2o_chain(demo, params):
    result = calculate_carbon(demo, "awd", params)
    entry = next(e for e in result.breakdown if e.source == "n2o_fertilizer_direct")

    assert entry.activity_unit == "kg_N"
    assert entry.activity_value == pytest.approx(55.2)
    assert entry.factors_used["_derived.n2o_n_kg"] == pytest.approx(55.2 * 0.02)
    assert entry.gas_kg == pytest.approx(55.2 * 0.02 * 2.0)
    assert entry.co2e_kg == pytest.approx(220.8)
    assert entry.gas == "n2o"


def test_n2o_indirect_declared_out_of_scope(demo, params):
    result = calculate_carbon(demo, "awd", params)
    assert any("gián tiếp" in w for w in result.warnings)


# ===========================================================================
# Test 3 — CH4 canh tác lúa
# ===========================================================================


def test_rice_methane_full_chain(demo, params):
    result = calculate_carbon(demo, "awd", params)
    entry = next(e for e in result.breakdown if e.source == "ch4_rice_cultivation")

    assert entry.factors_used["_derived.sfo"] == pytest.approx(5.25)
    assert entry.factors_used["_derived.ef_i_kgCH4_per_ha_day"] == pytest.approx(2.625)
    assert entry.activity_value == pytest.approx(100.0)
    assert entry.activity_unit == "ha_day"
    assert entry.gas_kg == pytest.approx(262.5)
    assert entry.co2e_kg == pytest.approx(2625.0)


def test_sfp_actually_enters_the_formula(demo, params):
    """Ngập trước vụ (SFp 2,0 trong TEST FACTORS) phải làm CH4 gấp đôi."""
    baseline = calculate_carbon(demo, "awd", params)
    demo.pre_season_water_regime = "flooded_pre_season_gt_30d"
    flooded = calculate_carbon(demo, "awd", params)

    ch4_base = next(e for e in baseline.breakdown if e.source == "ch4_rice_cultivation").co2e_kg
    ch4_flooded = next(e for e in flooded.breakdown if e.source == "ch4_rice_cultivation").co2e_kg
    assert ch4_flooded == pytest.approx(ch4_base * 2.0)


def test_missing_pre_season_regime_fails(demo, params):
    demo.pre_season_water_regime = None
    with pytest.raises(MethodologyGapError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "SFp" in str(exc.value)


def test_cultivation_days_is_never_defaulted(demo, params):
    """IPCC Table 5.11A là trung bình VÙNG cho kiểm kê quốc gia.

    Áp nó cho một thửa ruộng cụ thể trong báo cáo MRV cấp nông hộ là sai phạm vi.
    Engine phải báo lỗi, không được lặng lẽ dùng 102 ngày.
    """
    demo.cultivation_days = None
    with pytest.raises(MissingActivityDataError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "cultivation_days" in str(exc.value)


def test_cultivation_days_derived_from_dates(demo, params):
    demo.cultivation_days = None
    demo.sowing_date = "2026-01-01"
    demo.harvest_date = "2026-04-11"  # 100 ngày
    result = calculate_carbon(demo, "awd", params)
    assert result.total_co2e_kg == pytest.approx(AWD_TOTAL)


def test_unverified_parameter_status_is_warned(demo, params):
    """TEST FACTORS có status 'TEST' -> engine phải nói rõ chưa VERIFIED."""
    result = calculate_carbon(demo, "awd", params)
    assert any("CHƯA ở trạng thái VERIFIED" in w for w in result.warnings)
    assert any("gwp.ch4" in w for w in result.warnings)


def test_missing_straw_records_warned_not_silently_zero(demo, params):
    demo.straw = []
    result = calculate_carbon(demo, "awd", params)
    assert any("KHÔNG có bản ghi xử lý rơm rạ" in w for w in result.warnings)


def test_missing_fertilizer_records_warned_not_silently_zero(demo, params):
    demo.fertilizer = []
    result = calculate_carbon(demo, "awd", params)
    assert any("KHÔNG có bản ghi bón phân" in w for w in result.warnings)


def test_breakdown_carries_parameter_status(demo, params):
    result = calculate_carbon(demo, "awd", params)
    for entry in result.breakdown:
        assert entry.parameter_status, entry.source
        assert set(entry.parameter_status) <= set(entry.provenance)


# ===========================================================================
# Test 4 — AWD vs continuous flooding
# ===========================================================================


def test_awd_vs_continuous_flooding_totals(demo, params):
    awd = calculate_carbon(demo, "awd", params)
    cf = calculate_carbon(demo, "continuous_flooding", params)

    assert awd.total_co2e_kg == pytest.approx(AWD_TOTAL)
    assert cf.total_co2e_kg == pytest.approx(CF_TOTAL)
    assert awd.co2e_per_kg == pytest.approx(AWD_TOTAL / YIELD)
    assert cf.co2e_per_kg == pytest.approx(CF_TOTAL / YIELD)


def test_scenario_drives_both_ch4_and_n2o(demo, params):
    """AWD giảm CH4 nhưng TĂNG N2O — IPCC Table 5.12 vs Table 11.1.

    Đây là điểm dễ làm sai nhất: nếu chỉ áp kịch bản vào CH4 thì N2O sẽ giống nhau.
    """
    awd = by_source(calculate_carbon(demo, "awd", params))
    cf = by_source(calculate_carbon(demo, "continuous_flooding", params))

    assert awd["ch4_rice_cultivation:ch4"] < cf["ch4_rice_cultivation:ch4"]
    assert awd["n2o_fertilizer_direct:n2o"] > cf["n2o_fertilizer_direct:n2o"]


def test_scenario_is_not_a_flat_percentage_of_total(demo, params):
    """Không được lấy tổng rồi nhân một tỷ lệ giảm tuỳ ý.

    Nếu ai đó cài `awd_total = cf_total × k`, tỷ lệ giữa hai nguồn sẽ giữ nguyên.
    Test này bắt đúng lỗi đó: tỷ lệ CH4/N2O phải KHÁC nhau giữa hai kịch bản.
    """
    awd = by_source(calculate_carbon(demo, "awd", params))
    cf = by_source(calculate_carbon(demo, "continuous_flooding", params))

    ratio_awd = awd["ch4_rice_cultivation:ch4"] / awd["n2o_fertilizer_direct:n2o"]
    ratio_cf = cf["ch4_rice_cultivation:ch4"] / cf["n2o_fertilizer_direct:n2o"]
    assert ratio_awd != pytest.approx(ratio_cf)


def test_as_recorded_uses_recorded_regime(demo, params):
    result = calculate_carbon(demo, "as_recorded", params)
    assert result.water_regime_applied == "irrigated_multiple_drainage"
    assert result.total_co2e_kg == pytest.approx(AWD_TOTAL)


# ===========================================================================
# Test 5/6/7 — Rơm rạ: vùi / mang đi / đốt, và KHÔNG double counting
# ===========================================================================


def test_straw_incorporated_enters_sfo_only(demo, params):
    """Rơm vùi -> SFo (điều chỉnh CH4). KHÔNG tạo nguồn phát thải riêng."""
    result = calculate_carbon(demo, "awd", params)
    sources = {e.source for e in result.breakdown}

    assert "straw_burning" not in sources
    ch4 = next(e for e in result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(5.25)


def test_straw_incorporated_timing_changes_cfoa(demo, params):
    """Vùi >30 ngày trước canh tác: CFOA 0,2 thay vì 1,0 -> SFo = 1 + 4,25×0,2 = 1,85."""
    demo.straw[0].days_before_cultivation = 60
    result = calculate_carbon(demo, "awd", params)
    ch4 = next(e for e in result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(1.85)


def test_straw_incorporated_without_timing_fails(demo, params):
    """CFOA chênh 5 lần giữa <30d và >30d — engine không đoán."""
    demo.straw[0].days_before_cultivation = None
    with pytest.raises(MethodologyGapError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "days_before_cultivation" in str(exc.value)


def test_straw_removed_contributes_nothing(demo, params):
    """Mang rơm khỏi ruộng: SFo = 1,0, không có nguồn đốt."""
    demo.straw = [StrawEvent(method="removed", mass_kg=5000, dry_matter_fraction=0.85)]
    result = calculate_carbon(demo, "awd", params)

    ch4 = next(e for e in result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(1.0)
    assert ch4.co2e_kg == pytest.approx(500.0)  # 1,0 × 0,5 × 1,0 × 1,0 × 100 × 10
    assert "straw_burning" not in {e.source for e in result.breakdown}
    assert result.total_co2e_kg == pytest.approx(500.0 + 220.8 + 75.0)


def test_straw_burned_is_separate_source_not_in_sfo(demo, params):
    """Rơm đốt: nguồn riêng (CH4 + N2O), KHÔNG vào SFo.

    IPCC Table 5.14 chú thích a loại rơm bị đốt ra khỏi SFo.
    Tính tay: DM 4250 kg × Cf 0,5 = 2125 kg cháy
              CH4 = 2125 × 2,0/1000 = 4,25 kg -> CO2e 42,5
              N2O = 2125 × 0,1/1000 = 0,2125 kg -> CO2e 21,25
    """
    demo.straw = [StrawEvent(method="burned", mass_kg=5000, dry_matter_fraction=0.85)]
    result = calculate_carbon(demo, "awd", params)

    ch4_rice = next(e for e in result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4_rice.factors_used["_derived.sfo"] == pytest.approx(1.0), "rơm đốt KHÔNG được vào SFo"

    burning = by_source(result)
    assert burning["straw_burning:ch4"] == pytest.approx(42.5)
    assert burning["straw_burning:n2o"] == pytest.approx(21.25)
    assert result.total_co2e_kg == pytest.approx(500.0 + 220.8 + 42.5 + 21.25 + 75.0)


def test_no_double_counting_burned_straw(demo, params):
    """Cùng một khối rơm không bao giờ vừa vào SFo vừa vào nguồn đốt."""
    demo.straw = [StrawEvent(method="burned", mass_kg=5000, dry_matter_fraction=0.85)]
    amendments, burned = classify_straw(demo.straw, demo.crop_season_id, demo.area_ha)

    assert amendments == []
    assert len(burned) == 1


def test_double_counting_guard_raises(demo, params):
    """Chốt bất biến: nếu ai đó sửa classify_straw làm rơm đốt lọt vào SFo -> nổ lỗi."""
    from carbon.engine import _assert_no_double_counting

    burned = [StrawEvent(method="burned", mass_kg=1000, dry_matter_fraction=0.85)]
    bad_amendments = [
        OrganicAmendment(cfoa_key="straw_incorporated_lt_30d", rate_t_per_ha=0.85, origin="straw:burned")
    ]
    with pytest.raises(DoubleCountingError):
        _assert_no_double_counting(bad_amendments, burned, "demo-001")


def test_composted_straw_needs_returned_to_field(demo, params):
    demo.straw = [StrawEvent(method="composted", mass_kg=5000, dry_matter_fraction=0.85)]
    with pytest.raises(MethodologyGapError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "returned_to_field" in str(exc.value)


def test_composted_returned_uses_compost_cfoa(demo, params):
    demo.straw = [
        StrawEvent(
            method="composted",
            mass_kg=5000,
            dry_matter_fraction=0.85,
            returned_to_field=True,
        )
    ]
    result = calculate_carbon(demo, "awd", params)
    ch4 = next(e for e in result.breakdown if e.source == "ch4_rice_cultivation")
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(1 + 4.25 * 0.1)


def test_straw_without_dry_matter_fraction_fails(demo, params):
    """IPCC Eq 5.3 tính ROA theo khối lượng KHÔ — không đoán độ ẩm."""
    demo.straw[0].dry_matter_fraction = None
    with pytest.raises(MethodologyGapError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "dry_matter_fraction" in str(exc.value)


# ===========================================================================
# Test 8 — Nhiên liệu
# ===========================================================================


def test_fuel(demo, params):
    result = calculate_carbon(demo, "awd", params)
    entry = next(e for e in result.breakdown if e.source == "fuel_diesel")
    assert entry.activity_value == pytest.approx(25.0)
    assert entry.activity_unit == "litre"
    assert entry.co2e_kg == pytest.approx(75.0)


def test_fuel_without_factor_fails(demo, params):
    demo.fuel = [FuelUsage(fuel_type="gasoline", amount_litre=10)]
    with pytest.raises(MissingEmissionFactorError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "fuel.gasoline" in str(exc.value)


def test_electric_pump_warns_and_is_excluded(demo, params):
    from carbon import IrrigationEvent

    demo.irrigation = [IrrigationEvent(pump_energy_kwh=120)]
    result = calculate_carbon(demo, "awd", params)
    assert any("bơm điện" in w for w in result.warnings)
    assert result.total_co2e_kg == pytest.approx(AWD_TOTAL)  # chưa cộng vào


# ===========================================================================
# Test 9 — Tổng hợp
# ===========================================================================


def test_breakdown_sums_to_total(demo, params):
    for scenario in ("awd", "continuous_flooding", "as_recorded"):
        result = calculate_carbon(demo, scenario, params)
        assert sum(e.co2e_kg for e in result.breakdown) == pytest.approx(result.total_co2e_kg)


def test_co2e_per_kg(demo, params):
    result = calculate_carbon(demo, "awd", params)
    assert result.co2e_per_kg == pytest.approx(result.total_co2e_kg / YIELD)


# ===========================================================================
# Test 10 — Thiếu sản lượng
# ===========================================================================


def test_missing_yield_returns_none_not_zero(demo, params):
    demo.harvest.yield_kg = None
    result = calculate_carbon(demo, "awd", params)

    assert result.total_co2e_kg == pytest.approx(AWD_TOTAL)
    assert result.co2e_per_kg is None
    assert result.co2e_per_kg != 0
    assert any("Chưa có sản lượng" in w for w in result.warnings)


def test_zero_yield_is_validation_error(demo, params):
    demo.harvest.yield_kg = 0
    with pytest.raises(MissingActivityDataError):
        calculate_carbon(demo, "awd", params)


def test_negative_yield_is_validation_error(demo, params):
    demo.harvest.yield_kg = -5
    with pytest.raises(MissingActivityDataError):
        calculate_carbon(demo, "awd", params)


# ===========================================================================
# Test 11 — Thiếu hệ số
# ===========================================================================


def test_real_config_blocks_on_missing_gwp(demo):
    """Config thật bỏ GWP CH4: hệ số CH4/N2O VERIFIED nhưng thiếu GWP -> chặn ở GWP, không trả 0."""
    real = ParameterSet.load(MISSING_GWP_CONFIG)
    with pytest.raises(MissingEmissionFactorError) as exc:
        calculate_carbon(demo, "awd", real)
    assert "gwp.ch4" in str(exc.value)


def test_real_config_ipcc_factors_are_loadable():
    """Ngược lại: các hệ số IPCC đã trích dẫn phải nạp được và đúng giá trị bảng."""
    real = ParameterSet.load(REAL_CONFIG)

    assert real.factor("ch4_rice", "efc").value == pytest.approx(1.22)
    assert real.factor("ch4_rice", "sfw", "irrigated_continuous_flooding").value == pytest.approx(1.00)
    assert real.factor("ch4_rice", "sfw", "irrigated_multiple_drainage").value == pytest.approx(0.55)
    assert real.factor("ch4_rice", "sfp", "flooded_pre_season_gt_30d").value == pytest.approx(2.41)
    assert real.factor("ch4_rice", "sfo_exponent").value == pytest.approx(0.59)
    assert real.factor("ch4_rice", "cfoa", "straw_incorporated_lt_30d").value == pytest.approx(1.00)
    assert real.factor("ch4_rice", "cfoa", "straw_incorporated_gt_30d").value == pytest.approx(0.19)
    assert real.factor("n2o_fertilizer", "ef1fr", "continuous_flooding").value == pytest.approx(0.003)
    assert real.factor("n2o_fertilizer", "ef1fr", "single_and_multiple_drainage").value == pytest.approx(0.005)
    assert real.factor("straw_burning", "gef_ch4").value == pytest.approx(2.7)
    assert real.factor("straw_burning", "combustion_factor_rice").value == pytest.approx(0.80)


def test_real_config_factors_carry_provenance():
    """Mọi hệ số VERIFIED phải ghi rõ số hiệu bảng/phương trình."""
    real = ParameterSet.load(REAL_CONFIG)
    for path in (
        ("ch4_rice", "efc"),
        ("ch4_rice", "sfw", "irrigated_multiple_drainage"),
        ("ch4_rice", "sfp", "flooded_pre_season_gt_30d"),
        ("ch4_rice", "cfoa", "straw_incorporated_lt_30d"),
        ("n2o_fertilizer", "ef1fr", "single_and_multiple_drainage"),
        ("straw_burning", "gef_ch4"),
    ):
        parameter = real.factor(*path)
        assert parameter.status == "VERIFIED", path
        assert "Table" in (parameter.source or ""), path


def test_real_config_fuel_pending_and_gwp_decided():
    real = ParameterSet.load(REAL_CONFIG)
    assert real.gwp("ch4").value == 28 and real.gwp("n2o").value == 265  # AR5 GWP-100 (decided 2026-09-15)
    with pytest.raises(MissingEmissionFactorError):
        real.factor("fuel", "diesel")


# ===========================================================================
# Test 12 — Kịch bản / chế độ nước mâu thuẫn hoặc sai
# ===========================================================================


def test_invalid_scenario(demo, params):
    with pytest.raises(InvalidWaterRegimeError) as exc:
        calculate_carbon(demo, "random", params)
    assert "random" in str(exc.value)


def test_invalid_recorded_water_regime(demo, params):
    demo.water_regime = "flooded_sometimes"
    with pytest.raises(InvalidWaterRegimeError):
        calculate_carbon(demo, "as_recorded", params)


def test_as_recorded_without_regime_fails(demo, params):
    demo.water_regime = None
    with pytest.raises(MissingActivityDataError):
        calculate_carbon(demo, "as_recorded", params)


def test_conflicting_water_records_rejected():
    """Nhiều bản ghi tưới ghi chế độ khác nhau -> lỗi, engine không tự chọn."""
    with pytest.raises(ConflictingWaterRegimeError) as exc:
        assert_consistent_water_records(
            "demo-001", ["irrigated_multiple_drainage", "irrigated_continuous_flooding"]
        )
    assert "mâu thuẫn" in str(exc.value)


def test_consistent_water_records_accepted():
    regime = assert_consistent_water_records(
        "demo-001", ["irrigated_multiple_drainage", "irrigated_multiple_drainage"]
    )
    assert regime == "irrigated_multiple_drainage"


def test_upland_rice_n2o_not_implemented(demo, params):
    """IPCC Table 11.1 chú thích 7: lúa cạn dùng EF1, chưa cấu hình -> báo gap rõ ràng."""
    demo.water_regime = "upland"
    with pytest.raises(MethodologyGapError) as exc:
        calculate_carbon(demo, "as_recorded", params)
    assert "EF1" in str(exc.value)


def test_rainfed_uses_aggregate_ef_with_warning(demo, params):
    demo.water_regime = "rainfed_regular"
    result = calculate_carbon(demo, "as_recorded", params)
    entry = next(e for e in result.breakdown if e.source == "n2o_fertilizer_direct")
    assert entry.factors_used["factors.n2o_fertilizer.ef1fr.aggregate"] == pytest.approx(0.015)
    assert any("gộp" in w for w in result.warnings)


# ===========================================================================
# Test 13 — Thiếu tham số phương pháp luận bắt buộc
# ===========================================================================


def test_missing_methodology_parameter_fails_clearly(demo, params):
    """Xoá SFw của kịch bản đang dùng -> lỗi chỉ đúng đường dẫn tham số."""
    params._root["factors"]["ch4_rice"]["sfw"]["irrigated_multiple_drainage"]["value"] = None
    with pytest.raises(MissingEmissionFactorError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "ch4_rice.sfw.irrigated_multiple_drainage" in str(exc.value)


def test_missing_gwp_fails_clearly(demo, params):
    params._root["gwp"]["n2o"]["value"] = None
    with pytest.raises(MissingEmissionFactorError) as exc:
        calculate_carbon(demo, "awd", params)
    assert "gwp.n2o" in str(exc.value)


# ===========================================================================
# Test 14 — Input hash reproducibility
# ===========================================================================


def test_input_hash_is_reproducible(raw_demo, params):
    first = calculate_carbon(CropActivityData.from_dict(copy.deepcopy(raw_demo)), "awd", params)
    second = calculate_carbon(CropActivityData.from_dict(copy.deepcopy(raw_demo)), "awd", params)
    assert first.input_hash == second.input_hash
    assert len(first.input_hash) == 64  # khớp carbon_input_hash_chk trong Supabase


def test_input_hash_changes_with_input(demo, params):
    before = compute_input_hash(demo, "awd", params)
    demo.fertilizer.append(FertilizerApplication("Urea", 10, n_content_pct=46))
    assert compute_input_hash(demo, "awd", params) != before


def test_input_hash_changes_with_scenario(demo, params):
    assert compute_input_hash(demo, "awd", params) != compute_input_hash(
        demo, "continuous_flooding", params
    )


def test_deterministic_output(demo, params):
    first = calculate_carbon(demo, "awd", params).to_dict()
    second = calculate_carbon(demo, "awd", params).to_dict()
    first.pop("calculated_at")
    second.pop("calculated_at")
    assert first == second


# ===========================================================================
# Test 15 — Đổi bộ tham số -> provenance đổi theo
# ===========================================================================


def test_factor_set_version_flows_into_result(demo, params):
    result = calculate_carbon(demo, "awd", params)
    assert result.ef_config_version == "TEST-FACTORS-DO-NOT-USE"
    assert result.methodology["name"].startswith("TEST ONLY")
    assert result.engine_version


def test_factor_set_change_changes_hash_and_version(demo, params):
    hash_before = compute_input_hash(demo, "awd", params)
    params._root["version"] = "TEST-FACTORS-V2"
    reloaded = ParameterSet(
        version="TEST-FACTORS-V2",
        review_date=params.review_date,
        methodology=params.methodology,
        _root=params._root,
    )
    assert compute_input_hash(demo, "awd", reloaded) != hash_before
    assert calculate_carbon(demo, "awd", reloaded).ef_config_version == "TEST-FACTORS-V2"


# ===========================================================================
# Contract & provenance
# ===========================================================================


def test_output_contract_shape(demo, params):
    result = calculate_carbon(demo, "awd", params).to_dict()

    for key in (
        "total_co2e_kg",
        "yield_kg",
        "co2e_per_kg",
        "scenario",
        "breakdown",
        "methodology",
        "ef_config_version",
        "engine_version",
        "input_hash",
        "warnings",
    ):
        assert key in result, f"thiếu trường {key}"

    for entry in result["breakdown"]:
        for key in (
            "source",
            "gas",
            "activity_value",
            "activity_unit",
            "gas_kg",
            "co2e_kg",
            "formula",
            "factors_used",
            "provenance",
        ):
            assert key in entry, f"breakdown thiếu {key}"
        assert entry["formula"]
        assert entry["provenance"]


def test_tier1_default_warning_present(demo, params):
    """Kết quả phải tự nói rõ chưa được coi là MRV-compliant khi dùng default IPCC."""
    real = ParameterSet.load(REAL_CONFIG)
    assert real.methodology.tier == 1
    # Kiểm tra trực tiếp hàm cảnh báo (độc lập với dữ liệu vụ).
    from carbon.engine import _provenance_warnings

    notes = _provenance_warnings([], real)
    assert any("MRV-compliant" in n for n in notes)


def test_no_magic_numbers_in_engine_source():
    """Chốt RB-01: không có hằng số phát thải viết thẳng trong code tính toán."""
    import re

    forbidden = re.compile(r"\b(1\.22|0\.55|0\.71|2\.41|0\.59|0\.19|0\.003|0\.005|2\.7|0\.07|0\.80)\b")
    for name in ("engine.py", "methodology.py", "models.py", "factors.py"):
        source = (Path(__file__).resolve().parent.parent / "carbon" / name).read_text(
            encoding="utf-8"
        )
        code = "\n".join(
            line.split("#")[0] for line in source.splitlines() if not line.strip().startswith("#")
        )
        # bỏ docstring thô sơ: chỉ soi các dòng có phép gán/tính
        offenders = [
            line
            for line in code.splitlines()
            if forbidden.search(line) and ("=" in line or "*" in line)
        ]
        assert not offenders, f"{name} chứa hằng số phát thải: {offenders}"
