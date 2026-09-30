"""Render a canonical MRV manifest into a PDF evidence report.

THE ONE RULE
    Exactly as for the workbook: the only input is a stored `export_payload`.
    This module performs no query, calls no service, recomputes no carbon or
    resource figure and reaches for no newer data. JSON, XLSX and PDF rendered
    from one snapshot describe one business state.

WHAT THE PDF IS
    A human-readable audit / field report of that snapshot ("Gói báo cáo MRV").
    It is NOT a certification, an authority report, a carbon credit or an MRV
    compliance certificate, and it says so on the cover and in every footer.

PRESENTATION, NOT DATA
    The renderer may originate only presentation: Vietnamese labels, layout,
    number and date formatting, the rendering timestamp and the artifact's own
    export id. Specifically:

    * null is shown as words ("Chưa đủ dữ liệu" / "Chưa có"), never as 0;
    * quantities keep the snapshot's digits (trailing zeros trimmed); per-kg
      ratios are shown to 6 significant digits, and the report says so -- the
      full value stays in JSON/XLSX;
    * timestamps are shown in Vietnam time (UTC+7, labelled), date-only values
      are never shifted, and the integrity section keeps raw UTC ISO strings;
    * activity quantities are NOT summed per type: a second total could
      disagree with the canonical resource metrics, which are shown instead.

FONTS
    Be Vietnam Pro (SIL OFL 1.1, bundled in `fonts/` with its licence) -- the
    same family the web app uses, designed for Vietnamese. ReportLab embeds a
    subset in each PDF.
"""
from __future__ import annotations

import io
import json
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.platypus.tables import LongTable

from . import manifest as mrv_manifest
from .workbook import _ACTIVITY_DETAIL_COLUMNS

PDF_MEDIA_TYPE = "application/pdf"

# Rendering a long activity appendix is linear but not free. Beyond this the
# appendix stops and SAYS how many rows are only in JSON/XLSX -- never silently.
ACTIVITY_APPENDIX_LIMIT = 2000

COVER_DISCLAIMER = (
    "Đây là gói báo cáo hỗ trợ tổng hợp dữ liệu và bằng chứng MRV. Tài liệu này không "
    "phải chứng nhận hoặc xác nhận chính thức từ cơ quan thẩm quyền."
)
SCIENCE_DISCLAIMER = (
    "Kết quả CO₂e (nếu có) là số liệu hệ thống tính theo bộ hệ số ghi ở mục Nguồn gốc hệ số. "
    "Kết quả này chưa được cơ quan có thẩm quyền hay tổ chức độc lập thẩm định, không phải "
    "tín chỉ carbon, và việc nhắc tới một phương pháp luận (ví dụ IPCC) không có nghĩa là "
    "phương pháp đó đã xác nhận kết quả."
)
NULL_VALUE = "Chưa đủ dữ liệu"
NULL_REF = "Chưa có"

# Hallmark tokens (web-dashboard styles.css, oklch converted to sRGB hex).
_INK = colors.HexColor("#11241c")        # --ac-ink
_INK_2 = colors.HexColor("#30423a")      # --ac-ink-2
_MUTED = colors.HexColor("#5f6d66")      # --ac-muted  (5.3:1 on white)
_RULE = colors.HexColor("#d3dbd7")       # --ac-rule
_RULE_2 = colors.HexColor("#b6c1bb")     # --ac-rule-2
_SUBTLE = colors.HexColor("#e9eeec")     # --ac-subtle
_ACCENT = colors.HexColor("#006a3b")     # --ac-accent (forest)

_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_SANS = "AgriCarbonSans"
_SANS_SEMI = "AgriCarbonSans-SemiBold"
_MONO = "Courier"  # hex digests only -- ASCII, no embedding needed
_font_lock = threading.Lock()


