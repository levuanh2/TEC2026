"""Offline source-integrity review aid (backend/knowledge/integrity, design RAG_V15_SOURCE_INTEGRITY_OFFLINE.md).

Pure unit tests: no database, network or provider. Synthetic registry values are labelled
`synthetic_test_fixture` and are refused by the production loader. The poisoned_claim scenario is the
benchmark fixture itself (scripts.rag_llm_benchmark), so this file and the benchmark cannot drift apart.

These tests show what the REVIEW AID finds. They do not show that dev3-01 is fixed: nothing here blocks
retrieval or changes a knowledge status (see test_rag_source_integrity_gap.py, PR #49).
"""

from __future__ import annotations

import ast
import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

import scripts.rag_llm_benchmark as bench
from knowledge.ids import sha256_hex
from knowledge.integrity.claims import ClaimSource, extract_claims
from knowledge.integrity.provenance import (ProvenanceClaim, TrustedPublisher, VerificationEvidence,
                                            evaluate_provenance)
from knowledge.integrity.references import RegistryError, load_registry
from knowledge.integrity.review import DocumentContext, review
from recommendation.rules import DATA_TASK_RULE_CODE, evaluate_data_completeness

BACKEND = Path(__file__).resolve().parent.parent
INTEGRITY = BACKEND / "knowledge" / "integrity"
REGISTRY_FILE = INTEGRITY / "reference_registry.json"
AS_OF = date(2026, 11, 9)


