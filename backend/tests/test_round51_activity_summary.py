"""Round 5.1: `/crop-seasons/{id}/activity-summary` and newest-first `/activities`.

The Farmer Home now fetches only its few recent records plus this summary, so
the summary must carry exactly what the web's `seasonFacts` and season-date
helpers derived from the whole journal: counts, recorded costs per type (same
cost field per type, same number parsing), harvested area only when every
harvest has one, whether any fertilizer carries N/P/K, first seeding and last
harvest. `/activities` pages are newest first and stable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository, _as_number  # noqa: E402
from infrastructure.pagination import paginate  # noqa: E402
from tests.test_round51_org_plots_seasons import FakeClient  # noqa: E402

SEASON, BATCH = "season-1", "batch-1"


def _activity(aid, kind, at, deleted=False):
    return {"id": aid, "production_batch_id": BATCH, "activity_type": kind, "occurred_at": at,
            "recorded_at": at, "recorded_by": "u1", "source": "web", "note": None,
            "deleted_at": "2026-09-30T00:00:00Z" if deleted else None}


def _tables():
    acts = [
        _activity("s1", "seeding", "2026-05-03T01:00:00+00:00"),
        _activity("s0", "seeding", "2026-05-02T01:00:00+00:00"),
        _activity("f1", "fertilizer", "2026-06-01T01:00:00+00:00"),
        _activity("f2", "fertilizer", "2026-06-10T01:00:00+00:00"),
        _activity("i1", "irrigation", "2026-06-15T01:00:00+00:00"),
        _activity("h1", "harvest", "2026-08-20T01:00:00+00:00"),
        _activity("h2", "harvest", "2026-08-25T01:00:00+00:00"),
        _activity("gone", "irrigation", "2026-09-01T01:00:00+00:00", deleted=True),
    ]
    return {
        "crop_seasons": [{"id": SEASON}], "production_batches": [{"id": BATCH, "crop_season_id": SEASON}],
        "activities": acts, "profiles": [{"id": "u1", "full_name": "Nông hộ"}],
        "seeding_events": [{"activity_id": "s1", "cost_vnd": "150000"}, {"activity_id": "s0", "cost_vnd": None}],
        "fertilizer_applications": [{"activity_id": "f1", "total_cost_vnd": 200000, "nitrogen_percent": "46"},
                                    {"activity_id": "f2", "total_cost_vnd": "", "nitrogen_percent": None}],
        "irrigation_events": [{"activity_id": "i1", "total_cost_vnd": "50000.5"},
                              {"activity_id": "gone", "total_cost_vnd": "999"}],
        "harvest_events": [{"activity_id": "h1", "harvested_area_ha": "1.0"}, {"activity_id": "h2", "harvested_area_ha": "0.25"}],
    }


def _repo(tables):
    return SupabaseReadRepository(settings=None, token="jwt", client=FakeClient(tables))


def test_summary_carries_what_home_used_to_derive_from_the_whole_journal():
    s = _repo(_tables()).activity_summary(SEASON)
    assert s["total"] == 7  # the soft-deleted record is not counted
    assert s["count_by_type"] == {"seeding": 2, "fertilizer": 2, "irrigation": 1, "harvest": 2}
    assert s["cost_by_type"]["seeding"] == {"records": 2, "with_cost": 1, "recorded_vnd": 150000.0}
    assert s["cost_by_type"]["fertilizer"] == {"records": 2, "with_cost": 1, "recorded_vnd": 200000.0}
    assert s["cost_by_type"]["irrigation"] == {"records": 1, "with_cost": 1, "recorded_vnd": 50000.5}
    assert s["cost_by_type"]["harvest"] == {"records": 2, "with_cost": 0, "recorded_vnd": 0.0}
    assert (s["harvests"], s["harvests_with_area"], s["harvested_area_ha"]) == (2, 2, 1.25)
    assert s["fertilizer_has_nutrient"] is True
    assert s["first_seeding_at"].startswith("2026-05-02")
    assert s["last_harvest_at"].startswith("2026-08-25")


def test_a_harvest_without_area_is_counted_so_the_client_can_refuse_a_partial_sum():
    tables = _tables()
    tables["harvest_events"][1]["harvested_area_ha"] = None
    s = _repo(tables).activity_summary(SEASON)
    assert (s["harvests"], s["harvests_with_area"]) == (2, 1)


def test_activities_are_newest_first_so_page_one_is_the_recent_records():
    items = _repo(_tables()).activities(SEASON)
    assert [a["id"] for a in items] == ["h2", "h1", "i1", "f2", "f1", "s1", "s0"]
    assert [a["id"] for a in paginate(items, 1, 5)["items"]] == ["h2", "h1", "i1", "f2", "f1"]


def test_unknown_season_is_not_found():
    with pytest.raises(ReadNotFoundError):
        _repo(_tables()).activity_summary("other")


@pytest.mark.parametrize("value, expected", [
    (5, 5.0), ("1.25", 1.25), (" 7 ", 7.0), ("", None), ("  ", None), (None, None), ("abc", None),
    (True, None), (float("nan"), None), ("inf", None),
])
def test_number_parsing_matches_the_web(value, expected):
    assert _as_number(value) == expected


def test_a_jwt_issued_a_moment_in_the_future_is_retried_once_not_a_500(monkeypatch):
    """Hosted PostgREST's clock can trail Auth's right after sign-in (PGRST303
    "JWT issued at future"); the read waits a moment and succeeds instead of
    escaping as a 500."""
    import infrastructure.read_repo as rr

    class Skewed(Exception):
        code, message = "PGRST303", "JWT issued at future"

    calls = []
    monkeypatch.setattr(rr.time, "sleep", lambda s: calls.append(("sleep", s)))
    repo = _repo(_tables())

    def attempt():
        calls.append("try")
        if calls.count("try") == 1:
            raise Skewed()
        return "ok"

    assert repo._retrying(attempt) == "ok"
    assert calls == ["try", ("sleep", rr._CLOCK_SKEW_WAIT_SECONDS), "try"]

    def always():
        raise Skewed()

    with pytest.raises(Skewed):  # retried once only, then surfaces
        repo._retrying(always)
