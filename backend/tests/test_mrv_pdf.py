"""M07 part 3 — the PDF evidence report and its artifacts.

Same contract as the workbook: a PDF is a *rendering* of one stored manifest.
It must say what the snapshot says, nothing newer, nothing recomputed; a null
must never read as 0; and nothing in it may look like a certification.

Text is checked by extracting it with pypdf, never by OCR and never by
comparing whole files.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from mrv import report_pdf as rp  # noqa: E402
from service import MrvExportService  # noqa: E402
from tests.test_mrv_export import (  # noqa: E402
    ACTOR, CASE, FACTOR_SET_ROW, ORG, SUCCEEDED_CARBON,
    FakeCarbon, FakeExportStore, FakeRead,
)
from tests.test_mrv_xlsx import _large_manifest, build_manifest, client_for  # noqa: E402,F401

RENDERED_AT = datetime(2026, 9, 13, 9, 0, 0, tzinfo=timezone.utc)
PDF_ID = "abcdef01-2345-6789-abcd-ef0123456789"


def render(manifest: dict, export_id: str = PDF_ID) -> bytes:
    return rp.render_pdf(manifest, export_id=export_id, rendered_at=RENDERED_AT)


def text_of(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def flat(text: str) -> str:
    """Whitespace-free, for values a table cell may have wrapped."""
    return "".join(text.split())


def carbon_manifest() -> dict:
    manifest, *_ = build_manifest(FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW)),
                                  FakeCarbon(row=SUCCEEDED_CARBON))
    return manifest


# --------------------------------------------------------------------------
# Document structure
# --------------------------------------------------------------------------

def test_the_bytes_are_a_real_pdf_with_pages():
    manifest, *_ = build_manifest()
    data = render(manifest)
    assert data.startswith(b"%PDF-") and b"%%EOF" in data[-64:]
    assert len(data) > 1000
    assert len(PdfReader(io.BytesIO(data)).pages) > 0


def test_every_page_has_a_numbered_footer_and_a_non_certification_note():
    manifest, *_ = build_manifest()
    pages = PdfReader(io.BytesIO(render(manifest))).pages
    for number, page in enumerate(pages, start=1):
        text = page.extract_text()
        assert f"Trang {number} / {len(pages)}" in text
        assert "không phải chứng nhận" in text


def test_the_cover_identifies_the_report_and_the_snapshot():
    manifest, *_ = build_manifest()
    cover = PdfReader(io.BytesIO(render(manifest))).pages[0].extract_text()
    assert "Gói báo cáo MRV" in cover
    assert "MRV EVIDENCE REPORT" in cover
    assert "DEMO-MRV-2026" in cover and "Hồ sơ MRV demo" in cover
    assert manifest["export_id"] in cover and PDF_ID in cover
    assert "1.0" in cover
    assert flat(rp.COVER_DISCLAIMER) in flat(cover)
    assert "Không phải chứng nhận" in cover


def test_no_certification_or_compliance_claims():
    manifest, *_ = build_manifest()
    text = text_of(render(manifest)).lower()
    for claim in ("certified", "certificate", "compliant", "verified by", "đã được chứng nhận",
                  "đạt chuẩn mrv", "tín chỉ carbon đã"):
        assert claim not in text, claim


def test_vietnamese_text_round_trips_without_replacement_glyphs():
    manifest, *_ = build_manifest()
    manifest["steps"][1]["notes"] = "Khuyến nghị bổ sung ảnh hiện trường"
    manifest["activities"].append({
        "activity_id": "a-irr", "crop_season_id": manifest["activities"][0]["crop_season_id"],
        "production_batch_id": None, "activity_type": "irrigation", "occurred_at": "2026-07-02T03:00:00Z",
        "recorded_at": "2026-07-02T03:00:00Z", "source": "web", "recorded_by": ACTOR, "note": None,
        "deleted_at": None, "provenance": {"device_id": None, "client_event_id": None},
        "detail": {"method": "awd", "water_volume_m3": "12.500"},
    })
    text = text_of(render(manifest))
    for phrase in ("Thu hoạch", "Tưới nước", "Bằng chứng", "Khuyến nghị", "Chưa đủ dữ liệu",
                   "Không phải chứng nhận", "kgCO₂e/kg", "m³"):
        assert phrase in text, phrase
    assert "�" not in text and "■" not in text


def test_the_same_snapshot_renders_the_same_bytes():
    manifest, *_ = build_manifest()
    assert render(manifest) == render(copy.deepcopy(manifest))


def test_the_renderer_refuses_something_that_is_not_a_v1_manifest():
    with pytest.raises(ValueError):
        rp.render_pdf({"hello": "world"})
    manifest, *_ = build_manifest()
    with pytest.raises(ValueError):
        rp.render_pdf(dict(manifest, schema_version="2.0"))


def test_filename_is_deterministic_and_ascii():
    name = rp.report_filename("Hồ sơ/2026", "2026-09-13T08:00:00Z", PDF_ID)
    assert name == "agricarbon-mrv-Ho-so-2026-2026-09-13-abcdef01.pdf"
    assert name.isascii() and "/" not in name


# --------------------------------------------------------------------------
# Content semantics
# --------------------------------------------------------------------------

def test_step_statuses_are_preserved_and_not_started_is_not_failure():
    manifest, *_ = build_manifest()
    manifest["steps"].append({"step_no": 3, "name": "Thiết lập đường cơ sở", "status": "not_started",
                              "started_at": None, "completed_at": None, "notes": None, "evidence_count": 0})
    text = flat(text_of(render(manifest)))
    assert flat("Chưa bắt đầu (not_started)") in text
    assert flat("Đang thực hiện (in_progress)") in text
    assert flat("Hoàn thành (completed)") in text
    assert "Khôngđạt(" not in text


def test_evidence_is_metadata_only_and_no_storage_location_is_printed():
    manifest, *_ = build_manifest()
    text = text_of(render(manifest))
    assert "demo.jpg" in text
    assert flat("KHÔNG được nhúng") in flat(text)
    assert "Chưa có mã băm" in text
    assert f"{ORG}/{CASE}" not in text
    assert "mrv-evidence" not in text and "mrv-exports" not in text


def test_resource_values_come_from_the_snapshot_and_null_reads_as_words():
    manifest, *_ = build_manifest()
    text = text_of(render(manifest))
    assert "0,02317" in text  # fertilizer_per_kg, verbatim digits
    assert "120,5" in text    # fertilizer_kg
    assert re.search(r"Lượng nước\s+Chưa đủ dữ liệu", text), "a null water metric must read as words"
    assert not re.search(r"Lượng nước\s+0\b", text)


def test_ratios_use_documented_display_precision_only():
    assert rp.fmt_number("0.028846153846153848", sig=6) == "0,0288462"
    assert rp.fmt_number("5200.000") == "5.200"
    assert rp.fmt_number("-1234.50") == "-1.234,5"
    assert rp.fmt_number("0") == "0"
    assert rp.fmt_number(None) is None


def test_dates_are_not_shifted_and_instants_are_shown_in_vietnam_time():
    assert rp.fmt_date("2026-05-01") == "01/05/2026"
    assert rp.fmt_local("2026-09-13T20:30:00Z") == "14/09/2026 03:30"
    assert rp.fmt_local("2026-09-13T20:30:00") == "2026-09-13T20:30:00"  # naive: never guessed


def test_null_harvest_values_are_words_not_zero():
    manifest, *_ = build_manifest()
    manifest["harvest"]["events"][0]["moisture_percent"] = None
    text = text_of(render(manifest))
    assert re.search(r"5\.200\s+1,5\s+Chưa đủ dữ liệu", text)


def test_carbon_unavailable_is_a_deliberate_state_not_zero():
    manifest, *_ = build_manifest()
    text = text_of(render(manifest))
    assert "Chưa thể tính CO₂e với bộ dữ liệu/hệ số hiện tại." in text
    assert "no_succeeded_calculation" in text
    assert "0 kgCO₂e" not in text


def test_carbon_available_renders_snapshot_values_breakdown_and_provenance():
    text = text_of(render(carbon_manifest()))
    assert "2.920,8 kgCO₂e" in text
    assert "0,561692 kgCO₂e/kg" in text
    assert "EFc * SFw * A * t" in text
    assert "IPCC-2019-VN-1" in text and "Table 5.11" in text
    assert "factor_provenance_unavailable" not in text
    assert flat("chưa được cơ quan có thẩm quyền") in flat(text)


def test_missing_factor_provenance_is_shown_not_hidden():
    manifest, *_ = build_manifest()
    assert "factor_provenance_unavailable" in text_of(render(manifest))


def test_every_warning_is_rendered_with_its_severity():
    manifest = carbon_manifest()
    text = flat(text_of(render(manifest)))
    assert manifest["warnings"], "fixture must carry warnings"
    for warning in manifest["warnings"]:
        assert flat(warning["code"]) in text, warning["code"]
        assert flat(warning["message"]) in text, warning["message"]
    assert flat("Cảnh báo (warning)") in text and flat("Thông tin (info)") in text


def test_integrity_section_carries_the_payload_digest_and_lineage():
    manifest, *_ = build_manifest()
    text = text_of(render(manifest))
    assert manifest["package_integrity"]["manifest_sha256"] in flat(text)
    assert "source_snapshot_export_id" in text
    assert "file_sha256" in text
    assert "2026-09-13T09:00:00Z" in text  # rendered_at, UTC ISO


def test_activity_quantities_are_not_summed_and_the_appendix_says_when_it_stops(monkeypatch):
    manifest, *_ = build_manifest()
    template = manifest["activities"][0]
    manifest["activities"] = [dict(copy.deepcopy(template), activity_id=f"a-{i:03d}") for i in range(12)]
    monkeypatch.setattr(rp, "ACTIVITY_APPENDIX_LIMIT", 5)
    text = flat(text_of(render(manifest)))
    assert flat("Chỉ in 5 bản ghi đầu; 7 bản ghi còn lại") in text
    assert flat("không cộng dồn khối lượng") in text


# --------------------------------------------------------------------------
# Service: lineage, integrity, immutability, failure
# --------------------------------------------------------------------------

def _service():
    store = FakeExportStore()
    return MrvExportService(store, FakeCarbon()), FakeRead(), store


def test_a_pdf_export_records_its_source_snapshot():
    service, repo, store = _service()
    snapshot = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")
    artifact = service.render(read_repository=repo, export_id=snapshot["export_id"], fmt="pdf")

    assert artifact["format"] == "pdf"
    assert artifact["file_name"].endswith(".pdf")
    assert artifact["source_snapshot_export_id"] == snapshot["export_id"]
    assert artifact["payload_sha256"] == snapshot["payload_sha256"]
    assert artifact["file_sha256"] != snapshot["file_sha256"]
    assert store.rows[artifact["export_id"]]["export_payload"] == snapshot["manifest"]


def test_creating_a_pdf_directly_produces_one_snapshot_and_one_pdf():
    service, repo, store = _service()
    artifact = service.create(read_repository=repo, mrv_case_id=CASE, fmt="pdf")
    assert sorted(r["format"] for r in store.rows.values()) == ["json", "pdf"]
    assert store.rows[artifact["source_snapshot_export_id"]]["format"] == "json"


def test_xlsx_and_pdf_are_siblings_of_the_same_snapshot():
    service, repo, _ = _service()
    snapshot = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")
    xlsx = service.render(read_repository=repo, export_id=snapshot["export_id"], fmt="xlsx")
    pdf = service.render(read_repository=repo, export_id=snapshot["export_id"], fmt="pdf")
    assert xlsx["source_snapshot_export_id"] == pdf["source_snapshot_export_id"] == snapshot["export_id"]
    assert xlsx["payload_sha256"] == pdf["payload_sha256"] == snapshot["payload_sha256"]


def test_file_sha256_matches_the_stored_pdf_and_download_serves_it():
    service, repo, store = _service()
    artifact = service.create(read_repository=repo, mrv_case_id=CASE, fmt="pdf")
    row = store.rows[artifact["export_id"]]
    stored = store.objects[row["storage_object_path"]]
    assert hashlib.sha256(stored).hexdigest() == row["file_sha256"]
    assert artifact["byte_size"] == len(stored)
    data, filename, media_type = service.download(read_repository=repo, export_id=artifact["export_id"])
    assert data == stored and media_type == "application/pdf" and filename.endswith(".pdf")


def test_a_pdf_renders_the_old_snapshot_after_source_data_changes():
    """The critical one: the report describes the snapshot, not the present."""
    service, repo, _ = _service()
    snapshot_a = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")

    repo._evidence.append({
        "id": "e-late", "step_no": 2, "production_batch_id": None, "evidence_type": "doc",
        "file_name": "late.pdf", "mime_type": "application/pdf", "sha256": "b" * 64,
        "storage_bucket": "mrv-evidence", "storage_object_path": f"{ORG}/{CASE}/late.pdf",
        "uploaded_by": ACTOR, "uploaded_at": datetime(2026, 9, 14, tzinfo=timezone.utc),
    })
    repo._metrics["fertilizer_kg"] = "130.25"

    pdf_a = service.render(read_repository=repo, export_id=snapshot_a["export_id"], fmt="pdf")
    text_a = text_of(service.download(read_repository=repo, export_id=pdf_a["export_id"])[0])
    assert "late.pdf" not in text_a and "130,25" not in text_a
    assert "120,5" in text_a

    snapshot_b = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")
    pdf_b = service.render(read_repository=repo, export_id=snapshot_b["export_id"], fmt="pdf")
    text_b = text_of(service.download(read_repository=repo, export_id=pdf_b["export_id"])[0])
    assert "late.pdf" in text_b and "130,25" in text_b


@pytest.mark.parametrize("rendered", ["xlsx", "pdf"])
def test_rendering_a_pdf_from_a_rendering_is_refused(rendered):
    service, repo, _ = _service()
    artifact = service.create(read_repository=repo, mrv_case_id=CASE, fmt=rendered)
    with pytest.raises(Exception) as exc:
        service.render(read_repository=repo, export_id=artifact["export_id"], fmt="pdf")
    assert exc.type.__name__ == "UnsupportedExportFormatError"


def test_a_missing_pdf_object_is_a_controlled_failure_not_a_rebuild():
    service, repo, store = _service()
    artifact = service.create(read_repository=repo, mrv_case_id=CASE, fmt="pdf")
    store.objects.clear()
    with pytest.raises(Exception) as exc:
        service.download(read_repository=repo, export_id=artifact["export_id"])
    assert exc.type.__name__ == "MrvArtifactMissingError"
    assert store.objects == {}


def test_tampered_pdf_bytes_fail_closed():
    service, repo, store = _service()
    artifact = service.create(read_repository=repo, mrv_case_id=CASE, fmt="pdf")
    path = store.rows[artifact["export_id"]]["storage_object_path"]
    store.objects[path] = store.objects[path] + b"%tampered"
    with pytest.raises(Exception) as exc:
        service.download(read_repository=repo, export_id=artifact["export_id"])
    assert exc.type.__name__ == "MrvArtifactCorruptError"


def test_a_render_failure_writes_no_object_and_no_row(monkeypatch):
    service, repo, store = _service()
    snapshot = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")

    def boom(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(rp, "render_pdf", boom)
    with pytest.raises(RuntimeError):
        service.render(read_repository=repo, export_id=snapshot["export_id"], fmt="pdf")
    assert store.objects == {}
    assert list(store.rows) == [snapshot["export_id"]]
    data, _, _ = service.download(read_repository=repo, export_id=snapshot["export_id"])
    assert json.loads(data)["export_id"] == snapshot["export_id"]  # snapshot still valid


def test_a_failed_metadata_insert_removes_the_uploaded_object(monkeypatch):
    service, repo, store = _service()
    snapshot = service.create(read_repository=repo, mrv_case_id=CASE, fmt="json")
    original = store.create

    def failing_create(**kw):
        if kw["fmt"] == "pdf":
            raise RuntimeError("insert failed")
        return original(**kw)

    monkeypatch.setattr(store, "create", failing_create)
    with pytest.raises(RuntimeError):
        service.render(read_repository=repo, export_id=snapshot["export_id"], fmt="pdf")
    assert store.objects == {}, "an object no row points at must be cleaned up"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def test_manager_generates_and_downloads_pdf(client_for):
    client, _ = client_for(FakeRead())
    created = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"})
    assert created.status_code == 201
    body = created.json()
    assert body["format"] == "pdf" and body["file_name"].endswith(".pdf")

    response = client.get(f"/v1/mrv/exports/{body['export_id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition == f'attachment; filename="{body["file_name"]}"'
    assert response.content.startswith(b"%PDF-")
    assert hashlib.sha256(response.content).hexdigest() == body["file_sha256"]


def test_manager_renders_a_pdf_from_an_existing_snapshot(client_for):
    client, _ = client_for(FakeRead())
    snapshot = client.post(f"/v1/mrv/cases/{CASE}/exports").json()
    response = client.post(f"/v1/mrv/exports/{snapshot['export_id']}/render", json={"format": "pdf"})
    assert response.status_code == 201
    assert response.json()["source_snapshot_export_id"] == snapshot["export_id"]

    refused = client.post(f"/v1/mrv/exports/{response.json()['export_id']}/render", json={"format": "pdf"})
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"]["code"] == "unsupported_export_format"


def test_the_pdf_response_never_names_the_bucket_or_object_path(client_for):
    client, _ = client_for(FakeRead())
    text = json.dumps(client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"}).json())
    assert "storage_object_path" not in text and "storage_bucket" not in text
    assert "mrv-exports" not in text and f"{ORG}/{CASE}" not in text


def test_a_farmer_cannot_generate_render_or_download_pdf(client_for):
    manager, store = client_for(FakeRead())
    snapshot = manager.post(f"/v1/mrv/cases/{CASE}/exports").json()
    pdf = manager.post(f"/v1/mrv/exports/{snapshot['export_id']}/render", json={"format": "pdf"}).json()
    farmer, _ = client_for(FakeRead(roles=("farmer",)), store=store)
    assert farmer.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"}).status_code == 404
    assert farmer.post(f"/v1/mrv/exports/{snapshot['export_id']}/render", json={"format": "pdf"}).status_code == 404
    assert farmer.get(f"/v1/mrv/exports/{pdf['export_id']}/download").status_code == 404


def test_a_cross_org_manager_cannot_reach_a_pdf(client_for):
    manager, store = client_for(FakeRead())
    snapshot = manager.post(f"/v1/mrv/cases/{CASE}/exports").json()
    pdf = manager.post(f"/v1/mrv/exports/{snapshot['export_id']}/render", json={"format": "pdf"}).json()
    stranger = FakeRead(roles=("cooperative_manager",), membership_org="99999999-9999-9999-9999-999999999999")
    other, _ = client_for(stranger, store=store)
    assert other.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"}).status_code == 404
    assert other.post(f"/v1/mrv/exports/{snapshot['export_id']}/render", json={"format": "pdf"}).status_code == 404
    assert other.get(f"/v1/mrv/exports/{pdf['export_id']}/download").status_code == 404


def test_unauthenticated_pdf_routes_are_401():
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    assert client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"}).status_code == 401
    assert client.post(f"/v1/mrv/exports/{CASE}/render", json={"format": "pdf"}).status_code == 401
    assert client.get(f"/v1/mrv/exports/{CASE}/download").status_code == 401
    assert client.get(f"/v1/mrv/exports/{CASE}").status_code == 401


def test_a_missing_pdf_object_returns_404_with_the_shared_envelope(client_for):
    client, store = client_for(FakeRead())
    created = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"}).json()
    store.objects.clear()
    response = client.get(f"/v1/mrv/exports/{created['export_id']}/download")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "export_artifact_missing"


def test_a_tampered_pdf_returns_409_and_no_partial_body(client_for):
    client, store = client_for(FakeRead())
    created = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"}).json()
    path = store.rows[created["export_id"]]["storage_object_path"]
    store.objects[path] = b"%PDF-1.4 not the recorded report"
    response = client.get(f"/v1/mrv/exports/{created['export_id']}/download")
    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == "export_artifact_integrity_failed"
    assert not response.content.startswith(b"%PDF")


# --------------------------------------------------------------------------
# Scale
# --------------------------------------------------------------------------

def test_a_large_manifest_renders_with_readable_pagination():
    manifest, *_ = build_manifest()
    big = _large_manifest(manifest, activities=1000, evidence=100)
    template = big["warnings"][0]
    big["warnings"] = [dict(template, code=f"synthetic_{i:02d}", message=f"Cảnh báo tổng hợp {i}")
                       for i in range(10)]

    started = time.monotonic()
    data = render(big)
    elapsed = time.monotonic() - started

    reader = PdfReader(io.BytesIO(data))
    text = text_of(data)
    assert len(reader.pages) > 20
    assert "1000 bản ghi" in text
    assert all(f"synthetic_{i:02d}" in flat(text) for i in range(10))
    # Every appendix page repeats the table header rather than continuing bare.
    appendix = [p.extract_text() for p in reader.pages if "Thời điểm" in p.extract_text()
                and "Giá trị ghi nhận" in p.extract_text()]
    assert len(appendix) >= 20
    # Generous: guards against an accidental quadratic, not a few hundred ms.
    assert elapsed < 60, f"1000-activity PDF took {elapsed:.1f}s"
    assert len(data) < 8 * 1024 * 1024
    print(f"\n  large PDF: {elapsed:.2f}s, {len(data) / 1024:.0f} KiB, {len(reader.pages)} pages")
