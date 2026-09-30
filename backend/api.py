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

import contextlib
import contextvars
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
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
from infrastructure import profiling
from infrastructure.api_errors import error_detail
from infrastructure.auth import CropAccessChecker, CropAccessError, MissingAuthError, extract_bearer_token
from infrastructure.persist_access import CropPersistChecker
from infrastructure.pagination import paginate
from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository
from infrastructure.repository import CropNotFoundError, FactorSetNotFoundError
from infrastructure.mapping import CALCULATION_KIND
from service import (
    ActivityWriteAccessError,
    ActivityWriteService,
    CarbonService,
    CvAccessError,
    CvService,
    HarvestAreaExceedsPlotError,
    InvalidCropSeasonStateError,
    InvalidImageError,
    MrvExportAccessError,
    MrvExportService,
    RecommendationAccessError,
    ProvisioningFailedError,
    ProvisioningService,
    RecommendationService,
    SeasonService,
    SeasonTransitionService,
    UnsupportedExportFormatError,
)
from infrastructure.mrv_export_repo import MrvArtifactCorruptError, MrvArtifactMissingError
from infrastructure.season_repo import ActiveSeasonExistsError, IllegalSeasonTransitionError, SeasonCodeTakenError, SeasonScopeError
from infrastructure.provisioning_repo import (
    AccountExistsError,
    FarmCodeTakenError,
    FarmerAlreadyMemberError,
    MembershipInactiveError,
    PlotCodeTakenError,
    ProvisioningScopeError,
)
from infrastructure.write_repo import IdempotencyConflictError, SeasonNotOpenError

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


def _season_service() -> SeasonService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Crop season write repository is not configured."))


def _season_transition_service() -> SeasonTransitionService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Crop season write repository is not configured."))


def _recommendation_service() -> RecommendationService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Recommendation service is not configured."))


def _cv_service() -> CvService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "CV service is not configured."))


def _read_or_404(callback):
    try:
        return callback()
    except (ReadNotFoundError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.")) from exc


def _require_bearer(authorization: str | None = Header(default=None)) -> None:
    """Route-level: a caller with no token gets 401 before body validation (422)
    or an unconfigured-service 503. Carbon keeps its `missing_authorization` code."""
    try:
        extract_bearer_token(authorization)
    except MissingAuthError as exc:
        raise HTTPException(
            status_code=401, detail=error_detail("missing_authorization", str(exc))
        ) from exc


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
    authorization: str | None, checker: CropPersistChecker, crop_season_id: str, **resolved: Any,
) -> None:
    """B4: persisting needs write authority on the crop, not just read access.

    Runs after `_require_caller`, so the header is already known to be present.
    A read-only caller gets the same 404 `crop_not_found` as an out-of-scope one.
    """
    token = extract_bearer_token(authorization)
    try:
        checker.assert_can_persist(token, crop_season_id, **resolved)
    except CropAccessError as exc:
        raise HTTPException(
            status_code=404, detail=error_detail("crop_not_found", str(exc))
        ) from exc


def _require_caller_and_persist_authority(
    authorization: str | None, access_checker: CropAccessChecker,
    persist_checker: CropPersistChecker, crop_season_id: str,
) -> None:
    """Read scope, then write authority — with the identity lookup overlapped.

    The write check needs the Auth server's answer to "who is this JWT"; that
    round trip does not depend on the RLS read check, so it runs while the read
    check is in flight (Round 5.1: every sequential trip here cost 250–300 ms
    of each calculation). The write rule itself is still evaluated only after
    the read check passed, so an out-of-scope caller never reaches it, and a
    caller failing both still gets the read check's error.
    """
    resolve = getattr(persist_checker, "verified_user_id", None)
    try:
        token = extract_bearer_token(authorization)
    except MissingAuthError:
        resolve = None  # `_require_caller` below turns this into the 401
    if resolve is None:
        _require_caller(authorization, access_checker, crop_season_id)
        _require_persist_authority(authorization, persist_checker, crop_season_id)
        return

    def timed_resolve(value: str) -> Any:
        with profiling.phase("auth identity"):
            return resolve(value)

    with ThreadPoolExecutor(max_workers=1) as pool:
        identity = pool.submit(contextvars.copy_context().run, timed_resolve, token)
        try:
            with profiling.phase("auth read check"):
                _require_caller(authorization, access_checker, crop_season_id)
        finally:
            with profiling.phase("auth identity wait"):
                identity.exception()  # always wait: nothing outlives the request
    with profiling.phase("auth write check"):
        _require_persist_authority(authorization, persist_checker, crop_season_id, user_id=identity.result())


