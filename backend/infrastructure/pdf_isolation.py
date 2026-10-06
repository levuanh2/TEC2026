"""Process-isolated PDF parsing for the knowledge ingestion CLI (RAG V1.3-C).

A malicious or pathological PDF must not hang or exhaust the operator's ingestion process,
so PDF bytes are never parsed in the parent. `parse_pdf_isolated` spawns THIS file as a
fresh interpreter (`python -I -B`, subprocess: spawn semantics on every platform, never
fork), writes the PDF to the child's stdin and reads one bounded JSON document from its stdout.

Parent (all platforms):
- hard wall-clock timeout (PDF_PARSE_TIMEOUT_SECONDS); on timeout, crash, protocol error or an
  oversized result the child is killed and ALWAYS reaped (wait) and every pipe closed;
- the child gets a minimal environment: no Supabase URL/key, no database URL, no user secrets;
- stdout is read with a hard byte cap (MAX_RESULT_BYTES); stderr is read with a small cap and
  only its last line is ever surfaced;
- the result is JSON (never pickle) and validated field by field before a ParsedDocument is
  built; anything unexpected is `parse_worker_protocol`;
- no temporary file is created: bytes travel over pipes.
Child:
- POSIX: installs `resource` limits on itself BEFORE importing pypdf: address space
  (PDF_WORKER_MEMORY_BYTES), CPU seconds (the timeout), file size 0 (it never writes a file),
  open files; a limit hit is `parse_resource_limit`;
- Windows: no hard per-child memory cap in V1.3-C (that needs Job objects / pywin32); the
  wall-clock timeout, forced termination and the parser's own limits (50 MiB file, 2000 pages,
  pypdf's 75 MB per-stream cap, 20 M extracted characters, 100 000 blocks) still apply;
- runs the existing knowledge.parsers.pdf.parse, whose limits are enforced before the result
  is serialized.
Outcomes (ParseError.code): parse_timeout, parse_resource_limit, parse_worker_crashed,
parse_worker_protocol, extraction_limit_exceeded, plus the parser's own malformed, encrypted,
no_text_layer, too_large, too_many_blocks. A failure never reaches Storage or the database:
parsing happens in plan(), before any write.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

PDF_PARSE_TIMEOUT_SECONDS = 120          # offline operator CLI; generous for 2000 text pages
PDF_WORKER_MEMORY_BYTES = 2 * 1024 ** 3  # POSIX address-space cap of the child
PDF_WORKER_OPEN_FILES = 64
MAX_RESULT_BYTES = 96 * 1024 * 1024      # 20 M characters of mostly 3-byte UTF-8 + JSON framing
_STDERR_CAP = 64 * 1024
EXIT_OK, EXIT_PARSE_ERROR, EXIT_RESOURCE = 0, 2, 3

_BACKEND = Path(__file__).resolve().parent.parent
_KINDS = frozenset({"heading", "paragraph", "list", "table", "code"})
_FLAGS = frozenset({"table_uncertain", "page_first", "page_last"})
_ENV_KEEP = ("SYSTEMROOT", "WINDIR", "LANG", "LC_ALL")    # what an interpreter needs to start; nothing else


# ------------------------------------------------------------------------------ child side

def apply_limits(memory_bytes: int, cpu_seconds: int, open_files: int) -> bool:
    """POSIX only: cap the CURRENT process. Returns False where `resource` is unavailable."""
    try:
        import resource
    except ImportError:          # Windows
        return False
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (open_files, open_files))
    return True


def run_worker(data: bytes) -> tuple[int, bytes]:
    """Parse PDF bytes; (exit code, JSON payload). The parser's limits apply before serializing."""
    from knowledge.models import ParseError
    from knowledge.parsers import pdf

    try:
        parsed = pdf.parse(data)
    except ParseError as exc:
        return EXIT_PARSE_ERROR, json.dumps({"ok": False, "code": exc.code, "message": str(exc)[:500]}).encode()
    except MemoryError:
        return EXIT_RESOURCE, b'{"ok": false, "code": "parse_resource_limit"}'
    payload = {"ok": True, "format": parsed.format, "parser_version": parsed.parser_version,
               "page_count": parsed.page_count, "warnings": list(parsed.warnings),
               "blocks": [{"kind": b.kind, "text": b.text, "level": b.level, "page": b.page, "flags": list(b.flags)}
                          for b in parsed.blocks]}
    return EXIT_OK, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _child_main(argv: list[str]) -> int:
    memory_bytes, cpu_seconds, open_files = (int(a) for a in argv)
    apply_limits(memory_bytes, cpu_seconds, open_files)
    sys.path.insert(0, str(_BACKEND))
    try:
        data = sys.stdin.buffer.read()
        code, payload = run_worker(data)
    except MemoryError:
        code, payload = EXIT_RESOURCE, b'{"ok": false, "code": "parse_resource_limit"}'
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    return code


# ------------------------------------------------------------------------------ parent side

def _worker_command(timeout: int) -> list[str]:
    return [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
            str(PDF_WORKER_MEMORY_BYTES), str(timeout), str(PDF_WORKER_OPEN_FILES)]


def _child_env() -> dict[str, str]:
    return {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}


def _failure(code: str, message: str):
    from knowledge.models import ParseError

    return ParseError(message, code=code)


