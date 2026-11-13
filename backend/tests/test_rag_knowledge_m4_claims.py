"""RAG V1.5 M4 (migration 20261112090000): stored claims and contradiction candidates, at the DATABASE
under the real roles, through the operator pipeline (infrastructure/knowledge_claims_repo.py).

Every text is a SYNTHETIC TEST FIXTURE; the numbers are not agronomic reference values. Identities
are synthetic fixtures (tests/knowledge_status_paths.py). One transaction per test, rolled back,
except the concurrency/CLI test (it commits a synthetic never-approved draft and deletes it).
Skipped without SUPABASE_DB_URL.

dev3-01 stays OPEN: a candidate is a review aid for a human. Nothing here judges content, changes a
status, or is read by retrieval or the answer path.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from infrastructure.knowledge_claims_repo import (PsycopgClaimStore, UnknownDocument, analyze_document,
                                                  extract_document_claims)
from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION
from knowledge.integrity.contradictions import ANALYSIS_VERSION, Tolerance
from tests.test_rag_knowledge_m2_approval import as_role, m2, owner  # noqa: F401
from tests.test_rag_knowledge_m3_validity import DAY, approve, approved, force, today, version, window
from tests.test_rag_knowledge_status_events import M4_1_ROLLBACK, ROOT, _without_tx_control, unwind_ha
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, INVALID_PARAMETER, PERMISSION_DENIED, RPC,  # noqa: E402
                                              _DB_URL, pytestmark, psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

M4 = ROOT / "supabase/migrations/20261112090000_knowledge_claims_contradictions_m4.sql"
M4_ROLLBACK = ROOT / "supabase/rollbacks/20261112090000_knowledge_claims_contradictions_m4.down.sql"
M3_ROLLBACK = ROOT / "supabase/rollbacks/20261111090000_knowledge_effective_dates_m3.down.sql"
FOREIGN_KEY_VIOLATION = "23503"
RECORD_CLAIMS = "select private.knowledge_record_claims(%s, %s, %s::jsonb)"
RECORD_CANDIDATES = "select private.knowledge_record_contradiction_candidates(%s, %s::jsonb)"
TABLES = ("knowledge_claims", "knowledge_contradiction_candidates")

DRY_15 = "Khi mực nước xuống 15 cm dưới mặt ruộng thì tưới lại."
DRY_150MM = "Khi mực nước xuống 150 mm dưới mặt ruộng thì tưới lại."
DRY_30 = "Khi mực nước xuống 30 cm dưới mặt ruộng thì tưới lại."
KEY = "water.awd.dry_down_depth|cm"


def store(tx):
    return PsycopgClaimStore(tx.conn)


def stored(tx, doc, columns="claim_id, kind, status, comparison_key"):
    tx.cur.execute(f"select {columns} from public.knowledge_claims where document_pk = %s order by id", (doc,))
    return tx.cur.fetchall()


def claim_of(tx, doc, key=KEY):
    """The id of the one stored comparable claim of `doc` for `key`."""
    tx.cur.execute("select id from public.knowledge_claims where document_pk = %s and comparison_key = %s", (doc, key))
    (row,) = tx.cur.fetchall()
    return row[0]


def candidates(tx, *docs):
    tx.cur.execute(
        "select k.classification, k.reasons, k.independence, k.evidence_state_a, k.evidence_state_b, k.visibility,"
        "       k.organization_id from public.knowledge_contradiction_candidates k"
        "  join public.knowledge_claims a on a.id = k.claim_a join public.knowledge_claims b on b.id = k.claim_b"
        " where a.document_pk = any(%s) and b.document_pk = any(%s) order by k.id", (list(docs), list(docs)))
    return tx.cur.fetchall()


def proposal(a, b, classification, **extra):
    low, high = sorted((a, b))
    return json.dumps([{"claim_a": low, "claim_b": high, "classification": classification, "reasons": ["test"], **extra}])


def propose(tx, a, b, classification, **extra):
    return owner(tx, RECORD_CANDIDATES, (ANALYSIS_VERSION, proposal(a, b, classification, **extra)))


def active(tx, m2, text, **kw):
    """An approved, in-force version holding `text`, with its claims stored: (src, doc, chunk)."""
    src, doc, chunk = approved(tx, m2, content=text, **kw)
    extract_document_claims(store(tx), str(doc))
    return src, doc, chunk


def draft(tx, m2, text, src=None, **kw):
    """A review_required version holding `text`, with its claims stored: (doc, chunk)."""
    doc, chunk = version(tx, m2, src or tx.source(), content=text, **kw)
    extract_document_claims(store(tx), str(doc))
    return doc, chunk


# ================================================================== schema and privileges

def test_m4_tables_are_rls_locked_and_readable_only_by_service_role(tx):
    for table in TABLES:
        tx.cur.execute("select relrowsecurity, (select count(*) from pg_policies where tablename = %s)"
                       " from pg_class where oid = %s::regclass", (table, f"public.{table}"))
        assert tx.cur.fetchone() == (True, 0), table
        for role, expected in (("anon", False), ("authenticated", False), ("service_role", True)):
            tx.cur.execute("select has_table_privilege(%s, %s, 'select'),"
                           " has_table_privilege(%s, %s, 'insert, update, delete, truncate')",
                           (role, f"public.{table}", role, f"public.{table}"))
            assert tx.cur.fetchone() == (expected, False), (table, role)


def test_m4_functions_are_pinned_and_only_the_recording_functions_reach_service_role(tx):
    granted = {"knowledge_record_claims(uuid, text, jsonb)": True,
               "knowledge_record_contradiction_candidates(text, jsonb)": True,
               "knowledge_document_evidence_state(uuid)": True,
               "knowledge_classify_claim_pair(bigint, bigint, numeric)": False,
               "knowledge_claim_evidence_guard()": False}
    for name, service in granted.items():
        tx.cur.execute("select prosecdef, proconfig from pg_proc where oid = %s::regprocedure", (f"private.{name}",))
        definer, config = tx.cur.fetchone()
        assert config == ['search_path=""'] and definer is service, name
        for role, expected in (("anon", False), ("authenticated", False), ("service_role", service)):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, f"private.{name}"))
            assert tx.cur.fetchone()[0] is expected, (name, role)


def test_clients_and_tenants_read_nothing_and_call_nothing(tx, m2):
    _, doc, _ = active(tx, m2, DRY_15, visibility="tenant", org=tx.org_a)
    for user in (tx.member, tx.manager, tx.outsider):
        for table in TABLES:
            assert tx.as_user(user, f"select count(*) from public.{table}") == ("err", PERMISSION_DENIED)
        assert tx.as_user(user, RECORD_CLAIMS, (doc, "x-1", "[]")) == ("err", PERMISSION_DENIED)
        assert tx.as_user(user, RECORD_CANDIDATES, ("x-1", "[]")) == ("err", PERMISSION_DENIED)
        assert tx.as_user(user, "select * from private.knowledge_document_evidence_state(%s)", (doc,))[0] == "err"
    assert as_role(tx, "anon", "select count(*) from public.knowledge_claims") == ("err", PERMISSION_DENIED)
    assert as_role(tx, "service_role", "select count(*) from public.knowledge_claims where document_pk = %s",
                   (doc,))[1][0][0] >= 1


# ================================================================== extraction

def test_claims_are_bound_to_the_exact_chunk_span_and_scope(tx, m2):
    src = tx.source(visibility="tenant", org=tx.org_a, farm=tx.farm_a)
    doc, chunk = version(tx, m2, src, content="Giai đoạn đẻ nhánh, bón 1,5 tấn/ha phân bón. Bón 1.500 kg/ha phân bón.")
    result = extract_document_claims(store(tx), str(doc))
    assert (result.chunks, result.claims, result.inserted, result.unresolved, result.decision) == (1, 3, 3, 1, "none")
    assert result.extractor_version == CLAIM_EXTRACTOR_VERSION
    tx.cur.execute(
        "select c.kind, c.status, c.raw_text, substr(k.content, c.span_start + 1, c.span_end - c.span_start),"
        "       c.value_min::float8, c.unit, c.stage, c.comparison_key, c.chunk_id, c.chunk_content_sha256 = k.content_sha256,"
        "       c.visibility, c.organization_id, c.farm_id, c.source_id, c.document_version, c.extractor_version,"
        "       c.actor_role"
        "  from public.knowledge_claims c join public.knowledge_chunks k on k.id = c.chunk_pk"
        " where c.document_pk = %s order by c.span_start, c.kind", (doc,))
    rows = tx.cur.fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("stage", "extracted", "đẻ nhánh"),
                                                  ("quantity", "extracted", "1,5 tấn/ha"),
                                                  ("quantity", "ambiguous", "1.500 kg/ha")]
    assert all(r[2] == r[3] for r in rows)                                   # the span IS the raw text
    assert rows[1][4:8] == (1500.0, "kg/ha", "tillering", "fertilizer.rate|kg/ha")
    assert rows[2][4] is None and rows[2][7] is None                         # ambiguous: no value, no key
    assert all(r[8:] == (chunk, True, "tenant", tx.org_a, tx.farm_a, src, "v1", CLAIM_EXTRACTOR_VERSION, "postgres")
               for r in rows)


def test_extraction_is_idempotent_and_an_unknown_document_is_refused(tx, m2):
    doc, _ = version(tx, m2, tx.source(), content=DRY_15)
    first = extract_document_claims(store(tx), str(doc))
    again = extract_document_claims(store(tx), str(doc))
    assert (first.inserted, again.inserted, again.claims) == (1, 0, 1)
    assert len(stored(tx, doc)) == 1
    with pytest.raises(UnknownDocument):
        extract_document_claims(store(tx), str(uuid.uuid4()))
    assert owner(tx, RECORD_CLAIMS, (uuid.uuid4(), "x-1", "[]"))[1] == "P0002"


def _claim(chunk, **change):
    base = {"claim_id": "cl-" + "0" * 16, "chunk_id": chunk, "span_start": 0, "span_end": 4, "raw_text": "TEST",
            "kind": "assertion", "status": "extracted", "parameter": None, "value_min": None, "value_max": None,
            "unit": None, "dimension": None, "date_iso": None, "stage": None, "scope_tags": [], "note": ""}
    return {**base, **change}


@pytest.mark.parametrize("change, expected", [
    ({}, "ok"),
    ({"span_start": 1}, CHECK_VIOLATION),                         # the text is not at that span
    ({"raw_text": "TESX"}, CHECK_VIOLATION),
    ({"span_end": 100000, "raw_text": "TEST"}, CHECK_VIOLATION),  # beyond the chunk
    ({"span_start": 4, "span_end": 4, "raw_text": ""}, CHECK_VIOLATION),
    ({"span_start": -1}, INVALID_PARAMETER),
    ({"span_start": "0"}, INVALID_PARAMETER),
    ({"chunk_id": "f" * 20}, FOREIGN_KEY_VIOLATION),              # not a chunk of this version
    ({"chunk_id": "OTHER"}, FOREIGN_KEY_VIOLATION),               # a chunk of another version
    ({"kind": "opinion"}, CHECK_VIOLATION),
    ({"status": "verified"}, CHECK_VIOLATION),
    ({"claim_id": "x"}, CHECK_VIOLATION),
    ({"kind": "quantity", "value_min": 2, "value_max": 1, "unit": "cm"}, CHECK_VIOLATION),
    ({"value_min": 1, "value_max": 1}, CHECK_VIOLATION),          # a value without a unit / on a non-quantity
    ({"kind": "quantity", "value_min": "1", "value_max": 1, "unit": "cm"}, INVALID_PARAMETER),   # a number, not text
    ({"kind": "quantity", "value_min": 1, "value_max": [2], "unit": "cm"}, INVALID_PARAMETER),
    ({"kind": "date", "date_iso": "31/12/2026"}, INVALID_PARAMETER),
    ({"kind": "date", "date_iso": 20261231}, INVALID_PARAMETER),
    ({"kind": "date", "date_iso": "2026-02-31"}, "22008"),        # well-formed, not a calendar date
    ({"scope_tags": [1]}, INVALID_PARAMETER),
    ({"scope_tags": "awd"}, INVALID_PARAMETER),
])
def test_an_invalid_evidence_span_or_claim_is_refused(tx, m2, change, expected):
    doc, chunk = version(tx, m2, tx.source(), content=DRY_15)
    _, other_chunk = version(tx, m2, tx.source(), content=DRY_30)
    if change.get("chunk_id") == "OTHER":
        change = {**change, "chunk_id": other_chunk}
    result = owner(tx, RECORD_CLAIMS, (doc, "test-1", json.dumps([_claim(chunk, **change)])))
    assert result == (("ok", None) if expected == "ok" else ("err", expected))
    assert len(stored(tx, doc)) == (1 if expected == "ok" else 0)


@pytest.mark.parametrize("version_text, payload, expected", [
    ("", "[]", INVALID_PARAMETER), ("Bad Version", "[]", INVALID_PARAMETER), (None, "[]", INVALID_PARAMETER),
    ("test-1", "{}", INVALID_PARAMETER), ("test-1", "[1]", INVALID_PARAMETER), ("test-1", None, INVALID_PARAMETER),
])
def test_malformed_recording_calls_are_refused(tx, m2, version_text, payload, expected):
    doc, _ = version(tx, m2, tx.source(), content=DRY_15)
    assert owner(tx, RECORD_CLAIMS, (doc, version_text, payload)) == ("err", expected)


def test_the_same_claim_id_with_other_facts_needs_a_new_extractor_version(tx, m2):
    doc, chunk = version(tx, m2, tx.source(), content=DRY_15)
    assert owner(tx, RECORD_CLAIMS, (doc, "test-1", json.dumps([_claim(chunk)])))[0] == "ok"
    assert owner(tx, RECORD_CLAIMS, (doc, "test-1", json.dumps([_claim(chunk)])))[0] == "ok"          # identical: skipped
    assert owner(tx, RECORD_CLAIMS, (doc, "test-1", json.dumps([_claim(chunk, note="changed")]))) \
        == ("err", CHECK_VIOLATION)
    assert owner(tx, RECORD_CLAIMS, (doc, "test-2", json.dumps([_claim(chunk, note="changed")])))[0] == "ok"
    assert len(stored(tx, doc)) == 2


# ================================================================== append-only evidence

def test_claims_and_candidates_are_append_only_even_for_the_owner(tx, m2):
    _, a, _ = active(tx, m2, DRY_15)
    b, _ = draft(tx, m2, DRY_30)
    assert analyze_document(store(tx), str(b)).inserted == 1
    for table in TABLES:
        for sql in (f"update public.{table} set recorded_at = now()", f"delete from public.{table}",
                    f"truncate public.{table} cascade"):
            assert owner(tx, sql) == ("err", PERMISSION_DENIED), sql
            assert as_role(tx, "service_role", sql) == ("err", PERMISSION_DENIED), sql
    forged = ("insert into public.knowledge_claims (document_pk, chunk_pk, source_id, document_id, document_version,"
              " chunk_id, chunk_content_sha256, extractor_version, claim_id, span_start, span_end, raw_text, kind, status,"
              " visibility, actor_role) select document_pk, chunk_pk, source_id, document_id, document_version, chunk_id,"
              " chunk_content_sha256, 'forged-1', claim_id, span_start, span_end, raw_text, kind, status, visibility, 'x'"
              " from public.knowledge_claims where document_pk = %s")
    assert owner(tx, forged, (a,)) == ("err", PERMISSION_DENIED)
    for role in ("service_role", "authenticated", "anon"):
        assert as_role(tx, role, forged, (a,)) == ("err", PERMISSION_DENIED), role
    assert owner(tx, "insert into public.knowledge_contradiction_candidates (claim_a, claim_b, comparison_key,"
                     " classification, reasons, independence, analysis_version, policy_date, evidence_state_a,"
                     " evidence_state_b, visibility, actor_role) values (%s, %s, 'k', 'contradiction', '{x}',"
                     " 'same_source', 'forged-1', current_date, 'active', 'active', 'public', 'x')",
                 (claim_of(tx, a), claim_of(tx, b))) == ("err", PERMISSION_DENIED)


def test_evidence_of_a_never_approved_draft_goes_with_it_and_approved_evidence_stays(tx, m2):
    _, a, _ = active(tx, m2, DRY_15)
    b, _ = draft(tx, m2, DRY_30)
    analyze_document(store(tx), str(b))
    assert len(candidates(tx, a, b)) == 1
    # M1 allows deleting a never-approved review_required draft: its claims and candidates go with it
    assert owner(tx, "delete from public.knowledge_upload_attestations where document_pk = %s", (b,))[0] == "err"
    tx.cur.execute("alter table public.knowledge_upload_attestations disable trigger knowledge_upload_attestations_guard")
    tx.cur.execute("delete from public.knowledge_upload_attestations where document_pk = %s", (b,))
    tx.cur.execute("alter table public.knowledge_upload_attestations enable trigger knowledge_upload_attestations_guard")
    assert owner(tx, "delete from public.knowledge_chunks where document_pk = %s", (b,)) == ("ok", None)
    assert stored(tx, b) == [] and candidates(tx, a, b) == []
    assert owner(tx, "delete from public.knowledge_documents where id = %s", (b,)) == ("ok", None)
    # an approved version (and so its claims) can never be deleted
    assert owner(tx, "delete from public.knowledge_chunks where document_pk = %s", (a,))[0] == "err"
    assert owner(tx, "delete from public.knowledge_documents where id = %s", (a,))[0] == "err"
    assert len(stored(tx, a)) == 1


# ================================================================== contradiction candidates

def test_a_candidate_version_contradicting_active_guidance_is_reported_once(tx, m2):
    _, a, chunk_a = active(tx, m2, DRY_15)
    b, _ = draft(tx, m2, DRY_30)
    result = analyze_document(store(tx), str(b))
    assert (result.inserted, result.decision, result.analysis.compared) == (1, "none", 1)
    assert candidates(tx, a, b) == [("contradiction", ["same_parameter_same_context"], "independent_source", "active",
                                     "candidate", "public", None)]
    assert analyze_document(store(tx), str(b)).inserted == 0                  # idempotent
    assert analyze_document(store(tx), str(a)).inserted == 0                  # and symmetric
    assert len(candidates(tx, a, b)) == 1
    # a review aid only: nothing changed, and the contradicted chunk is still served
    assert (tx.status_of("document", a), tx.status_of("document", b)) == ("approved", "review_required")
    assert chunk_a in tx.rpc_ids(tx.member, tx.season_a, "mực nước dưới mặt ruộng")
    tx.cur.execute("select count(*) from public.knowledge_status_events where document_pk = any(%s)"
                   " and to_status in ('quarantined', 'rejected', 'archived')", ([a, b],))
    assert tx.cur.fetchone()[0] == 0


def test_equivalent_values_and_other_parameters_raise_nothing(tx, m2):
    _, a, _ = active(tx, m2, DRY_15)
    b, _ = draft(tx, m2, DRY_150MM + " Tưới lại sau 5 ngày giữa các lần tưới.")
    result = analyze_document(store(tx), str(b))
    assert (result.inserted, result.analysis.candidates) == (0, ())
    assert propose(tx, claim_of(tx, a), claim_of(tx, b), "contradiction") == ("err", CHECK_VIOLATION)   # consistent


def test_the_database_classifies_every_pair_itself_and_refuses_another_label(tx, m2):
    _, a, _ = active(tx, m2, "Giai đoạn đẻ nhánh, bón 30 kg/ha phân bón.")
    b, _ = draft(tx, m2, "Bón 60 kg/ha phân bón.")
    key = "fertilizer.rate|kg/ha"
    ca, cb = claim_of(tx, a, key), claim_of(tx, b, key)
    for label in ("contradiction", "apparent_contradiction", "insufficient_evidence"):
        assert propose(tx, ca, cb, label) == ("err", CHECK_VIOLATION), label
    assert propose(tx, ca, cb, "nonsense") == ("err", CHECK_VIOLATION)
    assert propose(tx, ca, cb, "missing_context", independence="same_document") == ("err", CHECK_VIOLATION)
    assert propose(tx, ca, cb, "missing_context") == ("ok", None)
    assert [c[0] for c in candidates(tx, a, b)] == ["missing_context"]
    # structure
    assert owner(tx, RECORD_CANDIDATES, (ANALYSIS_VERSION, json.dumps(
        [{"claim_a": cb, "claim_b": ca, "classification": "missing_context", "reasons": ["x"]}]))) \
        == ("err", INVALID_PARAMETER)                                                        # a < b
    assert propose(tx, ca, ca + 10 ** 9, "contradiction") == ("err", CHECK_VIOLATION)        # unknown claim
    assert propose(tx, ca, cb, "missing_context", tolerance=5) == ("err", INVALID_PARAMETER)  # unjustified tolerance
    assert propose(tx, ca, cb, "missing_context", tolerance=40, tolerance_rationale="TEST FIXTURE") \
        == ("err", CHECK_VIOLATION)                                                          # within it: consistent
    for version_text, payload in (("", "[]"), ("x-1", "{}"), ("x-1", "[1]"), ("x-1", None)):
        assert owner(tx, RECORD_CANDIDATES, (version_text, payload)) == ("err", INVALID_PARAMETER)


def test_different_stated_stages_and_one_chunk_are_never_paired(tx, m2):
    _, a, _ = active(tx, m2, "Giai đoạn đẻ nhánh, bón 30 kg/ha phân bón.")
    b, _ = draft(tx, m2, "Giai đoạn làm đòng, bón 60 kg/ha phân bón. Sau đó bón 90 kg/ha phân bón.")
    result = analyze_document(store(tx), str(b))
    assert result.inserted == 1 and dict(result.analysis.skipped) == {"different_stage": 1, "same_chunk": 1}
    assert [c[0] for c in candidates(tx, a, b)] == ["missing_context"]            # the unstaged 90 vs the staged 30
    key = "fertilizer.rate|kg/ha"
    tx.cur.execute("select id, stage from public.knowledge_claims where document_pk = %s and comparison_key = %s"
                   " order by span_start", (b, key))
    (staged, _), (unstaged, _) = tx.cur.fetchall()
    assert propose(tx, claim_of(tx, a, key), staged, "contradiction") == ("err", CHECK_VIOLATION)   # different stage
    assert propose(tx, staged, unstaged, "contradiction") == ("err", CHECK_VIOLATION)               # same chunk


def test_supersession_and_another_version_are_apparent_contradictions(tx, m2):
    src, old, _ = active(tx, m2, DRY_15)
    successor, _ = draft(tx, m2, DRY_30, src=src, document_id="doc-successor", supersedes_document_pk=old)
    assert analyze_document(store(tx), str(successor)).inserted == 1
    assert candidates(tx, old, successor) == [("apparent_contradiction", ["superseded_version"], "same_source",
                                               "active", "candidate", "public", None)]
    second, _ = draft(tx, m2, DRY_30, src=src, version="v2")                       # same document, next version
    analyze_document(store(tx), str(second))
    assert [c[:2] for c in candidates(tx, old, second)] == [("apparent_contradiction", ["other_version_of_document"])]
    assert propose(tx, claim_of(tx, old), claim_of(tx, second), "contradiction") == ("err", CHECK_VIOLATION)


def test_a_supersession_chain_is_followed_to_its_end_by_the_analysis_and_the_database(tx, m2):
    """v3 -> v2 -> v1: the pipeline reads the whole chain, so its label for (v3, v1) is the database's.
    The oldest version was archived by v2's approval, so the pair is at most insufficient evidence."""
    src, first, _ = active(tx, m2, DRY_15)
    second, _ = draft(tx, m2, "Bón 60 kg/ha phân bón.", src=src, document_id="doc-2", supersedes_document_pk=first)
    approve(tx, m2, second)                                       # archives `first`
    assert tx.status_of("document", first) == "archived"
    third, _ = draft(tx, m2, DRY_30, src=src, document_id="doc-3", supersedes_document_pk=second)
    claims, documents = store(tx).comparable_claims(str(third), CLAIM_EXTRACTOR_VERSION)
    assert {d.document_pk for d in documents} == {str(first), str(second), str(third)}   # `second` has no such claim
    result = analyze_document(store(tx), str(third))
    assert result.inserted == 1
    ((classification, reasons, independence, *_),) = candidates(tx, first, third)
    assert classification == "insufficient_evidence" and independence == "same_source"
    assert reasons == ["inactive_evidence:archived", "superseded_version"]


