"""RAG V1.5 M7 E5 (migration 20261114120000): answer-time re-validation of cited evidence, end to end.

The REAL `RagQuestionService` runs with a deterministic scripted model (no provider). Its reader is the test
transaction: retrieval (`match_knowledge_chunks_lexical`) and the final recheck (`knowledge_cited_evidence_state`)
run under the member's JWT (role authenticated, RLS); season facts and the stored AWD rule come from the
benchmark fixture. A change "between retrieval and emission" is made by `before_recheck`, which runs in the same
transaction after the model answered and just before the recheck: the real quarantine / archive paths, or an
owner-level edit where no product path exists (documented per test).

Every text and identity is a SYNTHETIC TEST FIXTURE; one rolled-back transaction per test. Skipped without
SUPABASE_DB_URL. dev3-01 stays OPEN. With E3 (owner decision D-E3-1 B) an approved poisoned version whose detected
conflict was dismissed no longer supports an ACTION answer; a READ-tier answer still cites it with a caveat.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest

import scripts.rag_llm_benchmark as bench
from infrastructure.llm_client import LlmCompletion, LlmUsage
from rag_citation_events import PostgresCitationSink
from rag_answer_integrity import ACTION_CONTAINED_FINDING_TYPES, ANSWER_CONFLICT_NOTE, FINDING_TYPE_LABELS
from rag_qa import QuestionInput, RagQuestionService
from recommendation.rag import RagError, RagIntent
from recommendation.rag.answers import INSUFFICIENT_MESSAGES
from tests.test_rag_knowledge_ha_assurance import ISOLATED, verified_doc
from tests.test_rag_knowledge_m2_approval import as_role, draft, m2, owner  # noqa: F401
from tests.test_rag_knowledge_storage import PERMISSION_DENIED, psycopg, pytestmark, tx  # noqa: E402
from tests.test_rag_m7_dev3_01_harness import POISON

__all__ = ["pytestmark", "tx", "m2"]

QUESTION = "Vụ này có nên chuyển sang tưới ngập khô xen kẽ không?"
AWD_TEXT = bench.AWD_CHUNKS[0]["content"]
MATCH = "select to_jsonb(r) from public.match_knowledge_chunks_lexical(%s, %s, %s) r"
STATE = "select to_jsonb(r) from public.knowledge_cited_evidence_state(%s, %s, %s) r"
#: What the E5.1 backend sends (infrastructure/read_repo.py): every row, with its integrity_status.
STATE_PIN = "select to_jsonb(r) from public.knowledge_cited_evidence_state(%s, %s, %s, true) r"
EQ_DOC = "select private.knowledge_emergency_quarantine_document(%s, %s, %s, %s)"
EQ_SRC = "select private.knowledge_emergency_quarantine_source(%s, %s, %s, %s)"


class DbReader:
    """The caller's reader over the test transaction (see the module docstring)."""

    def __init__(self, tx, user, season, *, before_recheck=None):
        self.tx, self.user, self.season_id = tx, user, season
        self.facts = bench.FixtureReader()
        self.before_recheck = before_recheck
        self.rechecks = 0

    def __getattr__(self, name):                                   # season, metrics, recommendations, ...
        return getattr(self.facts, name)

    def user_id(self):
        return str(self.user)

    def season_lineage(self, season_id):
        self.tx.cur.execute("select cs.id::text, p.id::text, p.farm_id::text, f.cooperative_id::text"
                            " from public.crop_seasons cs join public.plots p on p.id = cs.plot_id"
                            " join public.farms f on f.id = p.farm_id where cs.id = %s", (season_id,))
        cs, plot, farm, org = self.tx.cur.fetchone()
        return {"crop_season_id": cs, "plot_id": plot, "farm_id": farm, "organization_id": org}

    def knowledge_matches(self, season_id, query, top_k):
        status, rows = self.tx.as_user(self.user, MATCH, (season_id, query, top_k))
        assert status == "ok", rows
        return [r[0] for r in rows]

    def knowledge_evidence_admission(self, season_id, chunk_ids, *, demo=False):
        """M7 E5.1 gate 1, before the model: the same RPC under the member's JWT (no `before_recheck`: that models a
        change AFTER the model answered)."""
        self.admissions = getattr(self, "admissions", 0) + 1
        status, rows = self.tx.as_user(self.user, STATE_PIN, (season_id, list(chunk_ids), demo))
        if status != "ok":
            raise RuntimeError(f"admission check failed: {rows}")
        return [r[0] for r in rows]

    def knowledge_evidence_awaiting_recheck(self, season_id):
        """M7 E5.2 explanation signal under the member's JWT."""
        status, rows = self.tx.as_user(self.user, "select awaiting from public.knowledge_evidence_awaiting_recheck(%s)",
                                       (season_id,))
        if status != "ok":
            raise RuntimeError(f"awaiting-recheck failed: {rows}")
        return bool(rows and rows[0][0] is True)

    def knowledge_evidence_state(self, season_id, chunk_ids, *, demo=False):
        if self.before_recheck is not None:
            self.before_recheck()
        self.rechecks += 1
        status, rows = self.tx.as_user(self.user, STATE_PIN, (season_id, list(chunk_ids), demo))
        if status != "ok":
            raise RuntimeError(f"recheck failed: {rows}")
        return [r[0] for r in rows]


