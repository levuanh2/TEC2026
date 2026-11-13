"""RAG V1.5 M6 tabletop (docs/rag/RAG_V15_M6_REVOCATION_RUNBOOK.md, section 7), on the local isolated
stack: a served chunk is revoked through the documented emergency procedure, disappears from every
retrieval path, its exposure window is listed from the audited history, and a replacement passes the
full verified flow and the regression check before it is served.

Every text is a SYNTHETIC TEST FIXTURE; identities and the operator reference are synthetic. One
transaction per test, rolled back. Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN: this proves
the revocation mechanics, not the dev3-01 answer-side acceptance (M7).
"""

from __future__ import annotations

import pytest

from tests.test_rag_knowledge_ha_assurance import demo_rpc
from tests.test_rag_knowledge_m2_approval import as_role, m2, recommended  # noqa: F401
from tests.test_rag_knowledge_m3_validity import approve, version
from tests.test_rag_knowledge_status_events import ROOT
from tests.test_rag_knowledge_storage import PERMISSION_DENIED, pytestmark, tx  # noqa: E402

__all__ = ["pytestmark", "tx", "m2"]

EXPOSURE_SQL = (ROOT / "docs/rag/sql/m6_exposure_window.sql").read_text(encoding="utf-8")
EQ_DOC = "select private.knowledge_emergency_quarantine_document(%s, %s, %s, %s)"
POISON = "awd tabletop poisoned guidance"


def exposure(tx, chunk_id):
    tx.cur.execute(EXPOSURE_SQL, {"chunk_id": chunk_id})
    names = [d.name for d in tx.cur.description]
    return dict(zip(names, tx.cur.fetchone()))


def served(tx, doc_chunk, query=POISON):
    return doc_chunk in tx.rpc_ids(tx.member, tx.season_a, query)


def test_tabletop_revoke_a_served_chunk_and_list_its_exposure_window(tx, m2):
    # 1. a verified version is served
    doc, review = recommended(tx, m2, content=POISON)
    m2.decide(review, tx.approver)
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (doc,))
    chunk = tx.cur.fetchone()[0]
    assert served(tx, chunk)
    # 2. trigger (matrix row "integrity_mismatch"): emergency quarantine with a reason code and a ticket
    status, rows = as_role(tx, "service_role", EQ_DOC, (doc, "integrity_mismatch",
                                                        "TEST FIXTURE tabletop: poisoned guidance reported by a reviewer",
                                                        "TEST-FIXTURE-TABLETOP-1"))
    assert status == "ok"
    # 3. the chunk is gone from every read path
    assert not served(tx, chunk)
    status, rows = tx.as_user(tx.member, "select count(*) from public.knowledge_chunks where chunk_id = %s", (chunk,))
    assert rows == [(0,)]
    status, rows = tx.as_user(tx.member, "select count(*) from public.knowledge_documents where id = %s", (doc,))
    assert rows == [(0,)]
    tx.cur.execute("select private.knowledge_declare_isolated_test('TEST FIXTURE: tabletop on the local isolated stack')")
    status, rows = demo_rpc(tx, tx.member, tx.season_a, POISON)
    assert status == "ok" and chunk not in {r[3] for r in rows}            # nor through the demo RPC
    # 4. exposure window from the audited history (an upper bound: no request-level citation log yet)
    w = exposure(tx, chunk)
    assert w["document_status"] == "quarantined" and w["approval_assurance"] == "verified"
    assert w["servable_from"] is not None and w["servable_until"] is not None
    assert w["servable_from"] <= w["servable_until"]
    assert w["document_left_to"] == "quarantined" and w["document_left_reason"].startswith("EMERGENCY integrity_mismatch")
    assert w["emergency_actions"][0]["operator_reference"] == "TEST-FIXTURE-TABLETOP-1"


def test_a_replacement_is_served_only_after_the_full_verified_flow_and_the_regression_check(tx, m2):
    src, old, _ = None, None, None
    old, review = recommended(tx, m2, content=POISON)
    m2.decide(review, tx.approver)
    tx.cur.execute("select source_id from public.knowledge_documents where id = %s", (old,))
    src = tx.cur.fetchone()[0]
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (old,))
    old_chunk = tx.cur.fetchone()[0]
    tx.transition("document", old, "approved", "quarantined", "tabletop revocation")
    # quarantine is one-way: the corrected text is a NEW version through the full flow
    new, new_chunk = version(tx, m2, src, version="v2", content="awd tabletop corrected guidance")
    assert not served(tx, new_chunk, "awd tabletop")                       # not before approval
    # regression check before approval (runbook section 6): the poisoned span is absent from the new text
    tx.cur.execute("select content from public.knowledge_chunks where document_pk = %s", (new,))
    assert all("poisoned" not in r[0] for r in tx.cur.fetchall())
    approve(tx, m2, new)
    ids = tx.rpc_ids(tx.member, tx.season_a, "awd tabletop")
    assert new_chunk in ids and old_chunk not in ids
    # the quarantined version can never come back
    assert tx.transit("document", old, "quarantined", "approved")[0] == "err"


def test_the_exposure_query_is_not_client_readable(tx):
    for role in ("authenticated", "anon"):
        status, sqlstate = as_role(tx, role, EXPOSURE_SQL, {"chunk_id": "x"})
        assert (status, sqlstate) == ("err", PERMISSION_DENIED), role
