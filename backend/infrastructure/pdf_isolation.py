"""Process-isolated PDF parsing for the knowledge ingestion CLI (RAG V1.3-C).

A malicious or pathological PDF must not hang or exhaust the operator's ingestion process,
so PDF bytes are never parsed in the parent. `parse_pdf_isolated` spawns THIS file as a
fresh interpreter (`python -I -B`, subprocess: spawn semantics on every platform, never
fork), writes the PDF to the child's stdin and reads one bounded JSON document from its stdout.

Parent (all platforms):
- hard wall-clock timeout (PDF_PARSE_TIMEOUT_SECONDS); on timeout, crash, protocol error or an
  oversized result the child is killed and ALWAYS reaped (wait) and every pipe closed;
- the child gets a minimal environment: no Supabase URL/key, no database URL, no user secrets;
- stdout is read with a hard byte cap (MAX_RESULT_BYTES); stderr is drained to EOF keeping only a
  4 KiB rolling tail (so a chatty child can never block on a full pipe), and only its last line
  is ever surfaced; the child also disables logging below ERROR (pypdf warns per broken object);
- the result is JSON (never pickle) and validated field by field before a ParsedDocument is
  built; anything unexpected is `parse_worker_protocol`;
- no temporary file is created: bytes travel over pipes.
Child:
- POSIX: installs `resource` limits on itself BEFORE importing pypdf: address space
  (PDF_WORKER_MEMORY_BYTES), CPU seconds (the timeout), file size 0 (it never writes a file),
  open files; a limit hit is `parse_resource_limit`;
- Windows: no hard per-child memory cap in V1.3-C. One is possible with a Job object (stdlib
  ctypes, JOB_OBJECT_LIMIT_PROCESS_MEMORY) but is not built here; the wall-clock timeout, forced
  termination and the parser's own limits (50 MiB file, 2000 pages, pypdf's 75 MB per-stream cap,
  20 M extracted characters, 100 000 blocks) still apply. Ingest unreviewed PDFs on Linux;
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
_STDERR_TAIL = 4 * 1024                  # stderr is drained to EOF; only this rolling tail is kept
_MAX_MESSAGE = 500
# 86, not a small number: a Windows CRT abort() exits 3, a crash must never read as a limit hit.
EXIT_OK, EXIT_PARSE_ERROR, EXIT_RESOURCE = 0, 2, 86

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

    def cap(limit, soft, hard):
        # Never ask for more than the inherited hard limit (an operator's `ulimit` may be lower).
        current_hard = resource.getrlimit(limit)[1]
        if current_hard != resource.RLIM_INFINITY:
            soft, hard = min(soft, current_hard), min(hard, current_hard)
        resource.setrlimit(limit, (soft, hard))

    cap(resource.RLIMIT_AS, memory_bytes, memory_bytes)
    cap(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
    cap(resource.RLIMIT_FSIZE, 0, 0)
    cap(resource.RLIMIT_NOFILE, open_files, open_files)
    return True


def run_worker(data: bytes) -> tuple[int, bytes]:
    """Parse PDF bytes; (exit code, JSON payload). The parser's limits apply before serializing."""
    from knowledge.models import ParseError
    from knowledge.parsers import pdf

    def error(code: str, message: str) -> tuple[int, bytes]:
        return EXIT_PARSE_ERROR, json.dumps({"ok": False, "code": code, "message": message[:_MAX_MESSAGE]}).encode()

    try:
        parsed = pdf.parse(data)
    except ParseError as exc:
        return error(exc.code, str(exc))
    except MemoryError:
        return EXIT_RESOURCE, b'{"ok": false, "code": "parse_resource_limit"}'
    payload = {"ok": True, "format": parsed.format, "parser_version": parsed.parser_version,
               "page_count": parsed.page_count, "warnings": list(parsed.warnings),
               "blocks": [{"kind": b.kind, "text": b.text, "level": b.level, "page": b.page, "flags": list(b.flags)}
                          for b in parsed.blocks]}
    try:
        return EXIT_OK, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except UnicodeEncodeError:   # a crafted ToUnicode map can yield lone surrogates: not storable text
        return error("malformed", "the PDF text layer contains invalid Unicode (lone surrogates)")


