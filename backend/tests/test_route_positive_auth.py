"""Positive + negative auth for EVERY protected route, over real HTTP and real JWTs.

A route that rejects every caller (always 401 / `missing_authorization`) passes a
"no token -> 401" sweep. This suite closes that gap: on the isolated local
Supabase stack it builds a disposable tenant and drives each operation in
tests/route_auth_manifest.py as a genuinely signed-in persona, through the same
`main.app` production serves:

  * the persona gets the manifest's SUCCESS status (writes really write: season,
    batch, activities, Carbon result, recommendation, MRV export ...);
  * the same request without a token is 401;
  * where the manifest names `deny`, an active manager of ANOTHER cooperative
    gets a canonical denial (403/404) -- and that attempt runs first, so a leak
    would show up as a changed resource, not only a status.

Users are created through the Auth Admin API with random passwords and signed in
with the password grant (real GoTrue JWTs, nothing minted). Setup uses the
service role only where the API has no endpoint (the tenant, its managers, the
MRV case and one CV inference row). Everything is deleted afterwards.
"""
from __future__ import annotations

import io
import sys
import uuid
from collections import defaultdict
from datetime import date
from urllib.parse import urlparse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402
from tests.route_auth_manifest import EXCEPTION, POSITIVE, ROUTES  # noqa: E402

_SETTINGS = load_settings()
_DB_URL = _SETTINGS.supabase_db_url
_LOCAL = {"127.0.0.1", "localhost"}
# This suite creates users and writes a whole tenant: it never runs against a
# hosted project (e.g. a developer's backend/.env). That skip reason is NOT on
# any CI skip allowlist, so a CI job misconfigured to a remote stack fails.
_REMOTE = bool(_DB_URL) and not (urlparse(_DB_URL).hostname in _LOCAL
                                 and urlparse(_SETTINGS.supabase_url or "").hostname in _LOCAL)
pytestmark = [
    pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured."),
    pytest.mark.skipif(_REMOTE, reason="refusing: the positive auth suite only runs against a LOCAL Supabase stack"),
]

AUTH_CODES = {"unauthenticated", "missing_authorization"}
DENIAL = {403, 404}
PROTECTED = sorted(k for k, r in ROUTES.items() if r.kind in {POSITIVE, EXCEPTION})


