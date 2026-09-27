"""The auth coverage manifest must classify EVERY /v1 operation of the real app.

Runs without a database: the inventory comes from `main.app.openapi()`, the same
spec served in production. A protected route that is not in
tests/route_auth_manifest.py fails with PROTECTED_ROUTE_POSITIVE_COVERAGE_MISSING;
tests/test_route_positive_auth.py then proves each entry against a real stack.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from tests.route_auth_manifest import EXCEPTION, POSITIVE, PUBLIC, ROUTES  # noqa: E402

METHODS = {"get", "post", "put", "patch", "delete"}
# The only anonymous /v1 operation (EXC-API-01). Growing this set is a policy change.
DOCUMENTED_PUBLIC = {("GET", "/v1/carbon/scenarios")}


def openapi_operations() -> set[tuple[str, str]]:
    return {(m.upper(), p) for p, item in app.openapi()["paths"].items() if p.startswith("/v1")
            for m in item if m in METHODS}


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
