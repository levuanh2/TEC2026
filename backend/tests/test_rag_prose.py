"""Generated prose policy: UNTRUSTED generator text may carry no raw number, no
link and no placeholder other than the canonical `{{fact:<fact_id>}}`, in any
prose field. Trusted facts, evidence content and metadata are not affected."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recommendation.rag import (
    CitationMismatch,
    EvidenceRef,
    FactReferenceMismatch,
    GeneratedAnswer,
    GroundingFailed,
    RagIntent,
    RagMode,
    build_fact_catalog,
    build_season_context,
    render_facts,
    resolve_citations,
    validate_generated_prose,
    validate_grounding,
)
from tests.fixtures.rag_fakes import AWD_RULE, FakeFactsSource, public_chunk, scope

INTENSITY = "current.metrics.co2e_per_kg"
EVIDENCE = (public_chunk("c1"), public_chunk("c2", content="AWD giảm 30% phát thải CH4, tiết kiệm 1.200 m3 nước/ha."))


def _ground(answer: GeneratedAnswer, intent: RagIntent = RagIntent.RECOMMEND):
    context = build_season_context(scope(), FakeFactsSource(calls=[]), mode=RagMode.ASK)
    return validate_grounding(answer, intent=intent, evidence=EVIDENCE, facts=build_fact_catalog(context),
                              rule_codes=context.signal_rule_codes)


def _answer(**overrides) -> GeneratedAnswer:
    return GeneratedAnswer.model_validate({
        "status": "generated", "answer": "Cường độ là {{fact:%s}}." % INTENSITY,
        "fact_refs": [{"fact_id": INTENSITY}], "evidence_refs": [{"source_id": "guide-awd", "chunk_id": "c1"}],
        **overrides})


def _rec(**overrides) -> dict:
    return {"title": "Tưới AWD", "actions": ["Rút nước định kỳ"],
            "evidence_refs": [{"source_id": "guide-awd", "chunk_id": "c2"}], "rule_code": AWD_RULE, **overrides}


def _in_every_field(text: str) -> list[GeneratedAnswer]:
    """The same prose in each generator-controlled text field."""
    return [
        _answer(answer=text),
        _answer(rationale=text),
        _answer(limitations=[text]),
        _answer(recommendations=[_rec(title=text)]),
        _answer(recommendations=[_rec(actions=["Rút nước định kỳ", text])]),
    ]


# -- numbers ---------------------------------------------------------------------------

RAW_NUMBERS = [
    "Có thể giảm 18 so với vụ trước.",
    "Mức hiện tại là 0.58.",
    "Tăng thêm 120.",
    "Chênh lệch -12.",
    "Cường độ 1,23 trên mỗi kg.",
    "Tổng phát thải hiện tại là 2900.",
    "Giảm18 lượng nước.",                    # glued to a word
    "Áp dụng nguyên tắc 1 phải 5 giảm.",     # no harmless-number guessing in V1
    "Thực hiện trong vụ 2026.",              # years too, until an explicit allowlist exists
    "Cường độ {{fact:%s}} kg CO2e/kg." % INTENSITY,   # the unit is the renderer's job
    "Giảm ２９００ trên mỗi vụ.",             # full-width digits
    "Giảm ½ lượng đạm.",                     # vulgar fraction
    "Theo nguồn [1].",                       # no inline citation markers in the schema
    # known V1 casualties: gas names carry digits (allowlist / wording decided before V1.4)
    "Giảm phát thải CH4.",
    "Giảm N2O từ phân đạm.",
    "Phát thải CO2e của vụ.",
]


@pytest.mark.parametrize("text", RAW_NUMBERS)
def test_raw_number_in_generated_prose_fails_grounding(text):
    with pytest.raises(GroundingFailed, match="number without a system fact"):
        _ground(_answer(answer=text), RagIntent.EXPLAIN)


@pytest.mark.parametrize("text", ["Mức hiện tại là 0.58.", "Tổng phát thải là 2900.", "Áp dụng 1 phải 5 giảm."])
def test_raw_number_is_rejected_in_every_prose_field(text):
    for answer in _in_every_field(text):
        with pytest.raises(GroundingFailed, match="number without a system fact"):
            _ground(answer)


def test_number_carried_by_a_canonical_placeholder_is_grounded_and_rendered():
    answer = _answer(answer="Cường độ là {{fact:%s}}." % INTENSITY)
    assert _ground(answer, RagIntent.EXPLAIN) is answer
    context = build_season_context(scope(), FakeFactsSource(calls=[]), mode=RagMode.ASK)
    catalog = {fact.fact_id: fact for fact in build_fact_catalog(context)}
    assert isinstance(catalog[INTENSITY].value, float)                      # trusted fact keeps its number
    assert render_facts(answer.answer, catalog) == "Cường độ là 0,58 kg CO2e/kg."


def test_numeric_evidence_content_is_allowed_but_cannot_be_restated_in_prose():
    assert "30%" in EVIDENCE[1].content                                      # trusted document text keeps numbers
    quoting = _answer(answer="Theo hướng dẫn, AWD giảm 30% phát thải.",
                      evidence_refs=[{"source_id": "guide-awd", "chunk_id": "c2"}])
    with pytest.raises(GroundingFailed, match="number without a system fact"):
        _ground(quoting, RagIntent.EVIDENCE)
    citing = _answer(answer="Hướng dẫn tưới AWD nêu mức giảm phát thải.", fact_refs=[],
                     evidence_refs=[{"source_id": "guide-awd", "chunk_id": "c2"}])
    assert _ground(citing, RagIntent.EVIDENCE) is citing


# -- links -----------------------------------------------------------------------------

LINKS = [
    "Xem https://example.com để biết thêm.",
    "Xem http://example.com/awd.",
    "Xem www.example.com.",
    "Xem example.com.vn.",
    "Theo [nguồn](https://example.org/guide-awd).",
    "Theo [nguồn](guide-awd).",
    'Xem <a href="x">nguồn</a>.',
    "Gửi tới mailto:a@b.c.",
    "Bấm javascript:alert().",
    "Tải ftp://files.example.org/guide.",
]


@pytest.mark.parametrize("text", LINKS)
def test_link_in_generated_prose_fails_grounding(text):
    with pytest.raises(GroundingFailed, match="link in generated text"):
        _ground(_answer(answer=text), RagIntent.EXPLAIN)


def test_link_is_rejected_in_every_prose_field():
    for answer in _in_every_field("Xem https://example.com."):
        with pytest.raises(GroundingFailed, match="link in generated text"):
            _ground(answer)


def test_source_url_reaches_the_client_only_from_trusted_chunk_metadata():
    cited = resolve_citations([EvidenceRef(source_id="guide-awd", chunk_id="c1")], EVIDENCE)
    assert cited[0].url == "https://example.org/guide-awd"
    with pytest.raises(ValidationError):  # the generator cannot attach or override a URL
        EvidenceRef.model_validate({"source_id": "guide-awd", "chunk_id": "c1", "url": "https://evil.example"})


# -- placeholder grammar -----------------------------------------------------------------

MALFORMED = [
    "Cường độ {{ fact:%s }}." % INTENSITY,
    "Cường độ {{fact: %s}}." % INTENSITY,
    "Cường độ {{ fact : %s }}." % INTENSITY,
    "Cường độ {{FACT:%s}}." % INTENSITY,
    "Cường độ {{fact:%s }}." % INTENSITY,
    "Cường độ {{fact :%s}}." % INTENSITY,
    "Cường độ {{fact:}}.",
    "Cường độ {fact:%s}." % INTENSITY,
    "Cường độ {{fact:%s}." % INTENSITY,
    "Cường độ {{fact:%s}}}." % INTENSITY,
    "Cường độ {{fact:https://evil.example}}.",     # a URL cannot ride in a placeholder
]


@pytest.mark.parametrize("text", MALFORMED)
def test_malformed_placeholder_fails_closed_at_grounding(text):
    with pytest.raises(FactReferenceMismatch, match="malformed fact placeholder"):
        _ground(_answer(answer=text), RagIntent.EXPLAIN)


@pytest.mark.parametrize("text", MALFORMED)
def test_renderer_never_lets_a_malformed_placeholder_through(text):
    with pytest.raises(FactReferenceMismatch, match="malformed fact placeholder"):
        render_facts(text, {})


def test_malformed_placeholder_is_rejected_in_every_prose_field():
    for answer in _in_every_field("Cường độ {{ fact:%s }}." % INTENSITY):
        with pytest.raises(FactReferenceMismatch, match="malformed fact placeholder"):
            _ground(answer)


def test_unknown_canonical_placeholder_is_rejected():
    with pytest.raises(FactReferenceMismatch, match="unknown fact"):
        _ground(_answer(answer="Giá trị {{fact:www.evil.example}}."), RagIntent.EXPLAIN)


# -- channels ----------------------------------------------------------------------------

def test_policy_is_the_generated_prose_validator_and_accepts_clean_prose():
    validate_generated_prose(["Nên rút nước định kỳ.", "Cường độ {{fact:%s}}." % INTENSITY])


def test_evidence_ref_cannot_be_used_as_a_fact_placeholder():
    with pytest.raises(FactReferenceMismatch, match="unknown fact"):
        _ground(_answer(answer="Theo {{fact:guide-awd}}.", fact_refs=[{"fact_id": "guide-awd"}]),
                RagIntent.EXPLAIN)


def test_fact_id_cannot_be_cited_as_evidence():
    with pytest.raises(CitationMismatch):
        _ground(_answer(evidence_refs=[{"source_id": INTENSITY, "chunk_id": INTENSITY}]), RagIntent.EXPLAIN)


def test_generator_cannot_create_a_fact_value():
    with pytest.raises(ValidationError):
        _answer(fact_refs=[{"fact_id": INTENSITY, "value": 0.1}])
