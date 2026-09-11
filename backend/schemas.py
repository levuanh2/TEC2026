"""Pydantic response models cho toàn bộ route public /v1/*.

Mục tiêu: mọi route trả `dict` tự do trước đây giờ có schema rõ trong OpenAPI,
FastAPI validate response đúng hình dạng đã tài liệu hoá. Ngoại lệ CÓ CHỦ Ý:
`CarbonCalculationResponse` dùng `extra="allow"` + field lỏng (`dict[str, Any]`)
cho phần methodology/factors_used/provenance — đây là dữ liệu tự mô tả
(self-describing) từ Carbon Engine, ép kiểu chặt sẽ phải đồng bộ lại mỗi khi
engine đổi cấu trúc breakdown, rủi ro hơn lợi ích. Không áp response_model chặt
cho 2 route carbon hiện có để không đổi hành vi đã test — vẫn giữ nguyên kiểu
trả `dict[str, Any]` ở đó, models trong file này dùng để TÀI LIỆU HOÁ OpenAPI
(qua `responses=`) chứ không siết `response_model`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ApiErrorResponse(BaseModel):
    """Hình dạng lỗi thống nhất cho MỌI route: {"detail": {"error": {...}}}."""
    error: ApiError


class ItemsResponse(BaseModel, Generic[T]):
    items: list[T]


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    has_more: bool


# -- Auth ---------------------------------------------------------------

class MeResponse(BaseModel):
    user_id: str
    full_name: str | None
    # Hàng thô từ organization_memberships/farm_members — cột phụ thuộc migration,
    # cố tình không ép kiểu chặt từng field để tránh model lệch schema DB.
    organization_memberships: list[dict[str, Any]]
    farm_memberships: list[dict[str, Any]]
    roles: list[str]


# -- Farms / Plots / Crop Seasons ---------------------------------------

class FarmResponse(BaseModel):
    id: str
    farm_code: str
    farm_name: str
    province_name: str | None = None
    district_name: str | None = None
    commune_name: str | None = None
    plot_count: int


class PlotResponse(BaseModel):
    id: str
    farm_id: str
    plot_code: str
    name: str | None = None
    area_ha: float
    latitude: float | None = None
    longitude: float | None = None


class CropSeasonResponse(BaseModel):
    id: str
    plot_id: str
    season_code: str
    crop_type: str
    variety_name: str | None = None
    planting_date: str | None = None
    expected_harvest_date: str | None = None
    actual_harvest_date: str | None = None
    status: str


class ProductionBatchResponse(BaseModel):
    id: str
    crop_season_id: str
    batch_code: str
    name: str | None = None
    started_on: str | None = None
    closed_on: str | None = None
    status: str


class ActivityResponse(BaseModel):
    id: str
    activity_type: str
    occurred_at: str
    recorded_at: str
    recorded_by: str | None = None
    source: str
    # Payload khác nhau theo activity_type (fertilizer/irrigation/harvest/...) —
    # xem DETAIL_TABLES trong infrastructure/read_repo.py cho field cụ thể từng loại.
    payload: dict[str, Any]


# -- Farmer Web online activity writes ------------------------------------

class FertilizerActivityData(BaseModel):
    fertilizer_name: str = Field(min_length=1)
    fertilizer_type: str | None = None
    amount_kg: float = Field(gt=0)
    nitrogen_percent: float | None = Field(default=None, ge=0, le=100)
    phosphorus_percent: float | None = Field(default=None, ge=0, le=100)
    potassium_percent: float | None = Field(default=None, ge=0, le=100)
    total_cost_vnd: float | None = Field(default=None, ge=0)


class IrrigationActivityData(BaseModel):
    method: Literal["awd", "continuous_flooding", "alternate", "other"]
    # Water is intentionally nullable: a recorded irrigation event without a
    # measurement remains unknown in metrics, never an invented zero.
    water_volume_m3: float | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    water_level_cm: float | None = None
    pump_energy_kwh: float | None = Field(default=None, ge=0)
    total_cost_vnd: float | None = Field(default=None, ge=0)


class HarvestActivityData(BaseModel):
    yield_kg: float = Field(gt=0)
    harvested_area_ha: float | None = Field(default=None, gt=0)
    moisture_percent: float | None = Field(default=None, ge=0, le=100)
    total_cost_vnd: float | None = Field(default=None, ge=0)


class SeedingActivityData(BaseModel):
    variety_name: str | None = None
    seed_kg: float = Field(gt=0)
    seeding_method: str | None = None
    # `seeding_events.cost_vnd`, NOT `total_cost_vnd` — the one activity type
    # whose canonical cost column is named differently (FW-2 Part 3 §6); the
    # resource-metrics cost aggregation already keys off this exact name.
    cost_vnd: float | None = Field(default=None, ge=0)


class PesticideActivityData(BaseModel):
    product_name: str = Field(min_length=1)
    active_ingredient: str | None = None
    amount: float = Field(gt=0)
    unit: str = Field(min_length=1)
    total_cost_vnd: float | None = Field(default=None, ge=0)


class StrawManagementActivityData(BaseModel):
    method: Literal["incorporated", "removed", "burned", "composted", "other"]
    straw_mass_kg: float | None = Field(default=None, ge=0)
    total_cost_vnd: float | None = Field(default=None, ge=0)
    # The three fields below are Carbon-methodology inputs (IPCC Table 5.14 /
    # Eq 5.3 / Eq 2.27), deliberately not collected by the simple Farmer Web
    # form (brief FW-2 Part 3 §25: no SFo/CFOA jargon in the UI). Left null
    # here, exactly like fertilizer's `nitrogen_percent`: the Carbon Engine
    # raises a fail-closed MethodologyGapError at *calculation* time if a
    # method that needs them (incorporated/composted/burned) is missing one,
    # rather than the write API inventing or requiring a value.
    days_before_cultivation: int | None = Field(default=None, ge=0)
    dry_matter_fraction: float | None = Field(default=None, gt=0, le=1)
    returned_to_field: bool | None = None


ActivityType = Literal["fertilizer", "irrigation", "harvest", "seeding", "pesticide", "straw_management"]


class ActivityCreateRequest(BaseModel):
    idempotency_key: UUID
    activity_type: ActivityType
    occurred_at: datetime
    note: str | None = Field(default=None, max_length=2000)
    data: dict[str, Any]

    @model_validator(mode="after")
    def validate_detail(self) -> "ActivityCreateRequest":
        validate_activity_data(self.activity_type, self.data)
        return self


class ActivityUpdateRequest(BaseModel):
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ActivityUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one mutable activity field is required.")
        return self


class ActivityWriteResponse(BaseModel):
    id: str
    crop_season_id: str
    activity_type: ActivityType
    occurred_at: datetime
    note: str | None = None
    data: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime
    idempotent_replay: bool = False


_ACTIVITY_DATA_MODELS: dict[ActivityType, type[BaseModel]] = {
    "fertilizer": FertilizerActivityData,
    "irrigation": IrrigationActivityData,
    "harvest": HarvestActivityData,
    "seeding": SeedingActivityData,
    "pesticide": PesticideActivityData,
    "straw_management": StrawManagementActivityData,
}


def validate_activity_data(activity_type: ActivityType, data: dict[str, Any]) -> BaseModel:
    return _ACTIVITY_DATA_MODELS[activity_type].model_validate(data)


class MetricResponse(BaseModel):
    yield_kg: float | None
    water_m3: float | None
    fertilizer_kg: float | None
    total_co2e_kg: float | None
    water_per_kg: float | None
    fertilizer_per_kg: float | None
    co2e_per_kg: float | None
    cost_per_kg: float | None
    data_completeness: dict[str, bool]


# -- M03 CV Farmer integration ---------------------------------------------

DiseaseLabel = Literal["rice_blast", "bacterial_leaf_blight", "brown_spot", "healthy"]


class CvInferenceResponse(BaseModel):
    id: str
    crop_season_id: str
    image_id: str
    # None exactly when `uncertain` is true — the model never gets forced
    # into one of the four labels below the confidence threshold (FR-1b-04).
    label: DiseaseLabel | None
    label_vi: str | None
    confidence: float
    uncertain: bool
    threshold_used: float
    model_version: str
    created_at: datetime


# -- M05 recommendations ---------------------------------------------------

RecommendationType = Literal["optimization", "data_task"]
RecommendationStatus = Literal["generated", "accepted", "dismissed", "expired"]
ImpactStatus = Literal["available", "unavailable"]


class RecommendationResponse(BaseModel):
    id: str
    crop_season_id: str
    rule_code: str
    rule_version: str
    engine_version: str | None = None
    type: RecommendationType
    status: RecommendationStatus
    title: str
    reason: str
    compared_to: str | None = None
    co2e_total_kg_before: float | None = None
    co2e_total_kg_after: float | None = None
    co2e_total_kg_delta: float | None = None
    co2e_percent_delta: float | None = None
    impact_status: ImpactStatus
    impact_unavailable_reason: str | None = None
    generated_at: datetime
    accepted_at: datetime | None = None
    dismissed_at: datetime | None = None


class RecommendationStatusUpdateRequest(BaseModel):
    status: Literal["accepted", "dismissed"]


# -- Organizations --------------------------------------------------------

class OrganizationResponse(BaseModel):
    id: str
    organization_code: str
    name: str
    organization_type: str
    province_name: str | None = None
    district_name: str | None = None
    commune_name: str | None = None
    is_active: bool


class OrganizationSummaryResponse(BaseModel):
    organization_id: str
    farm_count: int
    plot_count: int
    crop_season_count: int
    total_area_ha: float
    total_yield_kg: float | None
    total_co2e_kg: float | None
    co2e_per_kg: float | None


class FarmPerformanceResponse(BaseModel):
    farm_id: str
    farm_name: str
    area_ha: float
    yield_kg: float | None
    water_per_kg: float | None
    fertilizer_per_kg: float | None
    co2e_per_kg: float | None
    cost_per_kg: float | None
    data_status: Literal["complete", "partial", "missing"]


# -- Emission factors (chỉ đọc, chỉ published) -----------------------------

class EmissionFactorSetResponse(BaseModel):
    id: str
    version_code: str
    name: str
    description: str | None = None
    methodology_name: str
    methodology_version: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    source_name: str
    source_url: str | None = None
    status: str
    published_at: str | None = None


class EmissionFactorResponse(BaseModel):
    id: str
    factor_set_id: str
    factor_code: str
    category: str
    gas: str
    activity_unit: str
    result_unit: str
    factor_value: float
    source_reference: str
    notes: str | None = None


# -- Carbon (tài liệu hoá OpenAPI — KHÔNG dùng làm response_model, xem docstring) --

class CarbonBreakdownEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    source: str
    gas: str
    activity_value: float
    activity_unit: str
    gas_kg: float
    co2e_kg: float
    formula: str
    factors_used: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    parameter_status: dict[str, str] = {}


class CarbonCalculationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    crop_season_id: str
    scenario: str
    water_regime_scenario: str
    water_regime_applied: str
    total_co2e_kg: float
    co2e_total_kg: float
    yield_kg: float | None
    co2e_per_kg: float | None
    breakdown: list[CarbonBreakdownEntry]
    methodology: dict[str, Any]
    ef_config_version: str
    engine_version: str
    input_hash: str
    calculated_at: str
    warnings: list[str]
    calculation_id: str | None = None


class CarbonScenarioResponse(BaseModel):
    scenarios: list[str]


# -- MRV --------------------------------------------------------------------

class MrvStepResponse(BaseModel):
    step_no: int
    name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    notes: str | None = None


class MrvCaseResponse(BaseModel):
    case_id: str
    case_code: str
    name: str
    period_start: str
    period_end: str
    status: str
    organization_id: str
    steps: list[MrvStepResponse]
    batch_count: int
    evidence_count: int


class MrvBatchResponse(BaseModel):
    production_batch_id: str
    batch_code: str
    crop_season_id: str
    farm_id: str
    plot_id: str


class MrvEvidenceResponse(BaseModel):
    id: str
    step_no: int
    production_batch_id: str | None = None
    evidence_type: str
    file_name: str
    mime_type: str
    storage_bucket: str
    storage_object_path: str
    sha256: str | None = None
    uploaded_at: str


class MrvExportResponse(BaseModel):
    id: str
    mrv_case_id: str
    format: str
    factor_set_id: str
    scope_description: str
    data_as_of_at: str
    contains_sample_data: bool
    is_finalized: bool
    warning_text: str | None = None
    storage_bucket: str
    storage_object_path: str
    file_sha256: str | None = None
    generated_at: str


# -- Health -------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    engine_version: str
    ef_config_version: str
    methodology: dict[str, Any]
    supabase_configured: bool
    auth_configured: bool
    carbon_production_ready: bool
    mrv_compliant: bool
    note: str
