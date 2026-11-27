"""L2 blocker fix (migration 20261127090000): the DIRECT read of knowledge chunk text obeys pin admission.

Before: `knowledge_chunks_select` required only a visible (approved, verified, in force) document, so a member's
`select ... from public.knowledge_chunks` returned the text of versions that retrieval refuses (suspended by a re-pin,
approved under an earlier pin). Real database, real approval path, real member JWT (`tx.as_user`).
"""
from __future__ import annotations

import re

from tests.test_rag_knowledge_m2_approval import as_role, m2  # noqa: F401
from tests.test_rag_knowledge_m7_e5_1_pin_admission import approve_now, problem, real_pin
from tests.test_rag_knowledge_m7_e5_2_pin_generation import E5_2_MIGRATION, clean_doc, repin_same, retrieved
from tests.test_rag_knowledge_m7_e5_answer_time import AWD_TEXT
from tests.test_rag_knowledge_storage import pytestmark, tx  # noqa: F401

__all__ = ["pytestmark", "tx", "m2"]

DIRECT = "select chunk_id, content from public.knowledge_chunks where document_pk = %s"


def direct(tx, doc, user=None):
    status, rows = tx.as_user(user or tx.member, DIRECT, (doc,))
    assert status == "ok", rows
    return [r[0] for r in rows]


def test_an_admitted_version_is_readable_directly_and_retrieved(tx, m2):
    doc, _, chunk = clean_doc(tx, m2)
    assert problem(tx, doc) is None
    assert direct(tx, doc) == [chunk] and chunk in retrieved(tx)


def test_a_version_suspended_by_a_re_pin_is_no_longer_readable_directly(tx, m2):
    doc, src, chunk = clean_doc(tx, m2)
    repin_same(tx)                                   # every approval of the previous generation is suspended
    assert problem(tx, doc) == "report_from_earlier_generation"
    assert chunk not in retrieved(tx)                # retrieval already refused it (E5.2)
    assert direct(tx, doc) == []                     # the raw text now too (before this fix: [chunk])
    new, new_chunk = approve_now(tx, m2, src, AWD_TEXT + " Bản rà soát lại.", doc_version="v2",
                                 supersedes_document_pk=doc)
    assert direct(tx, new) == [new_chunk] and new_chunk in retrieved(tx)
    assert direct(tx, doc) == []


def test_tenant_scope_of_the_direct_read_is_unchanged(tx, m2):
    real_pin(tx)
    src_b = tx.source(visibility="tenant", org=tx.org_b)
    doc_b, chunk_b = approve_now(tx, m2, src_b, AWD_TEXT, doc_version="v1")
    assert problem(tx, doc_b) is None
    assert direct(tx, doc_b, tx.outsider) == [chunk_b]   # org B's own member
    assert direct(tx, doc_b, tx.member) == []            # org A's member: never, admitted or not


def test_anon_still_reads_nothing(tx, m2):
    doc, _, _ = clean_doc(tx, m2)
    status, rows = as_role(tx, "anon", DIRECT, (doc,))
    assert (status == "ok" and rows == []) or status == "err"


def test_the_e5_2_helper_returns_exactly_what_its_previous_definition_returned(tx, m2):
    """Same rows as the E5.2 body, for an admitted, a suspended and a re-approved version, and for another tenant's
    season (nothing): the admission logic moved, it did not change."""
    text = E5_2_MIGRATION.read_text(encoding="utf-8")
    start = re.search(r"^create or replace function private\.knowledge_generation_admitted_documents\(", text, re.M).start()
    body = text[start:text.index("\n$$;", start) + 4]
    tx.cur.execute(body.replace("private.knowledge_generation_admitted_documents(", "pg_temp.e5_2_admitted(", 1))

    def both(season):
        out = []
        for fn in ("private.knowledge_generation_admitted_documents", "pg_temp.e5_2_admitted"):
            status, rows = tx.as_user(tx.member, f"select document_pk from {fn}(%s) order by 1", (season,))
            assert status == "ok", rows
            out.append([r[0] for r in rows])
        return out

    doc, src, _ = clean_doc(tx, m2)
    now, before = both(tx.season_a)
    assert now == before and doc in now
    repin_same(tx)
    now, before = both(tx.season_a)
    assert now == before and doc not in now
    new, _ = approve_now(tx, m2, src, AWD_TEXT + " v2", doc_version="v2", supersedes_document_pk=doc)
    now, before = both(tx.season_a)
    assert now == before and new in now
    assert both(tx.season_b) == [[], []]
