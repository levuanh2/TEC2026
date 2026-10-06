"""RAG V1.3-B knowledge storage through REAL PostgREST with REAL Supabase Auth JWTs.

The transaction-scoped matrix lives in test_rag_knowledge_storage.py; this proves the same
contract end to end over HTTP, as a Web/Flutter client or the future backend adapter would
see it: the SECURITY INVOKER RPC under the caller's JWT, RLS on direct table reads, no
client writes, no anonymous access, no extra scope parameter.

Knowledge rows are synthetic TEST FIXTURES — NOT REAL APPROVED SOURCES. Creates users and a
tenant, so it only runs against a LOCAL Supabase stack and deletes everything it created
(approved knowledge is undeletable by design, so cleanup disables the three immutability
triggers inside its own transaction).
"""
from __future__ import annotations

import base64
import hashlib
import json
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


def _knowledge(conn, ids, approver, key, content, *, visibility="public", org=None,
               source_status="approved", document_status="approved"):
    """One source + version + chunk in the given statuses (operator path, table owner); records
    the source for cleanup and the chunk id under ids[key]."""
    now = datetime.now(timezone.utc)
    source_id = f"kn-{ids['run']}-{key.replace('_', '-')}"
    ids["sources"].append(source_id)
    ever_approved = source_status in ("approved", "archived")
    conn.execute(
        "insert into public.knowledge_sources (source_id, title, owner, source_type, visibility,"
        " organization_id, status, approved_by, approved_at, review_note)"
        " values (%s, %s, 'Test publisher', 'guideline', %s, %s, %s, %s, %s, %s)",
        (source_id, FIXTURE + key, visibility, org, "approved" if ever_approved else source_status,
         approver if ever_approved else None, now if ever_approved else None, "fixture" if ever_approved else None))
    if source_status == "archived":           # archived only ever follows an approval
        conn.execute("update public.knowledge_sources set status = 'archived' where source_id = %s", (source_id,))
    # ingestion order: insert the version open for review, add its chunk, then approve/reject/archive
    doc = conn.execute(
        "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
        " official_url, artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version,"
        " chunker_version, license_basis)"
        " values (%s, 'doc', 'v1', %s, 'vi', %s, %s, %s, %s, 'p', 'n', 'c', 'official_publication') returning id",
        (source_id, FIXTURE + key, f"https://example.invalid/{key}", f"knowledge-artifacts/{_sha(source_id)}/doc.md",
         _sha(source_id), _sha("n" + source_id))).fetchone()[0]
    chunk_id = _sha(source_id + content)[:20]
    conn.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                 " values (%s, %s, 0, %s, %s)", (doc, chunk_id, FIXTURE + content, _sha(content)))
    if document_status in ("approved", "archived"):
        conn.execute("update public.knowledge_documents set status = 'approved', approved_by = %s,"
                     " approved_at = %s, review_note = 'fixture' where id = %s", (approver, now, doc))
    if document_status not in ("approved", "review_required"):
        conn.execute("update public.knowledge_documents set status = %s where id = %s", (document_status, doc))
    ids[key] = chunk_id


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
            approver = ids["users"]["approver"]
            _knowledge(conn, ids, approver, "public", "public awd guidance")
            _knowledge(conn, ids, approver, "org_a_doc", "htx a awd procedure", visibility="tenant", org=ids["org_a"])
            _knowledge(conn, ids, approver, "org_b_doc", "htx b awd procedure", visibility="tenant", org=ids["org_b"])
            _knowledge(conn, ids, approver, "pending", "pending awd draft",
                       source_status="review_required", document_status="review_required")
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
        conn.execute("alter table public.knowledge_sources disable trigger knowledge_sources_scope")
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
        conn.execute("alter table public.knowledge_sources enable trigger knowledge_sources_scope")
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


