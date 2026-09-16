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

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
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
import schemas
from infrastructure.api_errors import error_detail
from infrastructure.auth import CropAccessChecker, CropAccessError, MissingAuthError, extract_bearer_token
from infrastructure.persist_access import CropPersistChecker
from infrastructure.pagination import paginate
from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository
from infrastructure.repository import CropNotFoundError, FactorSetNotFoundError
from service import (
    ActivityWriteAccessError,
    ActivityWriteService,
    CarbonService,
    CvAccessError,
    CvService,
    InvalidCropSeasonStateError,
    InvalidImageError,
    MrvExportAccessError,
    MrvExportService,
    RecommendationAccessError,
    RecommendationService,
    UnsupportedExportFormatError,
)
from infrastructure.mrv_export_repo import MrvArtifactCorruptError, MrvArtifactMissingError
from infrastructure.write_repo import IdempotencyConflictError

router = APIRouter(prefix="/v1")
logger = logging.getLogger("agricarbon.api")

Scenario = Literal["awd", "continuous_flooding", "as_recorded"]


class CalculateRequest(BaseModel):
    crop_season_id: str = Field(..., description="Scope of the cultivation calculation: crop_seasons.id")
    water_regime_scenario: Scenario = "as_recorded"


def _service() -> CarbonService:  # bị ghi đè bằng dependency_overrides trong test/main.py
    raise HTTPException(
        status_code=503,
        detail=error_detail(
            "backend_not_configured",
            "Chưa cấu hình repository. Tạo backend/.env từ .env.example "
            "(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY), hoặc chạy với repository in-memory.",
        ),
    )


def _access_checker() -> CropAccessChecker:  # bị ghi đè bằng dependency_overrides
    raise HTTPException(
        status_code=503,
        detail=error_detail(
            "auth_not_configured",
            "Chưa cấu hình kiểm tra quyền. Tạo backend/.env với SUPABASE_URL và "
            "SUPABASE_PUBLISHABLE_KEY.",
        ),
    )


def _persist_checker() -> CropPersistChecker:  # bị ghi đè bằng dependency_overrides
    raise HTTPException(
        status_code=503,
        detail=error_detail(
            "auth_not_configured",
            "Chưa cấu hình kiểm tra quyền lưu bản tính. Cần SUPABASE_URL, "
            "SUPABASE_PUBLISHABLE_KEY và SUPABASE_DB_URL.",
        ),
    )


def _read_repo(authorization: str | None = Header(default=None)) -> SupabaseReadRepository:
    """Overridden by main. Keeping token extraction here makes every read route JWT-only."""
    try:
        extract_bearer_token(authorization)
    except MissingAuthError as exc:
        raise HTTPException(status_code=401, detail=error_detail("unauthenticated", str(exc))) from exc
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Read repository chưa được cấu hình."))


def _activity_write_service() -> ActivityWriteService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Activity write repository is not configured."))


def _recommendation_service() -> RecommendationService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Recommendation service is not configured."))


def _cv_service() -> CvService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "CV service is not configured."))


def _read_or_404(callback):
    try:
        return callback()
    except (ReadNotFoundError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.")) from exc


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
            status_code=401, detail=error_detail("missing_authorization", str(exc))
        ) from exc
    try:
        checker.assert_can_access(token, crop_season_id)
    except CropAccessError as exc:
        raise HTTPException(
            status_code=404, detail=error_detail("crop_not_found", str(exc))
        ) from exc


def _require_persist_authority(
    authorization: str | None, checker: CropPersistChecker, crop_season_id: str
) -> None:
    """B4: persisting needs write authority on the crop, not just read access.

    Runs after `_require_caller`, so the header is already known to be present.
    A read-only caller gets the same 404 `crop_not_found` as an out-of-scope one.
    """
    token = extract_bearer_token(authorization)
    try:
        checker.assert_can_persist(token, crop_season_id)
    except CropAccessError as exc:
        raise HTTPException(
            status_code=404, detail=error_detail("crop_not_found", str(exc))
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
                status_code=status, detail=error_detail(code, str(exc))
            ) from exc
    logger.exception("unhandled_error request_id=%s", request_id)
    raise HTTPException(
        status_code=500,
        detail=error_detail("internal_error", "Lỗi hệ thống.", request_id=request_id),
    ) from exc


