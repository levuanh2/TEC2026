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
    _kv(s, "Mã bản xuất (export_id)", _text(m.get("export_id")))
    _kv(s, "Phiên bản lược đồ (schema_version)", _text(m.get("schema_version")))
    _kv(s, "Thời điểm tạo (UTC)", _dt(m.get("generated_at")))
    generated_by = m.get("generated_by") or {}
    _kv(s, "Người tạo (user_id)", _text(generated_by.get("user_id")))
    _kv(s, "Vai trò người tạo", _text(generated_by.get("roles")))
    s.blank_row()

    case = m.get("case") or {}
    s.title_row("Hồ sơ MRV")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Mã hồ sơ (case_id)", _text(case.get("case_id")))
    _kv(s, "Ký hiệu hồ sơ", _text(case.get("case_code")))
    _kv(s, "Tên hồ sơ", _text(case.get("name")))
    _kv(s, "Trạng thái", _text(case.get("status")))
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
        "Xem sheet 'Cảnh báo' để biết phần nào của gói dữ liệu chưa đầy đủ."
    )
    s.finish(freeze_at="A2")


def _scope(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Phạm vi")
    scope = m.get("scope") or {}
    org = scope.get("organization") or {}

    s.title_row("Tổ chức")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Mã tổ chức", _text(org.get("organization_id")))
    _kv(s, "Ký hiệu", _text(org.get("organization_code")))
    _kv(s, "Tên", _text(org.get("name")))
    _kv(s, "Loại hình", _text(org.get("organization_type")))
    s.blank_row()

    s.title_row("Nông hộ / Thửa / Vụ canh tác / Lô sản xuất")
    s.note_row(
        "Phạm vi tính CO2e là VỤ CANH TÁC (crop season). Lô sản xuất chỉ phục vụ "
        "truy xuất nguồn gốc, KHÔNG phải phạm vi tính carbon."
    )
    s.header([
        "Nông hộ (mã)", "Nông hộ (ký hiệu)", "Nông hộ (tên)",
        "Thửa (mã)", "Thửa (ký hiệu)", "Diện tích (ha)",
        "Vụ (mã)", "Vụ (ký hiệu)", "Trạng thái vụ", "Bắt đầu", "Kết thúc",
        "Lô sản xuất (mã)", "Lô sản xuất (ký hiệu)",
    ])
    batches = scope.get("production_batches") or []
    if not batches:
        s.row([EMPTY_NOTE])
    for b in sorted(batches, key=lambda x: str(x.get("production_batch_id") or "")):
        farm = b.get("farm") or {}
        plot = b.get("plot") or {}
        season = b.get("crop_season") or {}
        s.row([
            _text(farm.get("farm_id")), _text(farm.get("farm_code")), _text(farm.get("name")),
            _text(plot.get("plot_id")), _text(plot.get("plot_code")), _num(plot.get("area_ha")),
            _text(season.get("crop_season_id")), _text(season.get("season_code")),
            _text(season.get("status")), _d(season.get("started_on")), _d(season.get("closed_on")),
            _text(b.get("production_batch_id")), _text(b.get("batch_code")),
        ])
    s.finish(autofilter=True)


def _steps(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Các bước MRV")
    s.note_row("Trạng thái được giữ nguyên như hệ thống ghi nhận; 'chưa bắt đầu' KHÔNG phải 'thất bại'.")
    s.header(["Thứ tự", "Tên bước", "Trạng thái", "Bắt đầu (UTC)", "Hoàn thành (UTC)",
              "Số bằng chứng", "Ghi chú"])
    steps = sorted(m.get("steps") or [], key=lambda x: x.get("step_no") or 0)
    if not steps:
        s.row([EMPTY_NOTE])
    for step in steps:
        s.row([
            _num(step.get("step_no")), _text(step.get("name")), _text(step.get("status")),
            _dt(step.get("started_at")), _dt(step.get("completed_at")),
            _num(step.get("evidence_count")), _text(step.get("notes")),
        ])
    s.finish(freeze_at="A3", autofilter=True)


def _evidence(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Bằng chứng")
    s.note_row(
        "Gói dữ liệu này CHỈ chứa THÔNG TIN MÔ TẢ của tệp bằng chứng — KHÔNG kèm "
        "tệp gốc. Cột 'Đường dẫn lưu trữ' là tham chiếu nội bộ, không phải liên kết tải về."
    )
    s.header(["Mã bằng chứng", "Bước", "Loại", "Tên tệp", "Kiểu MIME", "Tải lên (UTC)",
              "Người tải lên", "Thuật toán băm", "Mã băm", "Kèm tệp trong gói",
              "Kho lưu trữ", "Đường dẫn lưu trữ"])
    items = sorted(
        m.get("evidence") or [],
        key=lambda x: (x.get("step_no") or 0, str(x.get("evidence_id") or "")),
    )
    if not items:
        s.row([EMPTY_NOTE])
    for item in items:
        checksum = item.get("checksum") or {}
        storage = item.get("storage") or {}
        s.row([
            _text(item.get("evidence_id")), _num(item.get("step_no")),
            _text(item.get("evidence_type")), _text(item.get("file_name")),
            _text(item.get("mime_type")), _dt(item.get("uploaded_at")),
            _text(item.get("uploaded_by")),
            _text(checksum.get("algorithm")), _text(checksum.get("value")),
            _text(storage.get("included_in_package")),
            _text(storage.get("bucket")), _text(storage.get("object_path")),
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


def _activities(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Hoạt động canh tác")
    provenance = (m.get("provenance") or {}).get("activities") or {}
    s.note_row(
        "Hoạt động đã xoá mềm "
        + ("ĐƯỢC" if provenance.get("includes_deleted") else "KHÔNG được")
        + " đưa vào gói dữ liệu này. Ô để trống = không có số liệu, không phải 0."
    )
    base = ["Mã hoạt động", "Loại", "Thời điểm (UTC)", "Ghi nhận lúc (UTC)",
            "Nguồn", "Người ghi", "Mã vụ", "Ghi chú", "Mã thiết bị", "Mã sự kiện thiết bị"]
    s.header(base + [label for _, label, _ in _ACTIVITY_DETAIL_COLUMNS])

    items = sorted(
        m.get("activities") or [],
        key=lambda x: (str(x.get("occurred_at") or ""), str(x.get("activity_id") or "")),
    )
    if not items:
        s.row([EMPTY_NOTE])
    for a in items:
        detail = a.get("detail") or {}
        prov = a.get("provenance") or {}
        values: list[Any] = [
            _text(a.get("activity_id")), _text(a.get("activity_type")),
            _dt(a.get("occurred_at")), _dt(a.get("recorded_at")),
            _text(a.get("source")), _text(a.get("recorded_by")),
            _text(a.get("crop_season_id")), _text(a.get("note")),
            _text(prov.get("device_id")), _text(prov.get("client_event_id")),
        ]
        for key, _label, kind in _ACTIVITY_DETAIL_COLUMNS:
            raw = detail.get(key)
            values.append(_num(raw) if kind == "num" else _text(raw))
        s.row(values)
    s.finish(freeze_at="C3", autofilter=True)


def _harvest(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Thu hoạch")
    s.note_row("Sản lượng dùng làm mẫu số cho các chỉ số trên mỗi kg. Lấy nguyên từ gói dữ liệu.")
    s.header(["Mã hoạt động", "Mã vụ", "Thời điểm (UTC)", "Sản lượng (kg)",
              "Diện tích thu hoạch (ha)", "Độ ẩm (%)"])
    harvest = m.get("harvest") or {}
    events = sorted(
        harvest.get("events") or [],
        key=lambda x: (str(x.get("occurred_at") or ""), str(x.get("activity_id") or "")),
    )
    if not events:
        s.row([EMPTY_NOTE])
    for e in events:
        s.row([
            _text(e.get("activity_id")), _text(e.get("crop_season_id")),
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
    ("co2e_per_kg", "CO2e trên mỗi kg", "kgCO2e/kg", "carbon"),
]


def _resource(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Chỉ số tài nguyên")
    s.note_row(
        "Giá trị lấy nguyên từ gói dữ liệu, KHÔNG tính lại. Ô giá trị để trống nghĩa "
        "là thiếu số liệu đầu vào — cột 'Đầy đủ dữ liệu' cho biết vì sao."
    )
    s.header(["Mã vụ", "Chỉ số", "Giá trị", "Đơn vị", "Đầy đủ dữ liệu"])
    per_season = (m.get("resource_metrics") or {}).get("per_crop_season") or {}
    if not per_season:
        s.row([EMPTY_NOTE])
    for season_id in sorted(per_season):
        metrics = per_season[season_id] or {}
        completeness = metrics.get("data_completeness") or {}
        for key, label, unit, completeness_key in _METRIC_ROWS:
            complete = completeness.get(completeness_key) if completeness_key else None
            s.row([
                _text(season_id), label, _num(metrics.get(key)), unit,
                _text(complete) if complete is not None else None,
            ])
    s.finish(freeze_at="A3", autofilter=True)


def _carbon(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Carbon")
    s.note_row(
        "Kết quả CO2e lấy nguyên từ bản tính đã lưu. Bảng tính này KHÔNG tính lại "
        "và KHÔNG phải xác nhận hay chứng nhận phát thải."
    )
    s.header(["Mã vụ", "Trạng thái", "Lý do", "Mã bản tính", "Thời điểm tính (UTC)",
              "Kịch bản", "Tổng CO2e (kg)", "CO2e/kg", "Sản lượng (kg)",
              "Phiên bản engine", "Bậc phương pháp", "Bộ hệ số",
              "Loại kết quả", "Phiên bản bộ hệ số"])
    per_season = (m.get("carbon") or {}).get("per_crop_season") or {}
    if not per_season:
        s.row([EMPTY_NOTE])
    for season_id in sorted(per_season):
        c = per_season[season_id] or {}
        s.row([
            _text(season_id), _text(c.get("status")), _text(c.get("reason")),
            _text(c.get("calculation_id")), _dt(c.get("calculated_at")),
            _text(c.get("scenario")), _num(c.get("total_co2e_kg")),
            _num(c.get("co2e_per_kg")), _num(c.get("yield_kg")),
            _text(c.get("engine_version")), _num(c.get("methodology_tier")),
            _text(c.get("factor_set_id")),
            _text(c.get("calculation_kind")), _text(c.get("ef_config_version")),
        ])

    s.blank_row()
    s.title_row("Chi tiết phát thải theo hạng mục")
    s.header(["Mã vụ", "Hạng mục", "Khí", "Giá trị hoạt động", "Đơn vị",
              "Hệ số áp dụng", "Khí (kg)", "CO2e (kg)", "Mã hệ số", "Mã hoạt động", "Công thức"])
    any_breakdown = False
    for season_id in sorted(per_season):
        breakdown = (per_season[season_id] or {}).get("breakdown") or []
        for b in sorted(breakdown, key=lambda x: (str(x.get("category") or ""),
                                                  str(x.get("gas") or ""),
                                                  str(x.get("emission_factor_id") or ""))):
            any_breakdown = True
            s.row([
                _text(season_id), _text(b.get("category")), _text(b.get("gas")),
                _num(b.get("activity_value")), _text(b.get("activity_unit")),
                _num(b.get("factor_value_used")), _num(b.get("gas_kg")),
                _num(b.get("co2e_kg")), _text(b.get("emission_factor_id")),
                _text(b.get("activity_id")), _text(b.get("formula_expression")),
            ])
    if not any_breakdown:
        s.row(["Chưa có bản tính CO2e nào nên không có chi tiết phát thải."])
    s.finish(freeze_at="A3")


def _provenance(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Nguồn gốc hệ số")
    provenance = m.get("provenance") or {}
    s.title_row("Phạm vi và nguồn dữ liệu")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Phạm vi tính carbon", _text(provenance.get("carbon_scope")))
    _kv(s, "Bao gồm hoạt động đã xoá", _text((provenance.get("activities") or {}).get("includes_deleted")))
    _kv(s, "Kèm tệp bằng chứng gốc", _text(provenance.get("evidence_binaries_included")))
    _kv(s, "Bảng nguồn hoạt động", _text((provenance.get("activities") or {}).get("source_tables")))
    s.blank_row()

    sets = provenance.get("emission_factor_sets") or []
    s.title_row("Bộ hệ số phát thải")
    if not sets:
        # Never hidden: an empty provenance section is itself a finding.
        s.header(["Tình trạng", "Giải thích"])
        s.row(["factor_provenance_unavailable",
               "Gói dữ liệu không kèm nguồn gốc hệ số phát thải vì chưa có bản tính "
               "CO2e nào liên kết tới một bộ hệ số."])
        s.finish(freeze_at="A2")
        return

    s.header(["Mã bộ hệ số", "Ký hiệu", "Tên", "Phương pháp luận", "Phiên bản phương pháp",
              "Nguồn", "Liên kết nguồn", "Trạng thái", "Hiệu lực từ", "Hiệu lực đến",
              "Công bố lúc (UTC)"])
    for fs in sorted(sets, key=lambda x: str(x.get("factor_set_id") or "")):
        s.row([
            _text(fs.get("factor_set_id")), _text(fs.get("version_code")), _text(fs.get("name")),
            _text(fs.get("methodology_name")), _text(fs.get("methodology_version")),
            _text(fs.get("source_name")), _text(fs.get("source_url")), _text(fs.get("status")),
            _d(fs.get("valid_from")), _d(fs.get("valid_to")), _dt(fs.get("published_at")),
        ])

    s.blank_row()
    s.title_row("Hệ số chi tiết")
    s.header(["Bộ hệ số", "Mã hệ số", "Hạng mục", "Khí", "Giá trị", "Đơn vị hoạt động",
              "Đơn vị kết quả", "Tham chiếu nguồn", "Tình trạng đối chiếu",
              "Loại tham số", "Khoảng bất định"])
    for fs in sorted(sets, key=lambda x: str(x.get("factor_set_id") or "")):
        for f in sorted(fs.get("factors") or [], key=lambda x: str(x.get("factor_code") or "")):
            s.row([
                _text(fs.get("version_code")), _text(f.get("factor_code")),
                _text(f.get("category")), _text(f.get("gas")), _num(f.get("factor_value")),
                _text(f.get("activity_unit")), _text(f.get("result_unit")),
                _text(f.get("source_reference")), _text(f.get("verification_status")),
                _text(f.get("parameter_kind")), _text(f.get("uncertainty_range")),
            ])
    s.finish(freeze_at="A2")


def _warnings(wb: Workbook, m: dict[str, Any]) -> None:
    s = _Sheet(wb, "Cảnh báo")
    s.note_row(
        "Mức độ giữ nguyên như gói dữ liệu ghi nhận. 'info' nghĩa là dữ liệu chưa "
        "đầy đủ, KHÔNG phải lỗi."
    )
    s.header(["Mã cảnh báo", "Mức độ", "Nội dung", "Liên quan"])
    items = m.get("warnings") or []
    if not items:
        s.row(["Không có cảnh báo nào."])
    for w in sorted(items, key=lambda x: (str(x.get("code") or ""),
                                          json.dumps(x.get("related") or {}, sort_keys=True))):
        s.row([_text(w.get("code")), _text(w.get("severity")), _text(w.get("message")),
               _text(w.get("related"))])
    s.finish(freeze_at="A3", autofilter=True)


def _manifest(wb: Workbook, m: dict[str, Any], *, rendered_at: datetime | None) -> None:
    s = _Sheet(wb, "Gói dữ liệu gốc")
    integrity = m.get("package_integrity") or {}
    s.title_row("Tính toàn vẹn của gói dữ liệu")
    s.header(["Trường", "Giá trị"])
    _kv(s, "Phiên bản lược đồ", _text(m.get("schema_version")))
    _kv(s, "Mã bản xuất", _text(m.get("export_id")))
    _kv(s, "Thuật toán", _text(integrity.get("algorithm")))
    _kv(s, "Mã băm gói dữ liệu (manifest_sha256)", _text(integrity.get("manifest_sha256")))
    _kv(s, "Phạm vi băm", _text(integrity.get("canonical_over")))
    _kv(s, "Cách chuẩn hoá", _text(integrity.get("canonical_form")))
    _kv(s, "Gói dữ liệu tạo lúc (UTC)", _dt(m.get("generated_at")))
    # Through _dt: Excel rejects a tz-aware datetime outright.
    _kv(s, "Bảng tính kết xuất lúc (UTC)", _dt(rendered_at))
    s.blank_row()
    s.note_row(
        "Bảng tính này được KẾT XUẤT TỪ gói dữ liệu JSON ở trên, không truy vấn lại "
        "dữ liệu nguồn. Mọi giá trị nghiệp vụ trong các sheet đều lấy từ đúng gói dữ "
        "liệu có mã băm này. Đây là dữ liệu phục vụ đối chiếu, KHÔNG phải chứng nhận "
        "hay kết quả thẩm định."
    )
    s.finish(freeze_at="A2")


_SHEETS = [_summary, _scope, _steps, _evidence, _activities, _harvest,
           _resource, _carbon, _provenance, _warnings]

SHEET_TITLES = ["Tổng quan", "Phạm vi", "Các bước MRV", "Bằng chứng", "Hoạt động canh tác",
                "Thu hoạch", "Chỉ số tài nguyên", "Carbon", "Nguồn gốc hệ số", "Cảnh báo",
                "Gói dữ liệu gốc"]


def render_workbook(manifest: dict[str, Any], *, rendered_at: datetime | None = None) -> bytes:
    """Manifest -> .xlsx bytes. The manifest is the only source of business data."""
    if not isinstance(manifest, dict) or not manifest.get("schema_version"):
        raise ValueError("not an MRV manifest")

    wb = Workbook()
    wb.remove(wb.active)  # drop the default sheet rather than leaving it blank
    for build in _SHEETS:
        build(wb, manifest)
    _manifest(wb, manifest, rendered_at=rendered_at)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def workbook_filename(case_code: str, generated_at: Any, export_id: str) -> str:
    """Same deterministic, ASCII-safe convention as the JSON artifact."""
    from .manifest import export_filename

    return export_filename(case_code, _dt(generated_at) or datetime.now(timezone.utc), export_id)[:-5] + ".xlsx"
