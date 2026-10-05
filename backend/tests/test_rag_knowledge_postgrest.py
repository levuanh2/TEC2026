"""RAG V1.3-B knowledge storage through REAL PostgREST with REAL Supabase Auth JWTs.

The transaction-scoped matrix lives in test_rag_knowledge_storage.py; this proves the same
contract end to end over HTTP, as a Web/Flutter client or the future backend adapter would
see it: the SECURITY INVOKER RPC under the caller's JWT, RLS on direct table reads, no
client writes, no anonymous access, no extra scope parameter.

Knowledge rows are synthetic TEST FIXTURES — NOT REAL APPROVED SOURCES. Creates users and a
tenant, so it only runs against a LOCAL Supabase stack and deletes everything it created
(approved knowledge is undeletable by design, so cleanup disables the two immutability
triggers inside its own transaction).
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import datetime, timezone
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

FIXTURE = "TEST FIXTURE — NOT A REAL APPROVED SOURCE. "
RPC = "/rest/v1/rpc/match_knowledge_chunks_lexical"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture(scope="module")
def env():
    import httpx
    import psycopg
    from supabase import create_client

    url, service = _SETTINGS.require_supabase()
    _, publishable = _SETTINGS.require_publishable()
    admin = create_client(url, service)
    run = uuid.uuid4().hex[:8]
    ids: dict = {"users": {}, "run": run, "sources": []}
    try:
        tokens = {}
        for name in ("member", "outsider", "approver"):
            email, password = f"kn-{run}-{name}@agricarbon-ci.invalid", f"Kn-{uuid.uuid4().hex}!9"
            ids["users"][name] = admin.auth.admin.create_user(
                {"email": email, "password": password, "email_confirm": True}).user.id
            r = httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": publishable},
                           json={"email": email, "password": password}, timeout=30)
            r.raise_for_status()
            tokens[name] = r.json()["access_token"]
        with psycopg.connect(_DB_URL) as conn:
            one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]  # noqa: E731
            for key in ("org_a", "org_b"):
                ids[key] = one("insert into public.organizations (organization_code, name, organization_type)"
                               " values (%s, %s, 'cooperative') returning id", (f"KN-{run}-{key}",) * 2)
            for name, org in (("member", "org_a"), ("outsider", "org_b")):
                conn.execute("insert into public.organization_memberships (organization_id, user_id, role, joined_at)"
                             " values (%s, %s, 'farmer', now() - interval '10 days')", (ids[org], ids["users"][name]))
                farm = one("insert into public.farms (cooperative_id, farm_code, farm_name) values (%s, %s, 'KN')"
                           " returning id", (ids[org], f"KN-{run}-{name}"))
                conn.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, 'owner')",
                             (farm, ids["users"][name]))
                plot = one("insert into public.plots (farm_id, plot_code, name, area_ha) values (%s, %s, 'KN', 1)"
                           " returning id", (farm, f"KN-{run}-{name}"))
                ids[f"season_{name}"] = one("insert into public.crop_seasons (plot_id, season_code, status)"
                                            " values (%s, %s, 'active') returning id", (plot, f"KN-{run}-{name}"))
            now = datetime.now(timezone.utc)
            approver = ids["users"]["approver"]

            def corpus(key, content, *, visibility="public", org=None, approved=True):
                source_id = f"kn-{run}-{key.replace('_', '-')}"
                ids["sources"].append(source_id)
                status = "approved" if approved else "review_required"
                conn.execute(
                    "insert into public.knowledge_sources (source_id, title, owner, source_type, visibility,"
                    " organization_id, status, approved_by, approved_at, review_note)"
                    " values (%s, %s, 'Test publisher', 'guideline', %s, %s, %s, %s, %s, %s)",
                    (source_id, FIXTURE + key, visibility, org, status, approver if approved else None,
                     now if approved else None, "fixture" if approved else None))
                # ingestion order: insert the version open for review, add its chunk, then approve
                doc = one(
                    "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
                    " official_url, file_sha256, normalized_sha256, parser_version, normalizer_version,"
                    " chunker_version, license_basis)"
                    " values (%s, 'doc', 'v1', %s, 'vi', %s, %s, %s, 'p', 'n', 'c', 'official_publication') returning id",
                    (source_id, FIXTURE + key, f"https://example.invalid/{key}", _sha(key), _sha("n" + key)))
                chunk_id = _sha(source_id + content)[:20]
                conn.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                             " values (%s, %s, 0, %s, %s)", (doc, chunk_id, FIXTURE + content, _sha(content)))
                if approved:
                    conn.execute("update public.knowledge_documents set status = 'approved', approved_by = %s,"
                                 " approved_at = %s, review_note = 'fixture' where id = %s", (approver, now, doc))
                ids[key] = chunk_id

            corpus("public", "public awd guidance")
            corpus("org_a_doc", "htx a awd procedure", visibility="tenant", org=ids["org_a"])
            corpus("org_b_doc", "htx b awd procedure", visibility="tenant", org=ids["org_b"])
            corpus("pending", "pending awd draft", approved=False)
            conn.commit()

        def call(method, path, token=None, **kwargs):
            headers = {"apikey": publishable, "Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {tokens[token]}"
            return httpx.request(method, f"{url}{path}", headers=headers, timeout=30, **kwargs)

        yield call, ids
    finally:
        _cleanup(admin, ids)


def _cleanup(admin, ids):
    import psycopg

    users = [str(u) for u in ids["users"].values()]
    orgs = [str(ids[k]) for k in ("org_a", "org_b") if k in ids]
    with psycopg.connect(_DB_URL) as conn:
        # Approved knowledge is undeletable by design; the test owner lifts that only here.
        conn.execute("alter table public.knowledge_chunks disable trigger knowledge_chunks_immutable")
        conn.execute("alter table public.knowledge_documents disable trigger knowledge_documents_immutable")
        params = {"s": ids["sources"], "o": orgs, "u": users}
        farms = "select id from public.farms where cooperative_id = any(%(o)s::uuid[])"
        plots = f"select id from public.plots where farm_id in ({farms})"
        for statement in (
            "delete from public.knowledge_chunks where document_pk in"
            " (select id from public.knowledge_documents where source_id = any(%(s)s))",
            "delete from public.knowledge_documents where source_id = any(%(s)s)",
            "delete from public.knowledge_sources where source_id = any(%(s)s)",
            f"delete from public.crop_seasons where plot_id in ({plots})",
            f"delete from public.plots where id in ({plots})",
            f"delete from public.farm_members where farm_id in ({farms})",
            f"delete from public.farms where id in ({farms})",
            "delete from public.organization_memberships where organization_id = any(%(o)s::uuid[])"
            " or user_id = any(%(u)s::uuid[])",
            "delete from public.profiles where id = any(%(u)s::uuid[])",
            "delete from public.organizations where id = any(%(o)s::uuid[])",
        ):
            conn.execute(statement, params)
        conn.execute("alter table public.knowledge_documents enable trigger knowledge_documents_immutable")
        conn.execute("alter table public.knowledge_chunks enable trigger knowledge_chunks_immutable")
        conn.commit()
    for user in users:
        admin.auth.admin.delete_user(user)


def _chunk_ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {row["chunk_id"] for row in response.json()}


def test_rpc_over_postgrest_returns_public_and_own_tenant_only(env):
    call, ids = env
    found = _chunk_ids(call("POST", RPC, "member",
                            json={"p_crop_season_id": str(ids["season_member"]), "p_query": "awd", "p_top_k": 50}))
    assert ids["public"] in found and ids["org_a_doc"] in found
    assert ids["org_b_doc"] not in found and ids["pending"] not in found


def test_rpc_for_a_season_the_caller_cannot_read_returns_nothing(env):
    call, ids = env
    response = call("POST", RPC, "outsider",
                    json={"p_crop_season_id": str(ids["season_member"]), "p_query": "awd", "p_top_k": 50})
    assert _chunk_ids(response) == set()


def test_rpc_rejects_anonymous_callers(env):
    call, ids = env
    response = call("POST", RPC, json={"p_crop_season_id": str(ids["season_member"]), "p_query": "awd"})
    assert response.status_code in (401, 403), response.text
    assert ids["public"] not in response.text


def test_rpc_has_no_scope_parameter_to_smuggle(env):
    call, ids = env
    response = call("POST", RPC, "outsider", json={
        "p_crop_season_id": str(ids["season_outsider"]), "p_query": "awd", "p_organization_id": str(ids["org_a"])})
    assert response.status_code != 200 and ids["org_a_doc"] not in response.text


def test_direct_table_reads_are_limited_by_rls(env):
    call, ids = env
    wanted = ",".join(ids[k] for k in ("public", "org_a_doc", "org_b_doc", "pending"))
    member = _chunk_ids(call("GET", f"/rest/v1/knowledge_chunks?select=chunk_id&chunk_id=in.({wanted})", "member"))
    outsider = _chunk_ids(call("GET", f"/rest/v1/knowledge_chunks?select=chunk_id&chunk_id=in.({wanted})", "outsider"))
    assert member == {ids["public"], ids["org_a_doc"]}
    assert outsider == {ids["public"], ids["org_b_doc"]}
    anonymous = call("GET", f"/rest/v1/knowledge_chunks?select=chunk_id&chunk_id=in.({wanted})")
    assert anonymous.status_code in (401, 403) or anonymous.json() == []


def test_clients_cannot_write_knowledge(env):
    call, ids = env
    source = f"kn-{ids['run']}-public"
    attempts = [
        call("POST", "/rest/v1/knowledge_sources", "member",
             json={"source_id": f"kn-{ids['run']}-evil", "title": "x", "owner": "x", "source_type": "guideline",
                   "visibility": "public"}),
        call("PATCH", f"/rest/v1/knowledge_documents?source_id=eq.{source}", "member", json={"title": "rewritten"}),
        call("DELETE", f"/rest/v1/knowledge_chunks?chunk_id=eq.{ids['public']}", "member"),
        call("PATCH", f"/rest/v1/knowledge_sources?source_id=eq.{source}", "member", json={"status": "archived"}),
    ]
    for response in attempts:
        assert response.status_code in (401, 403), (response.request.method, response.status_code, response.text)
