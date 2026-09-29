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

import contextvars
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from carbon import SCENARIO_TO_DB

from . import profiling
from .config import Settings
from .mapping import RawCropBundle
from .repository import CropNotFoundError, FactorSetNotFoundError

try:  # httpx ships with supabase; a fake-client test never needs it
    import httpx
    _TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (httpx.TransportError,)
except Exception:  # noqa: BLE001 - absence just disables the retry below
    _TRANSPORT_ERRORS = ()

# Same policy as `read_repo.SupabaseReadRepository`: enough to ride out a
# keep-alive connection the server closed while idle ("Server disconnected"),
# not enough to paper over Supabase being down. READS ONLY -- writes are never
# retried (the commit state of a failed write is unknown).
_READ_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.15

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

    def _read(self, run: Callable[[Any], Any]) -> Any:
        """Run one idempotent read; on a dead connection drop the client (a new
        one is created lazily) and try again. Never used for inserts/deletes."""
        for remaining in range(_READ_ATTEMPTS - 1, -1, -1):
            try:
                return run(self.client)
            except _TRANSPORT_ERRORS:
                if remaining == 0 or self._settings is None:
                    raise
                time.sleep(_RETRY_BACKOFF_SECONDS)
                self._client = None
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _concurrent(*thunks: Callable[[], Any]) -> tuple[Any, ...]:
        """Independent reads overlapped instead of one round trip at a time.

        Same requests, same rows, same order of results — only the network
        latency overlaps (Round 5: 16 sequential PostgREST calls made one
        calculation take 3.5–9 s). Each thunk runs in its own copy of the
        caller's context so the request profiler still attributes it.
        """
        if len(thunks) <= 1:
            return tuple(t() for t in thunks)
        with ThreadPoolExecutor(max_workers=len(thunks)) as pool:
            futures = [pool.submit(contextvars.copy_context().run, t) for t in thunks]
            return tuple(f.result() for f in futures)

    def get_crop_bundle(self, crop_season_id: str) -> RawCropBundle:
        crop = self._one("crop_seasons", {"id": crop_season_id})
        if crop is None or crop.get("deleted_at") is not None:
            raise CropNotFoundError(f"Không tìm thấy vụ canh tác '{crop_season_id}'.")

        # plot and batches depend only on the season; farm only on the plot,
        # activities only on the batches.
        plot, batches = self._concurrent(
            lambda: self._one("plots", {"id": crop["plot_id"]}) or {},
            lambda: self._many("production_batches", {"crop_season_id": crop_season_id}),
        )
        batch_ids = [b["id"] for b in batches if b.get("deleted_at") is None]

        farm, *per_batch = self._concurrent(
            lambda: self._one("farms", {"id": plot["farm_id"]}) if plot.get("farm_id") else None,
            *[lambda b=batch_id: self._many("activities", {"production_batch_id": b}) for batch_id in batch_ids],
        )
        activities: list[dict[str, Any]] = [a for rows in per_batch for a in rows]
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

        def read_table(table: str, ids: list[str]) -> list[dict[str, Any]]:
            with profiling.observe(f"carbon select {table} in"):
                return self._read(
                    lambda c: c.table(table).select("*").in_("activity_id", ids).execute()
                ).data or []

        wanted = [(DETAIL_TABLES[t], ids) for t, ids in by_type.items() if DETAIL_TABLES.get(t) and ids]
        detail_by_activity: dict[str, dict[str, Any]] = {}
        # One table per activity type, all independent: read them together.
        for rows in self._concurrent(*[lambda t=t, i=i: read_table(t, i) for t, i in wanted]):
            for row in rows:
                detail_by_activity[row["activity_id"]] = row

        for activity in activities:
            activity["detail"] = detail_by_activity.get(activity["id"], {})

    # -- bộ hệ số ----------------------------------------------------------

    def resolve_factor_set_id(self, version_code: str) -> str:
        # A published factor set is immutable (status + version_code never
        # change once published), so its id is cached per process.
        cache = self.__dict__.setdefault("_factor_set_ids", {})
        if version_code in cache:
            return cache[version_code]
        cache[version_code] = self._resolve_factor_set_id(version_code)
        return cache[version_code]

    def _resolve_factor_set_id(self, version_code: str) -> str:
        with profiling.observe("carbon select emission_factor_sets"):
            rows = self._read(
                lambda c: c.table("emission_factor_sets").select("id,status")
                .eq("version_code", version_code).execute()
            ).data or []
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
        cache = self.__dict__.setdefault("_factor_ids", {})
        if factor_set_id not in cache:
            cache[factor_set_id] = self._factor_ids_by_code(factor_set_id)
        return dict(cache[factor_set_id])

    def _factor_ids_by_code(self, factor_set_id: str) -> dict[str, str]:
        with profiling.observe("carbon select emission_factors"):
            rows = self._read(
                lambda c: c.table("emission_factors").select("id,factor_code")
                .eq("factor_set_id", factor_set_id).execute()
            ).data or []
        return {r["factor_code"]: r["id"] for r in rows}

    def factor_set_version(self, factor_set_id: str) -> str | None:
        """version_code của một bộ hệ số, để bản tính đã lưu nói được nó dùng bộ nào.

        Bộ hệ số là bất biến sau khi publish, nên cache theo id trong tiến trình.
        """
        cache = self.__dict__.setdefault("_factor_set_versions", {})
        if factor_set_id not in cache:
            with profiling.observe("carbon select emission_factor_sets"):
                rows = self._read(
                    lambda c: c.table("emission_factor_sets").select("version_code")
                    .eq("id", factor_set_id).limit(1).execute()
                ).data or []
            if not rows:
                return None
            cache[factor_set_id] = rows[0].get("version_code")
        return cache[factor_set_id]

    # -- ghi ---------------------------------------------------------------

    def save_calculation(
        self, calculation: dict[str, Any], breakdowns: list[dict[str, Any]]
    ) -> str:
        """Ghi bản tính; tính lại với ĐÚNG đầu vào cũ trả lại bản tính đã có.

        `carbon_calculations_season_input_uniq` (crop_season_id, scenario, factor_set_id,
        input_hash) chặn bản trùng. Cùng input_hash nghĩa là cùng kết quả, nên trả id cũ
        (idempotent) thay vì để unique violation thành 500. Bắt lỗi sau insert thay vì
        select trước để không có race giữa hai người ghi cùng lúc.
        """
        from postgrest.exceptions import APIError

        try:
            with profiling.observe("carbon insert carbon_calculations"):
                inserted = self.client.table("carbon_calculations").insert(calculation).execute().data
        except APIError as exc:
            if exc.code != "23505":
                raise
            existing = self._existing_calculation_id(calculation)
            if existing is None:
                raise
            return existing
        calc_id = inserted[0]["id"]
        if breakdowns:
            try:
                with profiling.observe("carbon insert carbon_breakdowns"):
                    self.client.table("carbon_breakdowns").insert(
                        [{**b, "calculation_id": calc_id} for b in breakdowns]
                    ).execute()
            except Exception:
                # The two inserts are separate PostgREST requests, not one
                # transaction. A "succeeded" calculation without its breakdown
                # must not survive: a retry with the same input_hash would
                # otherwise reuse it forever. Best-effort; the original error
                # is the one reported (breakdowns cascade on delete).
                try:
                    self.client.table("carbon_calculations").delete().eq("id", calc_id).execute()
                except Exception:  # noqa: BLE001
                    pass
                raise
        return calc_id

    def _existing_calculation_id(self, calculation: dict[str, Any]) -> str | None:
        def run(client: Any) -> Any:
            query = client.table("carbon_calculations").select("id").is_("production_batch_id", "null")
            for column in ("crop_season_id", "scenario", "factor_set_id", "input_hash"):
                query = query.eq(column, calculation[column])
            return query.limit(1).execute()
        with profiling.observe("carbon select carbon_calculations"):
            rows = self._read(run).data or []
        return rows[0]["id"] if rows else None

    def latest_calculation(
        self, crop_season_id: str, scenario: str | None = None
    ) -> dict[str, Any] | None:
        def run(client: Any) -> Any:
            query = (
                client.table("carbon_calculations")
                .select("*")
                .eq("crop_season_id", crop_season_id)
                .eq("status", "succeeded")  # không trả bản tính thất bại như kết quả thành công
                .order("calculated_at", desc=True)
                .limit(1)
            )
            if scenario:
                query = query.eq("scenario", SCENARIO_TO_DB.get(scenario, scenario))
            return query.execute()
        with profiling.observe("carbon select carbon_calculations"):
            rows = self._read(run).data or []
        if not rows:
            return None

        latest = rows[0]
        with profiling.observe("carbon select carbon_breakdowns"):
            latest["breakdown"] = self._read(
                lambda c: c.table("carbon_breakdowns").select("*")
                .eq("calculation_id", latest["id"]).execute()
            ).data or []
        return latest

    # -- tiện ích ----------------------------------------------------------

    def _one(self, table: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        rows = self._many(table, filters)
        return rows[0] if rows else None

    def _many(self, table: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        def run(client: Any) -> Any:
            query = client.table(table).select("*")
            for column, value in filters.items():
                query = query.eq(column, value)
            return query.execute()
        with profiling.observe(f"carbon select {table}"):
            return self._read(run).data or []
