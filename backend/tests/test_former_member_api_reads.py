"""Core V1 closure (3A) through the API: the former-member contract.

Real `main.app`, real Supabase Auth JWTs, real RLS (FastAPI forwards the
caller's JWT or sets `request.jwt.claims` before calling the same
`private.user_can_read_*` helpers). A refused read must look exactly like a read
of an id that does not exist -- same status, same error envelope -- so nothing
about the farm leaks.

Product decision 2026-10-03 (docs/CORE_V1_CLOSURE.md): a former farm OWNER keeps
READ-ONLY access to the history of the farm they own -- no write, no other farm,
no HTX dashboard or aggregate. A former editor/viewer reads nothing. `moved_owner`
left this HTX as the farm's owner and is an active farmer of ANOTHER one: that
farmer role must not turn the historical read into a write.

Creates users and a tenant, so it only runs against a LOCAL Supabase stack and
deletes everything it created.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402

_SETTINGS = load_settings()
_DB_URL = _SETTINGS.supabase_db_url
_LOCAL = {"127.0.0.1", "localhost"}
_REMOTE = bool(_DB_URL) and not (urlparse(_DB_URL).hostname in _LOCAL
                                 and urlparse(_SETTINGS.supabase_url or "").hostname in _LOCAL)
pytestmark = [
    pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured."),
    pytest.mark.skipif(_REMOTE, reason="refusing: creates users; only runs against a LOCAL Supabase stack"),
]

PERSONAS = {  # name -> (organization, organization role, farm role, membership ended)
    "manager": ("coop", "cooperative_manager", None, False),
    "owner": ("coop", "farmer", "owner", False),
    "viewer": ("coop", "farmer", "viewer", False),
    "editor": ("coop", "farmer", "editor", False),
    "former_viewer": ("coop", "farmer", "viewer", True),
    "former_editor": ("coop", "farmer", "editor", True),
    "former_owner": ("coop", "farmer", "owner", True),
    "moved_owner": ("coop", "farmer", "owner", True),
    "outsider": ("other", "farmer", None, False),
}
READERS = ["manager", "owner", "viewer", "former_owner", "moved_owner"]
REFUSED = ["former_viewer", "former_editor", "outsider"]
FORMER = ["former_owner", "moved_owner", "former_viewer", "former_editor"]


@pytest.fixture(scope="module")
def tenant():
    import httpx
    import psycopg
    from fastapi.testclient import TestClient
    from supabase import create_client

    from main import app

    url, service = _SETTINGS.require_supabase()
    _, publishable = _SETTINGS.require_publishable()
    admin = create_client(url, service)
    run = uuid.uuid4().hex[:8]
    ids: dict = {"users": {}}
    with psycopg.connect(_DB_URL) as conn:
        one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]  # noqa: E731
        for key in ("coop", "other"):
            ids[key] = one("insert into public.organizations (organization_code, name, organization_type)"
                           " values (%s, %s, 'cooperative') returning id", (f"FMR-{run}-{key}",) * 2)
        conn.commit()
    try:
        tokens = {}
        for name, (org, role, farm_role, ended) in PERSONAS.items():
            email, password = f"fmr-{run}-{name}@agricarbon-ci.invalid", f"Fm-{uuid.uuid4().hex}!9"
            user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
            ids["users"][name] = user.id
            r = httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": publishable},
                           json={"email": email, "password": password}, timeout=30)
            r.raise_for_status()
            tokens[name] = r.json()["access_token"]
        with psycopg.connect(_DB_URL) as conn:
            one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]  # noqa: E731
            ids["farm"] = one("insert into public.farms (cooperative_id, farm_code, farm_name)"
                              " values (%s, %s, 'FMR') returning id", (ids["coop"], f"FMR-{run}"))
            ids["plot"] = one("insert into public.plots (farm_id, plot_code, name, area_ha)"
                              " values (%s, %s, 'FMR', 1) returning id", (ids["farm"], f"FMR-{run}"))
            ids["season"] = one("insert into public.crop_seasons (plot_id, season_code, status)"
                                " values (%s, %s, 'active') returning id", (ids["plot"], f"FMR-{run}"))
            ids["batch"] = one("insert into public.production_batches (crop_season_id, batch_code)"
                               " values (%s, 'default') returning id", (ids["season"],))
            # A second open season of the same farm, for the write tests only.
            ids["write_season"] = one("insert into public.crop_seasons (plot_id, season_code, status)"
                                      " values (%s, %s, 'active') returning id", (ids["plot"], f"FMR-W-{run}"))
            one("insert into public.production_batches (crop_season_id, batch_code)"
                " values (%s, 'default') returning id", (ids["write_season"],))
            # Another farm of the same HTX, owned by `owner` only.
            ids["other_farm"] = one("insert into public.farms (cooperative_id, farm_code, farm_name)"
                                    " values (%s, %s, 'FMR') returning id", (ids["coop"], f"FMR-O-{run}"))
            ids["other_plot"] = one("insert into public.plots (farm_id, plot_code, name, area_ha)"
                                    " values (%s, %s, 'FMR', 1) returning id", (ids["other_farm"], f"FMR-O-{run}"))
            ids["other_season"] = one("insert into public.crop_seasons (plot_id, season_code, status)"
                                      " values (%s, %s, 'active') returning id", (ids["other_plot"], f"FMR-O-{run}"))
            ids["activity"] = one(
                "insert into public.activities (production_batch_id, activity_type, occurred_at, recorded_at, source,"
                " recorded_by, note) values (%s, 'irrigation', now(), now(), 'web', %s, 'FMR') returning id",
                (ids["batch"], ids["users"]["owner"]))
            conn.execute("insert into public.irrigation_events (activity_id, method, water_volume_m3)"
                         " values (%s, 'awd', 1)", (ids["activity"],))
            for name, (org, role, farm_role, ended) in PERSONAS.items():
                conn.execute("insert into public.organization_memberships (organization_id, user_id, role, joined_at)"
                             " values (%s, %s, %s, now() - interval '10 days')", (ids[org], ids["users"][name], role))
                if farm_role:  # a farm role can only be given to an active member (validate_farm_member)
                    conn.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, %s)",
                                 (ids["farm"], ids["users"][name], farm_role))
                if name == "owner":
                    conn.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, 'owner')",
                                 (ids["other_farm"], ids["users"][name]))
                if ended:  # the membership ends afterwards: the farm role outlives it
                    conn.execute("update public.organization_memberships set ended_at = now() - interval '1 day'"
                                 " where user_id = %s", (ids["users"][name],))
            conn.execute("insert into public.organization_memberships (organization_id, user_id, role, joined_at)"
                         " values (%s, %s, 'farmer', now() - interval '1 day')", (ids["other"], ids["users"]["moved_owner"]))
            conn.commit()
        yield TestClient(app, raise_server_exceptions=False), tokens, ids
    finally:
        _cleanup(admin, ids)


def _cleanup(admin, ids):
    import psycopg

    users = [str(u) for u in ids["users"].values()]
    orgs = [str(ids[k]) for k in ("coop", "other") if k in ids]
    with psycopg.connect(_DB_URL) as conn:
        farms = "select id from public.farms where cooperative_id = any(%(o)s::uuid[])"
        plots = f"select id from public.plots where farm_id in ({farms})"
        seasons = f"select id from public.crop_seasons where plot_id in ({plots})"
        batches = f"select id from public.production_batches where crop_season_id in ({seasons})"
        activities = f"select id from public.activities where production_batch_id in ({batches})"
        for statement in (
            f"delete from public.season_recommendations where crop_season_id in ({seasons})",
            f"delete from public.irrigation_events where activity_id in ({activities})",
            f"delete from public.activities where id in ({activities})",
            f"delete from public.production_batches where id in ({batches})",
            f"delete from public.crop_seasons where id in ({seasons})",
            f"delete from public.plots where id in ({plots})",
            f"delete from public.farm_members where farm_id in ({farms})",
            f"delete from public.farms where id in ({farms})",
            "delete from public.organization_memberships where organization_id = any(%(o)s::uuid[])"
            " or user_id = any(%(u)s::uuid[])",
            "delete from public.profiles where id = any(%(u)s::uuid[])",
            "delete from public.organizations where id = any(%(o)s::uuid[])",
        ):
            conn.execute(statement, {"o": orgs, "u": users})
        conn.commit()
    for user in users:
        admin.auth.admin.delete_user(user)


def _routes(ids) -> list[tuple[str, str]]:
    """(route with the tenant's ids, the same route with a random id)."""
    unknown = str(uuid.uuid4())
    return [
        (f"/v1/farms/{ids['farm']}", f"/v1/farms/{unknown}"),
        (f"/v1/farms/{ids['farm']}/plots", f"/v1/farms/{unknown}/plots"),
        (f"/v1/farms/{ids['farm']}/crop-seasons", f"/v1/farms/{unknown}/crop-seasons"),
        (f"/v1/plots/{ids['plot']}", f"/v1/plots/{unknown}"),
        (f"/v1/crop-seasons/{ids['season']}", f"/v1/crop-seasons/{unknown}"),
        (f"/v1/crop-seasons/{ids['season']}/activities", f"/v1/crop-seasons/{unknown}/activities"),
        (f"/v1/crop-seasons/{ids['season']}/production-batches", f"/v1/crop-seasons/{unknown}/production-batches"),
        (f"/v1/production-batches/{ids['batch']}", f"/v1/production-batches/{unknown}"),
    ]


def _get(client, token, path):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize("who", READERS)
def test_current_readers_get_every_level_of_the_farm(tenant, who):
    client, tokens, ids = tenant
    for path, _ in _routes(ids):
        r = _get(client, tokens[who], path)
        assert r.status_code == 200, (who, path, r.status_code, r.text[:200])
    activities = _get(client, tokens[who], f"/v1/crop-seasons/{ids['season']}/activities").json()["items"]
    assert [a["id"] for a in activities] == [str(ids["activity"])]


@pytest.mark.parametrize("who", REFUSED)
def test_refused_reads_look_exactly_like_an_unknown_id(tenant, who):
    client, tokens, ids = tenant
    for path, unknown in _routes(ids):
        refused, missing = _get(client, tokens[who], path), _get(client, tokens[who], unknown)
        assert refused.status_code == missing.status_code, (who, path, refused.text[:200], missing.text[:200])
        assert refused.json() == missing.json(), (who, path)
        assert str(ids["farm"]) not in refused.text and "FMR" not in refused.text


@pytest.mark.parametrize("who", REFUSED)
def test_the_farm_is_not_listed_for_a_former_member(tenant, who):
    client, tokens, ids = tenant
    farms = _get(client, tokens[who], "/v1/farms")
    assert farms.status_code == 200
    assert str(ids["farm"]) not in {f["id"] for f in farms.json()["items"]}
    me = _get(client, tokens[who], "/v1/me").json()
    assert str(ids["farm"]) not in {str(m["farm_id"]) for m in me["farm_memberships"]}


def test_a_former_member_has_no_organization_role_left(tenant):
    client, tokens, ids = tenant
    for who in ("former_viewer", "former_editor", "former_owner"):
        me = _get(client, tokens[who], "/v1/me").json()
        assert me["organization_memberships"] == [], who
        assert "farmer" not in me["roles"], who
        r = _get(client, tokens[who], f"/v1/organizations/{ids['coop']}/farms")
        assert r.status_code in (403, 404), (who, r.status_code)


def _org_routes(org: str) -> list[str]:
    return [f"/v1/organizations/{org}{tail}" for tail in
            ("", "/farms", "/summary", "/metrics", "/farm-performance", "/plots-seasons", "/mrv-batches")]


@pytest.mark.parametrize("who", FORMER + ["outsider"])
def test_htx_dashboards_and_aggregates_look_like_an_unknown_organization(tenant, who):
    client, tokens, ids = tenant
    unknown = str(uuid.uuid4())
    for path, missing_path in zip(_org_routes(ids["coop"]), _org_routes(unknown)):
        refused, missing = _get(client, tokens[who], path), _get(client, tokens[who], missing_path)
        assert refused.status_code == missing.status_code == 404, (who, path, refused.status_code)
        assert refused.json() == missing.json(), (who, path)
    listed = _get(client, tokens[who], "/v1/organizations").json()["items"]
    assert str(ids["coop"]) not in {o["id"] for o in listed}, who


def test_the_manager_reads_the_same_dashboards(tenant):
    # Control for the test above: the routes do answer for an active manager.
    client, tokens, ids = tenant
    for path in _org_routes(ids["coop"]):
        r = _get(client, tokens["manager"], path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])


