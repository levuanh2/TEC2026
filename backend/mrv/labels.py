"""Vietnamese vocabulary for the MRV artifacts people read (PDF, XLSX business sheets).

The JSON snapshot keeps every canonical id and code; it is what machines and
auditors trace. The PDF and the XLSX business sheets show these labels instead
(Round 5.1). The XLSX "Dữ liệu kỹ thuật" sheet keeps the raw values beside
their labels, and its "Từ điển dữ liệu" sheet lists every code below, so
nothing an auditor needs is hidden.

A code with no label is shown as-is: an unknown value is never given an
invented name.
"""
from __future__ import annotations

import re
from typing import Any

STEP_STATUS = {
    "completed": "Hoàn thành", "in_progress": "Đang thực hiện", "not_started": "Chưa bắt đầu",
    "blocked": "Bị chặn", "skipped": "Bỏ qua", "failed": "Không đạt",
}
ACTIVITY_TYPE = {
    "seeding": "Gieo sạ", "fertilizer": "Bón phân", "irrigation": "Tưới nước",
    "pesticide": "Phun thuốc BVTV", "straw_management": "Xử lý rơm rạ", "harvest": "Thu hoạch",
    "fuel": "Nhiên liệu", "fuel_usage": "Nhiên liệu",
}
SOURCE = {"mobile_offline": "Di động (ngoại tuyến)", "mobile": "Di động", "web": "Web"}
SEVERITY = {"warning": "Cảnh báo", "info": "Thông tin"}
COMPLETENESS = {"water": "Nước", "fertilizer": "Phân bón", "cost": "Chi phí", "carbon": "Carbon"}
WARNING_CODE = {
    "carbon_unavailable": "Chưa có kết quả Carbon", "factor_provenance_unavailable": "Chưa rõ nguồn gốc hệ số",
    "factor_unverified": "Hệ số chưa đối chiếu nguồn", "evidence_none": "Chưa có bằng chứng",
    "evidence_checksum_missing": "Bằng chứng thiếu mã băm", "evidence_missing_for_step": "Bước thiếu bằng chứng",
    "mrv_step_incomplete": "Bước MRV chưa hoàn thành", "resource_metric_incomplete": "Chỉ số tài nguyên chưa đủ",
    "harvest_missing": "Chưa có thu hoạch", "scope_empty": "Hồ sơ chưa có phạm vi",
    "carbon_engine_warning": "Lưu ý của phép tính Carbon",
}
CARBON_STATUS = {"succeeded": "Đã tính", "unavailable": "Chưa có kết quả"}
CARBON_REASON = {"no_succeeded_calculation": "chưa có bản tính CO₂e thành công"}
CASE_STATUS = {
    "draft": "Nháp", "in_progress": "Đang thực hiện", "ready_for_verification": "Sẵn sàng thẩm định",
    "verified": "Đã thẩm định", "closed": "Đã đóng",
}
SEASON_STATUS = {
    "planned": "Dự kiến", "active": "Đang canh tác", "harvested": "Đã thu hoạch",
    "closed": "Đã đóng", "cancelled": "Đã huỷ",
}
ROLE = {
    "cooperative_manager": "Quản lý HTX", "farmer": "Nông hộ", "enterprise_viewer": "Doanh nghiệp (xem)",
    "regulator": "Cơ quan quản lý", "owner": "Chủ nông hộ", "editor": "Người ghi", "viewer": "Người xem",
}
ORGANIZATION_TYPE = {
    "cooperative": "Hợp tác xã", "enterprise": "Doanh nghiệp", "government": "Cơ quan nhà nước",
    "research": "Tổ chức nghiên cứu", "other": "Khác",
}
EVIDENCE_TYPE = {"photo": "Ảnh"}  # free text in the database; other values are shown as entered
CARBON_SCOPE = {"crop_season": "Vụ canh tác"}
SCENARIO = {"actual": "Theo dữ liệu đã ghi nhận", "awd": "Mô phỏng AWD", "continuous_flooding": "Mô phỏng ngập liên tục"}
CALCULATION_KIND = {"actual": "Kết quả vận hành", "scenario": "Kịch bản mô phỏng"}
CATEGORY = {
    "irrigation_ch4": "CH₄ ruộng lúa", "fertilizer_n2o": "N₂O phân đạm", "fuel": "Nhiên liệu",
    "straw": "Rơm rạ", "straw_burning_ch4": "Đốt rơm CH₄", "straw_burning_n2o": "Đốt rơm N₂O",
    "electricity": "Điện", "other": "Khác",
}
GAS = {"ch4": "CH₄", "n2o": "N₂O", "co2": "CO₂", "co2e": "CO₂e"}
FACTOR_SET_STATUS = {"published": "Đã công bố", "draft": "Nháp", "retired": "Ngừng dùng"}
VERIFICATION = {"VERIFIED": "Đã đối chiếu nguồn", "verified": "Đã đối chiếu nguồn",
                "UNVERIFIED": "Chưa đối chiếu nguồn", "unverified": "Chưa đối chiếu nguồn"}
