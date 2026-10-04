"""Render a canonical MRV manifest into an XLSX workbook.

THE ONE RULE
    The only input is a stored `export_payload`. This module performs no query,
    calls no service, recomputes no carbon or resource figure, and reaches for
    no newer data. Every business value in the workbook is copied from the
    snapshot it was given. A spreadsheet that disagreed with its own manifest
    would be worse than no spreadsheet.

    Presentation is allowed to differ -- sheet names, column order, widths,
    Vietnamese labels, and the rendering timestamp on the Manifest sheet. Those
    are the only things this module originates.

DETERMINISM
    Same manifest in, same cell values and same row order out. Every list is
    sorted on a stable key here rather than trusted to arrive ordered, so the
    workbook cannot drift with a change in JSON ordering.

    The .xlsx bytes themselves are NOT claimed to be reproducible: a zip carries
    timestamps and openpyxl writes its own metadata. What is deterministic is
    the content, which is what the tests assert and what an auditor reads.

NULL
    A null in the manifest becomes an EMPTY CELL. Never 0, never "N/A", never
    "null". A missing measurement and a measurement of zero are different facts
    and an evidence package must not blur them. Where a human explanation is
    useful it goes in its own status column, leaving the value column blank.

NUMBERS
    The manifest carries quantities as decimal strings so its checksum stays
    stable. Excel is a spreadsheet, so they are written back as real numbers --
    parsed through `Decimal` so the precision in the string is the precision in
    the cell, with no float round trip.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import labels as L

# Restrained on purpose: one header style, one note style, thin borders. An
# evidence package is read, filtered and printed, not admired.
_HEADER_FILL = PatternFill("solid", fgColor="E8ECEF")
_HEADER_FONT = Font(bold=True, size=10)
_TITLE_FONT = Font(bold=True, size=11)
_MUTED_FONT = Font(italic=True, size=9, color="606060")
_THIN = Side(style="thin", color="BFC6CC")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(vertical="top", wrap_text=True)
_TOP = Alignment(vertical="top")

_DATETIME_FORMAT = "yyyy-mm-dd hh:mm:ss"
_DATE_FORMAT = "yyyy-mm-dd"
_MAX_WIDTH = 60
_MIN_WIDTH = 10

# One cell cannot hold more than this many characters in xlsx.
_CELL_LIMIT = 32_000

EMPTY_NOTE = "Không có dữ liệu trong gói này."


# --------------------------------------------------------------------------
# Value coercion
# --------------------------------------------------------------------------

def _num(value: Any) -> Any:
    """Manifest decimal string -> a real number cell, precision preserved.

    Returns None for None so the cell stays empty; returns the original text if
    it is not actually numeric, rather than silently dropping a value.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    # int when it is exactly an integer, so Excel does not show 5200.000 as text.
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def _dt(value: Any) -> Any:
    """`2026-09-13T08:00:00Z` -> a naive-UTC datetime cell.

    Excel has no timezone concept, so the tz-aware instant is converted to UTC
    and the offset dropped; every timestamp column is labelled UTC in its header
    so the meaning is not lost. Converting to local time instead would silently
    shift dates across the ICT boundary, which this project has already been
    bitten by once.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _d(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return value


def _text(value: Any) -> Any:
    """Anything left over. Nested structures are compacted, never dumped raw."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "có" if value else "không"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or None
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in sorted(value.items())) or None
    text = str(value)
    return text[: _CELL_LIMIT - 3] + "..." if len(text) > _CELL_LIMIT else text


# --------------------------------------------------------------------------
# Sheet helpers
# --------------------------------------------------------------------------

