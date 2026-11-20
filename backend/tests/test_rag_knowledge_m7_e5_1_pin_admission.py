"""RAG V1.5 M7 E5.1 (migration 20261120090000): pin-aware evidence admission, end to end on the database.

Owner decisions 2026-11-20: D-E5-PIN (evidence evaluated under an obsolete integrity pin is not automatically
admissible), D-REVIEW (an affected approved original gets a NEW VERSION reviewed again; the original and its audit
history stay), D-ROLLOUT (local/CI only). The REAL `RagQuestionService` runs with a scripted model (no provider);
retrieval, gate 1 (before the model) and gate 2 (answer time) run under the member's JWT.

"kn-claims-3 build": this tree only holds kn-claims-4. `kn3_build` stands for a verifier deployment of the previous
extractor by patching, in this process only, what the verifier reports about itself (extractor version, manifest
digest) and the one rule that changed (kn-claims-3 dropped a spelled-out zero; the stand-in drops every assertion,
exactly like `kn3_report` of test_rag_knowledge_kn_claims_4_transition.py). It signs with the synthetic test key.

TEST ONLY: every text, identity, reviewer, disposition and approval is a SYNTHETIC FIXTURE in one rolled-back
transaction. Nothing here is a scientific approval. Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import contextlib

import pytest

from tests.test_rag_knowledge_storage import psycopg  # noqa: E402

from infrastructure import integrity_verifier as iv
from knowledge.integrity import verifier as kv
from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION, extract_claims
from recommendation.rag import RagIntent
from recommendation.rag.answers import INSUFFICIENT_MESSAGES
from scripts.knowledge_pin_reextraction_inventory import classify
from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_ha_assurance import ISOLATED
from tests.test_rag_knowledge_kn_claims_4_transition import OLD, OLD_DIGEST, kn3_report, pin
from tests.test_rag_knowledge_m2_approval import as_role, code, draft, m2  # noqa: F401
from tests.test_rag_knowledge_m3_validity import version, window
from tests.test_rag_knowledge_m7_e5_answer_time import (AWD_TEXT, EVIDENCE_QUESTION, QUESTION, STATE, WHAT_IF_QUESTION,
                                                         DbReader, ScriptedModel, TxSink, WhatIfModel, ask)
from tests.test_rag_knowledge_storage import CHECK_VIOLATION, PERMISSION_DENIED, pytestmark, tx  # noqa: F401

__all__ = ["pytestmark", "tx", "m2"]

#: The previously approved poison: a spelled-out zero kn-claims-3 did not read as an elimination claim.
SPELLED_ZERO_POISON = AWD_TEXT + " Áp dụng tưới ngập khô xen kẽ một vụ thì phát thải khí mê-tan bằng không."
STATE_ALL = "select to_jsonb(r) from public.knowledge_cited_evidence_state(%s, %s, %s, true) r"
STATUS = "select * from private.knowledge_cited_integrity_status(%s, %s, %s)"
NEXT = "kn-claims-next-fixture"            # a later extractor the owner might pin (no such code exists)


@contextlib.contextmanager
def kn3_build(monkeypatch):
    """The verifier as the kn-claims-3 deployment ran it (see the module docstring). TEST ONLY."""
    real = extract_claims
    with monkeypatch.context() as mp:
        mp.setattr(iv, "CLAIM_EXTRACTOR_VERSION", OLD)
        mp.setattr(iv, "extractor_code_digest", lambda: OLD_DIGEST)
        mp.setattr(kv, "CLAIM_EXTRACTOR_VERSION", OLD)
        mp.setattr(kv, "extract_claims", lambda source: [c for c in real(source) if c.kind != "assertion"])
        yield


def real_pin(tx):
    """The pin of THIS tree's extractor and verifier build (kn-claims-4)."""
    pin(tx, CLAIM_EXTRACTOR_VERSION, iv.extractor_code_digest())