PARAMETER_KIND = {
    "emission_factor": "Hệ số phát thải", "scaling_factor": "Hệ số hiệu chỉnh", "conversion_factor": "Hệ số quy đổi",
    "default_value": "Giá trị mặc định", "exponent": "Số mũ", "gwp": "Tiềm năng nóng lên toàn cầu (GWP)",
}
UNIT = {
    "dimensionless": "không thứ nguyên", "ha_day": "ha·ngày", "kgCH4": "kg CH₄", "gCH4": "g CH₄",
    "kgN": "kg N", "kgN2O": "kg N₂O", "gN2O": "g N₂O", "kgN2O-N": "kg N₂O-N", "kgCO2e": "kg CO₂e",
    "kg_dry_matter": "kg chất khô", "kg_dry_matter_burnt": "kg chất khô bị đốt",
}
# Choice fields recorded on activities (same options as the Flutter and web forms).
DETAIL_VALUE = {
    "seeding_method": {"sa_lan": "Sạ lan", "sa_hang": "Sạ hàng", "cay": "Cấy"},
    "method": {
        "awd": "Ngập - khô xen kẽ (AWD)", "continuous_flooding": "Ngập liên tục", "alternate": "Xen kẽ kiểu khác",
        "incorporated": "Vùi vào đất", "removed": "Mang khỏi ruộng", "burned": "Đốt tại ruộng",
        "composted": "Ủ compost", "other": "Cách khác",
    },
    "fuel_type": {"diesel": "Dầu diesel", "gasoline": "Xăng", "lpg": "Gas (LPG)", "other": "Loại khác"},
}

SOURCE_TABLE = {
    "activities": "Nhật ký hoạt động", "seeding_events": "Gieo sạ", "fertilizer_applications": "Bón phân",
    "irrigation_events": "Tưới nước", "pesticide_applications": "Phun thuốc BVTV", "fuel_usages": "Nhiên liệu",
    "straw_management_events": "Xử lý rơm rạ", "harvest_events": "Thu hoạch",
}
HASH_SCOPE = {"manifest-without-package_integrity": "Toàn bộ gói dữ liệu, trừ khối tính toàn vẹn"}
CANONICAL_FORM = {
    "json;sorted_keys;separators=(',',':');utf-8": "JSON, khoá sắp theo thứ tự, không khoảng trắng, mã hoá UTF-8",
}

