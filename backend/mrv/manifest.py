"""The MRV JSON evidence package: contract, canonical form, checksum.

WHAT THIS IS, AND IS NOT
    A snapshot of what the system actually holds for one MRV case at one moment:
    the case, its scope, its steps, its evidence references, the crop-season
    activities, the resource metrics and carbon result as computed by the
    existing services, and the provenance behind them.

    It is NOT a certification, a verification, an audit opinion, or a compliance
    statement, and nothing in it may be phrased as one. Where data is missing the
    package says so through `warnings` and leaves the value `null`; it never
    substitutes a zero, and it never fills a gap with an invented citation.

DETERMINISM
    Two exports built from the same logical snapshot must serialize identically
    and hash identically. That rules out dict insertion order, `set` iteration,
    float repr drift and locale-dependent dates, so: keys are sorted at
    serialization time, separators are fixed, numbers cross the boundary as
    strings where the source is a Postgres numeric, and every timestamp is
    normalized to UTC `...Z`. Dates stay dates.

CHECKSUM
    `package_integrity.manifest_sha256` is the SHA-256 of the canonical bytes of
    the manifest *without* the `package_integrity` key. The field cannot cover
    itself, so the documented process is: build the manifest, drop
    `package_integrity`, canonicalize, hash, then attach. A verifier repeats
    exactly that. `canonical_over` is recorded in the manifest so the process is
    discoverable from the artifact itself rather than only from this docstring.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

# Bump ONLY together with a documented change to the shape below. Consumers key
# their parsing off this, so a silent change is a broken contract.
MANIFEST_SCHEMA_VERSION = "1.0"

_INTEGRITY_KEY = "package_integrity"
_CANONICAL_OVER = "manifest-without-package_integrity"

# Neutral, repeated verbatim into every package. Deliberately not configurable:
# the point is that no deployment can quietly drop it.
DISCLAIMER = (
    "Gói dữ liệu MRV do hệ thống tạo từ dữ liệu hiện có. Đây KHÔNG phải chứng "
    "nhận, thẩm định hay xác nhận của cơ quan có thẩm quyền, và không khẳng "
    "định tuân thủ bất kỳ tiêu chuẩn MRV nào. Nội dung có thể chứa cảnh báo về "
    "bằng chứng hoặc hệ số phát thải chưa đầy đủ."
)


# --------------------------------------------------------------------------
# Warning vocabulary. Machine-readable codes; severity is `info` or `warning`
# only -- an absent optional value is not an error and must not read like one.
# --------------------------------------------------------------------------

class WarningCode:
    CARBON_UNAVAILABLE = "carbon_unavailable"
    FACTOR_PROVENANCE_UNAVAILABLE = "factor_provenance_unavailable"
    FACTOR_UNVERIFIED = "factor_unverified"
    EVIDENCE_NONE = "evidence_none"
    EVIDENCE_CHECKSUM_MISSING = "evidence_checksum_missing"
    EVIDENCE_MISSING_FOR_STEP = "evidence_missing_for_step"
    STEP_INCOMPLETE = "mrv_step_incomplete"
    RESOURCE_METRIC_INCOMPLETE = "resource_metric_incomplete"
    HARVEST_MISSING = "harvest_missing"
    SCOPE_EMPTY = "scope_empty"


def _warning(code: str, message: str, severity: str = "warning", **entity: Any) -> dict[str, Any]:
    related = {k: v for k, v in entity.items() if v is not None}
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "related": related or None,
    }


# --------------------------------------------------------------------------
# Value normalization
# --------------------------------------------------------------------------

def iso_utc(value: Any) -> str | None:
    """Timestamp -> `2026-09-13T08:00:00Z`. Naive input is rejected, not guessed.

    A naive timestamp reaching here means some layer dropped the timezone, and
    silently stamping UTC on it would put a wrong instant into an audit artifact.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        value = parsed
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"refusing to export a naive timestamp: {value!r}")
        text = value.astimezone(timezone.utc).isoformat(timespec="seconds")
        return text.replace("+00:00", "Z")
    raise TypeError(f"not a timestamp: {value!r}")


def iso_date(value: Any) -> str | None:
    """Date stays a date. `period_start` is a calendar day, not an instant."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def number(value: Any) -> str | None:
    """Postgres numerics cross the boundary as strings.

    `1.10` and `1.1` are the same float but different JSON text, and float repr
    varies with the driver. Keeping the source's own decimal text makes the
    checksum stable and stops a quantity silently changing precision in an audit
    artifact. Consumers parse it as a decimal.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("bool is not a quantity")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(repr(value)), "f")
    text = str(value).strip()
    return text or None


