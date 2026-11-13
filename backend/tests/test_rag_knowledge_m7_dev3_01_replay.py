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


