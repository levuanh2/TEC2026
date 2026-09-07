"""Model dữ liệu đầu vào của Carbon Engine.

Dùng dataclass của stdlib — KHÔNG phụ thuộc pydantic, FastAPI, Supabase hay UI.
Semantics bám SRS §3.2 (Activity theo khung "1 phải 5 giảm").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .errors import ValidationError

# Chế độ nước thực tế ghi trên đồng ruộng.
WATER_REGIMES = ("awd", "continuous_flooding")

# Kịch bản truyền vào engine: hai chế độ trên, cộng "dùng đúng cái nông dân đã ghi".
WATER_REGIME_SCENARIOS = WATER_REGIMES + ("as_recorded",)

STRAW_METHODS = ("burned", "incorporated", "removed")


@dataclass
class Seed:
    """Hoạt động giống — "giảm giống"."""

    variety: str | None = None
    seed_rate_kg_per_ha: float | None = None
    sowing_method: str | None = None  # sạ lan / sạ hàng / cấy


@dataclass
class FertilizerApplication:
    """Một lần bón phân — "giảm phân"."""

    fertilizer_type: str
    amount_kg: float
    n_content_pct: float | None = None
    application_no: int | None = None

    @property
    def nitrogen_kg(self) -> float | None:
        """Lượng N quy đổi. None khi chưa biết hàm lượng N — KHÔNG đoán."""
        if self.n_content_pct is None:
            return None
        return self.amount_kg * self.n_content_pct / 100.0


@dataclass
class WaterRecord:
    """Bản ghi chế độ nước — "giảm nước". Biến số carbon lớn nhất."""

    regime: str
    drainage_events: int | None = None
    drainage_dates: list[str] = field(default_factory=list)
    pump_fuel_litre: float | None = None


@dataclass
class PesticideApplication:
    """Một lần phun thuốc BVTV — "giảm thuốc".

    Hiện CHƯA gắn vào công thức phát thải nào (xem CARBON_METHOD.md,
    mục NOT IMPLEMENTED). Vẫn giữ trong model để không phải đổi contract về sau.
    """

    product_group: str | None = None
    amount: float | None = None
    unit: str | None = None


@dataclass
class StrawManagement:
    """Xử lý rơm rạ."""

    method: str
    amount_kg: float | None = None


@dataclass
class Harvest:
    """Thu hoạch — "giảm thất thoát sau thu hoạch"."""

    yield_kg: float | None = None
    loss_kg: float | None = None


@dataclass
class CropActivityData:
    """Toàn bộ Activity Data của một vụ canh tác trên một thửa."""

    crop_id: str
    area_ha: float
    harvest: Harvest = field(default_factory=Harvest)
    seed: Seed | None = None
    fertilizer: list[FertilizerApplication] = field(default_factory=list)
    water: list[WaterRecord] = field(default_factory=list)
    pesticide: list[PesticideApplication] = field(default_factory=list)
    straw: StrawManagement | None = None
    cultivation_days: int | None = None
    sowing_date: str | None = None
    harvest_date: str | None = None

    @property
    def yield_kg(self) -> float | None:
        return self.harvest.yield_kg

    @property
    def flooded_days(self) -> int | None:
        """Số ngày canh tác dùng cho công thức CH4.

        Ưu tiên `cultivation_days` nhập thẳng; nếu không có thì suy từ hai mốc ngày.
        Không có cả hai → None, engine sẽ báo MissingActivityDataError.
        """
        if self.cultivation_days is not None:
            return self.cultivation_days
        if self.sowing_date and self.harvest_date:
            delta = date.fromisoformat(self.harvest_date) - date.fromisoformat(self.sowing_date)
            return delta.days
        return None

    @property
    def pump_fuel_litre(self) -> float:
        return sum(w.pump_fuel_litre or 0.0 for w in self.water)

    # -- nạp từ dict/JSON ---------------------------------------------------

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CropActivityData:
        """Nạp từ dict (fixture JSON, hoặc payload API sau này).

        Chấp nhận `water` là 1 object hoặc list object; `yield_kg` đặt ở cấp trên
        cùng hoặc trong `harvest`.
        """
        if "crop_id" not in raw or "area_ha" not in raw:
            raise ValidationError("Activity Data phải có 'crop_id' và 'area_ha'.")

        harvest_raw = dict(raw.get("harvest") or {})
        if "yield_kg" in raw:
            harvest_raw.setdefault("yield_kg", raw["yield_kg"])

        water_raw = raw.get("water") or []
        if isinstance(water_raw, dict):
            water_raw = [water_raw]

        straw_raw = raw.get("straw")

        return cls(
            crop_id=raw["crop_id"],
            area_ha=raw["area_ha"],
            harvest=Harvest(**harvest_raw),
            seed=Seed(**raw["seed"]) if raw.get("seed") else None,
            fertilizer=[FertilizerApplication(**f) for f in raw.get("fertilizer") or []],
            water=[WaterRecord(**w) for w in water_raw],
            pesticide=[PesticideApplication(**p) for p in raw.get("pesticide") or []],
            straw=StrawManagement(**straw_raw) if straw_raw else None,
            cultivation_days=raw.get("cultivation_days"),
            sowing_date=raw.get("sowing_date"),
            harvest_date=raw.get("harvest_date"),
        )
