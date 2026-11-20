"""RAG V1.5 M7 E5.2 (migration 20261120120000): pin generations, generation-bound evidence, admission-aware retrieval,
safe rollback and the re-pin impact assessment, on the database.

TEST ONLY: every text, identity, reviewer, disposition and approval is a SYNTHETIC FIXTURE. Each test is one rolled-
back transaction, except `test_concurrent_pin_changes_serialize_and_each_is_a_generation`, which commits two pin
UPDATEs that keep the committed pin values (only the generation moves). Skipped without SUPABASE_DB_URL. dev3-01 stays
OPEN; nothing here is a scientific approval. BLOCKED FOR HOSTED.
"""

from __future__ import annotations

import os
import re
import threading
import time

import pytest

from infrastructure import integrity_verifier as iv
from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION
from recommendation.rag.answers import INSUFFICIENT_MESSAGES
from scripts.knowledge_repin_impact import assess
from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_kn_claims_4_transition import OLD, OLD_DIGEST, pin
from tests.test_rag_knowledge_m2_approval import as_role, code, draft, m2  # noqa: F401
from tests.test_rag_knowledge_m3_validity import version
from tests.test_rag_knowledge_m7_e5_1_pin_admission import (SPELLED_ZERO_POISON, CapturingModel, approve_now,
                                                             approve_under_kn3, legacy_rows, problem, real_pin,
                                                             status_for)
from tests.test_rag_knowledge_m7_e5_answer_time import AWD_TEXT, EQ_DOC, STATE_PIN, DbReader, ask
from tests.test_rag_knowledge_status_events import E5_2_ROLLBACK, ROOT, _without_tx_control
from tests.test_rag_knowledge_storage import CHECK_VIOLATION, PERMISSION_DENIED, psycopg, pytestmark, tx  # noqa: F401

__all__ = ["pytestmark", "tx", "m2"]

E5_2_MIGRATION = ROOT / "supabase/migrations/20261120120000_knowledge_pin_generation_e5_2.sql"
HA_MIGRATION = ROOT / "supabase/migrations/20261113090000_knowledge_m2_hardening_assurance.sql"
GEN = "select generation from private.knowledge_integrity_policy"
LOG = "select generation, reason from private.knowledge_integrity_pin_generations order by generation"
ROLES = ("anon", "authenticated", "service_role")


def gen(tx):
    tx.cur.execute(GEN)
    return tx.cur.fetchone()[0]


def log(tx, since=0):
    tx.cur.execute(LOG)
    return [r for r in tx.cur.fetchall() if r[0] > since]


def current_tuple(tx):
    tx.cur.execute("select extractor_version, review_version, registry_version, registry_digest, extractor_code_digest,"
                   " attestation_mode from private.knowledge_integrity_policy")
    return tx.cur.fetchone()


def repin_same(tx):
    """The owner re-pins the CURRENT tuple (A -> A): one generation per owner call."""
    ev, rv, regv, regd, code_digest, mode = current_tuple(tx)
    tx.cur.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)", (ev, rv, regv, regd))
    tx.cur.execute("select private.knowledge_set_integrity_code_digest(%s)", (code_digest,))
    tx.cur.execute("select private.knowledge_set_attestation_mode(%s)", (mode,))


def clean_doc(tx, m2, content=AWD_TEXT, **kw):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, content, doc_version="v1", **kw)
    return doc, src, chunk


def retrieved(tx, query="tưới ngập khô xen kẽ mê-tan", top_k=50):
    return [r[3] for r in tx.rpc(tx.member, tx.season_a, query, top_k)]


# ================================================================== B: the epoch

