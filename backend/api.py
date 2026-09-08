"""HTTP API cho lớp 1a.

Hợp đồng bám SRS §4. Quy tắc chuyển lỗi -> HTTP giữ đúng tinh thần fail-closed:
KHÔNG có đường nào trả về một con số bịa khi thiếu dữ liệu hoặc thiếu hệ số.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from carbon import SCENARIOS
from carbon.errors import (
    ConflictingWaterRegimeError,
    DoubleCountingError,
    InvalidWaterRegimeError,
    MethodologyGapError,
    MissingActivityDataError,
    MissingEmissionFactorError,
)
from infrastructure.repository import CropNotFoundError, FactorSetNotFoundError
from service import CarbonService

router = APIRouter(prefix="/v1")

Scenario = Literal["awd", "continuous_flooding", "as_recorded"]


class CalculateRequest(BaseModel):
    crop_season_id: str = Field(..., description="Scope of the cultivation calculation: crop_seasons.id")
    water_regime_scenario: Scenario = "as_recorded"


def _service() -> CarbonService:  # bị ghi đè bằng dependency_overrides trong test
    raise HTTPException(
        status_code=503,
        detail={
            "error": "backend_not_configured",
            "message": (
                "Chưa cấu hình repository. Tạo backend/.env từ .env.example "
                "(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY), hoặc chạy với repository in-memory."
            ),
        },
    )


def _payload(result, calculation_id: str | None) -> dict[str, Any]:
    body = result.to_dict()
    body["water_regime_scenario"] = body["scenario"]  # tên cũ trong SRS §4.2
    body["co2e_total_kg"] = body["total_co2e_kg"]
    body["calculation_id"] = calculation_id
    return body


# Ánh xạ lỗi -> HTTP. 422 = dữ liệu/hệ số không đủ để tính; 409 = mâu thuẫn phải sửa ở nguồn.
_ERROR_STATUS: list[tuple[type[Exception], int, str]] = [
    (CropNotFoundError, 404, "crop_not_found"),
    (InvalidWaterRegimeError, 400, "invalid_water_regime"),
    (ConflictingWaterRegimeError, 409, "conflicting_water_records"),
    (DoubleCountingError, 409, "double_counting"),
    (MissingEmissionFactorError, 422, "missing_emission_factor"),
    (MethodologyGapError, 422, "methodology_gap"),
    (MissingActivityDataError, 422, "missing_activity_data"),
    (FactorSetNotFoundError, 503, "factor_set_not_imported"),
]


def _raise_http(exc: Exception) -> None:
    for exc_type, status, code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            raise HTTPException(
                status_code=status, detail={"error": code, "message": str(exc)}
            ) from exc
    raise


@router.post("/carbon/calculate")
def calculate_carbon_endpoint(
    payload: CalculateRequest, service: CarbonService = Depends(_service)
) -> dict[str, Any]:
    """Tính CO2e cho một vụ và lưu kết quả.

    Thiếu sản lượng nhưng đủ hệ số -> vẫn trả `co2e_total_kg`, `co2e_per_kg = null`,
    kèm cảnh báo. Thiếu hệ số bắt buộc (ví dụ GWP) -> 422, KHÔNG trả 0.
    """
    try:
        outcome = service.calculate(payload.crop_season_id, payload.water_regime_scenario)
    except Exception as exc:  # noqa: BLE001 — chuyển thành HTTP có mã lỗi rõ ràng
        _raise_http(exc)
        raise
    return _payload(outcome.result, outcome.calculation_id)


@router.get("/crop-seasons/{crop_season_id}/carbon")
def get_crop_carbon(
    crop_season_id: str,
    scenario: Scenario | None = None,
    service: CarbonService = Depends(_service),
) -> dict[str, Any]:
    """Bản tính THÀNH CÔNG gần nhất của vụ. Không trả bản tính thất bại."""
    try:
        row = service.latest(crop_season_id, scenario)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)
        raise

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_calculation",
                "message": (
                    f"Vụ '{crop_season_id}' chưa có bản tính thành công nào"
                    + (f" cho kịch bản '{scenario}'" if scenario else "")
                    + ". Gọi POST /v1/carbon/calculate trước."
                ),
            },
        )
    return row


@router.get("/carbon/scenarios")
def list_scenarios() -> dict[str, Any]:
    return {"scenarios": list(SCENARIOS)}
