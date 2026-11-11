"""RAG V1.5 M4, pure part: the deterministic claim extractor's stored form and the contradiction
analysis (backend/knowledge/integrity/contradictions.py). No database.

Every text here is a SYNTHETIC TEST FIXTURE written for this test. The numbers are not agronomic
reference values and prove nothing about real guidance. The measured precision below is the
behaviour of the rules on these controlled fixtures only; it is not a scientific validation.
"""

from __future__ import annotations

from datetime import date

import pytest

from knowledge.integrity.claims import ClaimSource, extract_claims
from knowledge.integrity.contradictions import (ANALYSIS_VERSION, CLASSIFICATIONS, ClaimRecord, DocumentRecord,
                                                Tolerance, analyze, candidate_payload, claim_payload,
                                                comparison_key, same_boundary)

ORG_A, ORG_B = "org-a", "org-b"


def doc(pk, *, source="src-1", document_id=None, version="v1", visibility="public", org=None, farm=None,
        state="active", reason="approved_in_force", frm=None, to=None, supersedes=None):
    return DocumentRecord(pk, source, document_id or pk, version, visibility, org, farm, state, reason, frm, to,
                          supersedes)


def records(document_pk, text, *, chunk_id="c1", first_id=1):
    """ClaimRecords of the comparable claims the real extractor finds in `text`."""
    claims = extract_claims(ClaimSource(f"s/{document_pk}@v1", chunk_id, text))
    out = []
    for claim in claims:
        key = comparison_key(claim)
        if key:
            out.append(ClaimRecord(first_id + len(out), document_pk, chunk_id, claim.claim_id, key, claim.value_min,
                                   claim.value_max, claim.stage, claim.scope))
    return out


def pair(text_a, text_b, doc_a=None, doc_b=None, **kw):
    a = records("doc-a", text_a, chunk_id="ca", first_id=1)
    b = records("doc-b", text_b, chunk_id="cb", first_id=100)
    return analyze(a + b, [doc_a or doc("doc-a"), doc_b or doc("doc-b", source="src-2")], **kw)


DRY_15 = "Khi mực nước xuống 15 cm dưới mặt ruộng thì tưới lại."
DRY_150MM = "Khi mực nước xuống 150 mm dưới mặt ruộng thì tưới lại."
DRY_30 = "Khi mực nước xuống 30 cm dưới mặt ruộng thì tưới lại."
DRY_RANGE = "Khi mực nước xuống từ 10 đến 15 cm dưới mặt ruộng thì tưới lại."


# ================================================================== stored form of a claim

def test_a_stored_claim_keeps_the_exact_span_and_adds_nothing():
    text = "Giai đoạn đẻ nhánh, bón 1,5 tấn/ha phân bón."
    claims = extract_claims(ClaimSource("s/d@v1", "c1", text))
    quantity = next(c for c in claims if c.kind == "quantity")
    payload = claim_payload(quantity)
    assert text[payload["span_start"]:payload["span_end"]] == payload["raw_text"] == "1,5 tấn/ha"
    assert (payload["value_min"], payload["value_max"], payload["unit"], payload["dimension"]) == (
        1500.0, 1500.0, "kg/ha", "areal_mass")
    assert payload["stage"] == "tillering" and payload["status"] == "extracted"
    assert set(payload) == {"claim_id", "chunk_id", "span_start", "span_end", "raw_text", "kind", "status",
                            "parameter", "value_min", "value_max", "unit", "dimension", "date_iso", "stage",
                            "scope_tags", "note"}
    assert comparison_key(quantity) == "fertilizer.rate|kg/ha"


