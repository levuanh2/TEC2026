"""RAG V1.5 M7 E5: the answer-time evidence gate (rag_answer_integrity.py), offline cases the database cannot
stage: a cited chunk reported under another version, an unknown / demo assurance in production mode, the demo
mode, a reader that cannot re-validate, a recommendation without a citation, and the shape of the refusal.
The database half is test_rag_knowledge_m7_e5_answer_time.py. Synthetic values only; no network, no provider.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from rag_answer_integrity import CAVEAT_TEXT, answer_time_evidence_gate, recheck_cited_evidence
from recommendation.rag import RetrievalUnavailable
from recommendation.rag.answers import INSUFFICIENT_MESSAGES

CONTENT = "Tưới ngập khô xen kẽ giúp giảm phát thải mê-tan."
CHUNK = SimpleNamespace(source_id="s1", chunk_id="c1", document_id="d1", document_version="v1", content=CONTENT)


def row(**over):
    base = {"source_id": "s1", "document_id": "d1", "document_version": "v1", "chunk_id": "c1",
            "content_sha256": hashlib.sha256(CONTENT.encode()).hexdigest(), "content_hash_consistent": True,
            "approval_assurance": "verified", "resolved_finding_types": []}
    return {**base, **over}


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
    assert not refused and out.limitations == ("l", CAVEAT_TEXT.format(types="unsupported_assertion"))
    # nothing to check: an answer without evidence passes untouched, and the database is not called
    reader = Reader()
    out, refused = answer_time_evidence_gate(reader, crop_season_id="s", result=Result(status="insufficient_evidence",
                                             evidence=()), retrieved=[], demo=False)
    assert not refused and reader.calls == []
