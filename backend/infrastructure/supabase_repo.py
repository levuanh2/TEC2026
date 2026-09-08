"""Repository thật, chạy trên Supabase bằng service-role key.

BẢO MẬT
  * Service-role key CHỈ tồn tại ở backend. Không bao giờ gửi xuống Flutter/web.
  * Client đọc kết quả qua API này, hoặc qua Supabase với anon key + RLS.
  * Module này KHÔNG sửa và KHÔNG né RLS; nó dùng service role đúng như schema đã thiết kế:
    "Calculations are written by trusted backend/service role; authenticated users read
    scoped results."

Đọc theo TỪNG BẢNG rồi ghép trong Python, cố ý không dùng một câu join lớn: join nhiều
bảng 1-n cùng lúc sẽ nhân bản hàng và làm phồng tổng sản lượng.
"""

from __future__ import annotations

from typing import Any

from carbon import SCENARIO_TO_DB

from .config import Settings
from .mapping import RawCropBundle
from .repository import CropNotFoundError, FactorSetNotFoundError

# activity_type -> (tên bảng chi tiết)
DETAIL_TABLES = {
    "seeding": "seeding_events",
    "fertilizer": "fertilizer_applications",
    "irrigation": "irrigation_events",
    "pesticide": "pesticide_applications",
    "fuel": "fuel_usages",
    "straw_management": "straw_management_events",
    "harvest": "harvest_events",
}


class SupabaseCarbonRepository:
    """Cần `supabase` package và biến môi trường. Khởi tạo lười để import không nổ."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from supabase import create_client  # import lười: chỉ cần khi dùng thật

            url, key = self._settings.require_supabase()
            self._client = create_client(url, key)
        return self._client

    # -- đọc ---------------------------------------------------------------

    def get_crop_bundle(self, crop_season_id: str) -> RawCropBundle:
        crop = self._one("crop_seasons", {"id": crop_season_id})
        if crop is None or crop.get("deleted_at") is not None:
            raise CropNotFoundError(f"Không tìm thấy vụ canh tác '{crop_season_id}'.")

        plot = self._one("plots", {"id": crop["plot_id"]}) or {}
        farm = self._one("farms", {"id": plot["farm_id"]}) if plot.get("farm_id") else None

        batches = self._many("production_batches", {"crop_season_id": crop_season_id})
        batch_ids = [b["id"] for b in batches if b.get("deleted_at") is None]

        activities: list[dict[str, Any]] = []
        for batch_id in batch_ids:
            activities.extend(self._many("activities", {"production_batch_id": batch_id}))
        activities = [a for a in activities if a.get("deleted_at") is None]

        self._attach_details(activities)

        return RawCropBundle(
            crop_season=crop,
            plot=plot,
            farm=farm,
            production_batches=batches,
            activities=activities,
        )

    def _attach_details(self, activities: list[dict[str, Any]]) -> None:
        """Đọc từng bảng chi tiết theo lô id rồi gắn vào `activity['detail']`."""
        by_type: dict[str, list[str]] = {}
        for activity in activities:
            by_type.setdefault(activity["activity_type"], []).append(activity["id"])

        detail_by_activity: dict[str, dict[str, Any]] = {}
        for activity_type, ids in by_type.items():
            table = DETAIL_TABLES.get(activity_type)
            if not table or not ids:
                continue
            rows = (
                self.client.table(table).select("*").in_("activity_id", ids).execute().data or []
            )
            for row in rows:
                detail_by_activity[row["activity_id"]] = row

        for activity in activities:
            activity["detail"] = detail_by_activity.get(activity["id"], {})

    # -- bộ hệ số ----------------------------------------------------------

    def resolve_factor_set_id(self, version_code: str) -> str:
        rows = (
            self.client.table("emission_factor_sets")
            .select("id,status")
            .eq("version_code", version_code)
            .execute()
            .data
            or []
        )
        published = [r for r in rows if r.get("status") == "published"]
        if not published:
            raise FactorSetNotFoundError(
                f"Chưa có emission_factor_set nào ở trạng thái published với version_code "
                f"'{version_code}'. YAML là nguồn sự thật cho GIÁ TRỊ hệ số; bảng Supabase là "
                f"bản sao có kiểm soát để bản tính liên kết được factor_set_id. "
                f"Import bộ hệ số trước — KHÔNG tự tạo bộ rỗng."
            )
        return published[0]["id"]

    def factor_ids_by_code(self, factor_set_id: str) -> dict[str, str]:
        rows = (
            self.client.table("emission_factors")
            .select("id,factor_code")
            .eq("factor_set_id", factor_set_id)
            .execute()
            .data
            or []
        )
        return {r["factor_code"]: r["id"] for r in rows}

    # -- ghi ---------------------------------------------------------------

    def save_calculation(
        self, calculation: dict[str, Any], breakdowns: list[dict[str, Any]]
    ) -> str:
        inserted = self.client.table("carbon_calculations").insert(calculation).execute().data
        calc_id = inserted[0]["id"]
        if breakdowns:
            self.client.table("carbon_breakdowns").insert(
                [{**b, "calculation_id": calc_id} for b in breakdowns]
            ).execute()
        return calc_id

    def latest_calculation(
        self, crop_season_id: str, scenario: str | None = None
    ) -> dict[str, Any] | None:
        query = (
            self.client.table("carbon_calculations")
            .select("*")
            .eq("crop_season_id", crop_season_id)
            .eq("status", "succeeded")  # không trả bản tính thất bại như kết quả thành công
            .order("calculated_at", desc=True)
            .limit(1)
        )
        if scenario:
            query = query.eq("scenario", SCENARIO_TO_DB.get(scenario, scenario))
        rows = query.execute().data or []
        if not rows:
            return None

        latest = rows[0]
        latest["breakdown"] = (
            self.client.table("carbon_breakdowns")
            .select("*")
            .eq("calculation_id", latest["id"])
            .execute()
            .data
            or []
        )
        return latest

    # -- tiện ích ----------------------------------------------------------

    def _one(self, table: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        rows = self._many(table, filters)
        return rows[0] if rows else None

    def _many(self, table: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        query = self.client.table(table).select("*")
        for column, value in filters.items():
            query = query.eq(column, value)
        return query.execute().data or []