def test_disjoint_validity_windows_are_an_apparent_contradiction(tx, m2):
    t = today(tx)
    _, current, _ = active(tx, m2, DRY_15, effective_to=t)
    future, _ = draft(tx, m2, DRY_30, effective_from=t + DAY)
    analyze_document(store(tx), str(future))
    assert [c[:2] for c in candidates(tx, current, future)] == [("apparent_contradiction", ["disjoint_validity"])]
    overlapping, _ = draft(tx, m2, DRY_30, effective_from=t)                        # both in force on day t
    analyze_document(store(tx), str(overlapping))
    assert [c[0] for c in candidates(tx, current, overlapping)] == ["contradiction"]


@pytest.mark.parametrize("how", ["quarantined", "archived", "expired", "approval_lapsed", "rejected",
                                 "source_quarantined"])
def test_inactive_material_is_at_most_insufficient_evidence(tx, m2, how):
    src_a, a, _ = active(tx, m2, DRY_15)
    b, _ = draft(tx, m2, DRY_30)
    if how in ("quarantined", "archived"):
        tx.transition("document", a, "approved", how, "fixture")
    elif how == "expired":
        force(tx, a, effective_to=today(tx) - DAY)
    elif how == "approval_lapsed":
        force(tx, a, approval_expires_on=today(tx) - DAY)
    elif how == "source_quarantined":
        tx.transition("source", src_a, "approved", "quarantined", "fixture")
    else:
        tx.transition("document", b, "review_required", "rejected", "fixture")
        a, b = b, a
    reason = {"expired": "not_in_force", "approval_lapsed": "not_in_force"}.get(how, how)
    result = analyze_document(store(tx), str(b))
    assert result.inserted == 1
    ((classification, reasons, _, state_a, state_b, _, _),) = candidates(tx, a, b)
    assert classification == "insufficient_evidence" and f"inactive_evidence:{reason}" in reasons
    assert "inactive" in (state_a, state_b)
    assert propose(tx, claim_of(tx, a), claim_of(tx, b), "contradiction") == ("err", CHECK_VIOLATION)