@pytest.mark.parametrize("text, status", [
    ("Bón 1.500 kg/ha phân bón.", "ambiguous"),            # thousands separator or decimal: never guessed
    ("Mực nước -15 cm dưới mặt ruộng.", "ambiguous"),      # sign convention unknown
    ("Dùng 20 lít nước.", "unsupported"),                  # recognised but unsupported unit
    ("Chiều dài 15 cm.", "ambiguous"),                     # a unit without any parameter cue
])
def test_an_ambiguous_or_unsupported_claim_is_stored_unresolved_and_never_comparable(text, status):
    quantities = [c for c in extract_claims(ClaimSource("s/d@v1", "c1", text)) if c.kind == "quantity"]
    assert [c.status for c in quantities] == [status]
    assert comparison_key(quantities[0]) is None
    assert claim_payload(quantities[0])["status"] == status
    if status != "ambiguous" or quantities[0].value_min is None:
        assert claim_payload(quantities[0])["value_min"] is None or quantities[0].parameter is None


def test_a_bare_number_without_a_unit_is_not_a_claim():
    assert not [c for c in extract_claims(ClaimSource("s/d@v1", "c1", "Tưới lại sau 15 khi mực nước xuống."))
                if c.kind == "quantity"]


def test_non_quantity_claims_have_no_comparison_key():
    claims = extract_claims(ClaimSource("s/d@v1", "c1", "Có hiệu lực từ ngày 01/01/2027. Giai đoạn trổ bông."))
    assert {c.kind for c in claims} == {"date", "stage"}
    assert all(comparison_key(c) is None for c in claims)


def test_a_qualitative_assertion_is_stored_but_never_paired():
    """M4 compares quantities only. Two opposite assertions raise no candidate (documented limit)."""
    a = "Ruộng lúa không còn phát thải mê-tan."
    claims = extract_claims(ClaimSource("s/d@v1", "c1", a))
    assert [c.kind for c in claims] == ["assertion"] and comparison_key(claims[0]) is None
    assert pair(a, "Ruộng lúa vẫn phát thải mê-tan 250 kg CH4/ha/vụ.").candidates == ()


# ================================================================== comparison

def test_equivalent_values_in_different_units_are_not_a_contradiction():
    analysis = pair(DRY_15, DRY_150MM)
    assert analysis.compared == 1 and analysis.candidates == ()
    assert analysis.decision == "none" and analysis.analysis_version == ANALYSIS_VERSION


def test_overlapping_ranges_agree():
    assert pair(DRY_15, DRY_RANGE).candidates == ()


def test_a_real_contradiction_between_independent_sources():
    (candidate,) = pair(DRY_15, DRY_30).candidates
    assert (candidate.classification, candidate.reasons, candidate.independence) == (
        "contradiction", ("same_parameter_same_context",), "independent_source")
    assert (candidate.claim_a, candidate.claim_b) == (1, 100)
    assert candidate.comparison_key == "water.awd.dry_down_depth|cm"
    assert candidate_payload(candidate) == {
        "claim_a": 1, "claim_b": 100, "classification": "contradiction", "reasons": ["same_parameter_same_context"],
        "independence": "independent_source", "tolerance": 0.0, "tolerance_rationale": ""}


def test_different_parameters_and_dimensions_are_never_compared():
    analysis = pair(DRY_15, "Tưới lại sau 5 ngày giữa các lần tưới. Bón 30 kg/ha phân bón.")
    assert analysis.compared == 0 and analysis.candidates == ()


def test_two_values_in_one_chunk_are_not_compared():
    text = "Bón 30 kg/ha phân bón lúc gieo sạ. Bón 60 kg/ha phân bón lúc đẻ nhánh."
    claims = records("doc-a", text)
    analysis = analyze(claims, [doc("doc-a")])
    assert analysis.candidates == () and dict(analysis.skipped) == {"same_chunk": 1}


def test_different_stated_crop_stages_are_not_compared():
    analysis = pair("Giai đoạn đẻ nhánh, bón 30 kg/ha phân bón.", "Giai đoạn làm đòng, bón 60 kg/ha phân bón.")
    assert analysis.candidates == () and dict(analysis.skipped) == {"different_stage": 1}


