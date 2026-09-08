"""Model dữ liệu đầu vào của Carbon Engine.

Dùng dataclass stdlib — KHÔNG phụ thuộc pydantic, FastAPI, Supabase hay UI.
Semantics bám SRS §3.2 ("1 phải 5 giảm") và các biến mà phương pháp luận IPCC đòi hỏi
(docs/CARBON_METHOD.md).

Ánh xạ từ bảng Supabase sang các model này nằm ở lớp adapter riêng, KHÔNG nằm ở đây.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from .errors import ValidationError

# --- Chế độ nước trong vụ -------------------------------------------------
# Khớp 1-1 với khoá trong factors.ch4_rice.sfw (IPCC Table 5.12, cột disaggregated).
WATER_REGIMES = (
    "irrigated_continuous_flooding",
    "irrigated_single_drainage",
    "irrigated_multiple_drainage",  # AWD nằm ở đây
    "rainfed_regular",
    "rainfed_drought_prone",
    "deep_water",
    "upland",
)

# Kịch bản truyền vào engine.
SCENARIOS = ("awd", "continuous_flooding", "as_recorded")

# Kịch bản ghi đè -> chế độ nước cụ thể.
SCENARIO_TO_REGIME = {
    "awd": "irrigated_multiple_drainage",
    "continuous_flooding": "irrigated_continuous_flooding",
}

# Ánh xạ sang enum `public.carbon_scenario` của Supabase: DB gọi là 'actual', engine gọi là
# 'as_recorded'. Hai tên cho cùng một khái niệm — KHÔNG thêm giá trị enum mới, lớp adapter
# dịch qua bảng này. Xem supabase/migrations/20260908_carbon_methodology_alignment.sql §1.5.
SCENARIO_TO_DB = {
    "as_recorded": "actual",
    "awd": "awd",
    "continuous_flooding": "continuous_flooding",
}
SCENARIO_FROM_DB = {v: k for k, v in SCENARIO_TO_DB.items()}

# --- Chế độ nước trước vụ (SFp) -------------------------------------------
# Khớp 1-1 với khoá trong factors.ch4_rice.sfp (IPCC Table 5.13, cột disaggregated).
PRE_SEASON_REGIMES = (
    "non_flooded_pre_season_lt_180d",
    "non_flooded_pre_season_gt_180d",
    "flooded_pre_season_gt_30d",
    "non_flooded_pre_season_gt_365d",
)

# --- Rơm rạ ----------------------------------------------------------------
STRAW_METHODS = ("incorporated", "removed", "burned", "composted", "other")

FUEL_TYPES = ("diesel", "gasoline", "lpg", "other")


@dataclass
class Seed:
    """Hoạt động giống — "giảm giống".

    Chưa gắn với nguồn phát thải nào (phát thải upstream, ngoài ranh giới hệ thống MVP).
    """

    variety: str | None = None
    seed_rate_kg_per_ha: float | None = None
    sowing_method: str | None = None


@dataclass
class FertilizerApplication:
    """Một lần bón phân — "giảm phân"."""

    fertilizer_type: str
    amount_kg: float
    n_content_pct: float | None = None
    application_no: int | None = None
    is_organic: bool = False

    @property
    def nitrogen_kg(self) -> float | None:
        """Lượng N quy đổi. None khi chưa biết hàm lượng N — engine KHÔNG đoán."""
        if self.n_content_pct is None:
            return None
        return self.amount_kg * self.n_content_pct / 100.0


@dataclass
class OrganicAmendment:
    """Chất hữu cơ bổ sung vào ruộng — đầu vào của SFo (IPCC Eq 5.3).

    `cfoa_key` phải khớp một khoá trong factors.ch4_rice.cfoa.
    `rate_t_per_ha` là tấn/ha, **khối lượng khô** với rơm rạ (Eq 5.3).
    """

    cfoa_key: str
    rate_t_per_ha: float
    origin: str = ""  # mô tả nguồn gốc, để truy vết trong breakdown


@dataclass
class StrawEvent:
    """Một lần xử lý rơm rạ.

    Mỗi bản ghi đi vào ĐÚNG MỘT đường: SFo (vùi/ủ trả lại ruộng), hoặc đốt đồng, hoặc
    không đường nào (mang khỏi ruộng). Không bao giờ cả hai — xem docs/CARBON_METHOD.md.
    """

    method: str
    mass_kg: float | None = None
    dry_matter_fraction: float | None = None
    days_before_cultivation: int | None = None
    returned_to_field: bool | None = None


@dataclass
class FuelUsage:
    fuel_type: str
    amount_litre: float


@dataclass
class IrrigationEvent:
    """Bản ghi tưới. `pump_energy_kwh` dành cho bơm điện (hiện chưa có hệ số lưới)."""

    water_volume_m3: float | None = None
    pump_energy_kwh: float | None = None


@dataclass
class PesticideApplication:
    """Thuốc BVTV — "giảm thuốc".

    Chưa gắn nguồn phát thải nào (upstream, ngoài ranh giới hệ thống MVP).
    """

    product_group: str | None = None
    amount: float | None = None
    unit: str | None = None


@dataclass
class Harvest:
    yield_kg: float | None = None
    loss_kg: float | None = None


@dataclass
class CropActivityData:
    """Activity Data của một vụ canh tác trên một thửa."""

    crop_season_id: str
    area_ha: float

    # Biến bắt buộc của phương pháp luận CH4
    water_regime: str | None = None
    pre_season_water_regime: str | None = None
    cultivation_days: int | None = None
    sowing_date: str | None = None
    harvest_date: str | None = None

    harvest: Harvest = field(default_factory=Harvest)
    seed: Seed | None = None
    fertilizer: list[FertilizerApplication] = field(default_factory=list)
    straw: list[StrawEvent] = field(default_factory=list)
    fuel: list[FuelUsage] = field(default_factory=list)
    irrigation: list[IrrigationEvent] = field(default_factory=list)
    pesticide: list[PesticideApplication] = field(default_factory=list)

    @property
    def yield_kg(self) -> float | None:
        return self.harvest.yield_kg

    @property
    def recorded_cultivation_days(self) -> int | None:
        """Số ngày canh tác thực tế. None khi không suy ra được — engine KHÔNG đoán."""
        if self.cultivation_days is not None:
            return self.cultivation_days
        if self.sowing_date and self.harvest_date:
            return (
                date.fromisoformat(self.harvest_date) - date.fromisoformat(self.sowing_date)
            ).days
        return None

    @property
    def total_nitrogen_kg(self) -> float:
        """Tổng kg N từ phân bón. Raise nếu có lần bón thiếu n_content_pct."""
        total = 0.0
        for application in self.fertilizer:
            nitrogen = application.nitrogen_kg
            if nitrogen is None:
                raise ValidationError(
                    f"Lần bón '{application.fertilizer_type}' của vụ '{self.crop_season_id}' thiếu "
                    f"'n_content_pct'. Phương pháp luận áp hệ số lên **kg N**, không phải kg phân — "
                    f"engine không đoán hàm lượng N."
                )
            total += nitrogen
        return total

    def canonical_json(self) -> str:
        """Chuỗi JSON chuẩn hoá, dùng để băm input (reproducibility)."""
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, default=str)

    # -- nạp từ dict/JSON ---------------------------------------------------

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CropActivityData:
        if "crop_season_id" not in raw or "area_ha" not in raw:
            raise ValidationError("Activity Data phải có 'crop_season_id' và 'area_ha'.")

        harvest_raw = dict(raw.get("harvest") or {})
        if "yield_kg" in raw:
            harvest_raw.setdefault("yield_kg", raw["yield_kg"])

        def as_list(value: Any) -> list[dict[str, Any]]:
            if not value:
                return []
            return [value] if isinstance(value, dict) else list(value)

        return cls(
            crop_season_id=raw["crop_season_id"],
            area_ha=raw["area_ha"],
            water_regime=raw.get("water_regime"),
            pre_season_water_regime=raw.get("pre_season_water_regime"),
            cultivation_days=raw.get("cultivation_days"),
            sowing_date=raw.get("sowing_date"),
            harvest_date=raw.get("harvest_date"),
            harvest=Harvest(**harvest_raw),
            seed=Seed(**raw["seed"]) if raw.get("seed") else None,
            fertilizer=[FertilizerApplication(**f) for f in as_list(raw.get("fertilizer"))],
            straw=[StrawEvent(**s) for s in as_list(raw.get("straw"))],
            fuel=[FuelUsage(**f) for f in as_list(raw.get("fuel"))],
            irrigation=[IrrigationEvent(**i) for i in as_list(raw.get("irrigation"))],
            pesticide=[PesticideApplication(**p) for p in as_list(raw.get("pesticide"))],
        )
