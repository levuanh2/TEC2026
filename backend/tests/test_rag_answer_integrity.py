"""RAG V1.5 M7 E5: the answer-time evidence gate (rag_answer_integrity.py), offline cases the database cannot
stage: a cited chunk reported under another version, an unknown / demo assurance in production mode, the demo
mode, a reader that cannot re-validate, a recommendation without a citation, and the shape of the refusal.
The database half is test_rag_knowledge_m7_e5_answer_time.py. Synthetic values only; no network, no provider.
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace

import pytest

from rag_answer_integrity import (ACTION_CONTAINED_FINDING_TYPES, ANSWER_CONFLICT_NOTE, CAVEAT_TEXT,
                                  CITATION_CAVEAT, CITATION_CONFLICT_WARNING, CONFLICT_CAVEAT_TEXT,
                                  FINDING_TYPE_LABELS, AdmittedEvidenceRetriever, admit_retrieved_evidence,
                                  answer_time_evidence_gate, citation_detail, citation_warning,
                                  is_action_answer, recheck_cited_evidence)
from recommendation.rag import RetrievalUnavailable
from recommendation.rag.answers import INSUFFICIENT_MESSAGES

CONTENT = "Tưới ngập khô xen kẽ giúp giảm phát thải mê-tan."


class Cite(SimpleNamespace):
    """A frozen-model stand-in for EvidenceChunk / CitedEvidence (`model_copy` like pydantic)."""

    def model_copy(self, *, update):
        return Cite(**{**self.__dict__, **update})


CHUNK = Cite(source_id="s1", chunk_id="c1", document_id="d1", document_version="v1", content=CONTENT)


def row(**over):
    base = {"source_id": "s1", "document_id": "d1", "document_version": "v1", "chunk_id": "c1",
            "content_sha256": hashlib.sha256(CONTENT.encode()).hexdigest(), "content_hash_consistent": True,
            "approval_assurance": "verified", "resolved_finding_types": []}
    out = {**base, **over}
    # E5.1: what the database reports for an integrity-current version (or a demo approval) unless a test says otherwise
    out.setdefault("integrity_status", "current" if out["approval_assurance"] == "verified" else "demo_unverified")
    return out


class Reader:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.calls = rows if rows is not None else [row()], fail, []

    def knowledge_evidence_state(self, season_id, chunk_ids, *, demo):
        self.calls.append((season_id, tuple(chunk_ids), demo))
        if self.fail:
            raise OSError("TEST FIXTURE: database unreachable")
        return self.rows


def result(*, recs=(("water.awd", ("c1",)),), evidence=(CHUNK,)):
    recommendations = tuple(SimpleNamespace(rule_code=code, evidence_refs=tuple(SimpleNamespace(chunk_id=c) for c in refs))
                            for code, refs in recs)
    return SimpleNamespace(status="generated", evidence=evidence, recommendations=recommendations)


def check(rows, *, demo=False, res=None):
    return recheck_cited_evidence(Reader(rows), crop_season_id="season", result=res or result(), retrieved=[CHUNK],
                                  demo=demo)


@pytest.mark.parametrize("bad, reason", [
    (row(document_version="v2"), "version_changed"),
    (row(document_id="d-other"), "version_changed"),
    (row(content_sha256="0" * 64), "content_changed"),
    (row(content_hash_consistent=False), "content_hash_inconsistent"),
    (row(approval_assurance="unrecorded"), "assurance_not_verified"),
    (row(approval_assurance="demo_unverified"), "assurance_not_verified"),   # demo evidence in production mode
    (row(approval_assurance=None), "assurance_not_verified"),
])
def test_each_identity_or_assurance_change_refuses_the_citation(bad, reason):
    assert check([bad]).refused == (("c1", reason),)


def test_a_chunk_the_database_no_longer_returns_is_refused_and_one_bad_citation_is_enough():
    assert check([]).refused == (("c1", "no_longer_admissible"),)
    other = SimpleNamespace(source_id="s1", chunk_id="c2", document_id="d2", document_version="v1", content="x")
    res = result(evidence=(CHUNK, other), recs=(("water.awd", ("c1", "c2")),))
    out = recheck_cited_evidence(Reader([row()]), crop_season_id="s", result=res, retrieved=[CHUNK, other], demo=False)
    assert out.refused == (("c2", "no_longer_admissible"),) and not out.admissible


def test_demo_assurance_is_accepted_only_in_the_demo_mode():
    assert check([row(approval_assurance="demo_unverified")], demo=True).admissible
    assert not check([row(approval_assurance="unrecorded")], demo=True).admissible


def test_a_citation_that_was_not_retrieved_is_refused_before_any_lookup():
    foreign = SimpleNamespace(source_id="s9", chunk_id="c9", document_id="d9", document_version="v1", content="x")
    reader = Reader([row(source_id="s9", chunk_id="c9")])
    out = recheck_cited_evidence(reader, crop_season_id="s", result=result(evidence=(foreign,), recs=()), retrieved=[CHUNK],
                                 demo=False)
    assert out.refused == (("c9", "not_retrieved"),)


def test_a_recommendation_without_an_admissible_citation_is_refused():
    out = check([row()], res=result(recs=(("water.awd", ()),)))
    assert ("water.awd", "recommendation_without_citation") in out.refused


def test_a_reader_that_cannot_recheck_or_fails_refuses_the_answer():
    with pytest.raises(RetrievalUnavailable):
        recheck_cited_evidence(object(), crop_season_id="s", result=result(), retrieved=[CHUNK], demo=False)
    with pytest.raises(RetrievalUnavailable):
        recheck_cited_evidence(Reader(fail=True), crop_season_id="s", result=result(), retrieved=[CHUNK], demo=False)


class Result(SimpleNamespace):
    def model_copy(self, *, update):
        return Result(**{**self.__dict__, **update})


def test_the_gate_discards_the_whole_model_answer_or_adds_the_caveat():
    base = Result(status="generated", evidence=(CHUNK,), recommendations=result().recommendations, answer="model text",
                  answer_template="t", rationale="r", facts=("f",), limitations=("l",), confidence="high",
                  insufficient_reason=None, signals=("sig",))
    out, refused = answer_time_evidence_gate(Reader([]), crop_season_id="s", result=base, retrieved=[CHUNK], demo=False)
    assert refused and out.status == "insufficient_evidence" and out.insufficient_reason == "evidence_no_longer_admissible"
    assert (out.answer, out.recommendations, out.evidence, out.facts, out.rationale) == \
        (INSUFFICIENT_MESSAGES["evidence_no_longer_admissible"], (), (), (), None)
    assert out.signals == ("sig",)                                        # deterministic signals stay
    out, refused = answer_time_evidence_gate(Reader([row(resolved_finding_types=["unsupported_assertion"])]),
                                             crop_season_id="s", result=base, retrieved=[CHUNK], demo=False)
    assert not refused and out.limitations == ("l", CAVEAT_TEXT.format(
        labels="nhận định chưa có tài liệu tham chiếu hỗ trợ"))
    assert out.evidence[0].integrity_warning == CITATION_CAVEAT and out.answer == "model text"
    assert out.evidence[0].integrity_detail == "Phát hiện kiểm tra: nhận định chưa có tài liệu tham chiếu hỗ trợ."
    # nothing to check: an answer without evidence passes untouched, and the database is not called
    reader = Reader()
    out, refused = answer_time_evidence_gate(reader, crop_season_id="s", result=Result(status="insufficient_evidence",
                                             evidence=()), retrieved=[], demo=False)
    assert not refused and reader.calls == []


# ================================================================== M7 E3 (owner decision D-E3-1 B): action-tier containment

def read_result(intent="explain"):
    """A READ-tier (INFORMATIONAL) answer: no recommendation slot."""
    return SimpleNamespace(status="generated", intent=intent, evidence=(CHUNK,), recommendations=())


@pytest.mark.parametrize("finding_type", sorted(ACTION_CONTAINED_FINDING_TYPES))
def test_e3_an_action_answer_on_a_dismissed_scientific_conflict_is_refused(finding_type):
    out = check([row(resolved_finding_types=[finding_type])])
    assert out.refused == (("c1", "integrity_conflict_dismissed"),) and out.caveats == ()


def test_e3_a_what_if_answer_is_action_tier_even_without_a_recommendation():
    res = SimpleNamespace(status="generated", intent="what_if", evidence=(CHUNK,), recommendations=())
    assert is_action_answer(res) and not is_action_answer(read_result())
    assert check([row(resolved_finding_types=["reference_conflict"])], res=res).refused == \
        (("c1", "integrity_conflict_dismissed"),)


def test_e3_a_read_tier_answer_keeps_the_caveat_and_is_not_refused():
    out = check([row(resolved_finding_types=["reference_conflict", "claim_conflict"])], res=read_result())
    assert out.admissible and out.caveats == (("c1", ("reference_conflict", "claim_conflict")),)


@pytest.mark.parametrize("finding_type", ["unsupported_assertion", "expired_guidance", "superseded_guidance",
                                          "not_yet_effective"])
def test_e3_other_dismissed_finding_types_stay_a_caveat_for_actions(finding_type):
    out = check([row(resolved_finding_types=[finding_type])])
    assert out.admissible and out.caveats == (("c1", (finding_type,)),)


def test_e3_contained_types_are_blocking_e2_types_and_never_temporal():
    from knowledge.integrity.review import _NEEDS_REVIEW
    assert ACTION_CONTAINED_FINDING_TYPES <= _NEEDS_REVIEW
    assert not ACTION_CONTAINED_FINDING_TYPES & {"expired_guidance", "not_yet_effective", "superseded_guidance"}


def test_e3_refusal_shape_keeps_signals_and_inadmissible_evidence_takes_precedence():
    base = Result(status="generated", evidence=(CHUNK,), recommendations=result().recommendations, answer="model text",
                  answer_template="t", rationale="r", facts=("f",), limitations=("l",), confidence="high",
                  insufficient_reason=None, signals=("sig",), intent="recommend")
    out, refused = answer_time_evidence_gate(Reader([row(resolved_finding_types=["reference_conflict"])]),
                                             crop_season_id="s", result=base, retrieved=[CHUNK], demo=False)
    assert refused == (("c1", "integrity_conflict_dismissed"),)
    assert (out.status, out.insufficient_reason, out.answer) == \
        ("insufficient_evidence", "evidence_integrity_contested", INSUFFICIENT_MESSAGES["evidence_integrity_contested"])
    assert (out.recommendations, out.evidence, out.facts, out.rationale, out.limitations) == ((), (), (), None, ())
    assert out.signals == ("sig",)                                        # the stored M05 rule outcome stays
    # one contested + one withdrawn citation: the copy names the stronger fact (no longer admissible)
    other = SimpleNamespace(source_id="s1", chunk_id="c2", document_id="d2", document_version="v1", content="x")
    two = Result(**{**base.__dict__, "evidence": (CHUNK, other),
                    "recommendations": result(recs=(("water.awd", ("c1", "c2")),)).recommendations})
    out, refused = answer_time_evidence_gate(Reader([row(resolved_finding_types=["claim_conflict"])]),
                                             crop_season_id="s", result=two, retrieved=[CHUNK, other], demo=False)
    assert {r for _, r in refused} == {"integrity_conflict_dismissed", "no_longer_admissible"}
    assert out.insufficient_reason == "evidence_no_longer_admissible"


def test_e3_refusal_is_recorded_as_an_evidence_refused_citation_event():
    from rag_citation_events import build_event
    refused_result = SimpleNamespace(status="insufficient_evidence", insufficient_reason="evidence_integrity_contested",
                                     policy_rejection=None, evidence=())
    event = build_event(request_id="00000000-0000-0000-0000-000000000001",
                        crop_season_id="00000000-0000-0000-0000-000000000002", recorder=None,
                        result=refused_result, response_emitted=True)
    assert event.outcome == "evidence_refused" and event.cited == ()


# ================================================================== D-E3-3 (owner, 2026-11-16): READ-tier warnings

class _Answer(Result):
    pass


def _read_answer(types, *, intent="evidence"):
    base = _Answer(status="generated", intent=intent, evidence=(CHUNK,), recommendations=(), answer="Hệ thống soạn.",
                   answer_template="Hệ thống soạn.", limitations=("l",), insufficient_reason=None)
    return answer_time_evidence_gate(Reader([row(resolved_finding_types=list(types))]), crop_season_id="s",
                                     result=base, retrieved=[CHUNK], demo=False)


def _farmer_text(out) -> str:
    return " ".join([out.answer or "", *out.limitations,
                     *(f"{c.integrity_warning or ''} {getattr(c, 'integrity_detail', None) or ''}" for c in out.evidence)])


@pytest.mark.parametrize("finding_type", sorted(ACTION_CONTAINED_FINDING_TYPES))
def test_d_e3_3_read_tier_conflict_is_warned_on_the_citation_and_in_the_answer_without_codes(finding_type):
    out, refused = _read_answer([finding_type])
    assert not refused and out.status == "generated"
    label = FINDING_TYPE_LABELS[finding_type]
    # the owner's sentence, verbatim, with nothing added; the finding description is a separate field
    assert out.evidence[0].integrity_warning == OWNER_CONFLICT_SENTENCE
    assert out.evidence[0].integrity_detail == f"Phát hiện kiểm tra: {label}."
    assert out.evidence[0].url is None                                       # no navigable URL for any client
    assert out.answer.endswith(ANSWER_CONFLICT_NOTE) and out.answer_template.endswith(ANSWER_CONFLICT_NOTE)
    assert out.limitations == ("l", CONFLICT_CAVEAT_TEXT.format(labels=label))
    text = _farmer_text(out)
    assert not any(code in text for code in FINDING_TYPE_LABELS), text       # no internal code shown to a farmer


def test_d_e3_3_a_mixed_citation_names_only_vietnamese_labels_and_unknown_codes_are_not_echoed():
    out, _ = _read_answer(["reference_conflict", "unsupported_assertion", "some_future_type"])
    text = _farmer_text(out)
    assert "some_future_type" not in text and "phát hiện kiểm tra khác" in text
    assert not any(code in text for code in FINDING_TYPE_LABELS)


def test_d_e3_3_a_non_conflict_finding_does_not_add_the_conflict_sentence():
    out, _ = _read_answer(["expired_guidance"])
    assert out.answer == "Hệ thống soạn." and out.evidence[0].integrity_warning == CITATION_CAVEAT
    # an integrity caveat is distinct copy and never calls the document a scientific contradiction
    assert out.evidence[0].integrity_warning != OWNER_CONFLICT_SENTENCE
    assert "mâu thuẫn" not in out.evidence[0].integrity_warning and "khoa học cần xác minh" not in _farmer_text(out)
    assert out.evidence[0].integrity_detail == "Phát hiện kiểm tra: hướng dẫn đã hết hiệu lực."
    assert out.evidence[0].url is None                                       # a caveat also withholds the URL


#: Pinned as a literal (not imported): the owner's required sentence, 2026-11-16.
OWNER_CONFLICT_SENTENCE = ("Tài liệu đang có nội dung khoa học cần xác minh lại; không sử dụng làm căn cứ hướng dẫn"
                           " canh tác.")


def test_read_ux_the_conflict_warning_is_exactly_the_owner_sentence():
    assert CITATION_CONFLICT_WARNING == OWNER_CONFLICT_SENTENCE
    assert "{" not in CITATION_CONFLICT_WARNING and "{" not in CITATION_CAVEAT     # no interpolation into either


@pytest.mark.parametrize("types, conflict", [
    (["reference_conflict"], True), (["claim_conflict"], True), (["numeric_reference_mismatch"], True),
    (["reference_conflict", "expired_guidance", "some_future_type"], True),
    (["unsupported_assertion"], False), (["expired_guidance"], False), (["not_yet_effective"], False),
    (["superseded_guidance"], False), (["some_future_type"], False)])
def test_read_ux_the_headline_is_chosen_from_the_finding_types_and_the_detail_never_echoes_a_code(types, conflict):
    assert citation_warning(types) == (OWNER_CONFLICT_SENTENCE if conflict else CITATION_CAVEAT)
    detail = citation_detail(types)
    assert detail.startswith("Phát hiện kiểm tra: ") and "some_future_type" not in detail
    assert not any(code in detail for code in FINDING_TYPE_LABELS)


def test_read_ux_a_clean_citation_gets_no_warning_and_no_detail():
    base = _Answer(status="generated", intent="evidence", evidence=(CHUNK,), recommendations=(), answer="Hệ thống soạn.",
                   answer_template="Hệ thống soạn.", limitations=("l",), insufficient_reason=None)
    out, refused = answer_time_evidence_gate(Reader([row()]), crop_season_id="s", result=base, retrieved=[CHUNK],
                                             demo=False)
    assert not refused and out is base and not hasattr(out.evidence[0], "integrity_warning")


def test_e3_cannot_fail_open_when_the_recheck_omits_the_finding_state():
    for bad in (None, "reference_conflict"):
        with pytest.raises(RetrievalUnavailable):
            check([row(resolved_finding_types=bad)])
    missing = row()
    del missing["resolved_finding_types"]
    with pytest.raises(RetrievalUnavailable):
        check([missing])


# ================================================================== M7 E5.1: pin-aware admission (offline half)

class AdmissionReader:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.calls = rows if rows is not None else [row()], fail, []

    def knowledge_evidence_admission(self, season_id, chunk_ids, *, demo):
        self.calls.append((season_id, tuple(chunk_ids), demo))
        if self.fail:
            raise OSError("TEST FIXTURE: database unreachable")
        return self.rows


def test_e5_1_a_citation_whose_integrity_is_not_current_is_refused_with_its_own_copy():
    assert check([row(integrity_status="not_current")]).refused == (("c1", "integrity_not_current"),)
    base = Result(status="generated", evidence=(CHUNK,), recommendations=result().recommendations, answer="model text",
                  answer_template="t", rationale="r", facts=("f",), limitations=("l",), confidence="high",
                  insufficient_reason=None, signals=("sig",), intent="recommend")
    out, refused = answer_time_evidence_gate(Reader([row(integrity_status="not_current",
                                                         resolved_finding_types=["reference_conflict"])]),
                                             crop_season_id="s", result=base, retrieved=[CHUNK], demo=False)
    # stale takes precedence over E3: the conflict review it would rest on is itself out of date
    assert refused == (("c1", "integrity_not_current"),)
    assert (out.status, out.insufficient_reason, out.answer, out.evidence, out.recommendations) == \
        ("insufficient_evidence", "evidence_integrity_not_current",
         INSUFFICIENT_MESSAGES["evidence_integrity_not_current"], (), ())
    assert out.signals == ("sig",)


@pytest.mark.parametrize("status", [None, "", "CURRENT", "unknown", 1, True])
def test_e5_1_a_missing_or_unknown_integrity_status_fails_closed(status):
    bad = row()
    if status is None:
        del bad["integrity_status"]
    else:
        bad["integrity_status"] = status
    with pytest.raises(RetrievalUnavailable):
        check([bad])
    with pytest.raises(RetrievalUnavailable):
        admit_retrieved_evidence(AdmissionReader([bad]), crop_season_id="s", retrieved=[CHUNK], demo=False)


def test_e5_1_demo_rows_must_say_demo_unverified_and_verified_rows_must_say_current():
    assert check([row(approval_assurance="demo_unverified")], demo=True).refused == ()
    assert check([row(approval_assurance="demo_unverified", integrity_status="current")], demo=True).refused == \
        (("c1", "integrity_not_current"),)
    assert check([row(integrity_status="demo_unverified")]).refused == (("c1", "integrity_not_current"),)


def test_e5_1_gate_1_admits_only_current_chunks_and_never_passes_through_on_failure():
    other = SimpleNamespace(source_id="s1", chunk_id="c2", document_id="d2", document_version="v1", content="x")
    stale = row(chunk_id="c2", document_id="d2", content_sha256=hashlib.sha256(b"x").hexdigest(),
                integrity_status="not_current")
    reader = AdmissionReader([row(), stale])
    out = admit_retrieved_evidence(reader, crop_season_id="s", retrieved=[CHUNK, other], demo=False)
    assert out.admitted == (CHUNK,) and out.excluded == (("c2", "integrity_not_current"),) and out.pin_excluded
    assert reader.calls == [("s", ("c1", "c2"), False)]
    # a dismissed conflict is NOT a gate-1 decision (E3 stays at answer time)
    out = admit_retrieved_evidence(AdmissionReader([row(resolved_finding_types=["reference_conflict"])]),
                                   crop_season_id="s", retrieved=[CHUNK], demo=False)
    assert out.admitted == (CHUNK,)
    # nothing retrieved: no lookup at all
    empty = AdmissionReader()
    assert admit_retrieved_evidence(empty, crop_season_id="s", retrieved=[], demo=False).admitted == ()
    assert empty.calls == []
    with pytest.raises(RetrievalUnavailable):
        admit_retrieved_evidence(AdmissionReader(fail=True), crop_season_id="s", retrieved=[CHUNK], demo=False)
    with pytest.raises(RetrievalUnavailable):                      # a reader without the check never passes through
        admit_retrieved_evidence(object(), crop_season_id="s", retrieved=[CHUNK], demo=False)


def test_e5_1_the_retriever_wrapper_hands_the_model_only_admitted_chunks():
    other = SimpleNamespace(source_id="s1", chunk_id="c2", document_id="d2", document_version="v1", content="x")
    inner = SimpleNamespace(retrieve=lambda query: (CHUNK, other))
    wrapper = AdmittedEvidenceRetriever(inner, AdmissionReader([row()]), demo=False)
    query = SimpleNamespace(tenant=SimpleNamespace(crop_season_id="s"))
    assert wrapper.retrieve(query) == (CHUNK,)
    assert wrapper.admission.excluded == (("c2", "no_longer_admissible"),) and not wrapper.admission.pin_excluded
    with pytest.raises(RetrievalUnavailable):
        AdmittedEvidenceRetriever(inner, AdmissionReader(), demo=False).retrieve(
            SimpleNamespace(tenant=SimpleNamespace(crop_season_id=None)))


def test_e5_1_only_a_pin_exclusion_changes_the_no_evidence_copy():
    from rag_answer_integrity import EvidenceAdmission, explain_unadmitted_evidence
    empty = Result(status="insufficient_evidence", insufficient_reason="no_evidence_retrieved", answer="a",
                   answer_template=None)
    pin_out = EvidenceAdmission(admitted=(), excluded=(("c1", "integrity_not_current"),))
    out = explain_unadmitted_evidence(empty, pin_out)
    assert (out.insufficient_reason, out.answer) == ("no_integrity_current_evidence",
                                                    INSUFFICIENT_MESSAGES["no_integrity_current_evidence"])
    withdrawn = EvidenceAdmission(admitted=(), excluded=(("c1", "no_longer_admissible"),))
    assert explain_unadmitted_evidence(empty, withdrawn) is empty
    assert explain_unadmitted_evidence(empty, None) is empty
    other = Result(status="insufficient_evidence", insufficient_reason="no_rule_signal", answer="a", answer_template=None)
    assert explain_unadmitted_evidence(other, pin_out) is other


def test_e5_1_citation_events_record_the_answer_time_pin_refusal_only():
    from rag_citation_events import build_event
    for reason, outcome in (("evidence_integrity_not_current", "evidence_refused"),
                            ("no_integrity_current_evidence", "insufficient_evidence")):
        res = SimpleNamespace(status="insufficient_evidence", insufficient_reason=reason, evidence=(),
                              policy_rejection=None)
        assert build_event(request_id=str(uuid.uuid4()), crop_season_id=str(uuid.uuid4()), recorder=None, result=res,
                           response_emitted=True).outcome == outcome


def test_e5_1_the_new_copy_is_vietnamese_and_names_no_internal_code():
    for reason in ("evidence_integrity_not_current", "no_integrity_current_evidence"):
        text = INSUFFICIENT_MESSAGES[reason]
        assert "kiểm tra tính toàn vẹn hiện hành" in text and "không thay bằng một nguồn chưa được kiểm tra" in text
        assert "kn-claims" not in text and "pin" not in text.lower().split()
