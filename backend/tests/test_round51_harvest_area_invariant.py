"""Round 5.1: `harvested_area_ha <= plots.area_ha` holds in the DATABASE.

Migration 20260929120000 enforces the rule on every write path, including the
Flutter offline queue that writes straight to PostgREST. Each case runs as the
real farmer (`authenticated` role, RLS on) or as the backend role, inside a
savepoint of an outer transaction that is always rolled back.

Cases on one plot of area P: P - 0.01 and P pass, P + 0.001 fails with 23514
`harvested_area_exceeds_plot` (and a Vietnamese hint), a negative area fails
the existing check, NULL passes; shrinking the plot below a recorded harvest
and moving the season onto a smaller plot fail too. Skipped without
`SUPABASE_DB_URL`.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the real-database tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url
pytestmark = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


@pytest.fixture
def db():
    with psycopg.connect(_DB_URL, autocommit=False, row_factory=dict_row) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture
def scope(db):
    row = db.execute("""
        select cs.id::text as season, pb.id::text as batch, p.id::text as plot, p.area_ha, p.farm_id::text as farm,
               fm.user_id::text as farmer
        from public.crop_seasons cs
        join public.plots p on p.id = cs.plot_id
        join public.production_batches pb on pb.crop_season_id = cs.id and pb.deleted_at is null
        join public.farms f on f.id = p.farm_id
        join public.farm_members fm on fm.farm_id = f.id and fm.farm_role in ('owner', 'editor')
        join public.organization_memberships om on om.user_id = fm.user_id and om.organization_id = f.cooperative_id
        where cs.status = 'active' and cs.deleted_at is null and p.area_ha is not null
          and om.role = 'farmer' and (om.ended_at is null or om.ended_at > now())
          and coalesce(pb.status::text, '') not in ('closed', 'cancelled')
        order by cs.id limit 1""").fetchone()
    assert row, "no active season of a writable farmer on a plot with an area"
    return row


def _as_farmer(db, farmer: str) -> None:
    db.execute("select set_config('role', 'authenticated', true), "
               "set_config('request.jwt.claims', %s, true)", [json.dumps({"sub": farmer, "role": "authenticated"})])


def _as_backend(db) -> None:
    db.execute("reset role")
    db.execute("select set_config('request.jwt.claims', '', true)")


def _harvest(db, scope, area):
    """Insert one harvest as the farmer; returns None or the error raised."""
    try:
        with db.transaction():
            _as_farmer(db, scope["farmer"])
            activity = db.execute(
                "insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source,"
                " recorded_by, note) values (%s, 'harvest', now(), now(), 'web', %s, 'ROUND51-INVARIANT-TEST')"
                " returning id::text as id", [scope["batch"], scope["farmer"]]).fetchone()["id"]
            db.execute("insert into public.harvest_events (activity_id, yield_kg, harvested_area_ha)"
                       " values (%s, 100, %s)", [activity, area])
            _as_backend(db)
        return None
    except psycopg.Error as exc:
        _as_backend(db)
        return exc


def test_equal_or_smaller_area_is_accepted_for_the_farmer(db, scope):
    area = float(scope["area_ha"])
    assert _harvest(db, scope, round(area - 0.01, 4)) is None
    assert _harvest(db, scope, area) is None
    assert _harvest(db, scope, None) is None


def test_larger_area_is_refused_with_a_mappable_error(db, scope):
    exc = _harvest(db, scope, float(scope["area_ha"]) + 0.001)
    assert exc is not None, "a harvest larger than its plot was accepted"
    assert exc.sqlstate == "23514"
    assert str(exc).startswith("harvested_area_exceeds_plot:")
    assert exc.diag.message_hint == "Diện tích thu hoạch không được lớn hơn diện tích thửa."


def test_negative_area_is_refused(db, scope):
    exc = _harvest(db, scope, -1)
    assert exc is not None and exc.sqlstate == "23514"


def test_update_to_a_larger_area_is_refused(db, scope):
    assert _harvest(db, scope, float(scope["area_ha"])) is None
    with pytest.raises(psycopg.Error) as caught, db.transaction():
        db.execute("update public.harvest_events h set harvested_area_ha = h.harvested_area_ha + 1"
                   " from public.activities a where a.id = h.activity_id and a.note = 'ROUND51-INVARIANT-TEST'")
    assert caught.value.sqlstate == "23514"


def test_plot_cannot_shrink_below_a_recorded_harvest(db, scope):
    assert _harvest(db, scope, float(scope["area_ha"])) is None
    with pytest.raises(psycopg.Error) as caught, db.transaction():
        db.execute("update public.plots set area_ha = area_ha - 0.01 where id = %s", [scope["plot"]])
    assert caught.value.sqlstate == "23514"
    with db.transaction():  # growing is always fine
        db.execute("update public.plots set area_ha = area_ha + 1 where id = %s", [scope["plot"]])


def test_season_cannot_move_onto_a_smaller_plot(db, scope):
    assert _harvest(db, scope, float(scope["area_ha"])) is None
    small = str(uuid.uuid4())
    with db.transaction():
        db.execute("insert into public.plots (id, farm_id, plot_code, name, area_ha) values (%s, %s, %s, %s, %s)",
                   [small, scope["farm"], f"R51-{small[:8]}", "R51 test plot", float(scope["area_ha"]) / 2])
    with pytest.raises(psycopg.Error) as caught, db.transaction():
        db.execute("update public.crop_seasons set plot_id = %s where id = %s", [small, scope["season"]])
    assert caught.value.sqlstate == "23514"
