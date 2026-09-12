"""Round-4 read-path guarantees: client reuse, dead-connection retry, and the
request profiler that measures them.

These are behavioural, not timing, assertions — a stopwatch in CI proves
nothing, but "this caller's client is reused", "this token never borrows
another token's client", "a dropped keep-alive connection is retried once" and
"the profiler counts every round trip, including the concurrent ones" are all
exactly checkable.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure import profiling, supabase_clients  # noqa: E402
from infrastructure.config import Settings  # noqa: E402
from infrastructure.read_repo import SupabaseReadRepository  # noqa: E402

SETTINGS = Settings(
    supabase_url="https://example.supabase.co",
    supabase_service_role_key=None,
    supabase_publishable_key="publishable-key",
    ef_config_path=Path("unused"),
    require_factor_set_in_db=False,
    cors_origins=[],
)


class _Client:
    """Records the token bound to it and how many queries it answered."""

    created = 0

    def __init__(self, rows: dict[str, list[dict]] | None = None, fail_times: int = 0):
        _Client.created += 1
        self.index = _Client.created
        self.rows = rows or {}
        self.fail_times = fail_times
        self.queries: list[str] = []
        self.bound_token: str | None = None
        self.closed = False
        outer = self
        self.postgrest = SimpleNamespace(
            auth=lambda token: setattr(outer, "bound_token", token),
            session=SimpleNamespace(close=lambda: setattr(outer, "closed", True)),
        )
        self.auth = SimpleNamespace(get_user=lambda token: SimpleNamespace(user=SimpleNamespace(id="user-1")))

    def table(self, name: str):
        return _Table(self, name)


class _Table:
    def __init__(self, client: _Client, name: str):
        self.client = client
        self.name = name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a):
        return self

    def in_(self, *_a):
        return self

    def execute(self):
        self.client.queries.append(self.name)
        if self.client.fail_times > 0:
            self.client.fail_times -= 1
            raise httpx.RemoteProtocolError("Server disconnected")
        return SimpleNamespace(data=self.client.rows.get(self.name, []))


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    supabase_clients.clear()
    _Client.created = 0
    yield
    supabase_clients.clear()


def _patch_factory(monkeypatch, make):
    monkeypatch.setattr(supabase_clients, "create_client", make, raising=False)
    import supabase

    monkeypatch.setattr(supabase, "create_client", make)


def test_same_token_reuses_one_client(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key: _Client())
    first = SupabaseReadRepository(SETTINGS, "token-a")
    second = SupabaseReadRepository(SETTINGS, "token-a")
    assert first.client is second.client
    assert _Client.created == 1


def test_a_different_token_never_borrows_another_callers_client(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key: _Client())
    a = SupabaseReadRepository(SETTINGS, "token-a")
    b = SupabaseReadRepository(SETTINGS, "token-b")
    assert a.client is not b.client
    assert a.client.bound_token == "token-a"
    assert b.client.bound_token == "token-b"


def test_a_cached_client_is_never_rebound_to_a_second_token(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key: _Client())
    SupabaseReadRepository(SETTINGS, "token-a")
    reused = SupabaseReadRepository(SETTINGS, "token-a")
    # Re-authenticating a reused client is what would let one caller's pool
    # answer for another; construction must bind exactly once.
    assert reused.client.bound_token == "token-a"


def test_client_cache_is_bounded(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key: _Client())
    for i in range(supabase_clients.MAX_CLIENTS + 5):
        SupabaseReadRepository(SETTINGS, f"token-{i}")
    assert len(supabase_clients._clients) <= supabase_clients.MAX_CLIENTS


def test_dropped_connection_is_retried_once_on_a_fresh_client(monkeypatch):
    clients: list[_Client] = []

    def make(url, key):
        client = _Client(rows={"farms": [{"id": "f1"}]}, fail_times=1 if not clients else 0)
        clients.append(client)
        return client

    _patch_factory(monkeypatch, make)
    repo = SupabaseReadRepository(SETTINGS, "token-a")
    assert repo._many("farms") == [{"id": "f1"}]
    assert len(clients) == 2, "the dead pool must be replaced, not reused"
    assert repo.client is clients[1]


def test_retry_is_not_applied_to_an_injected_client(monkeypatch):
    """A test/production caller that supplied its own client owns its failures."""
    injected = _Client(fail_times=1)
    repo = SupabaseReadRepository(SETTINGS, "token-a", client=injected)
    with pytest.raises(httpx.RemoteProtocolError):
        repo._many("farms")


def test_profiler_counts_every_round_trip_including_concurrent_ones(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key: _Client(rows={"farms": [], "plots": [], "crop_seasons": []}))
    profile = profiling.start()
    SupabaseReadRepository(SETTINGS, "token-a").farmer_scope()
    assert profile.calls == 3, "reads issued from worker threads must still be attributed"
    assert {label for label, _, _ in profile.top()} == {
        "select farms", "select plots", "select crop_seasons",
    }


def test_profiler_is_inert_outside_a_request(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key: _Client())
    profiling._current.set(None)
    SupabaseReadRepository(SETTINGS, "token-a")._many("farms")  # must not raise



def test_concurrent_first_reads_of_one_token_build_a_single_client(monkeypatch):
    """A Farmer page load fires /me and /farmer/scope at the same instant. On a
    brand-new token both would otherwise build their own ~450ms client and all
    but one would be thrown away — measured as /v1/me going 1686ms -> 2546ms at
    login when the second read was added."""
    import threading

    started = threading.Barrier(3)

    def make(url, key):
        time.sleep(0.05)  # long enough for a racing thread to slip through
        return _Client()

    _patch_factory(monkeypatch, make)
    results: list[Any] = []

    def build():
        started.wait()
        results.append(SupabaseReadRepository(SETTINGS, "token-a").client)

    threads = [threading.Thread(target=build) for _ in range(2)]
    for t in threads:
        t.start()
    started.wait()
    for t in threads:
        t.join()

    assert _Client.created == 1
    assert results[0] is results[1]
    assert not supabase_clients._building, "the per-token build lock must not leak"


def test_eviction_never_closes_a_client_a_request_may_still_be_using(monkeypatch):
    """Closing on eviction closed sockets out from under live requests
    (`RuntimeError: Cannot send a request, as the client has been closed`)."""
    _patch_factory(monkeypatch, lambda url, key: _Client())
    in_use = SupabaseReadRepository(SETTINGS, "token-a").client
    for i in range(supabase_clients.MAX_CLIENTS + 2):
        SupabaseReadRepository(SETTINGS, f"other-{i}")

    assert "token-a" not in supabase_clients._clients, "it should be evicted"
    assert not in_use.closed, "but never closed while a request could hold it"