def _json_ready(body: dict[str, Any]) -> dict[str, Any]:
    """Exactly what the route's JSONResponse will do to `body`, done early.

    The Carbon route has no `response_model`; FastAPI runs `jsonable_encoder`
    and Starlette `json.dumps(..., allow_nan=False)` after the route returns.
    Doing both here, before the calculation is stored, means a NaN/inf or an
    unencodable value fails the request with nothing saved.
    """
    encoded = jsonable_encoder(body)
    json.dumps(encoded, ensure_ascii=False, allow_nan=False)
    return encoded


def _payload(result, calculation_id: str | None) -> dict[str, Any]:
    body = result.to_dict()
    body["water_regime_scenario"] = body["scenario"]  # tên cũ trong SRS §4.2
    body["co2e_total_kg"] = body["total_co2e_kg"]
    body["calculation_id"] = calculation_id
    body["calculation_kind"] = CALCULATION_KIND.get(body["scenario"], "scenario")
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


@router.post("/carbon/calculate", tags=['Carbon'], dependencies=[Depends(_require_bearer)])
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
    # One database connection for the write check, the read and the save
    # (Round 5.1); a service without a session behaves exactly as before.
    session = getattr(service, "session", None)
    resolve = getattr(persist_checker, "verified_user_id", None)
    authorize_in_read = resolve is not None and getattr(service, "can_authorize_reads", lambda: False)()
    token: str | None = None
    if authorize_in_read:
        try:
            token = extract_bearer_token(authorization)
        except MissingAuthError:
            _require_caller(authorization, access_checker, payload.crop_season_id)  # the standard 401
            raise
    with contextlib.ExitStack() as stack:
        identity = None
        if authorize_in_read:
            # Round 5.1: ask Auth who the caller is while the pooled connection
            # is being checked out; the read and write rules then run inside
            # Postgres in the same round trip as the bundle read (see
            # `PostgresCarbonRepository.get_crop_bundle_as`), instead of a
            # PostgREST read check, a write check and a read in sequence.
            pool = stack.enter_context(ThreadPoolExecutor(max_workers=1))

            def timed_resolve(value: str) -> Any:
                with profiling.phase("auth identity"):
                    return resolve(value)

            identity = pool.submit(contextvars.copy_context().run, timed_resolve, token)
        stack.enter_context(session() if session is not None else contextlib.nullcontext())
        caller: str | None = None
        if identity is not None:
            with profiling.phase("auth identity wait"):
                caller = identity.result()  # InvalidTokenError -> the standard 401
            if not caller:
                raise HTTPException(status_code=404, detail=error_detail(
                    "crop_not_found", f"'{payload.crop_season_id}' không tồn tại hoặc không thuộc phạm vi "
                                      "truy cập của người dùng hiện tại."))
        else:
            _require_caller_and_persist_authority(authorization, access_checker, persist_checker, payload.crop_season_id)

        try:
            # Serialized before `save_calculation` writes anything; only the new id
            # is added afterwards, which cannot make valid JSON invalid.
            outcome = service.calculate(
                payload.crop_season_id, payload.water_regime_scenario,
                prepare=lambda result: _json_ready(_payload(result, None)),
                **({"caller": caller} if caller is not None else {}),
            )
        except CropAccessError as exc:
            # Same 404 as the separate read/write checks gave: a caller never
            # learns which rule refused, or whether the season exists.
            raise HTTPException(status_code=404, detail=error_detail("crop_not_found", str(exc))) from exc
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
    return {**outcome.prepared, "calculation_id": outcome.calculation_id}


