"""PDF parser: the existing text layer only (pypdf, already pinned). Never OCR.

- Encrypted, malformed or oversized PDFs fail explicitly (`encrypted`, `malformed`, `too_large`).
- A page "has text" with >= MIN_PAGE_CHARS non-space characters. Fewer than half the pages with
  text -- or none -- is `no_text_layer` (a scan/image-only PDF): the artifact is refused rather
  than indexed. Individual empty pages are reported as warnings.
- Each page's text goes through the shared line classifier (knowledge.parsers.text). The first and
  last line of a page become their own blocks flagged `page_first` / `page_last`, so the
  normalizer can drop repeated headers/footers by its documented rule; they are never merged.
- pypdf cannot reliably reconstruct tables: table-like lines stay verbatim with `table_uncertain`.
- Top-level numbered sections (kn-pdf-2). The line classifier keeps a single-level `2. Title` line
  a list item: one line cannot tell a section heading from a numbered list. With the whole document
  in hand, such a line is promoted to a heading only when ALL of these hold:
  * shape: `N. Title` (N 1-99, a space, the title starts with an upper-case letter, >= 2 words),
    <= 100 characters, no `:`/`;`, no terminal punctuation (`2.5 kg/ha`, `2.10.2025`, `2.` never match);
  * sequence: it is `1.`, or the number right after the previous promoted section (`1.` -> `2.` ->
    `3.`, across pages); an existing level-1 heading (ALL-CAPS or legal division) starts a new
    sequence, except a running header (the same edge heading on >= 3 pages);
  * isolation: the line before is not item `N-1.` and the line after is not item `N+1.` (a
    numbering that continues through the line makes it a list item, even with a matching sequence);
  * not a wrapped sentence: the next line does not start with a lower-case letter (a list marker
    such as `a)` starts a new item, not a continuation).
  It nests under an open level-1 heading, and the `2.1`-style headings of THAT section move one
  level down with it, so `II. CONTENT > 1. Methods > 1.6 Pests` is followed by
  `II. CONTENT > 2. Harvest`, never `... > 1.6 > 2.`. A multi-level heading whose prefix is not the
  open section's number (`3.1` after `6.`) does not nest in it: it takes the section's own level.
  Everything else -- lists, prose, decimals, dates -- is unchanged. Font/bold data is not used:
  the parser reads plain extracted text only.
The pypdf version is part of PARSER_VERSION because extraction output may change between releases.
"""

from __future__ import annotations

import io
import re
import unicodedata

import pypdf
from pypdf.errors import PyPdfError

from knowledge.models import Block, ParsedDocument, ParseError, check_block_count
from knowledge.parsers.text import heading_level, segment_lines

PARSER_VERSION = f"kn-pdf-2+pypdf-{pypdf.__version__}"
MIN_PAGE_CHARS = 20
MAX_PAGES = 2000
MAX_TEXT_CHARS = 20_000_000
_EDGE_MAX_CHARS = 100
_SECTION_MAX_CHARS = 100

_TOP_NUMBERED = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
_MULTI_NUMBERED = re.compile(r"^\d{1,3}(?:\.\d{1,3}){1,5}\.?\s")
_DIGIT_ITEM = re.compile(r"^(\d{1,3})[.)]\s+\S")
_LIST_MARKER = re.compile(r"^(?:[-*+•–]|\d{1,3}[.)]|[a-zđ][)])\s+\S")   # the line classifier's list markers
_TERMINAL = (".", ",", ";", ":", "!", "?")


def _edge(line: str, page: int, flag: str) -> Block:
    level = heading_level(line)
    return Block(kind="heading" if level else "paragraph", text=line, level=level, page=page, flags=(flag,))


def _page_blocks(text: str, page: int) -> list[Block]:
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    content = [i for i, line in enumerate(lines) if line.strip()]
    if len(content) < 3:
        return segment_lines(lines, page)
    first, last = content[0], content[-1]
    blocks: list[Block] = []
    if len(lines[first].strip()) <= _EDGE_MAX_CHARS:
        blocks.append(_edge(lines[first].strip(), page, "page_first"))
        start = first + 1
    else:
        start = first
    end_block = None
    if len(lines[last].strip()) <= _EDGE_MAX_CHARS:
        end_block = _edge(lines[last].strip(), page, "page_last")
        stop = last
    else:
        stop = last + 1
    blocks.extend(segment_lines(lines[start:stop], page))
    if end_block:
        blocks.append(end_block)
    return blocks


def _section_number(line: str) -> int | None:
    """N when `line` has the SHAPE of a top-level `N. Title` heading; the context is checked by the caller."""
    m = _TOP_NUMBERED.match(line)
    if not m or len(line) > _SECTION_MAX_CHARS or line.endswith(_TERMINAL):
        return None
    title = m.group(2)
    if ":" in title or ";" in title or len(title.split()) < 2 or not (title[0].isalpha() and title[0].isupper()):
        return None
    return int(m.group(1)) or None


def _item_number(line: str | None) -> int | None:
    """N of a single-level `N.` / `N)` list item, else None."""
    m = _DIGIT_ITEM.match(line or "")
    return int(m.group(1)) if m else None


