"""Read-only dashboard repository.

Every request creates a publishable-key client and binds the caller JWT before
reading.  RLS therefore remains the tenant boundary; this module never uses a
service-role key and never accepts a user id supplied by the frontend.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .config import Settings

DETAIL_TABLES = {
    "seeding": "seeding_events", "fertilizer": "fertilizer_applications",
    "irrigation": "irrigation_events", "pesticide": "pesticide_applications",
    "fuel": "fuel_usages", "straw_management": "straw_management_events",
    "harvest": "harvest_events",
}

class ReadNotFoundError(Exception): pass

class SupabaseReadRepository:
    def __init__(self, settings: Settings, token: str, client: Any | None = None):
        if client is None:
            from supabase import create_client
            url, key = settings.require_publishable()
            client = create_client(url, key)
        self.client = client
        self.client.postgrest.auth(token)
        self.token = token

    def _many(self, table: str, **filters: str) -> list[dict[str, Any]]:
        query = self.client.table(table).select("*")
        for key, value in filters.items(): query = query.eq(key, value)
        return query.execute().data or []

    def _one(self, table: str, id: str) -> dict[str, Any]:
        rows = self._many(table, id=id)
        if not rows: raise ReadNotFoundError(table)
        return rows[0]

    def user_id(self) -> str:
        user = self.client.auth.get_user(self.token).user
        if user is None: raise ReadNotFoundError("user")
        return str(user.id)

    def me(self) -> dict[str, Any]:
        user_id = self.user_id()
        profile = self._one("profiles", user_id)
        orgs = self._many("organization_memberships", user_id=user_id)
        farms = self._many("farm_members", user_id=user_id)
        return {"user_id": user_id, "full_name": profile.get("full_name"), "organization_memberships": orgs, "farm_memberships": farms, "roles": sorted({str(x["role"]) for x in orgs} | {str(x["farm_role"]) for x in farms})}

    def farms(self) -> list[dict[str, Any]]:
        rows = self._many("farms")
        plots = self._many("plots")
        counts: dict[str, int] = defaultdict(int)
        for plot in plots: counts[str(plot["farm_id"])] += 1
        return [{"id": row["id"], "farm_code": row["farm_code"], "farm_name": row["farm_name"], "province_name": row.get("province_name"), "district_name": row.get("district_name"), "commune_name": row.get("commune_name"), "plot_count": counts[str(row["id"])]} for row in rows]

    def farm(self, farm_id: str) -> dict[str, Any]:
        row = next((x for x in self.farms() if str(x["id"]) == farm_id), None)
        if row is None:
            raise ReadNotFoundError("farms")
        return row

    def plots_for_farm(self, farm_id: str) -> list[dict[str, Any]]:
        self._one("farms", farm_id)
        return [self.plot_view(x) for x in self._many("plots", farm_id=farm_id)]

    def plot_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "farm_id", "plot_code", "name", "area_ha", "latitude", "longitude")}

    def plot(self, plot_id: str) -> dict[str, Any]: return self.plot_view(self._one("plots", plot_id))

    def season_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "plot_id", "season_code", "crop_type", "variety_name", "planting_date", "expected_harvest_date", "actual_harvest_date", "status")}

    def season(self, season_id: str) -> dict[str, Any]: return self.season_view(self._one("crop_seasons", season_id))
    def seasons_for_plot(self, plot_id: str) -> list[dict[str, Any]]:
        self._one("plots", plot_id); return [self.season_view(x) for x in self._many("crop_seasons", plot_id=plot_id)]

    def _activities(self, season_id: str) -> list[dict[str, Any]]:
        self._one("crop_seasons", season_id)
        batch_ids = [str(x["id"]) for x in self._many("production_batches", crop_season_id=season_id)]
        rows: list[dict[str, Any]] = []
        for batch_id in batch_ids: rows.extend(self._many("activities", production_batch_id=batch_id))
        return [x for x in rows if x.get("deleted_at") is None]

    def activities(self, season_id: str) -> list[dict[str, Any]]:
        rows = self._activities(season_id); ids = [str(x["id"]) for x in rows]; details: dict[str, dict[str, Any]] = {}
        # Fetch each 1:1 detail table independently then merge by activity_id.
        for table in DETAIL_TABLES.values():
            for activity_id in ids:
                found = self._many(table, activity_id=activity_id)
                if found: details[activity_id] = found[0]
        users = {str(x["id"]): x.get("full_name") for x in self._many("profiles")}
        return [self._activity_view(x, details.get(str(x["id"]), {}), users) for x in rows]

    def _activity_view(self, row: dict[str, Any], detail: dict[str, Any], users: dict[str, str | None]) -> dict[str, Any]:
        return {"id": row["id"], "activity_type": row["activity_type"], "occurred_at": row["occurred_at"], "recorded_at": row["recorded_at"], "recorded_by": users.get(str(row.get("recorded_by"))), "source": row["source"], "payload": {**detail, "note": row.get("note")}}

    def activity(self, activity_id: str) -> dict[str, Any]:
        row = self._one("activities", activity_id)
        if row.get("deleted_at") is not None:
            raise ReadNotFoundError("activities")
        detail: dict[str, Any] = {}
        for table in DETAIL_TABLES.values():
            found = self._many(table, activity_id=activity_id)
            if found:
                detail = found[0]
                break
        users = {str(x["id"]): x.get("full_name") for x in self._many("profiles")}
        return self._activity_view(row, detail, users)

    def metrics(self, season_id: str) -> dict[str, Any]:
        activities = self.activities(season_id)
        yield_kg = water_m3 = fertilizer_kg = total_cost = 0.0
        has_yield = has_water = has_fertilizer = has_cost = True
        for item in activities:
            payload = item["payload"]; kind = item["activity_type"]
            if kind == "harvest":
                if payload.get("yield_kg") is None: has_yield = False
                else: yield_kg += float(payload["yield_kg"])
            if kind == "irrigation":
                if payload.get("water_volume_m3") is None: has_water = False
                else: water_m3 += float(payload["water_volume_m3"])
            if kind == "fertilizer":
                if payload.get("amount_kg") is None: has_fertilizer = False
                else: fertilizer_kg += float(payload["amount_kg"])
            if payload.get("total_cost_vnd") is None: has_cost = False
            else: total_cost += float(payload["total_cost_vnd"])
        carbon = self._many("carbon_calculations", crop_season_id=season_id)
        succeeded = [x for x in carbon if x.get("status") == "succeeded" and x.get("scenario") == "actual"]
        latest = max(succeeded, key=lambda x: str(x.get("calculated_at")), default=None)
        y = yield_kg if has_yield and yield_kg > 0 else None
        co2e = float(latest["total_co2e_kg"]) if latest else None
        return {"yield_kg": y, "water_m3": water_m3 if has_water else None, "fertilizer_kg": fertilizer_kg if has_fertilizer else None, "total_co2e_kg": co2e, "water_per_kg": water_m3 / y if has_water and y else None, "fertilizer_per_kg": fertilizer_kg / y if has_fertilizer and y else None, "co2e_per_kg": co2e / y if co2e is not None and y else None, "cost_per_kg": total_cost / y if has_cost and y else None, "data_completeness": {"water": has_water, "fertilizer": has_fertilizer, "cost": has_cost, "carbon": latest is not None}}

    def _organization_farms(self, organization_id: str) -> list[dict[str, Any]]:
        self._one("organizations", organization_id)  # RLS scope check, never trust URL alone.
        return self._many("farms", cooperative_id=organization_id)

    def _organization_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "organization_code", "name", "organization_type", "province_name", "district_name", "commune_name", "is_active")}

    def organizations(self) -> list[dict[str, Any]]:
        return [self._organization_view(x) for x in self._many("organizations")]

    def organization(self, organization_id: str) -> dict[str, Any]:
        return self._organization_view(self._one("organizations", organization_id))

    def organization_farms(self, organization_id: str) -> list[dict[str, Any]]:
        # farms() tính plot_count trên toàn bộ farm nhìn thấy được — ở đây lọc lại theo
        # organization_id để KHÔNG lộ farm ngoài tổ chức qua route lồng trong org.
        farm_ids = {str(x["id"]) for x in self._organization_farms(organization_id)}
        return [x for x in self.farms() if str(x["id"]) in farm_ids]

    def _season_ids_for_farms(self, farms: list[dict[str, Any]]) -> list[str]:
        season_ids: list[str] = []
        for farm in farms:
            for plot in self._many("plots", farm_id=str(farm["id"])):
                season_ids.extend(str(s["id"]) for s in self._many("crop_seasons", plot_id=str(plot["id"])))
        return season_ids

    def _aggregate_metrics(self, season_ids: list[str]) -> dict[str, Any]:
        """Tổng (sum), KHÔNG trung bình — cùng nguyên tắc organization_summary().

        null nếu BẤT KỲ vụ nào trong tập hợp thiếu dữ liệu của field đó, để không
        âm thầm bỏ qua vụ chưa đo — giống hệt cách metrics()/organization_summary() xử lý.
        """
        ms = [self.metrics(sid) for sid in season_ids]

        def total(key: str) -> float | None:
            if not ms:
                return None
            values = [m[key] for m in ms]
            if any(v is None for v in values):
                return None
            return sum(float(v) for v in values)

        yield_kg = total("yield_kg"); water_m3 = total("water_m3")
        fertilizer_kg = total("fertilizer_kg"); total_co2e = total("total_co2e_kg")
        return {
            "yield_kg": yield_kg, "water_m3": water_m3, "fertilizer_kg": fertilizer_kg,
            "total_co2e_kg": total_co2e,
            "water_per_kg": water_m3 / yield_kg if water_m3 is not None and yield_kg else None,
            "fertilizer_per_kg": fertilizer_kg / yield_kg if fertilizer_kg is not None and yield_kg else None,
            "co2e_per_kg": total_co2e / yield_kg if total_co2e is not None and yield_kg else None,
            "cost_per_kg": None,  # chưa tổng hợp cost ở cấp farm/org — metrics() không trả cost_per_kg per-season để cộng
            "data_completeness": {
                "water": water_m3 is not None, "fertilizer": fertilizer_kg is not None,
                "cost": False, "carbon": total_co2e is not None,
            },
        }

    def organization_metrics(self, organization_id: str) -> dict[str, Any]:
        return self._aggregate_metrics(self._season_ids_for_farms(self._organization_farms(organization_id)))

    def farm_crop_seasons(self, farm_id: str) -> list[dict[str, Any]]:
        self._one("farms", farm_id)
        seasons: list[dict[str, Any]] = []
        for plot in self._many("plots", farm_id=farm_id):
            seasons.extend(self.season_view(x) for x in self._many("crop_seasons", plot_id=str(plot["id"])))
        return seasons

    def farm_metrics(self, farm_id: str) -> dict[str, Any]:
        self._one("farms", farm_id)
        season_ids: list[str] = []
        for plot in self._many("plots", farm_id=farm_id):
            season_ids.extend(str(s["id"]) for s in self._many("crop_seasons", plot_id=str(plot["id"])))
        return self._aggregate_metrics(season_ids)

    def organization_summary(self, organization_id: str) -> dict[str, Any]:
        farms = self._organization_farms(organization_id); plots = []; seasons = []
        for farm in farms:
            farm_plots = self._many("plots", farm_id=str(farm["id"])); plots.extend(farm_plots)
            for plot in farm_plots: seasons.extend(self._many("crop_seasons", plot_id=str(plot["id"])))
        metrics = [self.metrics(str(season["id"])) for season in seasons]
        complete = [m for m in metrics if m["yield_kg"] is not None and m["total_co2e_kg"] is not None]
        total_yield = sum(float(m["yield_kg"]) for m in complete) if len(complete) == len(metrics) else None
        total_co2e = sum(float(m["total_co2e_kg"]) for m in complete) if len(complete) == len(metrics) else None
        return {"organization_id": organization_id, "farm_count": len(farms), "plot_count": len(plots), "crop_season_count": len(seasons), "total_area_ha": sum(float(p["area_ha"]) for p in plots), "total_yield_kg": total_yield, "total_co2e_kg": total_co2e, "co2e_per_kg": total_co2e / total_yield if total_yield and total_co2e is not None else None}

    def farm_performance(self, organization_id: str) -> list[dict[str, Any]]:
        items = []
        for farm in self._organization_farms(organization_id):
            plots = self._many("plots", farm_id=str(farm["id"])); seasons = [s for p in plots for s in self._many("crop_seasons", plot_id=str(p["id"]))]; ms = [self.metrics(str(s["id"])) for s in seasons]
            complete = [m for m in ms if m["yield_kg"] is not None]; yield_kg = sum(float(m["yield_kg"]) for m in complete) if len(complete) == len(ms) else None
            carbon = [m for m in ms if m["total_co2e_kg"] is not None]; total_co2e = sum(float(m["total_co2e_kg"]) for m in carbon) if len(carbon) == len(ms) else None
            status = "complete" if ms and all(all(m["data_completeness"].values()) for m in ms) else "partial" if ms else "missing"
            items.append({"farm_id": farm["id"], "farm_name": farm["farm_name"], "area_ha": sum(float(p["area_ha"]) for p in plots), "yield_kg": yield_kg, "water_per_kg": None, "fertilizer_per_kg": None, "co2e_per_kg": total_co2e / yield_kg if total_co2e is not None and yield_kg else None, "cost_per_kg": None, "data_status": status})
        return items

    def mrv_cases(self) -> list[dict[str, Any]]:
        return [self.mrv_case(str(row["id"])) for row in self._many("mrv_cases")]

    def mrv_case(self, case_id: str) -> dict[str, Any]:
        case = self._one("mrv_cases", case_id)
        return {"case_id": case["id"], "case_code": case["case_code"], "name": case["name"], "period_start": case["period_start"], "period_end": case["period_end"], "status": case["status"], "organization_id": case["organization_id"], "steps": self.mrv_steps(case_id), "batch_count": len(self._many("mrv_case_batches", mrv_case_id=case_id)), "evidence_count": len(self._many("mrv_evidence", mrv_case_id=case_id))}

    # -- Production batches: traceability only, KHÔNG phải scope tính carbon --

    def _batch_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "crop_season_id", "batch_code", "name", "started_on", "closed_on", "status")}

    def production_batches(self, season_id: str) -> list[dict[str, Any]]:
        self._one("crop_seasons", season_id)
        return [self._batch_view(x) for x in self._many("production_batches", crop_season_id=season_id) if x.get("deleted_at") is None]

    def production_batch(self, batch_id: str) -> dict[str, Any]:
        return self._batch_view(self._one("production_batches", batch_id))

    # -- Emission factor sets: chỉ published, farmer không sửa được --

    def _ef_set_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "version_code", "name", "description", "methodology_name", "methodology_version", "valid_from", "valid_to", "source_name", "source_url", "status", "published_at")}

    def emission_factor_sets(self) -> list[dict[str, Any]]:
        return [self._ef_set_view(x) for x in self._many("emission_factor_sets", status="published")]

    def emission_factor_set(self, set_id: str) -> dict[str, Any]:
        row = self._one("emission_factor_sets", set_id)
        if row.get("status") != "published":
            raise ReadNotFoundError("emission_factor_sets")
        return self._ef_set_view(row)

    def _ef_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "factor_set_id", "factor_code", "category", "gas", "activity_unit", "result_unit", "factor_value", "source_reference", "notes")}

    def emission_factors(self, set_id: str) -> list[dict[str, Any]]:
        self.emission_factor_set(set_id)
        return [self._ef_view(x) for x in self._many("emission_factors", factor_set_id=set_id)]

    # -- MRV sub-resources: read-only, không tạo/sửa. Case đã qua RLS trong mrv_case()/_one --

    MRV_STEP_LABELS = ["Chuẩn bị", "Đăng ký", "Thiết lập đường cơ sở", "Đo đạc", "Báo cáo", "Thẩm định"]

    def mrv_steps(self, case_id: str) -> list[dict[str, Any]]:
        self._one("mrv_cases", case_id)
        by_no = {int(x["step_no"]): x for x in self._many("mrv_case_steps", mrv_case_id=case_id)}
        return [
            {
                "step_no": n, "name": label,
                "status": by_no.get(n, {}).get("status", "not_started"),
                "started_at": by_no.get(n, {}).get("started_at"),
                "completed_at": by_no.get(n, {}).get("completed_at"),
                "notes": by_no.get(n, {}).get("notes"),
            }
            for n, label in enumerate(self.MRV_STEP_LABELS, 1)
        ]

    def mrv_batches(self, case_id: str) -> list[dict[str, Any]]:
        self._one("mrv_cases", case_id)
        links = self._many("mrv_case_batches", mrv_case_id=case_id)
        items: list[dict[str, Any]] = []
        for link in links:
            batch = self._one("production_batches", str(link["production_batch_id"]))
            season = self._one("crop_seasons", str(batch["crop_season_id"]))
            plot = self._one("plots", str(season["plot_id"]))
            items.append({
                "production_batch_id": batch["id"], "batch_code": batch["batch_code"],
                "crop_season_id": season["id"], "farm_id": plot["farm_id"], "plot_id": plot["id"],
            })
        return items

    def mrv_evidence(self, case_id: str) -> list[dict[str, Any]]:
        self._one("mrv_cases", case_id)
        return [
            {key: row.get(key) for key in ("id", "step_no", "production_batch_id", "evidence_type", "file_name", "mime_type", "storage_bucket", "storage_object_path", "sha256", "uploaded_at")}
            for row in self._many("mrv_evidence", mrv_case_id=case_id)
        ]

    def _export_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "mrv_case_id", "format", "factor_set_id", "scope_description", "data_as_of_at", "contains_sample_data", "is_finalized", "warning_text", "storage_bucket", "storage_object_path", "file_sha256", "generated_at")}

    def mrv_exports(self, case_id: str) -> list[dict[str, Any]]:
        self._one("mrv_cases", case_id)
        return [self._export_view(x) for x in self._many("mrv_exports", mrv_case_id=case_id)]

    def mrv_export(self, export_id: str) -> dict[str, Any]:
        # Không lọc theo case trước — mrv_exports không phải resource lồng duy nhất
        # (route GET /v1/mrv/exports/{id} độc lập); giống production_batch()/
        # emission_factor_set(), dựa vào RLS của chính bảng mrv_exports để chặn
        # truy cập chéo tổ chức, không tự suy luận quyền bằng code Python.
        return self._export_view(self._one("mrv_exports", export_id))
