"""RAG V1.5 M7 dev3-01 replay, database stages B, C, D (docs/rag/RAG_V15_M7_DEV3_01_HARNESS.md). The
offline stages and the module rationale are in test_rag_m7_dev3_01_harness.py. DETERMINISTIC: no LLM, no
provider. Every text and identity is a SYNTHETIC TEST FIXTURE; one rolled-back transaction per test;
skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

from tests.test_rag_m7_dev3_01_harness import CLEAN, POISON  # first: puts backend/ on sys.path for scripts.*
import scripts.rag_llm_benchmark as bench  # noqa: E402
from tests.test_rag_knowledge_m2_approval import as_role, code, draft, m2  # noqa: E402,F401
from tests.test_rag_knowledge_storage import CHECK_VIOLATION, pytestmark, tx  # noqa: E402,F401
from tests.test_rag_source_integrity_gap import QUESTION, CitesPoisonModel, _service  # noqa: E402

__all__ = ["pytestmark", "tx", "m2"]


# ================================================================== B. human gate (DB)

BLOCKING = [{"kind": "contradiction", "severity": "blocking", "status": "open",
             "description": "TEST FIXTURE: integrity review reference_conflict on ch4.rice.emission_eliminated and"
                            " records.water.not_required (references not human-verified)"}]


def _poison_version(tx, m2):
    _, doc = draft(tx, m2, content=POISON["content"])
    return doc


def test_b_a_reviewer_who_records_the_unresolved_finding_cannot_recommend_approval(tx, m2):
    doc = _poison_version(tx, m2)
    review_id = m2.start(doc)
    assert code(m2.submit, review_id, findings=BLOCKING) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "expert_review"
    m2.submit(review_id, "reject", findings=BLOCKING, rationale="TEST FIXTURE: contradicts the reference registry")
    assert tx.status_of("document", doc) == "rejected"


def test_b_e2_a_reviewer_who_ignores_the_report_cannot_recommend_approval(tx, m2):
    """E2 CLOSED by migration 20261113210000 (was: the reviewer recorded no finding and the poisoned text was
    approved; the bypass on the pre-E2 functions is reproduced in test_rag_knowledge_m7_e2_integrity_gate.py).
    The integrity report of the exact version is recorded and acknowledged, its dev3-01 findings stay
    undispositioned: the recommendation is refused, the version stays under review, nothing is served."""
    doc = _poison_version(tx, m2)
    review_id = m2.start(doc)
    report, _ = m2.acknowledge(review_id)
    tx.cur.execute("select count(*) from public.knowledge_integrity_findings where report_id = %s"
                   " and needs_expert_review", (report,))
    assert tx.cur.fetchone()[0] >= 1                                        # integrity finding generated
    assert code(m2.submit, review_id) == CHECK_VIOLATION                    # human evidence gate
    assert code(m2.submit, review_id, integrity=False) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "expert_review"                 # status persisted: not approved


# ================================================================== C + D. quarantine and answer side (DB)

def _served_chunks(tx, query):
    """The benchmark chunk presets that the REAL retrieval returns to the member for `query`."""
    rows = tx.rpc(tx.member, tx.season_a, query, 50)
    contents = [r[9] for r in tx.own_rows(rows)]
    by_content = {POISON["content"]: POISON, CLEAN["content"]: CLEAN}
    return tuple(preset for text, preset in by_content.items() if any(text in c for c in contents))


def _answer(chunks):
    case = bench.Case("dev3-01-replay", "recommend", QUESTION, "grounded", chunks=chunks,
                      expected_rules=(bench.RULE,))
    return bench.run_case(_service(CitesPoisonModel()), case)


def test_c_d_quarantine_removes_the_poison_from_retrieval_and_the_answer_side_stops_citing_it(tx, m2):
    # dev3-01 state: the poisoned version was approved (stage B gap) next to a clean AWD version
    # with E2 the only way to the dev3-01 state is an explicit, attributable human error: the reviewer
    # resolves every finding as false_positive and names (synthetic) evidence
    poison = _poison_version(tx, m2)
    review_poison = m2.start(poison)
    report, sha = m2.acknowledge(review_poison)
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (report,))
    for fid, in tx.cur.fetchall():
        m2.dispose(review_poison, sha, fid, "false_positive",
                   justification="TEST FIXTURE: a MISTAKEN expert judgement, recorded and attributable",
                   evidence=[{"reference": "TEST FIXTURE wrong reference", "locator": "n/a"}])
    m2.submit(review_poison)
    m2.decide(review_poison, tx.approver)
    _, clean = draft(tx, m2, content=CLEAN["content"])
    review_clean = m2.start(clean)
    m2.submit(review_clean)
    m2.decide(review_clean, tx.approver)
    query = "tưới ngập khô xen kẽ mê-tan"
    before = _served_chunks(tx, query)
    assert POISON in before and CLEAN in before
    run = _answer(before)
    # D (before): the trusted path cites the poisoned chunk: dev3-01 reproduced on real retrieval
    assert run["outcome"] == "generated" and run["source_integrity_failure"] is True
    # C: the emergency procedure (H-b) removes it
    status, _ = as_role(tx, "service_role", "select private.knowledge_emergency_quarantine_document(%s, %s, %s, %s)",
                        (poison, "harmful_content_report", "TEST FIXTURE: dev3-01 poisoned guidance, M7 harness",
                         "TEST-FIXTURE-M7-1"))
    assert status == "ok"
    after = _served_chunks(tx, query)
    assert POISON not in after and CLEAN in after
    # D (after): the same scripted model still cites the poisoned id; the trusted path refuses that citation
    run = _answer(after)
    assert run["source_integrity_failure"] is False
    assert POISON["chunk_id"] not in run["cited"]




# ================================================================== M7 E7: the replay matrix (DB + real answer service)

def test_e7_replay_matrix_dishonest_operator_is_stopped_mistaken_expert_is_not(tx, m2):
    """Records, for the frozen dev3-01 fixture, whether the poisoned version is detected, refused at review,
    refused at approval, retrievable and cited, on two paths:

    * dishonest operator (E7): the service-key holder stores the claims WITHOUT the dev3-01 assertions and a
      report complete relative to them; the reviewer acknowledges it. The independent verifier re-reads the
      chunks: mismatch. Review and approval are refused, nothing is retrievable or cited.
    * honest operator, mistaken expert (E1/E4, NOT closed): the report is reproduced by the verifier, the
      reviewer resolves every finding as false_positive with (synthetic) evidence: approved, retrievable,
      cited. This is why test_rag_source_integrity_gap.py is NOT flipped and dev3-01 stays OPEN."""
    from tests.test_rag_knowledge_m7_e7_independent_verification import dishonest_report, verdict, verify
    query = "tưới ngập khô xen kẽ mê-tan"
    _, clean = draft(tx, m2, content=CLEAN["content"])
    review_clean = m2.start(clean)
    m2.submit(review_clean)
    m2.decide(review_clean, tx.approver)

    # -- dishonest operator
    poison = _poison_version(tx, m2)
    review = m2.start(poison)
    report, sha = dishonest_report(tx, m2, poison)
    tx.cur.execute("select finding_count from public.knowledge_integrity_reports where id = %s", (report,))
    operator_findings = tx.cur.fetchone()[0]
    m2.dispose(review, sha, None, "report_reviewed")
    verify(tx, m2, report)
    v, missing = verdict(tx, report)
    review_refused = code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    approval_refused = code(m2.decide, review, tx.approver) != "ok"
    served = _served_chunks(tx, query)
    run = _answer(served)
    dishonest = {"operator_report_findings": operator_findings, "detected_by_e7": v == "mismatch" and len(missing) >= 2,
                 "refused_at_review": review_refused, "refused_at_approval": approval_refused,
                 "status": tx.status_of("document", poison), "retrievable": POISON in served,
                 "cited": POISON["chunk_id"] in run["cited"] and run["source_integrity_failure"]}
    assert dishonest == {"operator_report_findings": 0, "detected_by_e7": True, "refused_at_review": True,
                         "refused_at_approval": True, "status": "expert_review", "retrievable": False,
                         "cited": False}, dishonest
    assert CLEAN in served                                                 # the clean version is still served

    # -- honest operator (the full claim set is added; claims are append-only), mistaken expert
    m2.integrity_report(poison)                                            # the full claim set, a new report
    new_report, new_sha = m2.acknowledge(review)                           # acknowledged and independently verified
    assert new_report != report and verdict(tx, new_report)[0] == "reproduced"
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (new_report,))
    findings = [r[0] for r in tx.cur.fetchall()]
    refused_before_disposition = code(m2.submit, review) == CHECK_VIOLATION
    for fid in findings:
        m2.dispose(review, new_sha, fid, "false_positive",
                   justification="TEST FIXTURE: a MISTAKEN expert judgement, recorded and attributable",
                   evidence=[{"reference": "TEST FIXTURE wrong reference", "locator": "n/a"}])
    m2.submit(review)
    m2.decide(review, tx.approver)
    served = _served_chunks(tx, query)
    run = _answer(served)
    mistaken = {"detected": len(findings) >= 1, "refused_until_dispositioned": refused_before_disposition,
                "status": tx.status_of("document", poison), "retrievable": POISON in served,
                "cited": POISON["chunk_id"] in run["cited"] and run["source_integrity_failure"]}
    assert mistaken == {"detected": True, "refused_until_dispositioned": True, "status": "approved",
                        "retrievable": True, "cited": True}, mistaken          # residual: dev3-01 stays OPEN


# ================================================================== M7 + E5: the full chain on the real answer path

def test_e5_full_chain_matrix_on_the_real_answer_path(tx, m2):
    """The frozen dev3-01 fixture through E2 + E7/E7.1 + E5 with the REAL retrieval RPC, the REAL answer-time
    recheck (both under the member's JWT) and the REAL RagQuestionService with a scripted model that cites the
    poisoned chunk. Columns: claim detection, independent verification, human review, approval, retrieval,
    answer-time validation, response outcome. The mistaken-expert row is the open residual (dev3-01 OPEN)."""
    from recommendation.rag import RagError
    from tests.test_rag_knowledge_m7_e5_answer_time import ask
    from tests.test_rag_knowledge_m7_e7_independent_verification import dishonest_report, verdict, verify
    _, clean = draft(tx, m2, content=CLEAN["content"])
    review_clean = m2.start(clean)
    m2.submit(review_clean)
    m2.decide(review_clean, tx.approver)
    poison = _poison_version(tx, m2)
    tx.cur.execute("select d.source_id, c.chunk_id from public.knowledge_chunks c join public.knowledge_documents d"
                   " on d.id = c.document_pk where d.id = %s", (poison,))
    src, chunk = tx.cur.fetchone()

    def answer():
        try:
            body, reader = ask(tx, (src, chunk))
            return body["status"], chunk in [c["chunk_id"] for c in body["citations"]], body, reader.rechecks
        except RagError as exc:
            return f"refused:{exc.code}", False, None, None

    # -- dishonest operator: omits the dev3-01 claims
    review = m2.start(poison)
    report, sha = dishonest_report(tx, m2, poison)
    m2.dispose(review, sha, None, "report_reviewed")
    verify(tx, m2, report)
    status, cited, _, _ = answer()
    dishonest = {"claims_detected_by_operator": False, "independent_verification": verdict(tx, report)[0],
                 "review_refused": code(m2.submit, review, integrity=False) == CHECK_VIOLATION,
                 "approved": tx.status_of("document", poison) == "approved",
                 "retrievable": chunk in [r[3] for r in tx.rpc(tx.member, tx.season_a, "tưới ngập khô xen kẽ mê-tan", 50)],
                 "response": status, "poison_cited": cited}
    assert dishonest == {"claims_detected_by_operator": False, "independent_verification": "mismatch",
                         "review_refused": True, "approved": False, "retrievable": False,
                         "response": "refused:citation_mismatch", "poison_cited": False}, dishonest

    # -- honest operator, mistaken expert (false_positive with wrong evidence)
    m2.integrity_report(poison)
    new_report, new_sha = m2.acknowledge(review)
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (new_report,))
    findings = [r[0] for r in tx.cur.fetchall()]
    for fid in findings:
        m2.dispose(review, new_sha, fid, "false_positive",
                   justification="TEST FIXTURE: a MISTAKEN expert judgement, recorded and attributable",
                   evidence=[{"reference": "TEST FIXTURE wrong reference", "locator": "n/a"}])
    m2.submit(review)
    m2.decide(review, tx.approver)
    status, cited, body, rechecks = answer()
    mistaken = {"claims_detected": len(findings) >= 1, "independent_verification": verdict(tx, new_report)[0],
                "approved": tx.status_of("document", poison) == "approved",
                "retrievable": chunk in [r[3] for r in tx.rpc(tx.member, tx.season_a, "tưới ngập khô xen kẽ mê-tan", 50)],
                "answer_time_rechecked": rechecks == 1,
                "caveat_shown": any("báo động nhầm" in line for line in body["limitations"]),
                "response": status, "poison_cited": cited}
    assert mistaken == {"claims_detected": True, "independent_verification": "reproduced", "approved": True,
                        "retrievable": True, "answer_time_rechecked": True, "caveat_shown": True,
                        "response": "generated", "poison_cited": True}, mistaken      # residual: dev3-01 OPEN