def test_every_pin_update_is_a_new_logged_generation_and_a_supplied_value_is_ignored(tx):
    g0 = gen(tx)
    real_pin(tx)                                                  # policy, code digest, (attestation if missing)
    g1 = gen(tx)
    assert g1 > g0 and [r[0] for r in log(tx, g0)] == list(range(g0 + 1, g1 + 1))
    assert {r[1] for r in log(tx, g0)} == {"pin_change"}
    repin_same(tx)                                                 # A -> A: three owner calls, three generations
    assert gen(tx) == g1 + 3
    tx.cur.execute("update private.knowledge_integrity_policy set generation = 1")   # an owner trying to lower it
    assert gen(tx) == g1 + 4
    # the log states exactly what the pin row was at each generation
    tx.cur.execute("select extractor_version, extractor_code_digest, complete from private.knowledge_integrity_pin_generations"
                   " where generation = %s", (gen(tx),))
    assert tx.cur.fetchone() == (CLAIM_EXTRACTOR_VERSION, iv.extractor_code_digest(), True)


def test_the_pin_row_and_its_log_are_append_only_even_for_the_owner(tx):
    g = gen(tx)
    for sql in ("delete from private.knowledge_integrity_policy",
                "truncate private.knowledge_integrity_policy",
                "update private.knowledge_integrity_pin_generations set reason = 'pin_change'",
                "delete from private.knowledge_integrity_pin_generations",
                "truncate private.knowledge_integrity_pin_generations"):
        tx.cur.execute("savepoint s")
        with pytest.raises(psycopg.Error) as exc:
            tx.cur.execute(sql)
        assert exc.value.sqlstate == PERMISSION_DENIED, sql
        tx.cur.execute("rollback to savepoint s")
    # a forged log row is refused BY THE GUARD (generations not yet used, so no primary-key collision can mask it):
    # a future generation, and the next one with a tuple that is not the pin row's
    for forged in (g + 1, g + 7):
        tx.cur.execute("savepoint s")
        with pytest.raises(psycopg.Error) as exc:
            tx.cur.execute("insert into private.knowledge_integrity_pin_generations (generation, extractor_version,"
                           " complete, reason) values (%s, 'kn-forged', false, 'pin_change')", (forged,))
        assert exc.value.sqlstate == PERMISSION_DENIED and "must state the current pin row" in str(exc.value)
        tx.cur.execute("rollback to savepoint s")
    assert gen(tx) == g


def test_a_failed_pin_change_consumes_no_generation(tx):
    g, before = gen(tx), log(tx)
    tx.cur.execute("savepoint failing_change")
    real_pin(tx)
    assert gen(tx) > g
    tx.cur.execute("rollback to savepoint failing_change")          # the transaction fails after the change
    assert gen(tx) == g and log(tx) == before