@router.post("/carbon/calculate", tags=['Carbon'])
def calculate_carbon_endpoint(
    payload: CalculateRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    service: CarbonService = Depends(_service),
    access_checker: CropAccessChecker = Depends(_access_checker),
    persist_checker: CropPersistChecker = Depends(_persist_checker),
) -> dict[str, Any]:
    """Tính CO2e cho một vụ và lưu kết quả.

    Thiếu sản lượng nhưng đủ hệ số -> vẫn trả `co2e_total_kg`, `co2e_per_kg = null`,
    kèm cảnh báo. Thiếu hệ số bắt buộc (ví dụ GWP) -> 422, KHÔNG trả 0.
    Chỉ người ghi được vụ (`private.user_can_write_crop`) mới lưu được bản tính.
    """
    request_id = str(uuid.uuid4())
    started = time.monotonic()
    _require_caller(authorization, access_checker, payload.crop_season_id)
    _require_persist_authority(authorization, persist_checker, payload.crop_season_id)

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


@router.get("/crop-seasons/{crop_season_id}/carbon", tags=['Carbon'])
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
            detail=error_detail(
                "no_calculation",
                f"Vụ '{crop_season_id}' chưa có bản tính thành công nào"
                + (f" cho kịch bản '{scenario}'" if scenario else "")
                + ". Gọi POST /v1/carbon/calculate trước.",
            ),
        )
    return row


@router.get(
    "/crop-seasons/{crop_season_id}/carbon/readiness", tags=['Carbon'],
    response_model=schemas.CarbonReadinessResponse,
)
def get_crop_carbon_readiness(
    crop_season_id: str,
    authorization: str | None = Header(default=None),
    service: CarbonService = Depends(_service),
    access_checker: CropAccessChecker = Depends(_access_checker),
) -> dict[str, Any]:
    """Những đầu vào Carbon vụ này còn thiếu, và chỗ bổ sung từng thứ.

    Lets a client say "Thiếu chế độ nước trước vụ" instead of a generic failure,
    without holding any methodology itself: the list is derived from the same
    `CropActivityData` the engine consumes. Read-only, so plain read scope is
    enough — the same callers who may view a result may see why there isn't one.
    """
    request_id = str(uuid.uuid4())
    _require_caller(authorization, access_checker, crop_season_id)
    try:
        return service.readiness(crop_season_id)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc, request_id)
        raise


@router.get("/carbon/scenarios", tags=['Carbon'], response_model=schemas.CarbonScenarioResponse)
def list_scenarios() -> dict[str, Any]:
    return {"scenarios": list(SCENARIOS)}