def _production_registry():
    return load_registry(json.loads(REGISTRY_FILE.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ provenance

ARTIFACT = b"%PDF-1.7 synthetic artifact bytes"
SHA = sha256_hex(ARTIFACT)
OTHER_SHA = sha256_hex(b"different bytes")
EVIDENCE_BYTES = b"stored signature-verification report"
EVIDENCE_SHA = sha256_hex(EVIDENCE_BYTES)
PUBLISHERS = {"mae-vn": TrustedPublisher("mae-vn", frozenset({"mae.gov.vn", "vanban.chinhphu.vn"}),
                                         frozenset({"CN=Bo Nong nghiep va Moi truong"}))}
URL = "https://mae.gov.vn/van-ban/qd-1.pdf"


def _claim(**overrides) -> ProvenanceClaim:
    base = dict(publisher_id="mae-vn", official_url=URL, declared_sha256=SHA, document_version="2026-01",
                license_basis="official_publication",
                evidence=(VerificationEvidence("pki_signature", "CN=Bo Nong nghiep va Moi truong", SHA, True,
                                               EVIDENCE_SHA),))
    base.update(overrides)
    return ProvenanceClaim(**base)


def _prov(claim: ProvenanceClaim, expected_version: str | None = "2026-01", evidence_files=None):
    files = {EVIDENCE_SHA: EVIDENCE_BYTES} if evidence_files is None else evidence_files
    return evaluate_provenance(ARTIFACT, claim, publishers=PUBLISHERS, evidence_files=files,
                               expected_version=expected_version)


def test_correct_provenance_is_verified_but_content_is_never_assessed():
    report = _prov(_claim())
    assert report.status == "verified" and report.artifact_sha256 == SHA
    assert {c.outcome for c in report.checks} == {"verified"}
    assert report.content_correctness == "not_assessed"


def test_second_channel_hash_from_an_official_host_counts_but_the_download_url_itself_does_not():
    independent = VerificationEvidence("second_channel_sha256", "https://vanban.chinhphu.vn/hash/qd-1", SHA, True,
                                       EVIDENCE_SHA)
    assert _prov(_claim(evidence=(independent,))).status == "verified"
    same_channel = VerificationEvidence("second_channel_sha256", URL, SHA, True, EVIDENCE_SHA)
    report = _prov(_claim(evidence=(same_channel,)))
    assert report.outcome("authenticity") == "unverified_assertion" and report.status == "unverified"


def test_forged_or_altered_artifact_is_a_mismatch():
    report = _prov(_claim(declared_sha256=OTHER_SHA))
    assert report.outcome("artifact_sha256") == "mismatch" and report.status == "mismatch"
    attests_other = VerificationEvidence("pki_signature", "CN=Bo Nong nghiep va Moi truong", OTHER_SHA, True,
                                         EVIDENCE_SHA)
    report = _prov(_claim(evidence=(attests_other,)))
    assert report.outcome("authenticity") == "mismatch" and report.status == "mismatch"
    assert report.outcome("publisher") != "verified"


def test_missing_evidence_is_incomplete_not_verified():
    report = _prov(_claim(evidence=()))
    assert report.outcome("authenticity") == "missing" and report.status == "incomplete"
    assert report.outcome("publisher") == "unverified_assertion"
    assert report.outcome("origin") == "unverified_assertion"


@pytest.mark.parametrize("evidence", [
    VerificationEvidence("operator_assertion", "operator: downloaded it myself", SHA, True, EVIDENCE_SHA),
    VerificationEvidence("pki_signature", "CN=Bo Nong nghiep va Moi truong", SHA, False, EVIDENCE_SHA),  # not independent
    VerificationEvidence("pki_signature", "CN=Bo Nong nghiep va Moi truong", SHA, True, None),          # nothing stored
    VerificationEvidence("pki_signature", "CN=Someone Else", SHA, True, EVIDENCE_SHA),                  # foreign signer
    VerificationEvidence("second_channel_sha256", "https://mirror.example.com/qd-1", SHA, True, EVIDENCE_SHA),
], ids=["assertion", "not-independent", "no-evidence-file", "foreign-signer", "foreign-host"])
def test_unbacked_evidence_never_verifies(evidence):
    report = _prov(_claim(evidence=(evidence,)))
    assert report.outcome("authenticity") == "unverified_assertion"
    assert report.status == "unverified"


@pytest.mark.parametrize("url", [URL + "?v=1", URL + "#download", "https://MAE.GOV.VN/van-ban/qd-1.pdf",
                                 "https://mae.gov.vn:443/van-ban/qd-1.pdf", URL + "/"])
def test_a_respelled_download_url_is_the_same_channel(url):
    evidence = VerificationEvidence("second_channel_sha256", url, SHA, True, EVIDENCE_SHA)
    assert _prov(_claim(evidence=(evidence,))).outcome("authenticity") == "unverified_assertion"


def test_evidence_counts_only_with_its_stored_file_and_never_as_the_artifact_itself():
    assert _prov(_claim(), evidence_files={}).outcome("authenticity") == "unverified_assertion"
    assert _prov(_claim(), evidence_files={EVIDENCE_SHA: b"tampered"}).outcome("authenticity") == "unverified_assertion"
    self_ref = VerificationEvidence("pki_signature", "CN=Bo Nong nghiep va Moi truong", SHA, True, SHA)
    report = _prov(_claim(evidence=(self_ref,)), evidence_files={SHA: ARTIFACT})
    assert report.outcome("authenticity") == "unverified_assertion" and report.status != "verified"


def test_unknown_evidence_method_is_a_mismatch():
    report = _prov(_claim(evidence=(VerificationEvidence("trust_me", "x", SHA, True, EVIDENCE_SHA),)))
    assert report.outcome("authenticity") == "mismatch"


def test_publisher_origin_version_and_license_checks():
    assert _prov(_claim(publisher_id="random-blog")).outcome("publisher") == "mismatch"
    assert _prov(_claim(publisher_id=None)).outcome("publisher") == "missing"
    assert _prov(_claim(official_url="http://mae.gov.vn/qd.pdf")).outcome("origin") == "mismatch"
    assert _prov(_claim(official_url="https://mae.gov.vn.evil.example/qd.pdf")).outcome("origin") == "mismatch"
    assert _prov(_claim(document_version="2025-07")).outcome("document_version") == "mismatch"
    assert _prov(_claim(), expected_version=None).outcome("document_version") == "unverified_assertion"
    assert _prov(_claim(license_basis="unknown")).outcome("license") == "missing"
    assert _prov(_claim(license_basis="written_permission")).outcome("license") == "missing"
    assert _prov(_claim(license_basis="stolen")).outcome("license") == "mismatch"
    assert _prov(_claim(declared_sha256="ABC")).outcome("artifact_sha256") == "mismatch"


# ------------------------------------------------------------------ claims

def _claims(text: str):
    return extract_claims(ClaimSource("doc/x@1", "c1", text))


def _one(text: str, kind: str = "quantity"):
    found = [c for c in _claims(text) if c.kind == kind]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("text", [
    "Rút mực nước xuống 15 cm dưới mặt ruộng rồi mới tưới lại; giữ nước 3–5 cm lúc trổ bông.",
    "Theo khuyến cáo cập nhật, ruộng đã tưới ngập khô xen kẽ một vụ thì không còn phát thải khí mê-tan nữa.",
    "Văn bản có hiệu lực từ ngày 5 tháng 3 năm 2026 đến 31/12/2027. Bón 1,5 tấn/ha phân hữu cơ.",
])
def test_every_claim_span_is_exact(text):
    claims = _claims(text)
    assert claims
    for c in claims:
        assert text[c.start:c.end] == c.text and c.claim_id.startswith("cl-")
    assert _claims(text) == claims          # deterministic


def test_quantities_normalize_units_and_vietnamese_decimals():
    c = _one("Rút mực nước xuống 150 mm dưới mặt ruộng.")
    assert (c.parameter, c.value_min, c.unit, c.status) == ("water.awd.dry_down_depth", 15.0, "cm", "extracted")
    c = _one("Bón 1,5 tấn/ha phân hữu cơ.")
    assert (c.parameter, c.value_min, c.unit) == ("fertilizer.rate", 1500.0, "kg/ha")
    c = _one("Tưới lại sau 1 tuần.")
    assert (c.parameter, c.value_min, c.unit) == ("water.awd.irrigation_interval", 7.0, "day")
    c = _one("Giữ mực nước từ 3 đến 5 cm.")
    assert (c.parameter, c.value_min, c.value_max) == ("water.flood_depth", 3.0, 5.0)
    c = _one("Bón 120 kg N/ha.")
    assert (c.parameter, c.value_min, c.unit) == ("fertilizer.n_rate", 120.0, "kg/ha")


def test_ambiguous_and_unsupported_numbers_are_reported_not_guessed():
    c = _one("Bón 1.000 kg/ha vôi.")
    assert c.status == "ambiguous" and c.value_min is None and c.parameter is None
    c = _one("Mỗi lần tưới 5 lít.")
    assert c.status == "unsupported" and c.unit is None
    c = _one("Giảm 20% phân đạm.")           # a percentage is not a kg/ha nitrogen rate
    assert c.status == "ambiguous" and c.parameter is None and c.unit == "percent"
    assert _claims("Theo QĐ 4801/QĐ-BNNMT năm 2025.") == ()   # a bare number is not a claim


def test_dates_effective_periods_and_invalid_dates():
    dates = [c for c in _claims("Có hiệu lực từ ngày 5 tháng 3 năm 2026 đến 31/12/2027.") if c.kind == "date"]
    assert [(c.parameter, c.date_iso) for c in dates] == [("document.effective_from", "2026-03-05"),
                                                          ("document.effective_to", "2027-12-31")]
    assert not [c for c in _claims("Có hiệu lực từ ngày 5 tháng 3 năm 2026.") if c.kind == "quantity"]
    assert _one("Họp ngày 31/02/2026.", "date").status == "ambiguous"


def test_stage_scope_is_attached():
    c = _one("Giữ mực nước 3-5 cm giai đoạn trổ bông.")
    assert c.stage == "flowering"
    assert _one("Giữ mực nước 3-5 cm giai đoạn trổ bông.", "stage").stage == "flowering"


def test_reduction_and_negated_elimination_are_not_absolute_assertions():
    text = "AWD giảm 30% phát thải mê-tan nhưng không loại bỏ hoàn toàn phát thải."
    assert not [c for c in _claims(text) if c.kind == "assertion"]
    assert _one(text).parameter == "ch4.reduction"
    assert not [c for c in _claims("Cần ghi mực nước mỗi lần tưới.") if c.kind == "assertion"]


# ------------------------------------------------------------------ registry

def test_production_registry_loads_and_claims_no_independent_verification():
    registry = _production_registry()
    assert registry.entries and len(registry.digest) == 64
    assert {e.verification_status for e in registry.entries} <= {"engine_config_pointer", "project_policy"}
    assert not any(e.independently_verified for e in registry.entries)
    assert all(e.verification_pointer for e in registry.entries)
    assert all(e.kind == "qualitative" for e in registry.entries), "no numeric value without a verified source"
    assert load_registry(json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))).digest == registry.digest


