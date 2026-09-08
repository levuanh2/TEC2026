"""Repository: hợp đồng đọc/ghi + bản in-memory dùng cho test và phát triển offline.

Carbon Engine KHÔNG import module này. Chiều phụ thuộc luôn là:

    Repository -> CropActivityData -> Carbon Engine

không bao giờ ngược lại.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from carbon import SCENARIO_TO_DB
from carbon.errors import CarbonEngineError

from .mapping import RawCropBundle


class FactorSetNotFoundError(CarbonEngineError):
    """Bộ hệ số của YAML chưa được import vào Supabase.

    YAML là nguồn sự thật duy nhất cho giá trị hệ số; bảng Supabase chỉ là bản sao có
    kiểm soát để bản tính liên kết được `factor_set_id`. Không có bản sao đó thì không
    ghi được kết quả — chứ KHÔNG tự tạo bộ hệ số rỗng.
    """


class CropNotFoundError(CarbonEngineError):
    """Không tìm thấy vụ canh tác."""


class CarbonRepository(Protocol):
    """Hợp đồng tối thiểu cho lớp 1a."""

    def get_crop_bundle(self, crop_season_id: str) -> RawCropBundle: ...

    def resolve_factor_set_id(self, version_code: str) -> str: ...

    def factor_ids_by_code(self, factor_set_id: str) -> dict[str, str]: ...

    def save_calculation(
        self, calculation: dict[str, Any], breakdowns: list[dict[str, Any]]
    ) -> str: ...

    def latest_calculation(
        self, crop_season_id: str, scenario: str | None = None
    ) -> dict[str, Any] | None: ...


@dataclass
class InMemoryCarbonRepository:
    """Bản in-memory. Dùng cho unit/integration test và chạy backend khi chưa có Supabase.

    KHÔNG phải mock giả lập sơ sài: nó giữ đúng các bất biến mà DB thật áp — chỉ trả bản
    tính `succeeded`, và từ chối bộ hệ số chưa import.
    """

    bundles: dict[str, RawCropBundle] = field(default_factory=dict)
    factor_sets: dict[str, str] = field(default_factory=dict)  # version_code -> id
    factors: dict[str, dict[str, str]] = field(default_factory=dict)  # set_id -> code -> id
    calculations: list[dict[str, Any]] = field(default_factory=list)
    breakdowns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _seq: int = 0

    def get_crop_bundle(self, crop_season_id: str) -> RawCropBundle:
        bundle = self.bundles.get(crop_season_id)
        if bundle is None:
            raise CropNotFoundError(f"Không tìm thấy vụ canh tác '{crop_season_id}'.")
        return bundle

    def resolve_factor_set_id(self, version_code: str) -> str:
        set_id = self.factor_sets.get(version_code)
        if set_id is None:
            raise FactorSetNotFoundError(
                f"Chưa có emission_factor_set nào ở trạng thái published với version_code "
                f"'{version_code}'. Import bộ hệ số từ YAML trước khi ghi kết quả."
            )
        return set_id

    def factor_ids_by_code(self, factor_set_id: str) -> dict[str, str]:
        return self.factors.get(factor_set_id, {})

    def save_calculation(
        self, calculation: dict[str, Any], breakdowns: list[dict[str, Any]]
    ) -> str:
        self._seq += 1
        calc_id = f"calc-{self._seq:04d}"
        row = {**calculation, "id": calc_id}
        row["co2e_per_kg"] = (
            row["total_co2e_kg"] / row["yield_kg"] if row.get("yield_kg") else None
        )
        self.calculations.append(row)
        self.breakdowns[calc_id] = [{**b, "calculation_id": calc_id} for b in breakdowns]
        return calc_id

    def latest_calculation(
        self, crop_season_id: str, scenario: str | None = None
    ) -> dict[str, Any] | None:
        db_scenario = SCENARIO_TO_DB.get(scenario, scenario) if scenario else None
        rows = [
            r
            for r in self.calculations
            if r.get("crop_season_id") == crop_season_id
            and r.get("status") == "succeeded"  # không trả bản tính thất bại
            and (db_scenario is None or r.get("scenario") == db_scenario)
        ]
        if not rows:
            return None
        latest = max(rows, key=lambda r: str(r.get("calculated_at")))
        return {**latest, "breakdown": self.breakdowns.get(latest["id"], [])}