@router.get("/crop-seasons/{crop_season_id}/carbon", tags=['Carbon'], dependencies=[Depends(_require_bearer)])
def get_crop_carbon(
    crop_season_id: str,
    scenario: Scenario = "as_recorded",
    authorization: str | None = Header(default=None),
    service: CarbonService = Depends(_service),
    access_checker: CropAccessChecker = Depends(_access_checker),
) -> dict[str, Any]:
    """Bản tính THÀNH CÔNG gần nhất của vụ CHO ĐÚNG KỊCH BẢN. Không trả bản tính thất bại.

    Mặc định `as_recorded` = kết quả vận hành chính thức của vụ. AWD và ngập liên
    tục là kịch bản mô phỏng, chỉ trả khi hỏi đích danh (`?scenario=awd`) — tính
    một kịch bản sau không bao giờ thay kết quả vận hành trong câu trả lời mặc định.
    `calculation_kind` cho biết "actual" hay "scenario".
    """
    request_id = str(uuid.uuid4())
    _require_caller(authorization, access_checker, crop_season_id)

    try:
        row = service.stored(crop_season_id, scenario)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc, request_id)
        raise

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "no_calculation",
                f"Vụ '{crop_season_id}' chưa có bản tính thành công nào"
                + f" cho kịch bản '{scenario}'"
                + ". Gọi POST /v1/carbon/calculate trước.",
            ),
        )
    return row