def test_two_inactive_versions_are_never_paired(tx, m2):
    _, a, _ = active(tx, m2, DRY_15)
    _, b, _ = active(tx, m2, DRY_30)
    for doc in (a, b):
        tx.transition("document", doc, "approved", "quarantined", "fixture")
    result = analyze_document(store(tx), str(b))
    assert result.inserted == 0 and dict(result.analysis.skipped) == {"both_inactive": 1}
    assert propose(tx, claim_of(tx, a), claim_of(tx, b), "insufficient_evidence") == ("err", CHECK_VIOLATION)


def test_an_explicit_justified_tolerance_is_recorded_with_the_candidate(tx, m2):
    _, a, _ = active(tx, m2, DRY_15)
    b, _ = draft(tx, m2, DRY_30)
    near, _ = draft(tx, m2, "Khi mực nước xuống 17 cm dưới mặt ruộng thì tưới lại.")
    tolerance = Tolerance(KEY, 3.0, "TEST FIXTURE rationale: field gauge reading error")
    assert analyze_document(store(tx), str(near), tolerances=[tolerance]).analysis.of("contradiction")[0].claim_b \
        == claim_of(tx, near)                                                      # 17 vs 30 still disagree
    assert analyze_document(store(tx), str(b), tolerances=[tolerance]).inserted == 1   # 15 vs 30 (17 vs 30 is stored)
    tx.cur.execute("select distinct tolerance::float8, tolerance_rationale from public.knowledge_contradiction_candidates"
                   " where claim_a = any(%(c)s) or claim_b = any(%(c)s)", {"c": [claim_of(tx, d) for d in (a, b, near)]})
    assert tx.cur.fetchall() == [(3.0, tolerance.rationale)]
    assert candidates(tx, a, near) == []                                            # 15 vs 17: inside the tolerance


