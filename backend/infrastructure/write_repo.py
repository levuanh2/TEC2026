"""Transactional persistence for Farmer Web online activities.

The public API is crop-season scoped while the legacy relational model stores
an activity below a production batch.  This repository receives a batch that
was resolved from a caller-authorized crop season by the service layer; it
never accepts a farm, organization, actor, or role from the HTTP payload.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from . import pg_pool
from .config import Settings


class ActivityNotFoundError(Exception):
    pass


class ActivityWritePermissionError(ActivityNotFoundError):
    """The caller can read the target scope but may not write it (for example a
    farm member with `farm_role = viewer`). A subclass of `ActivityNotFoundError`
    so every caller keeps the normalized 404 and never reveals the difference."""


class IdempotencyConflictError(Exception):
    pass


class SeasonNotOpenError(Exception):
    """The batch's season is not `active` (or the batch is closed) at the moment
    of the write, checked under a row lock inside the write's transaction."""


#: `private.user_can_write_*` accept an owner/editor `farm_members` row even
#: after the person left the cooperative, and do not look at `farms.deleted_at`
#: (baseline RLS; changing it needs a migration). FastAPI writes add this rule:
#: an active cooperative manager, or an ACTIVE member of the farm's cooperative,
#: on a farm that is not deleted. Evaluated with the transaction-local claim set.
ACTIVE_FARM_MEMBERSHIP_SQL = """
    f.deleted_at is null and (
      private.user_is_org_manager(f.cooperative_id)
      or exists (
        select 1 from public.organization_memberships om
        where om.organization_id = f.cooperative_id and om.user_id = (select auth.uid())
          and (om.ended_at is null or om.ended_at > now())
      )
    )
"""


_DETAILS: dict[str, tuple[str, tuple[str, ...]]] = {
    "fertilizer": ("fertilizer_applications", ("fertilizer_name", "fertilizer_type", "amount_kg", "nitrogen_percent", "phosphorus_percent", "potassium_percent", "total_cost_vnd")),
    "irrigation": ("irrigation_events", ("method", "water_volume_m3", "duration_minutes", "water_level_cm", "pump_energy_kwh", "total_cost_vnd")),
    "harvest": ("harvest_events", ("yield_kg", "harvested_area_ha", "moisture_percent", "total_cost_vnd")),
    "seeding": ("seeding_events", ("variety_name", "seed_kg", "seeding_method", "cost_vnd")),
    "pesticide": ("pesticide_applications", ("product_name", "active_ingredient", "amount", "unit", "total_cost_vnd")),
    "straw_management": (
        "straw_management_events",
        ("method", "straw_mass_kg", "total_cost_vnd", "days_before_cultivation", "dry_matter_fraction", "returned_to_field"),
    ),
}


def _prepared(prepare: Callable[[Any], Any] | None, result: Any) -> Any:
    """Build the caller's success representation while the transaction is still
    open: if it raises, the `with` block rolls the write back instead of the
    route answering 500 for a row that was already committed."""
    return prepare(result) if prepare is not None else result