class ScriptedModel:
    """Recommends the stored AWD rule citing `cite` (source_id, chunk_id), or declines."""

    def __init__(self, cite, *, decline=False):
        self.cite, self.decline, self.calls = cite, decline, 0

    def complete_json(self, *, system, user, schema):
        self.calls += 1
        ref = [{"source_id": self.cite[0], "chunk_id": self.cite[1]}]
        if self.decline:
            data = {"status": "insufficient_evidence", "answer": "Tài liệu chưa đủ để đưa ra gợi ý cho vụ này."}
        else:
            data = {"status": "generated", "answer": "Theo tài liệu đã duyệt, vụ này có thể cân nhắc tưới ngập khô xen kẽ.",
                    "evidence_refs": ref,
                    "recommendations": [{"title": "Cân nhắc tưới ngập khô xen kẽ", "rule_code": bench.RULE,
                                         "evidence_refs": ref}]}
        return LlmCompletion(data=data, usage=LlmUsage(900, 150, 1050, None), latency_ms=5, model="scripted-e5",
                             finish_reason="STOP")


class TxSink:
    """The M6.1 sink, writing through its exact SQL with the service role in the test transaction."""

    def __init__(self, tx):
        self.tx, self.results = tx, []

    def record(self, event):
        self.results.append(as_role(self.tx, "service_role", PostgresCitationSink.SQL, (
            event.request_id, event.crop_season_id, event.retrieval_mode, event.outcome, event.response_emitted,
            event.trace_completeness, json.dumps(list(event.retrieved)), json.dumps(list(event.cited)))))


def cited_doc(tx, m2, content=AWD_TEXT):
    doc, chunk = verified_doc(tx, m2, content)
    tx.cur.execute("select source_id from public.knowledge_documents where id = %s", (doc,))
    return doc, tx.cur.fetchone()[0], chunk


def ask(tx, cite, *, before_recheck=None, decline=False, sink=None, reader=None, intent=RagIntent.RECOMMEND,
        question=QUESTION, model=None, scenario=None):
    reader = reader or DbReader(tx, tx.member, tx.season_a, before_recheck=before_recheck)
    service = RagQuestionService(carbon_service=bench.FixtureCarbon(),
                                 llm_client=model or ScriptedModel(cite, decline=decline),
                                 write_gate=lambda **_: None, citation_sink=sink)
    body = service.answer(reader=reader, crop_season_id=str(tx.season_a), request_id=str(uuid.uuid4()),
                          question=QuestionInput(question=question, intent=intent, what_if_scenario=scenario))
    return body, reader


class WhatIfModel:
    """A what-if answer about the Carbon Engine's AWD delta, citing `cite` (or nothing)."""

    def __init__(self, cite=None):
        self.cite, self.calls = cite, 0

    def complete_json(self, *, system, user, schema):
        self.calls += 1
        data = {"status": "generated", "answer": "Theo Carbon Engine, mức chênh lệch là {{fact:what_if.awd.delta_co2e_kg}}.",
                "fact_refs": [{"fact_id": "what_if.awd.delta_co2e_kg"}]}
        if self.cite is not None:
            data["evidence_refs"] = [{"source_id": self.cite[0], "chunk_id": self.cite[1]}]
        return LlmCompletion(data=data, usage=LlmUsage(900, 150, 1050, None), latency_ms=5, model="scripted-e3-what-if",
                             finish_reason="STOP")


WHAT_IF_QUESTION = "Nếu tưới ngập khô xen kẽ thì phát thải thay đổi thế nào?"
EVIDENCE_QUESTION = "Tài liệu nào nói về tưới ngập khô xen kẽ và khí mê-tan?"