@router.get("/me", tags=['Auth'], response_model=schemas.MeResponse)
def get_me(repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(repo.me)


@router.get("/farmer/scope", tags=['Farms'], response_model=schemas.FarmerScopeResponse)
def get_farmer_scope(repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Farm -> plot -> crop season hierarchy the caller can read (RLS), in one call.
    Same items as /farms + /farms/{id}/plots + /plots/{id}/crop-seasons."""
    return repo.farmer_scope()


@router.get("/farms", tags=['Farms'], response_model=schemas.PaginatedResponse[schemas.FarmResponse])
def list_farms(
    page: int = 1, page_size: int = 20, repo: SupabaseReadRepository = Depends(_read_repo)
) -> dict[str, Any]:
    return paginate(repo.farms(), page, page_size)


@router.get("/farms/{farm_id}", tags=['Farms'], response_model=schemas.FarmResponse)
def get_farm(farm_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.farm(farm_id))


@router.get("/farms/{farm_id}/plots", tags=['Plots'], response_model=schemas.ItemsResponse[schemas.PlotResponse])
def list_farm_plots(farm_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.plots_for_farm(farm_id)})


@router.get("/farms/{farm_id}/crop-seasons", tags=['Crop Seasons'], response_model=schemas.ItemsResponse[schemas.CropSeasonResponse])
def list_farm_seasons(farm_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Gộp vụ của MỌI thửa trong farm — tiện cho dashboard cấp farm, không cần lặp qua từng plot."""
    return _read_or_404(lambda: {"items": repo.farm_crop_seasons(farm_id)})


@router.get("/farms/{farm_id}/metrics", tags=['Metrics'], response_model=schemas.MetricResponse)
def get_farm_metrics(farm_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.farm_metrics(farm_id))


@router.get("/plots/{plot_id}", tags=['Plots'], response_model=schemas.PlotResponse)
def get_plot(plot_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.plot(plot_id))


@router.get("/plots/{plot_id}/crop-seasons", tags=['Crop Seasons'], response_model=schemas.ItemsResponse[schemas.CropSeasonResponse])
def list_plot_seasons(plot_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.seasons_for_plot(plot_id)})


@router.get("/crop-seasons/{crop_season_id}", tags=['Crop Seasons'], response_model=schemas.CropSeasonResponse)
def get_crop_season(crop_season_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.season(crop_season_id))


@router.get("/crop-seasons/{crop_season_id}/activities", tags=['Activities'], response_model=schemas.PaginatedResponse[schemas.ActivityResponse])
def list_activities(
    crop_season_id: str, page: int = 1, page_size: int = 20,
    repo: SupabaseReadRepository = Depends(_read_repo),
) -> dict[str, Any]:
    return _read_or_404(lambda: paginate(repo.activities(crop_season_id), page, page_size))


@router.get("/activities/{activity_id}", tags=['Activities'], response_model=schemas.ActivityResponse)
def get_activity(activity_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.activity(activity_id))


def _write_or_http(callback):
    try:
        return callback()
    except ActivityWriteAccessError as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Activity not found or outside your scope.")) from exc
    except InvalidCropSeasonStateError as exc:
        raise HTTPException(status_code=422, detail=error_detail("invalid_crop_season_state", "Crop season is not open for journal writes.")) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=error_detail("duplicate_event", "Idempotency key was already used with different activity data.")) from exc


@router.post("/crop-seasons/{crop_season_id}/activities", tags=['Activities'], status_code=201, response_model=schemas.ActivityWriteResponse)
def create_activity(
    crop_season_id: str, payload: schemas.ActivityCreateRequest,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: ActivityWriteService = Depends(_activity_write_service),
) -> dict[str, Any]:
    return _write_or_http(lambda: service.create(read_repository=repo, crop_season_id=crop_season_id, request=payload))


@router.patch("/activities/{activity_id}", tags=['Activities'], response_model=schemas.ActivityWriteResponse)
def update_activity(
    activity_id: str, payload: schemas.ActivityUpdateRequest,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: ActivityWriteService = Depends(_activity_write_service),
) -> dict[str, Any]:
    return _write_or_http(lambda: service.update(read_repository=repo, activity_id=activity_id, request=payload))


@router.patch(
    "/crop-seasons/{crop_season_id}/methodology", tags=['Crop Seasons'],
    response_model=schemas.CropSeasonResponse,
)
def update_crop_season_methodology(
    crop_season_id: str, payload: schemas.CropSeasonMethodologyUpdate,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: ActivityWriteService = Depends(_activity_write_service),
) -> dict[str, Any]:
    """Record the IPCC water-regime inputs the Carbon engine reads off the season.

    Without this route the three columns could only be written by the Flutter app
    (which upserts `crop_seasons` straight through PostgREST), so a Farmer Web-only
    user could never supply SFw/SFp and never obtain a Carbon result.
    """
    return _write_or_http(
        lambda: service.update_crop_season_methodology(
            read_repository=repo, crop_season_id=crop_season_id, request=payload,
        )
    )


@router.delete("/activities/{activity_id}", tags=['Activities'], status_code=204, response_model=None)
def delete_activity(
    activity_id: str, repo: SupabaseReadRepository = Depends(_read_repo),
    service: ActivityWriteService = Depends(_activity_write_service),
) -> None:
    _write_or_http(lambda: service.delete(read_repository=repo, activity_id=activity_id))