# ================================================================== tenant isolation

def test_two_tenants_are_never_paired_and_a_tenant_pair_carries_the_tenant_scope(tx, m2):
    _, tenant_a, _ = active(tx, m2, DRY_15, visibility="tenant", org=tx.org_a)
    _, tenant_b, _ = active(tx, m2, DRY_30, visibility="tenant", org=tx.org_b)
    _, public, _ = active(tx, m2, "Khi mực nước xuống 25 cm dưới mặt ruộng thì tưới lại.")
    result = analyze_document(store(tx), str(tenant_a))
    assert dict(result.analysis.skipped) == {"scope_boundary": 1} and result.inserted == 1
    assert candidates(tx, tenant_a, tenant_b) == []
    assert propose(tx, claim_of(tx, tenant_a), claim_of(tx, tenant_b), "contradiction") == ("err", CHECK_VIOLATION)
    assert [(c[0], c[5], c[6]) for c in candidates(tx, tenant_a, public)] == [("contradiction", "tenant", tx.org_a)]
    analyze_document(store(tx), str(tenant_b))
    assert [(c[5], c[6]) for c in candidates(tx, tenant_b, public)] == [("tenant", tx.org_b)]
    # two farms of one tenant are separate too
    farm_a, _ = draft(tx, m2, DRY_15, src=tx.source(visibility="tenant", org=tx.org_a, farm=tx.farm_a))
    farm_a2, _ = draft(tx, m2, DRY_30, src=tx.source(visibility="tenant", org=tx.org_a, farm=tx.farm_a2))
    assert propose(tx, claim_of(tx, farm_a), claim_of(tx, farm_a2), "contradiction") == ("err", CHECK_VIOLATION)
    analyze_document(store(tx), str(farm_a2))
    assert candidates(tx, farm_a, farm_a2) == []
    tx.cur.execute("select farm_id from public.knowledge_contradiction_candidates where claim_a = %(c)s or claim_b = %(c)s",
                   {"c": claim_of(tx, farm_a2)})
    assert {r[0] for r in tx.cur.fetchall()} == {tx.farm_a2}                        # the more private scope


