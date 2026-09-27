"""Tenant isolation + data-consistency test cho SupabaseReadRepository.

Test THẲNG repository layer bằng fake Supabase client (không phải HTTP) — bug
tenant-isolation/double-counting thật sự nằm ở LOGIC đọc/tổng hợp trong
read_repo.py, không nằm ở tầng router, nên test ở đây bắt đúng chỗ bug có thể
xảy ra mà không cần khởi động cả FastAPI app cho mỗi test. Xem thêm
`test_query_param_type_error_uses_unified_error_contract` cuối file — bài đó
CẦN app thật (kiểm tra middleware/exception handler ở main.py).

Fake client mô phỏng đúng những gì Postgrest/RLS thật trả về: mỗi "người dùng" chỉ
CÓ SẴN trong fake data những hàng mà RLS thật sự cho họ đọc — con giả không tự lọc
theo user_id (không có RLS thật ở đây), mà mô phỏng KẾT QUẢ ĐÃ LỌC, đúng như
`SupabaseReadRepository` sẽ nhận được từ Postgrest thật khi bind JWT qua publishable
key. Nếu code lỡ đọc chéo sang bảng của user khác, `ReadNotFoundError`/list rỗng phải
xảy ra vì fake data của user đó không có hàng nào — không phải vì code tự chặn.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import Settings, load_settings  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository  # noqa: E402

DUMMY_SETTINGS = Settings(
    supabase_url=None,
    supabase_service_role_key=None,
    supabase_publishable_key=None,
    ef_config_path=Path("unused"),
    require_factor_set_in_db=False,
    cors_origins=[],
)


class _FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._filters: dict[str, str] = {}
        self._in_filters: dict[str, set[str]] = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._filters[key] = str(value)
        return self

    def in_(self, key, values):
        self._in_filters[key] = {str(v) for v in values}
        return self

    def execute(self):
        matched = [
            row for row in self._rows
            if all(str(row.get(k)) == v for k, v in self._filters.items())
            and all(str(row.get(k)) in values for k, values in self._in_filters.items())
        ]
        return SimpleNamespace(data=matched)


class FakeSupabaseClient:
    """Chỉ chứa những hàng mà RLS THẬT sẽ cho user này thấy — mô phỏng kết quả sau lọc."""

    def __init__(self, visible_rows: dict[str, list[dict]], user_id: str):
        self._visible_rows = visible_rows
        self._user_id = user_id
        self.auth = SimpleNamespace(
            get_user=lambda _token: SimpleNamespace(user=SimpleNamespace(id=user_id))
        )
        self.postgrest = SimpleNamespace(auth=lambda _token: None)

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self._visible_rows.get(name, []))


# ---------------------------------------------------------------------------
# Fixture data: hai nông hộ (A, B) hoàn toàn tách biệt.
# ---------------------------------------------------------------------------

FARM_A, PLOT_A, SEASON_A, ORG_A = "farm-a", "plot-a", "season-a", "org-a"
FARM_B, PLOT_B, SEASON_B, ORG_B = "farm-b", "plot-b", "season-b", "org-b"


def _rows_for(farm_id, plot_id, season_id, org_id, user_id) -> dict[str, list[dict]]:
    return {
        "profiles": [{"id": user_id, "full_name": f"User {user_id}"}],
        "organization_memberships": [{"user_id": user_id, "organization_id": org_id, "role": "farmer"}],
        "farm_members": [{"user_id": user_id, "farm_id": farm_id, "farm_role": "owner"}],
        "organizations": [{"id": org_id, "organization_code": org_id, "name": f"Org {org_id}", "organization_type": "cooperative", "is_active": True}],
        "farms": [{"id": farm_id, "farm_code": farm_id, "farm_name": f"Farm {farm_id}", "cooperative_id": org_id}],
        "plots": [{"id": plot_id, "farm_id": farm_id, "plot_code": plot_id, "name": plot_id, "area_ha": 1.0}],
        "crop_seasons": [{"id": season_id, "plot_id": plot_id, "season_code": season_id, "crop_type": "rice", "status": "active"}],
        "production_batches": [
            {"id": f"{season_id}-b1", "crop_season_id": season_id, "batch_code": "b1", "name": None, "started_on": None, "closed_on": None, "status": "planned", "deleted_at": None},
            {"id": f"{season_id}-b2", "crop_season_id": season_id, "batch_code": "b2", "name": None, "started_on": None, "closed_on": None, "status": "planned", "deleted_at": None},
        ],
        "activities": [
            {
                "id": f"{season_id}-h1", "production_batch_id": f"{season_id}-b1", "activity_type": "harvest",
                "occurred_at": "2026-01-01", "recorded_at": "2026-01-01", "recorded_by": user_id,
                "source": "manual", "deleted_at": None, "note": None,
            },
            {
                "id": f"{season_id}-h2", "production_batch_id": f"{season_id}-b2", "activity_type": "harvest",
                "occurred_at": "2026-01-02", "recorded_at": "2026-01-02", "recorded_by": user_id,
                "source": "manual", "deleted_at": None, "note": None,
            },
        ],
        "harvest_events": [
            {"activity_id": f"{season_id}-h1", "yield_kg": 1000.0, "total_cost_vnd": None},
            {"activity_id": f"{season_id}-h2", "yield_kg": 1500.0, "total_cost_vnd": None},
        ],
        "seeding_events": [], "fertilizer_applications": [], "irrigation_events": [],
        "pesticide_applications": [], "fuel_usages": [], "straw_management_events": [],
        "carbon_calculations": [],
        "mrv_cases": [{"id": f"{org_id}-case1", "organization_id": org_id, "case_code": "MRV-01", "name": "Vụ MRV 1", "period_start": "2026-01-01", "period_end": "2026-06-01", "status": "draft"}],
        "mrv_case_steps": [{"mrv_case_id": f"{org_id}-case1", "step_no": 1, "status": "completed", "started_at": "2026-01-01", "completed_at": "2026-01-02", "notes": None}],
        "mrv_case_batches": [{"mrv_case_id": f"{org_id}-case1", "production_batch_id": f"{season_id}-b1"}],
        "mrv_evidence": [{"id": f"{org_id}-ev1", "mrv_case_id": f"{org_id}-case1", "step_no": 1, "production_batch_id": f"{season_id}-b1", "evidence_type": "photo", "file_name": "a.jpg", "mime_type": "image/jpeg", "storage_bucket": "mrv-evidence", "storage_object_path": f"{org_id}/a.jpg", "sha256": None, "uploaded_at": "2026-01-01"}],
        "mrv_exports": [{"id": f"{org_id}-exp1", "mrv_case_id": f"{org_id}-case1", "format": "csv", "factor_set_id": "fs-1", "scope_description": "vu 1", "data_as_of_at": "2026-01-01", "contains_sample_data": True, "is_finalized": False, "warning_text": "TEST DATA", "storage_bucket": "mrv-exports", "storage_object_path": f"{org_id}/export.csv", "file_sha256": None, "generated_at": "2026-01-01"}],
    }


@pytest.fixture
def repo_a() -> SupabaseReadRepository:
    client = FakeSupabaseClient(_rows_for(FARM_A, PLOT_A, SEASON_A, ORG_A, "user-a"), "user-a")
    return SupabaseReadRepository(DUMMY_SETTINGS, "token-a", client=client)


@pytest.fixture
def repo_b() -> SupabaseReadRepository:
    client = FakeSupabaseClient(_rows_for(FARM_B, PLOT_B, SEASON_B, ORG_B, "user-b"), "user-b")
    return SupabaseReadRepository(DUMMY_SETTINGS, "token-b", client=client)


# ---------------------------------------------------------------------------
# Tenant isolation — A không đọc được BẤT KỲ resource nào của B, qua MỌI method.
# ---------------------------------------------------------------------------

def test_farmer_a_cannot_read_farmer_b_farm(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.farm(FARM_B)


def test_farmer_a_cannot_read_farmer_b_plot(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.plot(PLOT_B)


def test_farmer_a_cannot_list_plots_of_farmer_b_farm(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.plots_for_farm(FARM_B)


def test_farmer_a_cannot_read_farmer_b_season(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.season(SEASON_B)


def test_farmer_a_cannot_list_seasons_of_farmer_b_plot(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.seasons_for_plot(PLOT_B)


def test_farmer_a_cannot_read_farmer_b_activities(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.activities(SEASON_B)


def test_farmer_a_cannot_read_farmer_b_metrics(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.metrics(SEASON_B)


def test_farmer_a_cannot_read_farmer_b_organization_summary(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.organization_summary(ORG_B)


def test_farmer_a_cannot_read_farmer_b_farm_performance(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.farm_performance(ORG_B)


def test_farmer_a_farms_list_never_contains_farmer_b_farm(repo_a):
    # farms() không lọc theo id cụ thể (list toàn bộ "farms" nhìn thấy được) — với
    # fake client, "nhìn thấy được" = chỉ có hàng của A trong bảng giả -> B không lọt vào.
    ids = {row["id"] for row in repo_a.farms()}
    assert FARM_B not in ids
    assert ids == {FARM_A}


# ---------------------------------------------------------------------------
# Data consistency — 2 batch, mỗi batch 1 harvest -> metrics() PHẢI cộng, không nhân.
# ---------------------------------------------------------------------------

def test_metrics_sums_across_batches_without_multiplication(repo_a):
    metrics = repo_a.metrics(SEASON_A)
    # 2 batch x 1 harvest/batch = 1000 + 1500, KHÔNG phải 1000*2 hay 2500*2.
    assert metrics["yield_kg"] == 2500.0


def test_metrics_yield_none_when_any_harvest_missing_value(repo_a):
    client = FakeSupabaseClient(_rows_for(FARM_A, PLOT_A, SEASON_A, ORG_A, "user-a"), "user-a")
    repo = SupabaseReadRepository(DUMMY_SETTINGS, "token-a", client=client)
    # Xoá yield_kg của 1 harvest -> has_yield=False -> yield_kg tổng PHẢI null, không phải
    # tổng của phần còn lại (không được âm thầm bỏ qua bản ghi thiếu dữ liệu).
    client._visible_rows["harvest_events"][1]["yield_kg"] = None
    metrics = repo.metrics(SEASON_A)
    assert metrics["yield_kg"] is None
    assert metrics["co2e_per_kg"] is None  # không có yield -> không được chia ra số


def _add_activity(client, activity_id: str, activity_type: str, detail_table: str, detail: dict):
    client._visible_rows["activities"].append({
        "id": activity_id, "production_batch_id": f"{SEASON_A}-b1",
        "activity_type": activity_type, "occurred_at": "2026-01-03",
        "recorded_at": "2026-01-03", "recorded_by": "user-a", "source": "manual",
        "deleted_at": None, "note": None,
    })
    client._visible_rows[detail_table].append({"activity_id": activity_id, **detail})


def test_metrics_no_water_or_fertilizer_record_is_unknown_not_zero(repo_a):
    metrics = repo_a.metrics(SEASON_A)
    assert metrics["water_m3"] is None
    assert metrics["water_per_kg"] is None
    assert metrics["fertilizer_kg"] is None
    assert metrics["fertilizer_per_kg"] is None
    assert metrics["data_completeness"]["water"] is False
    assert metrics["data_completeness"]["fertilizer"] is False


def test_metrics_known_zero_water_is_not_unknown(repo_a):
    _add_activity(
        repo_a.client, "water-zero", "irrigation", "irrigation_events",
        {"method": "awd", "water_volume_m3": 0.0, "total_cost_vnd": None},
    )

    metrics = repo_a.metrics(SEASON_A)
    assert metrics["water_m3"] == 0.0
    assert metrics["water_per_kg"] == 0.0
    assert metrics["data_completeness"]["water"] is True


def test_metrics_missing_water_or_fertilizer_value_is_incomplete(repo_a):
    _add_activity(
        repo_a.client, "water-missing", "irrigation", "irrigation_events",
        {"method": "awd", "water_volume_m3": None, "total_cost_vnd": None},
    )
    _add_activity(
        repo_a.client, "fert-missing", "fertilizer", "fertilizer_applications",
        {"fertilizer_name": "Urea", "amount_kg": None, "total_cost_vnd": None},
    )

    metrics = repo_a.metrics(SEASON_A)
    assert metrics["water_m3"] is None
    assert metrics["fertilizer_kg"] is None
    assert metrics["data_completeness"]["water"] is False
    assert metrics["data_completeness"]["fertilizer"] is False


def test_metrics_uses_seeding_cost_vnd_and_all_recorded_direct_costs(repo_a):
    client = repo_a.client
    client._visible_rows["harvest_events"][0]["total_cost_vnd"] = 200.0
    client._visible_rows["harvest_events"][1]["total_cost_vnd"] = 300.0
    _add_activity(client, "seed-1", "seeding", "seeding_events", {"seed_kg": 50.0, "cost_vnd": 100.0})

    metrics = repo_a.metrics(SEASON_A)
    assert metrics["cost_per_kg"] == pytest.approx(600.0 / 2500.0)
    assert metrics["data_completeness"]["cost"] is True


def test_metrics_missing_direct_cost_is_incomplete_not_partial_total(repo_a):
    client = repo_a.client
    client._visible_rows["harvest_events"][0]["total_cost_vnd"] = 200.0
    client._visible_rows["harvest_events"][1]["total_cost_vnd"] = 300.0
    _add_activity(client, "seed-1", "seeding", "seeding_events", {"seed_kg": 50.0, "cost_vnd": None})

    metrics = repo_a.metrics(SEASON_A)
    assert metrics["cost_per_kg"] is None
    assert metrics["data_completeness"]["cost"] is False


def test_farm_performance_exposes_backend_resource_metrics(repo_a):
    client = repo_a.client
    client._visible_rows["harvest_events"][0]["total_cost_vnd"] = 200.0
    client._visible_rows["harvest_events"][1]["total_cost_vnd"] = 300.0
    _add_activity(client, "seed-1", "seeding", "seeding_events", {"seed_kg": 50.0, "cost_vnd": 100.0})
    _add_activity(client, "water-1", "irrigation", "irrigation_events", {"method": "awd", "water_volume_m3": 500.0, "total_cost_vnd": 0.0})
    _add_activity(client, "fert-1", "fertilizer", "fertilizer_applications", {"fertilizer_name": "Urea", "amount_kg": 125.0, "total_cost_vnd": 0.0})

    item = repo_a.farm_performance(ORG_A)[0]
    assert item["water_per_kg"] == pytest.approx(500.0 / 2500.0)
    assert item["fertilizer_per_kg"] == pytest.approx(125.0 / 2500.0)
    assert item["cost_per_kg"] == pytest.approx(600.0 / 2500.0)


def test_aggregate_metrics_uses_sum_over_sum_not_average_of_averages(repo_a, monkeypatch):
    values = {
        "a": {"yield_kg": 100.0, "water_m3": 100.0, "fertilizer_kg": 100.0, "total_co2e_kg": 100.0, "_total_cost_vnd": 100.0},
        "b": {"yield_kg": 300.0, "water_m3": 900.0, "fertilizer_kg": 900.0, "total_co2e_kg": 900.0, "_total_cost_vnd": 900.0},
    }
    monkeypatch.setattr(repo_a, "_bulk_metric_totals", lambda season_ids: {sid: values[sid] for sid in season_ids})

    aggregate = repo_a._aggregate_metrics(["a", "b"])
    assert aggregate["water_per_kg"] == pytest.approx(2.5)
    assert aggregate["fertilizer_per_kg"] == pytest.approx(2.5)
    assert aggregate["co2e_per_kg"] == pytest.approx(2.5)
    assert aggregate["cost_per_kg"] == pytest.approx(2.5)


def test_organization_metrics_uses_weighted_resource_intensity(repo_a, monkeypatch):
    values = {
        "a": {"yield_kg": 100.0, "water_m3": 100.0, "fertilizer_kg": 100.0, "total_co2e_kg": 100.0, "_total_cost_vnd": 100.0},
        "b": {"yield_kg": 300.0, "water_m3": 900.0, "fertilizer_kg": 900.0, "total_co2e_kg": 900.0, "_total_cost_vnd": 900.0},
    }
    monkeypatch.setattr(repo_a, "_season_ids_for_farms", lambda _farms: ["a", "b"])
    monkeypatch.setattr(repo_a, "_bulk_metric_totals", lambda season_ids: {sid: values[sid] for sid in season_ids})

    metrics = repo_a.organization_metrics(ORG_A)
    assert metrics["water_per_kg"] == pytest.approx(2.5)
    assert metrics["fertilizer_per_kg"] == pytest.approx(2.5)
    assert metrics["cost_per_kg"] == pytest.approx(2.5)


def test_farmer_a_cannot_read_farmer_b_organization(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.organization(ORG_B)


def test_farmer_a_organizations_list_never_contains_farmer_b_org(repo_a):
    ids = {row["id"] for row in repo_a.organizations()}
    assert ORG_B not in ids


def test_farmer_a_cannot_list_farmer_b_organization_farms(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.organization_farms(ORG_B)


def test_farmer_a_cannot_read_farmer_b_organization_metrics(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.organization_metrics(ORG_B)


def test_farmer_a_cannot_read_farmer_b_farm_crop_seasons(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.farm_crop_seasons(FARM_B)


def test_farmer_a_cannot_read_farmer_b_farm_metrics(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.farm_metrics(FARM_B)


def test_farmer_a_cannot_read_farmer_b_activity(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.activity(f"{SEASON_B}-h1")


def test_farmer_a_cannot_read_farmer_b_mrv_case(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.mrv_case(f"{ORG_B}-case1")


def test_farmer_a_cannot_read_farmer_b_mrv_steps(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.mrv_steps(f"{ORG_B}-case1")


def test_farmer_a_cannot_read_farmer_b_mrv_batches(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.mrv_batches(f"{ORG_B}-case1")


def test_farmer_a_cannot_read_farmer_b_mrv_evidence(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.mrv_evidence(f"{ORG_B}-case1")


def test_farmer_a_cannot_read_farmer_b_mrv_exports(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.mrv_exports(f"{ORG_B}-case1")


def test_farmer_a_cannot_read_farmer_b_mrv_export(repo_a):
    with pytest.raises(ReadNotFoundError):
        repo_a.mrv_export(f"{ORG_B}-exp1")


# ---------------------------------------------------------------------------
# MRV — shape correctness
# ---------------------------------------------------------------------------

def test_mrv_steps_always_has_6_steps_even_if_only_1_recorded(repo_a):
    steps = repo_a.mrv_steps(f"{ORG_A}-case1")
    assert len(steps) == 6
    assert [s["step_no"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert steps[0]["status"] == "completed"
    assert steps[1]["status"] == "not_started"  # chưa có record -> not_started, không bịa


def test_mrv_case_embeds_full_6_steps(repo_a):
    case = repo_a.mrv_case(f"{ORG_A}-case1")
    assert len(case["steps"]) == 6


def test_mrv_batches_resolves_farm_and_plot_via_batch_chain(repo_a):
    batches = repo_a.mrv_batches(f"{ORG_A}-case1")
    assert len(batches) == 1
    assert batches[0]["farm_id"] == FARM_A
    assert batches[0]["plot_id"] == PLOT_A


def test_mrv_export_export_payload_not_exposed(repo_a):
    export = repo_a.mrv_export(f"{ORG_A}-exp1")
    assert "export_payload" not in export  # jsonb có thể lớn/nội bộ, view chỉ trả metadata
    assert export["contains_sample_data"] is True
    assert export["warning_text"] == "TEST DATA"


def test_mrv_export_metadata_hides_the_storage_location(repo_a):
    # M07 part 2: a rendered artifact's path names a real private object.
    for export in (repo_a.mrv_export(f"{ORG_A}-exp1"), *repo_a.mrv_exports(f"{ORG_A}-case1")):
        assert "storage_object_path" not in export
        assert "storage_bucket" not in export
        assert export["file_name"] == "export.csv"


# ---------------------------------------------------------------------------
# Farm/org aggregation — sum, không average; null nếu thiếu dữ liệu
# ---------------------------------------------------------------------------

def test_farm_metrics_matches_season_metrics_single_season(repo_a):
    farm_metrics = repo_a.farm_metrics(FARM_A)
    season_metrics = repo_a.metrics(SEASON_A)
    assert farm_metrics["yield_kg"] == season_metrics["yield_kg"]


def test_organization_farms_scoped_to_organization(repo_a):
    farms = repo_a.organization_farms(ORG_A)
    assert {f["id"] for f in farms} == {FARM_A}


def test_organization_summary_sums_farms_not_averages(repo_a):
    # Chỉ 1 farm/1 season trong fixture nhưng vẫn khẳng định field là tổng (sum), không
    # phải trung bình co2e_per_kg — organization_summary() phải trả None cho co2e_per_kg
    # khi chưa có carbon_calculations nào (không bịa số 0).
    summary = repo_a.organization_summary(ORG_A)
    assert summary["total_co2e_kg"] is None  # không có carbon_calculations trong fixture
    assert summary["co2e_per_kg"] is None
    assert summary["farm_count"] == 1
    assert summary["crop_season_count"] == 1


# ---------------------------------------------------------------------------
# Unified validation-error contract (main.py) — Pydantic 422 tự động phải cùng
# hình dạng {"detail": {"error": {"code","message"}}} như lỗi tự tay raise.
# ---------------------------------------------------------------------------

# These drive the CONFIGURED `main.app`: without Supabase settings every read
# route answers 503 `backend_not_configured` before validation or auth, and the
# malformed-bearer cases need a live Supabase Auth/PostgREST to reject the JWT.
# CI runs them against its local Supabase stack (and fails on unexpected skips).
requires_supabase_config = pytest.mark.skipif(
    not load_settings().auth_configured,
    reason="SUPABASE_URL/SUPABASE_PUBLISHABLE_KEY are not configured; needs the configured main.app.",
)


@requires_supabase_config
def test_query_param_type_error_uses_unified_error_contract():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    response = client.get("/v1/farms", headers={"Authorization": "Bearer x"}, params={"page": "abc"})
    assert response.status_code == 422
    body = response.json()["detail"]["error"]
    assert body["code"] == "validation_error"
    assert isinstance(body["errors"], list) and body["errors"]


def test_missing_authorization_uses_unified_401_error_contract():
    """The configured production read dependency must not leak MissingAuthError as 500."""
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get("/v1/farms")
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


@requires_supabase_config
@pytest.mark.parametrize("token", ["garbage", "malformed.jwt.token", "a.b.c"])
@pytest.mark.parametrize("path", ["/v1/me", "/v1/farmer/scope", "/v1/farms"])
def test_malformed_bearer_returns_401_not_500(path, token, monkeypatch):
    """A syntactically valid header carrying a junk JWT must be 401, never 500.

    The header shape passes `extract_bearer_token`, so the token is only found
    to be junk once Supabase looks at it — deep inside the read repository.
    Before the fix that raised `AuthApiError`/PostgREST `PGRST301` straight
    through FastAPI and every one of these was a 500.
    """
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


@requires_supabase_config
def test_me_malformed_bearer_returns_401():
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get("/v1/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


@requires_supabase_config
def test_farmer_scope_malformed_bearer_returns_401():
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get("/v1/farmer/scope", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


# ---------------------------------------------------------------------------
# The 401 mapping must stay narrow (brief §5): only Supabase's own "this JWT is
# unusable" verdict becomes 401. A dropped connection, an outage or a bug here
# must keep surfacing as a real 5xx instead of bouncing the user to a login
# screen for a failure that has nothing to do with their token.
# ---------------------------------------------------------------------------

def test_only_supabase_jwt_rejection_is_translated():
    from postgrest.exceptions import APIError
    from supabase_auth.errors import AuthApiError, AuthRetryableError
    from infrastructure.auth import InvalidTokenError, jwt_rejection_as_invalid_token

    rejected = [
        APIError({"message": "Expected 3 parts in JWT; got 1", "code": "PGRST301"}),
        APIError({"message": "JWT cryptographic operation failed", "code": "PGRST301"}),
        AuthApiError("invalid JWT", 401, None),
        AuthApiError("forbidden", 403, None),
    ]
    for exc in rejected:
        with pytest.raises(InvalidTokenError):
            with jwt_rejection_as_invalid_token():
                raise exc

    untouched: list[Exception] = [
        APIError({"message": "no rows", "code": "PGRST116"}),
        AuthApiError("upstream is unwell", 500, None),
        AuthRetryableError("connection reset", 0),
        ConnectionError("server disconnected"),
        ValueError("a plain programming error"),
    ]
    for exc in untouched:
        with pytest.raises(type(exc)):
            with jwt_rejection_as_invalid_token():
                raise exc


def test_scope_denial_with_a_valid_token_is_still_404_not_401(repo_a):
    """The fix must not turn an authorization verdict into an authentication one.

    Farmer A holds a perfectly good token and asks for Farmer B's farm: that is
    a scope denial, and it must stay a 404 (never 403, never 401) so the reply
    does not reveal that `farm-b` exists.
    """
    from fastapi.testclient import TestClient
    import api
    from main import app

    previous = app.dependency_overrides.get(api._read_repo)
    app.dependency_overrides[api._read_repo] = lambda: repo_a
    try:
        response = TestClient(app).get(
            f"/v1/farms/{FARM_B}", headers={"Authorization": "Bearer token-a"}
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(api._read_repo, None)
        else:
            app.dependency_overrides[api._read_repo] = previous
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# CORS — không có middleware này thì browser thật chặn MỌI fetch từ React
# trước khi request rời đi (khác 401/403). Bug thật phát hiện qua browser QA
# (2026-09-09): baseline không có CORSMiddleware.
# ---------------------------------------------------------------------------

def test_cors_preflight_allows_configured_dev_origin():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    response = client.options(
        "/v1/farms",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unlisted_origin():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    response = client.options(
        "/v1/farms",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    # Starlette CORSMiddleware trả 200 nhưng KHÔNG có access-control-allow-origin
    # cho origin lạ -> browser tự chặn ở phía client, không phải backend từ chối.
    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------------------
# Farmer scope composition (Farmer Web V2) — one call, same RLS boundary.
# ---------------------------------------------------------------------------

def test_farmer_scope_returns_only_callers_hierarchy(repo_a):
    scope = repo_a.farmer_scope()
    assert [f["id"] for f in scope["farms"]] == [FARM_A]
    assert scope["farms"][0]["plot_count"] == 1
    assert [p["id"] for p in scope["plots"]] == [PLOT_A]
    assert [s["id"] for s in scope["crop_seasons"]] == [SEASON_A]
    visible = {x["id"] for group in scope.values() for x in group}
    assert not visible & {FARM_B, PLOT_B, SEASON_B}


def test_farmer_scope_drops_rows_outside_the_visible_hierarchy():
    rows = _rows_for(FARM_A, PLOT_A, SEASON_A, ORG_A, "user-a")
    rows["plots"].append({"id": "plot-orphan", "farm_id": FARM_B, "plot_code": "x", "name": "x", "area_ha": 1.0})
    rows["crop_seasons"].append({"id": "season-orphan", "plot_id": "plot-orphan", "season_code": "x", "crop_type": "rice", "status": "active"})
    repo = SupabaseReadRepository(DUMMY_SETTINGS, "token-a", client=FakeSupabaseClient(rows, "user-a"))
    scope = repo.farmer_scope()
    assert "plot-orphan" not in {p["id"] for p in scope["plots"]}
    assert "season-orphan" not in {s["id"] for s in scope["crop_seasons"]}


def test_farmer_scope_items_match_existing_list_endpoint_views(repo_a):
    scope = repo_a.farmer_scope()
    assert scope["farms"] == repo_a.farms()
    assert scope["plots"] == repo_a.plots_for_farm(FARM_A)
    assert scope["crop_seasons"] == repo_a.seasons_for_plot(PLOT_A)


def test_farmer_scope_route_requires_authentication():
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get("/v1/farmer/scope")
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


def test_farmer_scope_route_serializes_repository_view(repo_a):
    from fastapi.testclient import TestClient
    import api
    from main import app

    previous = app.dependency_overrides.get(api._read_repo)
    app.dependency_overrides[api._read_repo] = lambda: repo_a
    try:
        response = TestClient(app).get("/v1/farmer/scope", headers={"Authorization": "Bearer token-a"})
    finally:
        if previous is None:
            app.dependency_overrides.pop(api._read_repo, None)
        else:
            app.dependency_overrides[api._read_repo] = previous
    assert response.status_code == 200
    body = response.json()
    assert [f["farm_code"] for f in body["farms"]] == [FARM_A]
    assert [s["season_code"] for s in body["crop_seasons"]] == [SEASON_A]
