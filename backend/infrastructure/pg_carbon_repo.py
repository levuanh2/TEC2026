"""Carbon repository on the backend's pooled Postgres connection.

Same contract, same rows as `SupabaseCarbonRepository`; only the transport
changes. Round 5.1 measured one `POST /v1/carbon/calculate` against hosted
Supabase: pure engine work < 1 ms, but 13 PostgREST round trips at 250–300 ms
each (up to 2 s under load), four of them strictly sequential reads and two
writes. A pooled connection costs ~110 ms per round trip, and psycopg's
pipeline mode sends every independent statement of a stage in one trip.

Equivalence with the PostgREST repository is deliberate and tested
(`tests/test_round51_pg_carbon_repo.py`):

* Every read issues the same single-table filter PostgREST would
  (`select * from t where col = $1`), and rows are converted by Postgres itself
  (`to_jsonb`) and parsed as JSON, exactly like a PostgREST response. Row ORDER
  matters: the fertilizer/straw/fuel lists are hashed into `input_hash` in read
  order, so the activity query is not rewritten into a join.
* The insert goes through `jsonb_populate_record` over only the columns the
  caller supplied, like PostgREST's JSON body: same text-to-type conversion,
  column defaults for everything else.

What is new is atomicity: the calculation and its breakdown rows are written
in ONE transaction. A failure at any step rolls both back, so a `succeeded`
calculation without its breakdown can no longer exist (the PostgREST path had
to delete it best-effort). Re-sending the same calculation still returns the
existing id through the season/scenario/factor-set/input-hash unique index.
"""
from __future__ import annotations

import contextlib
import contextvars
import uuid
from typing import Any, Callable

from carbon import SCENARIO_TO_DB

from . import pg_pool, profiling
from .config import Settings
from .mapping import RawCropBundle
from .repository import CropNotFoundError, FactorSetNotFoundError
from .supabase_repo import DETAIL_TABLES

try:
    from psycopg.types.json import Jsonb
except Exception:  # noqa: BLE001 - only the real repository needs psycopg
    Jsonb = None  # type: ignore[assignment]


def _rows(cur: Any) -> list[dict[str, Any]]:
    if cur.description is None:  # a write without RETURNING
        return []
    return [row["r"] for row in cur.fetchall()]