def refused(body):
    return (body["status"], body["insufficient_reason"], body["recommendations"], body["citations"]) == \
        ("insufficient_evidence", "evidence_no_longer_admissible", [], [])


def owner_edit(tx, table, trigger, sql, params):
    """An owner-level change with no product path (documented per test): the guard trigger(s) are bypassed
    inside the rolled-back test transaction, standing for a change the answer path must not trust."""
    triggers = trigger if isinstance(trigger, tuple) else (trigger,)
    for trg in triggers:
        tx.cur.execute(f"alter table public.{table} disable trigger {trg}")
    tx.cur.execute(sql, params)
    for trg in triggers:
        tx.cur.execute(f"alter table public.{table} enable trigger {trg}")


# ================================================================== 1, 13: admissible answers

def test_1_a_valid_citation_is_rechecked_and_emitted(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)
    body, reader = ask(tx, (src, chunk))
    assert body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [chunk]
    assert body["recommendations"][0]["rule_code"] == bench.RULE and reader.rechecks == 1


def test_13_a_model_that_declines_is_returned_without_a_recheck(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)
    body, reader = ask(tx, (src, chunk), decline=True)
    assert body["status"] == "insufficient_evidence" and body["insufficient_reason"] == "generator_declined"
    assert reader.rechecks == 0 and body["citations"] == []


# ================================================================== 2, 10: citations outside the request

def test_2_a_citation_of_a_chunk_not_retrieved_in_this_request_is_refused(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)
    _, other_src, other = cited_doc(tx, m2, content="Rơm rạ sau thu hoạch nên được ủ làm phân thay vì đốt ngoài đồng.")
    with pytest.raises(RagError) as exc:
        ask(tx, (other_src, other))                                # approved and visible, but not retrieved now
    assert exc.value.code == "citation_mismatch"


def test_10_cross_tenant_citation_injection_finds_nothing(tx, m2):
    _, src, chunk = cited_doc(tx, m2)
    foreign = tx.corpus(AWD_TEXT, visibility="tenant", org=tx.org_b)
    tx.cur.execute("select source_id from public.knowledge_chunks c join public.knowledge_documents d"
                   " on d.id = c.document_pk where c.chunk_id = %s", (foreign,))
    foreign_src = tx.cur.fetchone()[0]
    with pytest.raises(RagError) as exc:
        ask(tx, (foreign_src, foreign))
    assert exc.value.code == "citation_mismatch"
    # the recheck itself reveals nothing about the other tenant's chunk, nor do its caveats
    status, rows = tx.as_user(tx.member, STATE, (tx.season_a, [foreign, chunk], False))
    assert status == "ok" and [r[0]["chunk_id"] for r in rows] == [chunk]
    status, rows = tx.as_user(tx.member, "select * from private.knowledge_cited_resolved_finding_types(%s, %s)",
                              (tx.season_a, [foreign]))
    assert (status, rows) == ("ok", [])
    # a caller who cannot read the season gets nothing at all
    assert tx.as_user(tx.outsider, STATE, (tx.season_a, [chunk], False)) == ("ok", [])


# ================================================================== 3, 4, 5, 8, 11: changes after retrieval

def test_3_source_quarantined_after_retrieval(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)
    body, _ = ask(tx, (src, chunk), before_recheck=lambda: as_role(
        tx, "service_role", EQ_SRC, (src, "harmful_content_report", "TEST FIXTURE: source withdrawn mid-request",
                                     "TEST-FIXTURE-E5-3")))
    assert tx.status_of("source", src) == "quarantined" and refused(body)


def test_4_document_archived_after_retrieval(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)
    body, _ = ask(tx, (src, chunk), before_recheck=lambda: m2.archive("document", doc, reason="E5 mid-request"))
    assert tx.status_of("document", doc) == "archived" and refused(body)


def test_5_evidence_expiring_between_retrieval_and_response(tx, m2):
    """No product path moves 'today' inside one request: the owner edit sets effective_to to yesterday, which is
    what the M3 policy date reaching the end of validity looks like to the recheck."""
    doc, src, chunk = cited_doc(tx, m2)
    body, _ = ask(tx, (src, chunk), before_recheck=lambda: owner_edit(
        tx, "knowledge_documents", "knowledge_documents_immutable",
        "update public.knowledge_documents set effective_to = (now() at time zone 'Asia/Ho_Chi_Minh')::date - 1"
        " where id = %s", (doc,)))
    assert refused(body)


