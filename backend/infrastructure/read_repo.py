"""Read-only dashboard repository.

Every request creates a publishable-key client and binds the caller JWT before
reading.  RLS therefore remains the tenant boundary; this module never uses a
service-role key and never accepts a user id supplied by the frontend.
"""
from __future__ import annotations

import math

import contextvars
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import auth, memberships, profiling, supabase_clients
from .auth_admin import must_change_password
from .config import Settings

DETAIL_TABLES = {
    "seeding": "seeding_events", "fertilizer": "fertilizer_applications",
    "irrigation": "irrigation_events", "pesticide": "pesticide_applications",
    "fuel": "fuel_usages", "straw_management": "straw_management_events",
    "harvest": "harvest_events",
}

# MVP cost means directly recorded activity/input cost.  Labor and contract
# machinery do not have separate fields in the current contract, so they are
# never inferred here.
# Fertilizer records that carry an N/P/K share (same keys as the web's seasonFacts).
_NUTRIENT_FIELDS = ("nitrogen_percent", "phosphorus_percent", "potassium_percent", "n_percent")


def _as_number(value: Any) -> float | None:
    """The web's `toNumber`: a finite number, or a non-blank numeric string; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


_COST_FIELD_BY_ACTIVITY = {
    "seeding": "cost_vnd",
    "fertilizer": "total_cost_vnd",
    "irrigation": "total_cost_vnd",
    "pesticide": "total_cost_vnd",
    "fuel": "total_cost_vnd",
    "straw_management": "total_cost_vnd",
    "harvest": "total_cost_vnd",
}

try:  # httpx ships with supabase; a fake-client test never needs it
    import httpx
    _TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (httpx.TransportError,)
except Exception:  # noqa: BLE001 - absence just disables the retry below
    _TRANSPORT_ERRORS = ()

# Small on purpose: enough to ride out a connection being closed under us,
# not enough to paper over Supabase actually being down.
_READ_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.15
# Round 5.1: right after sign-in, hosted PostgREST can reject a brand-new JWT
# with PGRST303 "JWT issued at future" (its clock trails Auth's by < 1 s). The
# token becomes valid a moment later, so this one rejection is retried once
# after a short wait instead of surfacing as a 500 (without CORS headers).
_CLOCK_SKEW_WAIT_SECONDS = 1.0


def _is_clock_skew(exc: BaseException) -> bool:
    return getattr(exc, "code", None) == "PGRST303" and "future" in str(getattr(exc, "message", exc)).lower()


class ReadNotFoundError(Exception): pass

class SupabaseReadRepository:
    def __init__(self, settings: Settings, token: str, client: Any | None = None):
        self._settings = settings
        self._pooled = client is None
        if client is None:
            # Reused per caller token (see supabase_clients): already bound to
            # this exact JWT, so it must not be re-authenticated here.
            self.client = supabase_clients.client_for_token(settings, token)
        else:
            self.client = client
            self.client.postgrest.auth(token)
        self.token = token

    def _retrying(self, attempt: Callable[[], Any]) -> Any:
        """Run one idempotent read, replacing the client on a dead connection.

        Reusing a client means reusing its keep-alive connections, and Supabase
        closes them whenever it likes; httpx then raises
        `RemoteProtocolError: Server disconnected` on the next read that picks
        one. Because Supabase speaks HTTP/2, a single close takes down every
        read multiplexed on that connection at once, and a burst of them can
        also catch the replacement's first request — measured against hosted
        Supabase, one retry left about 1% of reads still failing, which is a
        Farmer page section showing an error for no reason the farmer caused.

        These reads are idempotent, so a bounded number of attempts on a fresh
        client is the right answer. It is deliberately small: a genuine
        Supabase outage must still surface as an error rather than be hidden
        behind retries.
        """
        # A rejected JWT is a verdict, not a transport hiccup: it is the same on
        # every attempt, so it must leave this loop as `InvalidTokenError` (-> 401)
        # instead of escaping raw and becoming a 500.
        with auth.jwt_rejection_as_invalid_token():
            transport_retries, skew_retried = _READ_ATTEMPTS - 1, False
            while True:
                failed = self.client
                try:
                    return attempt()
                except Exception as exc:  # noqa: BLE001 - re-raised unless it is one of the two retryable cases
                    if _is_clock_skew(exc) and not skew_retried:
                        skew_retried = True
                        time.sleep(_CLOCK_SKEW_WAIT_SECONDS)
                        continue
                    if not isinstance(exc, _TRANSPORT_ERRORS) or not self._pooled or transport_retries == 0:
                        raise
                    transport_retries -= 1
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                    self.client = supabase_clients.renew(self._settings, self.token, failed)

    def _select(self, label: str, build: Callable[[Any], Any]) -> list[dict[str, Any]]:
        with profiling.observe(label):
            return self._retrying(lambda: build(self.client).execute().data or [])

    def _many(self, table: str, **filters: str) -> list[dict[str, Any]]:
        def build(client: Any) -> Any:
            query = client.table(table).select("*")
            for key, value in filters.items(): query = query.eq(key, value)
            return query
        return self._select(f"select {table}", build)

    def _many_in(self, table: str, column: str, values: list[str]) -> list[dict[str, Any]]:
        """Same as `_many` but for `column IN (values)` — one hosted-Supabase
        round trip for many parent ids instead of one round trip per id.  The
        per-id loop this replaces is the actual measured cause of the
        multi-second/minute organization rollup latency (see
        docs/FARMER_PERFORMANCE_ROUND4.md) — RLS still applies identically,
        this only changes how many requests fetch the same allowed rows.
        """
        if not values: return []
        return self._select(
            f"select {table} in",
            lambda client: client.table(table).select("*").in_(column, values),
        )

    def _one(self, table: str, id: str) -> dict[str, Any]:
        rows = self._many(table, id=id)
        if not rows: raise ReadNotFoundError(table)
        return rows[0]

    def _concurrent(self, *thunks: Callable[[], Any]) -> tuple[Any, ...]:
        """Run independent zero-arg callables concurrently instead of one
        network round trip at a time — each still issues its own PostgREST
        request through this same caller-bound client, so RLS/auth are
        unaffected; this only overlaps otherwise-sequential network latency
        (the measured cause of multi-second rollups, see
        docs/FARMER_PERFORMANCE_ROUND4.md). Results come back in the
        same order as `thunks`; if any raised, that exception propagates
        (after every thread has finished) instead of a value at that index —
        callers that must gate on one result before trusting another (e.g.
        an authorization check) keep that ordering by reading results in the
        same order they matter, since `.result()` re-raises at that point.
        """
        if len(thunks) == 1: return (thunks[0](),)
        # ThreadPoolExecutor does not carry the caller's context into its
        # workers, so each thunk runs inside its own copy of it — that is what
        # keeps request-scoped state (the read profiler) attributed to the
        # request that issued these reads instead of silently dropped. One
        # copy per thunk, not one shared copy: a `Context` cannot be entered
        # by two threads at once.
        with ThreadPoolExecutor(max_workers=len(thunks)) as pool:
            futures = [pool.submit(contextvars.copy_context().run, t) for t in thunks]
            return tuple(f.result() for f in futures)

    def _auth_user(self) -> Any:
        with profiling.observe("auth get_user"):
            user = self._retrying(lambda: self.client.auth.get_user(self.token).user)
        if user is None: raise ReadNotFoundError("user")
        return user

    def user_id(self) -> str:
        return str(self._auth_user().id)

    def me(self) -> dict[str, Any]:
        user = self._auth_user()
        user_id = str(user.id)
        # profile/orgs/farms are 3 independent filters on user_id — nothing
        # here depends on another's result, so they run concurrently instead
        # of as 3 sequential round trips.
        profile, orgs, farms = self._concurrent(
            lambda: self._one("profiles", user_id),
            lambda: self._many("organization_memberships", user_id=user_id),
            lambda: self._many("farm_members", user_id=user_id),
        )
        # RLS lets a user read their own membership rows even after they end, so
        # the ended ones come back here. Neither `roles` nor the membership list
        # may advertise them: every consumer (the Farmer write/recommendation/CV
        # gates, web role routing, the MRV management check) must see exactly the
        # memberships the SQL helpers treat as active.
        orgs = memberships.active_memberships(orgs)
        return {"user_id": user_id, "full_name": profile.get("full_name"), "organization_memberships": orgs, "farm_memberships": farms, "roles": sorted({str(x["role"]) for x in orgs} | {str(x["farm_role"]) for x in farms}),
                "must_change_password": must_change_password(getattr(user, "app_metadata", None))}

    @staticmethod
    def _farm_view(row: dict[str, Any], plot_count: int) -> dict[str, Any]:
        return {"id": row["id"], "farm_code": row["farm_code"], "farm_name": row["farm_name"], "province_name": row.get("province_name"), "district_name": row.get("district_name"), "commune_name": row.get("commune_name"), "plot_count": plot_count}

    def farms(self) -> list[dict[str, Any]]:
        rows = self._many("farms")
        plots = self._many("plots")
        counts: dict[str, int] = defaultdict(int)
        for plot in plots: counts[str(plot["farm_id"])] += 1
        return [self._farm_view(row, counts[str(row["id"])]) for row in rows]

    def farmer_scope(self) -> dict[str, Any]:
        """Every farm, plot and crop season the caller can read, in ONE client
        round trip instead of the farms -> plots-per-farm -> seasons-per-plot
        waterfall the Farmer app used to issue (measured: 7-15s to first
        content). Pure read composition of existing views — no new business
        rule. The three reads are independent and RLS-scoped, so they run
        concurrently; rows are then chained season -> visible plot -> visible
        farm so a partially visible hierarchy never returns an orphan id.
        """
        farm_rows, plot_rows, season_rows = self._concurrent(
            lambda: self._many("farms"),
            lambda: self._many("plots"),
            lambda: self._many("crop_seasons"),
        )
        farm_ids = {str(f["id"]) for f in farm_rows}
        plots = [p for p in plot_rows if str(p["farm_id"]) in farm_ids]
        plot_ids = {str(p["id"]) for p in plots}
        seasons = [s for s in season_rows if str(s["plot_id"]) in plot_ids]
        counts: dict[str, int] = defaultdict(int)
        for plot in plots: counts[str(plot["farm_id"])] += 1
        return {
            "farms": [self._farm_view(row, counts[str(row["id"])]) for row in farm_rows],
            "plots": [self.plot_view(p) for p in plots],
            "crop_seasons": [self.season_view(s) for s in seasons],
        }

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
        # The last three are IPCC methodology inputs (migration 20260908): the engine
        # reads them straight off `crop_seasons`, so a client that cannot SEE them
        # cannot tell the user which Carbon input is still missing.
        return {key: row.get(key) for key in ("id", "plot_id", "season_code", "crop_type", "variety_name", "planting_date", "expected_harvest_date", "actual_harvest_date", "status", "ipcc_water_regime", "pre_season_water_regime", "cultivation_days")}

    def season(self, season_id: str) -> dict[str, Any]: return self.season_view(self._one("crop_seasons", season_id))
    def seasons_for_plot(self, plot_id: str) -> list[dict[str, Any]]:
        self._one("plots", plot_id); return [self.season_view(x) for x in self._many("crop_seasons", plot_id=plot_id)]

    def _activities(self, season_id: str) -> list[dict[str, Any]]:
        # The season read is the 404/RLS gate and `production_batches` does not
        # depend on its *value*, so the two overlap; the gate's result is still
        # read first, so an invisible season raises before any batch row is
        # returned (same ordering rule as `_organization_farms`).
        season, batches = self._concurrent(
            lambda: self._one("crop_seasons", season_id),
            lambda: self._many("production_batches", crop_season_id=season_id),
        )
        del season
        batch_ids = [str(x["id"]) for x in batches]
        # One `IN` query for every batch instead of one query per batch.
        rows = self._many_in("activities", "production_batch_id", batch_ids)
        return [x for x in rows if x.get("deleted_at") is None]

    def recommendations(self, season_id: str) -> list[dict[str, Any]]:
        self._one("crop_seasons", season_id)
        rows = self._many("season_recommendations", crop_season_id=season_id)
        return sorted(rows, key=lambda x: str(x.get("generated_at") or ""))

    def _details_by_activity_id(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """One batched `IN` query per distinct activity_type present, instead
        of one query per (detail table, activity_id) pair — `rows` already
        carries `activity_type`, so which of the 7 detail tables a given
        activity lives in is already known; no need to probe all 7.

        The per-type queries are independent of each other (different
        tables, disjoint activity ids), so they run concurrently rather than
        one-at-a-time — with all 7 detail tables present this was the single
        largest sequential chain inside an organization rollup.
        """
        by_type: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            table = DETAIL_TABLES.get(str(row["activity_type"]))
            if table: by_type[table].append(str(row["id"]))
        if not by_type: return {}
        results = self._concurrent(*(
            (lambda t=table, ids=activity_ids: self._many_in(t, "activity_id", ids))
            for table, activity_ids in by_type.items()
        ))
        details: dict[str, dict[str, Any]] = {}
        for found_rows in results:
            for found in found_rows:
                details[str(found["activity_id"])] = found
        return details

    def activities(self, season_id: str) -> list[dict[str, Any]]:
        rows = self._activities(season_id)
        # `profiles` is an unfiltered read that depends on nothing here, so it
        # overlaps the per-type detail reads instead of following them.
        details, users_rows = self._concurrent(
            lambda: self._details_by_activity_id(rows),
            lambda: self._many("profiles"),
        )
        users = {str(x["id"]): x.get("full_name") for x in users_rows}
        # Newest first, deterministically (Round 5.1): pages of the paginated
        # endpoint are stable, and page 1 is the season's most recent records.
        ordered = sorted(rows, key=lambda x: (str(x.get("occurred_at") or ""), str(x.get("recorded_at") or ""),
                                              str(x["id"])), reverse=True)
        return [self._activity_view(x, details.get(str(x["id"]), {}), users) for x in ordered]

    def activity_summary(self, season_id: str) -> dict[str, Any]:
        """Whole-season facts of the journal, so Home can load only recent records.

        Exactly what the web's `seasonFacts` and season-date helpers derive from
        the full activity list (same rows as `activities`, same cost fields,
        same number parsing), plus the record count.
        """
        items = self.activities(season_id)
        by_type: dict[str, dict[str, Any]] = {}
        harvests = harvests_with_area = 0
        harvested_area = 0.0
        fertilizer_has_nutrient = False
        first_seeding: str | None = None
        last_harvest: str | None = None
        for a in items:
            kind, payload, at = str(a["activity_type"]), a.get("payload") or {}, a.get("occurred_at")
            at_text = str(at) if at else None
            if kind == "harvest":
                harvests += 1
                area = _as_number(payload.get("harvested_area_ha"))
                if area is not None and area > 0:
                    harvested_area += area
                    harvests_with_area += 1
                if at_text and (last_harvest is None or at_text > last_harvest):
                    last_harvest = at_text
            if kind == "seeding" and at_text and (first_seeding is None or at_text < first_seeding):
                first_seeding = at_text
            if kind == "fertilizer" and any(_as_number(payload.get(k)) is not None for k in _NUTRIENT_FIELDS):
                fertilizer_has_nutrient = True
            field = _COST_FIELD_BY_ACTIVITY.get(kind)
            if field is None:
                continue
            entry = by_type.setdefault(kind, {"records": 0, "with_cost": 0, "recorded_vnd": 0.0})
            entry["records"] += 1
            cost = _as_number(payload.get(field))
            if cost is not None:
                entry["with_cost"] += 1
                entry["recorded_vnd"] += cost
        counts: dict[str, int] = {}
        for a in items:
            counts[str(a["activity_type"])] = counts.get(str(a["activity_type"]), 0) + 1
        return {
            "crop_season_id": season_id, "total": len(items), "count_by_type": counts,
            "cost_by_type": by_type, "harvests": harvests, "harvests_with_area": harvests_with_area,
            "harvested_area_ha": harvested_area, "fertilizer_has_nutrient": fertilizer_has_nutrient,
            "first_seeding_at": first_seeding, "last_harvest_at": last_harvest,
        }

    def _bulk_activities_by_season(self, season_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Same shape as calling `activities(season_id)` for each id, but a
        fixed ~4 requests total (batches, activities, per-type details,
        profiles) instead of `O(seasons × detail types)` — this is what
        actually made the organization/farm rollups take 12-15s instead of
        instant even after the per-season N+1 fix: each season was still its
        own fully sequential round-trip chain. Used only by rollups; the
        single-season `activities()` path (season hub page) is unaffected.
        """
        if not season_ids: return {sid: [] for sid in season_ids}

        def _batches_then_activities() -> tuple[dict[str, str], list[dict[str, Any]]]:
            batches = self._many_in("production_batches", "crop_season_id", season_ids)
            season_by_batch = {str(b["id"]): str(b["crop_season_id"]) for b in batches}
            batch_ids = list(season_by_batch)
            rows = self._many_in("activities", "production_batch_id", batch_ids) if batch_ids else []
            return season_by_batch, [a for a in rows if a.get("deleted_at") is None]

        # `profiles` (no filter) never depends on batches/activities, so it
        # is fetched in parallel with that sequential 2-step chain instead of
        # after it.
        (season_by_batch, activity_rows), users_rows = self._concurrent(
            _batches_then_activities,
            lambda: self._many("profiles"),
        )
        details = self._details_by_activity_id(activity_rows)
        users = {str(x["id"]): x.get("full_name") for x in users_rows}
        by_season: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in activity_rows:
            sid = season_by_batch.get(str(row["production_batch_id"]))
            if sid: by_season[sid].append(self._activity_view(row, details.get(str(row["id"]), {}), users))
        return {sid: by_season.get(sid, []) for sid in season_ids}

    def _bulk_metric_totals(self, season_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Bulk-batched equivalent of calling `_metric_totals(season_id)` for
        each id — see `_bulk_activities_by_season` for why this exists.
        """
        # Independent of each other — activities come from
        # production_batches/activities/detail tables, carbon_calculations
        # is its own table filtered only by season id.
        activities_by_season, carbon_rows = self._concurrent(
            lambda: self._bulk_activities_by_season(season_ids),
            lambda: self._many_in("carbon_calculations", "crop_season_id", season_ids) if season_ids else [],
        )
        carbon_by_season: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in carbon_rows: carbon_by_season[str(row["crop_season_id"])].append(row)
        return {
            sid: self._compute_metric_totals(activities_by_season.get(sid, []), carbon_by_season.get(sid, []))
            for sid in season_ids
        }

    def _activity_view(self, row: dict[str, Any], detail: dict[str, Any], users: dict[str, str | None]) -> dict[str, Any]:
        return {"id": row["id"], "activity_type": row["activity_type"], "occurred_at": row["occurred_at"], "recorded_at": row["recorded_at"], "recorded_by": users.get(str(row.get("recorded_by"))), "source": row["source"], "payload": {**detail, "note": row.get("note")}}

    def activity(self, activity_id: str) -> dict[str, Any]:
        row = self._one("activities", activity_id)
        if row.get("deleted_at") is not None:
            raise ReadNotFoundError("activities")
        table = DETAIL_TABLES.get(str(row["activity_type"]))
        found = self._many(table, activity_id=activity_id) if table else []
        detail = found[0] if found else {}
        users = {str(x["id"]): x.get("full_name") for x in self._many("profiles")}
        return self._activity_view(row, detail, users)

    @staticmethod
    def _activity_cost_vnd(activity_type: str, payload: dict[str, Any]) -> float | None:
        field = _COST_FIELD_BY_ACTIVITY.get(activity_type)
        if field is None or payload.get(field) is None:
            return None
        return float(payload[field])

    def _metric_totals(self, season_id: str) -> dict[str, Any]:
        """Compute season numerators once; underscore keys are internal only."""
        # Independent: activities come from production_batches/activities/detail
        # tables, carbon_calculations is its own table filtered by season id.
        activities, carbon = self._concurrent(
            lambda: self.activities(season_id),
            lambda: self._many("carbon_calculations", crop_season_id=season_id),
        )
        return self._compute_metric_totals(activities, carbon)

    @staticmethod
    def _compute_metric_totals(activities: list[dict[str, Any]], carbon: list[dict[str, Any]]) -> dict[str, Any]:
        """Pure aggregation over already-fetched rows — no DB access — shared
        by the single-season path above and `_bulk_metric_totals` (rollups).
        """
        yield_kg = water_m3 = fertilizer_kg = total_cost = 0.0
        has_yield = has_cost = True
        # Seen at least one record / any record missing its value. Tracked
        # separately so the result cannot depend on which record comes last (B1):
        # one missing value anywhere makes the whole group incomplete.
        seen_water = missing_water = seen_fertilizer = missing_fertilizer = False
        for item in activities:
            payload = item["payload"]; kind = item["activity_type"]
            if kind == "harvest":
                if payload.get("yield_kg") is None: has_yield = False
                else: yield_kg += float(payload["yield_kg"])
            if kind == "irrigation":
                seen_water = True
                if payload.get("water_volume_m3") is None: missing_water = True
                else: water_m3 += float(payload["water_volume_m3"])
            if kind == "fertilizer":
                seen_fertilizer = True
                if payload.get("amount_kg") is None: missing_fertilizer = True
                else: fertilizer_kg += float(payload["amount_kg"])
            cost = SupabaseReadRepository._activity_cost_vnd(kind, payload)
            if cost is None: has_cost = False
            else: total_cost += cost
        has_water = seen_water and not missing_water
        has_fertilizer = seen_fertilizer and not missing_fertilizer
        succeeded = [x for x in carbon if x.get("status") == "succeeded" and x.get("scenario") == "actual"]
        latest = max(succeeded, key=lambda x: str(x.get("calculated_at")), default=None)
        y = yield_kg if has_yield and yield_kg > 0 else None
        co2e = float(latest["total_co2e_kg"]) if latest else None
        return {
            "yield_kg": y, "water_m3": water_m3 if has_water else None,
            "fertilizer_kg": fertilizer_kg if has_fertilizer else None,
            "total_co2e_kg": co2e,
            "water_per_kg": water_m3 / y if has_water and y else None,
            "fertilizer_per_kg": fertilizer_kg / y if has_fertilizer and y else None,
            "co2e_per_kg": co2e / y if co2e is not None and y else None,
            "cost_per_kg": total_cost / y if has_cost and y else None,
            "data_completeness": {
                "water": has_water, "fertilizer": has_fertilizer,
                "cost": has_cost, "carbon": latest is not None,
            },
            "_total_cost_vnd": total_cost if has_cost else None,
        }

    def metrics(self, season_id: str) -> dict[str, Any]:
        return {key: value for key, value in self._metric_totals(season_id).items() if not key.startswith("_")}

    def _organization_farms(self, organization_id: str) -> list[dict[str, Any]]:
        # Both requests fire concurrently, but the org lookup's result is
        # read first — if RLS/existence rejects it, that exception propagates
        # from `.result()` before the farms result is ever returned, so the
        # authorization gate (never trust the URL's org id alone) still
        # holds despite running them in parallel.
        org, farms = self._concurrent(
            lambda: self._one("organizations", organization_id),
            lambda: self._many("farms", cooperative_id=organization_id),
        )
        del org
        return farms

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

    def _plots_and_seasons_for_farms(self, farms: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Batched replacement for the old one-request-per-farm-then-per-plot
        loop: 2 requests total (all plots for these farms, then all seasons
        for those plots) instead of `len(farms) + len(plots)` requests.
        """
        farm_ids = [str(f["id"]) for f in farms]
        plots = self._many_in("plots", "farm_id", farm_ids)
        plot_ids = [str(p["id"]) for p in plots]
        seasons = self._many_in("crop_seasons", "plot_id", plot_ids)
        return plots, seasons

    def _season_ids_for_farms(self, farms: list[dict[str, Any]]) -> list[str]:
        _, seasons = self._plots_and_seasons_for_farms(farms)
        return [str(s["id"]) for s in seasons]

    def _aggregate_metrics(self, season_ids: list[str]) -> dict[str, Any]:
        """Tổng (sum), KHÔNG trung bình — cùng nguyên tắc organization_summary().

        null nếu BẤT KỲ vụ nào trong tập hợp thiếu dữ liệu của field đó, để không
        âm thầm bỏ qua vụ chưa đo — giống hệt cách metrics()/organization_summary() xử lý.
        """
        totals_by_season = self._bulk_metric_totals(season_ids)
        return self._aggregate_from_totals([totals_by_season[sid] for sid in season_ids])

    def organization_plots_and_seasons(self, organization_id: str) -> list[dict[str, Any]]:
        """Every farm of the organization with its plots and seasons, by RLS.

        Round 5.1: Management read `/farms/{id}/plots` and `/farms/{id}/crop-seasons`
        once PER FARM. This is the same rows through the same views
        (`plot_view`, `season_view`) and the same caller-bound client, in a fixed
        number of round trips: organization + farms, then all plots, then all
        seasons. Raises `ReadNotFoundError` when the organization is not visible.
        """
        farms = self._organization_farms(organization_id)
        plots, seasons = self._plots_and_seasons_for_farms(farms)
        farm_of_plot = {str(p["id"]): str(p["farm_id"]) for p in plots}
        out = []
        for farm in farms:
            fid = str(farm["id"])
            out.append({
                "farm_id": fid,
                "plots": [self.plot_view(p) for p in plots if str(p["farm_id"]) == fid],
                "crop_seasons": [self.season_view(s) for s in seasons if farm_of_plot.get(str(s["plot_id"])) == fid],
            })
        return out

    def organization_season_ids(self, organization_id: str) -> list[str]:
        """The organization's crop seasons this caller may read, by RLS.

        Same scope as the per-season Carbon routes' access check: each id here
        is one `crop_seasons` row the caller's JWT can select. Raises
        `ReadNotFoundError` when the organization itself is not visible.
        """
        return self._season_ids_for_farms(self._organization_farms(organization_id))

    def organization_metrics(self, organization_id: str) -> dict[str, Any]:
        return self._aggregate_metrics(self._season_ids_for_farms(self._organization_farms(organization_id)))

    def farm_crop_seasons(self, farm_id: str) -> list[dict[str, Any]]:
        farm = self._one("farms", farm_id)
        _, seasons = self._plots_and_seasons_for_farms([farm])
        return [self.season_view(s) for s in seasons]

    def farm_metrics(self, farm_id: str) -> dict[str, Any]:
        farm = self._one("farms", farm_id)
        _, seasons = self._plots_and_seasons_for_farms([farm])
        return self._aggregate_metrics([str(s["id"]) for s in seasons])

    @staticmethod
    def _aggregate_from_totals(ms: list[dict[str, Any]]) -> dict[str, Any]:
        """Shared by organization_metrics/farm_metrics (via _aggregate_metrics)
        and farm_performance — factored out so farm_performance can reuse the
        exact same per-season `_metric_totals` list it already computed for
        its own yield/co2e columns, instead of a second, redundant pass that
        redoes every activities()/detail-table fetch for the same seasons.
        """
        def total(key: str) -> float | None:
            if not ms: return None
            values = [m[key] for m in ms]
            if any(v is None for v in values): return None
            return sum(float(v) for v in values)

        yield_kg = total("yield_kg"); water_m3 = total("water_m3")
        fertilizer_kg = total("fertilizer_kg"); total_co2e = total("total_co2e_kg")
        total_cost = total("_total_cost_vnd")
        return {
            "yield_kg": yield_kg, "water_m3": water_m3, "fertilizer_kg": fertilizer_kg,
            "total_co2e_kg": total_co2e,
            "water_per_kg": water_m3 / yield_kg if water_m3 is not None and yield_kg else None,
            "fertilizer_per_kg": fertilizer_kg / yield_kg if fertilizer_kg is not None and yield_kg else None,
            "co2e_per_kg": total_co2e / yield_kg if total_co2e is not None and yield_kg else None,
            "cost_per_kg": total_cost / yield_kg if total_cost is not None and yield_kg else None,
            "data_completeness": {
                "water": water_m3 is not None, "fertilizer": fertilizer_kg is not None,
                "cost": total_cost is not None, "carbon": total_co2e is not None,
            },
        }

    def organization_summary(self, organization_id: str) -> dict[str, Any]:
        farms = self._organization_farms(organization_id)
        plots, seasons = self._plots_and_seasons_for_farms(farms)
        season_ids = [str(s["id"]) for s in seasons]
        totals_by_season = self._bulk_metric_totals(season_ids)
        metrics = [totals_by_season[sid] for sid in season_ids]
        complete = [m for m in metrics if m["yield_kg"] is not None and m["total_co2e_kg"] is not None]
        total_yield = sum(float(m["yield_kg"]) for m in complete) if len(complete) == len(metrics) else None
        total_co2e = sum(float(m["total_co2e_kg"]) for m in complete) if len(complete) == len(metrics) else None
        return {"organization_id": organization_id, "farm_count": len(farms), "plot_count": len(plots), "crop_season_count": len(seasons), "total_area_ha": sum(float(p["area_ha"]) for p in plots), "total_yield_kg": total_yield, "total_co2e_kg": total_co2e, "co2e_per_kg": total_co2e / total_yield if total_yield and total_co2e is not None else None}

    def farm_performance(self, organization_id: str) -> list[dict[str, Any]]:
        farms = self._organization_farms(organization_id)
        plots, seasons = self._plots_and_seasons_for_farms(farms)
        plots_by_farm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in plots: plots_by_farm[str(p["farm_id"])].append(p)
        seasons_by_plot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in seasons: seasons_by_plot[str(s["plot_id"])].append(s)
        # One bulk-batched pass across the WHOLE org, not per farm/season —
        # each season appears in exactly one farm, so this is still exactly
        # one computation per season, just fetched together (fixed request
        # count) instead of separately per season (O(seasons) round trips).
        totals_by_season = self._bulk_metric_totals([str(s["id"]) for s in seasons])

        items = []
        for farm in farms:
            farm_plots = plots_by_farm[str(farm["id"])]
            farm_season_ids = [str(s["id"]) for p in farm_plots for s in seasons_by_plot[str(p["id"])]]
            ms = [totals_by_season[sid] for sid in farm_season_ids]
            aggregate = self._aggregate_from_totals(ms)
            complete = [m for m in ms if m["yield_kg"] is not None]; yield_kg = sum(float(m["yield_kg"]) for m in complete) if len(complete) == len(ms) else None
            carbon = [m for m in ms if m["total_co2e_kg"] is not None]; total_co2e = sum(float(m["total_co2e_kg"]) for m in carbon) if len(carbon) == len(ms) else None
            status = "complete" if ms and all(all(m["data_completeness"].values()) for m in ms) else "partial" if ms else "missing"
            items.append({"farm_id": farm["id"], "farm_name": farm["farm_name"], "area_ha": sum(float(p["area_ha"]) for p in farm_plots), "yield_kg": yield_kg, "water_per_kg": aggregate["water_per_kg"], "fertilizer_per_kg": aggregate["fertilizer_per_kg"], "co2e_per_kg": total_co2e / yield_kg if total_co2e is not None and yield_kg else None, "cost_per_kg": aggregate["cost_per_kg"], "data_status": status})
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

    def organization_mrv_batches(self, organization_id: str) -> list[dict[str, Any]]:
        """Every MRV case of the organization with its batches, by RLS.

        Round 5.1: Management read `/mrv/cases` (paginated: only the first 20
        cases) and then `/mrv/cases/{id}/batches` once PER CASE, and each of those
        read 3 rows per batch. This is the same rows through the same caller-bound
        client in a fixed number of round trips: organization, cases, links,
        batches, seasons, plots. A batch whose season/plot the caller cannot read
        is left out (never guessed). Raises `ReadNotFoundError` when the
        organization is not visible.
        """
        _, cases = self._concurrent(
            lambda: self._one("organizations", organization_id),
            lambda: self._many("mrv_cases", organization_id=organization_id),
        )
        links = self._many_in("mrv_case_batches", "mrv_case_id", [str(c["id"]) for c in cases])
        batches = {str(b["id"]): b for b in self._many_in(
            "production_batches", "id", sorted({str(link["production_batch_id"]) for link in links}))}
        seasons = {str(s["id"]): s for s in self._many_in(
            "crop_seasons", "id", sorted({str(b["crop_season_id"]) for b in batches.values()}))}
        plots = {str(p["id"]): p for p in self._many_in(
            "plots", "id", sorted({str(s["plot_id"]) for s in seasons.values()}))}
        by_case: dict[str, list[dict[str, Any]]] = {str(c["id"]): [] for c in cases}
        for link in links:
            batch = batches.get(str(link["production_batch_id"]))
            season = seasons.get(str(batch["crop_season_id"])) if batch else None
            plot = plots.get(str(season["plot_id"])) if season else None
            if plot is None:
                continue
            by_case[str(link["mrv_case_id"])].append({
                "production_batch_id": batch["id"], "batch_code": batch["batch_code"],
                "crop_season_id": season["id"], "farm_id": plot["farm_id"], "plot_id": plot["id"],
            })
        return [
            {"case_id": c["id"], "case_code": c["case_code"], "status": c["status"], "batches": by_case[str(c["id"])]}
            for c in sorted(cases, key=lambda c: str(c.get("case_code") or ""))
        ]

    def mrv_evidence(self, case_id: str) -> list[dict[str, Any]]:
        self._one("mrv_cases", case_id)
        return [
            {key: row.get(key) for key in ("id", "step_no", "production_batch_id", "evidence_type", "file_name", "mime_type", "storage_bucket", "storage_object_path", "sha256", "uploaded_at")}
            for row in self._many("mrv_evidence", mrv_case_id=case_id)
        ]

    def _export_view(self, row: dict[str, Any]) -> dict[str, Any]:
        # storage_bucket/storage_object_path are NOT returned: since M07 part 2 an
        # XLSX row names a real private object. Clients get the filename only;
        # the bytes come from the authorized download route.
        view = {key: row.get(key) for key in ("id", "mrv_case_id", "format", "factor_set_id", "scope_description", "data_as_of_at", "contains_sample_data", "is_finalized", "warning_text", "file_sha256", "payload_sha256", "source_snapshot_export_id", "generated_at", "generated_by")}
        view["file_name"] = str(row.get("storage_object_path") or "").rsplit("/", 1)[-1]
        return view

    def mrv_exports(self, case_id: str) -> list[dict[str, Any]]:
        self._one("mrv_cases", case_id)
        rows = self._many("mrv_exports", mrv_case_id=case_id)
        # Newest first, decided here rather than by whatever order the API returns.
        rows.sort(key=lambda x: (str(x.get("generated_at") or ""), str(x.get("id") or "")), reverse=True)
        return [self._export_view(x) for x in rows]

    def mrv_export(self, export_id: str) -> dict[str, Any]:
        # Không lọc theo case trước — mrv_exports không phải resource lồng duy nhất
        # (route GET /v1/mrv/exports/{id} độc lập); giống production_batch()/
        # emission_factor_set(), dựa vào RLS của chính bảng mrv_exports để chặn
        # truy cập chéo tổ chức, không tự suy luận quyền bằng code Python.
        return self._export_view(self._one("mrv_exports", export_id))

    # -- MRV export bundle ------------------------------------------------
    # Raw rows for the evidence package. `mrv_batches`/`activities` above are
    # shaped for the UI (names, no ids, no audit columns); an export needs the
    # opposite. These read through the same caller-bound client, so RLS remains
    # the boundary, and they batch with `IN` so adding a season to a case does
    # not add a round trip per season.

    def mrv_scope(self, case_id: str) -> list[dict[str, Any]]:
        """Batch -> crop season -> plot -> farm for every batch on the case.

        5 requests regardless of how many batches the case links, instead of the
        4-per-batch the UI-facing `mrv_batches` costs.
        """
        self._one("mrv_cases", case_id)
        links = self._many("mrv_case_batches", mrv_case_id=case_id)
        batch_ids = [str(x["production_batch_id"]) for x in links]
        if not batch_ids:
            return []
        batches = self._many_in("production_batches", "id", batch_ids)
        season_ids = [str(b["crop_season_id"]) for b in batches]
        seasons = self._many_in("crop_seasons", "id", season_ids)
        by_season = {str(s["id"]): s for s in seasons}
        plots = self._many_in("plots", "id", [str(s["plot_id"]) for s in seasons])
        by_plot = {str(p["id"]): p for p in plots}
        farms = self._many_in("farms", "id", [str(p["farm_id"]) for p in plots])
        by_farm = {str(f["id"]): f for f in farms}

        entries: list[dict[str, Any]] = []
        for batch in batches:
            season = by_season.get(str(batch["crop_season_id"])) or {}
            plot = by_plot.get(str(season.get("plot_id"))) or {}
            farm = by_farm.get(str(plot.get("farm_id"))) or {}
            entries.append({
                "production_batch_id": batch["id"], "batch_code": batch.get("batch_code"),
                "crop_season_id": season.get("id"), "season_code": season.get("season_code"),
                "season_status": season.get("status"),
                "started_on": season.get("planting_date"),
                "closed_on": season.get("actual_harvest_date"),
                "plot_id": plot.get("id"), "plot_code": plot.get("plot_code"),
                "plot_area_ha": plot.get("area_ha"),
                "farm_id": farm.get("id"), "farm_code": farm.get("farm_code"),
                "farm_name": farm.get("farm_name"),
            })
        return entries

    def export_activities(self, season_ids: list[str]) -> list[dict[str, Any]]:
        """Raw activity rows plus their detail row, carrying the audit columns.

        Soft-deleted rows are returned here and filtered by the manifest builder,
        which is where the include/exclude decision is documented -- this method
        stays a faithful read of the table.
        """
        if not season_ids:
            return []
        batches = self._many_in("production_batches", "crop_season_id", season_ids)
        season_by_batch = {str(b["id"]): str(b["crop_season_id"]) for b in batches}
        if not season_by_batch:
            return []
        rows = self._many_in("activities", "production_batch_id", list(season_by_batch))
        details = self._details_by_activity_id(rows)
        return [
            {**row, "crop_season_id": season_by_batch.get(str(row["production_batch_id"])),
             "detail": details.get(str(row["id"]), {})}
            for row in rows
        ]

    def emission_factor_provenance(
        self, factor_set_ids: list[str]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """The factor sets a calculation used, and their factors. 2 requests.

        Only published sets are visible to a caller (`ef_sets_select`), so an
        unpublished set simply yields no provenance and the manifest warns.
        """
        ids = sorted({str(x) for x in factor_set_ids if x})
        if not ids:
            return {}, {}
        sets, factors = self._concurrent(
            lambda: self._many_in("emission_factor_sets", "id", ids),
            lambda: self._many_in("emission_factors", "factor_set_id", ids),
        )
        by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for factor in factors:
            by_set[str(factor["factor_set_id"])].append(factor)
        return {str(s["id"]): s for s in sets}, dict(by_set)

    def mrv_case_row(self, case_id: str) -> dict[str, Any]:
        """The raw case row (the UI view drops created_at/updated_at)."""
        return self._one("mrv_cases", case_id)

    def mrv_evidence_rows(self, case_id: str) -> list[dict[str, Any]]:
        """Raw evidence rows. The UI view drops `uploaded_by`, which an audit
        package needs in order to say who supplied a file.
        """
        self._one("mrv_cases", case_id)
        return self._many("mrv_evidence", mrv_case_id=case_id)

    def mrv_case_scopes(self) -> list[dict[str, str]]:
        """(case id, organization id) for every MRV case the caller can read.

        The organization comes back too so the caller can apply a role rule on
        top of RLS visibility -- reading a case and being allowed to package it
        are different questions.
        """
        return [
            {"id": str(row["id"]), "organization_id": str(row["organization_id"])}
            for row in self._many("mrv_cases")
        ]

    def metrics_for_seasons(self, season_ids: list[str]) -> dict[str, dict[str, Any]]:
        """`metrics()` for many seasons without a request chain per season.

        Same computation as the single-season path -- it delegates to the same
        `_bulk_metric_totals` the organization/farm rollups use, so the export
        cannot drift from what the dashboards show.
        """
        if not season_ids:
            return {}
        totals = self._bulk_metric_totals(list(season_ids))
        return {
            sid: {k: v for k, v in totals[sid].items() if not k.startswith("_")}
            for sid in season_ids
        }