# (group title, map) — the data dictionary lists every one of these.
DICTIONARY: list[tuple[str, dict[str, str]]] = [
    ("Trạng thái hồ sơ MRV", CASE_STATUS), ("Trạng thái bước MRV", STEP_STATUS),
    ("Trạng thái vụ canh tác", SEASON_STATUS), ("Vai trò", ROLE), ("Loại tổ chức", ORGANIZATION_TYPE),
    ("Loại bằng chứng", EVIDENCE_TYPE), ("Phạm vi tính Carbon", CARBON_SCOPE),
    ("Loại hoạt động", ACTIVITY_TYPE), ("Nguồn ghi nhận", SOURCE),
    ("Cách gieo", DETAIL_VALUE["seeding_method"]), ("Cách tưới / xử lý rơm", DETAIL_VALUE["method"]),
    ("Loại nhiên liệu", DETAIL_VALUE["fuel_type"]),
    ("Loại kết quả Carbon", CALCULATION_KIND), ("Kịch bản", SCENARIO), ("Trạng thái Carbon", CARBON_STATUS),
    ("Lý do chưa có Carbon", CARBON_REASON), ("Hạng mục phát thải", CATEGORY), ("Khí", GAS),
    ("Đơn vị", UNIT), ("Loại tham số", PARAMETER_KIND), ("Tình trạng đối chiếu", VERIFICATION),
    ("Trạng thái bộ hệ số", FACTOR_SET_STATUS), ("Mức độ cảnh báo", SEVERITY),
    ("Mã cảnh báo", WARNING_CODE), ("Nhóm dữ liệu", COMPLETENESS), ("Bảng nguồn", SOURCE_TABLE),
    ("Phạm vi băm", HASH_SCOPE), ("Cách chuẩn hoá khi băm", CANONICAL_FORM),
]

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_QUOTED_UUID = re.compile(r"(['\"]?)(" + UUID_RE.pattern + r")\1")


def label(code: Any, labels: dict[str, str]) -> str | None:
    """The Vietnamese label of `code`; the code itself when there is none; None for empty."""
    if code is None or code == "":
        return None
    return labels.get(str(code)) or str(code)


def short(value: Any, n: int = 8) -> str | None:
    return str(value)[:n] if value else None


def season_codes(manifest: dict[str, Any]) -> dict[str, str]:
    """crop_season_id -> season code, from the snapshot's own scope."""
    out: dict[str, str] = {}
    for b in (manifest.get("scope") or {}).get("production_batches") or []:
        season = b.get("crop_season") or {}
        if season.get("crop_season_id") and season.get("season_code"):
            out[str(season["crop_season_id"])] = str(season["season_code"])
    return out


def season_name(manifest: dict[str, Any], season_id: Any, codes: dict[str, str] | None = None) -> str | None:
    """A season as people know it: its code; a short id only when the scope does not name it."""
    if not season_id:
        return None
    code = (codes if codes is not None else season_codes(manifest)).get(str(season_id))
    return code or f"mã {short(season_id)}"


def humanize(manifest: dict[str, Any], text: Any) -> str | None:
    """A snapshot message as a person reads it: seasons by code, other ids
    shortened, status and data-group codes as labels. The JSON keeps it verbatim."""
    if text is None:
        return None
    codes = season_codes(manifest)
    out = _QUOTED_UUID.sub(
        lambda m: codes.get(m.group(2)) or f"mã {short(m.group(2))}", str(text))
    for code, name in {**STEP_STATUS, **COMPLETENESS}.items():
        out = re.sub(rf"(?<![A-Za-z_]){re.escape(code)}(?![A-Za-z_])",
                     name.lower() if code in COMPLETENESS else name, out)
    return out


def related(manifest: dict[str, Any], value: Any) -> str | None:
    """A warning's `related` block in words."""
    if not value:
        return None
    if not isinstance(value, dict):
        return humanize(manifest, value)
    parts = []
    for key, v in sorted(value.items()):
        if key == "crop_season_id":
            parts.append(f"Vụ {season_name(manifest, v)}")
        elif key == "step_no":
            parts.append(f"Bước {v}")
        elif key == "missing" and isinstance(v, (list, tuple)):
            parts.append("Thiếu: " + ", ".join(COMPLETENESS.get(str(x), str(x)).lower() for x in v))
        elif key == "factor_set_id":
            parts.append(f"Bộ hệ số mã {short(v)}")
        else:
            parts.append(humanize(manifest, v if not isinstance(v, (list, tuple)) else ", ".join(map(str, v))) or "")
    return "; ".join(p for p in parts if p) or None