def approve_under_kn3(tx, m2, monkeypatch, content, *, src=None, doc_version="v1", document_id="doc"):
    """A version reviewed and approved while the owner's pin was kn-claims-3: its report and its signed
    verification are kn-claims-3 ones. Returns (doc, source_id, chunk_id)."""
    if src is None:
        src, doc = draft(tx, m2, content=content)
    else:
        doc, _ = version(tx, m2, src, version=doc_version, document_id=document_id, content=content)
    review = m2.start(doc)
    pin(tx, OLD, OLD_DIGEST)
    with kn3_build(monkeypatch):
        kn3_report(tx, doc)
        m2.submit(review)                                      # acknowledges the kn-claims-3 report + verifies it
        m2.decide(review, tx.approver)
    assert tx.status_of("document", doc) == "approved"
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (doc,))
    return doc, src, tx.cur.fetchone()[0]


def approve_now(tx, m2, src, content, *, doc_version, document_id="doc", **cols):
    """A new version under the CURRENT pin through the real path (kn-claims-4 claims, report, signed verification,
    acknowledgement, approval). Returns (doc, chunk_id)."""
    doc, chunk = version(tx, m2, src, version=doc_version, document_id=document_id, content=content, **cols)
    review = m2.start(doc)
    m2.submit(review)
    m2.decide(review, tx.approver)
    return doc, chunk


def problem(tx, doc):
    tx.cur.execute("select private.knowledge_integrity_admission_problem(%s)", (doc,))
    return tx.cur.fetchone()[0]


def status_for(tx, chunk, *, user=None, season=None, demo=False):
    status, rows = tx.as_user(user or tx.member, STATE_ALL, (season or tx.season_a, [chunk], demo))
    assert status == "ok", rows
    return [r[0]["integrity_status"] for r in rows]


def legacy_rows(tx, chunk):
    """What an E5 backend (three arguments, no E5.1 code) sees: a not-current row is not returned at all."""
    status, rows = tx.as_user(tx.member, STATE, (tx.season_a, [chunk], False))
    assert status == "ok", rows
    return [r[0]["chunk_id"] for r in rows]


class CapturingModel(ScriptedModel):
    """ScriptedModel that keeps the request it was sent (to prove what entered the model context)."""

    def __init__(self, cite, **kw):
        super().__init__(cite, **kw)
        self.users = []

    def complete_json(self, *, system, user, schema):
        self.users.append(user)
        return super().complete_json(system=system, user=user, schema=schema)


class CapturingWhatIf(WhatIfModel):
    def __init__(self):
        super().__init__(None)
        self.users = []

    def complete_json(self, *, system, user, schema):
        self.users.append(user)
        return super().complete_json(system=system, user=user, schema=schema)


def generated_citing(body, chunk):
    return body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [chunk]


def gate1_refused(body):
    return (body["status"], body["insufficient_reason"], body["recommendations"], body["citations"],
            body["answer"]) == ("insufficient_evidence", "no_integrity_current_evidence", [], [],
                                INSUFFICIENT_MESSAGES["no_integrity_current_evidence"])


# ================================================================== D1-D2: old pin / new pin, old report

def test_old_pin_old_report_is_admissible_and_the_kn3_approval_even_cites_the_spelled_zero(tx, m2, monkeypatch):
    doc, src, chunk = approve_under_kn3(tx, m2, monkeypatch, SPELLED_ZERO_POISON)
    assert problem(tx, doc) is None and status_for(tx, chunk) == ["current"]
    model = CapturingModel((src, chunk))
    body, reader = ask(tx, (src, chunk), model=model)
    # under the kn-claims-3 pin the poison has no finding at all: this is the gap the re-pin closes
    assert generated_citing(body, chunk) and model.calls == 1 and reader.admissions == 1 and reader.rechecks == 1


