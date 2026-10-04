"""Round 5 — the Carbon repository reads a season concurrently; the bundle is unchanged.

The calculation route made 16 sequential PostgREST calls (median 4.9 s, p95 8.9 s
on hosted Supabase). Independent reads now overlap and the immutable factor-set
lookups are cached. These tests pin that the bundle the engine receives is the
same rows as before, and that the factor set is looked up once per process.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.mapping import map_crop_activity_data  # noqa: E402
from infrastructure.supabase_repo import SupabaseCarbonRepository  # noqa: E402
from tests.fixtures import supabase_rows as rows  # noqa: E402

DETAIL = {
    "seeding": "seeding_events", "fertilizer": "fertilizer_applications", "irrigation": "irrigation_events",
    "fuel": "fuel_usages", "straw_management": "straw_management_events", "harvest": "harvest_events",
}


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.in_filter = db, table, [], None

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        self.in_filter = (column, set(values))
        return self

    def execute(self):
        with self.db.lock:
            self.db.calls.append(self.table)
        data = [r for r in self.db.tables.get(self.table, [])
                if all(str(r.get(c)) == str(v) for c, v in self.filters)
                and (self.in_filter is None or r.get(self.in_filter[0]) in self.in_filter[1])]
        return type("R", (), {"data": data})()


class _Db:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls: list[str] = []
        acts = rows.activities()
        self.tables = {
            "crop_seasons": [rows.crop_season()],
            "plots": [rows.plot()],
            "farms": [{"id": rows.FARM_ID, "name": "Hộ demo"}],
            "production_batches": rows.production_batches(1),
            "activities": [{k: v for k, v in a.items() if k != "detail"} for a in acts],
            "emission_factor_sets": [{"id": rows.FACTOR_SET_ID, "status": "published", "version_code": "V"}],
            "emission_factors": [{"id": "ef-1", "factor_code": "ch4_rice.efc", "factor_set_id": rows.FACTOR_SET_ID}],
        }
        for a in acts:
            table = DETAIL.get(a["activity_type"])
            self.tables.setdefault(table, []).append({**a["detail"], "activity_id": a["id"]})

    def table(self, name):
        return _Query(self, name)


def _repo():
    db = _Db()
    return SupabaseCarbonRepository(settings=object(), client=db), db


def test_concurrent_bundle_is_the_same_rows_the_engine_always_received():
    repo, db = _repo()
    bundle = repo.get_crop_bundle(rows.CROP_ID)
    assert bundle.crop_season["id"] == rows.CROP_ID
    assert bundle.farm["id"] == rows.FARM_ID
    assert sorted(a["id"] for a in bundle.activities) == sorted(a["id"] for a in rows.activities())
    for activity in bundle.activities:
        expected = next(a for a in rows.activities() if a["id"] == activity["id"])["detail"]
        assert {k: v for k, v in activity["detail"].items() if k != "activity_id"} == \
            {k: v for k, v in expected.items() if k != "activity_id"}
    # Same Activity Data → the engine's input is identical.
    reference = map_crop_activity_data(type(bundle)(
        crop_season=rows.crop_season(), plot=rows.plot(), farm={"id": rows.FARM_ID, "name": "Hộ demo"},
        production_batches=rows.production_batches(1), activities=rows.activities(),
    ))
    assert map_crop_activity_data(bundle).canonical_json() == reference.canonical_json()


def test_every_detail_table_is_read_once():
    repo, db = _repo()
    repo.get_crop_bundle(rows.CROP_ID)
    detail_reads = [t for t in db.calls if t in DETAIL.values()]
    assert sorted(detail_reads) == sorted(set(detail_reads))


def test_published_factor_set_and_factor_ids_are_looked_up_once():
    repo, db = _repo()
    for _ in range(3):
        assert repo.resolve_factor_set_id("V") == rows.FACTOR_SET_ID
        assert repo.factor_ids_by_code(rows.FACTOR_SET_ID) == {"ch4_rice.efc": "ef-1"}
    assert db.calls.count("emission_factor_sets") == 1
    assert db.calls.count("emission_factors") == 1