def test_a_stage_stated_on_one_side_only_is_missing_context():
    (candidate,) = pair("Giai đoạn đẻ nhánh, bón 30 kg/ha phân bón.", "Bón 60 kg/ha phân bón.").candidates
    assert (candidate.classification, candidate.reasons) == ("missing_context", ("stage_unstated",))


def test_a_practice_tag_on_one_side_only_is_missing_context():
    (candidate,) = pair("Với ngập khô xen kẽ, năng suất đạt 6 tấn/ha.", "Năng suất đạt 5 tấn/ha.").candidates
    assert (candidate.classification, candidate.reasons) == ("missing_context", ("scope_tag_differs",))


def test_supersession_validity_and_versions_explain_an_apparent_contradiction():
    old = doc("doc-a", source="src-1", document_id="guide")
    direct = pair(DRY_15, DRY_30, old, doc("doc-b", source="src-1", document_id="guide-2", supersedes="doc-a"))
    assert [(c.classification, c.reasons, c.independence) for c in direct.candidates] == [
        ("apparent_contradiction", ("superseded_version",), "same_source")]
    # through a chain: doc-b supersedes doc-mid, which superseded doc-a
    a = records("doc-a", DRY_15, chunk_id="ca", first_id=1)
    b = records("doc-b", DRY_30, chunk_id="cb", first_id=100)
    chain = analyze(a + b, [old, doc("doc-mid", supersedes="doc-a", state="inactive", reason="archived"),
                            doc("doc-b", source="src-2", supersedes="doc-mid")])
    assert [c.reasons for c in chain.candidates] == [("superseded_version",)]
    periods = pair(DRY_15, DRY_30, doc("doc-a", to=date(2026, 12, 31)),
                   doc("doc-b", source="src-2", frm=date(2027, 1, 1)))
    assert [(c.classification, c.reasons) for c in periods.candidates] == [
        ("apparent_contradiction", ("disjoint_validity",))]
    touching = pair(DRY_15, DRY_30, doc("doc-a", to=date(2027, 1, 1)),
                    doc("doc-b", source="src-2", frm=date(2027, 1, 1)))
    assert [c.classification for c in touching.candidates] == ["contradiction"]     # both in force on that day
    versions = pair(DRY_15, DRY_30, doc("doc-a", document_id="guide", version="v1"),
                    doc("doc-b", document_id="guide", version="v2"))
    assert [(c.classification, c.reasons) for c in versions.candidates] == [
        ("apparent_contradiction", ("other_version_of_document",))]


@pytest.mark.parametrize("reason", ["quarantined", "archived", "rejected", "not_in_force", "source_quarantined"])
def test_inactive_material_is_never_a_contradiction_of_current_guidance(reason):
    inactive = doc("doc-b", source="src-2", state="inactive", reason=reason)
    (candidate,) = pair(DRY_15, DRY_30, doc("doc-a"), inactive).candidates
    assert candidate.classification == "insufficient_evidence"
    assert candidate.reasons[0] == f"inactive_evidence:{reason}"
    both = pair(DRY_15, DRY_30, doc("doc-a", state="inactive", reason="archived"), inactive)
    assert both.candidates == () and dict(both.skipped) == {"both_inactive": 1}


def test_a_candidate_version_is_compared_with_active_evidence():
    (candidate,) = pair(DRY_15, DRY_30, doc("doc-a", state="candidate", reason="expert_review"),
                        doc("doc-b", source="src-2")).candidates
    assert candidate.classification == "contradiction"