@pytest.mark.parametrize("role", [*ROLES, "knowledge_integrity_verifier"])
def test_no_client_or_verifier_role_can_move_the_pin_the_generation_or_the_log(tx, m2, role):
    m2.grant_verifier_to_self()
    reg = paths.integrity_registry()
    for sql, params in (("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                         (CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, reg.registry_version, reg.digest)),
                        ("select private.knowledge_set_integrity_code_digest(%s)", ("5" * 64,)),
                        ("select private.knowledge_set_attestation_mode(%s)", ("offline_signature_audit",)),
                        ("update private.knowledge_integrity_policy set generation = generation + 1", ()),
                        ("select generation from private.knowledge_integrity_policy", ()),
                        ("insert into private.knowledge_integrity_pin_generations (generation, complete, reason)"
                         " values (999999, false, 'pin_change')", ()),
                        ("select * from private.knowledge_corpus_integrity_inventory()", ())):
        assert as_role(tx, role, sql, params)[0] == "err", (role, sql)
    for table in ("knowledge_integrity_reports", "knowledge_integrity_verifications", "knowledge_approval_records"):
        assert as_role(tx, role, f"update public.{table} set pin_generation = 1", ())[0] == "err", (role, table)


def test_stamps_come_from_the_pin_row_and_cannot_be_changed(tx, m2):
    doc, _, _ = clean_doc(tx, m2)
    g = gen(tx)
    tx.cur.execute("select r.pin_generation, v.pin_generation, a.pin_generation"
                   " from public.knowledge_integrity_reports r"
                   " join public.knowledge_integrity_verifications v on v.report_id = r.id"
                   " join public.knowledge_approval_records a on a.document_pk = r.document_pk and a.decision = 'approve'"
                   " where r.document_pk = %s", (doc,))
    assert tx.cur.fetchall() == [(g, g, g)]
    # even the owner cannot rewrite a stamp (the evidence guards refuse any update outside the M2 steps)
    for table in ("knowledge_integrity_reports", "knowledge_integrity_verifications", "knowledge_approval_records"):
        tx.cur.execute("savepoint s")
        with pytest.raises(psycopg.Error) as exc:
            tx.cur.execute(f"update public.{table} set pin_generation = pin_generation + 1 where document_pk = %s",
                           (doc,))
        assert exc.value.sqlstate == PERMISSION_DENIED, table
        tx.cur.execute("rollback to savepoint s")
    # the frozen-stamp trigger on its own (side-agent review: the evidence guards above would mask its absence)
    for table, guard in (("knowledge_integrity_reports", "knowledge_integrity_reports_guard"),
                         ("knowledge_integrity_verifications", "knowledge_integrity_verifications_guard"),
                         ("knowledge_approval_records", "knowledge_approval_records_guard")):
        tx.cur.execute("savepoint s")
        tx.cur.execute(f"alter table public.{table} disable trigger {guard}")
        with pytest.raises(psycopg.Error) as exc:
            tx.cur.execute(f"update public.{table} set pin_generation = pin_generation + 1 where document_pk = %s",
                           (doc,))
        assert exc.value.sqlstate == PERMISSION_DENIED and "written once" in str(exc.value), table
        tx.cur.execute("rollback to savepoint s")


def test_a_report_or_verification_whose_tuple_is_not_the_pinned_one_is_refused_by_the_stamp(tx, m2):
    """The stamp re-reads the pin row under a share lock: a row produced against another tuple (a pin change racing the
    insert) is refused rather than stamped with a generation whose tuple it was not made under."""
    real_pin(tx)
    _, doc = draft(tx, m2, content=AWD_TEXT)
    report, _ = m2.integrity_report(doc)
    tx.cur.execute("select private.knowledge_m2_set_marker('knowledge_integrity_reports')")
    tx.cur.execute("savepoint s")
    with pytest.raises(psycopg.Error) as exc:
        tx.cur.execute("insert into public.knowledge_integrity_reports (document_pk, source_id, document_id,"
                       " document_version, document_snapshot_sha256, source_snapshot_sha256, file_sha256,"
                       " normalized_sha256, chunk_manifest_sha256, chunk_count, extractor_version, review_version,"
                       " registry_version, registry_digest, claim_count, finding_count, blocking_count, supported_claims,"
                       " limitations, report_sha256, actor_role, session_user_name, pin_generation)"
                       " select document_pk, source_id, document_id, document_version, document_snapshot_sha256,"
                       " source_snapshot_sha256, file_sha256, normalized_sha256, chunk_manifest_sha256, chunk_count,"
                       " 'kn-claims-racing', review_version, registry_version, registry_digest, claim_count,"
                       " finding_count, blocking_count, supported_claims, limitations, %s, actor_role,"
                       " session_user_name, 424242 from public.knowledge_integrity_reports where id = %s",
                       ("f" * 64, report))
    assert exc.value.sqlstate == CHECK_VIOLATION and "pin changed" in str(exc.value)
    tx.cur.execute("rollback to savepoint s")


# ================================================================== P1: no re-activation

def test_a_b_a_never_revives_an_approval(tx, m2, monkeypatch):
    doc, src, chunk = clean_doc(tx, m2)
    a = current_tuple(tx)
    assert problem(tx, doc) is None and chunk in retrieved(tx)
    pin(tx, "kn-claims-next-fixture", "9" * 64)                     # B
    reg = paths.integrity_registry()
    tx.cur.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)", a[:4])     # back to A, exactly
    tx.cur.execute("select private.knowledge_set_integrity_code_digest(%s)", (a[4],))
    tx.cur.execute("select private.knowledge_set_attestation_mode(%s)", (a[5],))
    assert current_tuple(tx) == a and reg.digest == a[3]
    assert problem(tx, doc) == "report_from_earlier_generation"
    assert status_for(tx, chunk) == ["not_current"] and legacy_rows(tx, chunk) == []
    assert chunk not in retrieved(tx)                               # retrieval no longer ranks it at all
    body, reader = ask(tx, (src, chunk), model=CapturingModel((src, chunk)))
    assert (body["status"], body["insufficient_reason"], body["citations"]) == \
        ("insufficient_evidence", "no_integrity_current_evidence", [])
    # nothing was retrieved, so gate 1 never ran and the model was never called
    assert reader.__dict__.get("admissions", 0) == 0 and body["answer"] == INSUFFICIENT_MESSAGES["no_integrity_current_evidence"]
    # E5.1's tuple-era case (kn-claims-3 approval, pin moved away and back) is not revived either
    old, _, old_chunk = approve_under_kn3(tx, m2, monkeypatch, AWD_TEXT)
    real_pin(tx)
    pin(tx, OLD, OLD_DIGEST)
    assert problem(tx, old) == "report_from_earlier_generation" and old_chunk not in retrieved(tx)