class PostgresActivityWriteRepository:
    """Backend-only psycopg repository; each method uses one DB transaction."""

    def __init__(self, settings: Settings, connect: Any | None = None):
        self._settings = settings
        self._connect = connect

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        # Pooled: a fresh hosted-Postgres connection costs ~700ms, which
        # dwarfed the statements themselves (see infrastructure/pg_pool).
        return pg_pool.connection(self._settings.require_db())

    @staticmethod
    def _detail_spec(activity_type: str) -> tuple[str, tuple[str, ...]]:
        try:
            return _DETAILS[activity_type]
        except KeyError as exc:
            raise ValueError("Unsupported activity type.") from exc

    def _view(
        self, cur: Any, activity_id: str, *, actor_id: str | None = None,
        allow_unattributed: bool = False,
    ) -> dict[str, Any]:
        base_sql = """
          select a.id::text, pb.crop_season_id::text, a.activity_type::text,
                 a.occurred_at, a.note, a.recorded_by::text as created_by,
                 a.created_at, a.updated_at
          from public.activities a
          join public.production_batches pb on pb.id = a.production_batch_id
          where a.id = %s and a.deleted_at is null
        """
        args: list[Any] = [activity_id]
        if actor_id is not None:
            # `allow_unattributed` mirrors the `activities_update` RLS WITH CHECK
            # (`recorded_by is null or recorded_by = auth.uid()`): a seeded or
            # imported record has no author, and any writer of its batch may
            # complete it. Batch write permission is still checked separately.
            base_sql += (
                " and (a.recorded_by = %s or a.recorded_by is null)" if allow_unattributed
                else " and a.recorded_by = %s"
            )
            args.append(actor_id)
        cur.execute(base_sql, args)
        row = cur.fetchone()
        if row is None:
            raise ActivityNotFoundError()
        table, columns = self._detail_spec(row["activity_type"])
        cur.execute(
            f"select {', '.join(columns)} from public.{table} where activity_id = %s",  # noqa: S608 -- table/columns are static above
            [activity_id],
        )
        detail = cur.fetchone()
        if detail is None:
            raise ActivityNotFoundError()
        return {**row, "data": dict(detail)}

    @staticmethod
    def _assert_can_write_batch(cur: Any, *, production_batch_id: str, actor_id: str) -> None:
        """Ask the RLS write rule itself, inside the write's own transaction.

        This connection bypasses RLS, and the service only establishes *read*
        scope through the caller's JWT — read scope is wider than write scope
        (a farm `viewer` can read). Rather than re-deriving `owner/editor or
        cooperative manager` in Python, evaluate `private.user_can_write_batch`,
        the helper the `activities` INSERT/UPDATE policies and the soft-delete
        RPC already use, with `auth.uid()` = the JWT-verified actor. The claim is
        transaction-local and cleared again before any row is written, so audit
        triggers see the same session as before.
        """
        cur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            [json.dumps({"sub": str(actor_id), "role": "authenticated"})],
        )
        cur.execute(
            f"""select private.user_can_write_batch(pb.id) and {ACTIVE_FARM_MEMBERSHIP_SQL} as allowed,
                       cs.status::text as season_status, cs.deleted_at is null as season_live,
                       pb.status::text as batch_status
                from public.production_batches pb
                join public.crop_seasons cs on cs.id = pb.crop_season_id
                join public.plots p on p.id = cs.plot_id
                join public.farms f on f.id = p.farm_id
                where pb.id = %s::uuid
                for share of cs""",  # noqa: S608 -- static SQL fragment
            [production_batch_id],
        )
        row = cur.fetchone()
        cur.execute("select set_config('request.jwt.claims', '', true)")
        if row is None or not row["allowed"]:
            raise ActivityWritePermissionError()
        # Re-checked here, under a share lock on the season row: the service's
        # earlier status read went through PostgREST, outside this transaction,
        # so a season closed in between must still refuse the write. A
        # concurrent close waits for this transaction, or this one sees it.
        if row["season_status"] != "active" or not row["season_live"] or row["batch_status"] in ("closed", "cancelled"):
            raise SeasonNotOpenError()

    def _assert_can_write_activity(self, cur: Any, *, activity_id: str, actor_id: str) -> None:
        cur.execute(
            "select production_batch_id::text as production_batch_id from public.activities where id = %s",
            [activity_id],
        )
        row = cur.fetchone()
        if row is None:
            raise ActivityNotFoundError()
        self._assert_can_write_batch(cur, production_batch_id=row["production_batch_id"], actor_id=actor_id)

    def get_for_actor(
        self, activity_id: str, actor_id: str, *, allow_unattributed: bool = False,
    ) -> dict[str, Any]:
        with self._connection() as conn, conn.cursor() as cur:
            return self._view(cur, activity_id, actor_id=actor_id, allow_unattributed=allow_unattributed)

    def create(
        self, *, crop_season_id: str, production_batch_id: str, actor_id: str,
        idempotency_key: str, activity_type: str, occurred_at: datetime,
        note: str | None, data: dict[str, Any],
        prepare: Callable[[tuple[dict[str, Any], bool]], Any] | None = None,
    ) -> Any:
        """Returns `(row, replay)`, or `prepare((row, replay))` computed before commit."""
        table, columns = self._detail_spec(activity_type)
        with self._connection() as conn, conn.cursor() as cur:
            # Before the idempotent-replay lookup too: a read-only member gets the
            # same answer whether or not the key was used before.
            self._assert_can_write_batch(cur, production_batch_id=production_batch_id, actor_id=actor_id)
            cur.execute(
                """select id::text, deleted_at is not null as is_deleted from public.activities
                   where recorded_by=%s and web_idempotency_key=%s""",
                [actor_id, idempotency_key],
            )
            replay = cur.fetchone()
            if replay is not None:
                # The unique key is intentionally retained after a soft delete:
                # a retry must never silently recreate a logically deleted event.
                if replay["is_deleted"]:
                    raise IdempotencyConflictError()
                existing = self._view(cur, replay["id"], actor_id=actor_id)
                requested = {"crop_season_id": crop_season_id, "activity_type": activity_type, "occurred_at": occurred_at, "note": note, "data": data}
                comparable = {key: existing[key] for key in requested}
                if comparable != requested:
                    raise IdempotencyConflictError()
                return _prepared(prepare, (existing, True))

            cur.execute(
                """insert into public.activities
                   (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, web_idempotency_key, note)
                   values (%s, %s, %s, now(), 'web', %s, %s, %s) returning id::text""",
                [production_batch_id, activity_type, occurred_at, actor_id, idempotency_key, note],
            )
            activity_id = cur.fetchone()["id"]
            cur.execute(
                f"insert into public.{table} (activity_id, {', '.join(columns)}) values (%s, {', '.join(['%s'] * len(columns))})",  # noqa: S608 -- static specs
                [activity_id, *[data.get(column) for column in columns]],
            )
            return _prepared(prepare, (self._view(cur, activity_id, actor_id=actor_id), False))

    def update(
        self, *, activity_id: str, actor_id: str, occurred_at: datetime | None,
        note: str | None, update_note: bool, data: dict[str, Any] | None,
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        with self._connection() as conn, conn.cursor() as cur:
            existing = self._view(cur, activity_id, actor_id=actor_id, allow_unattributed=True)
            self._assert_can_write_activity(cur, activity_id=activity_id, actor_id=actor_id)
            if occurred_at is not None or update_note:
                cur.execute(
                    """update public.activities set occurred_at=coalesce(%s, occurred_at),
                       note=case when %s then %s else note end,
                       updated_at=now(), row_version=row_version+1 where id=%s""",
                    [occurred_at, update_note, note, activity_id],
                )
            if data is not None:
                table, columns = self._detail_spec(existing["activity_type"])
                assignments = ", ".join(f"{column}=%s" for column in columns)
                cur.execute(
                    f"update public.{table} set {assignments}, updated_at=now() where activity_id=%s",  # noqa: S608 -- static specs
                    [*[data.get(column) for column in columns], activity_id],
                )
                if cur.rowcount != 1:
                    # No detail row means the write did not land; never report
                    # success for it (the whole transaction rolls back).
                    raise ActivityNotFoundError()
            return _prepared(prepare, self._view(cur, activity_id, actor_id=actor_id, allow_unattributed=True))

    def update_crop_season_methodology(
        self, *, crop_season_id: str, actor_id: str, fields: dict[str, Any],
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        """Set the IPCC methodology inputs the Carbon engine reads off the season.

        `fields` holds only the keys the caller actually sent, so an omitted key
        keeps its stored value while an explicit None clears it. Authorization is
        `private.user_can_write_crop` — the same helper behind the `crop_seasons`
        UPDATE policy and behind B4's persist gate, evaluated here rather than
        re-derived in Python, so a farm `viewer` or a read-only grant cannot write.
        """
        allowed = ("ipcc_water_regime", "pre_season_water_regime", "cultivation_days")
        unknown = sorted(set(fields) - set(allowed))
        if unknown:
            raise ValueError(f"unsupported crop season methodology field(s): {', '.join(unknown)}")
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select id::text as id from public.crop_seasons where id=%s and deleted_at is null",
                [crop_season_id],
            )
            if cur.fetchone() is None:
                raise ActivityNotFoundError()
            self._assert_can_write_crop(cur, crop_season_id=crop_season_id, actor_id=actor_id)
            if fields:
                # The two regime columns are enums; cast so psycopg sends a value
                # Postgres will reject if it is not a member, instead of text.
                casts = {
                    "ipcc_water_regime": "%s::public.ipcc_water_regime",
                    "pre_season_water_regime": "%s::public.ipcc_pre_season_regime",
                    "cultivation_days": "%s",
                }
                assignments = ", ".join(f"{column}={casts[column]}" for column in fields)
                cur.execute(
                    f"""update public.crop_seasons set {assignments}, updated_at=now()
                        where id=%s""",  # noqa: S608 -- column names come from `allowed`
                    [*[fields[column] for column in fields], crop_season_id],
                )
            cur.execute(
                """select id::text as id, plot_id::text as plot_id, season_code, crop_type,
                          variety_name, planting_date::text as planting_date,
                          expected_harvest_date::text as expected_harvest_date,
                          actual_harvest_date::text as actual_harvest_date, status::text as status,
                          ipcc_water_regime::text as ipcc_water_regime,
                          pre_season_water_regime::text as pre_season_water_regime,
                          cultivation_days
                   from public.crop_seasons where id=%s""",
                [crop_season_id],
            )
            return _prepared(prepare, dict(cur.fetchone()))

    @staticmethod
    def _assert_can_write_crop(cur: Any, *, crop_season_id: str, actor_id: str) -> None:
        """Same transaction-local JWT trick as `_assert_can_write_batch`, one level up."""
        cur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            [json.dumps({"sub": str(actor_id), "role": "authenticated"})],
        )
        cur.execute(
            f"""select private.user_can_write_crop(cs.id) and {ACTIVE_FARM_MEMBERSHIP_SQL} as allowed
                from public.crop_seasons cs
                join public.plots p on p.id = cs.plot_id
                join public.farms f on f.id = p.farm_id
                where cs.id = %s::uuid""",  # noqa: S608 -- static SQL fragment
            [crop_season_id],
        )
        row = cur.fetchone()
        allowed = bool(row and row["allowed"])
        cur.execute("select set_config('request.jwt.claims', '', true)")
        if not allowed:
            raise ActivityWritePermissionError()

    def soft_delete(self, *, activity_id: str, actor_id: str) -> None:
        with self._connection() as conn, conn.cursor() as cur:
            self._view(cur, activity_id, actor_id=actor_id)
            self._assert_can_write_activity(cur, activity_id=activity_id, actor_id=actor_id)
            cur.execute(
                """update public.activities set deleted_at=now(), updated_at=now(),
                   row_version=row_version+1 where id=%s and recorded_by=%s and deleted_at is null""",
                [activity_id, actor_id],
            )
            if cur.rowcount != 1:
                raise ActivityNotFoundError()
