"""Carbon Engine — điều phối các bộ tính theo nguồn và tổng hợp kết quả.

Hàm thuần, không phụ thuộc FastAPI / Supabase / Flutter / UI (docs/architecture.md §4.2).
Nhờ vậy What-if Simulation ở giai đoạn 2 chỉ cần gọi lại hàm này với input giả định.

Phương pháp luận và trích dẫn: docs/CARBON_METHOD.md, docs/CARBON_METHOD_SOURCES.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .errors import (
    ConflictingWaterRegimeError,
    DoubleCountingError,
    InvalidWaterRegimeError,
    MethodologyGapError,
    MissingActivityDataError,
)
from .factors import STATUS_VERIFIED, ParameterSet
from .methodology import (
    BreakdownEntry,
    FertilizerN2OCalculator,
    FuelEmissionCalculator,
    RiceMethaneCalculator,
    StrawBurningCalculator,
    classify_straw,
)
from .models import (
    SCENARIO_TO_REGIME,
    SCENARIOS,
    WATER_REGIMES,
    CropActivityData,
)

ENGINE_VERSION = "0.2.0"


@dataclass
class CarbonResult:
    """Kết quả tính. Cấu trúc đủ để truy ngược tới nguồn trích dẫn."""

    crop_season_id: str
    scenario: str
    water_regime_applied: str
    total_co2e_kg: float
    yield_kg: float | None
    co2e_per_kg: float | None
    breakdown: list[BreakdownEntry] = field(default_factory=list)
    methodology: dict[str, Any] = field(default_factory=dict)
    ef_config_version: str = "unknown"
    engine_version: str = ENGINE_VERSION
    input_hash: str = ""
    calculated_at: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "crop_season_id": self.crop_season_id,
            "scenario": self.scenario,
            "water_regime_applied": self.water_regime_applied,
            "total_co2e_kg": self.total_co2e_kg,
            "yield_kg": self.yield_kg,
            "co2e_per_kg": self.co2e_per_kg,
            "breakdown": [entry.to_dict() for entry in self.breakdown],
            "methodology": self.methodology,
            "ef_config_version": self.ef_config_version,
            "engine_version": self.engine_version,
            "input_hash": self.input_hash,
            "calculated_at": self.calculated_at,
            "warnings": self.warnings,
        }


def calculate_carbon(
    activity_data: CropActivityData,
    scenario: str = "as_recorded",
    methodology_config: ParameterSet | None = None,
) -> CarbonResult:
    """Tính CO2e tổng, CO2e/kg và phân rã theo nguồn cho một vụ canh tác.

    Args:
        activity_data: Activity Data của vụ.
        scenario: "awd" | "continuous_flooding" | "as_recorded".
        methodology_config: bộ tham số. Mặc định nạp backend/config/emission_factors.yaml.

    Raises:
        InvalidWaterRegimeError, ConflictingWaterRegimeError, MissingActivityDataError,
        MethodologyGapError, MissingEmissionFactorError, DoubleCountingError.
    """
    params = methodology_config or ParameterSet.load()
    warnings: list[str] = []

    regime = _resolve_water_regime(activity_data, scenario)
    cultivation_days = _resolve_cultivation_days(activity_data)

    amendments, burned = classify_straw(
        activity_data.straw, activity_data.crop_season_id, activity_data.area_ha
    )
    _assert_no_double_counting(amendments, burned, activity_data.crop_season_id)

    breakdown: list[BreakdownEntry] = [
        RiceMethaneCalculator().calculate(
            activity_data, regime, amendments, params, cultivation_days
        )
    ]

    n2o_entry, n2o_warnings = FertilizerN2OCalculator().calculate(activity_data, regime, params)
    warnings.extend(n2o_warnings)
    if n2o_entry is not None:
        breakdown.append(n2o_entry)

    breakdown.extend(StrawBurningCalculator().calculate(burned, activity_data, params))

    fuel_entries, fuel_warnings = FuelEmissionCalculator().calculate(activity_data, params)
    breakdown.extend(fuel_entries)
    warnings.extend(fuel_warnings)

    total = sum(entry.co2e_kg for entry in breakdown)
    per_kg, yield_warning = _per_kg(total, activity_data.yield_kg)
    if yield_warning:
        warnings.append(yield_warning)

    warnings.extend(_missing_record_warnings(activity_data))
    warnings.extend(_scope_warnings(activity_data, amendments))
    warnings.extend(_provenance_warnings(breakdown, params))

    return CarbonResult(
        crop_season_id=activity_data.crop_season_id,
        scenario=scenario,
        water_regime_applied=regime,
        total_co2e_kg=total,
        yield_kg=activity_data.yield_kg,
        co2e_per_kg=per_kg,
        breakdown=breakdown,
        methodology=params.methodology.to_dict(),
        ef_config_version=params.version,
        input_hash=compute_input_hash(activity_data, scenario, params),
        calculated_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
    )


def compute_input_hash(
    activity_data: CropActivityData, scenario: str, params: ParameterSet
) -> str:
    """SHA-256 của (Activity Data, kịch bản, phiên bản bộ tham số).

    Khớp ràng buộc `carbon_input_hash_chk` của bảng carbon_calculations trong Supabase.
    Cùng input + cùng bộ tham số -> cùng hash, kể cả giữa các lần chạy khác nhau.
    """
    payload = "|".join(
        [activity_data.canonical_json(), scenario, params.version, ENGINE_VERSION]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -- validation -------------------------------------------------------------


def _resolve_water_regime(data: CropActivityData, scenario: str) -> str:
    """Chốt chế độ nước, sau khi kiểm tra tính hợp lệ và nhất quán của dữ liệu.

    Kiểm tra chạy kể cả khi kịch bản ghi đè: dữ liệu mâu thuẫn là lỗi nhập liệu, phải sửa
    ở nguồn chứ không né bằng cách chọn kịch bản khác.
    """
    if scenario not in SCENARIOS:
        raise InvalidWaterRegimeError(
            f"scenario '{scenario}' không hợp lệ. Chỉ nhận: {', '.join(SCENARIOS)}."
        )

    recorded = data.water_regime
    if recorded is not None and recorded not in WATER_REGIMES:
        raise InvalidWaterRegimeError(
            f"'water_regime' = '{recorded}' không hợp lệ. "
            f"Chỉ nhận: {', '.join(WATER_REGIMES)}."
        )

    if scenario != "as_recorded":
        return SCENARIO_TO_REGIME[scenario]
    if recorded is None:
        raise MissingActivityDataError(
            f"Vụ '{data.crop_season_id}' chưa có 'water_regime' nên không dùng được kịch bản "
            f"'as_recorded'. Hãy truyền 'awd' hoặc 'continuous_flooding'."
        )
    return recorded


def assert_consistent_water_records(crop_id: str, regimes: list[str]) -> str:
    """Dùng ở lớp adapter khi gộp nhiều bản ghi tưới thành một chế độ nước cấp vụ.

    Nhiều bản ghi ghi chế độ khác nhau -> lỗi, engine không tự chọn.
    """
    distinct = {r for r in regimes if r}
    if len(distinct) > 1:
        raise ConflictingWaterRegimeError(
            f"Vụ '{crop_id}' có các bản ghi tưới ghi chế độ nước mâu thuẫn: "
            f"{', '.join(sorted(distinct))}. Engine không tự chọn — hãy sửa dữ liệu nguồn."
        )
    if not distinct:
        raise MissingActivityDataError(f"Vụ '{crop_id}' không có bản ghi chế độ nước nào.")
    return distinct.pop()


def _resolve_cultivation_days(data: CropActivityData) -> int:
    """Số ngày canh tác (t trong Eq 5.1). KHÔNG có giá trị mặc định.

    `factors.ch4_rice.default_cultivation_days` (IPCC Table 5.11A) là trung bình VÙNG dùng cho
    kiểm kê quốc gia. Áp nó cho một thửa ruộng cụ thể trong báo cáo MRV cấp nông hộ là sai
    phạm vi — engine bắt buộc có ngày thực tế.
    """
    recorded = data.recorded_cultivation_days
    if recorded is None:
        raise MissingActivityDataError(
            f"Vụ '{data.crop_season_id}' thiếu số ngày canh tác: cần 'cultivation_days', hoặc cả "
            f"'sowing_date' và 'harvest_date'. Engine KHÔNG dùng giá trị mặc định vùng "
            f"(IPCC Table 5.11A) cho tính toán cấp thửa ruộng."
        )
    if recorded <= 0:
        raise MissingActivityDataError(
            f"Vụ '{data.crop_season_id}': số ngày canh tác = {recorded}, không hợp lệ."
        )
    return recorded


def _per_kg(total: float, yield_kg: float | None) -> tuple[float | None, str | None]:
    """CO2e/kg. Thiếu sản lượng -> None kèm cảnh báo, KHÔNG trả 0 (NFR-03)."""
    if yield_kg is None:
        return None, "Chưa có sản lượng nên chưa tính được CO2e/kg."
    if yield_kg <= 0:
        raise MissingActivityDataError(
            f"Sản lượng phải > 0 (đang là {yield_kg}). Khớp ràng buộc "
            f"carbon_yield_chk của bảng carbon_calculations."
        )
    return total / yield_kg, None


def _assert_no_double_counting(amendments, burned, crop_id: str) -> None:
    """Một khối rơm chỉ đi một đường: SFo hoặc đốt đồng, không bao giờ cả hai.

    IPCC Table 5.14 chú thích a loại rơm bị đốt ra khỏi SFo. Kiểm tra này chốt lại
    bất biến đó ở tầng engine.
    """
    from_straw = [a for a in amendments if a.origin.startswith("straw:")]
    burned_methods = {e.method for e in burned}
    amendment_methods = {a.origin.split(":", 1)[1] for a in from_straw}
    overlap = burned_methods & amendment_methods
    if overlap:
        raise DoubleCountingError(
            f"Vụ '{crop_id}': rơm với phương pháp {', '.join(sorted(overlap))} bị tính vào cả "
            f"SFo (điều chỉnh CH4) lẫn nguồn đốt đồng. IPCC Table 5.14 chú thích a loại rơm đốt "
            f"ra khỏi SFo."
        )


# -- cảnh báo ---------------------------------------------------------------


def _missing_record_warnings(data: CropActivityData) -> list[str]:
    """Phân biệt "không có dữ liệu" với "bằng không".

    Vụ không có bản ghi rơm rạ cho SFo = 1,0; vụ không có bản ghi phân bón cho N2O = 0.
    Hai kết quả đó chỉ đúng nếu nông dân THỰC SỰ không bón/không xử lý rơm — nếu chỉ là
    chưa nhập liệu thì con số bị thiếu. Engine không phân biệt được, nên phải nói ra.
    """
    notes: list[str] = []
    if not data.straw:
        notes.append(
            f"Vụ '{data.crop_season_id}': KHÔNG có bản ghi xử lý rơm rạ nào nên SFo = 1,0 (coi như không "
            f"bổ sung chất hữu cơ). Nếu thực tế có vùi rơm mà chưa nhập, CH4 đang bị tính thiếu."
        )
    if not data.fertilizer:
        notes.append(
            f"Vụ '{data.crop_season_id}': KHÔNG có bản ghi bón phân nào nên N2O = 0. Nếu thực tế có bón "
            f"mà chưa nhập, phát thải đang bị tính thiếu."
        )
    return notes


def _scope_warnings(data: CropActivityData, amendments) -> list[str]:
    """Nêu rõ những gì CỐ Ý không nằm trong ranh giới hệ thống."""
    notes: list[str] = []
    if data.pesticide:
        notes.append(
            f"Vụ '{data.crop_season_id}': có ghi nhận thuốc BVTV nhưng phát thải upstream của thuốc "
            f"không nằm trong ranh giới hệ thống MVP (docs/CARBON_METHOD.md — NOT_IMPLEMENTED)."
        )
    if data.seed:
        notes.append(
            f"Vụ '{data.crop_season_id}': phát thải upstream của giống không nằm trong ranh giới "
            f"hệ thống MVP."
        )
    notes.append(
        "CH4 ngoài vụ (trước gieo sạ và sau thu hoạch) không được tính: IPCC ghi rõ SFp chỉ dùng "
        "để ước tính CH4 TRONG vụ, không dùng để lượng hoá phát thải ngoài vụ."
    )
    return notes


def _provenance_warnings(breakdown: list[BreakdownEntry], params: ParameterSet) -> list[str]:
    notes: list[str] = []

    missing_source = sorted(
        {
            path
            for entry in breakdown
            for path in entry.provenance
            if not str(entry.provenance[path]).strip()
        }
    )
    if missing_source:
        notes.append("Tham số thiếu nguồn trích dẫn: " + ", ".join(missing_source) + ".")

    unverified = sorted(
        {
            f"{path} ({status})"
            for entry in breakdown
            for path, status in entry.parameter_status.items()
            if status != STATUS_VERIFIED
        }
    )
    if unverified:
        notes.append(
            "Tham số CHƯA ở trạng thái VERIFIED: "
            + ", ".join(unverified)
            + ". Kết quả không dùng được cho báo cáo chính thức."
        )

    if params.methodology.tier == 1:
        notes.append(
            f"Đang dùng IPCC Tier 1 default ({params.methodology.name}), KHÔNG phải hệ số đặc "
            f"trưng quốc gia mà quy trình MRV yêu cầu. Chưa lấy được toàn văn QĐ 4801/QĐ-BNNMT "
            f"(OI-02) — KHÔNG được gắn nhãn 'MRV-compliant' cho kết quả này."
        )
    return notes


__all__ = [
    "ENGINE_VERSION",
    "BreakdownEntry",
    "CarbonResult",
    "assert_consistent_water_records",
    "calculate_carbon",
    "compute_input_hash",
]
