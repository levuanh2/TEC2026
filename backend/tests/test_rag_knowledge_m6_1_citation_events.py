"""RAG V1.5 M6.1 citation events, database half (migration 20261113180000): isolation-gated recording,
derived scope and document identity, tenant separation, RLS, append-only audit, retention purge, and the
exposure query that turns a possible exposure window into recorded deliveries.

Every text is a SYNTHETIC TEST FIXTURE; identities are synthetic. One transaction per test, rolled back.
Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.test_rag_knowledge_ha_assurance import ISOLATED, verified_doc
from tests.test_rag_knowledge_m2_approval import as_role, m2, owner  # noqa: F401
from tests.test_rag_knowledge_storage import INVALID_PARAMETER, PERMISSION_DENIED, pytestmark, tx  # noqa: E402

__all__ = ["pytestmark", "tx", "m2"]

RECORD = "select private.knowledge_record_citation_event(%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)"


def record(tx, season, retrieved, cited, *, request=None, outcome="generated", delivered=True, mode="production",
           role="service_role"):
    request = request or str(uuid.uuid4())
    return request, as_role(tx, role, RECORD, (request, season, mode, outcome, delivered, "complete",
                                               json.dumps(retrieved), json.dumps(cited)))


def test_recording_is_refused_on_a_shared_database(tx, m2):
    _, chunk = verified_doc(tx, m2, "awd citation shared")
    assert record(tx, tx.season_a, [chunk], [chunk])[1] == ("err", PERMISSION_DENIED)


def test_an_event_derives_scope_and_document_identity_and_separates_roles(tx, m2):
    doc, cited = verified_doc(tx, m2, "awd citation cited")
    _, candidate = verified_doc(tx, m2, "awd citation candidate")
    tx.cur.execute(ISOLATED)
    request, status = record(tx, tx.season_a, [cited, candidate], [cited])
    assert status[0] == "ok"
    tx.cur.execute("select organization_id, farm_id, delivered, outcome, retention_until - occurred_at"
                   " from public.knowledge_citation_events where request_id = %s", (request,))
    org, farm, delivered, outcome, retention = tx.cur.fetchone()
    assert (org, farm, delivered, outcome) == (tx.org_a, tx.farm_a, True, "generated")
    assert retention.days == 30                                              # the local/CI test value
    tx.cur.execute("select role, chunk_id, document_pk, approval_assurance from public.knowledge_citation_event_chunks"
                   " where request_id = %s order by role, chunk_id", (request,))
    rows = tx.cur.fetchall()
    assert ("cited", cited, doc, "verified") in rows
    assert {(r[0], r[1]) for r in rows} == {("cited", cited), ("retrieved", cited), ("retrieved", candidate)}


@pytest.mark.parametrize("case", ["cited_not_retrieved", "unknown_chunk", "not_strings"])
def test_an_inconsistent_event_is_refused(tx, m2, case):
    _, chunk = verified_doc(tx, m2, "awd citation refused")
    tx.cur.execute(ISOLATED)
    retrieved, cited = {"cited_not_retrieved": ([chunk], [chunk, "c-other"]),
                        "unknown_chunk": (["c-unknown"], []),
                        "not_strings": ([1], [])}[case]
    status = record(tx, tx.season_a, retrieved, cited)[1]
    assert status[0] == "err" and status[1] in (INVALID_PARAMETER, PERMISSION_DENIED)


def test_a_chunk_of_another_tenant_cannot_be_recorded_for_this_scope(tx, m2):
    tenant_b = tx.corpus("awd citation tenant b", visibility="tenant", org=tx.org_b)
    tx.settle()
    tx.cur.execute(ISOLATED)
    assert record(tx, tx.season_a, [tenant_b], [])[1] == ("err", PERMISSION_DENIED)


def test_only_the_service_role_records_and_purges(tx):
    for fn in ("private.knowledge_record_citation_event(uuid,uuid,text,text,boolean,text,jsonb,jsonb)",
               "private.knowledge_purge_citation_events()"):
        for role, expected in (("service_role", True), ("authenticated", False), ("anon", False)):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn))
            assert tx.cur.fetchone()[0] is expected, (fn, role)


def test_the_log_is_append_only_even_for_the_owner(tx, m2):
    _, chunk = verified_doc(tx, m2, "awd citation append only")
    tx.cur.execute(ISOLATED)
    request, _ = record(tx, tx.season_a, [chunk], [chunk])
    for sql in ("update public.knowledge_citation_events set delivered = false",
                "delete from public.knowledge_citation_events", "truncate public.knowledge_citation_events",
                "update public.knowledge_citation_event_chunks set role = 'cited'",
                "delete from public.knowledge_citation_event_chunks",
                "insert into public.knowledge_citation_events (request_id, crop_season_id, organization_id, farm_id,"
                " retrieval_mode, outcome, delivered, trace_completeness, retention_until)"
                " select gen_random_uuid(), crop_season_id, organization_id, farm_id, retrieval_mode, outcome, delivered,"
                " trace_completeness, retention_until from public.knowledge_citation_events"):
        # TRUNCATE of the referenced events table is refused by the foreign key (0A000) before the trigger
        assert owner(tx, sql) in (("err", PERMISSION_DENIED), ("err", "0A000")), sql
    assert owner(tx, "truncate public.knowledge_citation_event_chunks") == ("err", PERMISSION_DENIED)
    tx.cur.execute("select count(*) from public.knowledge_citation_events where request_id = %s", (request,))
    assert tx.cur.fetchone()[0] == 1


def test_no_client_role_reads_the_log_not_even_an_organization_manager(tx, m2):
    """Farm + season + time + cited chunk ids are behavioural data: service_role only (owner decision
    pending on any wider read access)."""
    _, chunk = verified_doc(tx, m2, "awd citation rls")
    tx.cur.execute(ISOLATED)
    request, _ = record(tx, tx.season_a, [chunk], [chunk])
    manager_a = tx.user(tx.org_a, "cooperative_manager")
    manager_b = tx.user(tx.org_b, "cooperative_manager")
    q = "select count(*) from public.knowledge_citation_events where request_id = %s"
    qc = "select count(*) from public.knowledge_citation_event_chunks where request_id = %s"
    for user in (manager_a, manager_b, tx.member):
        for sql in (q, qc):
            assert tx.as_user(user, sql, (request,)) == ("err", PERMISSION_DENIED)
    for role in ("anon", "authenticated"):
        assert as_role(tx, role, q, (request,)) == ("err", PERMISSION_DENIED)
    assert as_role(tx, "service_role", q, (request,)) == ("ok", [(1,)])


def test_retention_purges_only_expired_events_and_records_the_purge(tx, m2):
    _, chunk = verified_doc(tx, m2, "awd citation retention")
    tx.cur.execute(ISOLATED)
    old, _ = record(tx, tx.season_a, [chunk], [chunk])
    fresh, _ = record(tx, tx.season_a, [chunk], [])
    # TEST-ONLY time travel: age one event past its retention (trigger lifted on the owner connection)
    tx.cur.execute("alter table public.knowledge_citation_events disable trigger knowledge_citation_events_guard")
    tx.cur.execute("update public.knowledge_citation_events set retention_until = now() - interval '1 day'"
                   " where request_id = %s", (old,))
    tx.cur.execute("alter table public.knowledge_citation_events enable trigger knowledge_citation_events_guard")
    status, rows = as_role(tx, "service_role", "select private.knowledge_purge_citation_events()")
    assert status == "ok" and rows[0][0] >= 1
    tx.cur.execute("select request_id from public.knowledge_citation_events where request_id = any(%s)",
                   ([uuid.UUID(old), uuid.UUID(fresh)],))
    assert [str(r[0]) for r in tx.cur.fetchall()] == [fresh]
    tx.cur.execute("select count(*) from public.knowledge_citation_event_chunks where request_id = %s", (old,))
    assert tx.cur.fetchone()[0] == 0
    tx.cur.execute("select events_deleted from public.knowledge_citation_purges order by id desc limit 1")
    assert tx.cur.fetchone()[0] >= 1


def test_the_exposure_query_lists_recorded_deliveries_of_a_revoked_chunk(tx, m2):
    """With M6.1 events, the window of M6 becomes a list of recorded deliveries for that chunk: cited
    answers delivered, and retrieval-only candidates reported separately (not as exposure)."""
    doc, chunk = verified_doc(tx, m2, "awd citation exposure")
    tx.cur.execute(ISOLATED)
    cited_req, _ = record(tx, tx.season_a, [chunk], [chunk])
    candidate_req, _ = record(tx, tx.season_a, [chunk], [])
    tx.transition("document", doc, "approved", "quarantined", "tabletop revocation")
    from tests.test_rag_knowledge_status_events import ROOT
    tx.cur.execute((ROOT / "docs/rag/sql/m6_1_citation_exposure.sql").read_text(encoding="utf-8"), {"chunk_id": chunk})
    rows = {str(r[0]): r for r in tx.cur.fetchall()}
    assert rows[cited_req][1:3] == ("cited", True) and rows[candidate_req][1:3] == ("retrieved_only", True)
