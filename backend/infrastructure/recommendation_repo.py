"""Transactional persistence for M05 season recommendations.

Same trust model as `write_repo.py`: read scope is established by the caller
(via `SupabaseReadRepository`, RLS); WRITE authority is decided here, inside
each write's transaction, by `private.user_can_write_crop` plus an active farmer
membership in the season's HTX for the JWT-verified actor (`crop_write_authz`)
-- an HTX manager, a farm viewer, a former member or a data-grant
reader can read a season but writes nothing. The service-role connection
bypasses RLS, so this check is the only one. It never accepts a
farm/organization/actor from an HTTP payload.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import pg_pool, profiling
from .config import Settings
from .crop_write_authz import assert_can_write_crop


class RecommendationNotFoundError(Exception):
    pass


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    """psycopg returns `uuid` columns as Python UUID objects; the response
    schema (and every other read_repo/write_repo row shape in this backend)
    expects plain strings. Found via the real M05 E2E: FastAPI's response
    serialization rejected a raw UUID where `RecommendationResponse.id: str`
    was declared, 500ing the whole request.
    """
    row["id"] = str(row["id"])
    row["crop_season_id"] = str(row["crop_season_id"])
    return row


_UPSERT_COLUMNS = (
    "rule_version", "engine_version", "type", "title", "reason", "compared_to",
    "co2e_total_kg_before", "co2e_total_kg_after", "co2e_total_kg_delta", "co2e_percent_delta",
    "impact_status", "impact_unavailable_reason", "evidence", "input_hash",
)


class PostgresRecommendationRepository:
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

    def assert_can_write(self, *, crop_season_id: str, actor_id: str) -> None:
        """Early refusal, before the generation's Carbon work; each write
        re-checks inside its own transaction."""
        with self._connection() as conn, conn.cursor() as cur:
            assert_can_write_crop(cur, crop_season_id=crop_season_id, actor_id=actor_id)

    def save_generated(
        self, *, crop_season_id: str, recs: list[Any], actor_id: str,
        prepare: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> Any:
        """Persist one whole generation run in a single transaction.

        Same rows as upserting each rule then pruning, with two differences
        that both matter: it opens ONE connection instead of one per rule
        (a fresh hosted-Postgres connection measured ~740ms, which made
        generation's cost scale with the number of rules that fired), and the
        run is atomic — a concurrent reader sees the previous run or this one,
        never a half-applied mix of the two.
        """
        with profiling.observe("recommendation save_generated"), self._connection() as conn, conn.cursor() as cur:
            assert_can_write_crop(cur, crop_season_id=crop_season_id, actor_id=actor_id)
            rows = [self._upsert(cur, crop_season_id=crop_season_id, rec=rec) for rec in recs]
            self._prune(cur, crop_season_id=crop_season_id, keep_rule_codes=[rec.rule_code for rec in recs])
            # Built before the `with` commits: a representation that cannot be
            # produced rolls the run back rather than 500ing a saved one.
            return prepare(rows) if prepare is not None else rows

    @staticmethod
    def _upsert(cur: Any, *, crop_season_id: str, rec: Any) -> dict[str, Any]:
        cur.execute(
            f"""
            insert into public.season_recommendations
              (crop_season_id, rule_code, {', '.join(_UPSERT_COLUMNS)})
            values (%s, %s, {', '.join(['%s'] * len(_UPSERT_COLUMNS))})
            on conflict (crop_season_id, rule_code) do update set
              {', '.join(f'{c} = excluded.{c}' for c in _UPSERT_COLUMNS)},
              generated_at = now(), updated_at = now()
            returning *
            """,  # noqa: S608 -- _UPSERT_COLUMNS is a static tuple above, not request input
            [
                crop_season_id, rec.rule_code, rec.rule_version, rec.engine_version, rec.type,
                rec.title, rec.reason, rec.compared_to, rec.co2e_total_kg_before, rec.co2e_total_kg_after,
                rec.co2e_total_kg_delta, rec.co2e_percent_delta, rec.impact_status,
                rec.impact_unavailable_reason, json.dumps(rec.evidence), rec.input_hash,
            ],
        )
        return _normalize(cur.fetchone())

    @staticmethod
    def _prune(cur: Any, *, crop_season_id: str, keep_rule_codes: list[str]) -> None:
        cur.execute(
            """delete from public.season_recommendations
               where crop_season_id = %s and status = 'generated'
                 and not (rule_code = any(%s))""",
            [crop_season_id, keep_rule_codes],
        )

    def get(self, recommendation_id: str) -> dict[str, Any]:
        with profiling.observe("recommendation get"), self._connection() as conn, conn.cursor() as cur:
            cur.execute("select * from public.season_recommendations where id = %s", [recommendation_id])
            row = cur.fetchone()
            if row is None:
                raise RecommendationNotFoundError()
            return _normalize(row)

    def set_status(
        self, recommendation_id: str, status: str, *, actor_id: str,
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        column = "accepted_at" if status == "accepted" else "dismissed_at"
        with profiling.observe("recommendation set_status"), self._connection() as conn, conn.cursor() as cur:
            # Authority on the season the row belongs to, read and locked in
            # this transaction -- never a season id supplied by the caller.
            cur.execute("select crop_season_id::text as crop_season_id from public.season_recommendations"
                        " where id = %s for update", [recommendation_id])
            owner = cur.fetchone()
            if owner is None:
                raise RecommendationNotFoundError()
            assert_can_write_crop(cur, crop_season_id=owner["crop_season_id"], actor_id=actor_id)
            cur.execute(
                f"""update public.season_recommendations
                    set status = %s, {column} = now(), updated_at = now()
                    where id = %s returning *""",  # noqa: S608 -- column is one of two static literals above
                [status, recommendation_id],
            )
            row = cur.fetchone()
            if row is None:
                raise RecommendationNotFoundError()
            row = _normalize(row)
            return prepare(row) if prepare is not None else row