def test_new_pin_old_report_previously_approved_spelled_zero_is_not_given_to_the_model(tx, m2, monkeypatch):
    doc, src, chunk = approve_under_kn3(tx, m2, monkeypatch, SPELLED_ZERO_POISON)
    real_pin(tx)                                                 # the owner moves the pin to kn-claims-4
    assert problem(tx, doc) == "report_not_under_current_pin"
    assert status_for(tx, chunk) == ["not_current"] and legacy_rows(tx, chunk) == []
    model = CapturingModel((src, chunk))
    body, reader = ask(tx, (src, chunk), model=model)
    # gate 1: the stale chunk never reaches the model; nothing is generated, no other source is substituted
    assert gate1_refused(body) and model.calls == 0 and reader.rechecks == 0
    # nothing was quarantined, re-reported or rewritten: the approval and its kn-claims-3 evidence are intact
    assert tx.status_of("document", doc) == "approved"
    tx.cur.execute("select extractor_version from public.knowledge_integrity_reports where document_pk = %s", (doc,))
    assert [r[0] for r in tx.cur.fetchall()] == [OLD]
    # retrieval itself is unchanged (E5.1 is an admission rule, not a status change)
    assert chunk in [r[3] for r in tx.rpc(tx.member, tx.season_a, "tưới ngập khô xen kẽ mê-tan", 50)]


def test_a_clean_unaffected_kn3_approval_is_suspended_too(tx, m2, monkeypatch):
    """Service-availability consequence of D-E5-PIN, stated plainly: a re-pin suspends EVERY approval made under
    the old pin, also those whose claims would not change. The path back is a new version (D-REVIEW)."""
    doc, src, chunk = approve_under_kn3(tx, m2, monkeypatch, AWD_TEXT)
    real_pin(tx)
    assert problem(tx, doc) == "report_not_under_current_pin"
    body, _ = ask(tx, (src, chunk))
    assert gate1_refused(body)


def test_what_if_with_stale_evidence_keeps_engine_numbers_and_the_chunk_stays_out_of_the_prompt(tx, m2, monkeypatch):
    doc, src, chunk = approve_under_kn3(tx, m2, monkeypatch, SPELLED_ZERO_POISON)
    real_pin(tx)
    model = CapturingWhatIf()
    body, reader = ask(tx, None, intent=RagIntent.WHAT_IF, question=WHAT_IF_QUESTION, scenario="awd", model=model)
    assert body["status"] == "generated" and body["citations"] == [] and body["recommendations"] == []
    assert body["what_if"] is not None and model.calls == 1
    assert chunk not in model.users[0] and "bằng không" not in model.users[0]


def test_read_tier_without_rag_citation_still_answers_and_evidence_questions_say_why(tx, m2, monkeypatch):
    approve_under_kn3(tx, m2, monkeypatch, SPELLED_ZERO_POISON)
    real_pin(tx)
    # READ answer built solely from trusted crop-season data: unaffected (no document needed, no model)
    body, _ = ask(tx, None, intent=RagIntent.EXPLAIN, question="Giải thích lượng phát thải của vụ này.")
    assert body["status"] == "generated" and body["citations"] == [] and body["recommendations"] == []
    # READ question that needs documents: the stale one is not cited; the copy says why, and nothing is substituted
    body, _ = ask(tx, None, intent=RagIntent.EVIDENCE, question=EVIDENCE_QUESTION)
    assert gate1_refused(body)


# ================================================================== D3-D5: current report, manifest, registry

def test_new_pin_new_valid_report_is_admissible(tx, m2):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1")
    assert problem(tx, doc) is None and status_for(tx, chunk) == ["current"]
    body, _ = ask(tx, (src, chunk))
    assert generated_citing(body, chunk) and body["recommendations"]


def test_mismatched_manifest_digest_suspends_admission_and_the_verifier_refuses_to_sign(tx, m2):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1")
    tx.cur.execute("select private.knowledge_set_integrity_code_digest(%s)", ("6" * 64,))   # other runtime/code
    assert problem(tx, doc) == "not_verified_under_current_pin" and status_for(tx, chunk) == ["not_current"]
    assert gate1_refused(ask(tx, (src, chunk))[0])
    tx.cur.execute("select id from public.knowledge_integrity_reports where document_pk = %s", (doc,))
    report = tx.cur.fetchone()[0]
    key_id, key = paths.test_verifier_key()
    # no re-verification can revive it: the database serves no verification input for an approved version
    with pytest.raises(psycopg.Error):
        m2.as_verifier(lambda: iv.verify(tx.cur, tx.cur, str(report), key, key_id))


