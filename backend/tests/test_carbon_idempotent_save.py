"""Recalculating a season with unchanged inputs must not fail.

Hosted dev showed it: once a factor set was published, a second writer running
the identical calculation hit `carbon_calculations_season_input_uniq`
(crop_season_id, scenario, factor_set_id, input_hash) and got a 500. The same
inputs give the same result, so the stored calculation is reused.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgrest.exceptions import APIError  # noqa: E402

from infrastructure.repository import InMemoryCarbonRepository  # noqa: E402
from infrastructure.supabase_repo import SupabaseCarbonRepository  # noqa: E402

CALC = {"crop_season_id": "season-1", "scenario": "actual", "factor_set_id": "set-1", "input_hash": "a" * 64,
        "total_co2e_kg": 10.0, "yield_kg": 5.0, "calculated_at": "2026-09-16T00:00:00Z", "status": "succeeded"}


class _Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters, self.payload, self.op = client, table, [], None, "select"

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def is_(self, column, value):
        self.filters.append((column, None if value == "null" else value))
        return self

    def limit(self, _):
        return self

    def execute(self):
        self.client.calls.append((self.table, self.op, self.filters))
        return self.client.respond(self)


class _Client:
    def __init__(self, respond):
        self.respond, self.calls = respond, []

    def table(self, name):
        return _Query(self, name)


def _repo(client) -> SupabaseCarbonRepository:
    return SupabaseCarbonRepository(settings=None, client=client)


def test_in_memory_identical_calculation_reuses_row():
    repo = InMemoryCarbonRepository()
    first = repo.save_calculation(dict(CALC), [{"category": "irrigation_ch4"}])
    assert repo.save_calculation(dict(CALC), [{"category": "irrigation_ch4"}]) == first
    assert len(repo.calculations) == 1 and len(repo.breakdowns[first]) == 1
    changed = repo.save_calculation({**CALC, "input_hash": "b" * 64}, [])
    assert changed != first and len(repo.calculations) == 2


def test_supabase_unique_violation_returns_existing_calculation():
    def respond(query):
        if query.op == "insert":
            raise APIError({"code": "23505", "message": "duplicate key value violates unique constraint"})
        return type("R", (), {"data": [{"id": "calc-existing"}]})()

    client = _Client(respond)
    assert _repo(client).save_calculation(dict(CALC), [{"category": "irrigation_ch4"}]) == "calc-existing"
    lookup = client.calls[-1]
    assert lookup[0] == "carbon_calculations" and dict(lookup[2]) == {
        "production_batch_id": None, "crop_season_id": "season-1", "scenario": "actual",
        "factor_set_id": "set-1", "input_hash": "a" * 64}
    assert not any(table == "carbon_breakdowns" for table, _, _ in client.calls)  # no duplicate breakdown rows


def test_supabase_other_database_errors_still_raise():
    def respond(query):
        raise APIError({"code": "23514", "message": "check constraint"})

    with pytest.raises(APIError):
        _repo(_Client(respond)).save_calculation(dict(CALC), [])
