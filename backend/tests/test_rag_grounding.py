"""Retrieval tenant filter, tenant-isolation backstop, citation validation and
grounding — the pure policy pieces of RAG V1."""

from __future__ import annotations

import pytest

from recommendation.rag import (
    CitationMismatch,
    EvidenceRef,
    GeneratedAnswer,
    GroundingFailed,
    RagIntent,
    RagMode,
    TenantIsolationViolation,
    assert_tenant_isolation,
    build_retrieval_query,
    build_season_context,
    resolve_citations,
    validate_citations,
    validate_grounding,
)
from tests.fixtures.rag_fakes import (
    AWD_RULE,
    FARM_ID,
    ORG_ID,
    OTHER_ORG_ID,
    SEASON_ID,
    FakeFactsSource,
    public_chunk,
    scope,
    tenant_chunk,
)

EVIDENCE = (public_chunk("c1"), public_chunk("c2"), public_chunk("x1", source_id="ipcc-2019", title="IPCC 2019"))


def _ref(source_id: str = "guide-awd", chunk_id: str = "c1") -> dict:
    return {"source_id": source_id, "chunk_id": chunk_id}


def _context():
    return build_season_context(scope(), FakeFactsSource(calls=[]), mode=RagMode.ASK)


# -- retrieval query / isolation ------------------------------------------------

def test_retrieval_query_tenant_filter_is_the_authorized_scope():
    query = build_retrieval_query("Có nên chuyển sang AWD?", RagIntent.RECOMMEND, scope())
    assert query.tenant.organization_id == ORG_ID
    assert query.tenant.farm_id == FARM_ID
    assert query.tenant.crop_season_id == SEASON_ID
    assert query.include_public is True


def test_public_and_own_tenant_evidence_pass_isolation():
    assert_tenant_isolation([public_chunk(), tenant_chunk(), tenant_chunk("t2", farm_id=FARM_ID)], scope())


@pytest.mark.parametrize("chunk", [
    tenant_chunk(organization_id=OTHER_ORG_ID),
    tenant_chunk(farm_id="another-farm-same-htx"),
])
def test_foreign_tenant_evidence_is_a_security_failure(chunk):
    with pytest.raises(TenantIsolationViolation) as exc:
        assert_tenant_isolation([public_chunk(), chunk], scope())
    assert OTHER_ORG_ID not in str(exc.value)


# -- citations ------------------------------------------------------------------

def test_valid_citations_are_accepted():
    validate_citations([EvidenceRef(**_ref()), EvidenceRef(**_ref("ipcc-2019", "x1"))], EVIDENCE)


@pytest.mark.parametrize(("refs", "message"), [
    ([_ref("invented-source", "c1")], "unknown source"),
    ([_ref("guide-awd", "c999")], "unknown chunk"),
    ([_ref("guide-awd", "x1")], "unknown chunk"),          # real chunk id, wrong source
    ([_ref(), _ref()], "duplicate citation"),
])
def test_citation_mismatch_is_rejected(refs, message):
    with pytest.raises(CitationMismatch, match=message):
        validate_citations([EvidenceRef(**ref) for ref in refs], EVIDENCE)


def test_resolved_citations_use_trusted_metadata_in_first_cited_order():
    cited = resolve_citations([EvidenceRef(**_ref("ipcc-2019", "x1")), EvidenceRef(**_ref()),
                               EvidenceRef(**_ref("ipcc-2019", "x1"))], EVIDENCE)
    assert [(c.source_id, c.chunk_id) for c in cited] == [("ipcc-2019", "x1"), ("guide-awd", "c1")]
    assert cited[0].title == "IPCC 2019"
    assert cited[1].url == "https://example.org/guide-awd"


def test_resolving_an_unknown_citation_fails_closed():
    with pytest.raises(CitationMismatch):
        resolve_citations([EvidenceRef(**_ref("nope", "c1"))], EVIDENCE)


# -- grounding -------------------------------------------------------------------

def _answer(**overrides) -> GeneratedAnswer:
    return GeneratedAnswer.model_validate({"status": "generated", "answer": "Nên cân nhắc AWD.",
                                           "evidence_refs": [_ref()], **overrides})


def _rec(**overrides) -> dict:
    return {"title": "Tưới AWD", "actions": ["Rút nước định kỳ"], "evidence_refs": [_ref("guide-awd", "c2")],
            "rule_code": AWD_RULE, **overrides}


def test_grounded_answer_is_accepted_unchanged():
    answer = _answer(recommendations=[_rec()])
    assert validate_grounding(answer, intent=RagIntent.RECOMMEND, evidence=EVIDENCE, context=_context()) is answer


def test_recommendation_without_evidence_is_rejected():
    with pytest.raises(GroundingFailed, match="without evidence"):
        validate_grounding(_answer(recommendations=[_rec(evidence_refs=[])]),
                           intent=RagIntent.RECOMMEND, evidence=EVIDENCE, context=_context())


def test_recommendation_with_invented_citation_is_rejected():
    with pytest.raises(CitationMismatch):
        validate_grounding(_answer(recommendations=[_rec(evidence_refs=[_ref("made-up", "c1")])]),
                           intent=RagIntent.RECOMMEND, evidence=EVIDENCE, context=_context())


def test_recommendation_cannot_invent_a_deterministic_rule():
    with pytest.raises(GroundingFailed, match="rule the season does not have"):
        validate_grounding(_answer(recommendations=[_rec(rule_code="fertilizer.n_above_benchmark")]),
                           intent=RagIntent.RECOMMEND, evidence=EVIDENCE, context=_context())


@pytest.mark.parametrize("intent", [RagIntent.RECOMMEND, RagIntent.EVIDENCE, RagIntent.COMPARE, RagIntent.UNKNOWN])
def test_evidence_required_intent_without_citations_is_rejected(intent):
    with pytest.raises(GroundingFailed, match="requires cited evidence"):
        validate_grounding(_answer(evidence_refs=[]), intent=intent, evidence=EVIDENCE, context=_context())


@pytest.mark.parametrize("intent", [RagIntent.EXPLAIN, RagIntent.WHAT_IF, RagIntent.DATA_GAP])
def test_context_grounded_intents_may_answer_without_citations(intent):
    answer = _answer(evidence_refs=[])
    assert validate_grounding(answer, intent=intent, evidence=EVIDENCE, context=_context()) is answer


def test_insufficient_evidence_answer_is_valid_without_citations():
    answer = GeneratedAnswer(status="insufficient_evidence", answer="Chưa đủ tài liệu để trả lời.")
    assert validate_grounding(answer, intent=RagIntent.RECOMMEND, evidence=(), context=_context()) is answer
