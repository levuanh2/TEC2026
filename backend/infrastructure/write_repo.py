"""Transactional persistence for Farmer Web online activities.

The public API is crop-season scoped while the legacy relational model stores
an activity below a production batch.  This repository receives a batch that
was resolved from a caller-authorized crop season by the service layer; it
never accepts a farm, organization, actor, or role from the HTTP payload.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import pg_pool
from .config import Settings


class ActivityNotFoundError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


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

    def _view(self, cur: Any, activity_id: str, *, actor_id: str | None = None) -> dict[str, Any]:
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
            base_sql += " and a.recorded_by = %s"
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

    def get_for_actor(self, activity_id: str, actor_id: str) -> dict[str, Any]:
        with self._connection() as conn, conn.cursor() as cur:
            return self._view(cur, activity_id, actor_id=actor_id)

    def create(
        self, *, crop_season_id: str, production_batch_id: str, actor_id: str,
        idempotency_key: str, activity_type: str, occurred_at: datetime,
        note: str | None, data: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        table, columns = self._detail_spec(activity_type)
        with self._connection() as conn, conn.cursor() as cur:
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
                return existing, True

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
            return self._view(cur, activity_id, actor_id=actor_id), False

    def update(
        self, *, activity_id: str, actor_id: str, occurred_at: datetime | None,
        note: str | None, update_note: bool, data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self._connection() as conn, conn.cursor() as cur:
            existing = self._view(cur, activity_id, actor_id=actor_id)
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
            return self._view(cur, activity_id, actor_id=actor_id)

    def soft_delete(self, *, activity_id: str, actor_id: str) -> None:
        with self._connection() as conn, conn.cursor() as cur:
            self._view(cur, activity_id, actor_id=actor_id)
            cur.execute(
                """update public.activities set deleted_at=now(), updated_at=now(),
                   row_version=row_version+1 where id=%s and recorded_by=%s and deleted_at is null""",
                [activity_id, actor_id],
            )
            if cur.rowcount != 1:
                raise ActivityNotFoundError()