def _code(response) -> str | None:
    try:
        return response.json()["detail"]["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


class Journey:
    """Runs every request and records (who, status, code) per manifest key."""

    def __init__(self, client, tokens: dict[str, str]):
        self.client = client
        self.tokens = tokens
        self.calls: dict[tuple[str, str], list[tuple[str, int, str | None]]] = defaultdict(list)

    def _send(self, who: str | None, method: str, path: str, json=None, files=None):
        headers = {"Authorization": f"Bearer {self.tokens[who]}"} if who else {}
        return self.client.request(method, path, headers=headers, json=json, files=files)

    def call(self, method: str, template: str, *, json=None, files=None, **params):
        key = (method, template)
        route = ROUTES[key]
        path = template.format(**params)
        if not self.calls[key]:
            r = self._send(None, method, path, json, files() if files else None)
            self.calls[key].append(("anonymous", r.status_code, _code(r)))
            if route.deny:
                r = self._send(route.deny, method, path, json, files() if files else None)
                self.calls[key].append((route.deny, r.status_code, _code(r)))
        r = self._send(route.persona, method, path, json, files() if files else None)
        self.calls[key].append((route.persona, r.status_code, _code(r)))
        assert r.status_code in route.expect, f"{method} {path} as {route.persona}: {r.status_code} {r.text[:300]}"
        return r


def _run(journey: Journey, fx: dict) -> None:
    j, org = journey.call, fx["org"]
    tag = fx["tag"]

    # -- manager: identity, organization, provisioning ---------------------------
    assert any(m["organization_id"] == org for m in j("GET", "/v1/me").json()["organization_memberships"])
    assert org in j("GET", "/v1/organizations").text
    j("GET", "/v1/organizations/{organization_id}", organization_id=org)
    prov = j("POST", "/v1/organizations/{organization_id}/farmers", organization_id=org, json={
        "full_name": f"{tag} farmer", "email": fx["farmer_email"],
        "farm": {"farm_code": f"{tag}-FARM", "farm_name": f"{tag} farm"},
        "plot": {"plot_code": f"{tag}-PLOT", "name": f"{tag} plot", "area_ha": 1.0},
    }).json()
    fx["users"].append(prov["user_id"])
    journey.tokens["farmer"] = fx["sign_in"](fx["farmer_email"], prov["temporary_password"])
    farm, plot = prov["farm_id"], prov["plot_id"]
    assert prov["user_id"] in j("GET", "/v1/organizations/{organization_id}/farmers", organization_id=org).text
    farm2 = j("POST", "/v1/organizations/{organization_id}/farms", organization_id=org, json={
        "farm_code": f"{tag}-FARM2", "farm_name": f"{tag} farm 2", "owner_user_id": prov["user_id"]}).json()["id"]
    assert farm2 in j("GET", "/v1/organizations/{organization_id}/farms", organization_id=org).text
    for suffix in ("summary", "metrics", "farm-performance"):
        j("GET", "/v1/organizations/{organization_id}/" + suffix, organization_id=org)

    # -- farmer: farms and plots ---------------------------------------------------
    assert farm in j("GET", "/v1/farmer/scope").text
    assert farm in j("GET", "/v1/farms").text
    j("GET", "/v1/farms/{farm_id}", farm_id=farm)
    plot2 = j("POST", "/v1/farms/{farm_id}/plots", farm_id=farm2,
              json={"plot_code": f"{tag}-PLOT2", "name": f"{tag} plot 2", "area_ha": 0.5}).json()["id"]
    assert plot in j("GET", "/v1/farms/{farm_id}/plots", farm_id=farm).text
    j("GET", "/v1/plots/{plot_id}", plot_id=plot2)

    # -- crop season + default batch ----------------------------------------------
    season_body = {"season_code": f"{tag}-S1", "planting_date": "2026-05-01", "variety_name": "OM5451"}
    season = j("POST", "/v1/plots/{plot_id}/crop-seasons", plot_id=plot, json=season_body).json()
    sid, batch = season["id"], season["default_production_batch_id"]
    assert season["status"] == "active" and batch
    assert sid in j("GET", "/v1/farms/{farm_id}/crop-seasons", farm_id=farm).text
    assert sid in j("GET", "/v1/plots/{plot_id}/crop-seasons", plot_id=plot).text
    j("GET", "/v1/crop-seasons/{crop_season_id}", crop_season_id=sid)
    assert batch in j("GET", "/v1/crop-seasons/{crop_season_id}/production-batches", crop_season_id=sid).text
    j("GET", "/v1/production-batches/{production_batch_id}", production_batch_id=batch)
    methodology = j("PATCH", "/v1/crop-seasons/{crop_season_id}/methodology", crop_season_id=sid, json={
        "ipcc_water_regime": "irrigated_continuous_flooding",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d", "cultivation_days": 100}).json()
    assert methodology["ipcc_water_regime"] == "irrigated_continuous_flooding"

    # -- activities: the Carbon inputs, plus one edited and one deleted -----------
    def activity(kind: str, day: str, data: dict) -> str:
        return j("POST", "/v1/crop-seasons/{crop_season_id}/activities", crop_season_id=sid, json={
            "idempotency_key": str(uuid.uuid4()), "activity_type": kind,
            "occurred_at": f"2026-06-{day}T06:00:00+07:00", "note": tag, "data": data}).json()["id"]

    activity("irrigation", "02", {"method": "continuous_flooding", "water_volume_m3": 4000})
    activity("fertilizer", "05", {"fertilizer_name": "Urea", "amount_kg": 100, "nitrogen_percent": 46})
    activity("harvest", "20", {"yield_kg": 6000})
    extra = activity("irrigation", "10", {"method": "continuous_flooding", "water_volume_m3": 10})
    assert extra in j("GET", "/v1/crop-seasons/{crop_season_id}/activities", crop_season_id=sid).text
    summary = j("GET", "/v1/crop-seasons/{crop_season_id}/activity-summary", crop_season_id=sid).json()
    assert summary["crop_season_id"] == sid and summary["total"] >= 1
    j("GET", "/v1/activities/{activity_id}", activity_id=extra)
    assert j("PATCH", "/v1/activities/{activity_id}", activity_id=extra, json={"note": f"{tag} edited"}).json()["note"] == f"{tag} edited"
    j("DELETE", "/v1/activities/{activity_id}", activity_id=extra)
    assert extra not in journey._send("farmer", "GET", f"/v1/crop-seasons/{sid}/activities").text
    j("GET", "/v1/crop-seasons/{crop_season_id}/metrics", crop_season_id=sid)
    j("GET", "/v1/farms/{farm_id}/metrics", farm_id=farm)

    # -- Carbon ---------------------------------------------------------------------
    j("GET", "/v1/crop-seasons/{crop_season_id}/carbon/readiness", crop_season_id=sid)
    calc = j("POST", "/v1/carbon/calculate", json={"crop_season_id": sid}).json()
    assert calc["calculation_id"] and calc["co2e_total_kg"] is not None
    assert calc["calculation_id"] in j("GET", "/v1/crop-seasons/{crop_season_id}/carbon", crop_season_id=sid).text
    listing = j("GET", "/v1/organizations/{organization_id}/plots-seasons", organization_id=org).json()["items"]
    assert sid in [s["id"] for farm_item in listing for s in farm_item["crop_seasons"]]
    status = j("GET", "/v1/organizations/{organization_id}/carbon-status", organization_id=org).json()["items"]
    assert calc["calculation_id"] in [(i["actual"] or {}).get("calculation_id") for i in status if i["crop_season_id"] == sid]

    # -- recommendations (continuous flooding -> the AWD rule fires) ---------------
    recs = j("POST", "/v1/crop-seasons/{crop_season_id}/recommendations/generate", crop_season_id=sid).json()["items"]
    assert recs, "no recommendation generated for a continuous-flooding season"
    assert recs[0]["id"] in j("GET", "/v1/crop-seasons/{crop_season_id}/recommendations", crop_season_id=sid).text
    updated = j("PATCH", "/v1/recommendations/{recommendation_id}", recommendation_id=recs[0]["id"], json={"status": "accepted"})
    assert updated.json()["status"] == "accepted"

    # -- CV --------------------------------------------------------------------------
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(80, 140, 70)).save(buf, format="PNG")
    png = buf.getvalue()
    inference = j("POST", "/v1/crop-seasons/{crop_season_id}/cv/infer", crop_season_id=sid,
                  files=lambda: {"file": ("leaf.png", io.BytesIO(png), "image/png")}).json()["id"]
    assert inference in j("GET", "/v1/crop-seasons/{crop_season_id}/cv/inferences", crop_season_id=sid).text
    j("GET", "/v1/cv/inferences/{inference_id}", inference_id=inference)

    # -- MRV (manager) -----------------------------------------------------------------
    case = fx["mrv_case"](batch)
    assert case in j("GET", "/v1/mrv/cases").text
    j("GET", "/v1/mrv/cases/{mrv_case_id}", mrv_case_id=case)
    for suffix in ("steps", "batches", "evidence"):
        j("GET", "/v1/mrv/cases/{mrv_case_id}/" + suffix, mrv_case_id=case)
    grouped = j("GET", "/v1/organizations/{organization_id}/mrv-batches", organization_id=org).json()["items"]
    assert batch in [b["production_batch_id"] for c in grouped if c["case_id"] == case for b in c["batches"]]
    export = j("POST", "/v1/mrv/cases/{mrv_case_id}/exports", mrv_case_id=case, json={"format": "json"}).json()
    export_id = export["export_id"]
    assert export_id in j("GET", "/v1/mrv/cases/{mrv_case_id}/exports", mrv_case_id=case).text
    j("GET", "/v1/mrv/exports/{mrv_export_id}", mrv_export_id=export_id)
    j("POST", "/v1/mrv/exports/{mrv_export_id}/render", mrv_export_id=export_id, json={"format": "xlsx"})
    assert j("GET", "/v1/mrv/exports/{mrv_export_id}/download", mrv_export_id=export_id).content

    # -- emission factors ---------------------------------------------------------------
    sets = j("GET", "/v1/emission-factor-sets").json()["items"]
    assert sets
    j("GET", "/v1/emission-factor-sets/{emission_factor_set_id}", emission_factor_set_id=sets[0]["id"])
    assert j("GET", "/v1/emission-factor-sets/{emission_factor_set_id}/factors", emission_factor_set_id=sets[0]["id"]).json()["items"]

    # -- end the season last: afterwards the journal is read-only --------------------------
    ended = j("PATCH", "/v1/crop-seasons/{crop_season_id}/status", crop_season_id=sid,
              json={"status": "harvested", "actual_harvest_date": date(2026, 6, 20).isoformat()})
    assert ended.json()["status"] == "harvested"


@pytest.fixture(scope="module")
def journey():
    if not _DB_URL:
        pytest.skip("SUPABASE_DB_URL is not configured.")
    if _REMOTE:  # never create users or data on a hosted project, whatever the markers say
        pytest.skip("refusing: the positive auth suite only runs against a LOCAL Supabase stack")
    import httpx
    from fastapi.testclient import TestClient
    from supabase import create_client

    from main import app

    url, service = _SETTINGS.require_supabase()
    _, publishable = _SETTINGS.require_publishable()
    admin = create_client(url, service)
    run = uuid.uuid4().hex[:8]
    tag = f"AUTHCOV-{run}"
    email = lambda label: f"authcov-{run}-{label}@agricarbon-ci.invalid"  # noqa: E731
    fx: dict = {"tag": tag, "users": [], "orgs": [], "farmer_email": email("farmer")}

    def sign_in(address: str, password: str) -> str:
        r = httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": publishable},
                       json={"email": address, "password": password}, timeout=30)
        r.raise_for_status()
        return r.json()["access_token"]

    def manager_of(org_code: str, label: str) -> tuple[str, str]:
        org = admin.table("organizations").insert(
            {"organization_code": org_code, "name": org_code, "organization_type": "cooperative"}).execute().data[0]["id"]
        fx["orgs"].append(org)
        password = f"Ac-{uuid.uuid4().hex}!9"
        user = admin.auth.admin.create_user({"email": email(label), "password": password, "email_confirm": True}).user
        fx["users"].append(user.id)
        admin.table("organization_memberships").insert(
            {"organization_id": org, "user_id": user.id, "role": "cooperative_manager"}).execute()
        return org, sign_in(email(label), password)

    def mrv_case(batch: str) -> str:
        case = admin.table("mrv_cases").insert({
            "organization_id": fx["org"], "case_code": f"{tag}-CASE", "name": f"{tag} case",
            "period_start": "2026-05-01", "period_end": "2026-09-30", "status": "draft"}).execute().data[0]["id"]
        admin.table("mrv_case_batches").insert({"mrv_case_id": case, "production_batch_id": batch}).execute()
        return case

    fx.update(sign_in=sign_in, mrv_case=mrv_case)
    tokens: dict[str, str] = {}
    # CI has no trained checkpoint, so main.py leaves CV at 503. Inject a CvService
    # with an UNTRAINED model of the production architecture and the REAL Postgres
    # repository: auth, farmer scope, upload validation, Storage and DB rows are
    # the production path; only the prediction is meaningless. The DB job always
    # installs torch, so a missing torch fails here instead of skipping.
    import api
    from infrastructure.cv_repo import PostgresCvRepository
    from ml.model import build_model
    from service import CvService

    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    cv_meta = {"version_code": f"authcov-{run}", "model_name": "authcov-untrained", "test_dataset_name": "none",
               "test_dataset_version": None, "test_sample_count": 1, "accuracy": 0.0,
               "confusion_matrix": {}, "confidence_threshold": 0.5, "source_reference": "tests/test_route_positive_auth.py"}
    cv = CvService(model, {"image_size": 224, "run_name": f"authcov-{run}"}, 0.5, 1.0, cv_meta, PostgresCvRepository(_SETTINGS))
    previous_cv = app.dependency_overrides.get(api._cv_service)
    app.dependency_overrides[api._cv_service] = lambda: cv
    fx["cv_version_code"] = cv_meta["version_code"]
    try:
        fx["org"], tokens["manager"] = manager_of(f"{tag}-ORG", "manager")
        _, tokens["outsider"] = manager_of(f"{tag}-OTHER", "outsider")
        j = Journey(TestClient(app, raise_server_exceptions=False), tokens)
        failure = None
        try:
            _run(j, fx)
        except Exception as exc:  # noqa: BLE001 -- recorded; each manifest test reports its own route
            failure = f"{type(exc).__name__}: {exc}"
        yield j, failure
    finally:
        if previous_cv is None:
            app.dependency_overrides.pop(api._cv_service, None)
        else:
            app.dependency_overrides[api._cv_service] = previous_cv
        _cleanup(fx)


def _cleanup(fx: dict) -> None:
    """Delete the tenant: triggers off (lifecycle guards refuse deletes on ended
    seasons), then every row reachable from its organizations and users."""
    import psycopg
    from supabase import create_client

    orgs, users = fx["orgs"], fx["users"]
    if not orgs and not users:
        return
    with psycopg.connect(_DB_URL, autocommit=False) as conn:
        conn.execute("set local session_replication_role = replica")
        farms = "select id from public.farms where cooperative_id = any(%(o)s::uuid[])"
        plots = f"select id from public.plots where farm_id in ({farms})"
        seasons = f"select id from public.crop_seasons where plot_id in ({plots})"
        batches = f"select id from public.production_batches where crop_season_id in ({seasons})"
        activities = f"select id from public.activities where production_batch_id in ({batches})"
        cases = "select id from public.mrv_cases where organization_id = any(%(o)s::uuid[])"
        exports = f"select id from public.mrv_exports where mrv_case_id in ({cases})"
        images = f"select id from public.plant_images where crop_season_id in ({seasons})"
        details = [r[0] for r in conn.execute(
            "select table_name from information_schema.columns where table_schema = 'public' "
            "and column_name = 'activity_id' and table_name <> 'activities'").fetchall()]
        # Season-level results are stored with production_batch_id NULL.
        calculations = (f"select id from public.carbon_calculations where production_batch_id in ({batches}) "
                        f"or crop_season_id in ({seasons})")
        statements = [
            f"delete from storage.objects where (bucket_id, name) in (select storage_bucket, storage_object_path from public.mrv_exports where id in ({exports}))",
            f"delete from public.mrv_export_calculations where mrv_export_id in ({exports})",
            f"delete from public.mrv_exports where id in ({exports})",
            f"delete from public.mrv_evidence where mrv_case_id in ({cases})",
            f"delete from public.mrv_case_steps where mrv_case_id in ({cases})",
            f"delete from public.mrv_case_batches where mrv_case_id in ({cases})",
            f"delete from public.mrv_cases where id in ({cases})",
            f"delete from storage.objects where (bucket_id, name) in (select storage_bucket, storage_object_path from public.plant_images where id in ({images}))",
            f"delete from public.cv_inferences where image_id in ({images})",
            f"delete from public.plant_images where id in ({images})",
            "delete from public.cv_model_versions where version_code = %(cv)s",
            f"delete from public.season_recommendations where crop_season_id in ({seasons})",
            f"delete from public.recommendations where production_batch_id in ({batches})",
            f"delete from public.carbon_breakdowns where calculation_id in ({calculations})",
            f"delete from public.carbon_calculations where id in ({calculations})",
            *[f"delete from public.{t} where activity_id in ({activities})" for t in details],
            f"delete from public.activities where id in ({activities})",
            f"delete from public.production_batches where id in ({batches})",
            f"delete from public.crop_seasons where id in ({seasons})",
            f"delete from public.plots where id in ({plots})",
            f"delete from public.farm_members where farm_id in ({farms})",
            f"delete from public.farms where id in ({farms})",
            "delete from public.organization_memberships where organization_id = any(%(o)s::uuid[]) or user_id = any(%(u)s::uuid[])",
            "delete from public.profiles where id = any(%(u)s::uuid[])",
            "delete from public.organizations where id = any(%(o)s::uuid[])",
        ]
        params = {"o": orgs, "u": users, "cv": fx.get("cv_version_code", "")}
        for statement in statements:
            conn.execute(statement, params)
        conn.commit()
    url, service = _SETTINGS.require_supabase()
    admin = create_client(url, service)
    for user in users:
        admin.auth.admin.delete_user(user)
    with psycopg.connect(_DB_URL) as conn:
        left = conn.execute("select count(*) from public.organizations where id = any(%s::uuid[])", (orgs,)).fetchone()[0]
    assert left == 0, "route auth fixture tenant was not cleaned up"


def test_the_journey_completed(journey):
    _, failure = journey
    assert failure is None, failure


@pytest.mark.parametrize("key", PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
def test_route_positive_and_negative_auth(journey, key):
    j, _ = journey
    route = ROUTES[key]
    calls = j.calls.get(key)
    assert calls, f"PROTECTED_ROUTE_POSITIVE_CASE_MISSING: {key} is in the manifest but no request ran"
    authorized = [c for c in calls if c[0] == route.persona]
    assert authorized, f"{key}: never called as {route.persona}"
    for who, status, code in authorized:
        assert status != 401 and code not in AUTH_CODES, f"{key}: valid {who} token rejected ({status} {code})"
        assert status in route.expect, f"{key}: {who} got {status} {code}, expected {sorted(route.expect)}"
    anonymous = [c for c in calls if c[0] == "anonymous"]
    assert anonymous and all(s == 401 and c in AUTH_CODES for _, s, c in anonymous), f"{key}: anonymous {anonymous}"
    if route.deny:
        denied = [c for c in calls if c[0] == route.deny]
        assert denied and all(s in DENIAL for _, s, _c in denied), f"{key}: {route.deny} was not refused: {denied}"