# ================================================================== no effect on retrieval or approval

def test_m4_touches_neither_retrieval_nor_the_approval_flow(tx, m2):
    tx.cur.execute("select pg_get_functiondef(p.oid) from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
                   " where n.nspname in ('public', 'private') and p.proname in ('match_knowledge_chunks_lexical',"
                   " 'knowledge_decide_document', 'knowledge_start_expert_review', 'knowledge_expire_documents',"
                   " 'enforce_knowledge_document_immutability', 'knowledge_demo_approve_document')")
    bodies = [row[0] for row in tx.cur.fetchall()]
    assert len(bodies) == 6 and not any("knowledge_claims" in b or "contradiction" in b for b in bodies)
    tx.cur.execute("select qual from pg_policies where tablename in ('knowledge_sources', 'knowledge_documents',"
                   " 'knowledge_chunks')")
    assert not any("claim" in row[0] for row in tx.cur.fetchall())
    # a version with a stored contradiction against active guidance is still approved by the M2 flow
    _, a, _ = active(tx, m2, DRY_15)
    b, chunk_b = draft(tx, m2, DRY_30)
    analyze_document(store(tx), str(b))
    approve(tx, m2, b)
    assert tx.status_of("document", b) == "approved"
    assert chunk_b in [row[3] for row in tx.as_user(tx.member, RPC, (tx.season_a, "mực nước dưới mặt ruộng", 50))[1]]
    assert window(tx, b, effective_to=today(tx)) == ("err", CHECK_VIOLATION)        # M3 rules untouched


