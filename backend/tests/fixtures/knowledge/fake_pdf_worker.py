"""A misbehaving stand-in for the PDF worker (tests only; never shipped as a parser).

Run as `python -I -B fake_pdf_worker.py <mode> [args]`; it stands where
infrastructure/pdf_isolation.py would run, so the parent's timeout, kill/reap, output caps
and result validation can be tested without a real hostile PDF.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))      # backend/


def main(mode: str, *args: str) -> int:
    sys.stdin.buffer.read()
    out = sys.stdout.buffer
    if mode == "sleep":
        time.sleep(3600)
    elif mode == "crash":
        os._exit(70)
    elif mode == "flood":                                   # a result far beyond the parent's byte cap
        chunk = b"x" * (1 << 20)
        while True:
            out.write(chunk)
            out.flush()
    elif mode == "garbage":
        out.write(b"\x00\xffnot json")
    elif mode == "json":                                    # args[0]: a JSON payload, args[1]: exit code
        out.write(args[0].encode("utf-8"))
        return int(args[1])
    elif mode == "allocate":                                # POSIX: real limits, then exceed the memory cap
        from infrastructure.pdf_isolation import EXIT_RESOURCE, apply_limits

        apply_limits(256 * 1024 ** 2, 30, 64)
        try:
            blob = bytearray(1024 ** 3)
            out.write(str(len(blob)).encode())
        except MemoryError:
            out.write(b'{"ok": false, "code": "parse_resource_limit"}')
            return EXIT_RESOURCE
    elif mode == "spin":                                    # POSIX: real limits, then exceed the CPU cap
        from infrastructure.pdf_isolation import apply_limits

        apply_limits(1024 ** 3, 1, 64)
        while True:
            pass
    elif mode == "limits":                                  # POSIX: report what apply_limits installs
        import resource

        from infrastructure.pdf_isolation import apply_limits

        apply_limits(int(args[0]), int(args[1]), int(args[2]))
        names = ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NOFILE")
        out.write(json.dumps({n: resource.getrlimit(getattr(resource, n)) for n in names}).encode())
        return 0
    elif mode == "env":
        out.write(json.dumps(sorted(os.environ)).encode())
        return 0
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
