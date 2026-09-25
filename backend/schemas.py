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

from datetime import date, datetime
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


def success_payload(model: type[BaseModel], raw: Any) -> dict[str, Any]:
    """Validate AND JSON-serialize a write's success representation.

    Write repositories call this (through a `prepare` callback) *inside* their
    transaction, before it commits. FastAPI's `response_model` check runs only
    after the route returns — after the commit — so a representation it rejects
    used to surface as a 500 for data that had already been saved. What this
    returns is plain JSON data, so the route's own later check cannot fail on it.
    """
    return model.model_validate(raw).model_dump(mode="json")


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
    # IPCC methodology inputs the Carbon engine reads off the season itself.
    # Null means "not recorded yet" — never a default; the engine refuses to
    # calculate rather than assume a water regime.
    ipcc_water_regime: str | None = None
    pre_season_water_regime: str | None = None
    cultivation_days: int | None = None


class CropSeasonCreateRequest(BaseModel):
    """POST body for starting a crop season on a plot.

    Only what a farmer knows when starting a season. The plot comes from the URL;
    crop type keeps the column default (rice); status is not chosen by the
    client -- starting a season makes it `active`; the default production batch
    is created by the server. IPCC methodology inputs are recorded later through
    `PATCH /crop-seasons/{id}/methodology`, never defaulted here.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    season_code: str = Field(min_length=1, max_length=64)
    variety_name: str | None = Field(default=None, max_length=120)
    planting_date: date | None = None
    expected_harvest_date: date | None = None

    @model_validator(mode="after")
    def check(self) -> "CropSeasonCreateRequest":
        if self.variety_name == "":
            self.variety_name = None
        # Same rule as `crop_seasons_harvest_dates_chk`, answered as a 422
        # before the database has to refuse it.
        if self.planting_date and self.expected_harvest_date and self.expected_harvest_date < self.planting_date:
            raise ValueError("expected_harvest_date must not be before planting_date.")
        return self


class CropSeasonCreateResponse(CropSeasonResponse):
    #: Present on every successful create: the season can take activities now.
    default_production_batch_id: str
    #: True when this exact season already existed (a repeated submit).
    idempotent_replay: bool = False


# These two mirror `carbon.models.WATER_REGIMES` / `PRE_SEASON_REGIMES` and the
# `public.ipcc_water_regime` / `ipcc_pre_season_regime` enums. All three must stay
# in step; `test_crop_season_methodology.py` fails if they ever drift apart.
IpccWaterRegime = Literal[
    "irrigated_continuous_flooding",
    "irrigated_single_drainage",
    "irrigated_multiple_drainage",
    "rainfed_regular",
    "rainfed_drought_prone",
    "deep_water",
    "upland",
]
IpccPreSeasonRegime = Literal[
    "non_flooded_pre_season_lt_180d",
    "non_flooded_pre_season_gt_180d",
    "flooded_pre_season_gt_30d",
    "non_flooded_pre_season_gt_365d",
]


class CropSeasonMethodologyUpdate(BaseModel):
    """PATCH body for the season's IPCC methodology inputs.

    Every field is optional so a client may set one at a time, but an omitted
    field is left alone while an explicit `null` clears it — the two are not the
    same, and `model_fields_set` is what tells them apart.
    """
    model_config = ConfigDict(extra="forbid")

    ipcc_water_regime: IpccWaterRegime | None = None
    pre_season_water_regime: IpccPreSeasonRegime | None = None
    cultivation_days: int | None = Field(default=None, gt=0)


class FarmerScopeResponse(BaseModel):
    """Read composition of /farms, /farms/{id}/plots and /plots/{id}/crop-seasons
    for the caller's RLS scope — same item shapes, one request."""
    farms: list[FarmResponse]
    plots: list[PlotResponse]
    crop_seasons: list[CropSeasonResponse]


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
    # NULL for a seeded/imported record the caller completed: editing does not
    # claim authorship (see `write_repo._view(allow_unattributed=...)`).
    created_by: str | None = None
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


class CarbonMissingRecord(BaseModel):
    """The stored activity record an issue is about, so the client can open it."""
    activity_id: str
    occurred_on: str | None = None
    label: str | None = None


class CarbonMissingInput(BaseModel):
    """One Carbon input the season lacks, plus where the user supplies it.

    `flow` is what the client routes on ("carbon_methodology" | "activity" |
    "plot" | "factor_unavailable"); it never has to decide which input belongs
    to which screen. "factor_unavailable" is a limitation, not a form.
    """
    code: str
    label: str
    detail: str
    flow: str
    activity_type: str | None = None
    #: False when the input only costs the per-kg intensity, not the whole result.
    blocking: bool
    records: list[CarbonMissingRecord] = []


class CarbonReadinessResponse(BaseModel):
    can_calculate: bool
    blocking_count: int
    missing_inputs: list[CarbonMissingInput]


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
    # Null when the package was generated with no carbon calculation behind it;
    # the manifest then records carbon.status = unavailable plus a warning.
    factor_set_id: str | None = None
    scope_description: str
    data_as_of_at: str
    contains_sample_data: bool
    is_finalized: bool
    warning_text: str | None = None
    # No storage_bucket / storage_object_path: they name a real private object
    # for rendered artifacts. The filename is all a client needs.
    file_name: str
    file_sha256: str | None = None
    payload_sha256: str | None = None
    source_snapshot_export_id: str | None = None
    generated_at: str
    generated_by: str | None = None


# -- MRV evidence package (M07 part 1) ----------------------------------


