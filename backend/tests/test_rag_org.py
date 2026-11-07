"""PROTOTYPE organization (HTX) assistant: authorization contract, pagination, partial failure."""
from __future__ import annotations

import pytest

from rag_org import PAGE_SIZE, OrgQuestionService
from recommendation.rag import RagAccessDenied

ORG_A, ORG_B, ME = "org-a", "org-b", "user-1"


class Reader:
    def __init__(self, memberships=(("org-a", "cooperative_manager"),), seasons=3, fail_metrics=False,
                 must_change=False):
        self.memberships, self.n, self.fail, self.must_change, self.calls = memberships, seasons, fail_metrics, must_change, []

    def me(self):
        return {"user_id": ME, "must_change_password": self.must_change,
                "organization_memberships": [{"organization_id": o, "role": r} for o, r in self.memberships]}

    def organization_summary(self, org):
        self.calls.append(("summary", org))
        return {"organization_id": org, "farm_count": 2, "plot_count": 3, "crop_season_count": self.n,
                "total_area_ha": 4.5, "total_yield_kg": None, "total_co2e_kg": None, "co2e_per_kg": None}

    def organization_plots_and_seasons(self, org):
        self.calls.append(("seasons", org))
        return [{"farm_id": "f", "plots": [], "crop_seasons": [{"id": f"s{i:05d}", "season_code": f"V{i}"}
                                                               for i in range(self.n)]}]

    def metrics_for_seasons(self, ids):
        self.calls.append(("metrics", tuple(ids)))
        if self.fail:
            raise RuntimeError("upstream timeout")
        return {i: {"yield_kg": None if i.endswith("1") else 10.0,
                    "data_completeness": {"water": i.endswith("0"), "fertilizer": True, "cost": True}} for i in ids}


def _ask(reader, org=ORG_A, intent="org_summary", page=0):
    return OrgQuestionService().answer(reader=reader, organization_id=org, intent=intent, page=page)


@pytest.mark.parametrize("memberships, org", [
    ((), ORG_A),                                           # not a member
    ((("org-a", "farmer"),), ORG_A),                       # member, but a farm role is not an org read role
    ((("org-a", "cooperative_manager"),), ORG_B),          # manager of A selecting B in the request
    ((("org-b", "enterprise_viewer"),), ORG_B),            # not an org read role in this prototype
])
def test_access_comes_from_the_callers_active_membership_not_the_request(memberships, org):
    reader = Reader(memberships=memberships)
    with pytest.raises(RagAccessDenied):
        _ask(reader, org)
    assert reader.calls == []                              # nothing read before authorization


def test_a_pending_password_change_sees_nothing():
    with pytest.raises(RagAccessDenied):
        _ask(Reader(must_change=True))


def test_summary_states_missing_totals_as_missing_never_zero():
    body = _ask(Reader())
    assert body["status"] == "generated" and "chưa có dữ liệu" in body["answer"] and " 0 kg" not in body["answer"]
    assert body["provenance"] == {"answer_source": "system_composed", "llm_calls": 0, "persisted": False}
    assert any("MRV" in limitation for limitation in body["limitations"])


def test_data_gaps_are_listed_per_season():
    body = _ask(Reader(seasons=3), intent="org_data_gaps")
    assert body["facts"]["gaps"]["water"] == ["V1", "V2"] and body["facts"]["gaps"]["yield"] == ["V1"]


def test_a_large_htx_is_paginated_and_each_page_reads_only_its_seasons():
    reader = Reader(seasons=120)
    pages = [_ask(reader, intent="org_data_gaps", page=p) for p in range(3)]
    assert [len(c[1]) for c in reader.calls if c[0] == "metrics"] == [PAGE_SIZE, PAGE_SIZE, 20]
    assert [p["page"]["has_more"] for p in pages] == [True, True, False] and pages[0]["page"]["total"] == 120
    with pytest.raises(RagAccessDenied):
        _ask(reader, intent="org_data_gaps", page=10_000)


def test_a_failing_metrics_read_is_partial_and_invents_nothing():
    body = _ask(Reader(seasons=4, fail_metrics=True), intent="org_data_gaps")
    assert body["status"] == "partial" and body["partial"] is True
    assert body["facts"]["unknown"] == ["V0", "V1", "V2", "V3"] and not any(body["facts"]["gaps"].values())


def test_action_and_unknown_intents_are_refused():
    for intent in ("recommend", "what_if", "anything"):
        with pytest.raises(RagAccessDenied):
            _ask(Reader(), intent=intent)