def test_a_changed_registry_digest_suspends_admission(tx, m2):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1")
    reg = paths.integrity_registry()
    tx.cur.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                   (CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, reg.registry_version, "7" * 64))
    assert problem(tx, doc) == "report_not_under_current_pin" and status_for(tx, chunk) == ["not_current"]


def test_a_revoked_verifier_key_suspends_admission(tx, m2):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1")
    key_id, _ = paths.test_verifier_key()
    tx.cur.execute("select private.knowledge_revoke_verifier_key(%s, %s)", (key_id, "TEST FIXTURE: key compromised"))
    assert problem(tx, doc) == "not_verified_under_current_pin" and status_for(tx, chunk) == ["not_current"]


# ================================================================== D6, D8: missing metadata, new-version snapshot

def test_missing_integrity_metadata_is_never_current(tx, m2):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1")
    tx.cur.execute("select private.knowledge_set_integrity_policy(null, null, null, null)")    # pin withdrawn
    assert problem(tx, doc) == "policy_not_pinned" and status_for(tx, chunk) == ["not_current"]
    assert gate1_refused(ask(tx, (src, chunk))[0])
    real_pin(tx)
    tx.cur.execute("select attestation_mode from private.knowledge_integrity_policy")
    mode = tx.cur.fetchone()[0]
    tx.cur.execute("select private.knowledge_set_attestation_mode(null)")
    assert problem(tx, doc) == "policy_not_pinned"
    tx.cur.execute("select private.knowledge_set_attestation_mode(%s)", (mode,))
    assert problem(tx, doc) is None
    # a version with no integrity report at all (here: still under review) has nothing to admit
    _, bare = draft(tx, m2, content="TEST FIXTURE: phiên bản chưa có báo cáo kiểm tra")
    assert problem(tx, bare) == "no_report"


def test_a_new_version_whose_snapshot_changed_after_its_report_cannot_be_approved_or_admitted(tx, m2):
    real_pin(tx)
    src = tx.source()
    m2.ensure_verifier(*paths.test_verifier_key())                 # attestation mode chosen: the pin is complete
    doc, _ = version(tx, m2, src, version="v2", content=AWD_TEXT)
    m2.integrity_report(doc)
    tx.chunk(doc, "TEST FIXTURE: đoạn thêm sau khi báo cáo đã được ghi", ordinal=1)   # snapshot moves on
    review = m2.start(doc)
    assert problem(tx, doc) == "report_stale"
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


# ================================================================== D7, D12: rollback, re-activation, mid-request

def test_pin_rollback_reactivates_only_what_was_approved_under_that_exact_pin(tx, m2, monkeypatch):
    old_doc, src, old_chunk = approve_under_kn3(tx, m2, monkeypatch, AWD_TEXT)
    real_pin(tx)
    new_doc, new_chunk = approve_now(tx, m2, src, AWD_TEXT + " Bản v2.", doc_version="v2", document_id="doc-v2")
    assert (problem(tx, old_doc), problem(tx, new_doc)) == ("report_not_under_current_pin", None)
    pin(tx, OLD, OLD_DIGEST)                                     # the owner rolls back to the EXACT earlier tuple
    assert (problem(tx, old_doc), problem(tx, new_doc)) == (None, "report_not_under_current_pin")
    pin(tx, OLD, "8" * 64)                                       # same extractor label, another manifest: nothing
    assert problem(tx, old_doc) == "not_verified_under_current_pin"
    pin(tx, NEXT, "9" * 64)                                      # a pin no report was made under: nothing
    assert (problem(tx, old_doc), problem(tx, new_doc)) == ("report_not_under_current_pin",) * 2