def test_8_assurance_that_is_no_longer_verified_at_emission(tx, m2):
    """Owner edit (no product path relabels an approval): the version's assurance becomes `unrecorded`."""
    doc, src, chunk = cited_doc(tx, m2)
    body, _ = ask(tx, (src, chunk), before_recheck=lambda: owner_edit(
        tx, "knowledge_documents", ("knowledge_documents_immutable", "knowledge_documents_zz_assurance"),
        "update public.knowledge_documents set approval_assurance = 'unrecorded' where id = %s", (doc,)))
    assert refused(body)


def test_11_an_authoritative_recommendation_whose_only_citation_is_quarantined(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)
    sink = TxSink(tx)
    tx.cur.execute(ISOLATED)                                       # M6.1 records only on an isolated database
    body, _ = ask(tx, (src, chunk), sink=sink, before_recheck=lambda: as_role(
        tx, "service_role", EQ_DOC, (doc, "harmful_content_report", "TEST FIXTURE: quarantined mid-request",
                                     "TEST-FIXTURE-E5-11")))
    assert refused(body) and body["provenance"]["answer_source"] == "system_composed"
    # C7: the citation event records the refusal; emission of the refusal body is NOT proof of receipt
    assert sink.results and sink.results[-1][0] == "ok"
    tx.cur.execute("select outcome, response_emitted from public.knowledge_citation_events order by occurred_at desc"
                   " limit 1")
    assert tx.cur.fetchone() == ("evidence_refused", True)


# ================================================================== 6: chunk hash

@pytest.mark.parametrize("change", ["text_behind_trigger", "recorded_hash"])
def test_6_a_chunk_whose_hash_no_longer_matches(tx, m2, change):
    doc, src, chunk = cited_doc(tx, m2)
    if change == "text_behind_trigger":                             # text altered, recorded hash kept
        sql, params = ("update public.knowledge_chunks set content = content || ' (đã sửa)' where chunk_id = %s", (chunk,))
    else:                                                           # recorded hash altered
        sql, params = ("update public.knowledge_chunks set content_sha256 = %s where chunk_id = %s", ("0" * 64, chunk))
    body, _ = ask(tx, (src, chunk), before_recheck=lambda: owner_edit(tx, "knowledge_chunks", "knowledge_chunks_immutable",
                                                                         sql, params))
    assert refused(body)


# ================================================================== 9, 14: demo mode and a failing recheck

def test_9_the_demo_recheck_is_refused_on_a_shared_database(tx, m2):
    _, src, chunk = cited_doc(tx, m2)
    assert tx.as_user(tx.member, STATE, (tx.season_a, [chunk], True)) == ("err", PERMISSION_DENIED)


def test_14_a_database_failure_during_the_final_recheck_refuses_the_answer(tx, m2):
    doc, src, chunk = cited_doc(tx, m2)

    def fail():
        raise psycopg.OperationalError("TEST FIXTURE: connection lost during the final recheck")
    with pytest.raises(RagError) as exc:
        ask(tx, (src, chunk), before_recheck=fail)
    assert exc.value.code == "retrieval_unavailable"


# ================================================================== the consistency boundary

def test_a_change_committed_after_the_recheck_is_not_seen_by_the_response(tx, m2):
    """The documented boundary: the recheck sees the database as of its own statement. A quarantine after it
    does not reach the already-built body; the M6.1 exposure query covers that window after the fact."""
    doc, src, chunk = cited_doc(tx, m2)
    body, _ = ask(tx, (src, chunk))
    as_role(tx, "service_role", EQ_DOC, (doc, "harmful_content_report", "TEST FIXTURE: after the recheck",
                                         "TEST-FIXTURE-E5-B"))
    assert tx.status_of("document", doc) == "quarantined"
    assert body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [chunk]


def test_the_answer_time_rpcs_are_for_signed_in_callers_only(tx, m2):
    for fn, ok in (("public.knowledge_cited_evidence_state(uuid,text[],boolean,boolean)", {"authenticated"}),
                   ("private.knowledge_cited_resolved_finding_types(uuid,text[])", {"authenticated"}),
                   ("private.knowledge_cited_integrity_status(uuid,text[],boolean)", {"authenticated"}),
                   ("private.knowledge_integrity_admission_problem(uuid)", set()),
                   ("private.knowledge_integrity_admission_inventory()", set())):
        for role in ("anon", "authenticated", "service_role"):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn))
            assert tx.cur.fetchone()[0] is (role in ok), (fn, role)


# ================================================================== 12: the frozen dev3-01 fixture