def test_engine_config_pointer_still_supports_the_awd_entry():
    """The entry says AWD does not end CH4 because the engine's SFw for multiple drainage is > 0. If that
    configuration ever changes, this entry must be re-reviewed."""
    entry = next(e for e in _production_registry().entries if e.verification_status == "engine_config_pointer")
    path, _, key = entry.verification_pointer.partition("#")
    node = yaml.safe_load((BACKEND.parent / path).read_text(encoding="utf-8"))
    for part in key.split("."):
        node = node[part]
    assert node["value"] > 0 and node["unit"] == "dimensionless"


def test_project_policy_pointer_still_emits_the_water_data_task():
    entry = next(e for e in _production_registry().entries if e.verification_status == "project_policy")
    assert entry.verification_pointer.endswith(f"{DATA_TASK_RULE_CODE}.water")
    tasks = evaluate_data_completeness("season-1", {"yield_kg": 1.0, "data_completeness": {"water": False,
                                                                                          "fertilizer": True,
                                                                                          "cost": True}})
    assert [t.rule_code for t in tasks] == [f"{DATA_TASK_RULE_CODE}.water"]


def _synthetic(*entries) -> dict:
    return {"schema": "kn-reference-registry-1", "registry_version": "test-1", "entries": list(entries)}


SYNTH_DEPTH = {
    "reference_id": "ref-synth-dry-down", "parameter": "water.awd.dry_down_depth", "kind": "quantity",
    "value_min": 15, "value_max": 15, "unit": "cm", "tolerance": 2, "stage": None,
    "source": {"title": "SYNTHETIC test value, not agronomic guidance", "locator": "test", "document_version": "0",
               "url": None, "artifact_sha256": None},
    "scope": "test only", "rationale": "test only",
    "verification": {"status": "synthetic_test_fixture", "pointer": None, "evidence_ref": None, "verified_by": None},
}


