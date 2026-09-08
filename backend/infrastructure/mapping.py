"""Ánh xạ hàng Supabase <-> model của Carbon Engine.

HÀM THUẦN, KHÔNG I/O. Repository lo việc đọc/ghi; module này chỉ biến đổi dữ liệu.
Nhờ vậy test được toàn bộ luật ánh xạ mà không cần database.

Nguyên tắc: KHÔNG default, KHÔNG đoán. Thiếu dữ liệu thì để None và để Carbon Engine
raise lỗi đúng chỗ, hoặc raise ngay tại đây khi việc đoán là nguy hiểm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from carbon import (
    SCENARIO_TO_DB,
    CropActivityData,
    FertilizerApplication,
    FuelUsage,
    Harvest,
    IrrigationEvent,
    PesticideApplication,
    Seed,
    StrawEvent,
    assert_consistent_water_records,
)
from carbon.errors import CarbonEngineError, MethodologyGapError, MissingActivityDataError


class CalculationScopeError(CarbonEngineError):
    """Phạm vi tính toán không xác định được — xem migration 20260908b."""


# --- Chế độ nước ------------------------------------------------------------
# `public.irrigation_method` chỉ có ('awd','continuous_flooding','alternate','other').
# CHỈ hai giá trị đầu ánh xạ được sang phân loại IPCC Table 5.12 một cách chắc chắn.
# 'alternate' và 'other' KHÔNG được đoán thành AWD: AWD là "multiple drainage" (SFw 0,55),
# còn rút nước một lần là "single drainage" (SFw 0,71) — đoán sai lệch ~29% CH4.
IRRIGATION_METHOD_TO_IPCC = {
    "continuous_flooding": "irrigated_continuous_flooding",
    "awd": "irrigated_multiple_drainage",
}

AMBIGUOUS_IRRIGATION_METHODS = ("alternate", "other")

# Nguồn phát thải của engine -> public.emission_category
SOURCE_TO_CATEGORY = {
    ("ch4_rice_cultivation", "ch4"): "irrigation_ch4",
    ("n2o_fertilizer_direct", "n2o"): "fertilizer_n2o",
    ("straw_burning", "ch4"): "straw_burning_ch4",
    ("straw_burning", "n2o"): "straw_burning_n2o",
}

# Tham số CHÍNH của mỗi nguồn -> dùng cho carbon_breakdowns.emission_factor_id.
# Quy ước ghi trong migration 20260908 §5.
PRIMARY_FACTOR_PREFIX = {
    "ch4_rice_cultivation": "factors.ch4_rice.efc",
    "n2o_fertilizer_direct": "factors.n2o_fertilizer.ef1fr",
    "straw_burning": "factors.straw_burning.gef_",
}


@dataclass
class RawCropBundle:
    """Dữ liệu thô đã đọc từ Supabase, chưa biến đổi.

    `activities` là danh sách activity đã gộp sẵn bảng chi tiết vào khoá `detail`.
    Repository chịu trách nhiệm đọc từng bảng riêng rồi ghép — KHÔNG dùng một câu join
    lớn, vì join nhiều bảng 1-n sẽ nhân bản hàng và làm sai tổng sản lượng.
    """

    crop_season: dict[str, Any]
    plot: dict[str, Any]
    production_batches: list[dict[str, Any]] = field(default_factory=list)
    activities: list[dict[str, Any]] = field(default_factory=list)
    farm: dict[str, Any] | None = None

    def by_type(self, activity_type: str) -> list[dict[str, Any]]:
        return [
            a
            for a in self.activities
            if a.get("activity_type") == activity_type and a.get("deleted_at") is None
        ]


# --- Phạm vi tính toán ------------------------------------------------------


def resolve_calculation_batch(bundle: RawCropBundle) -> dict[str, Any]:
    """Chọn production_batch làm khoá phạm vi cho carbon_calculations.

    CH4 tính trên diện tích thửa × số ngày canh tác của cả VỤ. Nếu một vụ có nhiều lô
    thu hoạch, tính riêng từng lô sẽ đếm trọn diện tích nhiều lần -> double counting.
    Engine không tự chia diện tích. Xem supabase/migrations/20260908b_carbon_calculation_scope.sql.
    """
    active = [b for b in bundle.production_batches if b.get("deleted_at") is None]
    crop_id = bundle.crop_season.get("id")

    if not active:
        raise CalculationScopeError(
            f"Vụ '{crop_id}' chưa có production_batch nào. carbon_calculations.production_batch_id "
            f"là NOT NULL nên chưa ghi được kết quả."
        )
    if len(active) > 1:
        codes = ", ".join(sorted(str(b.get("batch_code")) for b in active))
        raise CalculationScopeError(
            f"Vụ '{crop_id}' có {len(active)} production_batch ({codes}). CH4 tính trên diện "
            f"tích thửa × số ngày canh tác của CẢ VỤ; tính riêng từng lô sẽ đếm trọn diện tích "
            f"nhiều lần. Backend không tự chia diện tích — xem migration 20260908b."
        )
    return active[0]


# --- Chế độ nước ------------------------------------------------------------


def resolve_water_regime(bundle: RawCropBundle) -> str | None:
    """Chế độ nước IPCC đã GHI NHẬN của vụ. None khi không xác định được.

    Thứ tự ưu tiên:
      1. `crop_seasons.ipcc_water_regime` — người dùng khai trực tiếp theo phân loại IPCC.
      2. Suy từ các bản ghi `irrigation_events` thực tế (chỉ 'awd'/'continuous_flooding').

    KHÔNG dùng `crop_seasons.default_irrigation_method` để che mất dữ liệu hoạt động thật:
    nó là giá trị khai báo đầu vụ, không phải cái đã xảy ra trên ruộng.
    """
    declared = bundle.crop_season.get("ipcc_water_regime")
    if declared:
        return declared

    crop_id = str(bundle.crop_season.get("id"))
    methods = [
        (a.get("detail") or {}).get("method")
        for a in bundle.by_type("irrigation")
    ]
    methods = [m for m in methods if m]
    if not methods:
        return None

    ambiguous = sorted({m for m in methods if m in AMBIGUOUS_IRRIGATION_METHODS})
    if ambiguous:
        raise MethodologyGapError(
            f"Vụ '{crop_id}': bản ghi tưới có phương pháp {', '.join(ambiguous)} — KHÔNG ánh xạ "
            f"được sang phân loại IPCC Table 5.12. Rút nước MỘT lần (SFw 0,71) và NHIỀU lần/AWD "
            f"(SFw 0,55) là hai nhóm khác nhau; đoán sai lệch CH4 khoảng 29%. "
            f"Hãy khai crop_seasons.ipcc_water_regime."
        )

    unknown = sorted({m for m in methods if m not in IRRIGATION_METHOD_TO_IPCC})
    if unknown:
        raise MethodologyGapError(
            f"Vụ '{crop_id}': phương pháp tưới {', '.join(unknown)} chưa có ánh xạ IPCC."
        )

    # Nhiều bản ghi mâu thuẫn -> lỗi rõ ràng, engine không tự chọn.
    mapped = [IRRIGATION_METHOD_TO_IPCC[m] for m in methods]
    return assert_consistent_water_records(crop_id, mapped)


# --- Activity Data ----------------------------------------------------------


def map_crop_activity_data(bundle: RawCropBundle) -> CropActivityData:
    """Biến hàng Supabase thành input của Carbon Engine.

    Mọi trường thiếu đều để None — Carbon Engine sẽ raise đúng loại lỗi. Module này
    KHÔNG điền giá trị thay thế.
    """
    crop = bundle.crop_season
    crop_id = str(crop.get("id"))

    area_ha = bundle.plot.get("area_ha")
    if area_ha is None:
        raise MissingActivityDataError(
            f"Thửa của vụ '{crop_id}' thiếu 'area_ha' — không tính được CH4 (Eq 5.1)."
        )

    return CropActivityData(
        crop_id=crop_id,
        area_ha=float(area_ha),
        water_regime=resolve_water_regime(bundle),
        # KHÔNG default: thiếu thì engine raise MethodologyGapError về SFp.
        pre_season_water_regime=crop.get("pre_season_water_regime"),
        cultivation_days=crop.get("cultivation_days"),
        sowing_date=_as_date_str(crop.get("planting_date")),
        harvest_date=_as_date_str(crop.get("actual_harvest_date")),
        harvest=Harvest(yield_kg=_total_yield(bundle), loss_kg=None),
        seed=_map_seed(bundle),
        fertilizer=_map_fertilizer(bundle),
        straw=_map_straw(bundle),
        fuel=_map_fuel(bundle),
        irrigation=_map_irrigation(bundle),
        pesticide=_map_pesticide(bundle),
    )


def _as_date_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:10]


def _total_yield(bundle: RawCropBundle) -> float | None:
    """Tổng sản lượng của vụ = tổng yield_kg các harvest_events còn hiệu lực.

    Quy tắc gộp: CỘNG tất cả. Không có harvest event nào -> None (KHÔNG phải 0), để
    Carbon Engine trả co2e_per_kg = None kèm cảnh báo thay vì chia cho 0.

    Đọc theo từng activity (không join nhiều bảng cùng lúc) nên không có nguy cơ nhân
    bản hàng làm phồng sản lượng.
    """
    events = bundle.by_type("harvest")
    values = [
        (a.get("detail") or {}).get("yield_kg")
        for a in events
    ]
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    return sum(values)


def _map_seed(bundle: RawCropBundle) -> Seed | None:
    events = bundle.by_type("seeding")
    if not events:
        return None
    detail = events[0].get("detail") or {}
    area_ha = float(bundle.plot.get("area_ha") or 0) or None
    seed_kg = detail.get("seed_kg")
    return Seed(
        variety=detail.get("variety_name"),
        seed_rate_kg_per_ha=(float(seed_kg) / area_ha) if (seed_kg and area_ha) else None,
        sowing_method=detail.get("seeding_method"),
    )


def _map_fertilizer(bundle: RawCropBundle) -> list[FertilizerApplication]:
    out: list[FertilizerApplication] = []
    for index, activity in enumerate(bundle.by_type("fertilizer"), start=1):
        detail = activity.get("detail") or {}
        out.append(
            FertilizerApplication(
                fertilizer_type=detail.get("fertilizer_name") or detail.get("fertilizer_type") or "?",
                amount_kg=float(detail["amount_kg"]),
                # nitrogen_percent thiếu -> None -> engine raise. KHÔNG tra bảng thành phần.
                n_content_pct=(
                    float(detail["nitrogen_percent"])
                    if detail.get("nitrogen_percent") is not None
                    else None
                ),
                application_no=index,
                is_organic=False,
            )
        )
    return out


def _map_straw(bundle: RawCropBundle) -> list[StrawEvent]:
    out: list[StrawEvent] = []
    for activity in bundle.by_type("straw_management"):
        detail = activity.get("detail") or {}
        out.append(
            StrawEvent(
                method=detail.get("method"),
                mass_kg=(
                    float(detail["straw_mass_kg"])
                    if detail.get("straw_mass_kg") is not None
                    else None
                ),
                # Hai trường dưới là cột mới của migration 20260908. Thiếu -> None ->
                # engine raise MethodologyGapError. KHÔNG đoán độ ẩm, không đoán thời điểm vùi.
                dry_matter_fraction=(
                    float(detail["dry_matter_fraction"])
                    if detail.get("dry_matter_fraction") is not None
                    else None
                ),
                days_before_cultivation=detail.get("days_before_cultivation"),
                returned_to_field=detail.get("returned_to_field"),
            )
        )
    return out


def _map_fuel(bundle: RawCropBundle) -> list[FuelUsage]:
    out: list[FuelUsage] = []
    for activity in bundle.by_type("fuel"):
        detail = activity.get("detail") or {}
        # Cột DB là `amount_liter`, model engine là `amount_litre`.
        out.append(
            FuelUsage(
                fuel_type=detail.get("fuel_type"),
                amount_litre=float(detail["amount_liter"]),
            )
        )
    return out


def _map_irrigation(bundle: RawCropBundle) -> list[IrrigationEvent]:
    return [
        IrrigationEvent(
            water_volume_m3=(
                float(d["water_volume_m3"]) if d.get("water_volume_m3") is not None else None
            ),
            pump_energy_kwh=(
                float(d["pump_energy_kwh"]) if d.get("pump_energy_kwh") is not None else None
            ),
        )
        for d in ((a.get("detail") or {}) for a in bundle.by_type("irrigation"))
    ]


def _map_pesticide(bundle: RawCropBundle) -> list[PesticideApplication]:
    return [
        PesticideApplication(
            product_group=d.get("active_ingredient") or d.get("product_name"),
            amount=float(d["amount"]) if d.get("amount") is not None else None,
            unit=d.get("unit"),
        )
        for d in ((a.get("detail") or {}) for a in bundle.by_type("pesticide"))
    ]


# --- Kết quả -> hàng Supabase ----------------------------------------------


def calculation_row(
    result,
    *,
    production_batch_id: str,
    crop_season_id: str,
    factor_set_id: str,
    area_ha: float,
    cultivation_days: int,
    pre_season_water_regime: str | None,
) -> dict[str, Any]:
    """Hàng cho `carbon_calculations`.

    KHÔNG ghi `co2e_per_kg` — cột đó là GENERATED ALWAYS trong schema.
    `mrv_compliant` luôn false cho tới khi có hệ số từ QĐ 4801/QĐ-BNNMT.
    """
    return {
        "production_batch_id": production_batch_id,
        "crop_season_id": crop_season_id,
        "scenario": SCENARIO_TO_DB[result.scenario],
        "factor_set_id": factor_set_id,
        "engine_version": result.engine_version,
        "input_hash": result.input_hash,
        "total_co2e_kg": result.total_co2e_kg,
        "yield_kg": result.yield_kg,
        "status": "succeeded",
        "methodology_tier": result.methodology.get("tier"),
        "mrv_compliant": False,
        "warnings": result.warnings,
        "area_ha_used": area_ha,
        "cultivation_days_used": cultivation_days,
        "water_regime_applied": result.water_regime_applied,
        "pre_season_water_regime_applied": pre_season_water_regime,
        "calculated_at": result.calculated_at,
    }


def breakdown_rows(result, factor_id_by_code: dict[str, str]) -> list[dict[str, Any]]:
    """Hàng cho `carbon_breakdowns`, một dòng mỗi (nguồn, khí).

    Quy ước (migration 20260908 §5):
      emission_factor_id -> tham số CHÍNH của nguồn
      factor_value_used  -> hệ số HIỆU DỤNG (CH4: EFi = EFc×SFw×SFp×SFo)
      formula_metadata   -> đủ để tái hiện toàn bộ phép tính
    """
    rows: list[dict[str, Any]] = []
    for entry in result.breakdown:
        category = SOURCE_TO_CATEGORY.get((entry.source, entry.gas))
        if category is None and entry.source.startswith("fuel_"):
            category = "fuel"
        if category is None:
            category = "other"

        primary_path = _primary_factor_path(entry)
        factor_code = primary_path.removeprefix("factors.") if primary_path else None
        rows.append(
            {
                "emission_factor_id": factor_id_by_code.get(factor_code) if factor_code else None,
                "category": category,
                "gas": entry.gas,
                "activity_value": entry.activity_value,
                "activity_unit": entry.activity_unit,
                "factor_value_used": _effective_factor(entry, primary_path),
                "gas_kg": entry.gas_kg,
                "co2e_kg": entry.co2e_kg,
                "formula_note": entry.formula[:500],
                "formula_expression": entry.formula,
                "formula_metadata": {
                    "factors_used": {
                        k: v for k, v in entry.factors_used.items() if not k.startswith("_")
                    },
                    "derived": {
                        k.removeprefix("_derived."): v
                        for k, v in entry.factors_used.items()
                        if k.startswith("_derived.")
                    },
                    "sfo_terms": entry.factors_used.get("_sfo_terms"),
                    "provenance": entry.provenance,
                    "parameter_status": entry.parameter_status,
                    "primary_factor_code": factor_code,
                },
            }
        )
    return rows


def _primary_factor_path(entry) -> str | None:
    prefix = PRIMARY_FACTOR_PREFIX.get(entry.source)
    if prefix is None and entry.source.startswith("fuel_"):
        prefix = "factors.fuel."
    if prefix is None:
        return None
    for path in entry.factors_used:
        if path.startswith(prefix):
            return path
    return None


def _effective_factor(entry, primary_path: str | None) -> float:
    """Hệ số hiệu dụng của dòng. CH4 lúa dùng EFi đã nhân hết bốn thành phần."""
    derived = entry.factors_used.get("_derived.ef_i_kgCH4_per_ha_day")
    if derived is not None:
        return float(derived)
    if primary_path is not None:
        return float(entry.factors_used[primary_path])
    return 0.0