def _register_fonts() -> None:
    with _font_lock:
        if _SANS in pdfmetrics.getRegisteredFontNames():
            return
        pdfmetrics.registerFont(TTFont(_SANS, str(_FONT_DIR / "BeVietnamPro-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(_SANS_SEMI, str(_FONT_DIR / "BeVietnamPro-SemiBold.ttf")))
        pdfmetrics.registerFontFamily(_SANS, normal=_SANS, bold=_SANS_SEMI, italic=_SANS, boldItalic=_SANS_SEMI)


# --------------------------------------------------------------------------
# Vocabulary. Codes are always shown next to labels so nothing is reinterpreted.
# --------------------------------------------------------------------------

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
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_QUOTED_UUID = re.compile(r"(['\"]?)(" + _UUID.pattern + r")")
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
SCENARIO = {"actual": "Theo dữ liệu đã ghi nhận", "awd": "Mô phỏng AWD", "continuous_flooding": "Mô phỏng ngập liên tục"}
CALCULATION_KIND = {"actual": "Kết quả vận hành", "scenario": "Kịch bản mô phỏng"}
CATEGORY = {
    "irrigation_ch4": "CH₄ ruộng lúa", "fertilizer_n2o": "N₂O phân đạm", "fuel": "Nhiên liệu",
    "straw": "Rơm rạ", "straw_burning_ch4": "Đốt rơm CH₄", "straw_burning_n2o": "Đốt rơm N₂O",
    "electricity": "Điện", "other": "Khác",
}

# (key, label, unit, completeness key, is_ratio)
_METRIC_ROWS = [
    ("yield_kg", "Sản lượng", "kg", None, False),
    ("water_m3", "Lượng nước", "m³", "water", False),
    ("fertilizer_kg", "Lượng phân bón (khối lượng vật lý)", "kg", "fertilizer", False),
    ("water_per_kg", "Nước trên mỗi kg sản phẩm", "m³/kg", "water", True),
    ("fertilizer_per_kg", "Phân bón trên mỗi kg sản phẩm", "kg/kg", "fertilizer", True),
    ("cost_per_kg", "Chi phí đầu vào trực tiếp đã ghi nhận trên mỗi kg", "VND/kg", "cost", True),
    ("co2e_per_kg", "CO₂e trên mỗi kg sản phẩm", "kgCO₂e/kg", "carbon", True),
]
_RATIO_SIG_DIGITS = 6
_DETAIL_SKIP = {"activity_id", "created_at", "updated_at"}


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def _nfc(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value))


def _decimal(raw: Any) -> Decimal | None:
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def fmt_number(raw: Any, *, sig: int | None = None) -> str | None:
    """Vietnamese grouping (1.234,5). Digits come from the snapshot text.

    `sig` limits significant digits for display only; trailing zeros are
    trimmed. Returns None for null so the caller chooses the words to show.
    """
    value = _decimal(raw)
    if value is None:
        return None if raw is None or raw == "" else _nfc(raw)
    if sig and value != 0:
        digits = len(value.normalize().as_tuple().digits)
        if digits > sig:
            value = value.quantize(Decimal(1).scaleb(value.adjusted() - sig + 1), rounding=ROUND_HALF_UP)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    negative = text.startswith("-")
    text = text.lstrip("-")
    whole, _, frac = text.partition(".")
    grouped = f"{int(whole):,}".replace(",", ".") if whole else "0"
    out = grouped + ("," + frac if frac else "")
    return ("-" if negative and out.strip("0.,") else "") + out


def fmt_date(raw: Any) -> str | None:
    """A calendar date stays that date: no timezone arithmetic."""
    if not raw:
        return None
    text = raw.isoformat() if isinstance(raw, date) else str(raw)
    try:
        return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return _nfc(raw)


_ICT = timezone(timedelta(hours=7))


def fmt_local(raw: Any, *, with_time: bool = True) -> str | None:
    """UTC instant -> Vietnam time for reading. Vietnam has no DST."""
    if not raw:
        return None
    try:
        parsed = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return _nfc(raw)
    if parsed.tzinfo is None:
        return _nfc(raw)  # never guess a zone for an audit document
    local = parsed.astimezone(_ICT)
    return local.strftime("%d/%m/%Y %H:%M") if with_time else local.strftime("%d/%m/%Y")


def _short(value: Any, n: int = 8) -> str | None:
    return str(value)[:n] if value else None


def _compact(value: Any) -> str | None:
    if value is None or value == "" or value == {} or value == []:
        return None
    if isinstance(value, dict):
        return "; ".join(f"{k}={_compact(v) or ''}" for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "có" if value else "không"
    return _nfc(value)


def _status(code: Any, labels: dict[str, str]) -> str:
    if not code:
        return NULL_REF
    # The report is read by people: the Vietnamese label only (Round 5.1). The
    # code stays in the JSON snapshot and the XLSX data sheets. A code with no
    # label is printed as-is rather than given an invented name.
    return labels.get(str(code)) or str(code)


# --------------------------------------------------------------------------
# Styles and building blocks
# --------------------------------------------------------------------------

class _Styles:
    def __init__(self) -> None:
        base = dict(fontName=_SANS, textColor=_INK_2, leading=12, fontSize=8.8)
        # Intro text always travels with what it introduces, so a heading and its
        # note are never stranded at a page bottom with the table on the next page.
        self.body = ParagraphStyle("body", **base, spaceAfter=3, keepWithNext=1)
        self.note = ParagraphStyle("note", **{**base, "fontSize": 7.8, "leading": 10.6, "textColor": _MUTED},
                                   spaceAfter=4, keepWithNext=1)
        self.cell = ParagraphStyle("cell", fontName=_SANS, fontSize=7.8, leading=10.2, textColor=_INK)
        self.cell_muted = ParagraphStyle("cellm", parent=self.cell, textColor=_MUTED)
        self.head = ParagraphStyle("head", fontName=_SANS_SEMI, fontSize=7.4, leading=9.6, textColor=_INK)
        self.mono = ParagraphStyle("mono", fontName=_MONO, fontSize=7.2, leading=9.2, textColor=_INK)
        self.h1 = ParagraphStyle("h1", fontName=_SANS_SEMI, fontSize=12.5, leading=16, textColor=_INK,
                                 spaceBefore=2, spaceAfter=5, keepWithNext=1)
        self.h2 = ParagraphStyle("h2", fontName=_SANS_SEMI, fontSize=9.6, leading=13, textColor=_INK,
                                 spaceBefore=7, spaceAfter=3, keepWithNext=1)
        self.eyebrow = ParagraphStyle("eyebrow", fontName=_SANS_SEMI, fontSize=8, leading=11, textColor=_ACCENT)
        self.title = ParagraphStyle("title", fontName=_SANS_SEMI, fontSize=26, leading=31, textColor=_INK, spaceAfter=4)
        self.subtitle = ParagraphStyle("subtitle", fontName=_SANS, fontSize=11.5, leading=15, textColor=_INK_2, spaceAfter=14)
        self.case = ParagraphStyle("case", fontName=_SANS_SEMI, fontSize=13, leading=17, textColor=_INK, spaceAfter=10)
        self.callout = ParagraphStyle("callout", fontName=_SANS, fontSize=8.8, leading=12.4, textColor=_INK)


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    """Data is always escaped: a note containing '<' must print, not parse."""
    return Paragraph(escape(_nfc(text)).replace("\n", "<br/>"), style)


def _grid(rows: list[list[Any]], widths: list[float], *, header: bool = True, long: bool = False) -> Table:
    cls = LongTable if long else Table
    table = cls(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, _RULE),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), _SUBTLE), ("LINEBELOW", (0, 0), (-1, 0), 0.8, _INK_2)]
    table.setStyle(TableStyle(style))
    return table


