"""Conservative, rule-based extraction of CHECKABLE statements from chunk text.

What it extracts, each with the exact character span in the chunk content:
- quantity:  a number or range followed by a known unit ("15 cm", "1,5–2 tấn/ha", "từ 5 đến 7 ngày",
             "120 kg N/ha/vụ"). The unit is normalized to one canonical unit per dimension (mm, m -> cm;
             tuần -> day; tấn/ha, tạ/ha -> kg/ha). The parameter comes from cue words in the same
             sentence: the nearest cue of a parameter of that dimension wins, and exclusion cues (bund,
             pipe, length) leave it unassigned. Without a parameter the claim stays `ambiguous`. A
             number followed by a recognised but unsupported unit (lít, giờ, ha, ...) is `unsupported`.
             A bare number without a unit is not extracted.
- date:      dd/mm/yyyy, yyyy-mm-dd or "ngày d tháng m năm yyyy". An "effective" cue sets
             effective_from or effective_to. An invalid calendar date is `ambiguous`. US mm/dd/yyyy is
             NOT recognised (it is read as dd/mm).
- stage:     every crop-stage mention (trổ bông, đẻ nhánh, ...). A quantity carries the stage whose cue
             is nearest to it in the same sentence.
- assertion: a short, fixed list of absolute qualitative statements (field methane emission ends or
             reaches zero, including a >= 100 % reduction; water records are not needed). This list is
             deliberately small and NOT a general falsehood detector. An unlisted false statement
             produces no claim.

Matching runs on a diacritic-folded copy of the text ("không" -> "khong", "đ" -> "d"). The fold
maps one character to one character, so spans stay exact for both accented and unaccented text.
Spans index the NFC form of the content. Ingestion chunks are already NFC (normalize.py).

Numbers (Vietnamese first): "1,5" is 1.5 and "0.125" is 0.125. One separator followed by exactly
three digits ("1.000", "1,500") is ambiguous (thousands separator or decimal), as is more than one
separator. A leading minus sign ("-15 cm") is ambiguous (sign convention unknown). Nothing is
guessed and no canonical value is invented.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from knowledge.ids import sha256_hex

CLAIM_EXTRACTOR_VERSION = "kn-claims-2"

ClaimKind = Literal["quantity", "date", "stage", "assertion"]
ClaimStatus = Literal["extracted", "ambiguous", "unsupported"]


def _fold(text: str) -> str:
    """Strip Vietnamese diacritics, one character in -> one character out (keeps spans exact)."""
    out = []
    for ch in text:
        if ch in "đĐ":
            out.append("d" if ch == "đ" else "D")
        else:
            out.append(unicodedata.normalize("NFD", ch)[0])
    return "".join(out)


def _low(text: str) -> str:
    """Folded + lowercased, for cue tests (no spans are taken from it)."""
    return _fold(text).lower()


def _rx(pattern: str) -> re.Pattern:
    """Compile a pattern written with diacritics against folded text (case-insensitive)."""
    return re.compile(_fold(pattern), re.IGNORECASE)


# canonical unit -> dimension
UNITS: dict[str, str] = {
    "cm": "length", "day": "duration", "kg/ha": "areal_mass", "m3/ha": "areal_volume",
    "percent": "ratio", "kgCH4/ha/day": "emission_rate",
}

_PER_SEASON = r"(?:\s?/\s?(?:vụ|season|crop))?"
# raw unit (regex) -> (canonical unit, factor to canonical)
_UNIT_FORMS: tuple[tuple[str, str, float], ...] = (
    (r"kg\s?ch4\s?/\s?ha\s?/\s?(?:ngày|day)", "kgCH4/ha/day", 1.0),
    (rf"m(?:3|³)\s?/\s?ha{_PER_SEASON}", "m3/ha", 1.0),
    (rf"tấn\s?/\s?ha{_PER_SEASON}", "kg/ha", 1000.0),
    (rf"tạ\s?/\s?ha{_PER_SEASON}", "kg/ha", 100.0),
    (rf"t\s?/\s?ha{_PER_SEASON}", "kg/ha", 1000.0),
    (rf"kg\s?n\s?/\s?ha{_PER_SEASON}", "kg/ha", 1.0),
    (rf"kg\s?/\s?ha{_PER_SEASON}", "kg/ha", 1.0),
    (r"cm", "cm", 1.0),
    (r"mm", "cm", 0.1),
    (r"m|mét", "cm", 100.0),
    (r"ngày|days?", "day", 1.0),
    (r"tuần|weeks?", "day", 7.0),
    (r"%|phần trăm|percent", "percent", 1.0),
)
_UNIT_RX = tuple((_rx(form), canonical, factor) for form, canonical, factor in _UNIT_FORMS)
_N_UNIT = _rx(rf"kg\s?n\s?/\s?ha{_PER_SEASON}")
_UNSUPPORTED_UNITS = r"lít|l/ha|g/ha|kg|g|giờ|hours?|h|ha|tháng|năm|months?|years?"

# parameter -> (dimension, cue groups (each group needs one cue), exclusion cues).
# A cue ending in "*" is a word prefix; any other cue must be a whole word or phrase.
PARAMETERS: dict[str, tuple[str, tuple[tuple[str, ...], ...], tuple[str, ...]]] = {
    "water.awd.dry_down_depth": ("length", (("mực nước", "water level*"),
                                            ("dưới mặt", "below the soil", "below soil", "below the surface")),
                                 ("bờ", "ống", "dài", "chiều cao", "bund*", "pipe*", "tube*", "long")),
    "water.flood_depth": ("length", (("mực nước", "giữ nước", "water level*", "flood depth"),),
                          ("bờ", "ống", "dài", "chiều cao", "bund*", "pipe*", "tube*", "long")),
    "water.awd.irrigation_interval": ("duration", (("tưới lại", "lần tưới", "giữa các lần", "re-irrigat*",
                                                    "irrigation interval*"),), ()),
    "ch4.reduction": ("ratio", (("giảm", "reduc*"),
                                ("phát thải", "mê-tan", "metan", "methane", "ch4", "khí nhà kính")), ()),
    "fertilizer.n_rate": ("areal_mass", (("đạm", "urê", "nitrogen"),), ()),
    "fertilizer.rate": ("areal_mass", (("phân bón", "bón", "fertili*"),), ()),
    "yield": ("areal_mass", (("năng suất", "sản lượng", "yield*"),), ()),
    "water.volume": ("areal_volume", (("nước", "water"),), ()),
    "ch4.emission_factor": ("emission_rate", (("mê-tan", "metan", "methane", "ch4"),), ()),
}
_TIE_CHARS = 12          # cues this close count as equally near; the earlier (more specific) parameter wins

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
    ("establishment", ("gieo sạ", "cấy lúa", "sowing", "transplant*")),
)

_AWD = ("ngập khô xen kẽ", "awd", "alternate wetting")
_NUM = r"\d+(?:[.,]\d+)*"
_QUANTITY = re.compile(
    rf"(?<![\w.,])(?:{_fold('từ')}\s+|from\s+)?(?P<a>{_NUM})(?:\s*(?:-|–|—|{_fold('đến')}|{_fold('tới')}|to)\s*"
    rf"(?P<b>{_NUM}))?\s*(?P<unit>{'|'.join(f'(?:{_fold(f)})' for f, _, _ in _UNIT_FORMS)}|{_fold(_UNSUPPORTED_UNITS)})"
    rf"(?![\w/])", re.IGNORECASE)
_DATES = (
    (re.compile(r"(?<![\d/])(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})(?![\d/])"), "dmy"),
    (re.compile(r"(?<![\d-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\d-])"), "iso"),
    (_rx(r"ngày\s+(?P<d>\d{1,2})\s+tháng\s+(?P<m>\d{1,2})\s+năm\s+(?P<y>\d{4})"), "vi"),
)

_EMISSION = r"(?:phát thải|mê-tan|metan|khí nhà kính|methane|emissions?)"
_WATER_RECORD = (r"(?:mực nước|lượng nước|nước tưới|số liệu tưới|số liệu nước|nhật ký tưới|sổ tưới|water levels?|"
                 r"water records?|irrigation (?:records?|logs?))")
_RECORD_VERB = r"(?:ghi chép|ghi|theo dõi|đo|records?|log|measure|keep)"
_NOT_BEFORE = r"(?<!không )(?<!chẳng )(?<!chưa )"
_ASSERTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("ch4.rice.emission_eliminated", _rx(
        rf"{_NOT_BEFORE}(?:không còn|chẳng còn|hổng còn)\s+(?:\S+\s+){{0,4}}?{_EMISSION}"
        rf"|{_NOT_BEFORE}\b(?:hết|chấm dứt|triệt tiêu|dừng hẳn|ngưng hẳn|cắt đứt)\s+(?:hoàn toàn\s+)?{_EMISSION}"
        rf"|{_NOT_BEFORE}\b(?:loại bỏ|xóa bỏ|cắt đứt|triệt tiêu|chấm dứt)\s+hoàn toàn\s+(?:\S+\s+){{0,2}}?{_EMISSION}"
        rf"|{_EMISSION}\s+(?:\S+\s+){{0,4}}?(?:bằng không|bằng 0|về 0|về không|xuống 0|= ?0)(?!\w)"
        rf"|{_EMISSION}\s+(?:\S+\s+){{0,4}}?(?:chấm dứt|dừng hẳn|ngưng hẳn|biến mất)\b"
        rf"|\b(?:eliminat\w*|ends?|stops?|zeroe?s?)\s+(?:all\s+|the\s+|field\s+)?(?:methane|ch4)\b"
        rf"|\b(?:methane|ch4)(?:\s+emissions?)?\s+(?:\w+\s+){{0,3}}?(?:reduced to zero|(?:is|are|drops?|falls?) "
        rf"(?:to )?zero|eliminated|ceases?|stops?)\b"
        rf"|\bno longer emits?\b")),
    ("records.water.not_required", _rx(
        rf"(?:không cần|khỏi cần|không phải|không bắt buộc|no need to|need not|not required to|do not need to|"
        rf"don't need to)\s+(?!chỉ\s|only\s)(?:phải\s+)?(?:\S+\s+){{0,2}}?{_RECORD_VERB}\s+(?:\S+\s+){{0,3}}?"
        rf"{_WATER_RECORD}"
        rf"|\b(?:bỏ qua|miễn)\s+(?:việc\s+)?{_RECORD_VERB}\s+(?:\S+\s+){{0,3}}?{_WATER_RECORD}"
        rf"|\b(?:ghi chép|ghi|theo dõi|recording|logging|measuring)\s+(?:\S+\s+){{0,4}}?{_WATER_RECORD}\s+"
        rf"(?:\S+\s+){{0,4}}?(?:không bắt buộc|không cần thiết|không cần|is unnecessary|are unnecessary|is optional|"
        rf"not required|can be omitted|can be skipped)")),
)
# A negator just before or inside an assertion match ("không bao giờ bằng 0", "chưa hết phát thải")
# cancels it. The assertion's own trigger phrase is removed before this test.
_TRIGGERS = re.compile(r"khong con|chang con|hong con|khong can thiet|khong can|khoi can|khong phai|khong bat buoc|"
                       r"no need to|need not|not required to|do not need to|don't need to|not required")
_NEGATOR = re.compile(r"(?<!\w)(?:khong|chang|chua|never|not|isn't|aren't|n't)(?!\w)")
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
    start: int                 # character span in the (NFC) chunk content: content[start:end] == text
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
    if len(frac) == 3 and whole != "0":
        return None            # "1.000" / "1,500": thousands separator or decimal
    return float(f"{whole}.{frac}")


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


_CUE_CACHE: dict[str, re.Pattern] = {}


def _cue(cue: str) -> re.Pattern:
    if cue not in _CUE_CACHE:
        stem = cue.endswith("*")
        body = re.escape(_low(cue.rstrip("*")))
        _CUE_CACHE[cue] = re.compile(rf"(?<!\w){body}" + ("" if stem else r"(?!\w)"))
    return _CUE_CACHE[cue]


def _positions(lowered: str, cues: tuple[str, ...]) -> list[int]:
    return [m.start() for cue in cues for m in _cue(cue).finditer(lowered)]


def _has(lowered: str, cues: tuple[str, ...]) -> bool:
    return any(_cue(cue).search(lowered) for cue in cues)


def _nearest(lowered: str, pos: int, candidates: list[tuple[str, tuple[str, ...]]]) -> str | None:
    """The candidate whose cue is nearest to `pos`; cues within _TIE_CHARS tie, and the earlier one wins."""
    scored = []
    for order, (name, cues) in enumerate(candidates):
        hits = _positions(lowered, cues)
        if hits:
            scored.append((min(abs(h - pos) for h in hits), order, name))
    if not scored:
        return None
    best = min(s[0] for s in scored)
    return min((s for s in scored if s[0] <= best + _TIE_CHARS), key=lambda s: s[1])[2]


_CLAUSE_BREAK = re.compile(r",(?=\s)|(?<!\w)(?:nho|va|khi|nhung|vi|while|and|but|because|whereas)(?!\w)")


def _clause(sentence: str, pos: int) -> tuple[int, int]:
    """The clause around `pos`: split at commas and a few conjunctions (nhờ, và, khi, nhưng, vì, ...)."""
    start, end = 0, len(sentence)
    for m in _CLAUSE_BREAK.finditer(sentence):
        if m.end() <= pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start()
            break
    return start, end


def _parameter(sentence: str, pos: int, dimension: str) -> str | None:
    """Cues in the number's own clause first; the whole sentence only if the clause names nothing."""
    c_start, c_end = _clause(sentence, pos)
    for text, offset in ((sentence[c_start:c_end], pos - c_start), (sentence, pos)):
        candidates = [(key, groups[0]) for key, (dim, groups, excludes) in PARAMETERS.items()
                      if dim == dimension and all(_has(text, g) for g in groups) and not _has(sentence, excludes)]
        if candidates:
            return _nearest(text, offset, candidates)
    return None


