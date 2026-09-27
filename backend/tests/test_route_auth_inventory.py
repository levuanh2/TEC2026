"""The auth coverage manifest must classify EVERY operation the real app serves.

Runs without a database: the inventory comes from `main.app.openapi()`, the same
spec served in production. A protected route that is not in
tests/route_auth_manifest.py fails with PROTECTED_ROUTE_POSITIVE_COVERAGE_MISSING;
tests/test_route_positive_auth.py then proves each entry against a real stack.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fastapi.routing  # noqa: E402
from fastapi.routing import APIRoute, APIRouter  # noqa: E402
from starlette.routing import Route  # noqa: E402

from infrastructure.route_freeze import frozen_class  # noqa: E402
from main import app  # noqa: E402
from tests.route_auth_manifest import EXCEPTION, POSITIVE, PUBLIC, ROUTES  # noqa: E402

METHODS = {"get", "post", "put", "patch", "delete"}
# The only anonymous operations: EXC-API-01 and the liveness probe. Growing this
# set is a policy change.
DOCUMENTED_PUBLIC = {("GET", "/v1/carbon/scenarios"), ("GET", "/health")}
# FastAPI's own documentation routes: the only served routes outside the schema.
DOCS_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
# Middleware sees every request; a new one could answer requests no route owns.
MIDDLEWARE = ["CORSMiddleware", "RequestIdMiddleware"]


OPENAPI_METHODS = METHODS | {"head", "options", "trace"}


def openapi_operations() -> set[tuple[str, str]]:
    # Every HTTP method the schema lists, so an explicit HEAD/OPTIONS operation
    # cannot slip past the manifest (the manifest and the suites use METHODS only).
    return {(m.upper(), p) for p, item in app.openapi()["paths"].items() for m in item if m in OPENAPI_METHODS}


def served_operations() -> set[tuple[str, str]]:
    """Every operation the app would actually route, from its routing table (not
    from the schema): a route added with app.mount(), hidden with
    include_in_schema=False (even via setattr) or of an unknown kind fails."""
    ops: set[tuple[str, str]] = set()
    # Exact types only, never duck typing or isinstance: a subclass or an object
    # with a spoofed `original_router` attribute must not be taken for a plain route.
    included = getattr(fastapi.routing, "_IncludedRouter", None)  # FastAPI >= 0.141
    assert included is not None, "FastAPI's router wrapper moved: update this inventory walk"

    def walk(routes, prefix: str = "") -> None:
        for route in routes:
            if type(route) is included:
                context = route.include_context
                assert type(route.original_router) is frozen_class(APIRouter), \
                    "UNINVENTORIED_ROUTE: included router is not the frozen plain APIRouter"
                assert context.include_in_schema, "UNINVENTORIED_ROUTE: a router is included with include_in_schema=False"
                walk(route.original_router.routes, prefix + context.prefix)
            elif type(route) is APIRoute:
                assert route.include_in_schema, f"UNINVENTORIED_ROUTE: {route.path} is hidden from the schema"
                # Every method counts (FastAPI adds no implicit HEAD to an APIRoute):
                # an explicit HEAD/OPTIONS/TRACE route is not something the suites send.
                extra = {m for m in route.methods if m.lower() not in METHODS}
                assert not extra, f"UNINVENTORIED_ROUTE: {sorted(extra)} {route.path} -- only {sorted(METHODS)} are inventoried"
                ops.update((m, prefix + route.path) for m in route.methods)
            elif type(route) is Route and route.path in DOCS_ROUTES:
                continue
            else:
                raise AssertionError(f"UNINVENTORIED_ROUTE: {type(route).__name__} {getattr(route, 'path', '?')} "
                                     "is served outside the OpenAPI schema (mount / websocket / raw route)")

    walk(app.routes)
    return ops


def test_every_served_route_is_in_the_schema():
    assert served_operations() == openapi_operations()


def test_routes_registered_at_startup_are_inventoried_too():
    # uvicorn's lifespan protocol enters exactly this context; a custom lifespan
    # could register routes, so walk the table again inside it.
    import asyncio

    async def inside_lifespan() -> set[tuple[str, str]]:
        async with app.router.lifespan_context(app):
            return served_operations()

    assert asyncio.run(inside_lifespan()) == served_operations() == openapi_operations()
    # Deprecated on_event hooks are not reviewed here at all: forbid them.
    assert app.router.on_startup == [] and app.router.on_shutdown == [], "use no on_event startup/shutdown hooks"


def test_routing_is_frozen_after_import():
    # main.py ends with freeze_routing(app): nothing can register a route later
    # (timer, lifespan task, aliased decorator), so this inventory is final.
    from fastapi import FastAPI

    assert type(app) is frozen_class(FastAPI) and type(app.router) is frozen_class(APIRouter)
    assert isinstance(app.router.routes, tuple)
    attempts = {
        "aliased decorator": lambda: app.get("/v1/late")(lambda: None),
        "include_router": lambda: app.include_router(APIRouter()),
        "add_api_route": lambda: app.router.add_api_route("/v1/late", lambda: None),
        "mount": lambda: app.mount("/v1/late", FastAPI()),
        "routes rebinding": lambda: setattr(app.router, "routes", []),
        "router rebinding": lambda: setattr(app, "router", APIRouter()),
    }
    for label, attempt in attempts.items():
        try:
            attempt()
        except (RuntimeError, AttributeError, TypeError):
            continue
        raise AssertionError(f"UNINVENTORIED_ROUTE: routing is not frozen ({label} succeeded)")
    assert served_operations() == openapi_operations()


def test_every_module_that_declares_routes_is_loaded_at_startup():
    # A route decorator runs when its module is imported. A module first imported
    # LATE (importlib / a timer) would register routes after this inventory ran,
    # so every module declaring routes must already be loaded once `main` is.
    import ast
    import re

    route_decorator = re.compile(r"^(?:app|\w*router)\.(?:get|post|put|patch|delete|head|options|trace|api_route|websocket|route)$")
    backend = Path(__file__).resolve().parent.parent
    late = []
    for path in backend.rglob("*.py"):
        parts = path.relative_to(backend).parts
        if {"tests", "tests_strict", "scripts", ".venv"} & set(parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        declares = any(isinstance(d, ast.Call) and route_decorator.match(ast.unparse(d.func))
                       for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                       for d in node.decorator_list)
        module = ".".join(path.relative_to(backend).with_suffix("").parts).removesuffix(".__init__")
        if declares and module not in sys.modules:
            late.append(module)
    assert not late, f"UNINVENTORIED_ROUTE: modules declare routes but are not imported at startup: {late}"


def test_middleware_is_exactly_the_reviewed_set():
    assert [m.cls.__name__ for m in app.user_middleware] == MIDDLEWARE


def test_every_protected_operation_has_positive_auth_coverage():
    ops = openapi_operations()
    assert len(ops) >= 50, "route inventory is suspiciously small"
    missing = sorted(ops - set(ROUTES))
    assert not missing, (
        "PROTECTED_ROUTE_POSITIVE_COVERAGE_MISSING: add each to tests/route_auth_manifest.py and drive it in "
        f"tests/test_route_positive_auth.py: {missing}")


def test_the_manifest_has_no_stale_entries():
    stale = sorted(set(ROUTES) - openapi_operations())
    assert not stale, f"ROUTE_MANIFEST_STALE: not in the app's OpenAPI any more: {stale}"


def test_public_operations_are_exactly_the_documented_ones():
    public = {k for k, r in ROUTES.items() if r.kind == PUBLIC}
    assert public == DOCUMENTED_PUBLIC
    assert all(ROUTES[k].reason for k in public)


def test_classifications_are_strict():
    for key, route in ROUTES.items():
        assert route.kind in {PUBLIC, POSITIVE, EXCEPTION}, key
        if route.kind == PUBLIC:
            continue
        assert route.persona in {"manager", "farmer"}, key
        assert route.expect, f"{key}: no expected status"
        assert 401 not in route.expect, f"{key}: a valid token must never be expected to get 401"
        if route.kind == POSITIVE:
            # A success path, not "any answer": 404/409/422 do not count as covered.
            assert route.expect <= {200, 201, 204}, f"{key}: POSITIVE must expect success, got {sorted(route.expect)}"
        else:
            assert route.reason.startswith("EXC-AUTH-"), f"{key}: EXCEPTION needs a documented EXC-AUTH id"
        assert route.deny in {None, "outsider"}, key


def test_every_write_operation_has_a_true_success_path():
    # Business writes (POST/PATCH/PUT/DELETE) are never an auth-layer-only EXCEPTION.
    writes = {k for k in ROUTES if k[0] != "GET" and ROUTES[k].kind != PUBLIC}
    not_positive = sorted(k for k in writes if ROUTES[k].kind != POSITIVE)
    assert not not_positive, f"write operations without a true success path: {not_positive}"
