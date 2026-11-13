"""RAG V1.5 M5 follow-up: deterministic condition tags and the numeric comparison of claims with the
human-verified registry (backend/knowledge/integrity/conditions.py). Pure: no database, no network.

Every text and every registry entry here is a SYNTHETIC TEST FIXTURE: no real reference value, no real
publisher. The committed numeric registry stays empty (test_knowledge_reference_numeric.py).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from knowledge.integrity import conditions as cd
from knowledge.integrity import reference_numeric as rn
from knowledge.integrity.claims import ClaimSource, extract_claims
from knowledge.integrity.references import load_registry
from knowledge.integrity.review import review
from tests.test_knowledge_reference_numeric import doc, entry

def committed_registry():
    from tests.test_knowledge_integrity import REGISTRY_FILE
    import json
    return load_registry(json.loads(REGISTRY_FILE.read_text(encoding="utf-8")))


def quantity(text: str, parameter: str | None = None):
    """The first extracted quantity claim of `text` (of `parameter` when given), and its source."""
    source = ClaimSource("src/doc@v1", "chunk-1", text)
    claims = [c for c in extract_claims(source) if c.kind == "quantity" and c.status == "extracted"
              and (parameter is None or c.parameter == parameter)]
    assert claims, text
    return claims[0], source


def tags(text: str, parameter: str | None = None) -> set[str]:
    claim, source = quantity(text, parameter)
    return set(cd.condition_tags(claim, source.content).tag_set)


# ================================================================== extraction: stated, never inferred

@pytest.mark.parametrize(("text", "expected"), [
    ("AWD giảm 30% phát thải mê-tan so với ngập liên tục.", {"baseline:continuous_flooding", "quantity:ch4"}),
    ("AWD giảm 30% phát thải CH4 so với ruộng đối chứng.", {"baseline:control", "quantity:ch4"}),
    ("Methane emission was reduced by 25% compared with continuous flooding.",
     {"baseline:continuous_flooding", "quantity:ch4"}),
    ("Giảm 30% phát thải mê-tan so với canh tác truyền thống.", {"baseline:conventional_practice", "quantity:ch4"}),
])
def test_baseline_and_quantity_are_tagged_only_from_the_sentence(text, expected):
    assert tags(text) >= expected


def test_no_condition_is_inferred_when_the_text_states_none():
    assert tags("AWD giảm 30% phát thải.") == set()                      # no gas, no baseline: nothing


def test_a_negated_condition_gives_no_tag():
    found = tags("Trên ruộng không phải đất phèn, năng suất đạt 6 tấn/ha.")
    assert not any(t.startswith("soil:") for t in found)
    assert "soil:acid_sulfate" in tags("Trên đất phèn, năng suất đạt 6 tấn/ha.")


def _span_claim(text: str, span: str):
    """A synthetic claim over `span` (the M4 extractor does not extract an N2O percent as a quantity)."""
    from knowledge.integrity.claims import Claim
    start = text.index(span)
    return Claim("cl-synthetic", "src/doc@v1", "chunk-1", start, start + len(span), span, "quantity", "ambiguous")


def test_applied_nitrogen_basis_and_n2o_n_are_explicit():
    text = "Hệ số phát thải N2O-N là 0,3% lượng đạm bón."
    found = cd.condition_tags(_span_claim(text, "0,3%"), text).tag_set
    assert {"quantity:n2o_n", "base:applied_n"} <= found and "quantity:n2o" not in found
    text = "Hệ số phát thải N2O là 0,3%."
    found = cd.condition_tags(_span_claim(text, "0,3%"), text).tag_set
    assert "quantity:n2o" in found and "base:applied_n" not in found


@pytest.mark.parametrize(("text", "tag"), [
    ("Năng suất vụ đông xuân đạt 7 tấn/ha.", "period:winter_spring"),
    ("Năng suất vụ hè thu đạt 5 tấn/ha.", "period:summer_autumn"),
    ("Phát thải 120 kg CH4/ha/vụ.", "period:season"),
    ("Methane emission of 2.5 kg CH4/ha/day was measured.", "period:day"),
    ("Bón 100 kg N/ha mỗi năm.", "period:year"),
])
def test_measurement_period(text, tag):
    assert tag in tags(text)


def test_stage_comes_from_the_same_words_the_m4_extractor_read():
    claim, source = quantity("Giai đoạn đẻ nhánh giữ mực nước 5 cm.")
    found = cd.condition_tags(claim, source.content)
    stage = [t for t in found.tags if t.tag.startswith("stage:")]
    assert [t.tag for t in stage] == ["stage:tillering"] and stage[0].text == "đẻ nhánh"


def test_region_soil_and_variety_when_explicit():
    claim, source = quantity("Ở Đồng bằng sông Cửu Long, giống OM5451 trên đất phù sa cho năng suất 6 tấn/ha.")
    found = cd.condition_tags(claim, source.content)
    assert found.region == "mekong_delta" and found.region_evidence.text == "Đồng bằng sông Cửu Long"
    assert {"variety:om5451", "soil:alluvial"} <= found.tag_set
    # two regions in one sentence: neither is stated for the claim
    claim, source = quantity("Ở ĐBSCL và Đồng bằng sông Hồng, năng suất đạt 6 tấn/ha.")  # noqa: E501
    assert cd.condition_tags(claim, source.content).region is None


def test_every_tag_carries_its_exact_evidence_span():
    text = "Ở Đồng bằng sông Cửu Long, AWD giảm 30% phát thải mê-tan so với ngập liên tục trong vụ đông xuân."
    claim, source = quantity(text)
    found = cd.condition_tags(claim, source.content)
    for t in found.tags:
        assert source.content[t.start:t.end] == t.text
    assert cd.TAG_AXES >= {rn.condition_axis(t.tag) for t in found.tags}


def test_a_tag_from_another_sentence_is_not_used():
    assert "baseline:continuous_flooding" not in tags("So với ngập liên tục thì khác. AWD giảm 30% phát thải mê-tan.")


def test_a_claim_that_does_not_match_its_content_is_refused():
    claim, _ = quantity("Năng suất đạt 6 tấn/ha.")
    with pytest.raises(ValueError):
        cd.condition_tags(claim, "other text entirely, much longer than the claim")


# ================================================================== comparison

def _registry(*entries):
    return rn.load_numeric_registry(doc(*entries), allow_synthetic=True)


def _rate_entry(**changes):
    return entry(**{"comparison__required_claim_conditions": ["quantity:ch4", "period:day"], "scope__region": None,
                    **changes})


def test_a_verified_entry_yields_a_traceable_mismatch_or_match():
    claim, source = quantity("Phát thải mê-tan 4,0 kg CH4/ha/ngày.", "ch4.emission_factor")
    registry = _registry(_rate_entry())
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, registry)
    assert c.outcome == "outside_printed_range" and c.is_mismatch
    assert (c.claimed_min, c.claim_unit, c.reference_unit, c.conversion) == ("4.0", "kgCH4/ha/day", "kgCH4/ha/day", "identity")
    assert {t.tag for t in c.conditions} == {"quantity:ch4", "period:day"} and c.locator["table"] == "Table S.1"
    claim, source = quantity("Phát thải mê-tan 2,5 kg CH4/ha/ngày.", "ch4.emission_factor")
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, registry)
    assert c.outcome == "within_printed_range" and not c.is_mismatch


def test_an_unverified_entry_never_produces_a_mismatch():
    claim, source = quantity("Phát thải mê-tan 9,0 kg CH4/ha/ngày.", "ch4.emission_factor")
    registry = _registry(_rate_entry(verification__human={"status": "pending"}))
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, registry)
    assert c.outcome == "reference_unverified" and not c.is_mismatch and c.normalized_min is None


def test_missing_or_extra_conditions_are_unresolved_not_a_mismatch():
    registry = _registry(_rate_entry())
    claim, source = quantity("Mê-tan 9,0 kg CH4/ha/ngày trên đất phèn.", "ch4.emission_factor")
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, registry)
    assert c.outcome == "out_of_scope" and "soil:acid_sulfate" in c.rationale
    registry = _registry(_rate_entry(**{"comparison__required_claim_conditions": ["quantity:ch4", "baseline:control"]}))
    claim, source = quantity("Phát thải mê-tan 9,0 kg CH4/ha/ngày.", "ch4.emission_factor")
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, registry)
    assert c.outcome == "out_of_scope" and not c.is_mismatch


def test_no_entry_for_the_parameter_is_unresolved():
    claim, source = quantity("Năng suất đạt 6 tấn/ha.")
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, _registry())
    assert (c.outcome, c.reference_id, c.is_mismatch) == ("no_reference", None, False)


def test_values_reach_the_comparison_as_exact_decimals():
    claim, source = quantity("Phát thải mê-tan 2,2 kg CH4/ha/ngày.", "ch4.emission_factor")
    value = cd.claim_value(claim, cd.condition_tags(claim, source.content))
    assert value.value_min == Decimal("2.2") and isinstance(value.value_min, Decimal)


# ================================================================== offline review integration

def test_the_review_reports_numeric_findings_and_never_decides():
    text = "Phát thải mê-tan 4,0 kg CH4/ha/ngày. Năng suất đạt 6 tấn/ha."
    source = ClaimSource("src/doc@v1", "chunk-1", text)
    result = review([source], registry=committed_registry(), as_of=date(2026, 11, 13),
                    numeric_registry=_registry(_rate_entry()))
    assert result.decision == "none"
    mismatch = result.of_type("numeric_reference_mismatch")
    assert len(mismatch) == 1 and mismatch[0].needs_expert_review and "conditions: quantity:ch4, period:day" in mismatch[0].detail
    unresolved = result.of_type("numeric_unresolved")
    assert unresolved and not any(f.needs_expert_review for f in unresolved)
    assert result.numeric_registry_digest and result.condition_extractor_version == cd.CONDITION_EXTRACTOR_VERSION


def test_without_a_numeric_registry_the_review_is_unchanged():
    source = ClaimSource("src/doc@v1", "chunk-1", "Phát thải mê-tan 4,0 kg CH4/ha/ngày.")
    result = review([source], registry=committed_registry(), as_of=date(2026, 11, 13))
    assert result.numeric_comparisons == () and not result.of_type("numeric_reference_mismatch")


def test_the_committed_registry_produces_no_mismatch():
    """No canonical numeric entry is committed (IPCC pending verification and rights; QĐ 2626 / 4801 /
    4043 blocked): the production registry can only ever answer unresolved."""
    from tests.test_knowledge_reference_numeric import NUMERIC_FILE
    import json
    registry = rn.load_numeric_registry(json.loads(NUMERIC_FILE.read_text(encoding="utf-8")))
    assert registry.entries == ()
    claim, source = quantity("Phát thải mê-tan 40 kg CH4/ha/ngày.", "ch4.emission_factor")
    (c,) = cd.compare_claims([claim], {(source.document_ref, source.chunk_id): source.content}, registry)
    assert c.outcome == "no_reference"