def test_a_pin_change_between_retrieval_and_the_answer_refuses_at_answer_time(tx, m2):
    real_pin(tx)
    src = tx.source()
    doc, chunk = approve_now(tx, m2, src, AWD_TEXT, doc_version="v1")
    sink = TxSink(tx)
    tx.cur.execute(ISOLATED)                                       # M6.1 records only on an isolated database
    model = CapturingModel((src, chunk))
    body, reader = ask(tx, (src, chunk), model=model, sink=sink,
                       before_recheck=lambda: pin(tx, NEXT, "9" * 64))
    assert model.calls == 1 and reader.admissions == 1 and reader.rechecks == 1    # gate 1 admitted it
    assert (body["status"], body["insufficient_reason"], body["citations"], body["recommendations"]) == \
        ("insufficient_evidence", "evidence_integrity_not_current", [], [])
    assert body["answer"] == INSUFFICIENT_MESSAGES["evidence_integrity_not_current"]
    assert [r[0] for r in sink.results] == ["ok"]
    tx.cur.execute("select outcome from public.knowledge_citation_events where recorded_xact = pg_current_xact_id()")
    assert [r[0] for r in tx.cur.fetchall()] == ["evidence_refused"]


# ================================================================== D9: unauthorized and cross-tenant

def test_cross_tenant_and_unauthorized_callers_learn_nothing(tx, m2):
    real_pin(tx)
    src_b, doc_b = draft(tx, m2, visibility="tenant", org=tx.org_b, content=AWD_TEXT)
    review = m2.start(doc_b)
    m2.submit(review)
    m2.decide(review, tx.approver)
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (doc_b,))
    chunk_b = tx.cur.fetchone()[0]
    pin(tx, NEXT, "9" * 64)                                        # stale AND foreign
    # org A's member asking for org B's chunk on org A's season: no row, stale or not
    assert status_for(tx, chunk_b) == []
    status, rows = tx.as_user(tx.member, STATUS, (tx.season_a, [chunk_b], False))
    assert (status, rows) == ("ok", [])
    # org A's member naming org B's season: unreadable season, nothing
    assert status_for(tx, chunk_b, season=tx.season_b) == []
    # the owner-only pieces are not callable by any client role
    for role in ("anon", "authenticated", "service_role"):
        assert as_role(tx, role, "select private.knowledge_integrity_admission_problem(%s)", (doc_b,)) == \
            ("err", PERMISSION_DENIED), role
        assert as_role(tx, role, "select * from private.knowledge_integrity_admission_inventory()") == \
            ("err", PERMISSION_DENIED), role
    assert as_role(tx, "anon", STATUS, (tx.season_b, [chunk_b], False)) == ("err", PERMISSION_DENIED)


def test_e3_containment_is_unchanged_for_a_current_dismissed_conflict(tx, m2):
    from tests.test_rag_knowledge_m7_e5_answer_time import mistaken_expert_approval
    real_pin(tx)
    doc, src, chunk, _ = mistaken_expert_approval(tx, m2)
    assert problem(tx, doc) is None                                 # current under the pin, still contested
    body, reader = ask(tx, (src, chunk))
    assert (body["status"], body["insufficient_reason"]) == ("insufficient_evidence", "evidence_integrity_contested")
    assert reader.admissions == 1 and reader.rechecks == 1          # gate 1 admits it; E3 decides at answer time


# ================================================================== Task C: inventory + versioned re-review