def test_a_chunk_delete_cannot_race_an_approval():
    """Two real sessions (READ COMMITTED): while one approves a version, another deletes one of
    its chunks. The delete must wait for the approval and then be refused -- otherwise the
    approved version would carry different content than was reviewed. Operator path (table
    owner), committed rows, so local-only like the rest of this module."""
    import threading
    import time

    import psycopg
    from supabase import create_client

    url, service = _SETTINGS.require_supabase()
    admin = create_client(url, service)
    ids: dict = {"users": {}, "run": f"{uuid.uuid4().hex[:8]}r", "sources": []}
    try:
        ids["users"]["approver"] = admin.auth.admin.create_user(
            {"email": f"kn-{ids['run']}-approver@agricarbon-ci.invalid", "password": f"Kn-{uuid.uuid4().hex}!9",
             "email_confirm": True}).user.id
        with psycopg.connect(_DB_URL) as conn:
            _knowledge(conn, ids, ids["users"]["approver"], "race", "race awd guidance", document_status="review_required")
            conn.commit()
        source_id = ids["sources"][0]
        outcome: dict = {}

        def delete_chunk():
            try:
                with psycopg.connect(_DB_URL) as conn:
                    conn.execute("delete from public.knowledge_chunks where chunk_id = %s", (ids["race"],))
                    conn.commit()
                outcome["result"] = "deleted"
            except psycopg.Error as exc:
                outcome["result"] = exc.sqlstate

        with psycopg.connect(_DB_URL) as approver, psycopg.connect(_DB_URL, autocommit=True) as watch:
            approver.execute("update public.knowledge_documents set status = 'approved', approved_by = %s,"
                             " approved_at = now(), review_note = 'fixture' where source_id = %s",
                             (ids["users"]["approver"], source_id))
            deleter = threading.Thread(target=delete_chunk)
            deleter.start()
            deadline = time.monotonic() + 10
            while deleter.is_alive() and time.monotonic() < deadline:
                waiting = watch.execute(
                    "select count(*) from pg_stat_activity where wait_event_type = 'Lock'"
                    " and query like 'delete from public.knowledge_chunks%%'").fetchone()[0]
                if waiting:
                    break
                time.sleep(0.05)
            approver.commit()
            deleter.join(timeout=30)
        assert outcome.get("result") == "23514", outcome
        with psycopg.connect(_DB_URL) as conn:
            assert conn.execute("select count(*) from public.knowledge_chunks where chunk_id = %s",
                                (ids["race"],)).fetchone()[0] == 1
            assert conn.execute("select status from public.knowledge_documents where source_id = %s",
                                (source_id,)).fetchone()[0] == "approved"
    finally:
        _cleanup(admin, ids)


# ------------------------------------------------------- Core V1 forced password change

# key: (source status, document status). Only approved + approved is ever retrievable.
STATUS_COMBOS = {
    "public": ("approved", "approved"),
    "src_review": ("review_required", "approved"),
    "src_rejected": ("rejected", "approved"),
    "src_archived": ("archived", "approved"),
    "doc_review": ("approved", "review_required"),
    "doc_rejected": ("approved", "rejected"),
    "doc_archived": ("approved", "archived"),
}


