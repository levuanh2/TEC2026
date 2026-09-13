"""M07 part 1 — MRV JSON evidence package.

Nothing here touches hosted data: the read repository and the export store are
fakes with the same contracts the real ones expose. The RLS behaviour those
fakes stand in for is covered separately against a real database; what is
covered here is the export's own contract — the manifest shape, canonical
serialization, checksum, warnings, authorization mapping and snapshot semantics.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from infrastructure.mrv_export_repo import (  # noqa: E402
    MrvArtifactMissingError,
    MrvExportNotFoundError,
)
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from mrv import manifest as m  # noqa: E402
from service import MrvExportService  # noqa: E402

CASE = "11111111-1111-1111-1111-111111111111"
ORG = "22222222-2222-2222-2222-222222222222"
SEASON = "33333333-3333-3333-3333-333333333333"
BATCH = "44444444-4444-4444-4444-444444444444"
ACTOR = "55555555-5555-5555-5555-555555555555"
FACTOR_SET = "66666666-6666-6666-6666-666666666666"
AT = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

class FakeRead:
    def __init__(self, *, visible=True, roles=("cooperative_manager",), evidence=None,
                 carbon=None, metrics=None, activities=None, scope=True, factor_sets=None,
                 membership_org=ORG, membership_ended_at=None):
        self.visible = visible
        self.roles = list(roles)
        self.membership_org = membership_org
        self.membership_ended_at = membership_ended_at
        self._evidence = evidence if evidence is not None else [{
            "id": "e1", "step_no": 1, "production_batch_id": None, "evidence_type": "photo",
            "file_name": "demo.jpg", "mime_type": "image/jpeg", "sha256": None,
            "storage_bucket": "mrv-evidence", "storage_object_path": f"{ORG}/{CASE}/demo.jpg",
            "uploaded_by": ACTOR, "uploaded_at": AT,
        }]
        self._carbon = carbon
        self._metrics = metrics if metrics is not None else {
            "yield_kg": Decimal("5200.000"), "water_m3": None, "fertilizer_kg": Decimal("120.5"),
            "water_per_kg": None, "fertilizer_per_kg": Decimal("0.02317"),
            "cost_per_kg": None, "co2e_per_kg": None,
            "data_completeness": {"water": False, "fertilizer": True, "cost": False, "carbon": False},
        }
        self._activities = activities if activities is not None else [
            {"id": "a1", "production_batch_id": BATCH, "activity_type": "harvest",
             "occurred_at": datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
             "recorded_at": AT, "source": "mobile_offline", "recorded_by": ACTOR,
             "device_id": "d1", "client_event_id": "c1", "note": "thu hoach",
             "deleted_at": None, "crop_season_id": SEASON,
             "detail": {"yield_kg": Decimal("5200.000"), "harvested_area_ha": Decimal("1.50"),
                        "moisture_percent": Decimal("14.20"), "total_cost_vnd": None}},
            {"id": "a2", "production_batch_id": BATCH, "activity_type": "irrigation",
             "occurred_at": datetime(2026, 7, 1, 3, 0, tzinfo=timezone.utc),
             "recorded_at": AT, "source": "web", "recorded_by": ACTOR,
             "device_id": None, "client_event_id": None, "note": None,
             "deleted_at": datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc),
             "crop_season_id": SEASON,
             "detail": {"method": "awd", "water_volume_m3": Decimal("12.500")}},
        ]
        self._scope = scope
        self._factor_sets = factor_sets or {}

    def _gate(self):
        if not self.visible:
            raise ReadNotFoundError("mrv_cases")

    def mrv_case_row(self, case_id):
        self._gate()
        return {"id": CASE, "case_code": "DEMO-MRV-2026", "name": "Hồ sơ MRV demo",
                "status": "draft", "period_start": date(2026, 5, 1), "period_end": date(2026, 9, 30),
                "organization_id": ORG, "created_at": AT, "updated_at": AT}

    def me(self):
        return {
            "user_id": ACTOR,
            "roles": self.roles,
            "organization_memberships": [
                {"organization_id": self.membership_org, "user_id": ACTOR,
                 "role": role, "ended_at": self.membership_ended_at}
                for role in self.roles
            ],
        }

    def organization(self, org_id):
        return {"id": ORG, "organization_code": "DEMO-ORG", "name": "HTX demo",
                "organization_type": "cooperative"}

    def mrv_steps(self, case_id):
        self._gate()
        return [
            {"step_no": 1, "name": "Chuẩn bị", "status": "completed",
             "started_at": AT, "completed_at": AT, "notes": None},
            {"step_no": 2, "name": "Đăng ký", "status": "in_progress",
             "started_at": AT, "completed_at": None, "notes": "đang làm"},
        ]

    def mrv_evidence_rows(self, case_id):
        self._gate()
        return list(self._evidence)

    def mrv_scope(self, case_id):
        self._gate()
        if not self._scope:
            return []
        return [{"production_batch_id": BATCH, "batch_code": "default",
                 "crop_season_id": SEASON, "season_code": "DEMO-HT-2026",
                 "season_status": "active", "started_on": date(2026, 5, 10),
                 "closed_on": None, "plot_id": "p1", "plot_code": "P-01",
                 "plot_area_ha": Decimal("1.50"), "farm_id": "f1",
                 "farm_code": "DEMO-FARM-01", "farm_name": "Hộ demo"}]

    def export_activities(self, season_ids):
        return [a for a in self._activities if a["crop_season_id"] in season_ids]

    def metrics_for_seasons(self, season_ids):
        return {sid: dict(self._metrics) for sid in season_ids}

    def emission_factor_provenance(self, ids):
        sets = {k: v for k, v in self._factor_sets.items() if k in ids}
        factors = {k: v.pop("factors", []) if isinstance(v, dict) else [] for k, v in
                   copy.deepcopy(sets).items()}
        return sets, factors

    def mrv_case_scopes(self):
        return [{"id": CASE, "organization_id": ORG}] if self.visible else []


class FakeCarbon:
    def __init__(self, row=None, raises=False):
        self.row, self.raises = row, raises

    def latest(self, season_id, scenario=None):
        if self.raises:
            raise RuntimeError("carbon backend unreachable")
        return self.row


class FakeExportStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.objects: dict[str, bytes] = {}

    def create(self, **kw):
        row = {
            "id": kw["export_id"], "mrv_case_id": kw["mrv_case_id"], "format": kw["fmt"],
            "factor_set_id": kw["factor_set_id"], "scope_description": kw["scope_description"],
            "data_as_of_at": kw["data_as_of_at"], "contains_sample_data": False,
            "is_finalized": False, "warning_text": kw["warning_text"],
            "storage_bucket": "mrv-exports", "storage_object_path": kw["storage_object_path"],
            "file_sha256": kw["file_sha256"], "generated_by": kw["generated_by"],
            "payload_sha256": kw.get("payload_sha256"),
            "source_snapshot_export_id": kw.get("source_snapshot_export_id"),
            "generated_at": kw["generated_at"],
            # Stored as JSON, exactly as jsonb would: proves the snapshot survives
            # a serialization round trip rather than aliasing a live dict.
            "export_payload": json.loads(json.dumps(kw["payload"])),
        }
        self.rows[kw["export_id"]] = row
        return row

    def artifact_row(self, export_id, *, authorized_case_ids):
        row = self.rows.get(export_id)
        if row is None or row["mrv_case_id"] not in authorized_case_ids:
            raise MrvExportNotFoundError()
        return row

    # -- artifact object store (in memory, same contract as Supabase Storage) --

    def put_artifact(self, object_path, data, content_type):
        if object_path in self.objects:
            raise RuntimeError("object already exists")  # upsert=false, as in production
        self.objects[object_path] = bytes(data)

    def get_artifact(self, object_path):
        data = self.objects.get(object_path)
        if data is None:
            raise MrvArtifactMissingError(object_path)
        return data


SUCCEEDED_CARBON = {
    "id": "calc-1", "status": "succeeded", "calculated_at": AT,
    "total_co2e_kg": Decimal("2920.800000"), "co2e_per_kg": Decimal("0.56169231"),
    "yield_kg": Decimal("5200.000000"), "scenario": "as_recorded",
    "engine_version": "1.4.0", "methodology_tier": 1, "factor_set_id": FACTOR_SET,
    "warnings": ["yield taken from a single harvest event"],
    "breakdown": [
        {"category": "methane", "gas": "ch4", "activity_value": Decimal("1.5"),
         "activity_unit": "ha", "factor_value_used": Decimal("1.30"),
         "gas_kg": Decimal("104.0"), "co2e_kg": Decimal("2912.0"),
         "emission_factor_id": "ef-1", "activity_id": "a2",
         "formula_expression": "EFc * SFw * A * t"},
    ],
}

FACTOR_SET_ROW = {
    FACTOR_SET: {
        "id": FACTOR_SET, "version_code": "IPCC-2019-VN-1", "name": "Bộ hệ số demo",
        "methodology_name": "IPCC 2019 Refinement", "methodology_version": "2019",
        "source_name": "IPCC", "source_url": "https://example.invalid/ipcc",
        "status": "published", "valid_from": date(2026, 1, 1), "valid_to": None,
        "published_at": AT,
        "factors": [
            {"factor_code": "ch4_baseline", "category": "methane", "gas": "ch4",
             "factor_value": Decimal("1.30"), "activity_unit": "ha",
             "result_unit": "kgCO2e", "source_reference": "Table 5.11",
             "verification_status": "verified", "parameter_kind": "emission_factor",
             "uncertainty_range": "±20%"},
            {"factor_code": "n2o_direct", "category": "nitrous_oxide", "gas": "n2o",
             "factor_value": Decimal("0.01"), "activity_unit": "kgN",
             "result_unit": "kgCO2e", "source_reference": "Table 11.1",
             "verification_status": "unverified", "parameter_kind": "emission_factor",
             "uncertainty_range": None},
        ],
    }
}


def build_service(read=None, carbon=None):
    store = FakeExportStore()
    return MrvExportService(store, carbon or FakeCarbon()), (read or FakeRead()), store


def generate(read=None, carbon=None):
    service, repo, store = build_service(read, carbon)
    return service.create(read_repository=repo, mrv_case_id=CASE), service, repo, store


# --------------------------------------------------------------------------
# Canonical form and checksum
# --------------------------------------------------------------------------

def test_canonical_bytes_are_key_order_independent():
    a = {"b": 1, "a": {"y": 2, "x": [3, 4]}}
    b = {"a": {"x": [3, 4], "y": 2}, "b": 1}
    assert m.canonical_bytes(a) == m.canonical_bytes(b)


def test_canonical_bytes_are_compact_utf8():
    raw = m.canonical_bytes({"name": "Hồ sơ", "n": 1})
    assert b", " not in raw and b'": ' not in raw
    assert "Hồ sơ" in raw.decode("utf-8")


def test_same_logical_payload_hashes_the_same():
    first, _, _, _ = generate()
    second, _, _, _ = generate()
    volatile = ("export_id", "generated_at")
    a = {k: v for k, v in first["manifest"].items() if k not in volatile}
    b = {k: v for k, v in second["manifest"].items() if k not in volatile}
    a.pop("package_integrity"), b.pop("package_integrity")
    assert m.canonical_bytes(a) == m.canonical_bytes(b)


def test_checksum_excludes_itself_and_verifies():
    result, _, _, _ = generate()
    manifest = result["manifest"]
    assert m.verify_checksum(manifest)
    assert manifest["package_integrity"]["canonical_over"] == "manifest-without-package_integrity"
    # Recomputing over the whole manifest (integrity included) must NOT match --
    # that is the mistake the documented process exists to prevent.
    import hashlib
    naive = hashlib.sha256(m.canonical_bytes(manifest)).hexdigest()
    assert naive != manifest["package_integrity"]["manifest_sha256"]


def test_one_meaningful_field_changes_the_hash():
    result, _, _, _ = generate()
    manifest = copy.deepcopy(result["manifest"])
    before = m.manifest_checksum(manifest)
    manifest["case"]["status"] = "in_progress"
    assert m.manifest_checksum(manifest) != before


def test_checksum_is_stable_across_a_json_round_trip():
    result, _, _, store = generate()
    stored = store.rows[result["export_id"]]["export_payload"]
    assert m.verify_checksum(stored)
    # `payload_sha256` is the manifest digest; `file_sha256` digests the served
    # bytes, which include the integrity block the manifest digest excludes.
    assert stored["package_integrity"]["manifest_sha256"] == result["payload_sha256"]
    assert result["file_sha256"] != result["payload_sha256"]


# --------------------------------------------------------------------------
# Timestamps and numbers
# --------------------------------------------------------------------------

def test_timestamps_are_utc_zulu_and_dates_stay_dates():
    result, _, _, _ = generate()
    manifest = result["manifest"]
    assert manifest["generated_at"].endswith("Z")
    assert manifest["case"]["period_start"] == "2026-05-01"
    assert manifest["case"]["created_at"] == "2026-09-13T08:00:00Z"


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc():
    with pytest.raises(ValueError):
        m.iso_utc(datetime(2026, 9, 13, 8, 0, 0))


def test_numeric_precision_is_preserved_as_text():
    result, _, _, _ = generate()
    harvest = result["manifest"]["harvest"]["events"][0]
    assert harvest["yield_kg"] == "5200.000"
    assert harvest["harvested_area_ha"] == "1.50"


# --------------------------------------------------------------------------
# Null is not zero
# --------------------------------------------------------------------------

def test_missing_metrics_stay_null_and_are_not_zeroed():
    result, _, _, _ = generate()
    metrics = result["manifest"]["resource_metrics"]["per_crop_season"][SEASON]
    assert metrics["water_per_kg"] is None
    assert metrics["cost_per_kg"] is None
    assert metrics["fertilizer_per_kg"] == "0.02317"
    assert metrics["data_completeness"] == {
        "carbon": False, "cost": False, "fertilizer": True, "water": False
    }


def test_incomplete_metrics_raise_an_info_warning_not_an_error():
    result, _, _, _ = generate()
    warning = _find(result["manifest"], m.WarningCode.RESOURCE_METRIC_INCOMPLETE)
    assert warning["severity"] == "info"
    assert warning["related"]["missing"] == ["carbon", "cost", "water"]


# --------------------------------------------------------------------------
# Carbon
# --------------------------------------------------------------------------

def _find(manifest, code):
    for w in manifest["warnings"]:
        if w["code"] == code:
            return w
    raise AssertionError(f"no warning {code} in {[w['code'] for w in manifest['warnings']]}")


def test_carbon_unavailable_still_produces_a_package():
    result, _, _, _ = generate()
    carbon = result["manifest"]["carbon"]["per_crop_season"][SEASON]
    assert carbon["status"] == "unavailable"
    assert carbon["reason"] == "no_succeeded_calculation"
    assert carbon["total_co2e_kg"] is None
    assert _find(result["manifest"], m.WarningCode.CARBON_UNAVAILABLE)
    assert result["manifest"]["readiness"]["carbon_available"] is False


def test_carbon_backend_failure_degrades_to_a_warning_not_a_failed_export():
    result, _, _, _ = generate(carbon=FakeCarbon(raises=True))
    assert result["manifest"]["carbon"]["per_crop_season"][SEASON]["status"] == "unavailable"


def test_carbon_present_is_copied_verbatim_with_provenance():
    read = FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW))
    result, _, _, _ = generate(read=read, carbon=FakeCarbon(SUCCEEDED_CARBON))
    carbon = result["manifest"]["carbon"]["per_crop_season"][SEASON]
    assert carbon["status"] == "succeeded"
    assert carbon["total_co2e_kg"] == "2920.800000"
    assert carbon["calculation_id"] == "calc-1"
    assert carbon["breakdown"][0]["formula_expression"] == "EFc * SFw * A * t"
    provenance = result["manifest"]["provenance"]["emission_factor_sets"][0]
    assert provenance["methodology_name"] == "IPCC 2019 Refinement"
    assert provenance["source_name"] == "IPCC"
    assert [f["factor_code"] for f in provenance["factors"]] == ["ch4_baseline", "n2o_direct"]
    assert result["manifest"]["readiness"]["carbon_available"] is True


def test_unverified_factors_are_flagged():
    read = FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW))
    result, _, _, _ = generate(read=read, carbon=FakeCarbon(SUCCEEDED_CARBON))
    warning = _find(result["manifest"], m.WarningCode.FACTOR_UNVERIFIED)
    assert warning["related"]["factor_codes"] == ["n2o_direct"]


def test_missing_factor_provenance_is_warned_not_invented():
    result, _, _, _ = generate()
    assert _find(result["manifest"], m.WarningCode.FACTOR_PROVENANCE_UNAVAILABLE)
    assert result["manifest"]["provenance"]["emission_factor_sets"] == []


def test_no_compliance_or_certification_language_anywhere():
    read = FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW))
    result, _, _, _ = generate(read=read, carbon=FakeCarbon(SUCCEEDED_CARBON))
    text = m.canonical_bytes(result["manifest"]).decode("utf-8").lower()
    for claim in ("certified", "mrv_compliant", "mrv compliant", "verified by",
                  "government-approved", "chứng nhận đạt", "đã thẩm định"):
        assert claim not in text, f"package must not claim {claim!r}"
    assert "không phải chứng nhận" in result["manifest"]["disclaimer"].lower()


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

def test_evidence_is_referenced_not_embedded():
    result, _, _, _ = generate()
    item = result["manifest"]["evidence"][0]
    assert item["storage"]["included_in_package"] is False
    assert item["storage"]["object_path"].endswith("demo.jpg")
    assert "content" not in item and "bytes" not in item
    assert result["manifest"]["provenance"]["evidence_binaries_included"] is False


def test_missing_evidence_checksum_is_reported_not_fabricated():
    result, _, _, _ = generate()
    assert result["manifest"]["evidence"][0]["checksum"] is None
    warning = _find(result["manifest"], m.WarningCode.EVIDENCE_CHECKSUM_MISSING)
    assert warning["related"]["evidence_ids"] == ["e1"]


def test_present_evidence_checksum_is_carried_through():
    sha = "a" * 64
    read = FakeRead(evidence=[{
        "id": "e9", "step_no": 2, "production_batch_id": None, "evidence_type": "doc",
        "file_name": "bien-ban.pdf", "mime_type": "application/pdf", "sha256": sha,
        "storage_bucket": "mrv-evidence", "storage_object_path": f"{ORG}/{CASE}/bien-ban.pdf",
        "uploaded_by": ACTOR, "uploaded_at": AT,
    }])
    result, _, _, _ = generate(read=read)
    assert result["manifest"]["evidence"][0]["checksum"] == {"algorithm": "sha256", "value": sha}


def test_a_case_with_no_evidence_warns_and_still_exports():
    result, _, _, _ = generate(read=FakeRead(evidence=[]))
    assert result["manifest"]["evidence"] == []
    assert _find(result["manifest"], m.WarningCode.EVIDENCE_NONE)


# --------------------------------------------------------------------------
# Steps, readiness, scope
# --------------------------------------------------------------------------

def test_step_status_semantics_are_preserved():
    result, _, _, _ = generate()
    steps = result["manifest"]["steps"]
    assert [s["status"] for s in steps] == ["completed", "in_progress"]
    assert steps[0]["evidence_count"] == 1 and steps[1]["evidence_count"] == 0
    incomplete = _find(result["manifest"], m.WarningCode.STEP_INCOMPLETE)
    assert incomplete["severity"] == "info"


def test_readiness_counts_real_state_without_inventing_a_score():
    result, _, _, _ = generate()
    readiness = result["manifest"]["readiness"]
    assert readiness == {
        "total_steps": 2, "completed_steps": 1, "remaining_steps": 1,
        "evidence_count": 1, "steps_without_evidence": [2], "carbon_available": False,
    }
    assert "score" not in readiness


def test_a_case_with_no_batches_exports_with_a_scope_warning():
    result, _, _, _ = generate(read=FakeRead(scope=False))
    assert result["manifest"]["scope"]["production_batches"] == []
    assert _find(result["manifest"], m.WarningCode.SCOPE_EMPTY)


# --------------------------------------------------------------------------
# Activities
# --------------------------------------------------------------------------

def test_soft_deleted_activities_are_excluded_by_default():
    result, _, _, _ = generate()
    ids = [a["activity_id"] for a in result["manifest"]["activities"]]
    assert ids == ["a1"]
    assert result["manifest"]["provenance"]["activities"]["includes_deleted"] is False


def test_activity_audit_provenance_is_carried():
    result, _, _, _ = generate()
    activity = result["manifest"]["activities"][0]
    assert activity["provenance"] == {"device_id": "d1", "client_event_id": "c1"}
    assert activity["source"] == "mobile_offline"
    assert activity["recorded_by"] == ACTOR


def test_harvest_uses_the_harvest_event_and_is_not_duplicated():
    result, _, _, _ = generate()
    harvest = result["manifest"]["harvest"]
    assert harvest["event_count"] == 1
    assert harvest["events"][0]["yield_kg"] == "5200.000"


# --------------------------------------------------------------------------
# generated_by
# --------------------------------------------------------------------------

def test_generated_by_comes_from_auth_and_leaks_nothing():
    result, _, _, _ = generate()
    assert result["manifest"]["generated_by"] == {
        "user_id": ACTOR, "roles": ["cooperative_manager"]
    }
    # Never a membership row, a claim set or anything else me() happens to carry.
    assert "organization_memberships" not in result["manifest"]["generated_by"]
    assert set(result["manifest"]["generated_by"]) == {"user_id", "roles"}


def test_no_secret_material_anywhere_in_the_package():
    read = FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW))
    result, _, _, _ = generate(read=read, carbon=FakeCarbon(SUCCEEDED_CARBON))
    text = m.canonical_bytes(result["manifest"]).decode("utf-8").lower()
    for secret in ("bearer ", "eyj", "service_role", "apikey", "postgresql://",
                   "password", "authorization", "jwt", "secret", "access_token"):
        assert secret not in text, f"package must not contain {secret!r}"


# --------------------------------------------------------------------------
# Schema version and filename
# --------------------------------------------------------------------------

def test_schema_version_is_the_declared_constant():
    result, _, _, _ = generate()
    assert m.MANIFEST_SCHEMA_VERSION == "1.0"
    assert result["manifest"]["schema_version"] == "1.0"
    assert result["schema_version"] == "1.0"


def test_filename_is_deterministic_and_sanitized():
    name = m.export_filename("DEMO/MRV 2026\\..", AT, "abcdef01-2345-6789-abcd-ef0123456789")
    assert name == "agricarbon-mrv-DEMO-MRV-2026-2026-09-13-abcdef01.json"
    assert "/" not in name and "\\" not in name and ".." not in name


def test_filename_survives_a_non_ascii_case_code():
    name = m.export_filename("Hồ sơ 2026", AT, "abcdef01-2345-6789-abcd-ef0123456789")
    assert name.isascii() and name.endswith(".json")


# --------------------------------------------------------------------------
# Golden structural contract
# --------------------------------------------------------------------------

def test_golden_manifest_structure():
    """Volatile fields are normalized, then the whole shape is asserted."""
    read = FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW))
    result, _, _, _ = generate(read=read, carbon=FakeCarbon(SUCCEEDED_CARBON))
    manifest = copy.deepcopy(result["manifest"])

    assert sorted(manifest) == [
        "activities", "carbon", "case", "disclaimer", "evidence", "export_id",
        "generated_at", "generated_by", "harvest", "package_integrity",
        "provenance", "readiness", "resource_metrics", "schema_version",
        "scope", "steps", "warnings",
    ]
    assert sorted(manifest["case"]) == [
        "case_code", "case_id", "created_at", "name", "organization_id",
        "period_end", "period_start", "status", "updated_at",
    ]
    assert sorted(manifest["package_integrity"]) == [
        "algorithm", "canonical_form", "canonical_over", "manifest_sha256",
    ]
    assert sorted(manifest["scope"]) == ["organization", "production_batches"]
    assert sorted(manifest["provenance"]) == [
        "activities", "carbon_scope", "emission_factor_sets", "evidence_binaries_included",
    ]
    assert manifest["provenance"]["carbon_scope"] == "crop_season"
    for w in manifest["warnings"]:
        assert sorted(w) == ["code", "message", "related", "severity"]
        assert w["severity"] in ("info", "warning")


# --------------------------------------------------------------------------
# Snapshot semantics
# --------------------------------------------------------------------------

def test_download_returns_the_stored_snapshot_not_a_rebuild():
    service, repo, store = build_service()
    created = service.create(read_repository=repo, mrv_case_id=CASE)

    # Source data moves after the export was taken.
    repo._evidence.append({
        "id": "e2", "step_no": 2, "production_batch_id": None, "evidence_type": "doc",
        "file_name": "late.pdf", "mime_type": "application/pdf", "sha256": "b" * 64,
        "storage_bucket": "mrv-evidence", "storage_object_path": f"{ORG}/{CASE}/late.pdf",
        "uploaded_by": ACTOR, "uploaded_at": AT,
    })

    data, filename, media_type = service.download(
        read_repository=repo, export_id=created["export_id"]
    )
    snapshot = json.loads(data)
    assert [e["evidence_id"] for e in snapshot["evidence"]] == ["e1"]
    assert snapshot == created["manifest"]
    assert m.verify_checksum(snapshot)
    assert media_type == "application/json; charset=utf-8"
    assert filename.endswith(".json") and "/" not in filename

    # A new export does see the change.
    fresh = service.create(read_repository=repo, mrv_case_id=CASE)
    assert [e["evidence_id"] for e in fresh["manifest"]["evidence"]] == ["e1", "e2"]
    assert fresh["export_id"] != created["export_id"]
    assert fresh["file_sha256"] != created["file_sha256"]


def test_every_export_gets_its_own_id_distinct_from_the_case():
    service, repo, _ = build_service()
    a = service.create(read_repository=repo, mrv_case_id=CASE)
    b = service.create(read_repository=repo, mrv_case_id=CASE)
    assert a["export_id"] != b["export_id"]
    assert a["export_id"] != CASE and b["export_id"] != CASE


def test_the_stored_row_records_the_audit_metadata():
    result, _, _, store = generate()
    row = store.rows[result["export_id"]]
    assert row["format"] == "json"
    assert row["generated_by"] == ACTOR
    assert row["payload_sha256"] == result["manifest"]["package_integrity"]["manifest_sha256"]
    assert row["is_finalized"] is False
    assert row["warning_text"] == m.DISCLAIMER
    assert row["storage_object_path"] == f"{ORG}/{CASE}/{result['file_name']}"
    # The response names the file but never the bucket or the object path.
    assert "storage_object_path" not in result and "storage_bucket" not in result


def test_factor_set_is_null_when_no_carbon_backs_the_package():
    result, _, _, store = generate()
    assert store.rows[result["export_id"]]["factor_set_id"] is None


def test_factor_set_is_recorded_when_carbon_backs_the_package():
    read = FakeRead(factor_sets=copy.deepcopy(FACTOR_SET_ROW))
    result, _, _, store = generate(read=read, carbon=FakeCarbon(SUCCEEDED_CARBON))
    assert store.rows[result["export_id"]]["factor_set_id"] == FACTOR_SET


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------

@pytest.fixture
def client_for():
    def build(read, carbon=None, store=None):
        app = FastAPI()
        app.include_router(api.router)
        store = store or FakeExportStore()
        service = MrvExportService(store, carbon or FakeCarbon())
        app.dependency_overrides[api._read_repo] = lambda: read
        app.dependency_overrides[api._mrv_export_service] = lambda: service
        return TestClient(app), store
    return build


def test_authorized_export_returns_201_with_the_manifest(client_for):
    client, _ = client_for(FakeRead())
    response = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "json"})
    assert response.status_code == 201
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["status"] == "generated"
    assert body["manifest"]["case"]["case_id"] == CASE


def test_export_defaults_to_json_without_a_body(client_for):
    client, _ = client_for(FakeRead())
    assert client.post(f"/v1/mrv/cases/{CASE}/exports").status_code == 201


def test_cross_scope_case_is_404_not_403(client_for):
    client, _ = client_for(FakeRead(visible=False))
    response = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "json"})
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "not_found"


def test_unknown_case_is_404(client_for):
    client, _ = client_for(FakeRead(visible=False))
    assert client.post("/v1/mrv/cases/does-not-exist/exports").status_code == 404


def test_unauthenticated_export_is_401():
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "json"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


def test_unsupported_format_is_rejected_with_the_shared_error_envelope(client_for):
    client, _ = client_for(FakeRead())
    response = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "pdf"})
    assert response.status_code == 422
    assert "error" in response.json()["detail"]


def test_download_serves_json_as_an_attachment(client_for):
    read = FakeRead()
    client, store = client_for(read)
    created = client.post(f"/v1/mrv/cases/{CASE}/exports").json()

    response = client.get(f"/v1/mrv/exports/{created['export_id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert "attachment;" in response.headers["content-disposition"]
    assert ".json" in response.headers["content-disposition"]
    assert response.json() == created["manifest"]


def test_download_of_another_organizations_export_is_404(client_for):
    read = FakeRead()
    client, store = client_for(read)
    created = client.post(f"/v1/mrv/cases/{CASE}/exports").json()

    stranger = FakeRead(visible=False)
    other_client, _ = client_for(stranger, store=store)
    assert other_client.get(f"/v1/mrv/exports/{created['export_id']}/download").status_code == 404


def test_download_of_an_unknown_export_is_404(client_for):
    client, _ = client_for(FakeRead())
    assert client.get("/v1/mrv/exports/99999999-9999-9999-9999-999999999999/download").status_code == 404


def test_download_is_byte_identical_to_the_canonical_form(client_for):
    client, _ = client_for(FakeRead())
    created = client.post(f"/v1/mrv/cases/{CASE}/exports").json()
    response = client.get(f"/v1/mrv/exports/{created['export_id']}/download")
    assert response.content == m.canonical_bytes(created["manifest"])


# --------------------------------------------------------------------------
# Export authorization: a full-case package is a Management capability
#
# The role rule sits on top of RLS visibility, not instead of it: a farmer in
# the organization CAN read the case (that is the existing product contract and
# these tests do not change it), and still must not be able to package it.
# --------------------------------------------------------------------------

FARMER = FakeRead(roles=("farmer",))


def test_a_farmer_cannot_generate_a_full_case_package(client_for):
    client, _ = client_for(FakeRead(roles=("farmer",)))
    response = client.post(f"/v1/mrv/cases/{CASE}/exports", json={"format": "json"})
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "not_found"


def test_a_farmer_who_can_read_the_case_still_cannot_export_it():
    """The denial is the role, not visibility -- the read itself succeeds."""
    repo = FakeRead(roles=("farmer",))
    assert repo.mrv_case_row(CASE)["case_code"] == "DEMO-MRV-2026"
    service, _, _ = build_service(repo)
    with pytest.raises(Exception) as exc:
        service.create(read_repository=repo, mrv_case_id=CASE)
    assert exc.type.__name__ == "MrvExportAccessError"


def test_a_farmer_cannot_download_a_known_export_id(client_for):
    """Guessing an id must not route around the generation restriction."""
    manager_client, store = client_for(FakeRead())
    created = manager_client.post(f"/v1/mrv/cases/{CASE}/exports").json()

    farmer_client, _ = client_for(FakeRead(roles=("farmer",)), store=store)
    response = farmer_client.get(f"/v1/mrv/exports/{created['export_id']}/download")
    assert response.status_code == 404


def test_enterprise_and_regulator_are_not_silently_granted_export(client_for):
    for role in ("enterprise_viewer", "regulator"):
        client, _ = client_for(FakeRead(roles=(role,)))
        assert client.post(f"/v1/mrv/cases/{CASE}/exports").status_code == 404, role


def test_a_manager_of_a_different_organization_is_denied(client_for):
    """Readable via a data grant, managed elsewhere -> still not exportable."""
    stranger = FakeRead(roles=("cooperative_manager",),
                        membership_org="99999999-9999-9999-9999-999999999999")
    client, _ = client_for(stranger)
    assert client.post(f"/v1/mrv/cases/{CASE}/exports").status_code == 404


def test_a_cross_org_manager_cannot_download(client_for):
    manager_client, store = client_for(FakeRead())
    created = manager_client.post(f"/v1/mrv/cases/{CASE}/exports").json()

    stranger = FakeRead(roles=("cooperative_manager",),
                        membership_org="99999999-9999-9999-9999-999999999999")
    other_client, _ = client_for(stranger, store=store)
    assert other_client.get(f"/v1/mrv/exports/{created['export_id']}/download").status_code == 404


def test_a_lapsed_management_membership_is_not_management_authority(client_for):
    lapsed = FakeRead(membership_ended_at="2026-01-01T00:00:00Z")
    client, _ = client_for(lapsed)
    assert client.post(f"/v1/mrv/cases/{CASE}/exports").status_code == 404


def test_a_membership_ending_in_the_future_is_still_authority(client_for):
    active = FakeRead(membership_ended_at="2099-01-01T00:00:00Z")
    client, _ = client_for(active)
    assert client.post(f"/v1/mrv/cases/{CASE}/exports").status_code == 201


def test_a_manager_generates_and_downloads_their_own_org_export(client_for):
    client, _ = client_for(FakeRead())
    created = client.post(f"/v1/mrv/cases/{CASE}/exports").json()
    response = client.get(f"/v1/mrv/exports/{created['export_id']}/download")
    assert response.status_code == 200
    assert response.json() == created["manifest"]


def test_denial_is_indistinguishable_from_a_missing_case(client_for):
    """Same status and same code, so neither reveals the other."""
    farmer_client, _ = client_for(FakeRead(roles=("farmer",)))
    denied = farmer_client.post(f"/v1/mrv/cases/{CASE}/exports")
    missing = farmer_client.post("/v1/mrv/cases/00000000-0000-0000-0000-000000000000/exports")
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


def test_the_metadata_route_never_exposes_the_payload():
    """`GET /v1/mrv/exports/{id}` predates this feature and is governed by
    `mrv_exports_select` RLS, so an organization member -- including a farmer --
    can still see that an export exists. It must never carry the package itself.

    This is the property that matters: the generation/download restriction is
    about the packaged artifact, and metadata visibility is a separate,
    pre-existing product decision (see docs/MRV_EXPORT_PACKAGE.md).
    """
    from infrastructure.read_repo import SupabaseReadRepository

    row = {
        "id": "x", "mrv_case_id": CASE, "format": "json", "factor_set_id": None,
        "scope_description": "s", "data_as_of_at": AT, "contains_sample_data": False,
        "is_finalized": False, "warning_text": "w", "storage_bucket": "mrv-exports",
        "storage_object_path": "p", "file_sha256": "h", "generated_at": AT,
        "export_payload": {"secret": "must not appear"},
    }
    view = SupabaseReadRepository._export_view(SupabaseReadRepository, row)
    assert "export_payload" not in view
    assert "secret" not in json.dumps(view, default=str)
