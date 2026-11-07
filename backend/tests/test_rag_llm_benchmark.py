"""The provider benchmark script runs end to end with a fake provider (no network)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.rag_llm_benchmark as bench  # noqa: E402
from infrastructure.llm_client import LlmCompletion, LlmUsage  # noqa: E402

ANSWER = {"status": "generated", "answer": "Theo tài liệu, tưới ngập khô xen kẽ giảm khí mê-tan.",
          "evidence_refs": [{"source_id": "fixture-awd", "chunk_id": "a1"}],
          "recommendations": [{"title": "Cân nhắc tưới ngập khô xen kẽ", "rule_code": bench.RULE,
                               "evidence_refs": [{"source_id": "fixture-awd", "chunk_id": "a1"}]}]}


class FakeClient:
    def complete_json(self, *, system, user, schema):
        return LlmCompletion(data=ANSWER, usage=LlmUsage(900, 150, 1050, 0.0005), latency_ms=10, model="fake",
                             finish_reason="STOP")


def test_no_provider_exits_2(monkeypatch):
    monkeypatch.delenv("RAG_LLM_PROVIDER", raising=False)
    assert bench.main([]) == 2


def test_report_counts_outcomes_latency_and_cost(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("RAG_LLM_MODEL", "fake")
    monkeypatch.setenv("RAG_LLM_API_KEY", "not-a-key")
    monkeypatch.setattr(bench, "build_llm_client", lambda settings: FakeClient())
    out = tmp_path / "report.json"
    assert bench.main(["--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cases"] == len(bench.CASES)
    # the what-if case cites no what-if fact -> refused by grounding; the rest are grounded
    assert report["outcomes"]["generated"] == len(bench.CASES) - 1 and report["outcomes"]["refused"] == 1
    assert report["cost_usd_mean_per_answer"] == 0.0005 and report["latency_ms"]["p50"] is not None
    assert "not-a-key" not in capsys.readouterr().out
