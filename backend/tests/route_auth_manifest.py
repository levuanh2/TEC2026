"""Auth coverage manifest: every operation the app serves (its OpenAPI), classified.

    PUBLIC    no token needed (documented exception, answered 200 anonymously)
    POSITIVE  a real authenticated persona gets the documented SUCCESS status on a
              deterministic fixture (tests/test_route_positive_auth.py drives it
              over HTTP against the local Supabase stack)
    EXCEPTION a full success path is impractical in CI; a valid JWT must still pass
              the authentication layer and get exactly the documented status --
              never 401 / `unauthenticated` / `missing_authorization`

`deny` names a persona that must get a canonical denial (403/404) on the same
request: an active manager of ANOTHER cooperative (cross-tenant). Unauthenticated
401 is asserted for every protected operation by the same suite.

tests/test_route_auth_inventory.py fails with PROTECTED_ROUTE_POSITIVE_COVERAGE_MISSING
when an operation is missing here, and rejects stale entries, a non-2xx POSITIVE
expectation, and an EXCEPTION that tolerates 401. Adding an entry is not enough:
the positive suite fails unless it actually executes that request.
This file is a guarded path (policy.json): changes need review.
"""
from __future__ import annotations

from dataclasses import dataclass

PUBLIC = "PUBLIC"
POSITIVE = "POSITIVE"
EXCEPTION = "EXCEPTION"


@dataclass(frozen=True)
class Route:
    kind: str
    persona: str | None = None       # manager | farmer
    expect: frozenset[int] = frozenset()
    deny: str | None = None          # persona that must be refused (403/404)
    reason: str = ""                 # required for PUBLIC and EXCEPTION


def ok(persona: str, *statuses: int, deny: str | None = None) -> Route:
    return Route(POSITIVE, persona, frozenset(statuses), deny)


M, F, X = "manager", "farmer", "outsider"

