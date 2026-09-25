"""Transactional crop-season creation for the Web (Farmer and Management).

A crop season is only useful once it can hold activities, and an activity hangs
off a production batch (`activities.production_batch_id` is NOT NULL). So a
season is created together with its default batch -- the same
`batch_code = 'default'` row the Flutter sync creates through
`ensureDefaultBatch` -- in ONE transaction: either both rows exist afterwards or
neither does. No client ever sees a season that cannot accept activities, and no
client has to make a second request to finish creating one.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import pg_pool
from .config import Settings
from .write_repo import ACTIVE_FARM_MEMBERSHIP_SQL

#: The batch every season starts with. Same code the Flutter sync upserts
#: (`app/lib/services/sync_gateway.dart`), so a season created on the Web and
#: later opened on the phone resolves to the same batch instead of a second one.
DEFAULT_BATCH_CODE = "default"

#: "Bắt đầu vụ" starts cultivation: the season is created `active`, the only
#: state `ActivityWriteService._write_batch` accepts journal writes for.
STARTED_STATUS = "active"


class SeasonScopeError(Exception):
    """The plot does not exist, or the caller may not write to its farm.

    One error for both, so the API answers the same 404 either way and a plot id
    in another cooperative cannot be told apart from one that does not exist."""


class ActiveSeasonExistsError(Exception):
    """The plot already has a season under cultivation."""


class SeasonCodeTakenError(Exception):
    """`unique (plot_id, season_code)` -- it also covers soft-deleted seasons."""


_SEASON_COLUMNS = """
    id::text as id, plot_id::text as plot_id, season_code, crop_type, variety_name,
    planting_date::text as planting_date, expected_harvest_date::text as expected_harvest_date,
    actual_harvest_date::text as actual_harvest_date, status::text as status,
    ipcc_water_regime::text as ipcc_water_regime,
    pre_season_water_regime::text as pre_season_water_regime, cultivation_days
"""


def _prepared(prepare: Callable[[Any], Any] | None, result: Any) -> Any:
    """Build the response while the transaction is open: if that raises, both
    rows roll back instead of the route answering 500 for a committed season."""
    return prepare(result) if prepare is not None else result


class PostgresSeasonRepository:
    """Backend-only psycopg repository; `create` is one DB transaction."""

    # Class attribute so a test can make exactly this statement fail and prove
    # the season insert before it rolls back with it.
    _INSERT_BATCH_SQL = """
        insert into public.production_batches (crop_season_id, batch_code)
        values (%s, %s) returning id::text as id
    """

    def __init__(self, settings: Settings | None, connect: Any | None = None):
        self._settings = settings
        self._connect = connect

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        return pg_pool.connection(self._settings.require_db())  # type: ignore[union-attr]

    @staticmethod
    def _assert_can_write_farm(cur: Any, *, farm_id: str, actor_id: str) -> None:
        """Ask the RLS rule itself, `private.user_can_write_farm` -- the helper
        behind the `crop_seasons` INSERT policy: farm owner/editor, or an active
        cooperative manager of the farm's cooperative -- plus
        `ACTIVE_FARM_MEMBERSHIP_SQL`: a farm role outlives a membership that
        has ended, and a deleted farm takes no new seasons. The JWT claim is
        transaction-local and cleared before any row is written, exactly as the
        activity repository does."""
        cur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            [json.dumps({"sub": str(actor_id), "role": "authenticated"})],
        )
        cur.execute(
            f"""select private.user_can_write_farm(f.id) and {ACTIVE_FARM_MEMBERSHIP_SQL} as allowed
                from public.farms f where f.id = %s::uuid""",  # noqa: S608 -- static SQL fragment
            [farm_id],
        )
        row = cur.fetchone()
        allowed = bool(row and row["allowed"])
        cur.execute("select set_config('request.jwt.claims', '', true)")
        if not allowed:
            raise SeasonScopeError()

    def create(
        self, *, plot_id: str, actor_id: str, season_code: str, variety_name: str | None,
        planting_date: Any, expected_harvest_date: Any,
        prepare: Callable[[tuple[dict[str, Any], bool]], Any] | None = None,
    ) -> Any:
        """Returns `prepare((season_row_with_batch_id, replay))`.

        `replay` is True when this exact season already exists on the plot --
        a double submit or a retried request gets the season it created instead
        of a conflict.
        """
        with self._connection() as conn, conn.cursor() as cur:
            # FOR UPDATE: two concurrent creates on one plot queue up here, so the
            # "one active season per plot" check below cannot race.
            cur.execute(
                "select id::text as id, farm_id::text as farm_id from public.plots "
                "where id = %s and deleted_at is null for update",
                [plot_id],
            )
            plot = cur.fetchone()
            if plot is None:
                raise SeasonScopeError()
            self._assert_can_write_farm(cur, farm_id=plot["farm_id"], actor_id=actor_id)

            cur.execute(
                f"select {_SEASON_COLUMNS}, deleted_at is not null as is_deleted "  # noqa: S608 -- static columns
                "from public.crop_seasons where plot_id = %s and season_code = %s",
                [plot_id, season_code],
            )
            same_code = cur.fetchone()
            if same_code is not None:
                requested = {
                    "variety_name": variety_name,
                    "planting_date": None if planting_date is None else str(planting_date),
                    "expected_harvest_date": None if expected_harvest_date is None else str(expected_harvest_date),
                    "status": STARTED_STATUS,
                }
                if not same_code["is_deleted"] and all(same_code[k] == v for k, v in requested.items()):
                    season = self._with_batch(cur, {k: v for k, v in same_code.items() if k != "is_deleted"})
                    # Never hand back a season that cannot take activities.
                    if season["default_production_batch_id"] is not None:
                        return _prepared(prepare, (season, True))
                raise SeasonCodeTakenError()

            cur.execute(
                "select 1 from public.crop_seasons where plot_id = %s and deleted_at is null and status = %s::public.crop_status",
                [plot_id, STARTED_STATUS],
            )
            if cur.fetchone() is not None:
                raise ActiveSeasonExistsError()

            cur.execute(
                f"""insert into public.crop_seasons
                      (plot_id, season_code, variety_name, planting_date, expected_harvest_date, status)
                    values (%s, %s, %s, %s, %s, %s::public.crop_status)
                    returning {_SEASON_COLUMNS}""",  # noqa: S608 -- static columns
                [plot_id, season_code, variety_name, planting_date, expected_harvest_date, STARTED_STATUS],
            )
            season = dict(cur.fetchone())
            cur.execute(self._INSERT_BATCH_SQL, [season["id"], DEFAULT_BATCH_CODE])
            season["default_production_batch_id"] = cur.fetchone()["id"]
            return _prepared(prepare, (season, False))

    @staticmethod
    def _with_batch(cur: Any, season: dict[str, Any]) -> dict[str, Any]:
        cur.execute(
            "select id::text as id from public.production_batches where crop_season_id = %s "
            "and batch_code = %s and deleted_at is null",
            [season["id"], DEFAULT_BATCH_CODE],
        )
        row = cur.fetchone()
        return {**season, "default_production_batch_id": row["id"] if row else None}