# ================================================================== concurrency and the operator CLI

def test_concurrent_extraction_stores_each_claim_once_and_the_cli_reports_a_review_aid(capsys, monkeypatch):
    """Two operators extract one version at the same time: the unique key serialises them and each
    claim is stored once. Then the CLI runs on it. COMMITS a synthetic never-approved draft (source
    prefix kn-m4conc-) and deletes it afterwards, together with its claims (cascade)."""
    from scripts import knowledge_claims as cli

    source_id = f"kn-m4conc-{uuid.uuid4().hex[:10]}"
    text = " ".join([DRY_15, "Tưới lại sau 5 ngày giữa các lần tưới.", "Bón 1.500 kg/ha phân bón."])
    with psycopg.connect(_DB_URL, autocommit=True) as setup:
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE m4 concurrency', 'o', 'guideline', 'public')", (source_id,))
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version)"
            " values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c') returning id",
            (source_id, f"knowledge-artifacts/{'e' * 64}/d.md", "e" * 64, "f" * 64)).fetchone()[0]
        setup.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                      " values (%s, %s, 0, %s, %s)", (doc, "ab" * 10, text, "1" * 64))
    outcome: dict = {}
    try:
        with psycopg.connect(_DB_URL) as first, psycopg.connect(_DB_URL) as second:
            first.execute("set local role service_role")
            assert extract_document_claims(PsycopgClaimStore(first), str(doc)).inserted == 3   # uncommitted

            def race():
                try:
                    second.execute("set lock_timeout = '20s'")
                    second.execute("set local role service_role")
                    outcome["second"] = extract_document_claims(PsycopgClaimStore(second), str(doc)).inserted
                    second.commit()
                except psycopg.Error as exc:
                    second.rollback()
                    outcome["second"] = exc.sqlstate

            worker = threading.Thread(target=race)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the second extraction did not wait for the first one's rows"
            first.commit()
            worker.join(timeout=30)
            assert not worker.is_alive() and outcome["second"] == 0
        with psycopg.connect(_DB_URL, autocommit=True) as check:
            assert check.execute("select count(*), count(distinct claim_id), count(*) filter (where actor_role ="
                                 " 'service_role') from public.knowledge_claims where document_pk = %s",
                                 (doc,)).fetchone() == (3, 3, 3)
        assert cli.main(["--document-pk", str(doc), "--target", "local"]) == 0
        out = capsys.readouterr().out
        assert "REVIEW AID, not a verdict" in out and out.rstrip().endswith("decision = none")
        assert "claims             3 (0 new, 1 unresolved)" in out and "content_correctness = not_assessed" in out
        assert cli.main(["--document-pk", str(uuid.uuid4()), "--target", "local"]) == 1
        assert "refused [unknown_document]" in capsys.readouterr().err
        monkeypatch.setattr(cli, "target_of", lambda url, db: "abcdefghijklmnopqrst")
        assert cli.main(["--document-pk", str(doc), "--target", "local"]) == 2
        assert "local stack only" in capsys.readouterr().err
        with pytest.raises(SystemExit):
            cli.main(["--document-pk", str(doc), "--target", "abcdefghijklmnopqrst"])
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            cleanup.execute("delete from public.knowledge_chunks where document_pk = %s", (doc,))
            cleanup.execute("delete from public.knowledge_documents where id = %s", (doc,))
            cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            assert cleanup.execute("select count(*) from public.knowledge_claims where source_id = %s",
                                   (source_id,)).fetchone()[0] == 0