@pytest.mark.parametrize("who", ["former_owner", "moved_owner"])
def test_a_former_owner_reads_no_other_farm_of_the_htx(tenant, who):
    client, tokens, ids = tenant
    unknown = str(uuid.uuid4())
    pairs = [
        (f"/v1/farms/{ids['other_farm']}", f"/v1/farms/{unknown}"),
        (f"/v1/farms/{ids['other_farm']}/plots", f"/v1/farms/{unknown}/plots"),
        (f"/v1/plots/{ids['other_plot']}", f"/v1/plots/{unknown}"),
        (f"/v1/crop-seasons/{ids['other_season']}", f"/v1/crop-seasons/{unknown}"),
        (f"/v1/crop-seasons/{ids['other_season']}/activities", f"/v1/crop-seasons/{unknown}/activities"),
    ]
    for path, missing_path in pairs:
        refused, missing = _get(client, tokens[who], path), _get(client, tokens[who], missing_path)
        assert refused.status_code == missing.status_code == 404, (who, path, refused.status_code)
        assert refused.json() == missing.json(), (who, path)
    assert str(ids["other_farm"]) not in {f["id"] for f in _get(client, tokens[who], "/v1/farms").json()["items"]}
    # Control: its owner reads it.
    assert _get(client, tokens["owner"], pairs[0][0]).status_code == 200