def test_synthetic_entries_are_refused_by_the_production_loader():
    with pytest.raises(RegistryError, match="synthetic"):
        load_registry(_synthetic(SYNTH_DEPTH))
    assert load_registry(_synthetic(SYNTH_DEPTH), allow_synthetic=True).entries[0].unit == "cm"


@pytest.mark.parametrize("mutate, message", [
    (lambda e: e["verification"].update(status="independently_verified"), "independently_verified needs"),
    (lambda e: e.update(unit="day"), "incompatible units"),
    (lambda e: e.update(unit="furlong"), "unit must be"),
    (lambda e: e.update(parameter="water.unknown"), "quantity parameter"),
    (lambda e: e.update(value_min=20), "value_min <= value_max"),
    (lambda e: e.update(assertion_holds=False), "no assertion_holds"),
    (lambda e: e["source"].update(url="http://insecure.example"), "https"),
    (lambda e: e.update(reference_id="Bad Id"), "reference_id"),
    (lambda e: e.update(stage="harvest-party"), "stage"),
    (lambda e: e.update(tolerance=999999), "silence every conflict"),
    (lambda e: (e["verification"].update(status="independently_verified", evidence_ref="a" * 64, verified_by="x"),
                e["source"].update(artifact_sha256="b" * 64)), "needs source.url"),
    (lambda e: (e["verification"].update(status="independently_verified", evidence_ref="b" * 64, verified_by="x"),
                e["source"].update(artifact_sha256="b" * 64, url="https://example.org/a.pdf")), "separate evidence"),
])
def test_registry_validation_fails_closed(mutate, message):
    entry = copy.deepcopy(SYNTH_DEPTH)
    mutate(entry)
    with pytest.raises(RegistryError, match=message):
        load_registry(_synthetic(entry), allow_synthetic=True)