class _Reader(threading.Thread):
    """Drain one pipe up to `cap` bytes; past the cap, stop and remember the overflow."""

    def __init__(self, stream, cap: int, on_overflow=None):
        super().__init__(daemon=True)
        self.stream, self.cap, self.on_overflow = stream, cap, on_overflow
        self.chunks: list[bytes] = []
        self.size = 0
        self.overflow = False

    def run(self):
        try:
            while True:
                chunk = self.stream.read(1 << 16)
                if not chunk:
                    return
                if self.size + len(chunk) > self.cap:
                    self.overflow = True
                    if self.on_overflow:
                        self.on_overflow()
                    return
                self.chunks.append(chunk)
                self.size += len(chunk)
        except (OSError, ValueError):
            return

    def data(self) -> bytes:
        return b"".join(self.chunks)


def _write_all(stream, data: bytes) -> None:
    try:
        stream.write(data)
    except (BrokenPipeError, OSError, ValueError):
        pass                      # the child exited early; its exit code tells why
    finally:
        try:
            stream.close()
        except OSError:
            pass


def parse_pdf_isolated(data: bytes, *, timeout: int = PDF_PARSE_TIMEOUT_SECONDS):
    """Parse a PDF in a separate, limited, always-reaped process. Returns a ParsedDocument."""
    proc = subprocess.Popen(_worker_command(timeout), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=_child_env(), cwd=str(_BACKEND), close_fds=True)
    out = _Reader(proc.stdout, MAX_RESULT_BYTES, on_overflow=proc.kill)
    err = _Reader(proc.stderr, _STDERR_CAP)
    writer = threading.Thread(target=_write_all, args=(proc.stdin, data), daemon=True)
    for t in (out, err, writer):
        t.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()                                   # always reaped: no zombie, no orphan
        for t in (writer, out, err):
            t.join(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass

    if timed_out:
        raise _failure("parse_timeout", f"PDF parsing exceeded {timeout} s and the worker was terminated")
    if out.overflow:
        raise _failure("extraction_limit_exceeded",
                       f"the PDF worker's result exceeded {MAX_RESULT_BYTES} bytes and was rejected")
    return _decode(proc.returncode, out.data(), err.data())


def _decode(returncode: int, raw: bytes, stderr: bytes):
    from knowledge.models import Block, ParsedDocument
    from knowledge.parsers import pdf

    if returncode == EXIT_RESOURCE or returncode in (-9, -24, 137, 152):   # SIGKILL (AS/OOM), SIGXCPU
        raise _failure("parse_resource_limit", "the PDF worker hit its memory/CPU limit")
    if returncode not in (EXIT_OK, EXIT_PARSE_ERROR):
        tail = stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise _failure("parse_worker_crashed", f"the PDF worker exited with {returncode} ({tail[0][:200]})")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _failure("parse_worker_protocol", "the PDF worker returned malformed output") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("ok"), bool):
        raise _failure("parse_worker_protocol", "the PDF worker returned an unexpected result")
    if returncode == EXIT_PARSE_ERROR or not doc["ok"]:
        code, message = doc.get("code"), doc.get("message", "")
        known = {"malformed", "encrypted", "no_text_layer", "too_large", "too_many_blocks", "parse_resource_limit"}
        if returncode != EXIT_PARSE_ERROR or doc["ok"] or code not in known or not isinstance(message, str):
            raise _failure("parse_worker_protocol", "the PDF worker returned an inconsistent error")
        raise _failure(code, message or code)
    return _validated(doc, Block, ParsedDocument, pdf)


def _validated(doc: dict, Block, ParsedDocument, pdf):
    from knowledge.models import MAX_BLOCKS

    def bad(why: str):
        return _failure("parse_worker_protocol", f"the PDF worker result is invalid: {why}")

    if set(doc) != {"ok", "format", "parser_version", "page_count", "warnings", "blocks"}:
        raise bad("fields")
    if doc["format"] != "pdf" or doc["parser_version"] != pdf.PARSER_VERSION:
        raise bad("format/version")
    pages = doc["page_count"]
    if not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= pdf.MAX_PAGES:
        raise bad("page_count")
    warnings, blocks = doc["warnings"], doc["blocks"]
    if not isinstance(warnings, list) or len(warnings) > pages or not all(isinstance(w, str) and len(w) < 200
                                                                        for w in warnings):
        raise bad("warnings")
    if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
        raise bad("blocks")
    out, total = [], 0
    for b in blocks:
        if not isinstance(b, dict) or set(b) != {"kind", "text", "level", "page", "flags"}:
            raise bad("block fields")
        kind, text, level, page, flags = b["kind"], b["text"], b["level"], b["page"], b["flags"]
        if kind not in _KINDS or not isinstance(text, str) or not isinstance(flags, list) or not set(flags) <= _FLAGS:
            raise bad("block values")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 6 or (level > 0) != (kind == "heading"):
            raise bad("block level")
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= pages:
            raise bad("block page")
        total += len(text)
        if total > pdf.MAX_TEXT_CHARS:
            raise _failure("extraction_limit_exceeded", "the PDF worker returned more text than the limit")
        out.append(Block(kind=kind, text=text, level=level, page=page, flags=tuple(flags)))
    return ParsedDocument(format="pdf", parser_version=doc["parser_version"], blocks=tuple(out),
                          page_count=pages, warnings=tuple(warnings))


if __name__ == "__main__":
    sys.exit(_child_main(sys.argv[1:]))