def _activity(key: str) -> dict:
    return {"idempotency_key": key, "activity_type": "irrigation", "occurred_at": "2026-09-10T08:00:00Z",
            "data": {"method": "awd", "water_volume_m3": 3}}


def _counts(ids) -> dict[str, int]:
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        one = lambda sql, p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
        return {
            "activities": one("select count(*) from public.activities a join public.production_batches b"
                              " on b.id = a.production_batch_id where b.crop_season_id = %s", (ids["write_season"],)),
            "recommendations": one("select count(*) from public.season_recommendations where crop_season_id = %s",
                                   (ids["write_season"],)),
            "plots": one("select count(*) from public.plots where farm_id = %s", (ids["farm"],)),
            "seasons": one("select count(*) from public.crop_seasons where plot_id = %s", (ids["plot"],)),
        }


@pytest.mark.parametrize("who", FORMER)
def test_former_members_write_nothing_and_the_refusal_looks_like_an_unknown_id(tenant, who):
    client, tokens, ids = tenant
    auth = {"Authorization": f"Bearer {tokens[who]}"}
    unknown = str(uuid.uuid4())
    before = _counts(ids)
    attempts = [
        (f"/v1/crop-seasons/{ids['write_season']}/activities", f"/v1/crop-seasons/{unknown}/activities",
         lambda: _activity(str(uuid.uuid4()))),
        (f"/v1/crop-seasons/{ids['write_season']}/recommendations/generate",
         f"/v1/crop-seasons/{unknown}/recommendations/generate", lambda: None),
        (f"/v1/farms/{ids['farm']}/plots", f"/v1/farms/{unknown}/plots",
         lambda: {"plot_code": f"X-{uuid.uuid4().hex[:6]}", "name": "X", "area_ha": 1}),
        (f"/v1/plots/{ids['plot']}/crop-seasons", f"/v1/plots/{unknown}/crop-seasons",
         lambda: {"season_code": f"X-{uuid.uuid4().hex[:6]}"}),
    ]
    for path, missing_path, body in attempts:
        refused = client.post(path, headers=auth, json=body())
        missing = client.post(missing_path, headers=auth, json=body())
        assert refused.status_code == missing.status_code and refused.status_code in (403, 404), (
            who, path, refused.status_code, refused.text[:200], missing.status_code)
        assert refused.json() == missing.json(), (who, path)
    assert _counts(ids) == before, who


