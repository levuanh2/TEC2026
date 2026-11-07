"""The provider benchmark script runs end to end with fake providers (no network)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.rag_llm_benchmark as bench  # noqa: E402
from infrastructure.llm_client import LlmCompletion, LlmUsage  # noqa: E402

#: A careless model: always recommends the AWD rule, whatever the question or evidence.
CARELESS = {"status": "generated", "answer": "Theo tài liệu, tưới ngập khô xen kẽ giảm khí mê-tan.",
            "evidence_refs": [{"source_id": "fixture-awd", "chunk_id": "a1"}],
            "recommendations": [{"title": "Cân nhắc tưới ngập khô xen kẽ", "rule_code": bench.RULE,
                                 "evidence_refs": [{"source_id": "fixture-awd", "chunk_id": "a1"}]}]}


class CarelessClient:
    def __init__(self):
        self.calls = 0

    def complete_json(self, *, system, user, schema):
        self.calls += 1
        return LlmCompletion(data=CARELESS, usage=LlmUsage(900, 150, 1050, 0.0005), latency_ms=10, model="careless",
                             finish_reason="STOP")


def _configure(monkeypatch, client):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("RAG_LLM_MODEL", "careless")
    monkeypatch.setenv("RAG_LLM_API_KEY", "not-a-key")
    monkeypatch.setattr(bench, "build_llm_client", lambda settings: client)


def test_no_provider_exits_2(monkeypatch):
    monkeypatch.delenv("RAG_LLM_PROVIDER", raising=False)
    assert bench.main([]) == 2


def test_a_careless_model_fails_the_safety_gates(monkeypatch, tmp_path, capsys):
    client = CarelessClient()
    _configure(monkeypatch, client)
    out = tmp_path / "careless.json"
    assert bench.main(["--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cases"] == len(bench.CASES)
    metrics = report["metrics"]
    # it "answers" the pesticide, injection and off-topic cases instead of declining
    assert metrics["correct_refusal_rate"] < 1.0 and metrics["injection_resistance"] < 1.0
    assert report["quality_gates"]["passed"] is False
    assert {"correct_refusal_rate", "injection_resistance"} <= set(report["quality_gates"]["failed"])
    # the no-rule and no-evidence cases never reach the provider, whatever the model
    assert metrics["no_model_cases_skip_provider"] == 1.0
    assert client.calls == len(bench.CASES) - 2
    assert report["cost_usd_mean_per_answer"] == 0.0005 and report["latency_ms"]["p50"] is not None
    assert "not-a-key" not in capsys.readouterr().out


def test_the_scripted_model_passes_and_validates_the_harness(tmp_path):
    out = tmp_path / "fake.json"
    assert bench.main(["--fake", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["quality_gates"]["passed"] is True, report["quality_gates"]
    assert report["metrics"]["grounding_success_rate"] == 1.0 and report["metrics"]["vietnamese_heuristic"] == 1.0
    assert report["cost_usd_mean_per_answer"] is None  # a fake has no price: never a made-up cost


def _report(path, model, passed, cost):
    path.write_text(json.dumps({"model": model, "quality_gates": {"passed": passed, "failed": [] if passed else ["x"]},
                                "cost_usd_mean_per_answer": cost, "latency_ms": {"p95": 1}}), encoding="utf-8")
    return str(path)


def test_choose_takes_the_cheapest_candidate_that_passes(tmp_path, capsys):
    lite = _report(tmp_path / "a.json", "gemini-2.5-flash-lite", False, 0.0004)
    flash = _report(tmp_path / "b.json", "gemini-2.5-flash", True, 0.002)
    assert bench.main(["--choose", lite, flash]) == 0
    assert "CHOICE: gemini-2.5-flash" in capsys.readouterr().out
    lite_ok = _report(tmp_path / "c.json", "gemini-2.5-flash-lite", True, 0.0004)
    assert bench.main(["--choose", lite_ok, flash]) == 0
    assert "CHOICE: gemini-2.5-flash-lite" in capsys.readouterr().out


def test_choose_refuses_when_nothing_passes(tmp_path):
    assert bench.main(["--choose", _report(tmp_path / "a.json", "m", False, 0.001)]) == 3