def mistaken_expert_approval(tx, m2, content=POISON["content"], *, disposition="false_positive", visibility="public",
                             org=None):
    """The frozen dev3-01 path: integrity findings detected, every one dismissed (`disposition`: false_positive or
    contextual_difference) with WRONG (synthetic) evidence by the verified reviewer, then approved.
    Returns (doc, source_id, chunk_id, finding ids)."""
    _, doc = draft(tx, m2, content=content, visibility=visibility, org=org)
    review = m2.start(doc)
    report, sha = m2.acknowledge(review)
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (report,))
    findings = [r[0] for r in tx.cur.fetchall()]
    assert findings
    evidence = {"reference": "TEST FIXTURE wrong reference", "locator": "n/a"}
    if disposition == "contextual_difference":
        evidence["conditions"] = ["TEST FIXTURE condition that does not hold"]
    for fid in findings:
        m2.dispose(review, sha, fid, disposition,
                   justification="TEST FIXTURE: a MISTAKEN expert judgement, recorded and attributable",
                   evidence=[evidence])
    m2.submit(review)
    m2.decide(review, tx.approver)
    tx.cur.execute("select d.source_id, c.chunk_id, c.content from public.knowledge_chunks c join public.knowledge_documents d"
                   " on d.id = c.document_pk where d.id = %s", (doc,))
    src, chunk, content = tx.cur.fetchone()
    assert hashlib.sha256(content.encode()).hexdigest()                 # hash-consistent (E7.1 contract)
    return doc, src, chunk, findings


def _review_trail(tx, findings):
    tx.cur.execute("select d.id, d.finding_id, d.disposition, d.justification from public.knowledge_integrity_dispositions d"
                   " where d.finding_id = any(%s) order by d.id", (findings,))
    return tx.cur.fetchall()


def test_12_dev3_01_mistaken_expert_action_answer_is_contained_read_tier_keeps_the_caveat(tx, m2):
    """E3 (owner decision D-E3-1 B) on the frozen dev3-01 fixture. E5 cannot know an approved text is false, and E3 does
    not try: it refuses to let an ACTION answer rest on a scientific conflict that only a (mistaken) dismissal
    resolved. The poisoned version stays approved and retrievable (no quarantine), the review trail is
    unchanged, the stored M05 rule signal is still returned, and a READ-tier answer citing it keeps the caveat.
    dev3-01 stays OPEN (undetected poison, E1, test_12i; real-model replay, E6)."""
    doc, src, chunk, findings = mistaken_expert_approval(tx, m2)
    tx.cur.execute("select distinct finding_type from public.knowledge_integrity_findings where id = any(%s)",
                   (findings,))
    types = {t for (t,) in tx.cur.fetchall()}
    assert types & ACTION_CONTAINED_FINDING_TYPES, types               # dev3-01 = reference_conflict
    trail_before = _review_trail(tx, findings)
    assert len(trail_before) == len(findings)
    sink = TxSink(tx)
    tx.cur.execute(ISOLATED)                                           # M6.1 records only on an isolated database

    # -- RECOMMEND (action tier): the model cites the poison with the stored AWD rule -> contained
    body, reader = ask(tx, (src, chunk), sink=sink)
    assert (body["status"], body["insufficient_reason"]) == ("insufficient_evidence", "evidence_integrity_contested")
    assert body["recommendations"] == [] and body["citations"] == [] and reader.rechecks == 1
    assert body["answer"] == INSUFFICIENT_MESSAGES["evidence_integrity_contested"]
    assert body["provenance"]["answer_source"] == "system_composed"
    assert [s["rule_code"] for s in body["signals"]] == [bench.RULE]  # the deterministic M05 outcome stays
    assert sink.results and sink.results[-1][0] == "ok"
    tx.cur.execute("select outcome, response_emitted from public.knowledge_citation_events order by occurred_at desc"
                   " limit 1")
    assert tx.cur.fetchone() == ("evidence_refused", True)

    # -- nothing was quarantined, re-reviewed or rewritten
    assert tx.status_of("document", doc) == "approved"
    assert chunk in [r[3] for r in tx.rpc(tx.member, tx.season_a, "tưới ngập khô xen kẽ mê-tan", 50)]
    assert _review_trail(tx, findings) == trail_before

    # -- READ tier (trusted composer, no model): may cite it, with a conspicuous warning ON the citation (D-E3-3)
    body, _ = ask(tx, (src, chunk), intent=RagIntent.EVIDENCE, question=EVIDENCE_QUESTION)
    assert_read_tier_warned(body, chunk, types)
    # -- an action request disguised as an evidence question: still no advice, still warned
    body, _ = ask(tx, (src, chunk), intent=RagIntent.EVIDENCE,
                  question="Tài liệu nào cho biết sau tưới ngập khô xen kẽ tôi có thể ngừng ghi mực nước?")
    assert_read_tier_warned(body, chunk, types)


