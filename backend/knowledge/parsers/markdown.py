"""Markdown parser (.md), stdlib only: the structure CommonMark makes explicit.

- ATX headings `#`..`######` and setext headings (`===` / `---` under one line);
- fenced code (``` or ~~~) kept whole as a `code` block;
- pipe tables kept whole as a `table` block (alignment rows `|---|` are markup and dropped);
- list items (`-`, `*`, `+`, `1.`, `1)`) with indented continuations;
- `>` quotes become paragraphs; a leading YAML front-matter block is ignored (warning).
Inline markup (emphasis, links) is kept verbatim -- no rewriting.
"""

from __future__ import annotations

import re

from knowledge.models import Block, ParsedDocument
from knowledge.parsers.text import decode

PARSER_VERSION = "kn-markdown-1"

_ATX = re.compile(r"^(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_SETEXT_1 = re.compile(r"^\s{0,3}=+\s*$")
_SETEXT_2 = re.compile(r"^\s{0,3}-{2,}\s*$")
_THEMATIC = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$|^[^|]+\|[^|]+\|")
_ALIGN_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+\S")
_CONTINUATION = re.compile(r"^\s{2,}\S")


def parse(data: bytes) -> ParsedDocument:
    lines = decode(data).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    warnings: list[str] = []
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, min(len(lines), 60)) if lines[i].strip() in ("---", "...")), None)
        if end is not None:
            lines = lines[end + 1:]
            warnings.append("front_matter_ignored")

    blocks: list[Block] = []
    buf: list[str] = []
    kind: str | None = None
    fence: str | None = None

    def flush():
        nonlocal buf, kind
        if buf:
            blocks.append(Block(kind=kind or "paragraph", text="\n".join(buf)))
        buf, kind = [], None

    for raw in lines:
        line = raw.rstrip()
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
                flush()
            else:
                buf.append(line)
            continue
        m = _FENCE.match(line)
        if m:
            flush()
            fence, kind = m.group(1)[0] * 3, "code"
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if kind == "paragraph" and len(buf) == 1 and (_SETEXT_1.match(line) or _SETEXT_2.match(line)):
            text, buf, kind = buf[0], [], None
            blocks.append(Block(kind="heading", text=text, level=1 if _SETEXT_1.match(line) else 2))
            continue
        if _THEMATIC.match(line):
            flush()
            continue
        m = _ATX.match(stripped)
        if m:
            flush()
            title = re.sub(r"(?:^|\s)#+$", "", (m.group(2) or "").strip()).strip()
            if title:
                blocks.append(Block(kind="heading", text=title, level=len(m.group(1))))
            continue
        if _TABLE_ROW.match(line):
            if kind != "table":
                flush()
                kind = "table"
            if not _ALIGN_ROW.match(line):
                buf.append(stripped)
            continue
        if _LIST_ITEM.match(line):
            if kind != "list":
                flush()
                kind = "list"
            buf.append(stripped)
            continue
        if kind == "list" and _CONTINUATION.match(line):
            buf[-1] = f"{buf[-1]} {stripped}"
            continue
        if kind not in (None, "paragraph"):
            flush()
        kind = "paragraph"
        buf.append(stripped[1:].strip() if stripped.startswith(">") else stripped)
    if fence is not None:
        warnings.append("unclosed_code_fence")
    flush()
    return ParsedDocument(format="markdown", parser_version=PARSER_VERSION, blocks=tuple(blocks),
                          warnings=tuple(warnings))