@pytest.fixture(scope="module")
def pw():
    """The Core V1 forced-password flow through the real API: a cooperative manager (no flag)
    provisions two farmers with temporary passwords. `pending` keeps it; `changed` signs in
    (TOKEN_OLD), changes it through POST /v1/me/password and signs in again (TOKEN_NEW).
    Knowledge: approved public + approved tenant (their cooperative) + every status combination.
    Passwords and tokens are never printed (assertions report status codes only)."""
    import httpx
    import psycopg
    from fastapi.testclient import TestClient
    from supabase import create_client

    from main import app

    url, service = _SETTINGS.require_supabase()
    _, publishable = _SETTINGS.require_publishable()
    admin = create_client(url, service)
    api = TestClient(app, raise_server_exceptions=False)
    run = uuid.uuid4().hex[:8]
    ids: dict = {"users": {}, "run": f"{run}p", "sources": []}
    tokens: dict = {}

    def sign_in(email, password):
        return httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": publishable},
                          json={"email": email, "password": password}, timeout=30)

    try:
        with psycopg.connect(_DB_URL) as conn:
            ids["org_a"] = conn.execute(
                "insert into public.organizations (organization_code, name, organization_type)"
                " values (%s, %s, 'cooperative') returning id", (f"KNPW-{run}",) * 2).fetchone()[0]
            conn.commit()
        for name in ("manager", "approver"):
            email, password = f"knpw-{run}-{name}@agricarbon-ci.invalid", f"Kn-{uuid.uuid4().hex}!9"
            ids["users"][name] = admin.auth.admin.create_user(
                {"email": email, "password": password, "email_confirm": True}).user.id
            if name == "manager":
                with psycopg.connect(_DB_URL) as conn:
                    conn.execute("insert into public.organization_memberships (organization_id, user_id, role)"
                                 " values (%s, %s, 'cooperative_manager')", (ids["org_a"], ids["users"][name]))
                    conn.commit()
                r = sign_in(email, password)
                assert r.status_code == 200, r.status_code
                tokens["manager"] = r.json()["access_token"]
        farmers = {}
        for name in ("pending", "changed"):
            email = f"knpw-{run}-{name}@agricarbon-ci.invalid"
            r = api.post(f"/v1/organizations/{ids['org_a']}/farmers",
                         headers={"Authorization": f"Bearer {tokens['manager']}"}, json={
                             "full_name": f"KNPW {name}", "email": email,
                             "farm": {"farm_code": f"KNPW-{run}-{name}", "farm_name": f"KNPW {name}"},
                             "plot": {"plot_code": f"KNPW-{run}-{name}", "name": f"KNPW {name}", "area_ha": 1.0}})
            assert r.status_code == 201, r.status_code      # the body carries a password
            farmers[name] = {**r.json(), "email": email}
            ids["users"][name] = farmers[name]["user_id"]
        with psycopg.connect(_DB_URL) as conn:
            for name, farmer in farmers.items():
                ids[f"season_{name}"] = conn.execute(
                    "insert into public.crop_seasons (plot_id, season_code, status) values (%s, %s, 'active')"
                    " returning id", (farmer["plot_id"], f"KNPW-{run}-{name}")).fetchone()[0]
            approver = ids["users"]["approver"]
            for key, (source_status, document_status) in STATUS_COMBOS.items():
                _knowledge(conn, ids, approver, key, f"{key} awd guidance",
                           source_status=source_status, document_status=document_status)
            _knowledge(conn, ids, approver, "tenant", "htx awd procedure", visibility="tenant", org=ids["org_a"])
            conn.commit()

        # Case A: the provisioned account signs in normally with its temporary password.
        r = sign_in(farmers["pending"]["email"], farmers["pending"]["temporary_password"])
        ids["pending_login_status"] = r.status_code
        tokens["pending"] = r.json().get("access_token") if r.status_code == 200 else None
        # Case B: TOKEN_OLD, the change through the real route, TOKEN_NEW.
        changed = farmers["changed"]
        r = sign_in(changed["email"], changed["temporary_password"])
        assert r.status_code == 200, r.status_code
        tokens["old"] = r.json()["access_token"]
        ids["flag_before_change"] = _live_flag(changed["user_id"])
        new_password = f"Own-{uuid.uuid4().hex[:10]}A1"
        r = api.post("/v1/me/password", headers={"Authorization": f"Bearer {tokens['old']}"},
                     json={"current_password": changed["temporary_password"], "new_password": new_password})
        assert r.status_code == 200, r.status_code
        r = sign_in(changed["email"], new_password)
        assert r.status_code == 200, r.status_code
        tokens["new"] = r.json()["access_token"]

        def call(method, path, token, **kwargs):
            headers = {"apikey": publishable, "Content-Type": "application/json",
                       "Authorization": f"Bearer {tokens[token]}"}
            return httpx.request(method, f"{url}{path}", headers=headers, timeout=30, **kwargs)

        yield call, ids, tokens
    finally:
        _cleanup(admin, ids)