class MrvExportWarning(BaseModel):
    """A gap in the package, stated in machine-readable form.

    Severity is `info` or `warning` only. Missing optional data is not an error
    and must not be presented as one.
    """
    code: str = Field(..., description="Stable machine-readable warning code.")
    severity: str = Field(..., description="info | warning")
    message: str
    related: dict[str, Any] | None = Field(
        default=None, description="Ids the warning refers to, when it refers to one."
    )


class MrvPackageIntegrity(BaseModel):
    algorithm: str = Field(..., description="sha256")
    canonical_over: str = Field(
        ..., description="Which bytes the digest covers, e.g. manifest-without-package_integrity."
    )
    canonical_form: str = Field(..., description="How those bytes are produced.")
    manifest_sha256: str


class MrvArtifactResponse(BaseModel):
    """A rendered artifact (XLSX or PDF) and its lineage.

    `source_snapshot_export_id` names the canonical JSON snapshot this was
    rendered from; `payload_sha256` is that snapshot's digest and `file_sha256`
    is the artifact's own. The two being different is the point: one says which
    data, the other says which file.

    No storage bucket or object path is returned. They name a real private
    object, and a client only ever needs the filename.
    """
    export_id: str
    mrv_case_id: str
    format: str
    schema_version: str
    status: str
    generated_at: str
    generated_by: str
    file_sha256: str
    payload_sha256: str | None = None
    source_snapshot_export_id: str | None = None
    file_name: str
    scope_description: str
    warning_text: str | None = None
    is_finalized: bool
    byte_size: int | None = None


class MrvRenderRequest(BaseModel):
    format: str = Field("xlsx", description="Artifact format to render from a stored JSON snapshot: 'xlsx' or 'pdf'.")


class MrvExportCreatedResponse(BaseModel):
    """The generated package's identity and audit metadata, plus the manifest.

    `manifest` is the stored snapshot verbatim -- the same object a later
    download returns. It is typed as a mapping rather than a fully nested model
    on purpose: the manifest's own contract is versioned by `schema_version` and
    documented in docs/MRV_EXPORT_PACKAGE.md, and re-declaring every nested
    shape here would create a second contract to keep in step.
    """
    export_id: str
    mrv_case_id: str
    format: str
    schema_version: str
    status: str = Field(..., description="generated")
    generated_at: str
    generated_by: str
    file_sha256: str
    payload_sha256: str | None = None
    source_snapshot_export_id: str | None = None
    file_name: str
    scope_description: str
    warning_text: str | None = None
    is_finalized: bool
    # Present for a JSON snapshot, which IS the manifest. A rendered artifact
    # (xlsx) omits it: the bytes are the deliverable and the manifest it came
    # from is named by `source_snapshot_export_id`, so echoing it would ship the
    # same document twice in two formats in one response.
    manifest: dict[str, Any] | None = None
    byte_size: int | None = None


class MrvExportRequest(BaseModel):
    """Deliberately not a `Literal`.

    An unsupported format is a domain answer ("that export does not exist yet"),
    and routing it through the service keeps it in the shared error envelope
    rather than FastAPI's raw request-validation shape.
    """
    format: str = Field(
        "json", description="'json' (the canonical snapshot), or 'xlsx' / 'pdf' (rendered from that snapshot in the same call)."
    )


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


# -- Management: farmer provisioning -----------------------------------------

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class FarmCreateFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    farm_code: str = Field(min_length=1, max_length=64)
    farm_name: str = Field(min_length=1, max_length=160)
    province_name: str | None = Field(default=None, max_length=120)
    district_name: str | None = Field(default=None, max_length=120)
    commune_name: str | None = Field(default=None, max_length=120)


class PlotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plot_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    # `plots.area_ha numeric(10,4) not null check (area_ha > 0)`.
    area_ha: float = Field(gt=0, le=100000)


class FarmerProvisionRequest(BaseModel):
    """Only fields the domain stores: `profiles.full_name`, `profiles.phone`
    and the login email. The cooperative comes from the URL, the role is
    always `farmer`, the account starts active. Farm and plot are optional
    so an account can be created before its land is recorded."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254, pattern=_EMAIL)
    phone: str | None = Field(default=None, max_length=32)
    farm: FarmCreateFields | None = None
    plot: PlotCreateRequest | None = None

    @model_validator(mode="after")
    def check(self) -> "FarmerProvisionRequest":
        self.email = self.email.lower()
        if self.phone == "":
            self.phone = None
        if self.plot is not None and self.farm is None:
            raise ValueError("A plot needs a farm: add farm details or leave the plot out.")
        return self


class FarmerProvisionResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    phone: str | None = None
    organization_id: str
    farm_id: str | None = None
    plot_id: str | None = None
    #: Shown to the manager ONCE, to hand to the farmer. Never stored in an
    #: application table, never logged, not retrievable again.
    temporary_password: str


class FarmCreateRequest(FarmCreateFields):
    owner_user_id: UUID


class FarmCreatedResponse(BaseModel):
    id: str
    farm_code: str
    farm_name: str


class PlotCreatedResponse(BaseModel):
    id: str
    farm_id: str
    plot_code: str
    name: str
    area_ha: float


class FarmerFarmRef(BaseModel):
    id: str
    farm_code: str
    farm_name: str
    farm_role: str


class FarmerListItem(BaseModel):
    user_id: str
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    account_status: Literal["active", "locked", "ended"]
    farms: list[FarmerFarmRef]
    plot_count: int
    season_count: int
    active_season_count: int
    stage: Literal["no_farm", "no_plot", "no_season", "active_season", "history_only"]
    primary_farm_id: str | None = None
    idle_plot_id: str | None = None