# -- M05 recommendations --------------------------------------------------

def _recommendation_or_http(callback):
    try:
        return callback()
    except RecommendationAccessError as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Recommendation or crop season not found or outside your scope.")) from exc


@router.get("/crop-seasons/{crop_season_id}/recommendations", tags=['Recommendations'], response_model=schemas.ItemsResponse[schemas.RecommendationResponse])
def list_recommendations(crop_season_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.recommendations(crop_season_id)})


@router.post(
    "/crop-seasons/{crop_season_id}/recommendations/generate", tags=['Recommendations'],
    response_model=schemas.ItemsResponse[schemas.RecommendationResponse],
)
def generate_recommendations_endpoint(
    crop_season_id: str, repo: SupabaseReadRepository = Depends(_read_repo),
    service: RecommendationService = Depends(_recommendation_service),
) -> dict[str, Any]:
    return {"items": _recommendation_or_http(lambda: service.generate(read_repository=repo, crop_season_id=crop_season_id))}


@router.patch("/recommendations/{recommendation_id}", tags=['Recommendations'], response_model=schemas.RecommendationResponse)
def update_recommendation_status(
    recommendation_id: str, payload: schemas.RecommendationStatusUpdateRequest,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: RecommendationService = Depends(_recommendation_service),
) -> dict[str, Any]:
    return _recommendation_or_http(
        lambda: service.set_status(read_repository=repo, recommendation_id=recommendation_id, status=payload.status)
    )


# -- M03 CV Farmer integration ---------------------------------------------

def _cv_or_http(callback):
    try:
        return callback()
    except CvAccessError as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Crop season or CV result not found or outside your scope.")) from exc
    except InvalidImageError as exc:
        raise HTTPException(status_code=422, detail=error_detail(exc.code, str(exc))) from exc


@router.post("/crop-seasons/{crop_season_id}/cv/infer", tags=['CV'], response_model=schemas.CvInferenceResponse)
async def infer_leaf_image(
    crop_season_id: str, file: UploadFile = File(...),
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: CvService = Depends(_cv_service),
) -> dict[str, Any]:
    file_bytes = await file.read()
    content_type = file.content_type or ""
    return _cv_or_http(
        lambda: service.infer(read_repository=repo, crop_season_id=crop_season_id, file_bytes=file_bytes, content_type=content_type)
    )


@router.get("/crop-seasons/{crop_season_id}/cv/inferences", tags=['CV'], response_model=schemas.ItemsResponse[schemas.CvInferenceResponse])
def list_cv_inferences(
    crop_season_id: str, repo: SupabaseReadRepository = Depends(_read_repo), service: CvService = Depends(_cv_service),
) -> dict[str, Any]:
    return {"items": _cv_or_http(lambda: service.list(read_repository=repo, crop_season_id=crop_season_id))}


@router.get("/cv/inferences/{inference_id}", tags=['CV'], response_model=schemas.CvInferenceResponse)
def get_cv_inference(
    inference_id: str, repo: SupabaseReadRepository = Depends(_read_repo), service: CvService = Depends(_cv_service),
) -> dict[str, Any]:
    return _cv_or_http(lambda: service.get(read_repository=repo, inference_id=inference_id))