class _Sheet:
    def __init__(self, workbook: Workbook, title: str):
        self.ws = workbook.create_sheet(title[:31])
        self._widths: dict[int, int] = {}
        self._row = 1

    def title_row(self, text: str) -> None:
        cell = self.ws.cell(row=self._row, column=1, value=text)
        cell.font = _TITLE_FONT
        self._track(1, text)
        self._row += 1

    def note_row(self, text: str) -> None:
        cell = self.ws.cell(row=self._row, column=1, value=text)
        cell.font = _MUTED_FONT
        cell.alignment = _WRAP
        self._track(1, text)
        self._row += 1

    def blank_row(self) -> None:
        self._row += 1

    def header(self, columns: Iterable[str]) -> None:
        self._header_row = self._row
        for index, name in enumerate(columns, start=1):
            cell = self.ws.cell(row=self._row, column=index, value=name)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.border = _BORDER
            cell.alignment = _WRAP
            self._track(index, name)
        self._row += 1

    def row(self, values: Iterable[Any], formats: Iterable[str | None] | None = None) -> None:
        formats = list(formats or [])
        for index, value in enumerate(values, start=1):
            if value is None:
                continue  # leave the cell genuinely empty
            cell = self.ws.cell(row=self._row, column=index, value=value)
            cell.border = _BORDER
            cell.alignment = _TOP
            fmt = formats[index - 1] if index - 1 < len(formats) else None
            if fmt:
                cell.number_format = fmt
            elif isinstance(value, datetime):
                cell.number_format = _DATETIME_FORMAT
            elif isinstance(value, date):
                cell.number_format = _DATE_FORMAT
            self._track(index, value)
        self._row += 1

    def finish(self, *, freeze_at: str | None = None, autofilter: bool = False) -> None:
        for index, width in self._widths.items():
            self.ws.column_dimensions[get_column_letter(index)].width = min(
                max(width + 2, _MIN_WIDTH), _MAX_WIDTH
            )
        if freeze_at:
            self.ws.freeze_panes = freeze_at
        if autofilter and getattr(self, "_header_row", None) and self._row > self._header_row + 1:
            last_col = get_column_letter(max(self._widths) if self._widths else 1)
            self.ws.auto_filter.ref = f"A{self._header_row}:{last_col}{self._row - 1}"

    def _track(self, index: int, value: Any) -> None:
        length = len(str(value)) if value is not None else 0
        if length > self._widths.get(index, 0):
            self._widths[index] = min(length, _MAX_WIDTH)


def _kv(sheet: _Sheet, label: str, value: Any, fmt: str | None = None) -> None:
    sheet.row([label, value], [None, fmt])


# --------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------