def test_concurrent_analysis_stores_each_candidate_once():
    """Two operators analyse the two sides of one pair at the same time: the pair key serialises
    them and the candidate is stored once. COMMITS two synthetic never-approved drafts (source prefix
    kn-m4pair-) and deletes them afterwards, together with their claims and the candidate (cascade)."""
    source_id = f"kn-m4pair-{uuid.uuid4().hex[:10]}"
    docs = []
    with psycopg.connect(_DB_URL, autocommit=True) as setup:
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE m4 pair concurrency', 'o', 'guideline', 'public')", (source_id,))
        for n, text in enumerate((DRY_15, DRY_30)):
            doc = setup.execute(
                "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
                " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version)"
                " values (%s, %s, 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c') returning id",
                (source_id, f"doc-{n}", f"knowledge-artifacts/{str(n) * 64}/d.md", str(n) * 64, "f" * 64)).fetchone()[0]
            setup.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                          " values (%s, %s, 0, %s, %s)", (doc, f"{n}c" * 10, text, str(n + 2) * 64))
            assert extract_document_claims(PsycopgClaimStore(setup), str(doc)).inserted == 1
            docs.append(doc)
    outcome: dict = {}
    try:
        with psycopg.connect(_DB_URL) as first, psycopg.connect(_DB_URL) as second:
            first.execute("set local role service_role")
            assert analyze_document(PsycopgClaimStore(first), str(docs[0])).inserted == 1       # uncommitted

            def race():
                try:
                    second.execute("set lock_timeout = '20s'")
                    second.execute("set local role service_role")
                    outcome["second"] = analyze_document(PsycopgClaimStore(second), str(docs[1])).inserted
                    second.commit()
                except psycopg.Error as exc:
                    second.rollback()
                    outcome["second"] = exc.sqlstate

            worker = threading.Thread(target=race)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the second analysis did not wait for the first one's candidate"
            first.commit()
            worker.join(timeout=30)
            assert not worker.is_alive() and outcome["second"] == 0
        with psycopg.connect(_DB_URL, autocommit=True) as check:
            assert check.execute(
                "select count(*), min(k.classification), min(k.independence), min(k.evidence_state_a || k.evidence_state_b)"
                "  from public.knowledge_contradiction_candidates k join public.knowledge_claims c on c.id = k.claim_a"
                " where c.source_id = %s", (source_id,)).fetchone() == (1, "contradiction", "same_source",
                                                                        "candidatecandidate")
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            for doc in docs:
                cleanup.execute("delete from public.knowledge_chunks where document_pk = %s", (doc,))
                cleanup.execute("delete from public.knowledge_documents where id = %s", (doc,))
            cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            assert cleanup.execute("select count(*) from public.knowledge_claims where source_id = %s",
                                   (source_id,)).fetchone()[0] == 0