def _live_flag(user_id):
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        return conn.execute("select raw_app_meta_data -> 'must_change_password' from auth.users where id = %s",
                            (user_id,)).fetchone()[0]


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _visible_knowledge(call, ids, token) -> dict[str, set[str]]:
    """Fixture keys each knowledge table shows the caller through PostgREST, and the RPC's chunks
    for the caller's own season (the manager uses the pending farmer's season)."""
    by_source = {f"kn-{ids['run']}-{key.replace('_', '-')}": key for key in [*STATUS_COMBOS, "tenant"]}
    by_chunk = {ids[key]: key for key in by_source.values()}
    seen = {}
    for table in ("knowledge_sources", "knowledge_documents"):
        r = call("GET", f"/rest/v1/{table}?select=source_id&source_id=like.kn-{ids['run']}-*", token)
        assert r.status_code == 200, r.text
        seen[table] = {by_source[row["source_id"]] for row in r.json()}
    r = call("GET", f"/rest/v1/knowledge_chunks?select=chunk_id&chunk_id=in.({','.join(by_chunk)})", token)
    assert r.status_code == 200, r.text
    seen["knowledge_chunks"] = {by_chunk[row["chunk_id"]] for row in r.json()}
    season = ids["season_changed"] if token in ("old", "new") else ids["season_pending"]
    r = call("POST", RPC, token, json={"p_crop_season_id": str(season), "p_query": "awd guidance procedure",
                                       "p_top_k": 50})
    assert r.status_code == 200, r.text
    seen["rpc"] = {by_chunk[row["chunk_id"]] for row in r.json() if row["chunk_id"] in by_chunk}
    return seen


NOTHING = {"knowledge_sources": set(), "knowledge_documents": set(), "knowledge_chunks": set(), "rpc": set()}
# Normal RLS for a member of the cooperative: a source row shows when the SOURCE is approved;
# a version, its chunks and retrieval need source AND version approved.
ELIGIBLE = {"public", "tenant"}
NORMAL = {"knowledge_sources": ELIGIBLE | {"doc_review", "doc_rejected", "doc_archived"},
          "knowledge_documents": ELIGIBLE, "knowledge_chunks": ELIGIBLE, "rpc": ELIGIBLE}


def test_pending_password_account_signs_in_but_sees_no_knowledge(pw):
    """Case A: approved PUBLIC knowledge is public to a valid business user, not a bypass of the
    forced password change -- direct reads of all three tables and the RPC return nothing."""
    call, ids, tokens = pw
    assert ids["pending_login_status"] == 200
    assert _claims(tokens["pending"])["app_metadata"]["must_change_password"] is True
    assert _live_flag(ids["users"]["pending"]) is True
    assert _visible_knowledge(call, ids, "pending") == NOTHING


def test_token_minted_with_the_temporary_password_stays_refused_after_the_change(pw):
    """Case B, TOKEN_OLD: the live flag is cleared; the token's own claim still refuses it."""
    call, ids, tokens = pw
    assert ids["flag_before_change"] is True and _live_flag(ids["users"]["changed"]) is False
    assert _claims(tokens["old"])["app_metadata"]["must_change_password"] is True
    assert _visible_knowledge(call, ids, "old") == NOTHING


def test_token_after_the_change_sees_only_approved_knowledge_in_scope(pw):
    """Case B, TOKEN_NEW: normal public/tenant RLS; review_required, rejected and archived
    sources or versions stay invisible."""
    call, ids, tokens = pw
    assert not _claims(tokens["new"]).get("app_metadata", {}).get("must_change_password")
    assert _visible_knowledge(call, ids, "new") == NORMAL


def test_account_without_the_flag_is_unaffected(pw):
    """Case C: an existing-style account (the cooperative manager, never flagged)."""
    call, ids, tokens = pw
    assert not _claims(tokens["manager"]).get("app_metadata", {}).get("must_change_password")
    assert _live_flag(ids["users"]["manager"]) is None
    assert _visible_knowledge(call, ids, "manager") == NORMAL