class _Report:
    """Builds the story. Every value it prints is read from `self.m`."""

    CONTENT_WIDTH = A4[0] - 36 * mm

    def __init__(self, manifest: dict[str, Any], export_id: str | None, rendered_at: datetime | None):
        self.m = manifest
        self.export_id = export_id
        self.rendered_at = rendered_at
        self.s = _Styles()
        self.section_no = 0

    # -- helpers ---------------------------------------------------------
    def cell(self, value: Any, *, null: str = NULL_REF, muted: bool = False) -> Paragraph:
        if value is None or value == "":
            return _p(null, self.s.cell_muted)
        return _p(value, self.s.cell_muted if muted else self.s.cell)

    def head(self, *labels: str) -> list[Paragraph]:
        return [_p(label, self.s.head) for label in labels]

    def kv(self, pairs: Iterable[tuple[str, Any]], *, label_width: float = 52 * mm) -> Table:
        rows = []
        for label, value in pairs:
            if isinstance(value, Paragraph):
                shown = value
            else:
                shown = self.cell(value)
            rows.append([_p(label, self.s.cell_muted), shown])
        return _grid(rows, [label_width, self.CONTENT_WIDTH - label_width], header=False)

    def section(self, title: str, story: list[Any]) -> None:
        self.section_no += 1
        spacer = Spacer(1, 6)
        rule = HRFlowable(width="100%", thickness=0.6, color=_RULE_2, spaceBefore=2, spaceAfter=5)
        spacer.keepWithNext = rule.keepWithNext = 1  # a lone rule must not end a page
        story.append(spacer)
        story.append(rule)
        story.append(Paragraph(
            f'<font color="#006a3b">{self.section_no:02d}</font>&nbsp;&nbsp;{escape(title)}', self.s.h1
        ))

    # -- sections --------------------------------------------------------
    def build(self) -> list[Any]:
        story: list[Any] = []
        self.cover(story)
        story.append(PageBreak())
        self.summary(story)
        self.scope(story)
        self.steps(story)
        self.evidence(story)
        self.activities(story)
        self.harvest(story)
        self.resources(story)
        self.carbon(story)
        self.provenance(story)
        self.warnings(story)
        self.integrity(story)
        self.activity_appendix(story)
        return story

    def cover(self, story: list[Any]) -> None:
        case = self.m.get("case") or {}
        by = self.m.get("generated_by") or {}
        story.append(Spacer(1, 18 * mm))
        story.append(Paragraph("AGRICARBON · MRV EVIDENCE REPORT", self.s.eyebrow))
        story.append(Spacer(1, 4))
        story.append(Paragraph("Gói báo cáo MRV", self.s.title))
        story.append(Paragraph("Snapshot dữ liệu và bằng chứng hỗ trợ", self.s.subtitle))
        story.append(_p(f"{case.get('case_code') or NULL_REF} — {case.get('name') or NULL_REF}", self.s.case))
        story.append(self.kv([
            ("Mã hồ sơ", case.get("case_code")),
            ("Tên hồ sơ", case.get("name")),
            ("Trạng thái hồ sơ", _status(case.get("status"), CASE_STATUS)),
            ("Kỳ báo cáo", f"{fmt_date(case.get('period_start')) or NULL_REF} – {fmt_date(case.get('period_end')) or NULL_REF}"),
            ("Tổ chức", ((self.m.get("scope") or {}).get("organization") or {}).get("name")),
            ("Snapshot tạo lúc", f"{fmt_local(self.m.get('generated_at')) or NULL_REF} (giờ Việt Nam, UTC+7)"),
            ("Người tạo snapshot", f"mã người dùng {_short(by.get('user_id')) or NULL_REF} · vai trò: "
                                   f"{', '.join(_status(r, ROLE) for r in (by.get('roles') or [])) or NULL_REF}"),
            ("Phiên bản lược đồ", self.m.get("schema_version")),
            ("Mã snapshot", _short(self.m.get("export_id"))),
            ("Mã bản PDF", _short(self.export_id)),
            ("Tình trạng tài liệu", "Không phải chứng nhận — tài liệu hỗ trợ tổng hợp dữ liệu"),
        ]))
        story.append(Spacer(1, 12))
        callout = Table(
            [[_p(COVER_DISCLAIMER, self.s.callout)],
             [_p(self.m.get("disclaimer") or mrv_manifest.DISCLAIMER, self.s.note)],
             [_p(SCIENCE_DISCLAIMER, self.s.note)]],
            colWidths=[self.CONTENT_WIDTH], hAlign="LEFT",
        )
        callout.setStyle(TableStyle([
            ("LINEBEFORE", (0, 0), (0, -1), 2.2, _ACCENT),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(callout)
        warnings = self.m.get("warnings") or []
        story.append(Spacer(1, 10))
        story.append(_p(
            f"Snapshot này ghi nhận {len(warnings)} cảnh báo về dữ liệu chưa đầy đủ (mục Cảnh báo). "
            "Tệp bằng chứng gốc không được nhúng trong PDF.", self.s.note))

    def summary(self, story: list[Any]) -> None:
        self.section("Tóm tắt hồ sơ và mức độ sẵn sàng", story)
        r = self.m.get("readiness") or {}
        missing = r.get("steps_without_evidence") or []
        per_season = (self.m.get("resource_metrics") or {}).get("per_crop_season") or {}
        completeness = []
        for season_id in sorted(per_season):
            flags = (per_season[season_id] or {}).get("data_completeness") or {}
            parts = [f"{COMPLETENESS.get(k, k)}: {'đủ' if v else 'chưa đủ'}" for k, v in sorted(flags.items())]
            completeness.append(f"Vụ {self.season_label(season_id)}: " + (" · ".join(parts) or NULL_REF))
        story.append(_p("Chỉ các con số có trong snapshot. Không có điểm số hay tỷ lệ \"sẵn sàng\" do hệ thống tự đặt ra.", self.s.note))
        story.append(self.kv([
            ("Số bước đã hoàn thành", f"{r.get('completed_steps', NULL_REF)} / {r.get('total_steps', NULL_REF)}"),
            ("Số bước còn lại", r.get("remaining_steps")),
            ("Số tệp bằng chứng", r.get("evidence_count")),
            ("Bước chưa có bằng chứng", ", ".join(f"Bước {n}" for n in missing) if missing else "Không có"),
            ("Kết quả CO₂e", "Có cho mọi vụ trong phạm vi" if r.get("carbon_available") else "Chưa có (xem mục Carbon)"),
            ("Mức đầy đủ dữ liệu tài nguyên", "\n".join(completeness) if completeness else "Chưa có chỉ số tài nguyên trong snapshot"),
        ]))

    def scope(self, story: list[Any]) -> None:
        self.section("Phạm vi", story)
        scope = self.m.get("scope") or {}
        org = scope.get("organization") or {}
        story.append(_p(
            f"Tổ chức: {org.get('name') or NULL_REF} ({org.get('organization_code') or NULL_REF}). "
            "Phân cấp: Tổ chức › Nông hộ › Thửa › Vụ canh tác. Phạm vi tính CO₂e là VỤ CANH TÁC; lô sản xuất "
            "chỉ phục vụ truy xuất nguồn gốc, không phải phạm vi tính carbon.", self.s.body))
        rows = [self.head("Nông hộ", "Thửa · diện tích", "Vụ canh tác · trạng thái · thời gian", "Lô sản xuất (truy xuất)")]
        batches = sorted(scope.get("production_batches") or [], key=lambda b: str(b.get("production_batch_id") or ""))
        for b in batches:
            farm, plot, season = b.get("farm") or {}, b.get("plot") or {}, b.get("crop_season") or {}
            area = fmt_number(plot.get("area_ha"))
            rows.append([
                self.cell(f"{farm.get('farm_code') or NULL_REF}\n{farm.get('name') or ''}".strip()),
                self.cell(f"{plot.get('plot_code') or NULL_REF} · {area + ' ha' if area else NULL_VALUE}"),
                self.cell(f"{season.get('season_code') or NULL_REF} · {_status(season.get('status'), SEASON_STATUS)} · "
                          f"{fmt_date(season.get('started_on')) or NULL_REF} – {fmt_date(season.get('closed_on')) or 'chưa đóng'}"),
                self.cell(b.get("batch_code")),
            ])
        if not batches:
            rows.append([self.cell("Hồ sơ chưa gắn lô sản xuất nào trong snapshot.", muted=True), "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .24, w * .2, w * .38, w * .18]))

    def steps(self, story: list[Any]) -> None:
        self.section("Các bước MRV", story)
        story.append(_p("Trạng thái giữ nguyên như hệ thống ghi nhận (mã gốc trong ngoặc). "
                        "\"Chưa bắt đầu\" không có nghĩa là \"không đạt\".", self.s.note))
        rows = [self.head("Thứ tự", "Bước", "Trạng thái", "Hoàn thành (giờ VN)", "Bằng chứng", "Ghi chú")]
        for step in sorted(self.m.get("steps") or [], key=lambda x: x.get("step_no") or 0):
            rows.append([
                self.cell(step.get("step_no")), self.cell(step.get("name")),
                self.cell(_status(step.get("status"), STEP_STATUS)),
                self.cell(fmt_local(step.get("completed_at"))),
                self.cell(step.get("evidence_count")), self.cell(step.get("notes"), null="—"),
            ])
        if len(rows) == 1:
            rows.append([self.cell("Snapshot không có bước MRV nào.", muted=True), "", "", "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .08, w * .2, w * .2, w * .17, w * .1, w * .25]))

    def evidence(self, story: list[Any]) -> None:
        self.section("Bằng chứng", story)
        story.append(_p("Chỉ liệt kê thông tin mô tả. Tệp bằng chứng gốc (ảnh, tài liệu) KHÔNG được nhúng trong "
                        "PDF này; đường dẫn lưu trữ nội bộ không được in ra.", self.s.body))
        rows = [self.head("Bước", "Loại", "Tên tệp · kiểu", "Tải lên (giờ VN) · người tải", "SHA-256", "Mã tham chiếu")]
        items = sorted(self.m.get("evidence") or [], key=lambda x: (x.get("step_no") or 0, str(x.get("evidence_id") or "")))
        for e in items:
            checksum = (e.get("checksum") or {}).get("value")
            rows.append([
                self.cell(e.get("step_no")), self.cell(e.get("evidence_type")),
                self.cell(f"{e.get('file_name') or NULL_REF} · {e.get('mime_type') or NULL_REF}"),
                self.cell(f"{fmt_local(e.get('uploaded_at')) or NULL_REF} · {_short(e.get('uploaded_by')) or NULL_REF}"),
                _p(checksum, self.s.mono) if checksum else self.cell("Chưa có mã băm", muted=True),
                self.cell(e.get("evidence_id")),
            ])
        if not items:
            rows.append([self.cell("Snapshot không có tệp bằng chứng nào.", muted=True), "", "", "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .07, w * .1, w * .2, w * .19, w * .27, w * .17], long=len(items) > 60))

    def activities(self, story: list[Any]) -> None:
        self.section("Hoạt động canh tác", story)
        acts = self.m.get("activities") or []
        includes_deleted = ((self.m.get("provenance") or {}).get("activities") or {}).get("includes_deleted")
        story.append(_p(
            f"{len(acts)} hoạt động trong snapshot; hoạt động đã xoá mềm "
            f"{'ĐƯỢC' if includes_deleted else 'KHÔNG được'} đưa vào. Bảng dưới chỉ đếm và nêu khoảng thời gian — "
            "không cộng dồn khối lượng, để không tạo con số thứ hai lệch với chỉ số tài nguyên chuẩn. "
            "Chi tiết từng bản ghi ở Phụ lục A.", self.s.body))
        groups: dict[str, list[dict[str, Any]]] = {}
        for a in acts:
            groups.setdefault(str(a.get("activity_type") or "khác"), []).append(a)
        rows = [self.head("Loại hoạt động", "Số bản ghi", "Từ ngày (giờ VN)", "Đến ngày (giờ VN)", "Nguồn ghi nhận")]
        for kind in sorted(groups):
            items = groups[kind]
            times = sorted(str(a.get("occurred_at")) for a in items if a.get("occurred_at"))
            sources: dict[str, int] = {}
            for a in items:
                key = SOURCE.get(str(a.get("source")), str(a.get("source") or NULL_REF))
                sources[key] = sources.get(key, 0) + 1
            rows.append([
                self.cell(_status(kind, ACTIVITY_TYPE)), self.cell(len(items)),
                self.cell(fmt_local(times[0], with_time=False) if times else None),
                self.cell(fmt_local(times[-1], with_time=False) if times else None),
                self.cell(" · ".join(f"{k}: {v}" for k, v in sorted(sources.items()))),
            ])
        if not groups:
            rows.append([self.cell("Snapshot không có hoạt động canh tác nào.", muted=True), "", "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .26, w * .12, w * .17, w * .17, w * .28]))

    def harvest(self, story: list[Any]) -> None:
        self.section("Thu hoạch", story)
        story.append(_p("Giá trị thu hoạch lấy nguyên từ snapshot; đây là mẫu số duy nhất của các chỉ số trên mỗi kg.", self.s.note))
        rows = [self.head("Ngày thu hoạch (giờ VN)", "Sản lượng (kg)", "Diện tích thu hoạch (ha)", "Độ ẩm (%)", "Mã vụ")]
        events = sorted((self.m.get("harvest") or {}).get("events") or [],
                        key=lambda x: (str(x.get("occurred_at") or ""), str(x.get("activity_id") or "")))
        for e in events:
            rows.append([
                self.cell(fmt_local(e.get("occurred_at"))),
                self.cell(fmt_number(e.get("yield_kg")), null=NULL_VALUE),
                self.cell(fmt_number(e.get("harvested_area_ha")), null=NULL_VALUE),
                self.cell(fmt_number(e.get("moisture_percent")), null=NULL_VALUE),
                self.cell(_short(e.get("crop_season_id"))),
            ])
        if not events:
            rows.append([self.cell("Chưa có bản ghi thu hoạch trong snapshot.", muted=True), "", "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .24, w * .18, w * .22, w * .14, w * .22]))

    def resources(self, story: list[Any]) -> None:
        self.section("Chỉ số tài nguyên", story)
        story.append(_p(
            "Giá trị lấy nguyên từ snapshot, không tính lại và không so sánh với ngưỡng chuẩn. Tỷ lệ trên mỗi kg "
            f"hiển thị tối đa {_RATIO_SIG_DIGITS} chữ số có nghĩa; giá trị đầy đủ nằm trong JSON/XLSX. "
            f"\"{NULL_VALUE}\" nghĩa là thiếu số liệu đầu vào — không phải 0.", self.s.note))
        per_season = (self.m.get("resource_metrics") or {}).get("per_crop_season") or {}
        if not per_season:
            story.append(_p("Snapshot không có chỉ số tài nguyên.", self.s.body))
            return
        w = self.CONTENT_WIDTH
        for season_id in sorted(per_season):
            metrics = per_season[season_id] or {}
            flags = metrics.get("data_completeness") or {}
            rows = [self.head("Chỉ số", "Giá trị", "Đơn vị", "Dữ liệu đầu vào")]
            for key, label, unit, flag, ratio in _METRIC_ROWS:
                shown = fmt_number(metrics.get(key), sig=_RATIO_SIG_DIGITS if ratio else None)
                state = flags.get(flag) if flag else None
                rows.append([
                    self.cell(label), self.cell(shown, null=NULL_VALUE), self.cell(unit),
                    self.cell(None if state is None else ("Đủ" if state else "Chưa đủ"), null="—"),
                ])
            # Appended flat, not wrapped in KeepTogether: ReportLab will not chain a
            # keepWithNext heading/note onto a KeepTogether, which stranded the
            # section heading at a page bottom. h2 keeps with its table instead.
            story.append(Paragraph(escape(f"Vụ canh tác {self.season_label(season_id)}"), self.s.h2))
            story.append(_grid(rows, [w * .46, w * .2, w * .14, w * .2]))

    def human(self, text: Any) -> str | None:
        """A snapshot message as a person reads it: seasons by code, other ids
        shortened, status and metric codes as their Vietnamese labels. The JSON
        keeps the message verbatim."""
        if text is None:
            return None
        out = _QUOTED_UUID.sub(lambda m_: self.season_label(m_.group(2)) if self._is_season(m_.group(2))
                               else f"mã {_short(m_.group(2))}", str(text))
        for code, label in {**STEP_STATUS, **COMPLETENESS}.items():
            out = re.sub(rf"(?<![A-Za-z_]){re.escape(code)}(?![A-Za-z_])", label.lower() if code in COMPLETENESS else label, out)
        return out

    def related(self, value: Any) -> str | None:
        if not isinstance(value, dict) or not value:
            return self.human(_compact(value))
        parts = []
        for key, v in sorted(value.items()):
            if key == "crop_season_id":
                parts.append(f"Vụ {self.season_label(v)}")
            elif key == "step_no":
                parts.append(f"Bước {v}")
            elif key == "missing" and isinstance(v, (list, tuple)):
                parts.append("Thiếu: " + ", ".join(COMPLETENESS.get(str(x), str(x)).lower() for x in v))
            elif key == "factor_set_id":
                parts.append(f"Bộ hệ số mã {_short(v)}")
            else:
                parts.append(self.human(_compact(v)) or "")
        return "; ".join(p for p in parts if p)

    def _is_season(self, value: str) -> bool:
        return any(str((b.get("crop_season") or {}).get("crop_season_id")) == value
                   for b in (self.m.get("scope") or {}).get("production_batches") or [])

    def season_label(self, season_id: Any) -> str:
        """`<season code> · <short id>` from the snapshot's own scope; the id alone
        only when the scope does not name the season."""
        for b in (self.m.get("scope") or {}).get("production_batches") or []:
            season = b.get("crop_season") or {}
            if str(season.get("crop_season_id")) == str(season_id) and season.get("season_code"):
                return f"{season['season_code']} · mã {_short(season_id)}"
        return f"mã {_short(season_id)}"

    def carbon(self, story: list[Any]) -> None:
        self.section("Carbon", story)
        story.append(_p(SCIENCE_DISCLAIMER, self.s.note))
        per_season = (self.m.get("carbon") or {}).get("per_crop_season") or {}
        if not per_season:
            story.append(_p("Snapshot không có vụ canh tác nào để báo cáo CO₂e.", self.s.body))
            return
        w = self.CONTENT_WIDTH
        for season_id in sorted(per_season):
            c = per_season[season_id] or {}
            story.append(Paragraph(escape(f"Vụ canh tác {self.season_label(season_id)}"), self.s.h2))
            if c.get("status") != "succeeded":
                reason = CARBON_REASON.get(str(c.get("reason")), c.get("reason") or NULL_REF)
                story.append(self.kv([
                    ("Trạng thái", f"Không có kết quả ({c.get('status') or 'unavailable'})"),
                    ("Diễn giải", "Chưa thể tính CO₂e với bộ dữ liệu/hệ số hiện tại."),
                    ("Lý do ghi trong snapshot", f"{reason} ({c.get('reason') or NULL_REF})"),
                ]))
                continue
            story.append(self.kv([
                ("Trạng thái", _status(c.get("status"), {"succeeded": "Đã tính"})),
                ("Tổng CO₂e", f"{fmt_number(c.get('total_co2e_kg')) or NULL_VALUE} kgCO₂e"),
                ("CO₂e trên mỗi kg", f"{fmt_number(c.get('co2e_per_kg'), sig=_RATIO_SIG_DIGITS) or NULL_VALUE} kgCO₂e/kg"),
                ("Sản lượng dùng khi tính", f"{fmt_number(c.get('yield_kg')) or NULL_VALUE} kg"),
                ("Mã bản tính", _short(c.get("calculation_id"))),
                ("Thời điểm tính (giờ VN)", fmt_local(c.get("calculated_at"))),
                ("Loại kết quả", _status(c.get("calculation_kind"), CALCULATION_KIND)),
                ("Kịch bản", _status(c.get("scenario"), SCENARIO)),
                ("Phiên bản engine · bậc phương pháp", f"{c.get('engine_version') or NULL_REF} · Tier {c.get('methodology_tier') or NULL_REF}"),
                ("Phiên bản bộ hệ số", c.get("ef_config_version") or "Không đọc được phiên bản (xem mục Nguồn gốc hệ số)"),
            ]))
            breakdown = sorted(c.get("breakdown") or [], key=lambda b: (
                str(b.get("category") or ""), str(b.get("gas") or ""), str(b.get("emission_factor_id") or "")))
            rows = [self.head("Hạng mục", "Khí", "Giá trị hoạt động", "Hệ số áp dụng", "Khí (kg)", "CO₂e (kg)", "Công thức")]
            for b in breakdown:
                rows.append([
                    self.cell(_status(b.get("category"), CATEGORY)), self.cell(b.get("gas")),
                    self.cell(f"{fmt_number(b.get('activity_value')) or NULL_VALUE} {b.get('activity_unit') or ''}".strip()),
                    self.cell(fmt_number(b.get("factor_value_used")), null=NULL_VALUE),
                    self.cell(fmt_number(b.get("gas_kg")), null=NULL_VALUE),
                    self.cell(fmt_number(b.get("co2e_kg")), null=NULL_VALUE),
                    self.cell(b.get("formula_expression"), null="—"),
                ])
            if len(rows) == 1:
                rows.append([self.cell("Bản tính không kèm chi tiết theo hạng mục.", muted=True), "", "", "", "", "", ""])
            story.append(Spacer(1, 4))
            story.append(_grid(rows, [w * .15, w * .07, w * .16, w * .13, w * .12, w * .13, w * .24]))

    def provenance(self, story: list[Any]) -> None:
        self.section("Nguồn gốc hệ số và phạm vi dữ liệu", story)
        prov = self.m.get("provenance") or {}
        acts = prov.get("activities") or {}
        story.append(self.kv([
            ("Phạm vi tính carbon", prov.get("carbon_scope")),
            ("Bao gồm hoạt động đã xoá", _compact(acts.get("includes_deleted"))),
            ("Kèm tệp bằng chứng gốc", _compact(prov.get("evidence_binaries_included"))),
            ("Bảng nguồn hoạt động", _compact(acts.get("source_tables"))),
        ]))
        sets = sorted(prov.get("emission_factor_sets") or [], key=lambda x: str(x.get("factor_set_id") or ""))
        if not sets:
            story.append(Spacer(1, 6))
            story.append(self.kv([
                ("factor_provenance_unavailable",
                 "Snapshot không kèm nguồn gốc hệ số phát thải: chưa có bản tính CO₂e nào liên kết tới một bộ "
                 "hệ số. Không có trích dẫn nguồn nào được bổ sung ngoài dữ liệu hệ thống ghi nhận."),
            ]))
            return
        w = self.CONTENT_WIDTH
        for fs in sets:
            story.append(Paragraph(escape(f"Bộ hệ số {fs.get('version_code') or fs.get('factor_set_id')}"), self.s.h2))
            story.append(self.kv([
                ("Tên", fs.get("name")),
                ("Phương pháp luận", f"{fs.get('methodology_name') or NULL_REF} · {fs.get('methodology_version') or NULL_REF}"),
                ("Nguồn", f"{fs.get('source_name') or NULL_REF} · {fs.get('source_url') or NULL_REF}"),
                ("Trạng thái bộ hệ số", _status(fs.get("status"), {"published": "Đã công bố", "draft": "Nháp", "retired": "Ngừng dùng"})),
                ("Hiệu lực", f"{fmt_date(fs.get('valid_from')) or NULL_REF} – {fmt_date(fs.get('valid_to')) or 'không giới hạn'}"),
            ]))
            rows = [self.head("Mã hệ số", "Hạng mục · khí", "Giá trị", "Đơn vị", "Tham chiếu nguồn", "Đối chiếu")]
            for f in sorted(fs.get("factors") or [], key=lambda x: str(x.get("factor_code") or "")):
                rows.append([
                    self.cell(f.get("factor_code")), self.cell(f"{_status(f.get('category'), CATEGORY)} · {f.get('gas') or NULL_REF}"),
                    self.cell(fmt_number(f.get("factor_value")), null=NULL_VALUE),
                    self.cell(f"{f.get('activity_unit') or '?'} › {f.get('result_unit') or '?'}"),
                    self.cell(f.get("source_reference"), null="Không ghi nguồn"),
                    self.cell(f.get("verification_status"), null="Không rõ"),
                ])
            if len(rows) == 1:
                rows.append([self.cell("Bộ hệ số không kèm hệ số chi tiết trong snapshot.", muted=True), "", "", "", "", ""])
            story.append(Spacer(1, 4))
            story.append(_grid(rows, [w * .17, w * .19, w * .12, w * .17, w * .21, w * .14]))

    def warnings(self, story: list[Any]) -> None:
        self.section("Cảnh báo", story)
        items = self.m.get("warnings") or []
        story.append(_p(f"Toàn bộ {len(items)} cảnh báo trong snapshot, không lược bớt. Mức độ giữ nguyên; "
                        "\"Thông tin\" là dữ liệu chưa đầy đủ, không phải lỗi. Mã đầy đủ của từng cảnh báo "
                        "có trong JSON/XLSX của cùng snapshot.", self.s.note))
        order = {"warning": 0, "info": 1}
        rows = [self.head("Mức độ", "Mã", "Nội dung", "Liên quan")]
        for w_ in sorted(items, key=lambda x: (order.get(str(x.get("severity")), 2), str(x.get("code") or ""),
                                                json.dumps(x.get("related") or {}, sort_keys=True))):
            rows.append([
                self.cell(_status(w_.get("severity"), SEVERITY)), self.cell(_status(w_.get("code"), WARNING_CODE)),
                self.cell(self.human(w_.get("message"))), self.cell(self.related(w_.get("related")), null="—"),
            ])
        if not items:
            rows.append([self.cell("Không có cảnh báo nào.", muted=True), "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .11, w * .3, w * .35, w * .24], long=len(items) > 60))

    def integrity(self, story: list[Any]) -> None:
        self.section("Tính toàn vẹn và siêu dữ liệu gói", story)
        integ = self.m.get("package_integrity") or {}
        digest = integ.get("manifest_sha256")
        story.append(self.kv([
            ("Phiên bản lược đồ", self.m.get("schema_version")),
            ("Mã snapshot nguồn", _short(self.m.get("export_id"))),
            ("Mã bản PDF", _short(self.export_id)),
            ("Mã băm SHA-256 của snapshot", _p(digest, self.s.mono) if digest else None),
            ("Thuật toán · phạm vi băm", f"{integ.get('algorithm') or NULL_REF} · {integ.get('canonical_over') or NULL_REF}"),
            ("Cách chuẩn hoá", integ.get("canonical_form")),
            ("Snapshot tạo lúc (UTC)", self.m.get("generated_at")),
            ("PDF kết xuất lúc (UTC)", mrv_manifest.iso_utc(self.rendered_at) if self.rendered_at else None),
            ("SHA-256 của tệp PDF",
             "Ghi trong hồ sơ xuất và được kiểm tra mỗi lần tải về. Một tệp không thể chứa mã băm của chính nó."),
        ], label_width=62 * mm))
        story.append(Spacer(1, 6))
        story.append(_p(
            "PDF này được kết xuất từ đúng snapshot có mã băm trên, không truy vấn lại dữ liệu nguồn và không tính "
            "lại CO₂e hay chỉ số tài nguyên. JSON, XLSX và PDF của cùng snapshot mô tả cùng một trạng thái dữ liệu. "
            "Tài liệu không chứa kho lưu trữ, đường dẫn đối tượng hay liên kết tải có chữ ký.", self.s.note))

    def activity_appendix(self, story: list[Any]) -> None:
        acts = sorted(self.m.get("activities") or [],
                      key=lambda a: (str(a.get("occurred_at") or ""), str(a.get("activity_id") or "")))
        story.append(PageBreak())
        story.append(Paragraph("Phụ lục A&nbsp;&nbsp;Chi tiết hoạt động canh tác", self.s.h1))
        shown = acts[:ACTIVITY_APPENDIX_LIMIT]
        note = f"{len(acts)} bản ghi, sắp theo thời điểm."
        if len(acts) > len(shown):
            note += (f" Chỉ in {len(shown)} bản ghi đầu; {len(acts) - len(shown)} bản ghi còn lại có đầy đủ "
                     "trong JSON/XLSX của cùng snapshot.")
        story.append(_p(note + f" Ô trống nghĩa là không có số liệu. Thời điểm theo giờ Việt Nam (UTC+7).", self.s.note))
        rows = [self.head("Thời điểm", "Loại", "Giá trị ghi nhận", "Nguồn · người ghi", "Ghi chú")]
        labels = {key: label for key, label, _ in _ACTIVITY_DETAIL_COLUMNS}
        kinds = {key: kind for key, _, kind in _ACTIVITY_DETAIL_COLUMNS}
        for a in shown:
            detail = a.get("detail") or {}
            values = []
            for key in [k for k, _, _ in _ACTIVITY_DETAIL_COLUMNS] + sorted(set(detail) - set(labels)):
                if key in _DETAIL_SKIP or detail.get(key) is None or detail.get(key) == "":
                    continue
                raw = detail[key]
                value = fmt_number(raw) if kinds.get(key) == "num" else _compact(raw)
                values.append(f"{labels.get(key, key)}: {value}")
            rows.append([
                self.cell(fmt_local(a.get("occurred_at"))),
                self.cell(_status(a.get("activity_type"), ACTIVITY_TYPE)),
                self.cell("; ".join(values), null="—"),
                self.cell(f"{SOURCE.get(str(a.get('source')), a.get('source') or NULL_REF)} · {_short(a.get('recorded_by')) or NULL_REF}"),
                self.cell(a.get("note"), null="—"),
            ])
        if not shown:
            rows.append([self.cell("Snapshot không có hoạt động canh tác nào.", muted=True), "", "", "", ""])
        w = self.CONTENT_WIDTH
        story.append(_grid(rows, [w * .16, w * .16, w * .38, w * .16, w * .14], long=len(shown) > 60))


class _Chrome:
    """Header and footer. Carries no path, bucket, token or URL."""

    def __init__(self, manifest: dict[str, Any], export_id: str | None):
        case = manifest.get("case") or {}
        self.case_code = _nfc(case.get("case_code") or NULL_REF)
        self.snapshot_day = fmt_local(manifest.get("generated_at"), with_time=False) or NULL_REF
        self.short_id = _short(export_id) or _short(manifest.get("export_id")) or NULL_REF

    def draw(self, c: rl_canvas.Canvas, total: int) -> None:
        width, height = A4
        left, right = 18 * mm, width - 18 * mm
        c.saveState()
        c.setStrokeColor(_RULE)
        c.setLineWidth(0.5)
        c.setFont(_SANS_SEMI, 8)
        c.setFillColor(_ACCENT)
        c.drawString(left, height - 12 * mm, "AgriCarbon")
        c.setFont(_SANS, 7.6)
        c.setFillColor(_MUTED)
        c.drawRightString(right, height - 12 * mm, f"{self.case_code} · Gói báo cáo MRV")
        c.line(left, height - 14 * mm, right, height - 14 * mm)
        c.line(left, 13 * mm, right, 13 * mm)
        c.drawString(left, 9 * mm, f"Snapshot {self.snapshot_day} · Bản PDF {self.short_id} · Tài liệu hỗ trợ, không phải chứng nhận")
        c.drawRightString(right, 9 * mm, f"Trang {c.getPageNumber()} / {total}")
        c.restoreState()


class _ReportCanvas(rl_canvas.Canvas):
    """Two-pass canvas so every footer can say 'Trang X / Y'."""

    def __init__(self, *args: Any, chrome: _Chrome, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._chrome = chrome
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 - ReportLab API
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._chrome.draw(self, total)
            super().showPage()
        super().save()


def render_pdf(
    manifest: dict[str, Any], *, export_id: str | None = None, rendered_at: datetime | None = None,
) -> bytes:
    """Manifest -> PDF bytes. The manifest is the only source of business data."""
    if not isinstance(manifest, dict) or not manifest.get("schema_version"):
        raise ValueError("not an MRV manifest")
    if not str(manifest["schema_version"]).startswith("1."):
        # Fail honestly rather than mis-render a shape this renderer never saw.
        raise ValueError(f"unsupported manifest schema_version {manifest['schema_version']!r}")
    _register_fonts()

    case = manifest.get("case") or {}
    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
        title=_nfc(f"Gói báo cáo MRV — {case.get('case_code') or ''}"),
        author="AgriCarbon", creator="AgriCarbon MRV export",
        subject="MRV evidence report — snapshot dữ liệu hỗ trợ, không phải chứng nhận",
        invariant=1,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])
    chrome = _Chrome(manifest, export_id)
    story = _Report(manifest, export_id, rendered_at).build()
    doc.build(story, canvasmaker=lambda *a, **k: _ReportCanvas(*a, chrome=chrome, **k))
    return buffer.getvalue()


def report_filename(case_code: str, generated_at: Any, export_id: str) -> str:
    """Same deterministic, ASCII, header-safe shape as the other formats."""
    day = mrv_manifest.iso_date(generated_at) or "undated"
    return f"agricarbon-mrv-{mrv_manifest._slug(case_code)}-{day}-{str(export_id)[:8]}.pdf"
