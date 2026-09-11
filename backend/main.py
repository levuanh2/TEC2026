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

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

import api
from carbon import ENGINE_VERSION, ParameterSet
from infrastructure.api_errors import error_detail
from infrastructure.auth import SupabaseCropAccessChecker
from infrastructure.config import load_settings
from infrastructure.supabase_repo import SupabaseCarbonRepository
from infrastructure.read_repo import SupabaseReadRepository
from infrastructure.write_repo import PostgresActivityWriteRepository
from infrastructure.auth import MissingAuthError, extract_bearer_token
from infrastructure.request_context import RequestIdMiddleware
from service import ActivityWriteService, CarbonService

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
    {"name": "Emission Factors", "description": "Bộ hệ số phát thải đã published (chỉ đọc)."},
    {"name": "MRV", "description": "Hồ sơ MRV theo QĐ 4801/QĐ-BNNMT."},
    {"name": "Health", "description": "Trạng thái vận hành backend."},
]

app = FastAPI(title="AgriCarbon API", version="0.2.0", openapi_tags=OPENAPI_TAGS)
app.add_middleware(RequestIdMiddleware)
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
    """Repository thật. Thiếu cấu hình -> ConfigError, KHÔNG âm thầm dùng bản in-memory."""
    parameters = ParameterSet.load(settings.ef_config_path)
    return CarbonService(SupabaseCarbonRepository(settings), parameters)


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
    _activity_write_service_singleton = ActivityWriteService(PostgresActivityWriteRepository(settings))
    app.dependency_overrides[api._activity_write_service] = lambda: _activity_write_service_singleton

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


@app.get("/health", tags=["Health"])
def health() -> dict:
    """Nói thật trạng thái. Lightweight — chỉ đọc file YAML, KHÔNG query Supabase.

    `carbon_production_ready` chỉ true khi GWP đã xác minh.
    """
    parameters = ParameterSet.load(settings.ef_config_path)
    try:
        parameters.gwp("ch4")
        parameters.gwp("n2o")
        gwp_ready = True
    except Exception:  # noqa: BLE001
        gwp_ready = False

    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "ef_config_version": parameters.version,
        "methodology": parameters.methodology.to_dict(),
        "supabase_configured": settings.supabase_configured,
        "auth_configured": settings.auth_configured,
        "carbon_production_ready": gwp_ready,
        "mrv_compliant": False,
        "note": (
            "GWP chưa xác minh (OI-05) nên chưa ra được CO2e thật. "
            "Chưa lấy được QĐ 4801/QĐ-BNNMT nên KHÔNG được gọi là MRV-compliant."
        ),
    }


# TODO(1a): POST /v1/sync — nhận batch Activity offline từ app (FR-1a-07)
# TODO(1b): GET /v1/plots/{id}/efficiency (FR-1b-05)
# TODO(1c): GET /v1/reports/mrv (FR-1c-05)