def _summary(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Tổng quan")
    s.title_row("GÓI DỮ LIỆU MRV")
    s.note_row(m.get("disclaimer") or "")
    s.blank_row()

    s.title_row("Thông tin bản xuất")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Thời điểm xuất (UTC)", _dt(m.get("generated_at")))
    generated_by = m.get("generated_by") or {}
    _kv(s, "Vai trò người xuất", _text([L.label(r, L.ROLE) for r in (generated_by.get("roles") or [])]))
    _kv(s, "Mã và định danh kỹ thuật", f"Xem sheet '{AUDIT_SHEET}'")
    s.blank_row()

    case = m.get("case") or {}
    s.title_row("Hồ sơ MRV")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Ký hiệu hồ sơ", _text(case.get("case_code")))
    _kv(s, "Tên hồ sơ", _text(case.get("name")))
    _kv(s, "Trạng thái", L.label(case.get("status"), L.CASE_STATUS))
    _kv(s, "Kỳ bắt đầu", _d(case.get("period_start")))
    _kv(s, "Kỳ kết thúc", _d(case.get("period_end")))
    s.blank_row()

    readiness = m.get("readiness") or {}
    s.title_row("Mức độ sẵn sàng")
    s.header(["Chỉ tiêu", "Giá trị"])
    _kv(s, "Tổng số bước", _num(readiness.get("total_steps")))
    _kv(s, "Số bước đã hoàn thành", _num(readiness.get("completed_steps")))
    _kv(s, "Số bước còn lại", _num(readiness.get("remaining_steps")))
    _kv(s, "Số tệp bằng chứng", _num(readiness.get("evidence_count")))
    _kv(s, "Bước chưa có bằng chứng", _text(readiness.get("steps_without_evidence")))
    _kv(s, "Có kết quả CO2e", _text(readiness.get("carbon_available")))
    _kv(s, "Số cảnh báo", _num(len(m.get("warnings") or [])))
    s.blank_row()

    s.note_row(
        "Các ô để TRỐNG nghĩa là chưa có dữ liệu — không phải giá trị 0. "
        "Xem sheet 'Cảnh báo' để biết phần nào của gói dữ liệu chưa đầy đủ. "
        f"Mã, định danh và giá trị gốc của mọi dòng nằm ở sheet '{AUDIT_SHEET}'; "
        f"ý nghĩa từng mã ở sheet '{DICTIONARY_SHEET}'."
    )
    s.finish(freeze_at="A2")


def _batches(m: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((m.get("scope") or {}).get("production_batches") or [], key=lambda b: (
        str((b.get("crop_season") or {}).get("season_code") or ""), str(b.get("batch_code") or ""),
        str(b.get("production_batch_id") or "")))


def _scope(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Phạm vi")
    scope = m.get("scope") or {}
    org = scope.get("organization") or {}

    s.title_row("Tổ chức")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Ký hiệu", _text(org.get("organization_code")))
    _kv(s, "Tên", _text(org.get("name")))
    _kv(s, "Loại hình", L.label(org.get("organization_type"), L.ORGANIZATION_TYPE))
    s.blank_row()

    s.title_row("Nông hộ / Thửa / Vụ canh tác / Lô sản xuất")
    s.note_row(
        "Phạm vi tính CO2e là VỤ CANH TÁC. Lô sản xuất chỉ phục vụ "
        "truy xuất nguồn gốc, KHÔNG phải phạm vi tính carbon."
    )
    s.header([
        "Nông hộ (ký hiệu)", "Nông hộ (tên)", "Thửa (ký hiệu)", "Diện tích (ha)",
        "Vụ (ký hiệu)", "Trạng thái vụ", "Bắt đầu", "Kết thúc", "Lô sản xuất (ký hiệu)",
    ])
    batches = _batches(m)
    if not batches:
        s.row([EMPTY_NOTE])
    for b in batches:
        farm = b.get("farm") or {}
        plot = b.get("plot") or {}
        season = b.get("crop_season") or {}
        s.row([
            _text(farm.get("farm_code")), _text(farm.get("name")),
            _text(plot.get("plot_code")), _num(plot.get("area_ha")),
            _text(season.get("season_code")), L.label(season.get("status"), L.SEASON_STATUS),
            _d(season.get("started_on")), _d(season.get("closed_on")), _text(b.get("batch_code")),
        ])
    s.finish(autofilter=True)


def _steps(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Các bước MRV")
    s.note_row("Trạng thái được giữ nguyên như hệ thống ghi nhận; 'Chưa bắt đầu' KHÔNG phải 'Không đạt'.")
    s.header(["Thứ tự", "Tên bước", "Trạng thái", "Bắt đầu (UTC)", "Hoàn thành (UTC)",
              "Số bằng chứng", "Ghi chú"])
    steps = sorted(m.get("steps") or [], key=lambda x: x.get("step_no") or 0)
    if not steps:
        s.row([EMPTY_NOTE])
    for step in steps:
        s.row([
            _num(step.get("step_no")), _text(step.get("name")), L.label(step.get("status"), L.STEP_STATUS),
            _dt(step.get("started_at")), _dt(step.get("completed_at")),
            _num(step.get("evidence_count")), _text(step.get("notes")),
        ])
    s.finish(freeze_at="A3", autofilter=True)


def _evidence_items(m: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(m.get("evidence") or [], key=lambda x: (x.get("step_no") or 0, str(x.get("evidence_id") or "")))


def _evidence(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Bằng chứng")
    s.note_row(
        "Gói dữ liệu này CHỈ chứa THÔNG TIN MÔ TẢ của tệp bằng chứng — KHÔNG kèm "
        f"tệp gốc. Mã băm và vị trí lưu trữ nội bộ nằm ở sheet '{AUDIT_SHEET}'."
    )
    s.header(["Bước", "Loại", "Tên tệp", "Tải lên (UTC)", "Có mã băm SHA-256", "Kèm tệp trong gói"])
    items = _evidence_items(m)
    if not items:
        s.row([EMPTY_NOTE])
    for item in items:
        checksum = item.get("checksum") or {}
        storage = item.get("storage") or {}
        s.row([
            _num(item.get("step_no")), L.label(item.get("evidence_type"), L.EVIDENCE_TYPE),
            _text(item.get("file_name")), _dt(item.get("uploaded_at")),
            _text(bool(checksum.get("value"))), _text(storage.get("included_in_package")),
        ])
    s.finish(freeze_at="A3", autofilter=True)


# A stable superset. Each activity type contributes its own columns; a type that
# does not have a column leaves it blank rather than borrowing another's.
_ACTIVITY_DETAIL_COLUMNS: list[tuple[str, str, str]] = [
    ("variety_name", "Giống", "text"),
    ("seed_kg", "Lượng giống (kg)", "num"),
    ("seeding_method", "Phương pháp gieo", "text"),
    ("fertilizer_name", "Tên phân bón", "text"),
    ("fertilizer_type", "Loại phân bón", "text"),
    ("amount_kg", "Lượng phân (kg)", "num"),
    ("nitrogen_percent", "N (%)", "num"),
    ("phosphorus_percent", "P (%)", "num"),
    ("potassium_percent", "K (%)", "num"),
    ("method", "Phương pháp", "text"),
    ("water_volume_m3", "Lượng nước (m³)", "num"),
    ("duration_minutes", "Thời lượng (phút)", "num"),
    ("water_level_cm", "Mực nước (cm)", "num"),
    ("pump_energy_kwh", "Điện bơm (kWh)", "num"),
    ("product_name", "Tên thuốc BVTV", "text"),
    ("active_ingredient", "Hoạt chất", "text"),
    ("amount", "Lượng dùng", "num"),
    ("unit", "Đơn vị", "text"),
    ("fuel_type", "Loại nhiên liệu", "text"),
    ("volume_liters", "Nhiên liệu (lít)", "num"),
    ("straw_mass_kg", "Khối lượng rơm (kg)", "num"),
    ("days_before_cultivation", "Số ngày trước canh tác", "num"),
    ("dry_matter_fraction", "Tỷ lệ chất khô", "num"),
    ("returned_to_field", "Vùi lại ruộng", "text"),
    ("yield_kg", "Sản lượng (kg)", "num"),
    ("harvested_area_ha", "Diện tích thu hoạch (ha)", "num"),
    ("moisture_percent", "Độ ẩm (%)", "num"),
    ("cost_vnd", "Chi phí (VND)", "num"),
    ("total_cost_vnd", "Tổng chi phí (VND)", "num"),
]


def _activity_items(m: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(m.get("activities") or [],
                  key=lambda x: (str(x.get("occurred_at") or ""), str(x.get("activity_id") or "")))


def _activities(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Hoạt động canh tác")
    provenance = (m.get("provenance") or {}).get("activities") or {}
    codes = L.season_codes(m)
    s.note_row(
        "Hoạt động đã xoá mềm "
        + ("ĐƯỢC" if provenance.get("includes_deleted") else "KHÔNG được")
        + " đưa vào gói dữ liệu này. Ô để trống = không có số liệu, không phải 0. "
        + f"Dòng STT N ở đây là dòng STT N của bảng hoạt động trong sheet '{AUDIT_SHEET}'."
    )
    base = ["STT", "Loại", "Thời điểm (UTC)", "Ghi nhận lúc (UTC)", "Nguồn", "Vụ", "Ghi chú"]
    s.header(base + [label for _, label, _ in _ACTIVITY_DETAIL_COLUMNS])
    items = _activity_items(m)
    if not items:
        s.row([EMPTY_NOTE])
    for n, a in enumerate(items, start=1):
        detail = a.get("detail") or {}
        values: list[Any] = [
            n, L.label(a.get("activity_type"), L.ACTIVITY_TYPE),
            _dt(a.get("occurred_at")), _dt(a.get("recorded_at")),
            L.label(a.get("source"), L.SOURCE), L.season_name(m, a.get("crop_season_id"), codes),
            _text(a.get("note")),
        ]
        for key, _label, kind in _ACTIVITY_DETAIL_COLUMNS:
            raw = detail.get(key)
            if kind == "num":
                values.append(_num(raw))
            elif key in L.DETAIL_VALUE:
                values.append(L.label(raw, L.DETAIL_VALUE[key]))
            else:
                values.append(_text(raw))
        s.row(values)
    s.finish(freeze_at="C3", autofilter=True)


def _harvest(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Thu hoạch")
    codes = L.season_codes(m)
    s.note_row("Sản lượng dùng làm mẫu số cho các chỉ số trên mỗi kg. Lấy nguyên từ gói dữ liệu.")
    s.header(["Vụ", "Thời điểm (UTC)", "Sản lượng (kg)", "Diện tích thu hoạch (ha)", "Độ ẩm (%)"])
    harvest = m.get("harvest") or {}
    events = sorted(
        harvest.get("events") or [],
        key=lambda x: (str(x.get("occurred_at") or ""), str(x.get("activity_id") or "")),
    )
    if not events:
        s.row([EMPTY_NOTE])
    for e in events:
        s.row([
            L.season_name(m, e.get("crop_season_id"), codes),
            _dt(e.get("occurred_at")), _num(e.get("yield_kg")),
            _num(e.get("harvested_area_ha")), _num(e.get("moisture_percent")),
        ])
    s.finish(freeze_at="A3", autofilter=True)


_METRIC_ROWS = [
    ("yield_kg", "Sản lượng", "kg", None),
    ("water_m3", "Lượng nước", "m³", "water"),
    ("fertilizer_kg", "Lượng phân bón", "kg", "fertilizer"),
    ("water_per_kg", "Nước trên mỗi kg", "m³/kg", "water"),
    ("fertilizer_per_kg", "Phân bón trên mỗi kg", "kg/kg", "fertilizer"),
    ("cost_per_kg", "Chi phí đầu vào đã ghi nhận trên mỗi kg", "VND/kg", "cost"),
    ("co2e_per_kg", "CO2e trên mỗi kg", "kg CO₂e/kg", "carbon"),
]


def _resource(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Chỉ số tài nguyên")
    codes = L.season_codes(m)
    s.note_row(
        "Giá trị lấy nguyên từ gói dữ liệu, KHÔNG tính lại. Ô giá trị để trống nghĩa "
        "là thiếu số liệu đầu vào — cột 'Đầy đủ dữ liệu' cho biết vì sao."
    )
    s.header(["Vụ", "Chỉ số", "Giá trị", "Đơn vị", "Đầy đủ dữ liệu"])
    per_season = (m.get("resource_metrics") or {}).get("per_crop_season") or {}
    if not per_season:
        s.row([EMPTY_NOTE])
    for season_id in sorted(per_season, key=lambda sid: (L.season_name(m, sid, codes) or "", sid)):
        metrics = per_season[season_id] or {}
        completeness = metrics.get("data_completeness") or {}
        for key, label, unit, completeness_key in _METRIC_ROWS:
            complete = completeness.get(completeness_key) if completeness_key else None
            s.row([
                L.season_name(m, season_id, codes), label, _num(metrics.get(key)), unit,
                _text(complete) if complete is not None else None,
            ])
    s.finish(freeze_at="A3", autofilter=True)


def _carbon_items(m: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    per_season = (m.get("carbon") or {}).get("per_crop_season") or {}
    return [(sid, per_season[sid] or {}) for sid in sorted(per_season)]


def _breakdown_items(m: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for season_id, c in _carbon_items(m):
        for b in sorted(c.get("breakdown") or [], key=lambda x: (
                str(x.get("category") or ""), str(x.get("gas") or ""), str(x.get("emission_factor_id") or ""))):
            out.append((season_id, b))
    return out


def _carbon(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Carbon")
    codes = L.season_codes(m)
    s.note_row(
        "Kết quả CO2e lấy nguyên từ bản tính đã lưu. Bảng tính này KHÔNG tính lại "
        "và KHÔNG phải xác nhận hay chứng nhận phát thải."
    )
    s.header(["Vụ", "Trạng thái", "Lý do", "Loại kết quả", "Kịch bản", "Thời điểm tính (UTC)",
              "Tổng CO2e (kg)", "CO2e/kg", "Sản lượng (kg)", "Phiên bản bộ hệ số",
              "Phiên bản engine", "Bậc phương pháp"])
    items = _carbon_items(m)
    if not items:
        s.row([EMPTY_NOTE])
    for season_id, c in items:
        s.row([
            L.season_name(m, season_id, codes), L.label(c.get("status"), L.CARBON_STATUS),
            L.label(c.get("reason"), L.CARBON_REASON), L.label(c.get("calculation_kind"), L.CALCULATION_KIND),
            L.label(c.get("scenario"), L.SCENARIO), _dt(c.get("calculated_at")),
            _num(c.get("total_co2e_kg")), _num(c.get("co2e_per_kg")), _num(c.get("yield_kg")),
            _text(c.get("ef_config_version")), _text(c.get("engine_version")), _num(c.get("methodology_tier")),
        ])

    s.blank_row()
    s.title_row("Chi tiết phát thải theo hạng mục")
    s.header(["Vụ", "Hạng mục", "Khí", "Giá trị hoạt động", "Đơn vị",
              "Hệ số áp dụng", "Khí (kg)", "CO2e (kg)"])
    breakdown = _breakdown_items(m)
    for season_id, b in breakdown:
        s.row([
            L.season_name(m, season_id, codes), L.label(b.get("category"), L.CATEGORY),
            L.label(b.get("gas"), L.GAS), _num(b.get("activity_value")), L.label(b.get("activity_unit"), L.UNIT),
            _num(b.get("factor_value_used")), _num(b.get("gas_kg")), _num(b.get("co2e_kg")),
        ])
    if not breakdown:
        s.row(["Chưa có bản tính CO2e nào nên không có chi tiết phát thải."])
    s.finish(freeze_at="A3")


def _factor_sets(m: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((m.get("provenance") or {}).get("emission_factor_sets") or [],
                  key=lambda x: (str(x.get("version_code") or ""), str(x.get("factor_set_id") or "")))


def _provenance(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Nguồn gốc hệ số")
    provenance = m.get("provenance") or {}
    s.title_row("Phạm vi và nguồn dữ liệu")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Phạm vi tính carbon", L.label(provenance.get("carbon_scope"), L.CARBON_SCOPE))
    _kv(s, "Bao gồm hoạt động đã xoá", _text((provenance.get("activities") or {}).get("includes_deleted")))
    _kv(s, "Kèm tệp bằng chứng gốc", _text(provenance.get("evidence_binaries_included")))
    s.blank_row()

    sets = _factor_sets(m)
    s.title_row("Bộ hệ số phát thải")
    if not sets:
        # Never hidden: an empty provenance section is itself a finding.
        s.header(["Tình trạng", "Giải thích"])
        s.row([L.label("factor_provenance_unavailable", L.WARNING_CODE),
               "Gói dữ liệu không kèm nguồn gốc hệ số phát thải vì chưa có bản tính "
               "CO2e nào liên kết tới một bộ hệ số."])
        s.finish(freeze_at="A2")
        return

    s.header(["Phiên bản", "Tên", "Phương pháp luận", "Phiên bản phương pháp",
              "Nguồn", "Liên kết nguồn", "Trạng thái", "Hiệu lực từ", "Hiệu lực đến",
              "Công bố lúc (UTC)"])
    for fs in sets:
        s.row([
            _text(fs.get("version_code")), _text(fs.get("name")),
            _text(fs.get("methodology_name")), _text(fs.get("methodology_version")),
            _text(fs.get("source_name")), _text(fs.get("source_url")), L.label(fs.get("status"), L.FACTOR_SET_STATUS),
            _d(fs.get("valid_from")), _d(fs.get("valid_to")), _dt(fs.get("published_at")),
        ])

    s.blank_row()
    s.title_row("Hệ số chi tiết")
    s.header(["Bộ hệ số", "Hạng mục", "Khí", "Loại tham số", "Giá trị", "Đơn vị hoạt động",
              "Đơn vị kết quả", "Tham chiếu nguồn", "Tình trạng đối chiếu", "Khoảng bất định"])
    for fs in sets:
        for f in sorted(fs.get("factors") or [], key=lambda x: str(x.get("factor_code") or "")):
            s.row([
                _text(fs.get("version_code")), L.label(f.get("category"), L.CATEGORY),
                L.label(f.get("gas"), L.GAS), L.label(f.get("parameter_kind"), L.PARAMETER_KIND),
                _num(f.get("factor_value")), L.label(f.get("activity_unit"), L.UNIT),
                L.label(f.get("result_unit"), L.UNIT), _text(f.get("source_reference")),
                L.label(f.get("verification_status"), L.VERIFICATION), _text(f.get("uncertainty_range")),
            ])
    s.finish(freeze_at="A2")


def _warning_items(m: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(m.get("warnings") or [], key=lambda x: (str(x.get("code") or ""),
                                                           json.dumps(x.get("related") or {}, sort_keys=True)))


def _warnings(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Cảnh báo")
    s.note_row(
        "Mức độ giữ nguyên như gói dữ liệu ghi nhận. 'Thông tin' nghĩa là dữ liệu chưa "
        f"đầy đủ, KHÔNG phải lỗi. Mã cảnh báo và nội dung gốc ở sheet '{AUDIT_SHEET}'."
    )
    s.header(["Loại cảnh báo", "Mức độ", "Nội dung", "Liên quan"])
    items = _warning_items(m)
    if not items:
        s.row(["Không có cảnh báo nào."])
    for w in items:
        s.row([L.label(w.get("code"), L.WARNING_CODE), L.label(w.get("severity"), L.SEVERITY),
               L.humanize(m, w.get("message")), L.related(m, w.get("related"))])
    s.finish(freeze_at="A3", autofilter=True)


_AUDIT_COLUMNS = [
    ("export_id", "Mã bản xuất JSON (snapshot) mà bảng tính này được kết xuất từ đó."),
    ("case_id / organization_id", "Mã hồ sơ MRV / tổ chức trong cơ sở dữ liệu."),
    ("user_id", "Mã người dùng (Supabase Auth) đã tạo bản xuất."),
    ("farm_id / plot_id / crop_season_id / production_batch_id", "Mã nông hộ / thửa / vụ canh tác / lô sản xuất."),
    ("activity_id", "Mã hoạt động canh tác trên máy chủ."),
    ("recorded_by", "Mã người dùng đã ghi hoạt động."),
    ("device_id / client_event_id", "Mã thiết bị và mã sự kiện offline — cặp khoá chống ghi trùng khi đồng bộ."),
    ("evidence_id / uploaded_by", "Mã tệp bằng chứng / mã người tải lên."),
    ("bucket / object_path", "Vị trí lưu trữ nội bộ của tệp bằng chứng (không phải liên kết tải về)."),
    ("calculation_id", "Mã bản tính CO2e đã lưu."),
    ("factor_set_id / emission_factor_id / factor_code", "Mã bộ hệ số / mã hệ số / ký hiệu hệ số trong bộ."),
    ("formula_expression", "Biểu thức engine đã dùng cho dòng phát thải."),
    ("manifest_sha256", "Mã băm SHA-256 của gói JSON (theo cách chuẩn hoá ghi bên cạnh)."),
]


def _dictionary(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, DICTIONARY_SHEET)
    s.title_row("Từ điển dữ liệu")
    s.note_row(
        "Mỗi mã trong gói JSON và sheet kỹ thuật, cùng nghĩa tiếng Việt đang hiển thị ở các sheet nghiệp vụ. "
        "Giá trị không có trong bảng này được hiển thị nguyên như đã nhập."
    )
    s.header(["Nhóm", "Mã (JSON / sheet kỹ thuật)", "Ý nghĩa (sheet nghiệp vụ, PDF)"])
    for group, table in L.DICTIONARY:
        for code, meaning in table.items():
            s.row([group, code, meaning])
    s.blank_row()
    s.title_row("Cột định danh trong sheet kỹ thuật")
    s.header(["Cột", "Ý nghĩa"])
    for column, meaning in _AUDIT_COLUMNS:
        s.row([column, meaning])
    s.finish(freeze_at="A4")


def _audit(wb: Workbook, m: dict[str, Any], *, rendered_at: datetime | None) -> None:
    """Every id and raw code, in ONE sheet, row-aligned with the business sheets."""
    s = _Sheet(wb, AUDIT_SHEET)
    s.title_row("Dữ liệu kỹ thuật / Audit metadata")
    s.note_row(
        "Định danh và mã gốc đúng như trong gói JSON — để đối chiếu và truy vết. "
        f"Ý nghĩa từng mã: sheet '{DICTIONARY_SHEET}'."
    )
    s.blank_row()

    integrity = m.get("package_integrity") or {}
    generated_by = m.get("generated_by") or {}
    case = m.get("case") or {}
    org = (m.get("scope") or {}).get("organization") or {}
    s.title_row("Bản xuất và tính toàn vẹn")
    s.header(["Trường", "Giá trị"])
    _kv(s, "export_id", _text(m.get("export_id")))
    _kv(s, "schema_version", _text(m.get("schema_version")))
    _kv(s, "generated_at (UTC)", _dt(m.get("generated_at")))
    _kv(s, "generated_by.user_id", _text(generated_by.get("user_id")))
    _kv(s, "generated_by.roles", _text(generated_by.get("roles")))
    _kv(s, "case_id", _text(case.get("case_id")))
    _kv(s, "case.status", _text(case.get("status")))
    _kv(s, "organization_id", _text(org.get("organization_id")))
    _kv(s, "organization_type", _text(org.get("organization_type")))
    _kv(s, "algorithm", _text(integrity.get("algorithm")))
    _kv(s, "manifest_sha256", _text(integrity.get("manifest_sha256")))
    _kv(s, "canonical_over", _text(integrity.get("canonical_over")))
    _kv(s, "canonical_form", _text(integrity.get("canonical_form")))
    # Through _dt: Excel rejects a tz-aware datetime outright.
    _kv(s, "workbook rendered_at (UTC)", _dt(rendered_at))
    s.note_row(
        "Bảng tính này được KẾT XUẤT TỪ gói dữ liệu JSON có mã băm trên, không truy vấn lại "
        "dữ liệu nguồn. Đây là dữ liệu phục vụ đối chiếu, KHÔNG phải chứng nhận hay kết quả thẩm định."
    )
    s.blank_row()

    s.title_row("Phạm vi (cùng thứ tự với sheet 'Phạm vi')")
    s.header(["farm_id", "farm_code", "plot_id", "plot_code", "crop_season_id", "season_code",
              "season.status", "production_batch_id", "batch_code"])
    for b in _batches(m):
        farm, plot, season = b.get("farm") or {}, b.get("plot") or {}, b.get("crop_season") or {}
        s.row([_text(farm.get("farm_id")), _text(farm.get("farm_code")), _text(plot.get("plot_id")),
               _text(plot.get("plot_code")), _text(season.get("crop_season_id")), _text(season.get("season_code")),
               _text(season.get("status")), _text(b.get("production_batch_id")), _text(b.get("batch_code"))])
    s.blank_row()

    s.title_row("Các bước MRV")
    s.header(["step_no", "status"])
    for step in sorted(m.get("steps") or [], key=lambda x: x.get("step_no") or 0):
        s.row([_num(step.get("step_no")), _text(step.get("status"))])
    s.blank_row()

    s.title_row("Bằng chứng (cùng thứ tự với sheet 'Bằng chứng')")
    s.header(["evidence_id", "step_no", "evidence_type", "mime_type", "uploaded_by",
              "checksum.algorithm", "checksum.value", "bucket", "object_path"])
    for item in _evidence_items(m):
        checksum, storage = item.get("checksum") or {}, item.get("storage") or {}
        s.row([_text(item.get("evidence_id")), _num(item.get("step_no")), _text(item.get("evidence_type")),
               _text(item.get("mime_type")), _text(item.get("uploaded_by")), _text(checksum.get("algorithm")),
               _text(checksum.get("value")), _text(storage.get("bucket")), _text(storage.get("object_path"))])
    s.blank_row()

    s.title_row("Hoạt động (dòng STT N = STT N của sheet 'Hoạt động canh tác')")
    choice_keys = sorted(L.DETAIL_VALUE)
    s.header(["STT", "activity_id", "activity_type", "source", "recorded_by", "crop_season_id",
              "device_id", "client_event_id", *choice_keys])
    for n, a in enumerate(_activity_items(m), start=1):
        prov, detail = a.get("provenance") or {}, a.get("detail") or {}
        s.row([n, _text(a.get("activity_id")), _text(a.get("activity_type")), _text(a.get("source")),
               _text(a.get("recorded_by")), _text(a.get("crop_season_id")), _text(prov.get("device_id")),
               _text(prov.get("client_event_id")), *[_text(detail.get(k)) for k in choice_keys]])
    s.blank_row()

    s.title_row("Carbon")
    s.header(["crop_season_id", "status", "reason", "calculation_id", "calculation_kind", "scenario",
              "factor_set_id", "ef_config_version"])
    for season_id, c in _carbon_items(m):
        s.row([_text(season_id), _text(c.get("status")), _text(c.get("reason")), _text(c.get("calculation_id")),
               _text(c.get("calculation_kind")), _text(c.get("scenario")), _text(c.get("factor_set_id")),
               _text(c.get("ef_config_version"))])
    s.header(["crop_season_id", "category", "gas", "activity_unit", "emission_factor_id", "activity_id",
              "formula_expression"])
    for season_id, b in _breakdown_items(m):
        s.row([_text(season_id), _text(b.get("category")), _text(b.get("gas")), _text(b.get("activity_unit")),
               _text(b.get("emission_factor_id")), _text(b.get("activity_id")), _text(b.get("formula_expression"))])
    s.blank_row()

    provenance = m.get("provenance") or {}
    s.title_row("Nguồn gốc hệ số")
    s.header(["Trường", "Giá trị"])
    _kv(s, "carbon_scope", _text(provenance.get("carbon_scope")))
    _kv(s, "activities.source_tables", _text((provenance.get("activities") or {}).get("source_tables")))
    s.header(["factor_set_id", "version_code", "factor_code", "category", "gas", "parameter_kind",
              "activity_unit", "result_unit", "verification_status", "status"])
    for fs in _factor_sets(m):
        for f in sorted(fs.get("factors") or [], key=lambda x: str(x.get("factor_code") or "")):
            s.row([_text(fs.get("factor_set_id")), _text(fs.get("version_code")), _text(f.get("factor_code")),
                   _text(f.get("category")), _text(f.get("gas")), _text(f.get("parameter_kind")),
                   _text(f.get("activity_unit")), _text(f.get("result_unit")),
                   _text(f.get("verification_status")), _text(fs.get("status"))])
    s.blank_row()

    s.title_row("Cảnh báo (cùng thứ tự với sheet 'Cảnh báo')")
    s.header(["code", "severity", "message", "related"])
    for w in _warning_items(m):
        s.row([_text(w.get("code")), _text(w.get("severity")), _text(w.get("message")), _text(w.get("related"))])
    s.finish(freeze_at="A2")


# Excel forbids "/" in a sheet name; the sheet's first line reads
# "Dữ liệu kỹ thuật / Audit metadata".
AUDIT_SHEET = "Dữ liệu kỹ thuật (Audit)"
DICTIONARY_SHEET = "Từ điển dữ liệu"

_SHEETS = [_summary, _scope, _steps, _evidence, _activities, _harvest,
           _resource, _carbon, _provenance, _warnings, _dictionary]

SHEET_TITLES = ["Tổng quan", "Phạm vi", "Các bước MRV", "Bằng chứng", "Hoạt động canh tác",
                "Thu hoạch", "Chỉ số tài nguyên", "Carbon", "Nguồn gốc hệ số", "Cảnh báo",
                DICTIONARY_SHEET, AUDIT_SHEET]
# The human-facing sheets: no UUID, raw enum or technical code (Round 5.1).
BUSINESS_SHEETS = SHEET_TITLES[:10]


def render_workbook(manifest: dict[str, Any], *, rendered_at: datetime | None = None) -> bytes:
    """Manifest -> .xlsx bytes. The manifest is the only source of business data."""
    if not isinstance(manifest, dict) or not manifest.get("schema_version"):
        raise ValueError("not an MRV manifest")

    wb = Workbook()
    wb.remove(wb.active)  # drop the default sheet rather than leaving it blank
    for build in _SHEETS:
        build(wb, manifest)
    _audit(wb, manifest, rendered_at=rendered_at)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def workbook_filename(case_code: str, generated_at: Any, export_id: str) -> str:
    """Same deterministic, ASCII-safe convention as the JSON artifact."""
    from .manifest import export_filename

    return export_filename(case_code, _dt(generated_at) or datetime.now(timezone.utc), export_id)[:-5] + ".xlsx"
