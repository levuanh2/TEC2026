"""HTTP API cho lớp 1a.

Hợp đồng bám SRS §4. Quy tắc chuyển lỗi -> HTTP giữ đúng tinh thần fail-closed:
KHÔNG có đường nào trả về một con số bịa khi thiếu dữ liệu hoặc thiếu hệ số.

Quyền truy cập: backend dùng service role để ĐỌC/GHI dữ liệu carbon (đúng thiết kế
RLS gốc — "Calculations are written by trusted backend/service role"), nhưng KHÔNG tự
quyết định ai được xem gì bằng code Python. Trước khi chạm tới service-role repository,
mọi request phải qua `CropAccessChecker` — replay JWT của người gọi qua publishable key
để chính PostgREST/RLS trả lời "được" hay "không", giống hệt Flutter gọi thẳng Supabase.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
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
from infrastructure.auth import CropAccessChecker, CropAccessError, MissingAuthError, extract_bearer_token
from infrastructure.repository import CropNotFoundError, FactorSetNotFoundError
from service import CarbonService

router = APIRouter(prefix="/v1")
logger = logging.getLogger("agricarbon.api")

Scenario = Literal["awd", "continuous_flooding", "as_recorded"]


class CalculateRequest(BaseModel):
    crop_season_id: str = Field(..., description="Scope of the cultivation calculation: crop_seasons.id")
    water_regime_scenario: Scenario = "as_recorded"


def _service() -> CarbonService:  # bị ghi đè bằng dependency_overrides trong test/main.py
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


def _access_checker() -> CropAccessChecker:  # bị ghi đè bằng dependency_overrides
    raise HTTPException(
        status_code=503,
        detail={
            "error": "auth_not_configured",
            "message": (
                "Chưa cấu hình kiểm tra quyền. Tạo backend/.env với SUPABASE_URL và "
                "SUPABASE_PUBLISHABLE_KEY."
            ),
        },
    )


def _require_caller(
    authorization: str | None, checker: CropAccessChecker, crop_season_id: str
) -> None:
    """Bắt buộc JWT hợp lệ VÀ quyền đọc crop season đó, trước khi chạm service role.

    Không phân biệt "không có quyền" với "không tồn tại" -> luôn 404 cho cả hai, tránh
    lộ ra rằng một crop_season_id nào đó tồn tại nhưng thuộc về nông hộ khác.
    """
    try:
        token = extract_bearer_token(authorization)
    except MissingAuthError as exc:
        raise HTTPException(
            status_code=401, detail={"error": "missing_authorization", "message": str(exc)}
        ) from exc
    try:
        checker.assert_can_access(token, crop_season_id)
    except CropAccessError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "crop_not_found", "message": str(exc)}
        ) from exc


def _payload(result, calculation_id: str | None) -> dict[str, Any]:
    body = result.to_dict()
    body["water_regime_scenario"] = body["scenario"]  # tên cũ trong SRS §4.2
    body["co2e_total_kg"] = body["total_co2e_kg"]
    body["calculation_id"] = calculation_id
    return body


# Ánh xạ lỗi -> HTTP. 422 = dữ liệu/hệ số không đủ để tính; 409 = mâu thuẫn phải sửa ở nguồn.
# Lỗi KHÔNG có trong bảng này (bug, lỗi mạng tới Supabase, ...) rơi xuống 500 generic —
# không leak message/stack trace gốc ra response, chỉ ghi log server-side kèm request_id.
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


def _raise_http(exc: Exception, request_id: str) -> None:
    for exc_type, status, code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            raise HTTPException(
                status_code=status, detail={"error": code, "message": str(exc)}
            ) from exc
    logger.exception("unhandled_error request_id=%s", request_id)
    raise HTTPException(
        status_code=500,
        detail={"error": "internal_error", "message": "Lỗi hệ thống.", "request_id": request_id},
    ) from exc


@router.post("/carbon/calculate")
def calculate_carbon_endpoint(
    payload: CalculateRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    service: CarbonService = Depends(_service),
    access_checker: CropAccessChecker = Depends(_access_checker),
) -> dict[str, Any]:
    """Tính CO2e cho một vụ và lưu kết quả.

    Thiếu sản lượng nhưng đủ hệ số -> vẫn trả `co2e_total_kg`, `co2e_per_kg = null`,
    kèm cảnh báo. Thiếu hệ số bắt buộc (ví dụ GWP) -> 422, KHÔNG trả 0.
    """
    request_id = str(uuid.uuid4())
    started = time.monotonic()
    _require_caller(authorization, access_checker, payload.crop_season_id)

    try:
        outcome = service.calculate(payload.crop_season_id, payload.water_regime_scenario)
    except Exception as exc:  # noqa: BLE001 — chuyển thành HTTP có mã lỗi rõ ràng
        logger.info(
            "carbon_calculate_failed request_id=%s crop_season_id=%s scenario=%s "
            "error=%s duration_ms=%d",
            request_id, payload.crop_season_id, payload.water_regime_scenario,
            type(exc).__name__, (time.monotonic() - started) * 1000,
        )
        _raise_http(exc, request_id)
        raise

    logger.info(
        "carbon_calculate_ok request_id=%s crop_season_id=%s scenario=%s "
        "calculation_id=%s factor_set=%s engine_version=%s duration_ms=%d",
        request_id, payload.crop_season_id, payload.water_regime_scenario,
        outcome.calculation_id, outcome.result.ef_config_version, outcome.result.engine_version,
        (time.monotonic() - started) * 1000,
    )
    return _payload(outcome.result, outcome.calculation_id)


@router.get("/crop-seasons/{crop_season_id}/carbon")
def get_crop_carbon(
    crop_season_id: str,
    scenario: Scenario | None = None,
    authorization: str | None = Header(default=None),
    service: CarbonService = Depends(_service),
    access_checker: CropAccessChecker = Depends(_access_checker),
) -> dict[str, Any]:
    """Bản tính THÀNH CÔNG gần nhất của vụ. Không trả bản tính thất bại."""
    request_id = str(uuid.uuid4())
    _require_caller(authorization, access_checker, crop_season_id)

    try:
        row = service.latest(crop_season_id, scenario)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc, request_id)
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