def assert_read_tier_warned(body, chunk, types):
    """D-E3-3: generated by the trusted composer, the contested citation carries the Vietnamese warning, the answer
    says the source is not established guidance, no recommendation, and no internal finding code is shown."""
    assert body["status"] == "generated" and body["provenance"]["answer_source"] == "system_composed", body
    assert body["recommendations"] == []
    cited = {c["chunk_id"]: c for c in body["citations"]}
    # READ-tier citation UX: the owner's sentence verbatim; the labels are the separate `integrity_detail`
    assert chunk in cited and cited[chunk]["integrity_warning"] == OWNER_CONFLICT_SENTENCE
    assert all(FINDING_TYPE_LABELS[t] in cited[chunk]["integrity_detail"] for t in types)
    assert cited[chunk]["title"] and cited[chunk]["document_id"]          # still inspectable by the authorized caller
    assert cited[chunk]["url"] is None                                     # but never offered as a link
    assert body["answer"].endswith(ANSWER_CONFLICT_NOTE)
    assert any(line.startswith("Cảnh báo: tài liệu được dẫn có mâu thuẫn khoa học") for line in body["limitations"])
    shown = " ".join([body["answer"], *body["limitations"],
                      *(f'{c["integrity_warning"] or ""} {c["integrity_detail"] or ""}' for c in body["citations"])])
    assert not any(code in shown for code in FINDING_TYPE_LABELS), shown


OWNER_CONFLICT_SENTENCE = "Tài liệu đang có nội dung khoa học cần xác minh lại; không sử dụng làm căn cứ hướng dẫn canh tác."


def test_12b_a_clean_document_in_the_same_database_still_supports_the_recommendation(tx, m2):
    """Containment is per cited chunk: an approved clean AWD document next to the contained poison still
    supports the stored AWD recommendation."""
    mistaken_expert_approval(tx, m2)
    doc, src, chunk = cited_doc(tx, m2)
    body, reader = ask(tx, (src, chunk))
    assert body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [chunk]
    assert body["recommendations"][0]["rule_code"] == bench.RULE and reader.rechecks == 1
    assert not any("báo động nhầm" in line for line in body["limitations"])


@pytest.mark.parametrize("relabel, contained", [("claim_conflict", True), ("numeric_reference_mismatch", True),
                                               ("unsupported_assertion", False)])
def test_12c_each_contained_type_is_mapped_from_the_stored_records_and_others_stay_a_caveat(tx, m2, relabel, contained):
    """D-E3-2: the stored finding type (relabelled by an owner-level edit inside the rolled-back test, standing for a
    finding of that type) decides. The three conflict types contain an action answer; `unsupported_assertion` stays a
    caveat (with its Vietnamese label, on the citation too)."""
    doc, src, chunk, findings = mistaken_expert_approval(tx, m2)
    owner_edit(tx, "knowledge_integrity_findings", "knowledge_integrity_findings_guard",
               "update public.knowledge_integrity_findings set finding_type = %s where id = any(%s)", (relabel, findings))
    body, _ = ask(tx, (src, chunk))
    if contained:
        assert (body["status"], body["insufficient_reason"]) == ("insufficient_evidence", "evidence_integrity_contested")
        assert body["citations"] == [] and body["recommendations"] == []
    else:
        assert body["status"] == "generated" and chunk in [c["chunk_id"] for c in body["citations"]], body
        label = FINDING_TYPE_LABELS[relabel]
        assert any(label in line for line in body["limitations"])
        cite = next(c for c in body["citations"] if c["chunk_id"] == chunk)
        assert label in cite["integrity_detail"] and cite["integrity_warning"].startswith("Lưu ý")
        assert cite["integrity_warning"] != OWNER_CONFLICT_SENTENCE        # a caveat is not called a contradiction
        assert cite["url"] is None


def test_12d_a_contextual_difference_dismissal_is_contained_like_a_false_positive(tx, m2):
    doc, src, chunk, findings = mistaken_expert_approval(tx, m2, disposition="contextual_difference")
    tx.cur.execute("select distinct disposition from public.knowledge_integrity_dispositions where finding_id = any(%s)",
                   (findings,))
    assert [r[0] for r in tx.cur.fetchall()] == ["contextual_difference"]
    body, _ = ask(tx, (src, chunk))
    assert (body["status"], body["insufficient_reason"]) == ("insufficient_evidence", "evidence_integrity_contested")