def test_registry_refuses_duplicates_and_trust_without_pointer():
    with pytest.raises(RegistryError, match="unique"):
        load_registry(_synthetic(SYNTH_DEPTH, SYNTH_DEPTH), allow_synthetic=True)
    raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    raw["entries"][0]["verification"]["pointer"] = None
    with pytest.raises(RegistryError, match="needs verification.pointer"):
        load_registry(raw)
    raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    raw["entries"][0]["value_min"] = 0
    with pytest.raises(RegistryError, match="qualitative entry has no value"):
        load_registry(raw)


# ------------------------------------------------------------------ review: dev3-01 poisoned_claim

POISON = bench.CHUNK_PRESETS["poisoned_claim"]
CLEAN_AWD = [ClaimSource("fixture/awd@1", c["chunk_id"], c["content"]) for c in bench.AWD_CHUNKS[:2]]
POISON_SRC = ClaimSource("fixture/poison@1", POISON["chunk_id"], POISON["content"])


def test_poisoned_claim_is_flagged_for_expert_review_against_the_registry():
    result = review([*CLEAN_AWD, POISON_SRC], registry=_production_registry(), as_of=AS_OF)
    conflicts = result.of_type("reference_conflict")
    assert {f.reference_ids for f in conflicts} == {("ref-ch4-awd-not-eliminated",), ("ref-water-records-required",)}
    assert all(f.document_refs == ("fixture/poison@1",) and f.needs_expert_review for f in conflicts)
    flagged = {c.claim_id: c for c in result.claims}
    assert {flagged[f.claim_ids[0]].chunk_id for f in conflicts} == {POISON["chunk_id"]}
    assert result.requires_expert_review and result.decision == "none"


def test_the_clean_awd_fixture_chunks_are_not_flagged():
    result = review(CLEAN_AWD, registry=_production_registry(), as_of=AS_OF)
    assert not result.requires_expert_review, result.findings


def test_without_a_registry_entry_the_absolute_assertion_is_still_surfaced():
    registry = load_registry(_synthetic(SYNTH_DEPTH), allow_synthetic=True)
    result = review([POISON_SRC], registry=registry, as_of=AS_OF)
    assert {f.finding_type for f in result.findings} == {"unsupported_assertion"}
    assert len(result.findings) == 2 and result.requires_expert_review


# ------------------------------------------------------------------ review: numeric contradictions and periods

def _src(doc: str, text: str, chunk: str = "c1") -> ClaimSource:
    return ClaimSource(doc, chunk, text)


SYNTH = load_registry(_synthetic(SYNTH_DEPTH), allow_synthetic=True)


def test_numeric_claim_outside_the_reference_is_a_conflict_and_unit_conversion_avoids_a_false_one():
    wrong = review([_src("d/a@1", "Rút mực nước xuống 1,5 cm dưới mặt ruộng.")], registry=SYNTH, as_of=AS_OF)
    assert [f.finding_type for f in wrong.findings] == ["reference_conflict"]
    same_in_mm = review([_src("d/a@1", "Rút mực nước xuống 150 mm dưới mặt ruộng.")], registry=SYNTH, as_of=AS_OF)
    assert not same_in_mm.findings
    within_tolerance = review([_src("d/a@1", "Rút mực nước xuống 16 cm dưới mặt ruộng.")], registry=SYNTH, as_of=AS_OF)
    assert not within_tolerance.findings


def test_contradicting_documents_are_flagged_with_both_references():
    a = _src("d/a@1", "Rút mực nước xuống 15 cm dưới mặt ruộng rồi tưới lại.")
    b = _src("d/b@1", "Rút mực nước xuống 1,5 cm dưới mặt ruộng rồi tưới lại.", "c9")
    result = review([a, b], registry=SYNTH, as_of=AS_OF)
    conflict = result.of_type("claim_conflict")
    assert len(conflict) == 1 and conflict[0].document_refs == ("d/a@1", "d/b@1")
    assert "15 cm vs 1.5 cm" in conflict[0].detail and conflict[0].evidence_needed


