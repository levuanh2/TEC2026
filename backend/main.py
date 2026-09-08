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

from fastapi import FastAPI

import api
from carbon import ENGINE_VERSION, ParameterSet
from infrastructure.auth import SupabaseCropAccessChecker
from infrastructure.config import load_settings
from infrastructure.supabase_repo import SupabaseCarbonRepository
from service import CarbonService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

settings = load_settings()

app = FastAPI(title="AgriCarbon API", version="0.2.0")


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

app.include_router(api.router)


@app.get("/health")
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
