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
from infrastructure import read_repo  # noqa: E402
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
    # The fake ignores `options`, so building a real pooled httpx client for it
    # is pure cost (a few hundred ms per fake, and a socket pool nothing closes).
    monkeypatch.setattr(supabase_clients, "_transport", lambda: None)
    import supabase

    monkeypatch.setattr(supabase, "create_client", make)


def test_same_token_reuses_one_client(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())
    first = SupabaseReadRepository(SETTINGS, "token-a")
    second = SupabaseReadRepository(SETTINGS, "token-a")
    assert first.client is second.client
    assert _Client.created == 1


def test_a_different_token_never_borrows_another_callers_client(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())
    a = SupabaseReadRepository(SETTINGS, "token-a")
    b = SupabaseReadRepository(SETTINGS, "token-b")
    assert a.client is not b.client
    assert a.client.bound_token == "token-a"
    assert b.client.bound_token == "token-b"


def test_a_cached_client_is_never_rebound_to_a_second_token(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())
    SupabaseReadRepository(SETTINGS, "token-a")
    reused = SupabaseReadRepository(SETTINGS, "token-a")
    # Re-authenticating a reused client is what would let one caller's pool
    # answer for another; construction must bind exactly once.
    assert reused.client.bound_token == "token-a"


def test_client_cache_is_bounded(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())
    for i in range(supabase_clients.MAX_CLIENTS + 5):
        SupabaseReadRepository(SETTINGS, f"token-{i}")
    assert len(supabase_clients._clients) <= supabase_clients.MAX_CLIENTS


def test_dropped_connection_is_retried_once_on_a_fresh_client(monkeypatch):
    clients: list[_Client] = []

    def make(url, key, **_kw):
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
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client(rows={"farms": [], "plots": [], "crop_seasons": []}))
    profile = profiling.start()
    SupabaseReadRepository(SETTINGS, "token-a").farmer_scope()
    assert profile.calls == 3, "reads issued from worker threads must still be attributed"
    assert {label for label, _, _ in profile.top()} == {
        "select farms", "select plots", "select crop_seasons",
    }


def test_profiler_is_inert_outside_a_request(monkeypatch):
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())
    profiling._current.set(None)
    SupabaseReadRepository(SETTINGS, "token-a")._many("farms")  # must not raise


def test_concurrent_first_reads_of_one_token_build_a_single_client(monkeypatch):
    """A Farmer page load fires /me and /farmer/scope at the same instant. On a
    brand-new token both would otherwise build their own ~450ms client and all
    but one would be thrown away — measured as /v1/me going 1686ms -> 2546ms at
    login when the second read was added."""
    import threading

    started = threading.Barrier(3)

    def make(url, key, **_kw):
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
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())
    in_use = SupabaseReadRepository(SETTINGS, "token-a").client
    for i in range(supabase_clients.MAX_CLIENTS + 2):
        SupabaseReadRepository(SETTINGS, f"other-{i}")

    assert "token-a" not in supabase_clients._clients, "it should be evicted"
    assert not in_use.closed, "but never closed while a request could hold it"


def test_access_checker_never_runs_one_callers_query_with_another_callers_token(monkeypatch):
    """Two concurrent callers must not be able to interleave
    `auth(A) -> auth(B) -> execute(A)` on one shared client."""
    from infrastructure.auth import SupabaseCropAccessChecker

    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client(rows={"crop_seasons": [{"id": "s1"}]}))
    checker = SupabaseCropAccessChecker(SETTINGS)
    checker.assert_can_access("token-a", "s1")
    checker.assert_can_access("token-b", "s1")

    bound = {client.bound_token for _, client in supabase_clients._clients.values()}
    assert bound == {"token-a", "token-b"}, "each caller must get its own bound client"
    assert len(supabase_clients._clients) == 2


def test_renew_takes_the_replacement_another_caller_already_built(monkeypatch):
    """Supabase speaks HTTP/2, so one connection carries every read a request
    issues concurrently: when the server closes it, all of them fail at once and
    all of them ask for a new client. Only the first replaces it — the rest must
    take that replacement, not each build (and cache, and evict) another ~450ms
    client while the previous thread is still using it."""
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())

    original = supabase_clients.client_for_token(SETTINGS, "token-a")
    first = supabase_clients.renew(SETTINGS, "token-a", original)
    second = supabase_clients.renew(SETTINGS, "token-a", original)
    third = supabase_clients.renew(SETTINGS, "token-a", original)

    assert first is not original, "the dead client must be replaced once"
    assert second is first and third is first, "later failures reuse that replacement"
    assert _Client.created == 2, "exactly one replacement was built"


def test_renew_still_replaces_a_client_that_is_the_current_one(monkeypatch):
    """A later, unrelated failure of the replacement must replace it in turn."""
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client())

    first = supabase_clients.client_for_token(SETTINGS, "token-a")
    second = supabase_clients.renew(SETTINGS, "token-a", first)
    third = supabase_clients.renew(SETTINGS, "token-a", second)

    assert third is not second and second is not first
    assert _Client.created == 3


def test_a_burst_of_dropped_connections_is_ridden_out(monkeypatch):
    """One close can take down every read multiplexed on an HTTP/2 connection,
    and the replacement's first request can be caught by the same burst. A
    single retry left ~1% of reads failing against hosted Supabase."""
    made: list[_Client] = []

    def make(url, key, **_kw):
        # The first two clients are doomed, the third works.
        client = _Client(rows={"farms": [{"id": "f1"}]}, fail_times=1 if len(made) < 2 else 0)
        made.append(client)
        return client

    _patch_factory(monkeypatch, make)
    repo = SupabaseReadRepository(SETTINGS, "token-a")

    assert repo._many("farms") == [{"id": "f1"}]
    assert len(made) == 3


def test_retries_are_bounded_so_a_real_outage_still_surfaces(monkeypatch):
    """Retrying forever would turn a Supabase outage into a hung request."""
    _patch_factory(monkeypatch, lambda url, key, **_kw: _Client(fail_times=99))
    repo = SupabaseReadRepository(SETTINGS, "token-a")

    with pytest.raises(httpx.RemoteProtocolError):
        repo._many("farms")
    assert _Client.created == read_repo._READ_ATTEMPTS


def test_pooled_clients_avoid_http2_multiplexing_and_keep_a_real_timeout():
    """These clients are shared by all of one caller's in-flight requests.

    Over HTTP/2 httpx would put every one of them on a single multiplexed
    connection: `httpcore`'s sync HTTP/2 connection then lost track of a stream
    and raised `KeyError: <stream id>` out of `_response_closed`, and one
    server-side close took down every read on it at once. Plain keep-alive
    HTTP/1.1 gives each concurrent read its own connection and still skips the
    TLS handshake, which is where the time was.

    The timeout is asserted too: supplying a custom httpx client replaces
    postgrest-py's 120s default with httpx's 5s one, and hosted rollup reads
    legitimately take longer than that.
    """
    transport = supabase_clients._transport()
    try:
        assert getattr(transport, "_transport", None) is not None
        assert transport.timeout.read == supabase_clients.REQUEST_TIMEOUT_SECONDS
        assert transport.timeout.connect == supabase_clients.REQUEST_TIMEOUT_SECONDS
        # http2 off -> httpcore opens one connection per concurrent request
        pool = transport._transport._pool
        assert pool._http2 is False
        assert pool._max_connections == supabase_clients.MAX_CONNECTIONS
    finally:
        transport.close()