def _as_uuid_str(value: Any) -> str | None:
    return str(value) if value is not None else None


# --------------------------------------------------------------------------
# Canonical serialization + checksum
# --------------------------------------------------------------------------

def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """The one serialization the checksum is defined over.

    sorted keys, no insignificant whitespace, UTF-8, non-ASCII kept as itself
    (the data is Vietnamese; escaping it would be lossless but needlessly
    unreadable in an artifact a human may have to inspect).
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def manifest_checksum(manifest: dict[str, Any]) -> str:
    """SHA-256 over the manifest with `package_integrity` removed."""
    without = {k: v for k, v in manifest.items() if k != _INTEGRITY_KEY}
    return hashlib.sha256(canonical_bytes(without)).hexdigest()


def verify_checksum(manifest: dict[str, Any]) -> bool:
    recorded = (manifest.get(_INTEGRITY_KEY) or {}).get("manifest_sha256")
    return bool(recorded) and recorded == manifest_checksum(manifest)


# --------------------------------------------------------------------------
# Filename
# --------------------------------------------------------------------------

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text: str) -> str:
    """ASCII, filesystem- and header-safe, never empty."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = folded.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub("-", folded).strip("-._")
    return cleaned[:60] or "case"


def export_filename(case_code: str, generated_at: datetime, export_id: str) -> str:
    day = iso_date(generated_at)
    return f"agricarbon-mrv-{_slug(case_code)}-{day}-{str(export_id)[:8]}.json"


# --------------------------------------------------------------------------
# Inputs. Every field is data the caller already fetched through an existing
# repository or service -- this module runs no query and recomputes no formula.
# --------------------------------------------------------------------------

@dataclass
class ManifestInputs:
    export_id: str
    generated_at: datetime
    generated_by: dict[str, Any]
    case: dict[str, Any]
    organization: dict[str, Any] | None = None
    scope_entries: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    activities: list[dict[str, Any]] = field(default_factory=list)
    metrics_by_season: dict[str, dict[str, Any]] = field(default_factory=dict)
    carbon_by_season: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    factor_sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    factors_by_set: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    include_deleted_activities: bool = False


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------

def _case_section(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": _as_uuid_str(case.get("case_id") or case.get("id")),
        "case_code": case.get("case_code"),
        "name": case.get("name"),
        "status": case.get("status"),
        "period_start": iso_date(case.get("period_start")),
        "period_end": iso_date(case.get("period_end")),
        "organization_id": _as_uuid_str(case.get("organization_id")),
        "created_at": iso_utc(case.get("created_at")),
        "updated_at": iso_utc(case.get("updated_at")),
    }