def test_an_explicit_identical_re_pin_suspends_and_a_new_version_restores(tx, m2):
    doc, src, chunk = clean_doc(tx, m2)
    repin_same(tx)
    assert problem(tx, doc) == "report_from_earlier_generation" and chunk not in retrieved(tx)
    new, new_chunk = approve_now(tx, m2, src, AWD_TEXT + " Bản rà soát lại.", doc_version="v2",
                                 supersedes_document_pk=doc)
    assert problem(tx, new) is None and new_chunk in retrieved(tx)
    body, _ = ask(tx, (src, new_chunk))
    assert body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [new_chunk]


def test_cross_generation_replay_of_a_report_or_verification_is_refused(tx, m2):
    real_pin(tx)
    _, doc = draft(tx, m2, content=AWD_TEXT)
    review = m2.start(doc)
    report, sha = m2.integrity_report(doc)
    m2.dispose(review, sha, None, "report_reviewed")
    m2.verify_report(report)                                        # verified in generation G
    repin_same(tx)                                                  # G -> G+3, same tuple
    tx.cur.execute("select private.knowledge_integrity_report_problem(r) from public.knowledge_integrity_reports r"
                   " where r.id = %s", (report,))
    assert "earlier pin generation" in tx.cur.fetchone()[0]
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    assert tx.status_of("document", doc) != "approved"


def test_missing_generations_are_never_current(tx, m2):
    doc, _, chunk = clean_doc(tx, m2)

    def owner_null(table, where):
        tx.cur.execute(f"alter table public.{table} disable trigger user")
        tx.cur.execute(f"update public.{table} set pin_generation = null where {where}", (doc,))
        tx.cur.execute(f"alter table public.{table} enable trigger user")

    owner_null("knowledge_approval_records", "document_pk = %s")
    assert problem(tx, doc) == "approval_from_earlier_generation" and chunk not in retrieved(tx)
    owner_null("knowledge_integrity_reports", "document_pk = %s")
    assert problem(tx, doc) == "generation_missing" and status_for(tx, chunk) == ["not_current"]


# ================================================================== concurrency (committed, two sessions)

