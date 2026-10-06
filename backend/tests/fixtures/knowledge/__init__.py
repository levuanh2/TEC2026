"""Synthetic knowledge fixtures (TEST FIXTURE — NOT A REAL APPROVED SOURCE) and generated PDFs.

PDFs are produced at test time with reportlab (already a production dependency) and the
bundled Be Vietnam Pro font, so no binary or copyrighted document is committed.
"""

from __future__ import annotations

import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = "TEST FIXTURE — NOT A REAL APPROVED SOURCE."
_FONT = HERE.parents[2] / "mrv" / "fonts" / "BeVietnamPro-Regular.ttf"


def read(name: str) -> bytes:
    return (HERE / name).read_bytes()


def make_pdf(pages: list[list[str]]) -> bytes:
    """One list of lines per page; an empty list makes an image-less blank page (no text layer)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    if "KnFixture" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("KnFixture", str(_FONT)))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for lines in pages:
        y = 800
        for line in lines:
            if line:
                c.setFont("KnFixture", 11)
                c.drawString(60, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()