def _child_main(argv: list[str]) -> int:
    memory_bytes, cpu_seconds, open_files = (int(a) for a in argv)
    apply_limits(memory_bytes, cpu_seconds, open_files)
    sys.path.insert(0, str(_BACKEND))
    import logging

    logging.disable(logging.WARNING)       # pypdf logs one warning per broken object; never flood stderr
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
    """Drain one pipe to EOF. `cap`: keep at most this many bytes and, past it, kill the child
    (`on_overflow`) and remember the overflow. `tail`: keep only the last bytes and DISCARD the
    rest while still reading, so the child can never block on a full pipe."""

    def __init__(self, stream, *, cap: int | None = None, tail: int | None = None, on_overflow=None):
        super().__init__(daemon=True)
        self.stream, self.cap, self.tail, self.on_overflow = stream, cap, tail, on_overflow
        self.chunks: list[bytes] = []
        self.size = 0
        self.overflow = False

    def run(self):
        try:
            while True:
                chunk = self.stream.read1(1 << 16)
                if not chunk:
                    return
                if self.tail is not None:
                    self.chunks = [(b"".join(self.chunks) + chunk)[-self.tail:]]
                    continue
                if self.size + len(chunk) > self.cap:
                    self.overflow = True
                    self.chunks = []
                    if self.on_overflow:
                        self.on_overflow()
                    return
                self.chunks.append(chunk)
                self.size += len(chunk)
        except (OSError, ValueError):
            return

    def take(self) -> bytes:
        data, self.chunks = b"".join(self.chunks), []
        return data


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
    out = _Reader(proc.stdout, cap=MAX_RESULT_BYTES, on_overflow=proc.kill)
    err = _Reader(proc.stderr, tail=_STDERR_TAIL)
    writer = threading.Thread(target=_write_all, args=(proc.stdin, data), daemon=True)
    started: list[threading.Thread] = []
    timed_out = False
    try:
        for t in (out, err, writer):                  # inside the try: a failed start still reaps the child
            t.start()
            started.append(t)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()                                   # always reaped: no zombie, no orphan
        for t in started:
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
    return _decode(proc.returncode, out.take(), err.take())


_KNOWN_ERRORS = frozenset({"malformed", "encrypted", "no_text_layer", "too_large", "too_many_blocks",
                           "parse_resource_limit"})


def _decode(returncode: int, raw: bytes, stderr: bytes):
    if returncode == EXIT_RESOURCE or returncode in (-9, -24):     # MemoryError, SIGKILL (AS/OOM), SIGXCPU
        raise _failure("parse_resource_limit", "the PDF worker hit its memory/CPU limit")
    if returncode not in (EXIT_OK, EXIT_PARSE_ERROR):
        tail = stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise _failure("parse_worker_crashed", f"the PDF worker exited with {returncode} ({tail[0][:200]})")
    try:
        return _interpret(returncode, raw)
    except (TypeError, ValueError, RecursionError, KeyError, AttributeError):
        # Whatever shape a broken/compromised worker sends (deep nesting, unhashable values,
        # invalid UTF-8): a typed protocol error, never an unhandled exception.
        raise _failure("parse_worker_protocol", "the PDF worker returned malformed output") from None


def _interpret(returncode: int, raw: bytes):
    from knowledge.models import Block, ParsedDocument
    from knowledge.parsers import pdf

    # Strict UTF-8 first: json.loads(bytes) would also accept UTF-16/32 and surrogate bytes.
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("ok"), bool):
        raise _failure("parse_worker_protocol", "the PDF worker returned an unexpected result")
    if returncode == EXIT_PARSE_ERROR or not doc["ok"]:
        code, message = doc.get("code"), doc.get("message", "")
        if (returncode != EXIT_PARSE_ERROR or doc["ok"] or not isinstance(code, str) or code not in _KNOWN_ERRORS
                or not isinstance(message, str) or len(message) > _MAX_MESSAGE):
            raise _failure("parse_worker_protocol", "the PDF worker returned an inconsistent error")
        raise _failure(code, message or code)
    return _validated(doc, Block, ParsedDocument, pdf)


def _storable(text: str) -> bool:
    """Defense in depth: a lone surrogate (e.g. a `\\ud800` JSON escape) is not storable text."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


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
    if not isinstance(warnings, list) or len(warnings) > pages or not all(
            isinstance(w, str) and len(w) < 200 and _storable(w) for w in warnings):
        raise bad("warnings")
    if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
        raise bad("blocks")
    out, total = [], 0
    for b in blocks:
        if not isinstance(b, dict) or set(b) != {"kind", "text", "level", "page", "flags"}:
            raise bad("block fields")
        kind, text, level, page, flags = b["kind"], b["text"], b["level"], b["page"], b["flags"]
        if (not isinstance(kind, str) or kind not in _KINDS or not isinstance(text, str) or not isinstance(flags, list)
                or not all(isinstance(f, str) and f in _FLAGS for f in flags)):
            raise bad("block values")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 6 or (level > 0) != (kind == "heading"):
            raise bad("block level")
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= pages:
            raise bad("block page")
        if not _storable(text):
            raise bad("block text is not valid Unicode")
        total += len(text)
        if total > pdf.MAX_TEXT_CHARS:
            raise _failure("extraction_limit_exceeded", "the PDF worker returned more text than the limit")
        out.append(Block(kind=kind, text=text, level=level, page=page, flags=tuple(flags)))
    return ParsedDocument(format="pdf", parser_version=doc["parser_version"], blocks=tuple(out),
                          page_count=pages, warnings=tuple(warnings))


if __name__ == "__main__":
    sys.exit(_child_main(sys.argv[1:]))