def _unit(raw: str) -> tuple[str, float] | None:
    for pattern, canonical, factor in _UNIT_RX:
        if pattern.fullmatch(raw):
            return canonical, factor
    return None


def _negated(lowered: str, s_start: int, start: int, end: int) -> bool:
    window = lowered[max(s_start, start - 12):end]
    return bool(_NEGATOR.search(_TRIGGERS.sub(" ", window)))


def _claim(source: ClaimSource, start: int, end: int, kind: ClaimKind, status: ClaimStatus, **fields) -> Claim:
    claim_id = "cl-" + sha256_hex(f"{source.document_ref}|{source.chunk_id}|{start}|{end}|{kind}")[:16]
    return Claim(claim_id, source.document_ref, source.chunk_id, start, end, source.content[start:end], kind, status,
                 **fields)


def extract_claims(source: ClaimSource) -> tuple[Claim, ...]:
    text = unicodedata.normalize("NFC", source.content)
    if text != source.content:
        source = ClaimSource(source.document_ref, source.chunk_id, text)
    folded = _fold(text)
    lowered = folded.lower() if len(folded.lower()) == len(folded) else folded
    claims: list[Claim] = []
    for s_start, s_end in _sentences(text):
        sentence = lowered[s_start:s_end]
        scope = ("awd",) if _has(sentence, _AWD) else ()
        stage_hits = sorted({(s_start + p, name) for name, cues in STAGES for p in _positions(sentence, cues)})
        for pos, name in stage_hits:
            cue_end = pos + next(m.end() - m.start() for cue in dict(STAGES)[name]
                                 for m in [_cue(cue).match(lowered, pos)] if m)
            claims.append(_claim(source, pos, cue_end, "stage", "extracted", stage=name, scope=scope))

        def stage_at(pos: int) -> str | None:
            rel = pos - s_start
            c_start, c_end = _clause(sentence, rel)
            return (_nearest(sentence[c_start:c_end], rel - c_start, list(STAGES))
                    or _nearest(sentence, rel, list(STAGES)))

        date_spans = [(m.start(), m.end()) for pattern, _ in _DATES for m in pattern.finditer(folded, s_start, s_end)]
        for m in _QUANTITY.finditer(folded, s_start, s_end):
            if any(m.start() < d_end and d_start < m.end() for d_start, d_end in date_spans):
                continue        # "ngày 5 tháng 3 năm 2026" is a date, not "5 tháng" + "3 năm"
            stage = stage_at(m.start())
            unit = _unit(m.group("unit"))
            if unit is None:
                claims.append(_claim(source, m.start(), m.end(), "quantity", "unsupported", stage=stage, scope=scope,
                                     note=f"unit {text[m.start('unit'):m.end('unit')]!r} is not supported"))
                continue
            canonical, factor = unit
            dimension = UNITS[canonical]
            a, b = _number(m.group("a")), _number(m.group("b")) if m.group("b") else None
            signed = m.start() > 0 and folded[m.start() - 1] in "-−" and (
                m.start() == 1 or not folded[m.start() - 2].isalnum())
            if a is None or (m.group("b") and b is None) or signed:
                claims.append(_claim(source, m.start(), m.end(), "quantity", "ambiguous", unit=canonical,
                                     dimension=dimension, stage=stage, scope=scope,
                                     note="signed value: sign convention unknown" if signed else
                                     "number format is ambiguous (thousands separator or decimal)"))
                continue
            low, high = sorted((round(a * factor, 6), round((b if b is not None else a) * factor, 6)))
            parameter = ("fertilizer.n_rate" if _N_UNIT.fullmatch(m.group("unit"))       # the unit names nitrogen
                         else _parameter(sentence, m.start() - s_start, dimension))
            claims.append(_claim(source, m.start(), m.end(), "quantity", "extracted" if parameter else "ambiguous",
                                 parameter=parameter, value_min=low, value_max=high, unit=canonical,
                                 dimension=dimension, stage=stage, scope=scope,
                                 note="" if parameter else "no unambiguous parameter cue of this dimension"))
            if parameter == "ch4.reduction" and low >= 100:
                claims.append(_claim(source, m.start(), m.end(), "assertion", "extracted",
                                     parameter="ch4.rice.emission_eliminated", stage=stage, scope=scope,
                                     note="a reduction of 100 % or more means emission ends"))

        for pattern, _ in _DATES:
            for m in pattern.finditer(folded, s_start, s_end):
                try:
                    iso = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
                except ValueError:
                    claims.append(_claim(source, m.start(), m.end(), "date", "ambiguous", note="not a calendar date"))
                    continue
                prefix = lowered[s_start:m.start()]
                if _has(sentence, ("hiệu lực", "effective")):
                    ends = _has(prefix, ("đến", "hết", "until", "to"))
                    parameter = "document.effective_to" if ends else "document.effective_from"
                else:
                    parameter = "date.mentioned"
                claims.append(_claim(source, m.start(), m.end(), "date", "extracted", parameter=parameter, date_iso=iso))

        for parameter, pattern in _ASSERTION_PATTERNS:
            for m in pattern.finditer(folded, s_start, s_end):
                if _negated(lowered, s_start, m.start(), m.end()):
                    continue
                claims.append(_claim(source, m.start(), m.end(), "assertion", "extracted",
                                     parameter=parameter, stage=stage_at(m.start()), scope=scope))
    return tuple(sorted(claims, key=lambda c: (c.start, c.end, c.kind)))
