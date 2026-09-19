"""Carbon repository: an idempotent read survives a server-closed keep-alive
connection; a write is never retried.

Found by the Flutter emulator E2E (2026-09-20): readiness and the latest result
both answered 500 with `httpcore.RemoteProtocolError: Server disconnected`
because `SupabaseCarbonRepository` -- unlike `SupabaseReadRepository` -- had no
retry for a dead PostgREST connection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

httpx = pytest.importorskip("httpx")

from infrastructure import supabase_repo  # noqa: E402
from infrastructure.supabase_repo import SupabaseCarbonRepository  # noqa: E402


class _Query:
    def __init__(self, client, table):
        self.client, self.table = client, table

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def insert(self, rows):
        self.client.inserts += 1
        return self

    def execute(self):
        if self.client.failures_left > 0:
            self.client.failures_left -= 1
            raise httpx.RemoteProtocolError("Server disconnected")
        return type("R", (), {"data": [{"id": "row-1", "table": self.table}]})()


class _Client:
    created = 0

    def __init__(self, failures: int):
        _Client.created += 1
        self.failures_left = failures
        self.inserts = 0

    def table(self, name):
        return _Query(self, name)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(supabase_repo.time, "sleep", lambda _s: None)


def _repo(first: _Client, monkeypatch) -> SupabaseCarbonRepository:
    repo = SupabaseCarbonRepository(settings=object(), client=first)
    # A replacement client (what `client` builds lazily after a reset) is healthy.
    monkeypatch.setattr(SupabaseCarbonRepository, "client",
                        property(lambda self: self._client if self._client is not None else _fresh(self)))
    return repo


def _fresh(repo):
    repo._client = _Client(failures=0)
    return repo._client


def test_a_dead_connection_on_a_read_is_replaced_and_the_read_succeeds(monkeypatch):
    dead = _Client(failures=1)
    repo = _repo(dead, monkeypatch)
    rows = repo._many("crop_seasons", {"id": "s"})
    assert rows == [{"id": "row-1", "table": "crop_seasons"}]
    assert repo._client is not dead  # the dead client was dropped


def test_a_read_that_keeps_failing_still_raises(monkeypatch):
    repo = SupabaseCarbonRepository(settings=object(), client=_Client(failures=99))
    monkeypatch.setattr(SupabaseCarbonRepository, "client",
                        property(lambda self: self._client or _Client(failures=99)))
    with pytest.raises(httpx.RemoteProtocolError):
        repo._many("crop_seasons", {"id": "s"})


def test_a_write_is_never_retried(monkeypatch):
    client = _Client(failures=1)
    repo = _repo(client, monkeypatch)
    with pytest.raises(httpx.RemoteProtocolError):
        repo.save_calculation({"crop_season_id": "s"}, [])
    assert client.inserts == 1