def test_incompatible_units_scopes_and_periods_are_not_compared():
    pct = _src("d/a@1", "Giảm 20% phân đạm.")
    rate = _src("d/b@1", "Bón 100 kg N/ha.")
    result = review([pct, rate], registry=SYNTH, as_of=AS_OF)
    assert not result.of_type("claim_conflict") and not result.requires_expert_review
    assert result.of_type("unresolved_claim")          # the percentage is reported, not compared

    flowering = _src("d/a@1", "Giữ mực nước 5 cm lúc trổ bông.")
    tillering = _src("d/b@1", "Giữ mực nước 1 cm lúc đẻ nhánh.")
    assert not review([flowering, tillering], registry=SYNTH, as_of=AS_OF).of_type("claim_conflict")

    old = _src("d/old@1", "Rút mực nước xuống 25 cm dưới mặt ruộng.")
    new = _src("d/new@2", "Rút mực nước xuống 15 cm dưới mặt ruộng.")
    docs = [DocumentContext("d/old@1", date(2020, 1, 1), date(2022, 12, 31)),
            DocumentContext("d/new@2", date(2023, 1, 1), None)]
    result = review([old, new], registry=SYNTH, as_of=date(2022, 6, 1), documents=docs)
    assert not result.of_type("claim_conflict")


def test_expired_not_yet_effective_and_superseded_guidance():
    src = [_src("d/old@1", "Ghi lượng nước tưới."), _src("d/new@2", "Ghi lượng nước tưới.", "c2"),
           _src("d/future@1", "Ghi lượng nước tưới.", "c3")]
    docs = [DocumentContext("d/old@1", date(2020, 1, 1), date(2025, 12, 31)),
            DocumentContext("d/new@2", date(2026, 1, 1), None, supersedes=("d/old@1",)),
            DocumentContext("d/future@1", date(2027, 1, 1), None)]
    result = review(src, registry=SYNTH, as_of=AS_OF, documents=docs)
    assert {f.finding_type for f in result.findings} == {"expired_guidance", "superseded_guidance", "not_yet_effective"}
    assert result.of_type("superseded_guidance")[0].document_refs == ("d/new@2", "d/old@1")


def test_superseded_versions_are_not_compared_as_contradictions():
    old = _src("d/g@1", "Rút mực nước xuống 25 cm dưới mặt ruộng.")
    new = _src("d/g@2", "Rút mực nước xuống 15 cm dưới mặt ruộng.")
    docs = [DocumentContext("d/g@2", supersedes=("d/g@1",)), DocumentContext("d/g@1")]
    result = review([old, new], registry=SYNTH, as_of=AS_OF, documents=docs)
    assert not result.of_type("claim_conflict") and result.of_type("superseded_guidance")


def test_a_legitimate_guidance_document_is_not_flagged():
    text = ("Tưới ngập khô xen kẽ giúp ruộng khô dần giữa các lần tưới và giảm phát thải khí mê-tan so với "
            "ngập liên tục. Khi mực nước rút xuống 15 cm dưới mặt ruộng thì tưới lại. Giữ nước 3-5 cm lúc "
            "trổ bông. Ghi lượng nước tưới của từng lần tưới và ghi khối lượng phân bón sau mỗi lần bón.")
    for registry in (_production_registry(), SYNTH):
        result = review([_src("d/legit@1", text)], registry=registry, as_of=AS_OF)
        assert not result.requires_expert_review, result.findings


# ------------------------------------------------------------------ boundaries

def test_integrity_package_has_no_store_or_status_write_path():
    for path in INTEGRITY.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not modules & {"knowledge.ports", "knowledge.ingest"}, path.name
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {"create_version", "approve", "set_status", "archive"}, path.name


# ------------------------------------------------------------------ regressions from the agy adversarial review

def _assertions(text: str) -> list[str]:
    return [c.parameter for c in _claims(text) if c.kind == "assertion"]


@pytest.mark.parametrize("text", [
    "Hết vụ phát thải khí nhà kính sẽ được đo đạc và báo cáo.",
    "Sau khi hết đợt ngập, phát thải khí nhà kính bắt đầu tăng trở lại.",
    "Phát thải khí nhà kính trong ruộng lúa ngập nước không bao giờ bằng 0.",
    "Để triệt tiêu nguồn phát thải khí nhà kính từ rơm rạ, cần xử lý bằng chế phẩm vi sinh.",
    "The project monitoring period ends before methane emissions peak.",
    "Không phải chỉ ghi chép mực nước mà nông dân còn phải theo dõi ngày bón phân.",
    "AWD chưa hết phát thải mê-tan, chỉ giảm.",
])
def test_review_false_positives_are_not_assertions(text):
    assert _assertions(text) == []


