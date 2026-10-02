"""AgriCarbon backend — entrypoint.

Lớp 1a (Walking Skeleton). Người B phụ trách.
Đặc tả: docs/modules/02-carbon-engine.md · docs/SRS.md §4

Luồng:
    App -> API -> [kiểm quyền qua RLS bằng JWT người gọi] -> SupabaseCarbonRepository
                                                                  -> CropActivityData
                                                                  -> Carbon Engine
                                                                       |
    App <- API <----------- carbon_calculations / carbon_breakdowns <---+
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

import api
from carbon import ENGINE_VERSION, ParameterSet
from infrastructure.api_errors import error_detail
from infrastructure.auth import SupabaseCropAccessChecker
from infrastructure.persist_access import PostgresCropPersistChecker
from infrastructure.pg_carbon_repo import PostgresCarbonRepository
from carbon.factor_register import load_parameter_file, readiness as factor_readiness
from infrastructure.config import load_settings
from infrastructure import pg_pool, supabase_clients
from infrastructure.supabase_repo import SupabaseCarbonRepository
from infrastructure.read_repo import SupabaseReadRepository
from infrastructure.write_repo import PostgresActivityWriteRepository
from infrastructure.mrv_export_repo import PostgresMrvExportRepository
from infrastructure.recommendation_repo import PostgresRecommendationRepository
from infrastructure.cv_repo import PostgresCvRepository
from infrastructure.auth import InvalidTokenError, MissingAuthError, extract_bearer_token
from infrastructure.request_context import RequestIdMiddleware
from infrastructure.season_repo import PostgresSeasonRepository
from infrastructure.provisioning_repo import PostgresProvisioningRepository
from infrastructure.auth_admin import SupabaseAuthAdmin
from service import ActivityWriteService, CarbonService, CvService, MrvExportService, PasswordChangeService, ProvisioningService, RecommendationService, SeasonService, SeasonTransitionService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

settings = load_settings()

OPENAPI_TAGS = [
    {"name": "Auth", "description": "Danh tính người gọi hiện tại (GET /v1/me)."},
    {"name": "Organizations", "description": "Tổ hợp tác/doanh nghiệp — tổng hợp theo tổ chức."},
    {"name": "Farms", "description": "Hộ/trang trại."},
    {"name": "Plots", "description": "Thửa canh tác."},
    {"name": "Crop Seasons", "description": "Vụ canh tác — scope tính carbon."},
    {"name": "Production Batches", "description": "Lô sản xuất — chỉ để truy vết, KHÔNG phải scope tính carbon."},
    {"name": "Activities", "description": "Nhật ký hoạt động canh tác đã ghi nhận."},
    {"name": "Metrics", "description": "Chỉ số tài nguyên/carbon tổng hợp theo vụ/hộ/tổ chức."},
    {"name": "Carbon", "description": "Tính và đọc kết quả CO2e (Carbon Engine)."},
    {"name": "Recommendations", "description": "Khuyến nghị canh tác có định lượng, sinh từ rule engine (M05)."},
    {"name": "CV", "description": "Nhận diện bệnh lá lúa từ ảnh (M03 baseline model, draft — chưa xác thực thực địa)."},
    {"name": "Emission Factors", "description": "Bộ hệ số phát thải đã published (chỉ đọc)."},
    {"name": "MRV", "description": "Hồ sơ MRV theo QĐ 4801/QĐ-BNNMT."},
    {"name": "Health", "description": "Trạng thái vận hành backend."},
]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Release pooled connections on shutdown.

    Both pools are opened lazily on first use, so there is nothing to do on
    startup; what matters is that a stopping process hands its hosted-Postgres
    connections and its Supabase HTTP sockets back instead of leaving them for
    a server-side timeout to reap.
    """
    yield
    pg_pool.close_all()
    supabase_clients.clear()


