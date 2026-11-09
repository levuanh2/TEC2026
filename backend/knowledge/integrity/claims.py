"""Conservative, rule-based extraction of CHECKABLE statements from chunk text.

What it extracts (each with the exact character span in the chunk content):
- quantity:  a number or range followed by a known unit ("15 cm", "1,5–2 tấn/ha", "từ 5 đến 7 ngày").
             The unit is normalized to a canonical unit of one dimension (mm -> cm, tuần -> day,
             tấn/ha -> kg/ha). The parameter comes from cue words in the same sentence. When no
             parameter of that dimension is cued, the claim stays `ambiguous` and gets no parameter.
             A number followed by a recognised but unsupported unit (lít, giờ, ha, ...) is
             `unsupported`. A bare number without a unit is not extracted.
- date:      dd/mm/yyyy or "ngày d tháng m năm yyyy"; an "effective from/to" cue in the sentence
             sets the parameter. An invalid calendar date is `ambiguous`.
- stage:     a crop-stage mention (trổ bông, đẻ nhánh, ...); quantities in the same sentence
             carry it as `stage` scope.
- assertion: a short, fixed list of absolute qualitative statements (methane emission ends;
             water records unnecessary). This list is deliberately small and NOT a general
             falsehood detector: an unlisted false statement produces no claim.

Number conventions (Vietnamese text): "1,5" is 1.5. A dot followed by exactly three digits
("1.000") is ambiguous (thousands separator or decimal) and is reported, never guessed. More than
one separator is ambiguous too. Nothing here invents a canonical value.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from knowledge.ids import sha256_hex

CLAIM_EXTRACTOR_VERSION = "kn-claims-1"

ClaimKind = Literal["quantity", "date", "stage", "assertion"]
ClaimStatus = Literal["extracted", "ambiguous", "unsupported"]

# canonical unit -> dimension
UNITS: dict[str, str] = {
    "cm": "length", "day": "duration", "kg/ha": "areal_mass", "m3/ha": "areal_volume",
    "percent": "ratio", "kgCH4/ha/day": "emission_rate",
}

# raw unit (regex, longest first) -> (canonical unit, factor to canonical)
_UNIT_FORMS: tuple[tuple[str, str, float], ...] = (
    (r"kg\s?ch4\s?/\s?ha\s?/\s?(?:ngày|day)", "kgCH4/ha/day", 1.0),
    (r"m(?:3|³)\s?/\s?ha", "m3/ha", 1.0),
    (r"(?:tấn|t)\s?/\s?ha", "kg/ha", 1000.0),
    (r"kg\s?n\s?/\s?ha", "kg/ha", 1.0),
    (r"kg\s?/\s?ha", "kg/ha", 1.0),
    (r"cm", "cm", 1.0),
    (r"mm", "cm", 0.1),
    (r"ngày|days?", "day", 1.0),
    (r"tuần|weeks?", "day", 7.0),
    (r"%|phần trăm|percent", "percent", 1.0),
)
_UNSUPPORTED_UNITS = r"lít|lit|l/ha|g/ha|kg|g|giờ|hours?|h|ha|mét|m|tháng|năm"

# parameter -> (dimension, cue groups; every group needs one of its cues in the sentence).
# Order matters: the first parameter whose cues match AND whose dimension equals the unit's wins.
PARAMETERS: dict[str, tuple[str, tuple[tuple[str, ...], ...]]] = {
    "water.awd.dry_down_depth": ("length", (("mực nước", "water level"),
                                            ("dưới mặt", "below the soil", "below soil", "below the surface"))),
    "water.flood_depth": ("length", (("mực nước", "water level", "ngập", "giữ nước", "flood"),)),
    "water.awd.irrigation_interval": ("duration", (("tưới lại", "lần tưới", "giữa các lần", "re-irrigat", "irrigation interval"),)),
    "ch4.reduction": ("ratio", (("giảm", "reduc"), ("phát thải", "mê-tan", "metan", "methane", "ch4", "khí nhà kính"))),
    "fertilizer.n_rate": ("areal_mass", (("đạm", "urê", "ure", "nitrogen"),)),
    "fertilizer.rate": ("areal_mass", (("phân", "fertili"),)),
    "yield": ("areal_mass", (("năng suất", "sản lượng", "yield"),)),
    "water.volume": ("areal_volume", (("nước", "water"),)),
    "ch4.emission_factor": ("emission_rate", (("mê-tan", "metan", "methane", "ch4"),)),
}

# qualitative assertion parameter -> description (the registry states whether it holds)
ASSERTIONS: dict[str, str] = {
    "ch4.rice.emission_eliminated": "methane emission from the field ends / is zero",
    "records.water.not_required": "water / irrigation records no longer need to be kept",
}

DATE_PARAMETERS = ("document.effective_from", "document.effective_to", "date.mentioned")

STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flowering", ("trổ bông", "trỗ bông", "flowering", "heading")),
    ("panicle_initiation", ("làm đòng", "panicle initiation")),
    ("tillering", ("đẻ nhánh", "tillering")),
    ("ripening", ("lúa chín", "giai đoạn chín", "chín sáp", "ripening")),
    ("establishment", ("gieo sạ", "cấy lúa", "sowing", "transplant")),
)

_AWD = ("ngập khô xen kẽ", "awd", "alternate wetting")
_NUM = r"\d+(?:[.,]\d+)*"
_QUANTITY = re.compile(
    rf"(?<![\w.,])(?:từ\s+|from\s+)?(?P<a>{_NUM})(?:\s*(?:-|–|—|đến|tới|to)\s*(?P<b>{_NUM}))?\s*"
    rf"(?P<unit>{'|'.join(f'(?:{form})' for form, _, _ in _UNIT_FORMS)}|{_UNSUPPORTED_UNITS})(?![\w/])",
    re.IGNORECASE)
_DATES = (
    re.compile(r"(?<![\d/])(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})(?![\d/])"),
    re.compile(r"ngày\s+(?P<d>\d{1,2})\s+tháng\s+(?P<m>\d{1,2})\s+năm\s+(?P<y>\d{4})", re.IGNORECASE),
)
_EMISSION = r"(?:phát thải|mê-tan|metan|khí nhà kính|methane|emission)"
_WATER_RECORD = r"(?:mực nước|lượng nước|nước tưới|số liệu tưới|số liệu nước|water level|water record|irrigation record)"
_ASSERTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("ch4.rice.emission_eliminated", re.compile(
        rf"(?<!không )(?<!chưa )(?:không còn|hết|chấm dứt|loại bỏ hoàn toàn|triệt tiêu)\s+(?:\S+\s+){{0,2}}?{_EMISSION}"
        rf"|{_EMISSION}\s+(?:\S+\s+){{0,3}}?(?:bằng không|bằng 0|= ?0)(?!\S)"
        rf"|(?:eliminat\w*|ends?|zero)\s+(?:\w+\s+){{0,2}}?{_EMISSION}"
        rf"|no longer emits?", re.IGNORECASE)),
    ("records.water.not_required", re.compile(
        rf"(?:không cần|khỏi cần|không phải|no need to|need not|not required to)\s+(?:\S+\s+){{0,2}}?"
        rf"(?:ghi chép|ghi|theo dõi|đo|record|log|measure)\s+(?:\S+\s+){{0,3}}?{_WATER_RECORD}", re.IGNORECASE)),
)
_SENTENCE_END = re.compile(r"[.!?;](?=\s|$)|\n")


@dataclass(frozen=True)
class ClaimSource:
    document_ref: str          # e.g. "source-id/document-id@version"
    chunk_id: str
    content: str


@dataclass(frozen=True)
class Claim:
    claim_id: str
    document_ref: str
    chunk_id: str
    start: int                 # character span in the chunk content: content[start:end] == text
    end: int
    text: str
    kind: ClaimKind
    status: ClaimStatus
    parameter: str | None = None
    value_min: float | None = None
    value_max: float | None = None
    unit: str | None = None    # canonical unit (UNITS)
    dimension: str | None = None
    date_iso: str | None = None
    stage: str | None = None
    scope: tuple[str, ...] = ()
    note: str = ""


def _number(token: str) -> float | None:
    """Vietnamese-first parsing; None = ambiguous (never guessed)."""
    seps = re.findall(r"[.,]", token)
    if not seps:
        return float(token)
    if len(seps) > 1:
        return None
    whole, frac = re.split(r"[.,]", token)
    if seps[0] == "." and len(frac) == 3:
        return None
    return float(f"{whole}.{frac}")


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _has(sentence: str, cues: tuple[str, ...]) -> bool:
    return any(cue in sentence for cue in cues)


def _stage(sentence: str) -> str | None:
    return next((name for name, cues in STAGES if _has(sentence, cues)), None)


def _unit(raw: str) -> tuple[str, float] | None:
    for form, canonical, factor in _UNIT_FORMS:
        if re.fullmatch(form, raw, re.IGNORECASE):
            return canonical, factor
    return None


def _parameter(sentence: str, dimension: str) -> str | None:
    for key, (dim, groups) in PARAMETERS.items():
        if dim == dimension and all(_has(sentence, group) for group in groups):
            return key
    return None


def _claim(source: ClaimSource, start: int, end: int, kind: ClaimKind, status: ClaimStatus, **fields) -> Claim:
    claim_id = "cl-" + sha256_hex(f"{source.document_ref}|{source.chunk_id}|{start}|{end}|{kind}")[:16]
    return Claim(claim_id, source.document_ref, source.chunk_id, start, end, source.content[start:end], kind, status,
                 **fields)


def extract_claims(source: ClaimSource) -> tuple[Claim, ...]:
    text = unicodedata.normalize("NFC", source.content)
    if text != source.content:
        source = ClaimSource(source.document_ref, source.chunk_id, text)
    claims: list[Claim] = []
    for s_start, s_end in _sentences(text):
        sentence = text[s_start:s_end].casefold()
        stage = _stage(sentence)
        scope = ("awd",) if _has(sentence, _AWD) else ()
        if stage:
            cue = next(c for name, cues in STAGES if name == stage for c in cues if c in sentence)
            m = re.compile(re.escape(cue), re.IGNORECASE).search(text, s_start, s_end)
            if m:
                claims.append(_claim(source, m.start(), m.end(), "stage", "extracted", stage=stage, scope=scope))

        date_spans = [(m.start(), m.end()) for pattern in _DATES for m in pattern.finditer(text, s_start, s_end)]
        for m in _QUANTITY.finditer(text, s_start, s_end):
            if any(m.start() < d_end and d_start < m.end() for d_start, d_end in date_spans):
                continue        # "ngày 5 tháng 3 năm 2026" is a date, not "5 tháng" + "3 năm"
            unit = _unit(m.group("unit"))
            if unit is None:
                claims.append(_claim(source, m.start(), m.end(), "quantity", "unsupported", stage=stage, scope=scope,
                                     note=f"unit {m.group('unit')!r} is not supported"))
                continue
            canonical, factor = unit
            a, b = _number(m.group("a")), _number(m.group("b")) if m.group("b") else None
            dimension = UNITS[canonical]
            if a is None or (m.group("b") and b is None):
                claims.append(_claim(source, m.start(), m.end(), "quantity", "ambiguous", unit=canonical,
                                     dimension=dimension, stage=stage, scope=scope,
                                     note="number format is ambiguous (thousands separator or decimal)"))
                continue
            low, high = (a, b) if b is not None else (a, a)
            low, high = sorted((round(low * factor, 6), round(high * factor, 6)))
            parameter = _parameter(sentence, dimension)
            if re.fullmatch(r"kg\s?n\s?/\s?ha", m.group("unit"), re.IGNORECASE):
                parameter = "fertilizer.n_rate"      # the unit itself names nitrogen
            claims.append(_claim(source, m.start(), m.end(), "quantity", "extracted" if parameter else "ambiguous",
                                 parameter=parameter, value_min=low, value_max=high, unit=canonical,
                                 dimension=dimension, stage=stage, scope=scope,
                                 note="" if parameter else "no parameter cue of this dimension in the sentence"))

        for pattern in _DATES:
            for m in pattern.finditer(text, s_start, s_end):
                try:
                    iso = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
                except ValueError:
                    claims.append(_claim(source, m.start(), m.end(), "date", "ambiguous", note="not a calendar date"))
                    continue
                prefix = sentence[: m.start() - s_start]
                if _has(sentence, ("hiệu lực", "effective")):
                    ends = _has(prefix, ("đến", "hết", "until", "to "))
                    parameter = "document.effective_to" if ends else "document.effective_from"
                else:
                    parameter = "date.mentioned"
                claims.append(_claim(source, m.start(), m.end(), "date", "extracted", parameter=parameter, date_iso=iso))

        for parameter, pattern in _ASSERTION_PATTERNS:
            for m in pattern.finditer(text, s_start, s_end):
                claims.append(_claim(source, m.start(), m.end(), "assertion", "extracted",
                                     parameter=parameter, stage=stage, scope=scope))
    return tuple(sorted(claims, key=lambda c: (c.start, c.end, c.kind)))