@pytest.mark.parametrize("a, b, allowed", [
    (doc("a"), doc("b"), True),
    (doc("a"), doc("b", visibility="tenant", org=ORG_A), True),
    (doc("a", visibility="tenant", org=ORG_A), doc("b", visibility="tenant", org=ORG_A), True),
    (doc("a", visibility="tenant", org=ORG_A), doc("b", visibility="tenant", org=ORG_B), False),
    (doc("a", visibility="tenant", org=ORG_A, farm="f1"), doc("b", visibility="tenant", org=ORG_A, farm="f2"), False),
    (doc("a", visibility="tenant", org=ORG_A, farm="f1"), doc("b", visibility="tenant", org=ORG_A), True),
    (doc("a", visibility="tenant", org=None), doc("b", visibility="tenant", org=None), False),
])
def test_the_data_boundary(a, b, allowed):
    assert same_boundary(a, b) is allowed and same_boundary(b, a) is allowed


def test_two_tenants_are_never_paired():
    analysis = pair(DRY_15, DRY_30, doc("doc-a", visibility="tenant", org=ORG_A),
                    doc("doc-b", source="src-2", visibility="tenant", org=ORG_B))
    assert analysis.candidates == () and dict(analysis.skipped) == {"scope_boundary": 1} and analysis.compared == 0


def test_no_tolerance_is_assumed_and_an_explicit_one_needs_a_rationale():
    near_a, near_b = "Năng suất đạt 5 tấn/ha.", "Năng suất đạt 5,2 tấn/ha."
    assert [c.classification for c in pair(near_a, near_b).candidates] == ["contradiction"]
    tolerance = Tolerance("yield|kg/ha", 250.0, "TEST FIXTURE rationale: rounding of reported yields")
    assert pair(near_a, near_b, tolerances=[tolerance]).candidates == ()
    (still,) = pair(near_a, "Năng suất đạt 6 tấn/ha.", tolerances=[tolerance]).candidates
    assert (still.tolerance, still.tolerance_rationale) == (250.0, tolerance.rationale)
    for bad in ({"absolute": -1.0}, {"rationale": "  "}, {"comparison_key": ""}, {"absolute": float("nan")},
                {"absolute": float("inf")}):
        with pytest.raises(ValueError):
            Tolerance(**{"comparison_key": "yield|kg/ha", "absolute": 1.0, "rationale": "r", **bad})
    with pytest.raises(ValueError, match="two tolerances"):
        pair(near_a, near_b, tolerances=[tolerance, tolerance])


def test_the_analysis_is_deterministic_and_respects_the_subject_document():
    a = records("doc-a", DRY_15, chunk_id="ca", first_id=1)
    b = records("doc-b", DRY_30, chunk_id="cb", first_id=100)
    c = records("doc-c", "Khi mực nước xuống 20 cm dưới mặt ruộng thì tưới lại.", chunk_id="cc", first_id=200)
    documents = [doc("doc-a"), doc("doc-b", source="src-2"), doc("doc-c", source="src-3")]
    full = analyze(a + b + c, documents)
    assert analyze(c + b + a, list(reversed(documents))) == full
    assert [(x.claim_a, x.claim_b) for x in full.candidates] == [(1, 100), (1, 200), (100, 200)]
    subject = analyze(a + b + c, documents, subject_document_pk="doc-c")
    assert [(x.claim_a, x.claim_b) for x in subject.candidates] == [(1, 200), (100, 200)]
    assert subject.of("contradiction") == subject.candidates and subject.of("missing_context") == ()


def test_claims_of_an_unknown_document_or_state_are_refused_or_ignored():
    a = records("doc-a", DRY_15)
    assert analyze(a + records("doc-x", DRY_30, first_id=50), [doc("doc-a")]).candidates == ()
    with pytest.raises(ValueError, match="unknown evidence state"):
        analyze(a, [doc("doc-a", state="approved")])


# ================================================================== controlled fixture measurement