ROUTES: dict[tuple[str, str], Route] = {
    # -- public ------------------------------------------------------------
    ("GET", "/v1/carbon/scenarios"): Route(PUBLIC, reason="EXC-API-01: static scenario names, no tenant data"),
    ("GET", "/health"): Route(PUBLIC, reason="liveness probe for Render; reads the factor YAML, no tenant data"),

    # -- identity / organizations (manager) ----------------------------------
    ("GET", "/v1/me"): ok(M, 200),
    ("GET", "/v1/organizations"): ok(M, 200),
    ("GET", "/v1/organizations/{organization_id}"): ok(M, 200, deny=X),
    ("GET", "/v1/organizations/{organization_id}/farms"): ok(M, 200),
    ("POST", "/v1/organizations/{organization_id}/farms"): ok(M, 201, deny=X),
    ("GET", "/v1/organizations/{organization_id}/summary"): ok(M, 200),
    ("GET", "/v1/organizations/{organization_id}/metrics"): ok(M, 200),
    ("GET", "/v1/organizations/{organization_id}/farm-performance"): ok(M, 200),
    ("GET", "/v1/organizations/{organization_id}/plots-seasons"): ok(M, 200, deny=X),
    ("GET", "/v1/organizations/{organization_id}/farmers"): ok(M, 200, deny=X),
    ("POST", "/v1/organizations/{organization_id}/farmers"): ok(M, 201, deny=X),

    # -- farms / plots (farmer, provisioned through the API) ------------------
    ("GET", "/v1/farmer/scope"): ok(F, 200),
    ("GET", "/v1/farms"): ok(F, 200),
    ("GET", "/v1/farms/{farm_id}"): ok(F, 200, deny=X),
    ("GET", "/v1/farms/{farm_id}/plots"): ok(F, 200),
    ("POST", "/v1/farms/{farm_id}/plots"): ok(M, 201, deny=X),  # cooperative manager only (official plot structure)
    ("GET", "/v1/farms/{farm_id}/crop-seasons"): ok(F, 200),
    ("GET", "/v1/farms/{farm_id}/metrics"): ok(F, 200),
    ("GET", "/v1/plots/{plot_id}"): ok(F, 200, deny=X),
    ("GET", "/v1/plots/{plot_id}/crop-seasons"): ok(F, 200),

    # -- crop season lifecycle ------------------------------------------------
    ("POST", "/v1/plots/{plot_id}/crop-seasons"): ok(F, 201, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}"): ok(F, 200, deny=X),
    ("PATCH", "/v1/crop-seasons/{crop_season_id}/methodology"): ok(F, 200, deny=X),
    ("PATCH", "/v1/crop-seasons/{crop_season_id}/status"): ok(F, 200, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}/production-batches"): ok(F, 200),
    ("GET", "/v1/production-batches/{production_batch_id}"): ok(F, 200, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}/metrics"): ok(F, 200),

    # -- activities -------------------------------------------------------------
    ("POST", "/v1/crop-seasons/{crop_season_id}/activities"): ok(F, 201, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}/activities"): ok(F, 200),
    ("GET", "/v1/activities/{activity_id}"): ok(F, 200, deny=X),
    ("PATCH", "/v1/activities/{activity_id}"): ok(F, 200, deny=X),
    ("DELETE", "/v1/activities/{activity_id}"): ok(F, 204, deny=X),

    # -- Carbon -----------------------------------------------------------------
    ("GET", "/v1/crop-seasons/{crop_season_id}/carbon/readiness"): ok(F, 200, deny=X),
    ("POST", "/v1/carbon/calculate"): ok(F, 200, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}/carbon"): ok(F, 200, deny=X),
    ("GET", "/v1/organizations/{organization_id}/carbon-status"): ok(M, 200, deny=X),

    # -- recommendations --------------------------------------------------------
    ("POST", "/v1/crop-seasons/{crop_season_id}/recommendations/generate"): ok(F, 200, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}/recommendations"): ok(F, 200),
    ("PATCH", "/v1/recommendations/{recommendation_id}"): ok(F, 200, deny=X),

    # -- CV -----------------------------------------------------------------------
    # CI has no trained checkpoint (ml/runs is not committed); the suite injects an
    # untrained model of the same architecture, so auth, scope, upload, storage and
    # the DB rows are all real -- only the prediction itself is meaningless.
    ("POST", "/v1/crop-seasons/{crop_season_id}/cv/infer"): ok(F, 200, deny=X),
    ("GET", "/v1/crop-seasons/{crop_season_id}/cv/inferences"): ok(F, 200),
    ("GET", "/v1/cv/inferences/{inference_id}"): ok(F, 200, deny=X),

    # -- MRV (manager) ------------------------------------------------------------
    ("GET", "/v1/mrv/cases"): ok(M, 200),
    ("GET", "/v1/mrv/cases/{mrv_case_id}"): ok(M, 200, deny=X),
    ("GET", "/v1/mrv/cases/{mrv_case_id}/steps"): ok(M, 200),
    ("GET", "/v1/mrv/cases/{mrv_case_id}/batches"): ok(M, 200),
    ("GET", "/v1/mrv/cases/{mrv_case_id}/evidence"): ok(M, 200),
    ("GET", "/v1/mrv/cases/{mrv_case_id}/exports"): ok(M, 200),
    ("POST", "/v1/mrv/cases/{mrv_case_id}/exports"): ok(M, 201, deny=X),
    ("GET", "/v1/mrv/exports/{mrv_export_id}"): ok(M, 200, deny=X),
    ("POST", "/v1/mrv/exports/{mrv_export_id}/render"): ok(M, 201, deny=X),
    ("GET", "/v1/mrv/exports/{mrv_export_id}/download"): ok(M, 200, deny=X),

    # -- emission factors (reference data, any signed-in user) ------------------
    ("GET", "/v1/emission-factor-sets"): ok(F, 200),
    ("GET", "/v1/emission-factor-sets/{emission_factor_set_id}"): ok(F, 200),
    ("GET", "/v1/emission-factor-sets/{emission_factor_set_id}/factors"): ok(F, 200),
}