def test_concurrent_pin_changes_serialize_and_each_is_a_generation():
    url = os.environ["SUPABASE_DB_URL"]
    with psycopg.connect(url) as first, psycopg.connect(url) as second:
        tuple_sql = "select extractor_version, review_version, registry_version, registry_digest," \
                    " generation from private.knowledge_integrity_policy"
        ev, rv, regv, regd, g0 = first.execute(tuple_sql).fetchone()
        first.commit()
        same = "select private.knowledge_set_integrity_policy(%s, %s, %s, %s)"
        first.execute(same, (ev, rv, regv, regd))                     # holds the pin row lock, uncommitted
        result = {}

        def contender():
            try:
                second.execute("set lock_timeout = '20s'")
                started = time.monotonic()
                second.execute(same, (ev, rv, regv, regd))
                result["waited"] = time.monotonic() - started
                result["gen"] = second.execute("select generation from private.knowledge_integrity_policy").fetchone()[0]
                second.commit()
            except Exception as exc:  # noqa: BLE001 - reported below
                result["error"] = exc
                second.rollback()

        thread = threading.Thread(target=contender)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive()                                      # blocked on the pin row
        first.commit()
        thread.join(30)
        assert "error" not in result, result
        assert result["gen"] == g0 + 2 and result["waited"] >= 0.5
        rows = first.execute("select generation, reason, extractor_version from private.knowledge_integrity_pin_generations"
                             " where generation > %s order by generation", (g0,)).fetchall()
        assert rows == [(g0 + 1, "pin_change", ev), (g0 + 2, "pin_change", ev)]
        first.commit()


# ================================================================== P3: retrieval starvation

def baseline_rpc(tx):
    """H-a's retrieval function (no generation predicate) as pg_temp.match_e5_1_baseline: what E5.1 retrieved."""
    text = HA_MIGRATION.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = [m.start() for m in re.finditer(r"^create or replace function public\.match_knowledge_chunks_lexical\(",
                                            text, re.M)][-1]
    body = text[start:text.index("\n$$;\n", start) + 5]
    tx.cur.execute(body.replace("public.match_knowledge_chunks_lexical(", "pg_temp.match_e5_1_baseline(", 1))


def starved_corpus(tx, m2, n_stale):
    """`n_stale` versions approved in an earlier generation whose chunks match the query better than the one clean
    version approved after the owner re-pinned."""
    real_pin(tx)
    stale = []
    for i in range(n_stale):
        src = tx.source()
        _, chunk = approve_now(tx, m2, src, f"tưới ngập khô xen kẽ mê-tan tưới ngập khô xen kẽ lúa ruộng {i}",
                               doc_version="v1", document_id=f"stale-{i}")
        stale.append(chunk)
    repin_same(tx)
    src = tx.source()
    clean_pk, clean = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1", document_id="clean")
    return stale, clean, src


def test_stale_chunks_no_longer_starve_retrieval(tx, m2):
    stale, clean, src = starved_corpus(tx, m2, 10)
    baseline_rpc(tx)
    query = "tưới ngập khô xen kẽ mê-tan"
    status, rows = tx.as_user(tx.member, "select chunk_id from pg_temp.match_e5_1_baseline(%s, %s, 8)",
                              (tx.season_a, query))
    assert status == "ok"
    e51 = [r[0] for r in rows]
    assert clean not in e51 and len(set(e51) & set(stale)) == 8     # E5.1: top_k all stale, the clean chunk unseen
    e52 = [r[3] for r in tx.rpc(tx.member, tx.season_a, query, 8)]
    assert clean in e52 and not set(e52) & set(stale)               # E5.2: only admitted versions are ranked
    body, reader = ask(tx, (src, clean))
    assert body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [clean]
    assert reader.admissions == 1