@router.get("/production-batches/{production_batch_id}", tags=['Production Batches'], response_model=schemas.ProductionBatchResponse)
def get_production_batch(production_batch_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Chỉ đọc, tra cứu — batch KHÔNG phải scope tính carbon (đó là crop_season)."""
    return _read_or_404(lambda: repo.production_batch(production_batch_id))


@router.get("/crop-seasons/{crop_season_id}/production-batches", tags=['Production Batches'], response_model=schemas.ItemsResponse[schemas.ProductionBatchResponse])
def list_production_batches(crop_season_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.production_batches(crop_season_id)})


@router.get("/crop-seasons/{crop_season_id}/metrics", tags=['Metrics'], response_model=schemas.MetricResponse)
def get_metrics(crop_season_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.metrics(crop_season_id))

@router.get("/organizations", tags=['Organizations'], response_model=schemas.ItemsResponse[schemas.OrganizationResponse])
def list_organizations(repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return {"items": repo.organizations()}


@router.get("/organizations/{organization_id}", tags=['Organizations'], response_model=schemas.OrganizationResponse)
def get_organization(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.organization(organization_id))


@router.get("/organizations/{organization_id}/farms", tags=['Organizations'], response_model=schemas.ItemsResponse[schemas.FarmResponse])
def list_organization_farms(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.organization_farms(organization_id)})


@router.get("/organizations/{organization_id}/summary", tags=['Organizations'], response_model=schemas.OrganizationSummaryResponse)
def organization_summary(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.organization_summary(organization_id))


@router.get("/organizations/{organization_id}/metrics", tags=['Organizations'], response_model=schemas.MetricResponse)
def get_organization_metrics(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.organization_metrics(organization_id))


@router.get("/organizations/{organization_id}/farm-performance", tags=['Organizations'], response_model=schemas.ItemsResponse[schemas.FarmPerformanceResponse])
def farm_performance(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.farm_performance(organization_id)})

@router.get("/mrv/cases", tags=['MRV'], response_model=schemas.PaginatedResponse[schemas.MrvCaseResponse])
def mrv_cases(
    page: int = 1, page_size: int = 20, repo: SupabaseReadRepository = Depends(_read_repo)
) -> dict[str, Any]:
    return paginate(repo.mrv_cases(), page, page_size)

@router.get("/mrv/cases/{mrv_case_id}", tags=['MRV'], response_model=schemas.MrvCaseResponse)
def mrv_case(mrv_case_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.mrv_case(mrv_case_id))


@router.get("/mrv/cases/{mrv_case_id}/steps", tags=['MRV'], response_model=schemas.ItemsResponse[schemas.MrvStepResponse])
def mrv_case_steps(mrv_case_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Luôn đủ 6 bước theo QĐ 4801, kể cả bước chưa có record (status='not_started')."""
    return _read_or_404(lambda: {"items": repo.mrv_steps(mrv_case_id)})


@router.get("/mrv/cases/{mrv_case_id}/batches", tags=['MRV'], response_model=schemas.ItemsResponse[schemas.MrvBatchResponse])
def mrv_case_batches(mrv_case_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Chỉ trả batch thuộc case này (qua mrv_case_batches), không phải toàn bộ batch của tổ chức."""
    return _read_or_404(lambda: {"items": repo.mrv_batches(mrv_case_id)})


@router.get("/mrv/cases/{mrv_case_id}/evidence", tags=['MRV'], response_model=schemas.ItemsResponse[schemas.MrvEvidenceResponse])
def mrv_case_evidence(mrv_case_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Metadata bằng chứng — KHÔNG trả signed URL (chưa có nhu cầu tải file qua API này)."""
    return _read_or_404(lambda: {"items": repo.mrv_evidence(mrv_case_id)})


@router.get("/mrv/cases/{mrv_case_id}/exports", tags=['MRV'], response_model=schemas.ItemsResponse[schemas.MrvExportResponse])
def mrv_case_exports(mrv_case_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.mrv_exports(mrv_case_id)})


@router.get("/mrv/exports/{mrv_export_id}", tags=['MRV'], response_model=schemas.MrvExportResponse)
def mrv_export(mrv_export_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.mrv_export(mrv_export_id))


def _mrv_export_service() -> MrvExportService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "MRV export service is not configured."))


