"""Format registry: only .md, .txt and text-layer PDF (ADR §4.1).

The extension selects the parser, and the leading bytes must agree with it, so a renamed
DOCX/ZIP/PDF is refused instead of being parsed as text. Anything else is unsupported --
no DOCX, HTML, spreadsheets, OCR or crawling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from knowledge.models import ParsedDocument, UnsupportedFormatError


@dataclass(frozen=True)
class Format:
    name: str
    extension: str
    content_type: str


FORMATS = {
    ".md": Format("markdown", ".md", "text/markdown"),
    ".txt": Format("text", ".txt", "text/plain"),
    ".pdf": Format("pdf", ".pdf", "application/pdf"),
}
_FOREIGN_MAGIC = (b"%PDF-", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"{\\rtf", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")


def detect(filename: str, data: bytes) -> Format:
    dot = filename.rfind(".")
    extension = filename[dot:].lower() if dot > 0 else ""
    fmt = FORMATS.get(extension)
    if fmt is None:
        raise UnsupportedFormatError(f"unsupported file type {extension or '(none)'!r}: only .md, .txt and "
                                     "PDF with a text layer are supported")
    if fmt.name == "pdf" and not data.startswith(b"%PDF-"):
        raise UnsupportedFormatError("the file is named .pdf but is not a PDF")
    if fmt.name != "pdf" and data.lstrip(b"\xef\xbb\xbf").startswith(_FOREIGN_MAGIC):
        raise UnsupportedFormatError(f"the file is named {extension} but its content is a binary/PDF/Office format")
    return fmt


def parser_for(fmt: Format) -> Callable[[bytes], ParsedDocument]:
    """In-process parsers for the TEXT formats only. PDFs are never parsed in the calling
    process: the caller injects an isolated parser (infrastructure/pdf_isolation.py) into
    knowledge.ingest.plan; knowledge.parsers.pdf.parse runs inside that worker."""
    if fmt.name == "markdown":
        from knowledge.parsers.markdown import parse
    elif fmt.name == "text":
        from knowledge.parsers.text import parse
    else:
        raise ValueError("PDF parsing is process-isolated; pass pdf_parser to knowledge.ingest.plan")
    return parse
