"""Carbon straw quick-fix persistence against the REAL database.

Reproduced bug (2026-09-19): the demo seed writes activities with
`recorded_by` NULL. The `activities_update` RLS policy lets any writer of the
batch complete such a record, but the FastAPI write repository filtered on
`recorded_by = actor`, so the Carbon "Sửa ngay" PATCH answered 404 and the
straw methodology fields never reached `straw_management_events`.

This drives the real service + repository inside one transaction that is
always rolled back, then reads the subtype row directly and runs it through the
same mapper and readiness code the readiness endpoint uses. Skipped when
`SUPABASE_DB_URL` is not configured.
"""
from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schemas  # noqa: E402
from carbon.readiness import missing_inputs  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402
from infrastructure.mapping import RawCropBundle, map_crop_activity_data  # noqa: E402
from infrastructure.write_repo import PostgresActivityWriteRepository  # noqa: E402
from service import ActivityWriteAccessError, ActivityWriteService  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the real-database tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url

pytestmark = pytest.mark.skipif(
    not _DB_URL,
    reason="SUPABASE_DB_URL is not configured; persistence needs a real database.",
)

FARM_CODE = "DEMO-FARM-01"
STRAW_CODES = {"straw_mass", "straw_dry_matter", "straw_days_before_cultivation", "straw_returned_to_field"}


@pytest.fixture
def db():
    with psycopg.connect(_DB_URL, autocommit=False, row_factory=dict_row) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


def _one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def _scope(conn):
    """The demo farm's first live batch and a farmer who owns/edits it."""
    row = _one(conn, """
        select pb.id::text as batch, pb.crop_season_id::text as season, fm.user_id::text as farmer
        from public.farms f
        join public.plots p on p.farm_id = f.id
        join public.crop_seasons cs on cs.plot_id = p.id
        join public.production_batches pb on pb.crop_season_id = cs.id
        join public.farm_members fm on fm.farm_id = f.id and fm.farm_role in ('owner', 'editor')
        join public.organization_memberships om on om.user_id = fm.user_id and om.organization_id = f.cooperative_id
        where f.farm_code = %s and pb.deleted_at is null and om.role = 'farmer'
          and (om.ended_at is null or om.ended_at > now())
        limit 1""", (FARM_CODE,))
    assert row, "no writable farmer scope on the demo farm"
    return row


def _straw(conn, batch, *, recorded_by=None):
    activity = _one(conn, """
        insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source, recorded_by, note)
        values (%s, 'straw_management', now(), now(), 'web', %s, 'STRAW-QUICKFIX-TEST') returning id::text as id""",
        (batch, recorded_by))["id"]
    conn.execute(
        "insert into public.straw_management_events (activity_id, method, straw_mass_kg) values (%s, 'incorporated', 800)",
        (activity,),
    )
    return activity


class _Reader:
    """The caller-JWT scope answers the service asks for; the write itself and
    its batch permission check run on the real database."""

    def __init__(self, farmer, season, batch):
        self._farmer, self._season, self._batch = farmer, season, batch

    def me(self):
        return {"user_id": self._farmer, "roles": ["farmer"]}

    def activity(self, activity_id):
        return {"id": activity_id}

    def season(self, season_id):
        return {"id": season_id, "status": "active"}

    def production_batches(self, season_id):
        return [{"id": self._batch, "status": "active"}]


def _service(conn):
    bound = type("Bound", (), {"cursor": lambda self: conn.cursor(row_factory=dict_row)})()
    return ActivityWriteService(PostgresActivityWriteRepository(settings=None, connect=lambda: nullcontext(bound)))


def _patch(conn, reader, activity_id, data):
    return _service(conn).update(
        read_repository=reader, activity_id=activity_id,
        request=schemas.ActivityUpdateRequest(data=data),
    )


def _row(conn, activity_id):
    return _one(conn, "select * from public.straw_management_events where activity_id = %s", (activity_id,))


def _straw_readiness(conn, activity_id):
    """The persisted row → CropActivityData → readiness, as the endpoint maps it."""
    bundle = RawCropBundle(
        crop_season={"id": "season"}, plot={"area_ha": 1},
        activities=[{"id": activity_id, "activity_type": "straw_management", "deleted_at": None, "detail": _row(conn, activity_id)}],
    )
    return {m.code for m in missing_inputs(map_crop_activity_data(bundle))} & STRAW_CODES


def test_quickfix_on_a_seeded_straw_record_persists_and_readiness_follows(db):
    scope = _scope(db)
    reader = _Reader(scope["farmer"], scope["season"], scope["batch"])
    activity_id = _straw(db, scope["batch"])  # recorded_by NULL, like the demo seed

    assert _straw_readiness(db, activity_id) == {"straw_dry_matter", "straw_days_before_cultivation"}

    response = _patch(db, reader, activity_id, {"days_before_cultivation": 20})
    assert response["data"]["days_before_cultivation"] == 20
    # The route's response model must accept the unattributed row, or the
    # committed write reaches the browser as a 500.
    assert schemas.ActivityWriteResponse.model_validate(response).created_by is None
    row = _row(db, activity_id)
    assert row["days_before_cultivation"] == 20 and row["dry_matter_fraction"] is None
    assert _straw_readiness(db, activity_id) == {"straw_dry_matter"}

    _patch(db, reader, activity_id, {"dry_matter_fraction": 0.85, "returned_to_field": True})
    row = _row(db, activity_id)
    assert row["days_before_cultivation"] == 20  # the second PATCH omitted it
    assert float(row["dry_matter_fraction"]) == 0.85
    assert row["returned_to_field"] is True
    assert float(row["straw_mass_kg"]) == 800
    assert _straw_readiness(db, activity_id) == set()

    # Editing completes the record; it does not claim authorship of it.
    assert _one(db, "select recorded_by from public.activities where id = %s", (activity_id,))["recorded_by"] is None


def test_explicit_null_clears_a_persisted_straw_field(db):
    scope = _scope(db)
    reader = _Reader(scope["farmer"], scope["season"], scope["batch"])
    activity_id = _straw(db, scope["batch"])
    _patch(db, reader, activity_id, {"days_before_cultivation": 20, "dry_matter_fraction": 0.85})
    _patch(db, reader, activity_id, {"dry_matter_fraction": None})
    row = _row(db, activity_id)
    assert row["dry_matter_fraction"] is None and row["days_before_cultivation"] == 20
    assert _straw_readiness(db, activity_id) == {"straw_dry_matter"}


def test_another_farmers_straw_record_is_still_not_editable(db):
    scope = _scope(db)
    other = _one(db, """select fm.user_id::text as id from public.farm_members fm
                        where fm.user_id <> %s limit 1""", (scope["farmer"],))
    assert other, "need a second user to author the record"
    activity_id = _straw(db, scope["batch"], recorded_by=other["id"])
    reader = _Reader(scope["farmer"], scope["season"], scope["batch"])
    with pytest.raises(ActivityWriteAccessError):
        _patch(db, reader, activity_id, {"days_before_cultivation": 20})
    assert _row(db, activity_id)["days_before_cultivation"] is None


def test_a_seeded_record_still_cannot_be_deleted_by_the_farmer(db):
    scope = _scope(db)
    reader = _Reader(scope["farmer"], scope["season"], scope["batch"])
    activity_id = _straw(db, scope["batch"])
    with pytest.raises(ActivityWriteAccessError):
        _service(db).delete(read_repository=reader, activity_id=activity_id)
    assert _one(db, "select deleted_at from public.activities where id = %s", (activity_id,))["deleted_at"] is None
