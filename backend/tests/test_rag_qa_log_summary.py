"""scripts/ops/rag_qa_log_summary.py: counts, percentiles and alerts from the API's own log lines."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "rag_qa_log_summary.py"
_spec = importlib.util.spec_from_file_location("rag_qa_log_summary", _PATH)
summary_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(summary_tool)

Q = "/v1/crop-seasons/0b4a7d0e-1111-4111-8111-000000000001/questions"


def access(status, ms, path=Q, method="POST", rid="r1", db=30):
    return (f"INFO agricarbon.access access request_id={rid} method={method} path={path} status={status} "
            f"duration_ms={ms} db_calls={db} db_ms=10.0")


def question(rid="r1", llm=0, tier="read_only", error="None", status="answered"):
    return (f"INFO agricarbon.rag rag_question request_id={rid} intent=RagIntent.EXPLAIN mode=RagMode.ASK "
            f"status={status} error={error} llm_calls={llm} input_tokens=0 output_tokens=0 cost_usd=0 "
            f"llm_ms=0 total_ms=200 tier={tier}")


def run(lines, **kw):
    return summary_tool.summarise(lines, **kw)


def test_counts_statuses_and_percentiles_for_question_posts_only():
    lines = [access(200, 100), access(200, 300), access(429, 5), access(401, 3), access(404, 50),
             access(503, 20), access(200, 900, path="/v1/me", method="GET"),
             access(200, 900, method="GET")]
    s = run(lines)
    assert s["questions"] == 6
    assert s["by_status"] == {"200": 2, "401": 1, "404": 1, "429": 1, "503": 1}
    assert (s["rate_limited_429"], s["unauthorized_401"], s["not_found_404"], s["server_errors_5xx"]) == (1, 1, 1, 1)
    assert s["latency_ms"]["p50"] == 20.0 and s["latency_ms"]["p95"] == 300.0 and s["latency_ms"]["max"] == 300.0
    assert s["alerts"] == []  # fewer than min_requests: no rate alerts


def test_llm_calls_on_a_read_only_server_alert():
    s = run([question(rid="x9", llm=1, tier="read_only")])
    assert [a["alert"] for a in s["alerts"]] == ["llm_calls_in_read_only"]
    assert s["alerts"][0]["request_id"] == "x9" and s["llm_calls_total"] == 1


def test_llm_calls_without_a_tier_alert_while_read_only_is_expected():
    assert [a["alert"] for a in run([question(llm=2, tier="unknown")])["alerts"]] == ["llm_calls_nonzero"]
    assert run([question(llm=2, tier="read_and_action")], expect_read_only=False)["alerts"] == []


def test_action_tier_start_up_alerts():
    s = run(["INFO agricarbon.rag rag_question_service tier=read_and_action provider_configured=False"])
    assert [a["alert"] for a in s["alerts"]] == ["action_tier_enabled"]
    assert run(["INFO agricarbon.rag rag_question_service tier=read_only provider=not_loaded"])["alerts"] == []


def test_tenant_isolation_and_backend_alerts():
    s = run([question(error="tenant_isolation_violation", status="error"),
             "ERROR agricarbon.rag rag_tenant_isolation_violation evidence outside scope",
             "ERROR agricarbon.rag rag_alert llm_calls_in_read_only request_id=q7 llm_calls=1"])
    assert [a["alert"] for a in s["alerts"]] == ["tenant_isolation", "tenant_isolation", "rag_alert"]


def test_5xx_rate_and_p95_alerts_need_enough_requests():
    lines = [access(200, 100)] * 18 + [access(503, 9000)] * 2
    s = run(lines)
    assert {a["alert"] for a in s["alerts"]} == {"server_errors", "latency_p95"}
    assert run(lines[:19])["alerts"] == []  # 19 < min_requests


def test_rate_limited_lines_are_counted_by_window():
    s = run(["WARNING agricarbon.rag.rate_limit rag_question_rate_limited request_id=a window=minute retry_after_s=40",
             "WARNING agricarbon.rag.rate_limit rag_question_rate_limited request_id=b window=day retry_after_s=9"])
    assert s["rate_limited_by_window"] == {"minute": 1, "day": 1}


def test_cli_exit_codes_and_json(tmp_path, capsys):
    log = tmp_path / "api.log"
    log.write_text("\n".join([access(200, 10), question()]), encoding="utf-8")
    assert summary_tool.main([str(log), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["questions"] == 1
    assert summary_tool.main([], stdin=io.StringIO(question(llm=1))) == 1
    assert "ALERT llm_calls_in_read_only" in capsys.readouterr().out
    assert summary_tool.main([str(tmp_path / "missing.log")]) == 2


def test_a_lock_refusal_is_not_a_server_error():
    lines = [access(200, 10, rid=f"ok{i}") for i in range(19)] + [access(503, 5, rid="lock1"),
                                                                    question(rid="lock1", error="action_tier_disabled")]
    s = run(lines)
    assert s["server_errors_5xx"] == 0 and s["refused_by_lock_503"] == 1 and s["alerts"] == []
    s = run(lines[:-1])  # same 503 without the lock line: a real server error
    assert s["server_errors_5xx"] == 1 and s["refused_by_lock_503"] == 0


@pytest.mark.parametrize("line", ["", "garbage", "access", "rag_question", "access status=abc duration_ms=x"])
def test_unparseable_lines_are_ignored(line):
    assert run([line])["questions"] == 0