class PostgresCarbonRepository:
    def __init__(self, settings: Settings | None, *, connect: Callable[[], Any] | None = None) -> None:
        self._settings = settings
        self._connect = connect
        self._factor_set_ids: dict[str, str] = {}
        self._factor_ids: dict[str, dict[str, str]] = {}
        self._factor_set_versions: dict[str, str | None] = {}
        self._session_conn: contextvars.ContextVar[Any] = contextvars.ContextVar(
            f"carbon_pg_session_{id(self)}", default=None,
        )

    def _connection(self):
        bound = self._session_conn.get()
        if bound is not None:
            return contextlib.nullcontext(bound)
        if self._connect is not None:
            return self._connect()
        return pg_pool.connection(self._settings.require_db())  # type: ignore[union-attr]

    @contextlib.contextmanager
    def session(self):
        """One connection for every call made inside the block.

        A calculation reads its bundle and then saves: without this, each call
        checks a connection out of the pool, and each checkout is a liveness
        round trip. On the pool this is `pg_pool.bound`, so the route's write
        check shares the same connection too. Every stage still commits (or
        rolls back) its own transaction.
        """
        if self._connect is None:
            with pg_pool.bound(self._settings.require_db()):  # type: ignore[union-attr]
                yield
            return
        if self._session_conn.get() is not None:
            yield
            return
        with self._connection() as conn:
            token = self._session_conn.set(conn)
            try:
                yield
            finally:
                self._session_conn.reset(token)

    @staticmethod
    def _stage(
        conn: Any, label: str, statements: list[tuple[str, list[Any]]], *, last: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Run independent statements in one round trip; one result list each.

        psycopg otherwise spends a round trip on the implicit BEGIN and another
        on the COMMIT when the pooled connection is returned; in a pipeline both
        travel with the statements (`last=True` queues the COMMIT). A connection
        without `pipeline` (a test savepoint) runs them one by one and leaves
        the transaction to its owner.
        """
        pipelined = hasattr(conn, "pipeline")
        cursors = [conn.cursor() for _ in statements]
        with profiling.observe(label):
            with conn.pipeline() if pipelined else contextlib.nullcontext():
                for cur, (sql, params) in zip(cursors, statements):
                    cur.execute(sql, params)
                if last and pipelined:
                    conn.commit()
            results = [_rows(cur) for cur in cursors]
        for cur in cursors:
            cur.close()
        return results

    # -- reads --------------------------------------------------------------

    def get_crop_bundle(self, crop_season_id: str) -> RawCropBundle:
        outcome = self.get_crop_bundles([crop_season_id])[crop_season_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get_crop_bundles(self, crop_season_ids: list[str]) -> dict[str, RawCropBundle | CropNotFoundError]:
        """Bundles for many seasons in ONE round trip, whatever their number.

        Per season: the four row reads PostgREST issued (`select * from t where
        col = $1`), one activities read, and one read per detail table, all in a
        single pipeline. Activity ORDER matters (fertilizer/straw/fuel lists are
        hashed in read order), and PostgREST read them one batch at a time:
        `activities` has no non-partial index on `production_batch_id`, so each of
        those reads was a sequential scan, i.e. `ctid` order, and batches came in
        the order `production_batches where crop_season_id = $1` scans them. The
        activities read here states that order explicitly, `(batch scan
        position, ctid)`, instead of relying on a plan. A season that does not
        exist is a `CropNotFoundError` in its own slot, never a failure of the rest.
        """
        out: dict[str, RawCropBundle | CropNotFoundError] = {}
        ids: list[str] = []
        for season in dict.fromkeys(crop_season_ids):
            try:
                uuid.UUID(str(season))
                ids.append(season)
            except ValueError:
                out[season] = CropNotFoundError(f"Không tìm thấy vụ canh tác '{season}'.")
        if not ids:
            return out

        detail_tables = list(DETAIL_TABLES.items())
        per_season = 5 + len(detail_tables)
        statements: list[tuple[str, list[Any]]] = []
        for season in ids:
            statements += [
                ("select to_jsonb(t) as r from public.crop_seasons t where t.id = %s", [season]),
                ("select to_jsonb(t) as r from public.plots t"
                 " where t.id = (select c.plot_id from public.crop_seasons c where c.id = %s)", [season]),
                ("select to_jsonb(t) as r from public.production_batches t where t.crop_season_id = %s", [season]),
                ("select to_jsonb(t) as r from public.farms t where t.id = ("
                 " select p.farm_id from public.plots p join public.crop_seasons c on c.plot_id = p.id"
                 " where c.id = %s)", [season]),
                ("select to_jsonb(a) as r from public.activities a join ("
                 " select x.id, x.deleted_at, row_number() over () as pos"
                 " from (select t.id, t.deleted_at from public.production_batches t where t.crop_season_id = %s) x"
                 ") b on b.id = a.production_batch_id where b.deleted_at is null order by b.pos, a.ctid", [season]),
                *[(f"select to_jsonb(d) as r from public.{table} d where d.activity_id in ("
                   " select a.id from public.activities a join public.production_batches b"
                   " on b.id = a.production_batch_id where b.crop_season_id = %s and b.deleted_at is null"
                   " and a.deleted_at is null and a.activity_type = %s::public.activity_type)",
                   [season, activity_type]) for activity_type, table in detail_tables],
            ]
        with self._connection() as conn:
            results = self._stage(conn, "carbon pg season bundle", statements, last=True)

        for n, season in enumerate(ids):
            crops, plots, batches, farms, rows, *details = results[per_season * n: per_season * (n + 1)]
            crop = crops[0] if crops else None
            if crop is None or crop.get("deleted_at") is not None:
                out[season] = CropNotFoundError(f"Không tìm thấy vụ canh tác '{season}'.")
                continue
            plot = plots[0] if plots else {}
            farm = (farms[0] if farms else None) if plot.get("farm_id") else None
            detail_by_activity = {row["activity_id"]: row for table_rows in details for row in table_rows}
            activities = [a for a in rows if a.get("deleted_at") is None]
            for activity in activities:
                activity["detail"] = (
                    detail_by_activity.get(activity["id"], {}) if DETAIL_TABLES.get(activity["activity_type"]) else {}
                )
            out[season] = RawCropBundle(
                crop_season=crop, plot=plot, farm=farm, production_batches=batches, activities=activities,
            )
        return out

    def latest_calculation(self, crop_season_id: str, scenario: str | None = None) -> dict[str, Any] | None:
        return self.latest_calculations([crop_season_id], scenario).get(crop_season_id)

    def latest_calculations(
        self, crop_season_ids: list[str], scenario: str | None = None,
    ) -> dict[str, dict[str, Any] | None]:
        """Each season's latest succeeded calculation (of `scenario`), one round trip."""
        out: dict[str, dict[str, Any] | None] = {}
        ids: list[str] = []
        for season in dict.fromkeys(crop_season_ids):
            try:
                uuid.UUID(str(season))
                ids.append(season)
            except ValueError:
                out[season] = None
        if not ids:
            return out
        where = "t.crop_season_id = %s and t.status = 'succeeded'"
        extra: list[Any] = []
        if scenario:
            where += " and t.scenario = %s::public.carbon_scenario"
            extra.append(SCENARIO_TO_DB.get(scenario, scenario))
        sql = (
            f"with c as (select t.* from public.carbon_calculations t where {where}"
            " order by t.calculated_at desc limit 1)"
            " select to_jsonb(c) || jsonb_build_object('__breakdown', coalesce((select jsonb_agg(to_jsonb(b))"
            " from public.carbon_breakdowns b where b.calculation_id = c.id), '[]'::jsonb)) as r from c"
        )
        with self._connection() as conn:
            results = self._stage(conn, "carbon pg latest calculation",
                                  [(sql, [season, *extra]) for season in ids], last=True)
        for season, rows in zip(ids, results):
            if not rows:
                out[season] = None
                continue
            row = rows[0]
            breakdown = row.pop("__breakdown")
            out[season] = {**row, "breakdown": breakdown}
        return out

    # -- factor sets (published sets are immutable: cached per process) -------

    def resolve_factor_set_id(self, version_code: str) -> str:
        if version_code not in self._factor_set_ids:
            with self._connection() as conn, conn.cursor() as cur:
                with profiling.observe("carbon pg factor set"):
                    cur.execute(
                        "select id::text as id from public.emission_factor_sets"
                        " where version_code = %s and status = 'published' limit 1", [version_code],
                    )
                    row = cur.fetchone()
            if row is None:
                raise FactorSetNotFoundError(
                    f"Chưa có emission_factor_set nào ở trạng thái published với version_code "
                    f"'{version_code}'. YAML là nguồn sự thật cho GIÁ TRỊ hệ số; bảng Supabase là "
                    f"bản sao có kiểm soát để bản tính liên kết được factor_set_id. "
                    f"Import bộ hệ số trước — KHÔNG tự tạo bộ rỗng."
                )
            self._factor_set_ids[version_code] = row["id"]
        return self._factor_set_ids[version_code]

    def factor_ids_by_code(self, factor_set_id: str) -> dict[str, str]:
        if factor_set_id not in self._factor_ids:
            with self._connection() as conn, conn.cursor() as cur:
                with profiling.observe("carbon pg factor ids"):
                    cur.execute(
                        "select factor_code, id::text as id from public.emission_factors where factor_set_id = %s",
                        [factor_set_id],
                    )
                    self._factor_ids[factor_set_id] = {r["factor_code"]: r["id"] for r in cur.fetchall()}
        return dict(self._factor_ids[factor_set_id])

    def factor_set_version(self, factor_set_id: str) -> str | None:
        if factor_set_id not in self._factor_set_versions:
            with self._connection() as conn, conn.cursor() as cur:
                with profiling.observe("carbon pg factor set version"):
                    cur.execute(
                        "select version_code from public.emission_factor_sets where id = %s limit 1",
                        [factor_set_id],
                    )
                    row = cur.fetchone()
            if row is None:
                return None
            self._factor_set_versions[factor_set_id] = row["version_code"]
        return self._factor_set_versions[factor_set_id]

    # -- write ----------------------------------------------------------------

    def save_calculation(self, calculation: dict[str, Any], breakdowns: list[dict[str, Any]]) -> str:
        """Calculation + breakdown in one transaction and one round trip.

        The new row gets its id here, so the breakdown insert needs no answer
        from the first statement: it only inserts when a row with THAT id
        exists, i.e. when this call created it. On the season/input unique
        index the insert does nothing and the existing row is named instead
        (idempotent re-send). If a concurrent identical insert is in flight,
        Postgres waits for it; the final select, a new statement with a new
        snapshot, then sees the row it committed. Any failure rolls back all.
        """
        new_id = str(uuid.uuid4())
        row = {**calculation, "id": new_id}
        column_list = ", ".join(row)
        key = [calculation[c] for c in ("crop_season_id", "scenario", "factor_set_id", "input_hash")]
        statements: list[tuple[str, list[Any]]] = [(
            f"insert into public.carbon_calculations ({column_list})"
            f" select {column_list} from jsonb_populate_record(null::public.carbon_calculations, %s)"
            " on conflict (crop_season_id, scenario, factor_set_id, input_hash)"
            " where production_batch_id is null do nothing",
            [Jsonb(row)],
        )]
        breakdown_columns = list(dict.fromkeys(k for b in breakdowns for k in b))
        if breakdown_columns:
            cols = ", ".join(breakdown_columns)
            statements.append((
                f"insert into public.carbon_breakdowns (calculation_id, {cols})"
                f" select %s::uuid, {cols} from jsonb_populate_recordset(null::public.carbon_breakdowns, %s)"
                " where exists (select 1 from public.carbon_calculations c where c.id = %s::uuid)",
                [new_id, Jsonb(breakdowns), new_id],
            ))
        statements.append((
            "select jsonb_build_object('id', id::text) as r from public.carbon_calculations"
            " where production_batch_id is null and crop_season_id = %s"
            " and scenario = %s::public.carbon_scenario and factor_set_id = %s and input_hash = %s limit 1",
            key,
        ))
        with self._connection() as conn:
            *_, outcome = self._stage(conn, "carbon pg save calculation", statements, last=True)
        if not outcome:
            raise RuntimeError("carbon calculation was neither inserted nor found")
        return outcome[0]["id"]