def _running_edge_headings(blocks: list[Block]) -> set[str]:
    """Level-1 edge headings whose text (digits ignored) recurs on >= 3 page edges: running headers,
    which the normalizer may drop later. They neither start nor close a numbered-section sequence."""
    pages: dict[str, set[int | None]] = {}
    for b in blocks:
        if b.kind == "heading" and b.level == 1 and {"page_first", "page_last"} & set(b.flags):
            pages.setdefault(re.sub(r"\d+", "#", b.text.lower()), set()).add(b.page)
    return {key for key, seen in pages.items() if len(seen) >= 3}


def _top_level_sections(blocks: list[Block]) -> list[Block]:
    """Promote isolated, in-sequence `N. Title` lines to headings (module docstring, kn-pdf-2)."""
    running = _running_edge_headings(blocks)
    out: list[Block] = []
    last: int | None = None      # number of the previous promoted section in this sequence
    nested = False               # a level-1 heading is open: promoted sections become level 2
    inside = False               # a promoted section is open

    def promotable(line: str, before: str | None, after: str | None) -> int | None:
        n = _section_number(line)
        if n is None or n != (last or 0) + 1:
            return None
        if _item_number(before) == n - 1 or _item_number(after) == n + 1:
            return None
        if after and after[0].isalpha() and after[0].islower() and not _LIST_MARKER.match(after):
            return None
        return n

    for i, b in enumerate(blocks):
        if b.kind == "heading":
            if b.level == 1 and re.sub(r"\d+", "#", b.text.lower()) not in running:
                last, nested, inside = None, True, False
            elif inside and _MULTI_NUMBERED.match(b.text):
                # `2.3` inside promoted section `2.` nests one level down; `3.1` after `6.` is not part of
                # it and returns to the section's own level, closing the section instead of nesting in it.
                offset = (1 if nested else 0) - (0 if int(b.text.split(".", 1)[0]) == last else 1)
                level = min(max(b.level + offset, 1), 6)
                b = Block(kind="heading", text=b.text, level=level, page=b.page, flags=b.flags)
            out.append(b)
            continue
        single_edge = b.kind == "paragraph" and "\n" not in b.text and {"page_first", "page_last"} & set(b.flags)
        if b.kind != "list" and not single_edge:
            out.append(b)
            continue
        lines = [line.strip() for line in b.text.split("\n")]
        prev_block = blocks[i - 1].text.split("\n")[-1].strip() if i else None
        next_block = blocks[i + 1].text.split("\n")[0].strip() if i + 1 < len(blocks) else None
        pending: list[str] = []
        for j, line in enumerate(lines):
            before = lines[j - 1] if j else prev_block
            after = lines[j + 1] if j + 1 < len(lines) else next_block
            n = promotable(line, before, after)
            if n is None:
                pending.append(line)
                continue
            if pending:
                out.append(Block(kind=b.kind, text="\n".join(pending), page=b.page, flags=b.flags))
                pending = []
            out.append(Block(kind="heading", text=line, level=2 if nested else 1, page=b.page, flags=b.flags))
            last, inside = n, True
        if pending:
            out.append(Block(kind=b.kind, text="\n".join(pending), page=b.page, flags=b.flags))
    return out


def parse(data: bytes) -> ParsedDocument:
    if not data.startswith(b"%PDF-"):
        raise ParseError("not a PDF file (missing %PDF- header)", code="malformed")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ParseError("encrypted PDFs are not supported", code="encrypted")
        page_count = len(reader.pages)
        if page_count == 0:
            raise ParseError("the PDF has no pages", code="no_text_layer")
        if page_count > MAX_PAGES:
            raise ParseError(f"the PDF has {page_count} pages (limit {MAX_PAGES})", code="too_large")
        texts, total = [], 0
        for page in reader.pages:
            text = unicodedata.normalize("NFC", page.extract_text() or "")   # before structure rules
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise ParseError(f"extracted text exceeds {MAX_TEXT_CHARS} characters", code="too_large")
            texts.append(text)
    except ParseError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError,
            OSError, ZeroDivisionError) as exc:
        raise ParseError(f"the PDF could not be read ({type(exc).__name__})", code="malformed") from exc

    with_text = [i for i, t in enumerate(texts, start=1) if sum(not c.isspace() for c in t) >= MIN_PAGE_CHARS]
    if len(with_text) * 2 < page_count or not with_text:
        raise ParseError(f"no usable text layer: {len(with_text)} of {page_count} pages have text "
                         f"(scanned/image-only PDFs need OCR, which is unsupported)", code="no_text_layer")
    warnings = [f"page {i} has no extractable text" for i in range(1, page_count + 1) if i not in with_text]
    blocks: list[Block] = []
    for number, text in enumerate(texts, start=1):
        if number in with_text:
            blocks.extend(_page_blocks(text, number))
            check_block_count(len(blocks))
    blocks = _top_level_sections(blocks)
    check_block_count(len(blocks))
    return ParsedDocument(format="pdf", parser_version=PARSER_VERSION, blocks=tuple(blocks),
                          page_count=page_count, warnings=tuple(warnings))