# ================================================================== rollback

def test_rollback_order_is_m4_then_m3_and_m4_replays(tx, m2):
    _, a, chunk = active(tx, m2, DRY_15)
    tx.cur.execute("savepoint rb")
    tx.cur.execute("set local knowledge.m3_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="M4 is installed"):
        tx.cur.execute(_without_tx_control(M3_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="DROPS the stored claims"):
        tx.cur.execute(_without_tx_control(M4_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("set local knowledge.m4_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="M4.1 is installed"):
        tx.cur.execute(_without_tx_control(M4_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    unwind_ha(tx)                                                                   # newest first
    tx.cur.execute("set local knowledge.m4_1_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M4_1_ROLLBACK))
    tx.cur.execute("set local knowledge.m4_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M4_ROLLBACK))
    tx.cur.execute("select to_regclass('public.knowledge_claims'), to_regclass('public.knowledge_contradiction_candidates'),"
                   " to_regproc('private.knowledge_record_claims'), to_regproc('private.knowledge_classify_claim_pair'),"
                   " to_regproc('private.knowledge_document_evidence_state')")
    assert tx.cur.fetchone() == (None, None, None, None, None)
    assert tx.status_of("document", a) == "approved"                               # nothing else changed
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "mực nước dưới mặt ruộng")
    tx.cur.execute(M4.read_text(encoding="utf-8"))                                  # replay
    assert extract_document_claims(store(tx), str(a)).inserted == 1