def test_admission_aware_retrieval_keeps_tenant_scope_and_reveals_nothing(tx, m2):
    real_pin(tx)
    src_b, doc_b = draft(tx, m2, visibility="tenant", org=tx.org_b, content=AWD_TEXT)
    review = m2.start(doc_b)
    m2.submit(review)
    m2.decide(review, tx.approver)
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (doc_b,))
    chunk_b = tx.cur.fetchone()[0]
    assert chunk_b not in retrieved(tx)                              # org A's member, org A's season
    assert chunk_b in [r[3] for r in tx.rpc(tx.outsider, tx.season_b, "tưới ngập khô xen kẽ mê-tan", 50)]
    status, rows = tx.as_user(tx.member, "select * from private.knowledge_generation_admitted_documents(%s)",
                              (tx.season_b,))                          # another tenant's season: nothing
    assert (status, rows) == ("ok", [])
    status, rows = tx.as_user(tx.member, "select * from private.knowledge_generation_admitted_documents(%s)",
                              (tx.season_a,))
    assert doc_b not in [r[0] for r in rows]
    assert as_role(tx, "anon", "select * from private.knowledge_generation_admitted_documents(%s)",
                   (tx.season_a,)) == ("err", PERMISSION_DENIED)


def test_version_skew_an_older_backend_cannot_admit_a_previous_generation(tx, m2):
    doc, src, chunk = clean_doc(tx, m2)
    repin_same(tx)
    assert chunk not in retrieved(tx)                                # pre-E5 backend: retrieval only
    assert legacy_rows(tx, chunk) == []                              # E5 backend: three-argument recheck
    status, rows = tx.as_user(tx.member, STATE_PIN, (tx.season_a, [chunk], False))
    assert [r[0]["integrity_status"] for r in rows] == ["not_current"]   # E5.1 backend


def test_e3_containment_and_the_quarantine_path_are_unchanged(tx, m2):
    from tests.test_rag_knowledge_m7_e5_answer_time import mistaken_expert_approval
    real_pin(tx)
    doc, src, chunk, _ = mistaken_expert_approval(tx, m2)
    assert chunk in retrieved(tx)                                   # admitted in this generation, still contested
    body, _ = ask(tx, (src, chunk))
    assert body["insufficient_reason"] == "evidence_integrity_contested"
    as_role(tx, "service_role", EQ_DOC, (doc, "harmful_content_report", "TEST FIXTURE: E5.2 quarantine", "TEST-E52"))
    assert chunk not in retrieved(tx)


# ================================================================== C: safe rollback rehearsal

def test_the_rollback_refuses_without_acknowledgement(tx):
    tx.cur.execute("savepoint s")
    with pytest.raises(psycopg.Error) as exc:
        tx.cur.execute(_without_tx_control(E5_2_ROLLBACK))
    assert exc.value.sqlstate == "55000" and "safe-refusal-acknowledged" in str(exc.value)
    tx.cur.execute("rollback to savepoint s")
    tx.cur.execute("select to_regprocedure('private.knowledge_stamp_pin_generation()') is not null")
    assert tx.cur.fetchone()[0] is True


