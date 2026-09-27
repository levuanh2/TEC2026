"""Freeze the application's routing table once main.py has declared it.

Every route is declared at import time (router decorators, one include_router
in main.py). After `freeze_routing(app)`, no code path can add, replace or hide
a route: each router's route list becomes a tuple, and every registration
method -- including the decorators, which all go through add_api_route /
add_route -- raises. A late registration (a timer, a lifespan task, an aliased
`route = app.get`) therefore fails loudly instead of serving an operation the
auth inventory never saw (tests/test_route_auth_inventory.py asserts the
frozen state; docs/CI_PIPELINE.md, "Positive auth coverage").
"""
from __future__ import annotations

from typing import Any

FROZEN_MESSAGE = "routing is frozen: routes are declared at import time only (backend/infrastructure/route_freeze.py)"

# Everything that registers routes or startup/shutdown handlers on a Starlette
# Router / FastAPI APIRouter / FastAPI app.
_MUTATORS = (
    "add_api_route", "add_api_websocket_route", "add_route", "add_websocket_route", "include_router",
    "mount", "host", "api_route", "route", "websocket_route", "websocket", "add_event_handler", "on_event",
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
)
_LOCKED_ATTRIBUTES = {"routes", "router", "lifespan_context", "on_startup", "on_shutdown"}
_frozen_classes: dict[type, type] = {}


def _refuse(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError(FROZEN_MESSAGE)


def frozen_class(cls: type) -> type:
    """A subclass of `cls` whose registration methods raise and whose routing
    attributes cannot be rebound."""
    if cls not in _frozen_classes:
        def __setattr__(self: Any, name: str, value: Any) -> None:
            if name in _LOCKED_ATTRIBUTES:
                raise RuntimeError(FROZEN_MESSAGE)
            cls.__setattr__(self, name, value)

        namespace: dict[str, Any] = {name: _refuse for name in _MUTATORS if hasattr(cls, name)}
        namespace["__setattr__"] = __setattr__
        namespace["__frozen_routing__"] = True
        _frozen_classes[cls] = type(f"Frozen{cls.__name__}", (cls,), namespace)
    return _frozen_classes[cls]


def _routers(router: Any) -> list[Any]:
    found = [router]
    for route in router.routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found += _routers(inner)
    return found


def freeze_routing(app: Any) -> None:
    for router in _routers(app.router):
        if getattr(type(router), "__frozen_routing__", False):
            continue
        router.routes = tuple(router.routes)
        router.__class__ = frozen_class(type(router))
    if not getattr(type(app), "__frozen_routing__", False):
        app.__class__ = frozen_class(type(app))