#: (label, text A, text B, expected classification or None). SYNTHETIC statements, labelled by hand.
LABELLED = [
    ("unit_equivalent", DRY_15, DRY_150MM, None),
    ("range_contains_point", DRY_15, DRY_RANGE, None),
    ("identical_week_and_days", "Tưới lại sau 1 tuần giữa các lần tưới.", "Tưới lại sau 7 ngày giữa các lần tưới.", None),
    ("different_stage", "Giai đoạn đẻ nhánh, bón 30 kg/ha phân bón.", "Giai đoạn làm đòng, bón 60 kg/ha phân bón.", None),
    ("different_parameter", DRY_15, "Giữ nước ở mực nước 5 cm trên ruộng.", None),
    ("bund_height_is_not_a_water_depth", DRY_15, "Bờ ruộng cao 30 cm, mực nước dưới mặt ruộng ổn định.", None),
    ("ambiguous_number", "Bón 1.500 kg/ha phân bón.", "Bón 100 kg/ha phân bón.", None),
    ("unsupported_unit", "Bón 20 kg phân bón.", "Bón 100 kg/ha phân bón.", None),
    ("dry_down_conflict", DRY_15, DRY_30, "contradiction"),
    ("interval_conflict", "Tưới lại sau 5 ngày giữa các lần tưới.", "Tưới lại sau 2 tuần giữa các lần tưới.",
     "contradiction"),
    ("nitrogen_conflict", "Bón 80 kg N/ha.", "Bón 150 kg N/ha.", "contradiction"),
    ("yield_units_conflict", "Năng suất đạt 6 tấn/ha.", "Năng suất đạt 45 tạ/ha.", "contradiction"),
    ("stage_one_side", "Giai đoạn đẻ nhánh, bón 30 kg/ha phân bón.", "Bón 60 kg/ha phân bón.", "missing_context"),
    ("awd_tag_one_side", "Với ngập khô xen kẽ, năng suất đạt 6 tấn/ha.", "Năng suất đạt 5 tấn/ha.", "missing_context"),
    # kn-claims-3: emission amounts per area and durations
    ("co2e_units_equivalent", "Phát thải 3,2 tấn CO2e/ha mỗi vụ.", "Phát thải 3200 kg CO2tđ/ha.", None),
    ("reduction_is_not_an_emission_level", "Phát thải 250 kg CH4/ha/vụ.", "Tưới tiết kiệm giảm phát thải 50 kg CH4/ha/vụ.",
     None),
    ("per_day_is_not_per_season", "Hệ số phát thải 1,3 kg CH4/ha/ngày.", "Phát thải 250 kg CH4/ha/vụ.", None),
    ("monitoring_window_is_not_an_interval", "Quan trắc mực nước mỗi 3 ngày.", "Quan trắc trong 90 ngày.", None),
    ("seasonal_ch4_conflict", "Phát thải 250 kg CH4/ha/vụ.", "Phát thải 400 kg CH4/ha/vụ.", "contradiction"),
    ("drainage_conflict", "Rút nước 7 ngày trước khi thu hoạch.", "Tháo nước 3 tuần trước khi thu hoạch.",
     "contradiction"),
]


def test_measured_behaviour_on_the_controlled_fixtures():
    """Precision and false positives of the rules on LABELLED. Controlled synthetic pairs only: this
    measures the rules against their own specification, not against real guidance."""
    outcomes = {}
    for label, text_a, text_b, _ in LABELLED:
        candidates = pair(text_a, text_b).candidates
        assert len(candidates) <= 1, label
        outcomes[label] = candidates[0].classification if candidates else None
    expected = {label: want for label, _, _, want in LABELLED}
    assert outcomes == expected
    flagged = [label for label, got in outcomes.items() if got is not None]
    true_positive = [label for label in flagged if expected[label] is not None]
    false_positive = [label for label in flagged if expected[label] is None]
    negatives = [label for label, want in expected.items() if want is None]
    assert (len(LABELLED), len(negatives), len(flagged), len(true_positive), len(false_positive)) == (20, 12, 8, 8, 0)
    assert len(true_positive) / len(flagged) == 1.0                     # precision on these fixtures
    assert set(outcomes.values()) - {None} <= set(CLASSIFICATIONS)