def test_12e_a_confirmed_conflict_is_rejected_and_never_retrieved_or_cited(tx, m2):
    """Unchanged E2 behaviour, replayed: a reviewer who CONFIRMS the conflict rejects the version."""
    _, doc = draft(tx, m2, content=POISON["content"])
    review = m2.start(doc)
    report, sha = m2.acknowledge(review)
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (report,))
    for (fid,) in tx.cur.fetchall():
        m2.dispose(review, sha, fid, "confirmed_problem", justification="TEST FIXTURE: contradicts the reference")
    m2.submit(review, "reject", rationale="TEST FIXTURE: the integrity findings are confirmed")
    assert tx.status_of("document", doc) == "rejected"
    cited_doc(tx, m2)                                                  # an approved clean document is retrieved
    tx.cur.execute("select d.source_id, c.chunk_id from public.knowledge_chunks c join public.knowledge_documents d"
                   " on d.id = c.document_pk where d.id = %s", (doc,))
    src, chunk = tx.cur.fetchone()
    assert chunk not in [r[3] for r in tx.rpc(tx.member, tx.season_a, "tưới ngập khô xen kẽ mê-tan", 50)]
    with pytest.raises(RagError) as exc:
        ask(tx, (src, chunk))
    assert exc.value.code == "citation_mismatch"


def test_12f_another_htx_contested_document_reveals_nothing(tx, m2):
    """Another cooperative's tenant document, approved through the same mistaken dismissal: never retrieved for this
    season, its citation is refused exactly like any unknown chunk (no E3 reason, no warning), and neither the recheck
    nor the caveat helper reveals that it exists or that it has findings."""
    doc, src, chunk, _ = mistaken_expert_approval(tx, m2, visibility="tenant", org=tx.org_b)
    cited_doc(tx, m2)                                                  # this season's own clean document is retrieved
    assert chunk not in [r[3] for r in tx.rpc(tx.member, tx.season_a, "tưới ngập khô xen kẽ mê-tan", 50)]
    with pytest.raises(RagError) as exc:
        ask(tx, (src, chunk))
    assert exc.value.code == "citation_mismatch"
    assert tx.as_user(tx.member, STATE, (tx.season_a, [chunk], False)) == ("ok", [])
    assert tx.as_user(tx.member, "select * from private.knowledge_cited_resolved_finding_types(%s, %s)",
                      (tx.season_a, [chunk])) == ("ok", [])


def test_12f_read_tier_another_htx_contested_document_reveals_no_title_url_or_warning(tx, m2):
    """READ-tier citation UX: the same foreign contested document, asked about through the trusted READ composer.
    The body never names it: its source id (part of its source title and of its URL) appears nowhere, and the
    caller's own clean citation carries no warning borrowed from it."""
    doc, src, chunk, _ = mistaken_expert_approval(tx, m2, visibility="tenant", org=tx.org_b)
    _, own_src, own_chunk = cited_doc(tx, m2)
    body, _ = ask(tx, None, intent=RagIntent.EVIDENCE, question=EVIDENCE_QUESTION)
    assert body["status"] == "generated" and body["provenance"]["answer_source"] == "system_composed", body
    assert [c["chunk_id"] for c in body["citations"]] == [own_chunk]
    assert src not in json.dumps(body, ensure_ascii=False) and chunk not in json.dumps(body, ensure_ascii=False)
    own = body["citations"][0]
    assert (own["integrity_warning"], own["integrity_detail"]) == (None, None)
    assert own["url"] and own["url"].startswith("https://")                 # a clean citation keeps its link
    assert not any("xác minh lại" in line for line in body["limitations"]) and ANSWER_CONFLICT_NOTE not in body["answer"]


def test_12g_a_contested_source_withdrawn_after_retrieval_is_refused_as_no_longer_admissible(tx, m2):
    """C1-C5 take precedence over E3: the copy names the stronger fact."""
    doc, src, chunk, _ = mistaken_expert_approval(tx, m2)
    body, _ = ask(tx, (src, chunk), before_recheck=lambda: as_role(
        tx, "service_role", EQ_DOC, (doc, "harmful_content_report", "TEST FIXTURE: quarantined mid-request",
                                     "TEST-FIXTURE-E3-12G")))
    assert refused(body)