def test_the_active_owner_writes_through_the_same_routes(tenant):
    # Control for the test above (contract A): same routes, same season, 2xx.
    client, tokens, ids = tenant
    auth = {"Authorization": f"Bearer {tokens['owner']}"}
    before = _counts(ids)
    r = client.post(f"/v1/crop-seasons/{ids['write_season']}/activities", headers=auth, json=_activity(str(uuid.uuid4())))
    assert r.status_code == 201, r.text[:300]
    r = client.post(f"/v1/crop-seasons/{ids['write_season']}/recommendations/generate", headers=auth)
    assert r.status_code == 200, r.text[:300]
    after = _counts(ids)
    assert after["activities"] == before["activities"] + 1
    assert after["recommendations"] >= 1
    # A former owner (any farmer role elsewhere) cannot accept/dismiss them.
    rec = r.json()["items"][0]
    # Generation keeps an earlier accept/dismiss, so compare with the status now.
    status_before = rec["status"]
    for who in ("former_owner", "moved_owner"):
        refused = client.patch(f"/v1/recommendations/{rec['id']}", json={"status": "accepted"},
                               headers={"Authorization": f"Bearer {tokens[who]}"})
        missing = client.patch(f"/v1/recommendations/{uuid.uuid4()}", json={"status": "accepted"},
                               headers={"Authorization": f"Bearer {tokens[who]}"})
        assert refused.status_code == missing.status_code == 404, (who, refused.text[:200])
        assert refused.json() == missing.json(), who
    listed = _get(client, tokens["owner"], f"/v1/crop-seasons/{ids['write_season']}/recommendations").json()["items"]
    assert {x["id"]: x["status"] for x in listed}[rec["id"]] == status_before