def test_the_rollback_ends_in_safe_refusal_keeps_the_audit_and_a_re_apply_never_reuses_a_generation(tx, m2):
    doc, src, chunk = clean_doc(tx, m2)
    g = gen(tx)
    tx.cur.execute("select count(*) from private.knowledge_integrity_pin_generations")
    log_rows = tx.cur.fetchone()[0]
    tx.cur.execute("set local knowledge.e5_2_rollback = 'safe-refusal-acknowledged'")
    tx.cur.execute(_without_tx_control(E5_2_ROLLBACK))
    # safe refusal: pin cleared as a final logged generation; nothing is retrievable or admissible
    assert current_tuple(tx) == (None,) * 6 and gen(tx) == g + 1
    assert log(tx, g) == [(g + 1, "schema_rollback_unpinned")]
    assert chunk not in retrieved(tx) and status_for(tx, chunk) == ["not_current"]
    assert ask(tx, (src, chunk))[0]["insufficient_reason"] == "no_integrity_current_evidence"
    # audit kept: log rows, stamps and the generation column
    tx.cur.execute("select count(*) from private.knowledge_integrity_pin_generations")
    assert tx.cur.fetchone()[0] == log_rows + 1
    tx.cur.execute("select pin_generation from public.knowledge_integrity_reports where document_pk = %s", (doc,))
    assert tx.cur.fetchone()[0] == g
    # rolled-back period: E5.1 rules approve again, but nothing new is stamped, so nothing is served
    real_pin(tx)
    assert gen(tx) == g + 1                                         # no bump without E5.2
    src2 = tx.source()
    mid, mid_chunk = approve_now(tx, m2, src2, AWD_TEXT, doc_version="v1", document_id="during-rollback")
    assert tx.status_of("document", mid) == "approved" and mid_chunk not in retrieved(tx)
    assert chunk not in retrieved(tx)                               # the old approval is not revived by the re-pin
    # re-apply E5.2: a generation above every recorded one; nothing before it becomes current
    tx.cur.execute(E5_2_MIGRATION.read_text(encoding="utf-8"))
    assert gen(tx) == g + 2 and log(tx, g + 1) == [(g + 2, "migration_apply")]
    assert problem(tx, doc) == "report_from_earlier_generation" and problem(tx, mid) == "generation_missing"
    assert chunk not in retrieved(tx) and mid_chunk not in retrieved(tx)
    # recovery: a new version reviewed in the new generation is served
    new, new_chunk = approve_now(tx, m2, src, AWD_TEXT + " Bản sau khi khôi phục.", doc_version="v2",
                                 supersedes_document_pk=doc)
    assert problem(tx, new) is None and new_chunk in retrieved(tx)


# ================================================================== D: re-pin impact assessment

def test_the_impact_assessment_classifies_without_writing(tx, m2, monkeypatch):
    kn3_changed, _, _ = approve_under_kn3(tx, m2, monkeypatch, SPELLED_ZERO_POISON)
    kn3_same, _, _ = approve_under_kn3(tx, m2, monkeypatch, AWD_TEXT)
    real_pin(tx)                                                    # one re-pin: both kn-claims-3 approvals stale
    current, _ = approve_now(tx, m2, tx.source(), AWD_TEXT, doc_version="v1", document_id="current")
    quarantined, _ = approve_now(tx, m2, tx.source(), AWD_TEXT + " Bản sẽ bị cách ly.", doc_version="v1",
                                 document_id="quarantined")
    as_role(tx, "service_role", EQ_DOC, (quarantined, "harmful_content_report", "TEST FIXTURE: impact", "TEST-E52-I"))
    _, in_review = draft(tx, m2, content="TEST FIXTURE: phiên bản đang chờ duyệt")
    tx.cur.execute("select count(*) from public.knowledge_claims")
    claims_before = tx.cur.fetchone()[0]
    report = assess(tx.cur, registry=paths.integrity_registry())
    rows = {r["document_pk"]: set(r["categories"]) for r in report["rows"]}
    assert rows[str(current)] == {"current_under_existing_pin", "will_become_stale", "claim_set_unchanged"}
    assert {"not_current_now", "missing_evidence", "claim_set_changed", "needs_expert_review"} <= rows[str(kn3_changed)]
    assert {"not_current_now", "missing_evidence", "claim_set_unchanged"} <= rows[str(kn3_same)]
    assert "needs_expert_review" not in rows[str(kn3_same)]
    assert rows[str(quarantined)] == {"inaccessible_or_blocked"} and rows[str(in_review)] == {"in_review"}
    summary = report["summary"]
    assert summary["admissible_after_any_re_pin"] == 0 and summary["database"] == "local"
    assert "not a production-scale estimate" in summary["scale_note"]
    assert summary["current_under_existing_pin"] >= 1 and summary["will_become_stale"] == summary["current_under_existing_pin"]
    tx.cur.execute("select count(*) from public.knowledge_claims")
    assert tx.cur.fetchone()[0] == claims_before                    # offline only: nothing written
    for row in report["rows"]:                                      # ids and categories only, never text
        assert set(row) <= {"document_pk", "source_id", "admission_problem", "categories", "offline"}


