"""Process-isolated PDF parsing (infrastructure/pdf_isolation.py), RAG V1.3-C.

Real worker: identical output to the in-process parser, scans/encrypted/malformed still
refused, result validation. A misbehaving stand-in worker (fixtures/knowledge/
fake_pdf_worker.py) covers timeout, crash, flooding, malformed/inconsistent output, secret-free
environment and, on POSIX, the installed resource limits and their enforcement. Every spawned
process must be reaped. No real decompression bomb is used. Runs under Windows spawn semantics
(subprocess, never fork) and on Linux CI.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure import pdf_isolation as iso  # noqa: E402
from knowledge.models import Block, ParseError  # noqa: E402
from knowledge.parsers import pdf  # noqa: E402
from tests.fixtures.knowledge import FIXTURE, HERE, make_pdf  # noqa: E402

FAKE = HERE / "fake_pdf_worker.py"
POSIX = sys.platform != "win32"
PAGES = [[FIXTURE, f"1.{i} Mực nước", "Tưới ướt khô xen kẽ giúp giảm phát thải mê-", "tan.", f"Trang {i}"]
         for i in range(1, 4)]


@pytest.fixture(scope="module")
def good_pdf() -> bytes:
    return make_pdf(PAGES)


@pytest.fixture
def spawned(monkeypatch):
    """Record every process parse_pdf_isolated spawns (and its arguments)."""
    procs, calls = [], []
    real = subprocess.Popen

    def recording(*args, **kwargs):
        calls.append((args, kwargs))
        proc = real(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(iso.subprocess, "Popen", recording)
    return procs, calls


def fake(monkeypatch, *mode: str):
    monkeypatch.setattr(iso, "_worker_command", lambda timeout: [sys.executable, "-I", "-B", str(FAKE), *mode])


def _alive(pid: int) -> bool:
    if POSIX:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _all_reaped(procs):
    assert procs and all(p.returncode is not None for p in procs)
    assert not any(_alive(p.pid) for p in procs)
    assert all(p.stdin.closed and p.stdout.closed and p.stderr.closed for p in procs)


# ------------------------------------------------------------------ real worker

def test_isolated_output_is_identical_and_deterministic(good_pdf, spawned):
    first, second = iso.parse_pdf_isolated(good_pdf), iso.parse_pdf_isolated(good_pdf)
    assert first == second == pdf.parse(good_pdf)
    _all_reaped(spawned[0])


@pytest.mark.parametrize(("make", "code"), [
    (lambda: make_pdf([[], [], []]), "no_text_layer"),
    (lambda: b"%PDF-1.4\n%not really a pdf", "malformed"),
])
def test_scans_and_malformed_pdfs_are_still_refused(make, code, spawned):
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(make())
    assert err.value.code == code
    _all_reaped(spawned[0])


def test_encrypted_pdf_is_still_refused(good_pdf):
    import pypdf

    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(good_pdf)))
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(buf.getvalue())
    assert err.value.code == "encrypted"


def test_the_child_gets_no_secret_and_runs_isolated(monkeypatch, spawned, good_pdf):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret-key")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres:pw@host/db")
    iso.parse_pdf_isolated(good_pdf)
    (args, kwargs), = spawned[1]
    command = args[0]
    assert command[:3] == [sys.executable, "-I", "-B"] and command[3].endswith("pdf_isolation.py")
    assert not {k for k in kwargs["env"] if "SUPABASE" in k or "KEY" in k or "TOKEN" in k}
    fake(monkeypatch, "env")
    with pytest.raises(ParseError):                       # "env" output is not a parse result...
        iso.parse_pdf_isolated(b"%PDF-1.4")
    env_raw = subprocess.run([sys.executable, "-I", "-B", str(FAKE), "env"], input=b"", capture_output=True,
                             env=iso._child_env()).stdout
    assert not [k for k in json.loads(env_raw) if "SUPABASE" in k]


def test_parser_result_text_over_the_limit_is_rejected_by_the_parent(monkeypatch, good_pdf):
    monkeypatch.setattr(pdf, "MAX_TEXT_CHARS", 10)       # the parent's check; the child is unaffected
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(good_pdf)
    assert err.value.code == "extraction_limit_exceeded"


# ------------------------------------------------------------------ misbehaving worker

def _interpreter_pid(path: Path) -> int:
    for _ in range(100):                                   # the worker writes it right after starting
        if path.exists() and path.read_text():
            return int(path.read_text())
        time.sleep(0.05)
    raise AssertionError("the worker never reported its pid")


def test_a_worker_that_never_finishes_is_terminated_and_reaped(monkeypatch, spawned, tmp_path):
    pid_file = tmp_path / "pid"
    fake(monkeypatch, "sleep", str(pid_file))
    started = time.monotonic()
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4", timeout=3)
    assert err.value.code == "parse_timeout" and time.monotonic() - started < 15
    _all_reaped(spawned[0])
    real = _interpreter_pid(pid_file)                       # the interpreter itself, not only a launcher
    deadline = time.monotonic() + 5
    while _alive(real) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(real)


def test_repeated_timeouts_leak_no_process(monkeypatch, spawned, tmp_path):
    pids = []
    for i in range(3):
        pid_file = tmp_path / f"pid{i}"
        fake(monkeypatch, "sleep", str(pid_file))
        with pytest.raises(ParseError):
            iso.parse_pdf_isolated(b"%PDF-1.4", timeout=3)
        pids.append(_interpreter_pid(pid_file))
    assert len(spawned[0]) == 3
    _all_reaped(spawned[0])
    deadline = time.monotonic() + 5
    while any(_alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not any(_alive(p) for p in pids)


def test_a_crashing_worker_is_a_typed_failure(monkeypatch, spawned):
    fake(monkeypatch, "crash")
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4")
    assert err.value.code == "parse_worker_crashed"
    _all_reaped(spawned[0])


def test_a_flooding_worker_is_cut_off_at_the_byte_cap(monkeypatch, spawned):
    fake(monkeypatch, "flood")
    monkeypatch.setattr(iso, "MAX_RESULT_BYTES", 2 * 1024 * 1024)
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4", timeout=30)
    assert err.value.code == "extraction_limit_exceeded"
    _all_reaped(spawned[0])


@pytest.mark.parametrize("mode", [("garbage",), ("json", '{"ok": true}', "0"), ("json", "[1, 2]", "0"),
                                  ("json", '{"ok": true, "code": "malformed"}', "2"),
                                  ("json", '{"ok": false, "code": "rm -rf", "message": "x"}', "2"),
                                  ("json", '{"ok": false, "code": "malformed", "message": "x"}', "0")])
def test_malformed_or_inconsistent_worker_output_is_rejected(monkeypatch, spawned, mode):
    fake(monkeypatch, *mode)
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4")
    assert err.value.code == "parse_worker_protocol"
    _all_reaped(spawned[0])


def test_a_worker_error_code_is_passed_through_only_when_known(monkeypatch):
    fake(monkeypatch, "json", '{"ok": false, "code": "no_text_layer", "message": "scan"}', "2")
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4")
    assert (err.value.code, str(err.value)) == ("no_text_layer", "scan")


# ------------------------------------------------------------------ result validation (in-process)

def _payload(**change):
    doc = {"ok": True, "format": "pdf", "parser_version": pdf.PARSER_VERSION, "page_count": 2, "warnings": [],
           "blocks": [{"kind": "heading", "text": "1.1 A", "level": 2, "page": 1, "flags": []},
                      {"kind": "paragraph", "text": "b", "level": 0, "page": 2, "flags": ["page_last"]}]}
    doc.update(change)
    return json.dumps(doc).encode()


def test_a_valid_result_becomes_a_parsed_document():
    parsed = iso._decode(0, _payload(), b"")
    assert parsed.blocks[0] == Block(kind="heading", text="1.1 A", level=2, page=1)
    assert parsed.page_count == 2 and parsed.parser_version == pdf.PARSER_VERSION


@pytest.mark.parametrize("change", [
    {"format": "markdown"}, {"parser_version": "kn-pdf-1+pypdf-0.0.0"}, {"page_count": 0}, {"page_count": True},
    {"page_count": 99999}, {"warnings": "x"}, {"warnings": [1]}, {"extra": 1},
    {"blocks": [{"kind": "script", "text": "x", "level": 0, "page": 1, "flags": []}]},
    {"blocks": [{"kind": "paragraph", "text": 5, "level": 0, "page": 1, "flags": []}]},
    {"blocks": [{"kind": "paragraph", "text": "x", "level": 2, "page": 1, "flags": []}]},
    {"blocks": [{"kind": "heading", "text": "x", "level": 0, "page": 1, "flags": []}]},
    {"blocks": [{"kind": "paragraph", "text": "x", "level": 0, "page": 3, "flags": []}]},
    {"blocks": [{"kind": "paragraph", "text": "x", "level": 0, "page": 1, "flags": ["evil"]}]},
    {"blocks": [{"kind": "paragraph", "text": "x", "level": 0, "page": 1}]},
    {"blocks": "x"},
])
def test_invalid_result_shapes_are_rejected(change):
    with pytest.raises(ParseError) as err:
        iso._decode(0, _payload(**change), b"")
    assert err.value.code == "parse_worker_protocol"


def test_too_many_blocks_in_a_result_are_rejected(monkeypatch):
    import knowledge.models as models

    monkeypatch.setattr(models, "MAX_BLOCKS", 1)
    with pytest.raises(ParseError):
        iso._decode(0, _payload(), b"")


@pytest.mark.parametrize(("code", "expected"), [(3, "parse_resource_limit"), (-9, "parse_resource_limit"),
                                                (-24, "parse_resource_limit"), (1, "parse_worker_crashed"),
                                                (-11, "parse_worker_crashed")])
def test_exit_statuses_map_to_typed_failures(code, expected):
    with pytest.raises(ParseError) as err:
        iso._decode(code, b"", b"Traceback\nSomeError: boom\n")
    assert err.value.code == expected


def test_run_worker_in_process(good_pdf, monkeypatch):
    code, payload = iso.run_worker(good_pdf)
    assert code == iso.EXIT_OK and iso._decode(code, payload, b"") == pdf.parse(good_pdf)
    code, payload = iso.run_worker(make_pdf([[]]))
    assert code == iso.EXIT_PARSE_ERROR and json.loads(payload)["code"] == "no_text_layer"

    def oom(data):
        raise MemoryError

    monkeypatch.setattr(pdf, "parse", oom)
    assert iso.run_worker(good_pdf)[0] == iso.EXIT_RESOURCE


def test_child_main_reads_stdin_and_writes_one_result(good_pdf, monkeypatch):
    monkeypatch.setattr(iso, "apply_limits", lambda *a: False)       # never limit the test process itself
    stdout = io.BytesIO()
    monkeypatch.setattr(iso.sys, "stdin", type("I", (), {"buffer": io.BytesIO(good_pdf)})())
    monkeypatch.setattr(iso.sys, "stdout", type("O", (), {"buffer": stdout})())
    assert iso._child_main(["1", "2", "3"]) == iso.EXIT_OK
    assert iso._decode(0, stdout.getvalue(), b"") == pdf.parse(good_pdf)


def test_apply_limits_is_a_no_op_without_resource(monkeypatch):
    if POSIX:
        monkeypatch.setitem(sys.modules, "resource", None)        # import resource -> ImportError
    assert iso.apply_limits(1, 1, 1) is False


# ------------------------------------------------------------------ POSIX resource limits

posix_only = pytest.mark.skipif(not POSIX, reason="`resource` limits exist only on POSIX (Linux CI)")


@posix_only
def test_the_child_installs_the_intended_limits():
    out = subprocess.run([sys.executable, "-I", "-B", str(FAKE), "limits", str(512 * 1024 ** 2), "7", "48"],
                         input=b"", capture_output=True, timeout=60, env=iso._child_env())
    limits = json.loads(out.stdout)
    assert limits == {"RLIMIT_AS": [512 * 1024 ** 2] * 2, "RLIMIT_CPU": [7, 8], "RLIMIT_FSIZE": [0, 0],
                      "RLIMIT_NOFILE": [48, 48]}


@posix_only
def test_the_memory_limit_is_enforced_as_parse_resource_limit(monkeypatch, spawned):
    fake(monkeypatch, "allocate")
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4", timeout=60)
    assert err.value.code == "parse_resource_limit"
    _all_reaped(spawned[0])


@posix_only
def test_the_cpu_limit_is_enforced_as_parse_resource_limit(monkeypatch, spawned):
    fake(monkeypatch, "spin")
    with pytest.raises(ParseError) as err:
        iso.parse_pdf_isolated(b"%PDF-1.4", timeout=60)
    assert err.value.code == "parse_resource_limit"
    _all_reaped(spawned[0])


@posix_only
def test_the_real_worker_command_installs_limits_before_parsing(good_pdf):
    command = iso._worker_command(5)
    assert command[4:] == [str(iso.PDF_WORKER_MEMORY_BYTES), "5", str(iso.PDF_WORKER_OPEN_FILES)]
    assert iso.parse_pdf_isolated(good_pdf, timeout=30) == pdf.parse(good_pdf)
