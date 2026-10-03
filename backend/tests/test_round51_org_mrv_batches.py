"""Round 5.1: `GET /v1/organizations/{id}/mrv-batches` — one request, every MRV case.

Management read `/mrv/cases` (first page of 20 only) and then one
`/mrv/cases/{id}/batches` PER CASE. The batch must return, for each case of the
organization, exactly what the per-case endpoint returns, in a number of reads
that does not grow with the number of cases (0, 1, 30). Scope stays with the
caller's client (RLS): the fake only returns what its tables hold.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository  # noqa: E402
from tests.test_round51_org_plots_seasons import FakeClient  # noqa: E402

ORG = "org-1"


def _tenant(cases: int) -> dict:
    t = {"organizations": [{"id": ORG}, {"id": "org-2"}], "mrv_cases": [], "mrv_case_batches": [],
         "production_batches": [], "crop_seasons": [], "plots": [], "mrv_case_steps": [], "mrv_evidence": []}
    for c in range(cases):
        cid = f"case-{c:02d}"
        t["mrv_cases"].append({"id": cid, "case_code": f"MRV-{c:02d}", "name": "Hồ sơ", "status": "draft",
                               "organization_id": ORG, "period_start": None, "period_end": None})
        for b in range(1 + c % 3):
            bid, sid, pid = f"b-{c}-{b}", f"s-{c}-{b}", f"p-{c}-{b}"
            t["plots"].append({"id": pid, "farm_id": f"farm-{c % 4}"})
            t["crop_seasons"].append({"id": sid, "plot_id": pid})
            t["production_batches"].append({"id": bid, "crop_season_id": sid, "batch_code": f"L{c}{b}"})
            t["mrv_case_batches"].append({"mrv_case_id": cid, "production_batch_id": bid})
    # Another organization's case must never appear.
    t["mrv_cases"].append({"id": "foreign", "case_code": "X", "name": "x", "status": "draft", "organization_id": "org-2"})
    return t


def _repo(tables):
    client = FakeClient(tables)
    return SupabaseReadRepository(settings=None, token="jwt", client=client), client


@pytest.mark.parametrize("cases", [0, 1, 30])
def test_fixed_reads_and_same_rows_as_per_case(cases):
    tables = _tenant(cases)
    repo, client = _repo(tables)
    items = repo.organization_mrv_batches(ORG)
    reads = len(client.requests)

    assert [i["case_id"] for i in items] == [f"case-{c:02d}" for c in range(cases)]  # all 30, not 20
    assert reads <= 6  # org + cases + links + batches + seasons + plots, whatever the count

    for item in items:
        per_case, _ = _repo(tables)
        assert item["batches"] == per_case.mrv_batches(item["case_id"])


def test_invisible_organization_is_not_found():
    repo, _ = _repo(_tenant(1))
    with pytest.raises(ReadNotFoundError):
        repo.organization_mrv_batches("org-hidden")


def test_batch_hidden_by_rls_is_left_out_not_guessed():
    tables = _tenant(1)
    tables["plots"].clear()  # the caller cannot read the plot
    repo, _ = _repo(tables)
    assert repo.organization_mrv_batches(ORG) == [
        {"case_id": "case-00", "case_code": "MRV-00", "status": "draft", "batches": []}]