def test_the_impact_script_runs_read_only_on_the_local_stack_and_refuses_hosted(monkeypatch, capsys):
    import json

    from scripts import knowledge_repin_impact as impact
    assert impact.main(["--target", "local"]) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["database"] == "local" and summary["admissible_after_any_re_pin"] == 0
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres:x@db.example.supabase.co:5432/postgres")
    assert impact.main(["--target", "local"]) == 2
    assert "local stack only" in capsys.readouterr().err


def test_re_running_the_migration_on_an_e5_2_database_logs_one_new_generation(tx):
    """Side-agent review finding (2026-11-20): a re-run without the rollback must not double-log the bump."""
    g = gen(tx)
    tx.cur.execute(E5_2_MIGRATION.read_text(encoding="utf-8"))
    assert gen(tx) == g + 1 and log(tx, g) == [(g + 1, "migration_apply")]
    real_pin(tx)                                                    # the triggers are back: a change is logged
    assert all(reason == "pin_change" for _, reason in log(tx, g + 1)) and gen(tx) > g + 1


def test_the_inventory_never_reports_an_unapproved_version_as_admitted(tx, m2):
    """Side-agent review finding (2026-11-20): NULL means admitted, so a version that is not approved+verified must
    carry an explicit reason."""
    _, doc = draft(tx, m2, content="TEST FIXTURE: phiên bản chưa duyệt")
    tx.cur.execute("select admission_problem from private.knowledge_corpus_integrity_inventory() where document_pk = %s",
                   (doc,))
    assert tx.cur.fetchone()[0] == "not_approved"


# ================================================================== the explanation signal (side-agent note 2026-11-20)

AWAITING = "select awaiting from public.knowledge_evidence_awaiting_recheck(%s)"


def awaiting(tx, user, season):
    status, rows = tx.as_user(user, AWAITING, (season,))
    assert status == "ok", rows
    return rows[0][0]


def test_the_awaiting_signal_is_one_boolean_for_the_callers_own_scope(tx, m2):
    real_pin(tx)
    src_b, doc_b = draft(tx, m2, visibility="tenant", org=tx.org_b, content=AWD_TEXT)
    review = m2.start(doc_b)
    m2.submit(review)
    m2.decide(review, tx.approver)
    # baseline: whatever the committed corpus holds is admitted, or nothing is approved at all
    before_a = awaiting(tx, tx.member, tx.season_a)
    assert awaiting(tx, tx.outsider, tx.season_b) is before_a        # org B's own version is admitted
    repin_same(tx)                                                   # org B's version is now suspended
    assert awaiting(tx, tx.outsider, tx.season_b) is True            # org B learns its own scope awaits a re-check
    assert awaiting(tx, tx.member, tx.season_a) is before_a          # org A learns nothing about org B
    assert awaiting(tx, tx.member, tx.season_b) is False             # an unreadable season says nothing
    assert as_role(tx, "anon", AWAITING, (tx.season_a,)) == ("err", PERMISSION_DENIED)
    assert as_role(tx, "authenticated", "select private.knowledge_scope_has_suspended_evidence(%s)",
                   (tx.season_a,))[0] == "ok"                          # callable only through RLS-scoped arguments


def test_without_the_signal_or_when_it_fails_the_answer_is_still_refused_with_the_generic_copy(tx, m2):
    doc, src, chunk = clean_doc(tx, m2)
    repin_same(tx)

    class NoSignal(DbReader):
        def knowledge_evidence_awaiting_recheck(self, season_id):
            raise RuntimeError("TEST FIXTURE: signal unavailable")

    body, _ = ask(tx, (src, chunk), reader=NoSignal(tx, tx.member, tx.season_a))
    assert (body["status"], body["insufficient_reason"], body["citations"], body["recommendations"]) == \
        ("insufficient_evidence", "no_evidence_retrieved", [], [])