# -- Viewer is read-only (product decision 2026-10-03) -----------------------------
# Recommendation and CV writes go through a service-role connection; write
# authority is `private.user_can_write_crop` for the JWT-verified caller. The
# farmer-role gate stays on top (an HTX manager is refused these farmer actions).

WRITERS = ["owner", "editor"]
NOT_WRITERS = ["viewer", "former_owner", "moved_owner", "former_viewer", "former_editor", "outsider", "manager"]


def _auth(tokens, who):
    return {"Authorization": f"Bearer {tokens[who]}"}


@pytest.mark.parametrize("who", NOT_WRITERS)
def test_generate_accept_and_dismiss_are_refused_without_write_authority(tenant, who):
    client, tokens, ids = tenant
    season, unknown = ids["write_season"], str(uuid.uuid4())
    generated = client.post(f"/v1/crop-seasons/{season}/recommendations/generate", headers=_auth(tokens, "owner"))
    assert generated.status_code == 200, generated.text[:200]
    rec = generated.json()["items"][0]
    before = _counts(ids)
    statuses = lambda: {x["id"]: x["status"] for x in _get(  # noqa: E731
        client, tokens["owner"], f"/v1/crop-seasons/{season}/recommendations").json()["items"]}
    # Generation keeps a farmer's earlier accept/dismiss, so compare, never assume.
    status_before = statuses()

    refused = client.post(f"/v1/crop-seasons/{season}/recommendations/generate", headers=_auth(tokens, who))
    missing = client.post(f"/v1/crop-seasons/{unknown}/recommendations/generate", headers=_auth(tokens, who))
    assert refused.status_code == missing.status_code == 404, (who, refused.text[:200])
    assert refused.json() == missing.json(), who
    for status in ("accepted", "dismissed"):
        refused = client.patch(f"/v1/recommendations/{rec['id']}", json={"status": status}, headers=_auth(tokens, who))
        missing = client.patch(f"/v1/recommendations/{uuid.uuid4()}", json={"status": status}, headers=_auth(tokens, who))
        assert refused.status_code == missing.status_code == 404, (who, status, refused.text[:200])
        assert refused.json() == missing.json(), (who, status)

    assert _counts(ids) == before, who
    assert statuses() == status_before, who


@pytest.mark.parametrize("who", WRITERS)
def test_owner_and_editor_generate_accept_and_dismiss(tenant, who):
    client, tokens, ids = tenant
    season = ids["write_season"]
    generated = client.post(f"/v1/crop-seasons/{season}/recommendations/generate", headers=_auth(tokens, who))
    assert generated.status_code == 200, (who, generated.text[:200])
    rec = generated.json()["items"][0]
    for status in ("accepted", "dismissed"):
        r = client.patch(f"/v1/recommendations/{rec['id']}", json={"status": status}, headers=_auth(tokens, who))
        assert r.status_code == 200 and r.json()["status"] == status, (who, status, r.text[:200])


@pytest.mark.parametrize("who,allowed", [
    ("owner", True), ("editor", True), ("manager", True),  # the DB helper; the service adds the farmer gate
    ("viewer", False), ("former_owner", False), ("moved_owner", False),
    ("former_viewer", False), ("former_editor", False), ("outsider", False),
])
def test_cv_upload_write_authority_is_the_plant_images_insert_rule(tenant, who, allowed):
    from infrastructure.crop_write_authz import CropWriteDeniedError
    from infrastructure.cv_repo import PostgresCvRepository

    _, _, ids = tenant
    repo = PostgresCvRepository(_SETTINGS)
    user = str(ids["users"][who])
    if allowed:
        repo.assert_can_write(crop_season_id=str(ids["write_season"]), actor_id=user)
    else:
        with pytest.raises(CropWriteDeniedError):
            repo.assert_can_write(crop_season_id=str(ids["write_season"]), actor_id=user)
        # The row write itself refuses too, and nothing is written.
        with pytest.raises(CropWriteDeniedError):
            repo.create_image(crop_season_id=str(ids["write_season"]), uploaded_by=user,
                              storage_object_path=f"{ids['farm']}/{ids['write_season']}/x.jpg", mime_type="image/jpeg",
                              file_size_bytes=1, sha256=uuid.uuid4().hex * 2)
    with pytest.raises(CropWriteDeniedError):  # unknown season: same refusal
        repo.assert_can_write(crop_season_id=str(uuid.uuid4()), actor_id=user)
