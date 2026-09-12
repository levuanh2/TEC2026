"""Per-caller Supabase client reuse.

Building a `supabase` client and binding a JWT to it costs ~450ms, and the
fresh connection pool that comes with it makes that request's first PostgREST
query pay a full TLS handshake on top (measured on hosted Supabase: ~390ms
cold vs ~150ms on a warm pool). Doing that once per HTTP request put roughly
800ms of pure overhead on every Farmer read — the single largest fixed cost
after recommendation generation.

A client here is nothing but a connection pool plus one fixed `Authorization`
header, so reuse is keyed on the **exact** access token: two requests carrying
the same token are indistinguishable to PostgREST, which validates that token
server-side on every single request and applies RLS from it. A cached client
is therefore never able to answer for a different caller than the one whose
token produced it — there is no ambient/service-role identity to leak into,
and a token that has expired is rejected by Supabase exactly as before.

The cache is bounded and time-limited so tokens (and their sockets) cannot
accumulate in a long-lived process.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from .config import Settings

MAX_CLIENTS = 32
TTL_SECONDS = 600.0

_lock = threading.Lock()
_clients: OrderedDict[str, tuple[float, Any]] = OrderedDict()
# One build at a time per token: the first read of a brand-new token is
# normally accompanied by two or three more fired at the same moment (a Farmer
# page load asks for /me and /farmer/scope together), and without this each of
# them would build its own ~450ms client just to have all but one thrown away.
_building: dict[str, threading.Lock] = {}


def _close(client: Any) -> None:
    """Close a client's sockets. Only safe when nothing can still be using it."""
    for owner in (getattr(client, "postgrest", None), getattr(client, "auth", None)):
        session = getattr(owner, "session", None)
        close = getattr(session, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001 - teardown must never fail a request
                pass


def _evict_locked(now: float) -> None:
    """Forget expired//overflow entries WITHOUT closing them.

    A request that already took a client out of this cache keeps using it for
    the rest of its work, so closing on eviction closed sockets out from under
    live requests — observed directly as `RuntimeError: Cannot send a request,
    as the client has been closed` 500ing a Farmer page section whenever an
    eviction happened to land mid-request. Dropping the reference is enough:
    the last request still holding it releases it when it finishes, and the
    sockets go with it.
    """
    for token, (created, _client) in list(_clients.items()):
        if now - created >= TTL_SECONDS:
            del _clients[token]
    while len(_clients) > MAX_CLIENTS:
        _clients.popitem(last=False)


def _cached(token: str) -> Any | None:
    with _lock:
        entry = _clients.get(token)
        if entry is not None and time.monotonic() - entry[0] < TTL_SECONDS:
            _clients.move_to_end(token)
            return entry[1]
    return None


def client_for_token(settings: Settings, token: str) -> Any:
    """A JWT-bound client for `token`, reused while it is fresh.

    The token is bound once, at construction: a cached client is never
    re-authenticated with a different token, so one caller's client can never
    be handed to another.
    """
    client = _cached(token)
    if client is not None:
        return client

    with _lock:
        build_lock = _building.setdefault(token, threading.Lock())

    try:
        with build_lock:
            client = _cached(token)  # another thread may have built it while we waited
            if client is not None:
                return client
            from supabase import create_client

            url, key = settings.require_publishable()
            client = create_client(url, key)
            client.postgrest.auth(token)
            now = time.monotonic()
            with _lock:
                _clients[token] = (now, client)
                _clients.move_to_end(token)
                _evict_locked(now)
            return client
    finally:
        # Also on failure, so a build that raised cannot pin an entry here.
        with _lock:
            _building.pop(token, None)


def renew(settings: Settings, token: str) -> Any:
    """Drop the cached client for `token` and build a fresh one.

    Used when a pooled keep-alive connection turns out to have been closed by
    Supabase: the dead pool is discarded rather than handed to the next reader.
    """
    with _lock:
        _clients.pop(token, None)  # dropped, not closed — see `_evict_locked`
    return client_for_token(settings, token)



def clear() -> None:
    """Drop every cached client. Closes them, so only call it when no request
    is in flight (tests, shutdown)."""
    with _lock:
        _building.clear()
        clients = [client for _, client in _clients.values()]
        _clients.clear()
    for client in clients:
        _close(client)