@router.get(
    "/crop-seasons/{crop_season_id}/carbon/readiness", tags=['Carbon'], dependencies=[Depends(_require_bearer)],
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


def _error_body(exc: Exception, request_id: str) -> dict[str, str]:
    """The `{code, message}` the per-season route would have answered with."""
    for exc_type, _status, code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            return {"code": code, "message": str(exc)}
    logger.error("carbon_status_part_failed request_id=%s error=%s", request_id, type(exc).__name__,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return {"code": "internal_error", "message": f"Lỗi hệ thống. (request_id={request_id})"}


@router.get(
    "/organizations/{organization_id}/carbon-status", tags=['Carbon'],
    response_model=schemas.CarbonStatusBatchResponse,
)
def organization_carbon_status(
    organization_id: str,
    crop_season_id: list[str] | None = Query(default=None, description="Optional: only these seasons."),
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: CarbonService = Depends(_service),
) -> dict[str, Any]:
    """Carbon readiness and the actual result of every season of an organization, in one request.

    Replaces one readiness + one result request PER SEASON on the Management
    screens. Scope is decided by RLS with the caller's JWT, exactly like the
    per-season routes: only seasons of this organization the caller can read
    are listed, and asking for any other id simply leaves it out. A missing
    token is the standard 401 `unauthenticated` (from `_read_repo`), not the
    legacy Carbon `missing_authorization` (EXC-API-02 covers only the three
    per-season Carbon routes Flutter maps). Each item
    equals what the per-season endpoints return for that season; one season
    failing never changes another's answer.
    """
    request_id = str(uuid.uuid4())
    visible = _read_or_404(lambda: repo.organization_season_ids(organization_id))
    if crop_season_id:
        wanted = set(crop_season_id)
        visible = [sid for sid in visible if sid in wanted]
    status = service.status_many(visible)
    items = []
    for sid in visible:
        part = status[sid]
        item: dict[str, Any] = {"crop_season_id": sid}
        readiness, actual = part.get("readiness"), part.get("actual")
        if isinstance(readiness, Exception):
            item["readiness_error"] = _error_body(readiness, request_id)
        else:
            item["readiness"] = readiness
        if isinstance(actual, Exception):
            item["actual_error"] = _error_body(actual, request_id)
        else:
            item["actual"] = _json_ready(actual) if actual is not None else None
        items.append(item)
    return {"organization_id": organization_id, "items": items}


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


@router.post(
    "/plots/{plot_id}/crop-seasons", tags=['Crop Seasons'], status_code=201,
    response_model=schemas.CropSeasonCreateResponse,
)
def create_crop_season(
    plot_id: str, payload: schemas.CropSeasonCreateRequest, response: Response,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: SeasonService = Depends(_season_service),
) -> dict[str, Any]:
    """Start a crop season on a plot, with its default production batch.

    Both rows are written in one transaction, so a season returned here can take
    activities immediately. Allowed for a farm owner/editor and for an active
    cooperative manager of the farm's cooperative (`private.user_can_write_farm`);
    anyone else -- and a plot that does not exist -- gets the same 404.
    Repeating the exact same request returns the season it created (200,
    `idempotent_replay: true`) instead of a second season.
    """
    try:
        body = service.create(read_repository=repo, plot_id=plot_id, request=payload)
    except SeasonScopeError as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.")) from exc
    except ActiveSeasonExistsError as exc:
        raise HTTPException(status_code=409, detail=error_detail("active_season_exists", "Thửa này đang có một vụ đang canh tác. Kết thúc vụ đó trước khi bắt đầu vụ mới.")) from exc
    except SeasonCodeTakenError as exc:
        raise HTTPException(status_code=409, detail=error_detail("season_code_exists", "Thửa này đã có một vụ với mã này. Hãy dùng mã vụ khác.")) from exc
    if body["idempotent_replay"]:
        response.status_code = 200
    return body


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
    except (InvalidCropSeasonStateError, SeasonNotOpenError) as exc:
        # SeasonNotOpenError: the same rule, re-checked under a lock inside the
        # write transaction (a season closed after the service's first read).
        raise HTTPException(status_code=422, detail=error_detail("invalid_crop_season_state", "Crop season is not open for journal writes.")) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=error_detail("duplicate_event", "Idempotency key was already used with different activity data.")) from exc
    except HarvestAreaExceedsPlotError as exc:
        raise HTTPException(status_code=422, detail=error_detail(
            "harvested_area_exceeds_plot", str(exc), field="harvested_area_ha", plot_area_ha=exc.plot_area_ha,
        )) from exc


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


@router.patch(
    "/crop-seasons/{crop_season_id}/status", tags=['Crop Seasons'],
    response_model=schemas.CropSeasonResponse,
)
def update_crop_season_status(
    crop_season_id: str, payload: schemas.CropSeasonStatusUpdate,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: SeasonTransitionService = Depends(_season_transition_service),
) -> dict[str, Any]:
    """End a season: `active -> harvested | closed`, `harvested -> closed`.

    After it the journal is read-only for every client (the database refuses
    activity writes to a season that is not active); metrics, Carbon results
    and methodology stay as they are. A season is never reopened here.
    Writers only (`private.user_can_write_crop`); anyone else gets 404.
    """
    try:
        return service.transition(read_repository=repo, crop_season_id=crop_season_id, request=payload)
    except SeasonScopeError as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.")) from exc
    except IllegalSeasonTransitionError as exc:
        raise HTTPException(status_code=409, detail=error_detail("illegal_crop_season_transition", "Vụ này không thể chuyển sang trạng thái đó; vụ đã kết thúc không mở lại được.")) from exc


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


@router.get(
    "/organizations/{organization_id}/plots-seasons", tags=['Organizations'],
    response_model=schemas.OrganizationPlotsSeasonsResponse,
)
def organization_plots_seasons(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Plots and crop seasons of every farm of the organization, in one request.

    Replaces `/farms/{id}/plots` + `/farms/{id}/crop-seasons` PER FARM on the
    Management screens (Round 5.1). RLS decides scope, as for those routes; each
    item is exactly what they return for that farm.
    """
    return _read_or_404(lambda: {
        "organization_id": organization_id,
        "items": repo.organization_plots_and_seasons(organization_id),
    })


@router.get(
    "/organizations/{organization_id}/mrv-batches", tags=['MRV'],
    response_model=schemas.OrganizationMrvBatchesResponse,
)
def organization_mrv_batches(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    """Every MRV case of the organization with its batches, in one request.

    Replaces `/mrv/cases` + `/mrv/cases/{id}/batches` PER CASE on the Management
    screens (Round 5.1); the request count no longer grows with the number of
    cases, and no case is lost past the first page. RLS decides scope.
    """
    return _read_or_404(lambda: {
        "organization_id": organization_id,
        "items": repo.organization_mrv_batches(organization_id),
    })


@router.get("/organizations/{organization_id}/farm-performance", tags=['Organizations'], response_model=schemas.ItemsResponse[schemas.FarmPerformanceResponse])
def farm_performance(organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo)) -> dict[str, Any]:
    return _read_or_404(lambda: {"items": repo.farm_performance(organization_id)})

# -- Management: farmer provisioning ------------------------------------------

def _provisioning_service() -> ProvisioningService:
    raise HTTPException(status_code=503, detail=error_detail("backend_not_configured", "Farmer provisioning is not configured."))


_PROVISIONING_CONFLICTS: list[tuple[type[Exception], str, str]] = [
    (FarmerAlreadyMemberError, "farmer_already_member", "Email này đã là tài khoản thành viên của HTX. Tìm nông hộ trong danh sách thay vì tạo mới."),
    (MembershipInactiveError, "membership_inactive", "Email này thuộc một thành viên đã ngừng tham gia HTX. Việc kích hoạt lại cần quản trị hệ thống thực hiện."),
    # Deliberately says nothing about where the account belongs.
    (AccountExistsError, "account_exists", "Email này đã được dùng cho một tài khoản khác. Dùng email khác hoặc liên hệ quản trị hệ thống."),
    (FarmCodeTakenError, "farm_code_exists", "HTX đã có nông hộ với mã này. Hãy dùng mã hộ khác."),
    (PlotCodeTakenError, "plot_code_exists", "Nông hộ đã có thửa với mã này. Hãy dùng mã thửa khác."),
]


def _provisioning_or_http(callback):
    try:
        return callback()
    except ProvisioningScopeError as exc:
        raise HTTPException(status_code=404, detail=error_detail("not_found", "Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.")) from exc
    except ProvisioningFailedError as exc:
        if exc.compensated:
            raise HTTPException(status_code=500, detail=error_detail(
                "provisioning_failed", "Chưa tạo được tài khoản nông hộ. Không có dữ liệu nào được lưu; hãy thử lại.")) from exc
        raise HTTPException(status_code=500, detail=error_detail(
            "provisioning_incomplete",
            "Chưa tạo được tài khoản nông hộ. Có thể còn một tài khoản đăng nhập chưa thuộc HTX (đã khoá nếu hệ thống khoá được); báo quản trị hệ thống kiểm tra.")) from exc
    except tuple(t for t, _, _ in _PROVISIONING_CONFLICTS) as exc:
        code, message = next((c, m) for t, c, m in _PROVISIONING_CONFLICTS if isinstance(exc, t))
        raise HTTPException(status_code=409, detail=error_detail(code, message)) from exc


@router.get(
    "/organizations/{organization_id}/farmers", tags=['Organizations'],
    response_model=schemas.ItemsResponse[schemas.FarmerListItem],
)
def list_organization_farmers(
    organization_id: str, repo: SupabaseReadRepository = Depends(_read_repo),
    service: ProvisioningService = Depends(_provisioning_service),
) -> dict[str, Any]:
    """Farmer accounts of the cooperative with their onboarding stage.
    Active cooperative manager of this cooperative only; anyone else 404."""
    return {"items": _provisioning_or_http(lambda: service.list_farmers(read_repository=repo, organization_id=organization_id))}


@router.post(
    "/organizations/{organization_id}/farmers", tags=['Organizations'], status_code=201,
    response_model=schemas.FarmerProvisionResponse,
)
def provision_farmer(
    organization_id: str, payload: schemas.FarmerProvisionRequest, response: Response,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: ProvisioningService = Depends(_provisioning_service),
) -> dict[str, Any]:
    """Create a farmer account in the cooperative ("Thêm nông hộ"), optionally
    with the farm (the farmer as owner) and its first plot.

    There is no public sign-up: accounts are provisioned here, server-side,
    with a temporary password returned ONCE for the manager to hand over.
    """
    # The body carries a password: no cache may keep it.
    response.headers["Cache-Control"] = "no-store"
    return _provisioning_or_http(lambda: service.provision(read_repository=repo, organization_id=organization_id, request=payload))


@router.post(
    "/organizations/{organization_id}/farms", tags=['Organizations'], status_code=201,
    response_model=schemas.FarmCreatedResponse,
)
def create_organization_farm(
    organization_id: str, payload: schemas.FarmCreateRequest,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: ProvisioningService = Depends(_provisioning_service),
) -> dict[str, Any]:
    """A farm for a farmer who already belongs to the cooperative (owner)."""
    return _provisioning_or_http(lambda: service.create_farm(read_repository=repo, organization_id=organization_id, request=payload))


@router.post("/farms/{farm_id}/plots", tags=['Plots'], status_code=201, response_model=schemas.PlotCreatedResponse)
def create_farm_plot(
    farm_id: str, payload: schemas.PlotCreateRequest,
    repo: SupabaseReadRepository = Depends(_read_repo),
    service: ProvisioningService = Depends(_provisioning_service),
) -> dict[str, Any]:
    """Record a plot on a farm. Cooperative manager of the farm's cooperative
    only: the official plot structure is the cooperative's, so a farm owner
    cannot add plots here even though RLS would let them."""
    return _provisioning_or_http(lambda: service.create_plot(read_repository=repo, farm_id=farm_id, request=payload))


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
