"""Plain-text parser (.txt) and the line classifier shared with the PDF parser.

Structure is detected conservatively and never rewritten:
- headings: multi-level numbering (`1.2`, `1.2.3 Title`), Vietnamese legal divisions
  (`Chương II`, `Mục 1`, `Điều 5`, `Phần`, `Phụ lục`), or a short ALL-CAPS line;
- list items: `-`, `*`, `+`, `•`, `–`, `1.`, `1)`, `a)` markers (continuations stay in the item);
- table-like lines: two or more `|`, a tab, or two or more runs of 2+ spaces between words.
  Plain text cannot prove a table, so these blocks carry `table_uncertain`.
Blank lines end a paragraph. Single-level `1.` lines are list items, not headings.
"""

from __future__ import annotations

import re
import unicodedata

from knowledge.models import Block, ParsedDocument, ParseError

PARSER_VERSION = "kn-text-1"

_NUMBERED = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){1,5})\.?\s+(\S.*)$")
_LEGAL = re.compile(r"^(Phần|Chương|Mục|Điều|Phụ lục)\s+([0-9]{1,3}|[IVXLC]{1,7})\b[.:]?(\s.*)?$", re.IGNORECASE)
_LEGAL_LEVEL = {"phần": 1, "chương": 1, "phụ lục": 1, "mục": 2, "điều": 3}
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•–]|\d{1,3}[.)]|[a-zđ][)])\s+\S")
_CONTINUATION = re.compile(r"^\s{2,}\S")
_TERMINAL = (".", ",", ";", ":", "!", "?")


def decode(data: bytes) -> str:
    if b"\x00" in data:
        raise ParseError("the file contains NUL bytes: not a text document", code="binary_content")
    try:
        # NFC before any structure rule: canonically equivalent input (NFD `Điều`) must classify
        # identically, or section paths and chunk ids would differ.
        return unicodedata.normalize("NFC", data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ParseError(f"the file is not valid UTF-8 (byte {exc.start})", code="encoding") from exc


def heading_level(line: str) -> int:
    """Heading depth of a stripped line, or 0."""
    if len(line) > 120 or line.endswith(_TERMINAL):
        return 0
    m = _NUMBERED.match(line)
    if m and m.group(2)[:1].isalpha():
        return m.group(1).count(".") + 1
    m = _LEGAL.match(line)
    if m:
        return _LEGAL_LEVEL[m.group(1).lower()]
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 2 and len(line) <= 80 and line == line.upper() and len(line.split()) >= 2:
        return 1
    return 0


def is_table_line(line: str) -> bool:
    return line.count("|") >= 2 or "\t" in line or len(re.findall(r"\S {2,}(?=\S)", line.strip())) >= 2


def segment_lines(lines: list[str], page: int | None = None) -> list[Block]:
    blocks: list[Block] = []
    buf: list[str] = []
    kind: str | None = None

    def flush():
        nonlocal buf, kind
        if buf:
            flags = ("table_uncertain",) if kind == "table" else ()
            blocks.append(Block(kind=kind or "paragraph", text="\n".join(buf), page=page, flags=flags))
        buf, kind = [], None

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        level = heading_level(stripped)
        if level:
            flush()
            blocks.append(Block(kind="heading", text=stripped, level=level, page=page))
        elif is_table_line(line):
            if kind != "table":
                flush()
                kind = "table"
            buf.append(line)
        elif _LIST_ITEM.match(line):
            if kind != "list":
                flush()
                kind = "list"
            buf.append(stripped)
        elif kind == "list" and _CONTINUATION.match(line):
            buf[-1] = f"{buf[-1]} {stripped}"
        else:
            if kind not in (None, "paragraph"):
                flush()
            kind = "paragraph"
            buf.append(stripped)
    flush()
    return blocks


def parse(data: bytes) -> ParsedDocument:
    text = decode(data).replace("\r\n", "\n").replace("\r", "\n")
    return ParsedDocument(format="text", parser_version=PARSER_VERSION, blocks=tuple(segment_lines(text.split("\n"))))
