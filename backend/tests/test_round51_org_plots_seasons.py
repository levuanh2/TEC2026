"""Round 5.1: `GET /v1/organizations/{id}/plots-seasons` — one request, every farm.

Management listed plots and seasons with two requests PER FARM. The batch must
return, for each farm, exactly what `/farms/{id}/plots` and
`/farms/{id}/crop-seasons` return, in a number of reads that does not grow with
the number of farms (1, 5, 30). Scope stays with the caller's client (RLS): the
fake below only ever returns what its tables hold, like PostgREST under RLS.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository  # noqa: E402

ORG = "org-1"


class _Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters = client, table, []

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters.append((column, {value}))
        return self

    def in_(self, column, values):
        self.filters.append((column, set(values)))
        return self

    def execute(self):
        self.client.requests.append(self.table)
        rows = [r for r in self.client.tables.get(self.table, []) if all(str(r.get(c)) in {str(v) for v in vs} for c, vs in self.filters)]
        return type("Resp", (), {"data": [dict(r) for r in rows]})()


class FakeClient:
    def __init__(self, tables):
        self.tables, self.requests = tables, []
        self.postgrest = type("P", (), {"auth": lambda *_: None})()

    def table(self, name):
        return _Query(self, name)


def _tenant(farms: int):
    tables = {"organizations": [{"id": ORG, "name": "HTX"}], "farms": [], "plots": [], "crop_seasons": []}
    for f in range(farms):
        fid = f"farm-{f}"
        tables["farms"].append({"id": fid, "cooperative_id": ORG, "name": f"Hộ {f}"})
        for p in range(1 + f % 2):
            pid = f"plot-{f}-{p}"
            tables["plots"].append({"id": pid, "farm_id": fid, "plot_code": f"P{f}{p}", "name": "Thửa", "area_ha": 1.25})
            for s in range(f % 3):
                tables["crop_seasons"].append({"id": f"season-{f}-{p}-{s}", "plot_id": pid, "season_code": f"S{s}",
                                               "status": "active", "deleted_at": None})
    tables["farms"].append({"id": "foreign-farm", "cooperative_id": "other-org", "name": "Hộ khác"})
    return tables


def _repo(client):
    return SupabaseReadRepository(settings=None, token="jwt", client=client)


@pytest.mark.parametrize("farms", [1, 5, 30])
def test_batch_equals_the_per_farm_endpoints_in_a_constant_number_of_reads(farms):
    client = FakeClient(_tenant(farms))
    repo = _repo(client)
    batch = repo.organization_plots_and_seasons(ORG)
    batch_requests = len(client.requests)

    client.requests.clear()
    per_farm = {}
    for item in batch:
        per_farm[item["farm_id"]] = {
            "plots": repo.plots_for_farm(item["farm_id"]),
            "crop_seasons": repo.farm_crop_seasons(item["farm_id"]),
        }
    per_farm_requests = len(client.requests)

    assert [i["farm_id"] for i in batch] == [f"farm-{f}" for f in range(farms)]  # never the foreign farm
    for item in batch:
        expected = per_farm[item["farm_id"]]
        assert sorted(item["plots"], key=lambda x: x["id"]) == sorted(expected["plots"], key=lambda x: x["id"])
        assert sorted(item["crop_seasons"], key=lambda x: x["id"]) == sorted(expected["crop_seasons"], key=lambda x: x["id"])
    assert batch_requests == 4  # organization, farms, plots, seasons — for 1, 5 or 30 farms
    assert per_farm_requests == 5 * farms  # what the two per-farm routes cost together


def test_an_organization_the_caller_cannot_read_is_not_found():
    with pytest.raises(ReadNotFoundError):
        _repo(FakeClient(_tenant(2))).organization_plots_and_seasons("other-org-not-visible")
