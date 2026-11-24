"""Summarise the API's own log lines for the season Q&A pilot and raise alerts. Offline, stdlib only.

    docker logs --since 15m <api container> 2>&1 | python scripts/ops/rag_qa_log_summary.py
    python scripts/ops/rag_qa_log_summary.py api.log --json

Reads only lines the backend already writes (no question text, token, key or user id is in them):
  access request_id=.. method=POST path=/v1/crop-seasons/<id>/questions status=.. duration_ms=.. db_calls=..
  rag_question request_id=.. intent=.. mode=.. status=.. error=.. llm_calls=.. ... tier=..
  rag_question_service tier=read_only|read_and_action ...
  rag_question_rate_limited request_id=.. window=..
  rag_question_rate_store_error type=..
  rag_question_cohort mode=allow_list|closed|open_to_all_signed_in_users users=..
  rag_alert ...

Alerts (exit code 1; thresholds are PROPOSED, pending the owner's A-13 decision):
  llm_calls_in_read_only   any rag_question line with tier=read_only and llm_calls > 0
  llm_calls_nonzero        any llm_calls > 0 while --expect-read-only (default on)
  action_tier_enabled      a rag_question_service tier=read_and_action start-up line
  rag_alert                any `rag_alert` line the backend wrote
  tenant_isolation         any rag_tenant_isolation_violation / error=tenant_isolation_violation
  cohort_unrestricted      a rag_question_cohort mode=open_to_all_signed_in_users start-up line (RAG_QA_ALLOWED_USER_IDS=*)
  quota_store_unavailable  any rag_question_rate_store_error line (the question was refused 503, fail closed)
  server_errors            5xx share of questions (deliberate 503 action_tier_disabled excluded) > --max-5xx-rate (default 0.02) with >= --min-requests
  latency_p95              p95 duration of questions > --max-p95-ms (default 8000) with >= --min-requests
Exit 0 = no alert, 1 = alert(s), 2 = unreadable input.
Not covered here: an API that does not start at all writes no Q&A line; watch the container / health
probe for that.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from typing import Iterable, TextIO

QUESTION_PATH = re.compile(r"^/v1/crop-seasons/[^/\s]+/questions$")
FIELD = re.compile(r"(\w+)=(\S*)")


def fields(line: str, marker: str) -> dict[str, str] | None:
    at = line.find(marker + " ")
    if at < 0:
        return None
    return dict(FIELD.findall(line[at + len(marker):]))


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def summarise(lines: Iterable[str], *, expect_read_only: bool = True, max_5xx_rate: float = 0.02,
              max_p95_ms: float = 8000.0, min_requests: int = 20) -> dict:
    statuses: Counter[int] = Counter()
    status_by_request: list[tuple[str | None, int]] = []
    error_by_request: dict[str, str] = {}
    durations: list[float] = []
    db_calls: list[int] = []
    errors: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    windows: Counter[str] = Counter()
    cohort_modes: Counter[str] = Counter()
    store_errors = 0
    llm_calls_total = 0
    alerts: list[dict] = []

    def alert(kind: str, detail: str, request_id: str | None = None) -> None:
        alerts.append({"alert": kind, "detail": detail, "request_id": request_id})

    for line in lines:
        access = fields(line, "access")
        if access and access.get("method") == "POST" and QUESTION_PATH.match(access.get("path", "")):
            statuses[_int(access.get("status"))] += 1
            status_by_request.append((access.get("request_id"), _int(access.get("status"))))
            try:
                durations.append(float(access.get("duration_ms", "")))
            except ValueError:
                pass
            db_calls.append(_int(access.get("db_calls")))
            continue
        question = fields(line, "rag_question")
        if question is not None and "request_id" in question:
            calls = _int(question.get("llm_calls"))
            llm_calls_total += calls
            tier = question.get("tier") or "unknown"
            tiers[tier] += 1
            if question.get("error") not in (None, "", "None"):
                errors[question["error"]] += 1
                error_by_request[question.get("request_id") or ""] = question["error"]
            if question.get("error") == "tenant_isolation_violation":
                alert("tenant_isolation", "a question ended in tenant_isolation_violation", question.get("request_id"))
            if calls > 0 and tier == "read_only":
                alert("llm_calls_in_read_only", f"llm_calls={calls} on a READ-only server", question.get("request_id"))
            elif calls > 0 and expect_read_only:
                alert("llm_calls_nonzero", f"llm_calls={calls} while READ-only is expected", question.get("request_id"))
            continue
        service = fields(line, "rag_question_service")
        if service is not None and service.get("tier") == "read_and_action":
            alert("action_tier_enabled", "the API started with RAG_QA_ACTION_TIER_ENABLED=true")
            continue
        limited = fields(line, "rag_question_rate_limited")
        if limited is not None:
            windows[limited.get("window") or "unknown"] += 1
            continue
        cohort = fields(line, "rag_question_cohort")
        if cohort is not None:
            mode = cohort.get("mode") or "unknown"
            cohort_modes[mode] += 1
            if mode == "open_to_all_signed_in_users":
                alert("cohort_unrestricted", "the API started with RAG_QA_ALLOWED_USER_IDS=* (every signed-in user)")
            continue
        store_error = fields(line, "rag_question_rate_store_error")
        if store_error is not None:
            store_errors += 1
            alert("quota_store_unavailable", f"rate-limit store error type={store_error.get('type', '?')}")
            continue
        if "rag_tenant_isolation_violation" in line:
            alert("tenant_isolation", "rag_tenant_isolation_violation logged")
            continue
        backend_alert = fields(line, "rag_alert")
        if backend_alert is not None:
            alert("rag_alert", " ".join(f"{k}={v}" for k, v in sorted(backend_alert.items())),
                  backend_alert.get("request_id"))

    total = sum(statuses.values())
    # A deliberate refusal (READ-only lock, Q&A switched off) is a 503 but not a server fault.
    deliberate = {"action_tier_disabled", "backend_not_configured"}
    locked = sum(1 for rid, code in status_by_request if code == 503 and error_by_request.get(rid or "") in deliberate)
    server_errors = sum(n for code, n in statuses.items() if code >= 500) - locked
    p50, p95 = percentile(durations, 0.50), percentile(durations, 0.95)
    if total >= min_requests and server_errors / total > max_5xx_rate:
        alert("server_errors", f"{server_errors}/{total} questions were 5xx (> {max_5xx_rate:.0%})")
    if total >= min_requests and p95 is not None and p95 > max_p95_ms:
        alert("latency_p95", f"p95 {p95:.0f} ms > {max_p95_ms:.0f} ms over {total} questions")
    return {
        "questions": total,
        "by_status": {str(code): n for code, n in sorted(statuses.items())},
        "rate_limited_429": statuses.get(429, 0),
        "rate_limited_by_window": dict(windows),
        "rate_store_errors": store_errors,
        "cohort_modes_seen": dict(cohort_modes),
        "unauthorized_401": statuses.get(401, 0),
        "forbidden_403": statuses.get(403, 0),
        "not_found_404": statuses.get(404, 0),
        "server_errors_5xx": server_errors,
        "refused_by_lock_503": locked,
        "latency_ms": {"p50": p50, "p95": p95, "max": max(durations) if durations else None},
        "db_calls": {"p50": percentile([float(n) for n in db_calls], 0.50), "max": max(db_calls) if db_calls else None},
        "llm_calls_total": llm_calls_total,
        "tiers_seen": dict(tiers),
        "errors": dict(errors),
        "alerts": alerts,
    }


def render(summary: dict) -> str:
    lat = summary["latency_ms"]
    out = [f"questions={summary['questions']} by_status={summary['by_status']}",
           f"429={summary['rate_limited_429']} {summary['rate_limited_by_window']} 401={summary['unauthorized_401']} "
           f"403={summary['forbidden_403']} 404={summary['not_found_404']} 5xx={summary['server_errors_5xx']} "
           f"refused_by_lock_503={summary['refused_by_lock_503']}",
           f"latency_ms p50={lat['p50']} p95={lat['p95']} max={lat['max']} db_calls={summary['db_calls']}",
           f"llm_calls_total={summary['llm_calls_total']} tiers={summary['tiers_seen']} errors={summary['errors']}"]
    out += [f"ALERT {a['alert']}: {a['detail']}" + (f" request_id={a['request_id']}" if a["request_id"] else "")
            for a in summary["alerts"]]
    out.append("OK: no alert" if not summary["alerts"] else f"ALERTS: {len(summary['alerts'])}")
    return "\n".join(out)


def main(argv: list[str] | None = None, stdin: TextIO = sys.stdin) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("log", nargs="?", help="log file (default: stdin)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-action-tier", action="store_true",
                    help="do not alert on llm_calls > 0 outside a read_only tier line")
    ap.add_argument("--max-5xx-rate", type=float, default=0.02)
    ap.add_argument("--max-p95-ms", type=float, default=8000.0)
    ap.add_argument("--min-requests", type=int, default=20)
    args = ap.parse_args(argv)
    try:
        if args.log:
            with open(args.log, encoding="utf-8", errors="replace") as handle:
                summary = summarise(handle, expect_read_only=not args.allow_action_tier,
                                    max_5xx_rate=args.max_5xx_rate, max_p95_ms=args.max_p95_ms,
                                    min_requests=args.min_requests)
        else:
            summary = summarise(stdin, expect_read_only=not args.allow_action_tier,
                                max_5xx_rate=args.max_5xx_rate, max_p95_ms=args.max_p95_ms,
                                min_requests=args.min_requests)
    except OSError as exc:
        print(f"rag_qa_log_summary: cannot read input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1) if args.json else render(summary))
    return 1 if summary["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