def test_12h_what_if_on_contested_evidence_keeps_the_engine_numbers_and_drops_the_model_answer(tx, m2):
    doc, src, chunk, _ = mistaken_expert_approval(tx, m2)
    body, _ = ask(tx, None, intent=RagIntent.WHAT_IF, question=WHAT_IF_QUESTION, scenario="awd",
                  model=WhatIfModel((src, chunk)))
    assert (body["status"], body["insufficient_reason"]) == ("insufficient_evidence", "evidence_integrity_contested")
    assert body["citations"] == [] and body["trusted_facts"] == [] and body["what_if"] is not None
    assert body["answer"] == INSUFFICIENT_MESSAGES["evidence_integrity_contested"]
    # the same what-if, citing nothing: the Carbon Engine numbers alone, no document, no advice
    body, reader = ask(tx, None, intent=RagIntent.WHAT_IF, question=WHAT_IF_QUESTION, scenario="awd",
                       model=WhatIfModel())
    assert body["status"] == "generated" and body["citations"] == [] and body["recommendations"] == []
    assert body["what_if"] is not None and reader.rechecks == 0


#: Plausible misinformation that no registry entry covers (E1): the verifier raises no needs-review finding.
UNDETECTED_POISON = ("Khi tưới ngập khô xen kẽ, nên để ruộng khô nứt nẻ suốt giai đoạn trổ bông thì lúa cho năng suất"
                     " cao nhất.")


def test_12i_undetected_poison_is_still_cited_e3_only_contains_what_was_detected(tx, m2):
    """STILL UNSAFE (E1, characterization). Absence of a finding is not proof of correctness: a false claim no
    reference covers is approved without any disposition and supports the recommendation. dev3-01 stays OPEN."""
    _, doc = draft(tx, m2, content=UNDETECTED_POISON)
    review = m2.start(doc)
    report, _ = m2.acknowledge(review)
    tx.cur.execute("select count(*) from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (report,))
    assert tx.cur.fetchone()[0] == 0                                   # nothing for E2 or E3 to act on
    m2.submit(review)
    m2.decide(review, tx.approver)
    tx.cur.execute("select d.source_id, c.chunk_id from public.knowledge_chunks c join public.knowledge_documents d"
                   " on d.id = c.document_pk where d.id = %s", (doc,))
    src, chunk = tx.cur.fetchone()
    body, _ = ask(tx, (src, chunk))
    assert body["status"] == "generated" and [c["chunk_id"] for c in body["citations"]] == [chunk]
    assert body["citations"][0]["integrity_warning"] is None           # and nothing warns the farmer
    assert body["citations"][0]["integrity_detail"] is None


# ================================================================== rollback

def test_the_e5_rollback_restores_m6_1_and_refuses_while_refusal_events_exist(tx, m2):
    from tests.test_rag_knowledge_status_events import E5_ROLLBACK, _without_tx_control
    doc, src, chunk = cited_doc(tx, m2)
    tx.cur.execute(ISOLATED)
    sink = TxSink(tx)
    ask(tx, (src, chunk), sink=sink, before_recheck=lambda: as_role(
        tx, "service_role", EQ_DOC, (doc, "harmful_content_report", "TEST FIXTURE: rollback case", "TEST-FIXTURE-E5-R")))
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.Error) as exc:
        tx.cur.execute(_without_tx_control(E5_ROLLBACK))
    assert "evidence_refused" in str(exc.value)
    tx.cur.execute("rollback to savepoint rb")                     # events are append-only: nothing is deleted


def test_the_e5_rollback_on_a_clean_database_removes_e5_and_restores_m6_1(tx, m2):
    from tests.test_rag_knowledge_status_events import E5_ROLLBACK, _without_tx_control, unwind_e5_1
    unwind_e5_1(tx)                                                # E5.1 (pin-aware admission) unwinds first
    tx.cur.execute(_without_tx_control(E5_ROLLBACK))
    tx.cur.execute("select to_regprocedure('public.knowledge_cited_evidence_state(uuid,text[],boolean)'),"
                   " to_regprocedure('private.knowledge_cited_resolved_finding_types(uuid,text[])')")
    assert tx.cur.fetchone() == (None, None)
    tx.cur.execute("select pg_get_constraintdef(oid) from pg_constraint where conname = 'knowledge_citation_events_outcome_chk'")
    assert "evidence_refused" not in tx.cur.fetchone()[0]
    tx.cur.execute("select prosrc from pg_proc where oid = 'private.knowledge_record_citation_event(uuid,uuid,text,text,"
                   "boolean,text,jsonb,jsonb)'::regprocedure")
    assert "evidence_refused" not in tx.cur.fetchone()[0]