def _mrv_export_or_http(callback):
    """One error contract, shared with the rest of the API.

    Not being allowed to see a case and the case not existing both become 404:
    an export must not be a way to discover that some organization has a case
    with a given id.
    """
    try:
        return callback()
    except MrvExportAccessError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail("not_found", "Không tìm thấy hồ sơ MRV hoặc hồ sơ không thuộc phạm vi truy cập."),
        ) from exc
    except UnsupportedExportFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "unsupported_export_format",
                "Chỉ hỗ trợ định dạng 'json' (gói dữ liệu gốc), 'xlsx' và 'pdf' (kết xuất "
                "từ gói đó). Chỉ kết xuất được từ một gói dữ liệu gốc, không từ bản kết xuất khác.",
            ),
        ) from exc
    except MrvArtifactMissingError as exc:
        # Metadata without an object. The snapshot is still intact, so this is
        # reported honestly rather than papered over by rebuilding from live
        # data -- that would return something other than the recorded snapshot.
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "export_artifact_missing",
                "Tệp kết xuất không còn trong kho lưu trữ. Gói dữ liệu gốc vẫn nguyên vẹn; "
                "hãy kết xuất lại từ gói đó.",
            ),
        ) from exc
    except MrvArtifactCorruptError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "export_artifact_integrity_failed",
                "Tệp kết xuất không khớp mã băm đã ghi nhận nên không được phục vụ.",
            ),
        ) from exc


@router.post("/mrv/cases/{mrv_case_id}/exports", tags=['MRV'], status_code=201, response_model=schemas.MrvExportCreatedResponse)
def create_mrv_export(
    mrv_case_id: str,
    payload: schemas.MrvExportRequest | None = None,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: MrvExportService = Depends(_mrv_export_service),
) -> dict[str, Any]:
    """Generate an MRV evidence package for one case: the canonical JSON snapshot,
    or that snapshot rendered as XLSX or PDF in the same call.

    The package is a snapshot of current data and its provenance. It is not a
    certification, a verification or a compliance statement, and it carries its
    own disclaimer plus machine-readable warnings for whatever is incomplete.
    """
    fmt = (payload.format if payload else "json")
    return _mrv_export_or_http(
        lambda: service.create(read_repository=repo, mrv_case_id=mrv_case_id, fmt=fmt)
    )


@router.post("/mrv/exports/{mrv_export_id}/render", tags=['MRV'], status_code=201, response_model=schemas.MrvArtifactResponse)
def render_mrv_export(
    mrv_export_id: str,
    payload: schemas.MrvRenderRequest | None = None,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: MrvExportService = Depends(_mrv_export_service),
) -> dict[str, Any]:
    """Render an artifact from an EXISTING canonical snapshot.

    The auditable path: the workbook demonstrably comes from one stored manifest
    rather than from data as it happens to look now. Nothing is reassembled and
    no carbon or resource figure is recomputed.
    """
    fmt = (payload.format if payload else "xlsx")
    return _mrv_export_or_http(
        lambda: service.render(read_repository=repo, export_id=mrv_export_id, fmt=fmt)
    )


@router.get("/mrv/exports/{mrv_export_id}/download", tags=['MRV'], response_model=None)
def download_mrv_export(
    mrv_export_id: str,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: MrvExportService = Depends(_mrv_export_service),
) -> Response:
    """Re-serve the stored artifact byte-for-byte.

    Never rebuilt from live data: an export is evidence of what the system held
    when it was generated, so a later change to the case must not change it. The
    bytes are checked against their recorded digest before being served.
    """
    data, filename, media_type = _mrv_export_or_http(
        lambda: service.download(read_repository=repo, export_id=mrv_export_id)
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/emission-factor-sets", tags=['Emission Factors'], response_model=schemas.ItemsResponse[schemas.EmissionFactorSetResponse])
def list_emission_factor_sets(repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Chỉ bộ hệ số đã published — farmer không sửa/xem bản draft."""
    return {"items": repo.emission_factor_sets()}


@router.get("/emission-factor-sets/{emission_factor_set_id}", tags=['Emission Factors'], response_model=schemas.EmissionFactorSetResponse)
def get_emission_factor_set(emission_factor_set_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: repo.emission_factor_set(emission_factor_set_id))


@router.get("/emission-factor-sets/{emission_factor_set_id}/factors", tags=['Emission Factors'], response_model=schemas.ItemsResponse[schemas.EmissionFactorResponse])
def list_emission_factors(emission_factor_set_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.emission_factors(emission_factor_set_id)})
