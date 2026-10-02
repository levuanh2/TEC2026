"""Core V1 closure (3A) through the API: a former farm editor/viewer reads nothing.

Real `main.app`, real Supabase Auth JWTs, real RLS (FastAPI forwards the
caller's JWT or sets `request.jwt.claims` before calling the same
`private.user_can_read_*` helpers). A refused read must look exactly like a read
of an id that does not exist -- same status, same error envelope -- so nothing
about the farm leaks.

The former OWNER keeps reading their own farm: unchanged, pending a product
decision (docs/CORE_V1_CLOSURE.md, 3A).

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
    "former_viewer": ("coop", "farmer", "viewer", True),
    "former_editor": ("coop", "farmer", "editor", True),
    "former_owner": ("coop", "farmer", "owner", True),
    "outsider": ("other", "farmer", None, False),
}
READERS = ["manager", "owner", "viewer", "former_owner"]  # former_owner: pending product decision
REFUSED = ["former_viewer", "former_editor", "outsider"]


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
                if ended:  # the membership ends afterwards: the farm role outlives it
                    conn.execute("update public.organization_memberships set ended_at = now() - interval '1 day'"
                                 " where user_id = %s", (ids["users"][name],))
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