def _scope_section(
    organization: dict[str, Any] | None, entries: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    if not entries:
        warnings.append(
            _warning(
                WarningCode.SCOPE_EMPTY,
                "Hồ sơ chưa gắn lô sản xuất nào, nên gói dữ liệu không có phạm vi canh tác.",
            )
        )
    org = None
    if organization:
        org = {
            "organization_id": _as_uuid_str(organization.get("id")),
            "organization_code": organization.get("organization_code"),
            "name": organization.get("name"),
            "organization_type": organization.get("organization_type"),
        }
    items = [
        {
            "production_batch_id": _as_uuid_str(e.get("production_batch_id")),
            "batch_code": e.get("batch_code"),
            "farm": {
                "farm_id": _as_uuid_str(e.get("farm_id")),
                "farm_code": e.get("farm_code"),
                "name": e.get("farm_name"),
            },
            "plot": {
                "plot_id": _as_uuid_str(e.get("plot_id")),
                "plot_code": e.get("plot_code"),
                "area_ha": number(e.get("plot_area_ha")),
            },
            "crop_season": {
                "crop_season_id": _as_uuid_str(e.get("crop_season_id")),
                "season_code": e.get("season_code"),
                "status": e.get("season_status"),
                "started_on": iso_date(e.get("started_on")),
                "closed_on": iso_date(e.get("closed_on")),
            },
        }
        for e in entries
    ]
    items.sort(key=lambda i: (i["production_batch_id"] or ""))
    return {"organization": org, "production_batches": items}, warnings


def _steps_section(
    steps: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Statuses are copied, never reinterpreted.

    `not_started` is not a failure and `blocked` is not `failed`; converting one
    into the other would misrepresent the case to whoever reads the package.
    """
    counts: dict[int, int] = {}
    for item in evidence:
        step_no = item.get("step_no")
        if step_no is not None:
            counts[int(step_no)] = counts.get(int(step_no), 0) + 1

    out = [
        {
            "step_no": int(s["step_no"]),
            "name": s.get("name"),
            "status": s.get("status"),
            "started_at": iso_utc(s.get("started_at")),
            "completed_at": iso_utc(s.get("completed_at")),
            "notes": s.get("notes"),
            "evidence_count": counts.get(int(s["step_no"]), 0),
        }
        for s in steps
    ]
    out.sort(key=lambda s: s["step_no"])

    warnings = [
        _warning(
            WarningCode.STEP_INCOMPLETE,
            f"Bước {s['step_no']} ({s['name']}) chưa hoàn thành — trạng thái hiện tại: {s['status']}.",
            severity="info",
            step_no=s["step_no"],
        )
        for s in out
        if s["status"] != "completed"
    ]
    return out, warnings


def _evidence_section(
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """References only. No bytes are embedded and none are claimed to be.

    A missing `sha256` is reported as a provenance gap rather than computed here:
    hashing would mean fetching the object, and an export must not silently turn
    into a bulk download of remote storage.
    """
    items = [
        {
            "evidence_id": _as_uuid_str(e.get("id")),
            "step_no": int(e["step_no"]) if e.get("step_no") is not None else None,
            "production_batch_id": _as_uuid_str(e.get("production_batch_id")),
            "evidence_type": e.get("evidence_type"),
            "file_name": e.get("file_name"),
            "mime_type": e.get("mime_type"),
            "uploaded_at": iso_utc(e.get("uploaded_at")),
            "uploaded_by": _as_uuid_str(e.get("uploaded_by")),
            "storage": {
                "bucket": e.get("storage_bucket"),
                "object_path": e.get("storage_object_path"),
                "included_in_package": False,
            },
            "checksum": (
                {"algorithm": "sha256", "value": e["sha256"]} if e.get("sha256") else None
            ),
        }
        for e in evidence
    ]
    items.sort(key=lambda i: (i["step_no"] or 0, i["evidence_id"] or ""))

    warnings: list[dict[str, Any]] = []
    if not items:
        warnings.append(
            _warning(
                WarningCode.EVIDENCE_NONE,
                "Hồ sơ chưa có tệp bằng chứng nào.",
            )
        )
    unhashed = [i for i in items if i["checksum"] is None]
    if unhashed:
        warnings.append(
            _warning(
                WarningCode.EVIDENCE_CHECKSUM_MISSING,
                f"{len(unhashed)} tệp bằng chứng chưa có mã băm SHA-256, "
                "nên không thể đối chiếu tính toàn vẹn của tệp từ gói dữ liệu này.",
                evidence_ids=[i["evidence_id"] for i in unhashed],
            )
        )
    return items, warnings


def _activities_section(
    activities: list[dict[str, Any]], *, include_deleted: bool
) -> list[dict[str, Any]]:
    """Soft-deleted activities are excluded by default.

    A deleted activity is one the farmer retracted; carrying it into an evidence
    package would misrepresent what was recorded. The flag exists because an
    audit may later need the retractions too, and the manifest states which of
    the two it is (`provenance.activities.includes_deleted`) rather than leaving
    a reader to guess.
    """
    rows = [
        a
        for a in activities
        if include_deleted or not a.get("deleted_at")
    ]
    out = [
        {
            "activity_id": _as_uuid_str(a.get("id")),
            "crop_season_id": _as_uuid_str(a.get("crop_season_id")),
            "production_batch_id": _as_uuid_str(a.get("production_batch_id")),
            "activity_type": a.get("activity_type"),
            "occurred_at": iso_utc(a.get("occurred_at")),
            "recorded_at": iso_utc(a.get("recorded_at")),
            "source": a.get("source"),
            "recorded_by": _as_uuid_str(a.get("recorded_by")),
            "note": a.get("note"),
            "deleted_at": iso_utc(a.get("deleted_at")),
            "provenance": {
                "device_id": _as_uuid_str(a.get("device_id")),
                "client_event_id": _as_uuid_str(a.get("client_event_id")),
            },
            "detail": {
                key: number(value) if _is_quantity(key, value) else value
                for key, value in sorted((a.get("detail") or {}).items())
            },
        }
        for a in rows
    ]
    out.sort(key=lambda a: (a["occurred_at"] or "", a["activity_id"] or ""))
    return out


_NON_QUANTITY_KEYS = {
    "activity_id", "method", "variety_name", "seeding_method", "fertilizer_name",
    "fertilizer_type", "product_name", "active_ingredient", "unit", "returned_to_field",
    "created_at", "updated_at",
}


def _is_quantity(key: str, value: Any) -> bool:
    if key in _NON_QUANTITY_KEYS or value is None or isinstance(value, (bool, str)):
        return False
    return isinstance(value, (int, float, Decimal))


def _harvest_section(
    activities: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One denominator, from `harvest_events` -- the same rows the resource and
    carbon layers read. No second yield source is introduced here.
    """
    events = [
        a for a in activities
        if a.get("activity_type") == "harvest" and not a.get("deleted_at")
    ]
    items = []
    for a in events:
        detail = a.get("detail") or {}
        items.append({
            "activity_id": _as_uuid_str(a.get("id")),
            "crop_season_id": _as_uuid_str(a.get("crop_season_id")),
            "occurred_at": iso_utc(a.get("occurred_at")),
            "yield_kg": number(detail.get("yield_kg")),
            "harvested_area_ha": number(detail.get("harvested_area_ha")),
            "moisture_percent": number(detail.get("moisture_percent")),
        })
    items.sort(key=lambda i: (i["occurred_at"] or "", i["activity_id"] or ""))

    warnings: list[dict[str, Any]] = []
    if not items:
        warnings.append(
            _warning(
                WarningCode.HARVEST_MISSING,
                "Chưa có bản ghi thu hoạch, nên các chỉ số tính trên mỗi kg không có mẫu số.",
            )
        )
    return {"events": items, "event_count": len(items)}, warnings


def _resource_section(
    metrics_by_season: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Values come from the resource-metric service as-is.

    `null` is exported as `null`. A missing metric is not zero, and rounding or
    defaulting one here would be inventing a measurement.
    """
    per_season = {}
    warnings: list[dict[str, Any]] = []
    for season_id, m in sorted(metrics_by_season.items()):
        completeness = m.get("data_completeness") or {}
        per_season[season_id] = {
            "yield_kg": number(m.get("yield_kg")),
            "water_m3": number(m.get("water_m3")),
            "fertilizer_kg": number(m.get("fertilizer_kg")),
            "water_per_kg": number(m.get("water_per_kg")),
            "fertilizer_per_kg": number(m.get("fertilizer_per_kg")),
            "cost_per_kg": number(m.get("cost_per_kg")),
            "co2e_per_kg": number(m.get("co2e_per_kg")),
            "data_completeness": {k: bool(v) for k, v in sorted(completeness.items())},
        }
        missing = sorted(k for k, v in completeness.items() if not v)
        if missing:
            warnings.append(
                _warning(
                    WarningCode.RESOURCE_METRIC_INCOMPLETE,
                    "Chỉ số tài nguyên chưa đầy đủ cho vụ này: " + ", ".join(missing) + ".",
                    severity="info",
                    crop_season_id=season_id,
                    missing=missing,
                )
            )
    return {"per_crop_season": per_season}, warnings


def _carbon_section(
    carbon_by_season: dict[str, dict[str, Any] | None],
    factor_sets: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """The persisted calculation, verbatim. No CO2e is computed here.

    Round 5.1: each result also names what KIND of result it is (the actual,
    `as_recorded` calculation — the export never reads a scenario) and the
    factor-set VERSION it was computed with, read from the factor-set row the
    provenance section reads too. A set that cannot be read gives `null`, never
    a guessed version.

    When no succeeded calculation exists the section is `status: unavailable`
    with a warning, and the package is still generated -- an MRV case is more
    than its carbon number, and refusing to export the evidence because the
    factors have not been imported would hide the very gap that matters.
    """
    per_season: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    factor_set_ids: list[str] = []

    for season_id, row in sorted(carbon_by_season.items()):
        if not row:
            per_season[season_id] = {
                "status": "unavailable",
                "reason": "no_succeeded_calculation",
                "calculation_id": None,
                "calculated_at": None,
                "total_co2e_kg": None,
                "co2e_per_kg": None,
                "yield_kg": None,
                "scenario": None,
                "engine_version": None,
                "methodology_tier": None,
                "factor_set_id": None,
                "calculation_kind": None,
                "ef_config_version": None,
                "breakdown": [],
            }
            warnings.append(
                _warning(
                    WarningCode.CARBON_UNAVAILABLE,
                    "Chưa có bản tính CO2e thành công cho vụ này, nên gói dữ liệu "
                    "không kèm kết quả phát thải.",
                    crop_season_id=season_id,
                )
            )
            continue

        factor_set_id = _as_uuid_str(row.get("factor_set_id"))
        if factor_set_id:
            factor_set_ids.append(factor_set_id)
        breakdown = [
            {
                "category": b.get("category"),
                "gas": b.get("gas"),
                "activity_value": number(b.get("activity_value")),
                "activity_unit": b.get("activity_unit"),
                "factor_value_used": number(b.get("factor_value_used")),
                "gas_kg": number(b.get("gas_kg")),
                "co2e_kg": number(b.get("co2e_kg")),
                "emission_factor_id": _as_uuid_str(b.get("emission_factor_id")),
                "activity_id": _as_uuid_str(b.get("activity_id")),
                "formula_expression": b.get("formula_expression"),
            }
            for b in (row.get("breakdown") or [])
        ]
        breakdown.sort(key=lambda b: (b["category"] or "", b["gas"] or "", b["emission_factor_id"] or ""))
        per_season[season_id] = {
            "status": row.get("status"),
            "reason": None,
            "calculation_id": _as_uuid_str(row.get("id")),
            "calculated_at": iso_utc(row.get("calculated_at")),
            "total_co2e_kg": number(row.get("total_co2e_kg")),
            "co2e_per_kg": number(row.get("co2e_per_kg")),
            "yield_kg": number(row.get("yield_kg")),
            "scenario": row.get("scenario"),
            "engine_version": row.get("engine_version"),
            "methodology_tier": row.get("methodology_tier"),
            "factor_set_id": factor_set_id,
            "calculation_kind": "actual" if row.get("scenario") == "actual" else "scenario",
            "ef_config_version": ((factor_sets or {}).get(factor_set_id) or {}).get("version_code") if factor_set_id else None,
            "breakdown": breakdown,
        }
        for w in (row.get("warnings") or []):
            warnings.append(
                _warning(
                    "carbon_engine_warning",
                    w if isinstance(w, str) else json.dumps(w, sort_keys=True, ensure_ascii=False),
                    severity="info",
                    crop_season_id=season_id,
                )
            )

    return {"per_crop_season": per_season}, warnings, factor_set_ids


def _provenance_section(
    inputs: ManifestInputs, factor_set_ids: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Only what the database actually records. No citation is invented."""
    warnings: list[dict[str, Any]] = []
    sets = []
    for set_id in sorted(set(factor_set_ids)):
        row = inputs.factor_sets.get(set_id)
        if not row:
            warnings.append(
                _warning(
                    WarningCode.FACTOR_PROVENANCE_UNAVAILABLE,
                    "Không đọc được thông tin nguồn của bộ hệ số đã dùng.",
                    factor_set_id=set_id,
                )
            )
            continue
        factors = []
        for f in sorted(inputs.factors_by_set.get(set_id, []), key=lambda x: str(x.get("factor_code"))):
            factors.append({
                "factor_code": f.get("factor_code"),
                "category": f.get("category"),
                "gas": f.get("gas"),
                "factor_value": number(f.get("factor_value")),
                "activity_unit": f.get("activity_unit"),
                "result_unit": f.get("result_unit"),
                "source_reference": f.get("source_reference"),
                "verification_status": f.get("verification_status"),
                "parameter_kind": f.get("parameter_kind"),
                "uncertainty_range": f.get("uncertainty_range"),
            })
        # The database enum is upper-case (VERIFIED / PENDING_VERIFICATION / ...); compare
        # case-insensitively so a verified factor is never reported as unverified.
        unverified = [f["factor_code"] for f in factors
                      if f["verification_status"] is not None and str(f["verification_status"]).upper() != "VERIFIED"]
        if unverified:
            warnings.append(
                _warning(
                    WarningCode.FACTOR_UNVERIFIED,
                    f"{len(unverified)} hệ số trong bộ '{row.get('version_code')}' chưa "
                    "được đối chiếu nguồn gốc.",
                    factor_set_id=set_id,
                    factor_codes=unverified,
                )
            )
        sets.append({
            "factor_set_id": set_id,
            "version_code": row.get("version_code"),
            "name": row.get("name"),
            "methodology_name": row.get("methodology_name"),
            "methodology_version": row.get("methodology_version"),
            "source_name": row.get("source_name"),
            "source_url": row.get("source_url"),
            "status": row.get("status"),
            "valid_from": iso_date(row.get("valid_from")),
            "valid_to": iso_date(row.get("valid_to")),
            "published_at": iso_utc(row.get("published_at")),
            "factors": factors,
        })

    if not sets:
        warnings.append(
            _warning(
                WarningCode.FACTOR_PROVENANCE_UNAVAILABLE,
                "Gói dữ liệu không kèm nguồn gốc hệ số phát thải vì chưa có bản tính "
                "CO2e nào liên kết tới một bộ hệ số.",
            )
        )

    provenance = {
        "emission_factor_sets": sets,
        "activities": {
            "source_tables": ["activities", "seeding_events", "fertilizer_applications",
                              "irrigation_events", "pesticide_applications", "fuel_usages",
                              "straw_management_events", "harvest_events"],
            "includes_deleted": bool(inputs.include_deleted_activities),
        },
        "carbon_scope": "crop_season",
        "evidence_binaries_included": False,
    }
    return provenance, warnings


def _readiness_section(
    steps: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    carbon: dict[str, Any],
) -> dict[str, Any]:
    """Counts of real state. No invented score -- the product has none."""
    completed = [s for s in steps if s["status"] == "completed"]
    steps_without_evidence = [s["step_no"] for s in steps if s["evidence_count"] == 0]
    per_season = carbon.get("per_crop_season") or {}
    carbon_available = bool(per_season) and all(
        v.get("status") == "succeeded" for v in per_season.values()
    )
    return {
        "total_steps": len(steps),
        "completed_steps": len(completed),
        "remaining_steps": len(steps) - len(completed),
        "evidence_count": len(evidence),
        "steps_without_evidence": sorted(steps_without_evidence),
        "carbon_available": carbon_available,
    }


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_manifest(inputs: ManifestInputs) -> dict[str, Any]:
    """Assemble, then checksum. The returned dict is the stored artifact."""
    warnings: list[dict[str, Any]] = []

    case = _case_section(inputs.case)
    scope, w = _scope_section(inputs.organization, inputs.scope_entries)
    warnings += w
    steps, w = _steps_section(inputs.steps, inputs.evidence)
    warnings += w
    evidence, w = _evidence_section(inputs.evidence)
    warnings += w
    activities = _activities_section(
        inputs.activities, include_deleted=inputs.include_deleted_activities
    )
    harvest, w = _harvest_section(inputs.activities)
    warnings += w
    resource, w = _resource_section(inputs.metrics_by_season)
    warnings += w
    carbon, w, factor_set_ids = _carbon_section(inputs.carbon_by_season, inputs.factor_sets)
    warnings += w
    provenance, w = _provenance_section(inputs, factor_set_ids)
    warnings += w

    # Stable order so the same logical findings serialize identically.
    warnings.sort(key=lambda x: (x["code"], canonical_bytes(x["related"] or {}).decode("utf-8")))

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "export_id": str(inputs.export_id),
        "generated_at": iso_utc(inputs.generated_at),
        "generated_by": inputs.generated_by,
        "disclaimer": DISCLAIMER,
        "case": case,
        "scope": scope,
        "readiness": _readiness_section(steps, evidence, carbon),
        "steps": steps,
        "evidence": evidence,
        "activities": activities,
        "harvest": harvest,
        "resource_metrics": resource,
        "carbon": carbon,
        "provenance": provenance,
        "warnings": warnings,
    }
    manifest[_INTEGRITY_KEY] = {
        "algorithm": "sha256",
        "canonical_over": _CANONICAL_OVER,
        "canonical_form": "json;sorted_keys;separators=(',',':');utf-8",
        "manifest_sha256": manifest_checksum(manifest),
    }
    return manifest


def new_export_id() -> str:
    """Its own identity, never the case id -- a case has many exports."""
    return str(uuid.uuid4())
