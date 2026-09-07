"""Carbon Engine — Activity Data × Emission Factor → CO2e.

Hàm thuần, không phụ thuộc FastAPI / Supabase / Flutter / UI (docs/architecture.md §4.2).
Nhờ vậy: test được bằng ca tính tay, và What-if Simulation ở giai đoạn 2 chỉ cần gọi lại
hàm này với input giả định thay vì viết lại lớp 1a.

Công thức và trạng thái xác minh từng nguồn: xem docs/CARBON_METHOD.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .errors import (
    ConflictingWaterRegimeError,
    InvalidWaterRegimeError,
    MissingActivityDataError,
)
from .factors import EmissionFactorSet
from .models import (
    STRAW_METHODS,
    WATER_REGIME_SCENARIOS,
    WATER_REGIMES,
    CropActivityData,
)


@dataclass
class BreakdownEntry:
    """Một dòng phân rã theo nguồn phát thải."""

    source: str
    co2e_kg: float
    activity_value: float
    activity_unit: str
    ef_path: str
    ef_value: float
    ef_status: str


@dataclass
class CarbonResult:
    """Kết quả tính — cấu trúc bám SRS §4.2."""

    crop_id: str
    water_regime_scenario: str
    water_regime_applied: str
    co2e_total_kg: float
    yield_kg: float | None
    co2e_per_kg: float | None
    breakdown: list[BreakdownEntry] = field(default_factory=list)
    ef_config_version: str = "unknown"
    calculated_at: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_carbon(
    activity_data: CropActivityData,
    water_regime_scenario: str = "as_recorded",
    emission_factors: EmissionFactorSet | None = None,
) -> CarbonResult:
    """Tính CO2e tổng, CO2e/kg và phân rã theo nguồn cho một vụ canh tác.

    Args:
        activity_data: Activity Data của vụ.
        water_regime_scenario: "awd" | "continuous_flooding" | "as_recorded".
        emission_factors: bộ hệ số. Mặc định nạp backend/config/emission_factors.yaml.

    Raises:
        InvalidWaterRegimeError: kịch bản nước không hợp lệ.
        ConflictingWaterRegimeError: các bản ghi nước ghi chế độ mâu thuẫn.
        MissingActivityDataError: thiếu dữ liệu hoạt động bắt buộc.
        MissingEmissionFactorError: hệ số cần dùng đang null/chưa cấu hình.
    """
    factors = emission_factors or EmissionFactorSet.load()
    warnings: list[str] = []

    regime = _resolve_water_regime(activity_data, water_regime_scenario)
    breakdown = [
        entry
        for entry in (
            _methane(activity_data, regime, factors),
            _fertilizer_n2o(activity_data, factors),
            _fuel(activity_data, factors),
            _straw(activity_data, factors),
        )
        if entry is not None
    ]

    total = sum(entry.co2e_kg for entry in breakdown)
    per_kg, yield_warning = _per_kg(total, activity_data.yield_kg)
    if yield_warning:
        warnings.append(yield_warning)

    unverified = sorted({e.ef_path for e in breakdown if e.ef_status != "VERIFIED"})
    if unverified:
        warnings.append(
            "Hệ số chưa được xác minh chính thức: "
            + ", ".join(unverified)
            + ". Kết quả CHƯA dùng được cho báo cáo MRV (xem open issue OI-02)."
        )
    if activity_data.pesticide:
        warnings.append(
            "Thuốc BVTV đã ghi nhận nhưng chưa được đưa vào công thức phát thải "
            "(docs/CARBON_METHOD.md — NOT IMPLEMENTED)."
        )
    if regime == "awd" and any(w.drainage_events for w in activity_data.water):
        warnings.append(
            "Số lần rút nước (drainage_events) chưa được đưa vào công thức AWD "
            "(docs/CARBON_METHOD.md — NOT IMPLEMENTED, open issue OI-04)."
        )

    return CarbonResult(
        crop_id=activity_data.crop_id,
        water_regime_scenario=water_regime_scenario,
        water_regime_applied=regime,
        co2e_total_kg=total,
        yield_kg=activity_data.yield_kg,
        co2e_per_kg=per_kg,
        breakdown=breakdown,
        ef_config_version=factors.version,
        calculated_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
    )


# -- validation -------------------------------------------------------------


def _resolve_water_regime(data: CropActivityData, scenario: str) -> str:
    """Chốt chế độ nước dùng để tính, sau khi kiểm tra tính nhất quán của dữ liệu.

    Kiểm tra mâu thuẫn chạy kể cả khi kịch bản ghi đè chế độ đã ghi: dữ liệu mâu thuẫn
    là lỗi nhập liệu, phải sửa ở nguồn chứ không phải né bằng cách chọn kịch bản khác.
    """
    if scenario not in WATER_REGIME_SCENARIOS:
        raise InvalidWaterRegimeError(
            f"water_regime_scenario '{scenario}' không hợp lệ. "
            f"Chỉ nhận: {', '.join(WATER_REGIME_SCENARIOS)}."
        )

    recorded = {w.regime for w in data.water}
    invalid = recorded - set(WATER_REGIMES)
    if invalid:
        raise InvalidWaterRegimeError(
            f"Bản ghi nước có chế độ không hợp lệ: {', '.join(sorted(invalid))}. "
            f"Chỉ nhận: {', '.join(WATER_REGIMES)}."
        )
    if len(recorded) > 1:
        raise ConflictingWaterRegimeError(
            f"Vụ '{data.crop_id}' có các bản ghi nước ghi chế độ mâu thuẫn: "
            f"{', '.join(sorted(recorded))}. Engine không tự chọn — hãy sửa dữ liệu nguồn."
        )

    if scenario != "as_recorded":
        return scenario
    if not recorded:
        raise MissingActivityDataError(
            f"Vụ '{data.crop_id}' chưa có bản ghi chế độ nước nên không dùng được "
            f"kịch bản 'as_recorded'. Hãy truyền 'awd' hoặc 'continuous_flooding'."
        )
    return recorded.pop()


def _per_kg(total: float, yield_kg: float | None) -> tuple[float | None, str | None]:
    """CO2e/kg. Thiếu hoặc sai sản lượng → None kèm cảnh báo, KHÔNG trả 0 (NFR-03)."""
    if yield_kg is None:
        return None, "Chưa có sản lượng nên chưa tính được CO2e/kg."
    if yield_kg <= 0:
        return None, f"Sản lượng không hợp lệ ({yield_kg} kg) nên chưa tính được CO2e/kg."
    return total / yield_kg, None


# -- các nguồn phát thải ----------------------------------------------------
# Mỗi hàm trả None khi vụ không có dữ liệu hoạt động của nguồn đó.
# Có dữ liệu nhưng thiếu hệ số → MissingEmissionFactorError nổ ra từ factors.get().


def _methane(data: CropActivityData, regime: str, factors) -> BreakdownEntry | None:
    """CH4 ruộng ngập: area_ha × số ngày canh tác × EF theo chế độ nước.

    Luôn bắt buộc — lúa nước lúc nào cũng có chế độ nước.
    """
    days = data.flooded_days
    if days is None:
        raise MissingActivityDataError(
            f"Vụ '{data.crop_id}' thiếu 'cultivation_days' (hoặc cặp sowing_date/harvest_date) "
            f"nên không tính được CH4 ruộng ngập."
        )
    ef = factors.get("methane", regime)
    return BreakdownEntry(
        source="ch4_flooding",
        co2e_kg=data.area_ha * days * ef.value,
        activity_value=data.area_ha * days,
        activity_unit="ha_day",
        ef_path=ef.path,
        ef_value=ef.value,
        ef_status=ef.status,
    )


def _fertilizer_n2o(data: CropActivityData, factors) -> BreakdownEntry | None:
    """N2O từ phân đạm: tổng kg N × EF."""
    if not data.fertilizer:
        return None

    total_n = 0.0
    for application in data.fertilizer:
        nitrogen = application.nitrogen_kg
        if nitrogen is None:
            raise MissingActivityDataError(
                f"Lần bón '{application.fertilizer_type}' của vụ '{data.crop_id}' thiếu "
                f"'n_content_pct' nên không quy đổi được lượng N. Engine không đoán hàm lượng N."
            )
        total_n += nitrogen

    ef = factors.get("fertilizer_n2o")
    return BreakdownEntry(
        source="n2o_fertilizer",
        co2e_kg=total_n * ef.value,
        activity_value=total_n,
        activity_unit="kg_N",
        ef_path=ef.path,
        ef_value=ef.value,
        ef_status=ef.status,
    )


def _fuel(data: CropActivityData, factors) -> BreakdownEntry | None:
    """Nhiên liệu bơm tưới: số lít × EF."""
    litres = data.pump_fuel_litre
    if litres <= 0:
        return None
    ef = factors.get("fuel", "diesel")
    return BreakdownEntry(
        source="fuel_pumping",
        co2e_kg=litres * ef.value,
        activity_value=litres,
        activity_unit="litre",
        ef_path=ef.path,
        ef_value=ef.value,
        ef_status=ef.status,
    )


def _straw(data: CropActivityData, factors) -> BreakdownEntry | None:
    """Xử lý rơm rạ: khối lượng rơm × EF theo phương pháp."""
    straw = data.straw
    if straw is None:
        return None
    if straw.method not in STRAW_METHODS:
        raise MissingActivityDataError(
            f"Phương pháp xử lý rơm rạ '{straw.method}' không hợp lệ. "
            f"Chỉ nhận: {', '.join(STRAW_METHODS)}."
        )
    if straw.amount_kg is None:
        raise MissingActivityDataError(
            f"Vụ '{data.crop_id}' ghi phương pháp xử lý rơm rạ nhưng thiếu 'amount_kg'."
        )

    ef = factors.get("straw", straw.method)
    return BreakdownEntry(
        source="straw_management",
        co2e_kg=straw.amount_kg * ef.value,
        activity_value=straw.amount_kg,
        activity_unit="kg_straw",
        ef_path=ef.path,
        ef_value=ef.value,
        ef_status=ef.status,
    )