def test_versioned_re_review_after_the_re_pin(tx, m2, monkeypatch):
    """D-REVIEW on the local DB (TEST ONLY reviewer and approver): inventory, classify, new versions, kn-claims-4
    reports, independent verification, the expert gate, admission only when every condition holds."""
    poisoned, src_p, chunk_p = approve_under_kn3(tx, m2, monkeypatch, SPELLED_ZERO_POISON)
    clean, src_c, chunk_c = approve_under_kn3(tx, m2, monkeypatch, AWD_TEXT)
    def kn3_rows(doc):
        tx.cur.execute("select count(*) from public.knowledge_claims where document_pk = %s and extractor_version = %s",
                       (doc, OLD))
        return tx.cur.fetchone()[0]
    kn3_before = {doc: kn3_rows(doc) for doc in (poisoned, clean)}
    real_pin(tx)

    # 1. inventory (owner, read-only) ...
    tx.cur.execute("select document_pk, report_extractor_version, admission_problem"
                   " from private.knowledge_integrity_admission_inventory() where document_pk = any(%s)",
                   ([poisoned, clean],))
    assert sorted(tx.cur.fetchall()) == sorted([(poisoned, OLD, "report_not_under_current_pin"),
                                                (clean, OLD, "report_not_under_current_pin")])
    # 2-3. ... and which ones the current extractor reads differently (offline, nothing written)
    tx.cur.execute("select count(*) from public.knowledge_claims")
    claims_before = tx.cur.fetchone()[0]
    rows = {r["document_pk"]: r for r in classify(tx.cur, [str(poisoned), str(clean)])}
    assert rows[str(poisoned)]["impact"] == "claims_changed" and rows[str(poisoned)]["added_assertions"] == 1
    assert rows[str(clean)]["impact"] == "claims_unchanged"
    tx.cur.execute("select count(*) from public.knowledge_claims")
    assert tx.cur.fetchone()[0] == claims_before

    # 4-8, affected document: a NEW version; kn-claims-4 finds the conflict; the expert gate decides
    v2, chunk_v2 = version(tx, m2, src_p, version="v2", content=SPELLED_ZERO_POISON)
    window(tx, v2, supersedes_document_pk=poisoned)
    review = m2.start(v2)
    report, sha = m2.acknowledge(review)                            # kn-claims-4 report + signed verification
    tx.cur.execute("select finding_type, needs_expert_review from public.knowledge_integrity_findings"
                   " where report_id = %s", (report,))
    assert ("reference_conflict", True) in tx.cur.fetchall()
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION        # undisposed: no approval
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (report,))
    for fid, in tx.cur.fetchall():
        m2.dispose(review, sha, fid, "confirmed_problem",
                   justification="TEST FIXTURE: the (synthetic) expert confirms the claim contradicts the reference",
                   evidence=[{"reference": "TEST FIXTURE reference (synthetic)", "locator": "S.1"}])
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION        # confirmed problem: never approved
    m2.submit(review, "reject", integrity=False, rationale="TEST FIXTURE: confirmed conflict, version rejected")
    assert tx.status_of("document", v2) != "approved"
    assert gate1_refused(ask(tx, (src_p, chunk_p))[0])                       # v1 still not admitted

    # 4-9, unaffected document: a new version under the new pin is approved through every gate and admitted
    u2, chunk_u2 = approve_now(tx, m2, src_c, AWD_TEXT, doc_version="v2", supersedes_document_pk=clean)
    assert problem(tx, u2) is None and status_for(tx, chunk_u2) == ["current"]
    assert generated_citing(ask(tx, (src_c, chunk_u2))[0], chunk_u2)

    # originals preserved with their audit history (nothing mutated or deleted)
    for doc in (poisoned, clean):
        tx.cur.execute("select count(*) from public.knowledge_integrity_reports where document_pk = %s", (doc,))
        assert tx.cur.fetchone()[0] == 1
        tx.cur.execute("select count(*) from public.knowledge_approval_records where document_pk = %s"
                       " and decision = 'approve'", (doc,))
        assert tx.cur.fetchone()[0] == 1
        assert kn3_rows(doc) == kn3_before[doc]


def test_the_inventory_script_refuses_a_non_local_target(monkeypatch, capsys):
    from scripts import knowledge_pin_reextraction_inventory as inv
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres:x@db.example.supabase.co:5432/postgres")
    assert inv.main(["--target", "local"]) == 2
    assert "local stack only" in capsys.readouterr().err


def test_the_inventory_script_runs_read_only_on_the_local_stack(capsys):
    """The operator CLI against this (local) stack: committed data only, a read-only transaction, a summary line."""
    import json

    from scripts import knowledge_pin_reextraction_inventory as inv
    assert inv.main(["--target", "local"]) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(summary) == {"approved", "not_current", "claims_changed"}
    assert 0 <= summary["claims_changed"] <= summary["not_current"] <= summary["approved"]