app = FastAPI(title="AgriCarbon API", version="0.2.0", openapi_tags=OPENAPI_TAGS, lifespan=lifespan)
app.add_middleware(RequestIdMiddleware, server_timing=settings.server_timing)
# Không có CORS thì browser chặn MỌI fetch từ React trước khi request rời đi —
# khác 401/403 (đó là backend từ chối; đây là trình duyệt không cho gọi).
# Chỉ liệt kê origin cụ thể (mặc định Vite dev) — không dùng "*" vì client gửi
# header Authorization (request "not simple", cần preflight khớp origin thật).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # FW-2 Part 1 added PATCH/DELETE activity-write routes; this list predated
    # them and was never updated, so a browser's PATCH/DELETE preflight was
    # silently rejected client-side (found via real Farmer write E2E — no
    # request ever reached the backend, so backend pytest never caught it).
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    # Diagnostic headers a browser-side profiler needs to read; both are
    # numbers/ids, not data. `Server-Timing` is only ever set when
    # AGRICARBON_SERVER_TIMING is on.
    expose_headers=["X-Request-ID", "Server-Timing"],
)


def _custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, routes=app.routes, tags=OPENAPI_TAGS
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "bearerAuth": {
            "type": "http", "scheme": "bearer", "bearerFormat": "Supabase JWT",
            "description": "Authorization: Bearer <supabase_jwt>. Backend replay JWT này qua "
            "publishable key để RLS thật quyết định quyền — xem infrastructure/auth.py.",
        }
    }
    public_paths = {"/health", "/v1/carbon/scenarios"}
    for path, methods in schema.get("paths", {}).items():
        if path in public_paths:
            continue
        for operation in methods.values():
            operation["security"] = [{"bearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[method-assign]


def _build_service() -> CarbonService:
    """Repository thật. Thiếu cấu hình -> ConfigError, KHÔNG âm thầm dùng bản in-memory.

    With the backend DB URL the pooled-Postgres repository serves the same rows
    in fewer round trips and writes a calculation atomically (Round 5.1); without
    it the PostgREST repository still works, as before.
    """
    parameters = ParameterSet.load(settings.ef_config_path)
    repository = (
        PostgresCarbonRepository(settings) if settings.supabase_db_url else SupabaseCarbonRepository(settings)
    )
    return CarbonService(repository, parameters)


if settings.supabase_configured:
    _service_singleton = _build_service()
    app.dependency_overrides[api._service] = lambda: _service_singleton

if settings.auth_configured:
    _access_checker_singleton = SupabaseCropAccessChecker(settings)
    app.dependency_overrides[api._access_checker] = lambda: _access_checker_singleton
    def _read_repo(authorization: str | None = Header(default=None)) -> SupabaseReadRepository:
        """Bind only a valid caller JWT to the read repository.

        The production dependency override must retain the default dependency's
        401 behavior.  Otherwise a missing Authorization header escapes as a
        ``MissingAuthError`` and Starlette turns it into a bare 500 response.
        """
        try:
            token = extract_bearer_token(authorization)
        except MissingAuthError as exc:
            raise HTTPException(
                status_code=401,
                detail=error_detail("unauthenticated", str(exc)),
            ) from exc
        return SupabaseReadRepository(settings, token)
    app.dependency_overrides[api._read_repo] = _read_repo

if settings.auth_configured and settings.supabase_db_url:
    # B4: persisting a Carbon calculation needs write authority on the crop.
    # Without a DB URL the dependency stays unconfigured and the route fails
    # closed (503), never falls back to read-only authorization.
    _persist_checker_singleton = PostgresCropPersistChecker(settings)
    app.dependency_overrides[api._persist_checker] = lambda: _persist_checker_singleton

if settings.auth_configured and settings.supabase_db_url:
    _activity_write_service_singleton = ActivityWriteService(PostgresActivityWriteRepository(settings))
    app.dependency_overrides[api._activity_write_service] = lambda: _activity_write_service_singleton
    _season_service_singleton = SeasonService(PostgresSeasonRepository(settings))
    app.dependency_overrides[api._season_service] = lambda: _season_service_singleton
    _season_transition_singleton = SeasonTransitionService(PostgresSeasonRepository(settings))
    app.dependency_overrides[api._season_transition_service] = lambda: _season_transition_singleton

if settings.auth_configured and settings.supabase_db_url and settings.supabase_configured:
    # The service-role key stays here, server-side: Management Web reaches the
    # Auth Admin API only through these routes.
    _provisioning_service_singleton = ProvisioningService(
        PostgresProvisioningRepository(settings), SupabaseAuthAdmin(settings)
    )
    app.dependency_overrides[api._provisioning_service] = lambda: _provisioning_service_singleton

if settings.auth_configured and settings.supabase_configured:
    # Forced first login: the same server-side Auth Admin adapter clears the
    # temporary-password flag together with the new password.
    _password_change_singleton = PasswordChangeService(SupabaseAuthAdmin(settings))
    app.dependency_overrides[api._password_change_service] = lambda: _password_change_singleton

if settings.auth_configured and settings.supabase_db_url and settings.supabase_configured:
    _recommendation_service_singleton = RecommendationService(_service_singleton, PostgresRecommendationRepository(settings))
    app.dependency_overrides[api._recommendation_service] = lambda: _recommendation_service_singleton

if settings.auth_configured and settings.supabase_db_url and settings.supabase_configured:
    # Carbon is read through the same service the carbon routes use, so the
    # export can never disagree with /v1/crop-seasons/{id}/carbon.
    _mrv_export_service_singleton = MrvExportService(
        PostgresMrvExportRepository(settings), _service_singleton
    )
    app.dependency_overrides[api._mrv_export_service] = lambda: _mrv_export_service_singleton


def _build_cv_service() -> CvService | None:
    """Load the M03 baseline checkpoint ONCE at process startup, never per
    request (brief FW M03 §8). If the artifact is missing/broken, CV routes
    fall back to 503 `backend_not_configured` — the rest of the API keeps
    working; this is not a reason to crash the whole process, and it is
    absolutely not a reason to silently retrain a replacement.
    """
    import json

    try:
        # torch/Pillow chỉ có khi môi trường cài ml/requirements.txt. Thiếu thì
        # CV tắt (503), phần còn lại của API vẫn chạy — quan trọng cho môi
        # trường nhỏ như Render Free.
        from ml.infer import find_latest_run, resolve_temperature, resolve_threshold
        from ml.model import load_checkpoint

        run_dir = find_latest_run()
        model, model_config = load_checkpoint(str(run_dir / "model.pt"), device="cpu")
        threshold = resolve_threshold(run_dir, None)
        temperature = resolve_temperature(run_dir, None)
        eval_metrics = json.loads((run_dir / "eval_metrics.json").read_text(encoding="utf-8"))
    except Exception:
        logging.getLogger("agricarbon.cv").exception("cv_model_load_failed run_dir=%s", "unresolved")
        return None

    # eval_metrics.json is the single source of truth for cv_model_versions
    # metadata (brief §16) — no value here is retyped/duplicated in backend code.
    model_meta = {
        "version_code": eval_metrics["version_code"],
        "model_name": eval_metrics["model_name"],
        "test_dataset_name": eval_metrics["test_dataset_name"],
        "test_dataset_version": eval_metrics.get("test_dataset_version"),
        "test_sample_count": eval_metrics.get("test_sample_count"),
        "accuracy": eval_metrics["accuracy"],
        "confusion_matrix": eval_metrics["confusion_matrix"],
        "confidence_threshold": eval_metrics["confidence_threshold"],
        "source_reference": eval_metrics.get("source_reference"),
    }
    return CvService(model, model_config, threshold, temperature, model_meta, PostgresCvRepository(settings))


if settings.auth_configured and settings.supabase_db_url and settings.supabase_configured:
    _cv_service_singleton = _build_cv_service()
    if _cv_service_singleton is not None:
        app.dependency_overrides[api._cv_service] = lambda: _cv_service_singleton

app.include_router(api.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI mặc định trả {"detail": [...]}  cho lỗi validate query/body — KHÁC hợp đồng
    lỗi thống nhất {"detail": {"error": {"code","message"}}} dùng ở mọi route thủ công.
    Bắt ở đây để dù lỗi đến từ Pydantic tự động (path/query param sai kiểu) hay từ code
    thủ công, response vẫn chung MỘT hình dạng."""
    return JSONResponse(
        status_code=422,
        content={"detail": error_detail(
            "validation_error", "Dữ liệu request không hợp lệ.", errors=exc.errors(),
        )},
    )


def _database_unavailable_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = []
    try:
        import psycopg
        types.append(psycopg.OperationalError)
    except Exception:  # noqa: BLE001 - psycopg is optional for a fake-only test run
        pass
    try:
        from psycopg_pool import PoolTimeout
        types.append(PoolTimeout)
    except Exception:  # noqa: BLE001
        pass
    return tuple(types)


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """No healthy database connection, or one lost mid-request.

    A controlled 503 in the shared envelope. The message never includes the
    exception text (which can carry a host name or SQL); the server log has the
    full context. It does NOT claim that nothing was saved: a connection lost
    during a write leaves the commit state unknown, so no retry happens here
    (see infrastructure/pg_pool.py)."""
    logging.getLogger("agricarbon.db").error(
        "database_unavailable method=%s path=%s error=%s", request.method, request.url.path,
        type(exc).__name__, exc_info=exc,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": error_detail(
            "database_unavailable", "Tạm thời không kết nối được cơ sở dữ liệu. Vui lòng thử lại sau ít phút.",
        )},
    )


for _exc_type in _database_unavailable_types():
    app.add_exception_handler(_exc_type, database_unavailable_handler)


@app.exception_handler(InvalidTokenError)
async def invalid_token_exception_handler(request: Request, exc: InvalidTokenError) -> JSONResponse:
    """Token sai định dạng/hết hạn phải là 401, không phải 500.

    Header đúng dạng `Bearer <...>` nên dependency cho qua; chỉ tới lúc gọi
    Supabase thật mới biết token hỏng, và lỗi đó nằm sâu trong repository. Bắt
    ở tầng app để MỌI route dùng JWT trả cùng một 401 `unauthenticated`, thay
    vì phải nhớ bọc try/except ở từng route. Chỉ lời từ chối JWT mới tới được
    đây (xem `_is_rejected_jwt`) — lỗi hạ tầng vẫn nổi lên thành 5xx thật.
    """
    return JSONResponse(
        status_code=401,
        content={"detail": error_detail("unauthenticated", str(exc))},
    )


@app.get("/health", tags=["Health"])
def health() -> dict:
    """Nói thật trạng thái. Lightweight — chỉ đọc file YAML, KHÔNG query Supabase.

    `carbon_scientific_readiness` = `carbon.factor_register.readiness` (READY_FOR_DEMO khi mọi hệ số lõi
    VERIFIED + GWP đã chọn + đơn vị khớp; READY_FOR_PILOT chỉ khi thêm rà soát chuyên gia hoàn tất).
    `carbon_production_ready` chỉ true khi READY_FOR_PILOT — tức đã có rà soát chuyên gia; hệ số đủ
    thôi là CHƯA đủ. `mrv_compliant` luôn false (chưa có hệ số QĐ 4801/QĐ-BNNMT).
    """
    raw = load_parameter_file(settings.ef_config_path)
    parameters = ParameterSet.load(settings.ef_config_path)
    carbon_readiness = factor_readiness(raw)

    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "ef_config_version": parameters.version,
        "methodology": parameters.methodology.to_dict(),
        "supabase_configured": settings.supabase_configured,
        "auth_configured": settings.auth_configured,
        "carbon_scientific_readiness": carbon_readiness,
        "carbon_production_ready": carbon_readiness["level"] == "READY_FOR_PILOT",
        "mrv_compliant": False,
        "note": (
            "Hệ số lõi IPCC 2019 Tier 1 + GWP AR5 đã đối chiếu nguồn; rà soát chuyên gia chưa có nên chưa "
            "sẵn sàng cho thí điểm. Hệ số nhiên liệu chưa xác minh. Chưa lấy được QĐ 4801/QĐ-BNNMT nên KHÔNG "
            "được gọi là MRV-compliant."
        ),
    }


# TODO(1a): POST /v1/sync — nhận batch Activity offline từ app (FR-1a-07)
# TODO(1b): GET /v1/plots/{id}/efficiency (FR-1b-05)
# TODO(1c): GET /v1/reports/mrv (FR-1c-05)


# Last statement: every route is declared above. From here on, nothing can add,
# replace or hide a route (tests/test_route_auth_inventory.py asserts it).
from infrastructure.route_freeze import freeze_routing  # noqa: E402

freeze_routing(app)