def test_known_false_positive_a_conditional_statement_is_still_flagged():
    """Documented limit: the rules do not read conditions. A reviewer must (the candidate is an aid)."""
    (candidate,) = pair("Bón 60 kg/ha phân bón.", "Nếu đất phèn nặng thì bón 120 kg/ha phân bón.").candidates
    assert candidate.classification == "contradiction"


def test_known_false_positive_an_unstated_variety_or_region_is_still_flagged():
    """Documented limit: variety, region, soil and season are not extracted, so two statements about
    different varieties are reported as a contradiction. Only a reviewer can tell."""
    (candidate,) = pair("Giống ngắn ngày có thời gian sinh trưởng 95-100 ngày.",
                        "Giống dài ngày có thời gian sinh trưởng 130 ngày.").candidates
    assert (candidate.classification, candidate.comparison_key) == ("contradiction", "crop.growth_duration|day")


# ================================================================== kn-claims-3 claim types (M4)

@pytest.mark.parametrize("text, raw, parameter, low, high, unit", [
    ("Phát thải 250 kg CH4/ha/vụ ở ruộng ngập.", "250 kg CH4/ha/vụ", "ch4.seasonal_emission", 250.0, 250.0, "kgCH4/ha"),
    ("Phát thải 3,2 tấn CO2e/ha mỗi vụ.", "3,2 tấn CO2e/ha", "ghg.emission_per_area", 3200.0, 3200.0, "kgCO2e/ha"),
    ("Emission of 1.2 t CO2-eq/ha per season.", "1.2 t CO2-eq/ha", "ghg.emission_per_area", 1200.0, 1200.0, "kgCO2e/ha"),
    ("Hệ số phát thải 1,3 kg CH4/ha/ngày.", "1,3 kg CH4/ha/ngày", "ch4.emission_factor", 1.3, 1.3, "kgCH4/ha/day"),
    ("Rút nước 7 ngày trước khi thu hoạch.", "7 ngày", "water.drainage_duration", 7.0, 7.0, "day"),
    ("Thời gian sinh trưởng 95-100 ngày.", "95-100 ngày", "crop.growth_duration", 95.0, 100.0, "day"),
    ("Quan trắc mực nước mỗi 3 ngày.", "3 ngày", "mrv.monitoring_interval", 3.0, 3.0, "day"),
])
def test_emission_amounts_and_durations_are_extracted_with_their_unit(text, raw, parameter, low, high, unit):
    (claim,) = [c for c in extract_claims(ClaimSource("s/d@v1", "c1", text)) if c.kind == "quantity"]
    assert (claim.text, claim.status, claim.parameter, claim.value_min, claim.value_max, claim.unit) == (
        raw, "extracted", parameter, low, high, unit)
    assert text[claim.start:claim.end] == raw and comparison_key(claim) == f"{parameter}|{unit}"


@pytest.mark.parametrize("text", [
    "Tưới tiết kiệm giảm phát thải 50 kg CH4/ha/vụ.",      # a reduction, not an emission level
    "Chênh lệch phát thải 0,8 tấn CO2e/ha.",               # a difference
    "Ruộng đạt 250 kg CH4/ha/vụ.",                         # no emission cue
    "Quan trắc trong 90 ngày.",                            # a monitoring window, not an interval
    "Sau 5 ngày thì bón.",                                 # a duration nothing names
])
def test_an_emission_or_duration_without_a_clear_meaning_stays_unresolved(text):
    (claim,) = [c for c in extract_claims(ClaimSource("s/d@v1", "c1", text)) if c.kind == "quantity"]
    assert claim.status == "ambiguous" and claim.parameter is None and comparison_key(claim) is None


def test_a_gas_amount_without_an_area_is_unsupported_and_no_unit_is_invented():
    (claim,) = [c for c in extract_claims(ClaimSource("s/d@v1", "c1", "Phát thải 250 kg CH4 mỗi vụ."))
                if c.kind == "quantity"]
    assert claim.status == "unsupported" and claim.value_min is None and claim.unit is None