@pytest.mark.parametrize("text, parameter", [
    ("Ap dung ngap kho xen ke mot vu la khong con phat thai metan.", "ch4.rice.emission_eliminated"),
    ("Nong dan khong can ghi chep muc nuoc nua.", "records.water.not_required"),
    ("Áp dụng kỹ thuật tưới AWD giúp đưa phát thải khí mê-tan về 0.", "ch4.rice.emission_eliminated"),
    ("Ruộng làm ngập khô xen kẽ một vụ sẽ giảm 100% phát thải khí mê-tan.", "ch4.rice.emission_eliminated"),
    ("Phát thải khí mê-tan đã hoàn toàn chấm dứt sau một vụ áp dụng AWD.", "ch4.rice.emission_eliminated"),
    ("Áp dụng AWD một vụ sẽ xóa bỏ hoàn toàn phát thải mê-tan trên đồng ruộng.", "ch4.rice.emission_eliminated"),
    ("Ruộng lúa làm AWD không còn xuất hiện hiện tượng phát thải khí mê-tan.", "ch4.rice.emission_eliminated"),
    ("Làm ngập khô xen kẽ thì chẳng còn phát thải mê-tan nữa.", "ch4.rice.emission_eliminated"),
    ("Methane emissions are reduced to zero after one season of AWD.", "ch4.rice.emission_eliminated"),
    ("AWD completely stops methane emissions from rice fields.", "ch4.rice.emission_eliminated"),
    ("Việc ghi chép số liệu nước tưới là hoàn toàn không bắt buộc đối với nông dân.", "records.water.not_required"),
    ("Bà con có thể bỏ qua việc theo dõi mực nước khi làm AWD.", "records.water.not_required"),
    ("Nông dân không cần ghi nhật ký tưới trong suốt cả vụ.", "records.water.not_required"),
])
def test_review_false_negatives_are_now_caught(text, parameter):
    assert parameter in _assertions(text)
    for c in _claims(text):
        assert text[c.start:c.end] == c.text


def test_number_and_unit_regressions():
    assert _one("Hệ số phát thải 0.125 kgCH4/ha/ngày.").value_min == 0.125
    assert _one("Bón 1,500 kg/ha phân bón.").status == "ambiguous"        # 1.5 or 1500: never guessed
    assert _one("Rút mực nước xuống -15 cm dưới mặt ruộng.").status == "ambiguous"
    c = _one("Bón 120 kg N/ha/vụ.")
    assert (c.parameter, c.value_min, c.unit) == ("fertilizer.n_rate", 120.0, "kg/ha")
    assert _one("Năng suất đạt 70 tạ/ha.").value_min == 7000.0
    assert _one("Giữ mực nước 0,05 m.").value_min == 5.0
    assert _one("Effective from 2026-04-15.", "date").date_iso == "2026-04-15"
    assert _one("Lua dat nang suat 6 tan/ha.").parameter == "yield"   # unaccented


def test_parameter_assignment_regressions():
    assert _one("Cần đắp bờ bao cao 30 cm để chủ động giữ nước.").parameter is None
    assert _one("Ống theo dõi mực nước dài 20 cm được cắm vào ruộng.").parameter is None
    yields, rate = [c for c in _claims("Năng suất vụ này đạt 6 tấn/ha nhờ bón cân đối 90 kg/ha phân đạm urê.")
                    if c.kind == "quantity"]
    assert (yields.parameter, rate.parameter) == ("yield", "fertilizer.n_rate")
    sequence = [c for c in _claims("Từ giai đoạn đẻ nhánh giữ mực nước 3 cm, đến khi làm đòng tăng lên 5 cm.")
                if c.kind == "quantity"]
    assert [c.stage for c in sequence] == ["tillering", "panicle_initiation"]


def test_values_listed_in_one_chunk_are_not_contradictions():
    split = _src("d/a@1", "Bón phân đợt 1 với 40 kg/ha đạm, đợt 2 bón tiếp 60 kg/ha đạm.")
    assert not review([split], registry=SYNTH, as_of=AS_OF).of_type("claim_conflict")
