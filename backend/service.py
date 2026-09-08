"""Lớp ứng dụng: nối Repository -> Carbon Engine -> Repository.

Đây là nơi DUY NHẤT biết cả hai phía. Carbon Engine không biết repository;
repository không biết Carbon Engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from carbon import CarbonResult, ParameterSet, calculate_carbon
from infrastructure.mapping import (
    breakdown_rows,
    calculation_row,
    map_crop_activity_data,
)
from infrastructure.repository import CarbonRepository


@dataclass
class CalculationOutcome:
    result: CarbonResult
    calculation_id: str | None
    persisted: bool


class CarbonService:
    """Tính CO2e cho một vụ và lưu kết quả.

    `persist=False` cho phép chạy kịch bản giả định (What-if, giai đoạn 2) mà không ghi
    vào database — engine vốn là hàm thuần nên việc này không tốn gì thêm.
    """

    def __init__(self, repository: CarbonRepository, parameters: ParameterSet) -> None:
        self._repo = repository
        self._params = parameters

    @property
    def parameters(self) -> ParameterSet:
        return self._params

    def calculate(
        self, crop_season_id: str, scenario: str = "as_recorded", *, persist: bool = True
    ) -> CalculationOutcome:
        bundle = self._repo.get_crop_bundle(crop_season_id)
        activity_data = map_crop_activity_data(bundle)

        # Mọi lỗi phương pháp luận/thiếu hệ số nổ ra từ đây — fail closed, không nuốt.
        result = calculate_carbon(activity_data, scenario, self._params)

        if not persist:
            return CalculationOutcome(result=result, calculation_id=None, persisted=False)

        factor_set_id = self._repo.resolve_factor_set_id(result.ef_config_version)
        factor_ids = self._repo.factor_ids_by_code(factor_set_id)

        calculation_id = self._repo.save_calculation(
            calculation_row(
                result,
                crop_season_id=crop_season_id,
                factor_set_id=factor_set_id,
                area_ha=activity_data.area_ha,
                cultivation_days=activity_data.recorded_cultivation_days,
                pre_season_water_regime=activity_data.pre_season_water_regime,
            ),
            breakdown_rows(result, factor_ids),
        )
        return CalculationOutcome(
            result=result, calculation_id=calculation_id, persisted=True
        )

    def latest(self, crop_season_id: str, scenario: str | None = None) -> dict[str, Any] | None:
        return self._repo.latest_calculation(crop_season_id, scenario)
