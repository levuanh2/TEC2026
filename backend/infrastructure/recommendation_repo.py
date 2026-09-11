"""Transactional persistence for M05 season recommendations.

Same trust model as `write_repo.py`: authorization is established by the
caller (via `SupabaseReadRepository`, RLS) *before* reaching this repository;
this class only performs the actual write/lookup using a backend-only
service-role Postgres connection. It never accepts a farm/organization/actor
from an HTTP payload.
"""
from __future__ import annotations

import json
from typing import Any

from .config import Settings


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
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self._settings.require_db(), row_factory=dict_row)

    def upsert(self, *, crop_season_id: str, rec: Any) -> dict[str, Any]:
        """Insert or refresh one rule's row for a season.

        A farmer's already-made decision (accepted/dismissed) is preserved
        across regeneration — only the evidence/impact/title/reason fields
        and `generated_at` are refreshed; `status`/`accepted_at`/`dismissed_at`
        are untouched.
        """
        with self._connection() as conn, conn.cursor() as cur:
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

    def prune_missing(self, *, crop_season_id: str, keep_rule_codes: list[str]) -> None:
        """Remove a still-`generated` (never accepted/dismissed) row whose rule
        no longer applies this run — keeps the list honest as data changes.
        A farmer's own accept/dismiss decision is never pruned.
        """
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """delete from public.season_recommendations
                   where crop_season_id = %s and status = 'generated'
                     and not (rule_code = any(%s))""",
                [crop_season_id, keep_rule_codes],
            )

    def get(self, recommendation_id: str) -> dict[str, Any]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("select * from public.season_recommendations where id = %s", [recommendation_id])
            row = cur.fetchone()
            if row is None:
                raise RecommendationNotFoundError()
            return _normalize(row)

    def set_status(self, recommendation_id: str, status: str) -> dict[str, Any]:
        column = "accepted_at" if status == "accepted" else "dismissed_at"
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""update public.season_recommendations
                    set status = %s, {column} = now(), updated_at = now()
                    where id = %s returning *""",  # noqa: S608 -- column is one of two static literals above
                [status, recommendation_id],
            )
            row = cur.fetchone()
            if row is None:
                raise RecommendationNotFoundError()
            return _normalize(row)
