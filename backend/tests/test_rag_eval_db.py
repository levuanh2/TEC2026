"""The retrieval-eval runner end to end on a LOCAL Supabase stack, through the production
retriever with a real JWT. Corpus and labels are TEST FIXTURES (from
test_rag_retrieval_db.py); the numbers prove the runner, not retrieval quality."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_rag_retrieval_db import _SETTINGS, env, pytestmark  # noqa: E402,F401  (fixture + local-only guard)


def _label(env, key):
    return {"source_id": f"rq-{env['run']}-{key.replace('_', '-')}", "document_id": "doc", "section_path": "Tưới nước"}


def test_runner_scores_fixture_queries_through_the_real_retriever(env, tmp_path, monkeypatch, capsys):  # noqa: F811
    import scripts.eval_retrieval as runner

    rows = [
        {"id": "fx-1", "split": "fixture", "group": "awd-public", "category": "concept", "intent": "explain",
         "question": "hướng dẫn tưới awd ngập khô xen kẽ", "expected": [_label(env, "public")]},
        {"id": "fx-2", "split": "fixture", "group": "awd-htx", "category": "evidence", "intent": "evidence",
         "question": "quy trình awd của htx a", "expected": [_label(env, "org_a_doc")]},
        {"id": "fx-3", "split": "fixture", "group": "no-diacritic", "category": "robustness", "intent": "explain",
         "question": "huong dan tuoi awd", "expected": [_label(env, "public")]},
        {"id": "fx-n1", "split": "fixture", "group": "out-of-corpus", "category": "negative", "intent": "explain",
         "question": "zxqv wpkt jjjj", "negative": True, "expected": []},
    ]
    path = tmp_path / "fixture.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    out = tmp_path / "report.json"
    monkeypatch.setenv("EVAL_ACCESS_TOKEN", env["tokens"]["member"])
    assert runner.main(["--set", str(path), "--season-id", str(env["season_member"]), "--top-k", "8",
                        "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["split"] == "fixture" and report["queries"] == 4
    assert report["hit@5"]["count"] == 3 and report["negative_fpr"]["count"] == 0
    assert report["config"]["min_fused_score"] == 0.0 and report["latency_ms"]["p50"] is not None
    foreign = f"rq-{env['run']}-org-b-doc"
    assert all(item["source_id"] != foreign for q in report["per_query"] for item in q["top"])
    assert env["tokens"]["member"] not in out.read_text(encoding="utf-8")
    assert env["tokens"]["member"] not in capsys.readouterr().out


def test_runner_refuses_without_a_token(monkeypatch, tmp_path):
    import scripts.eval_retrieval as runner

    monkeypatch.delenv("EVAL_ACCESS_TOKEN", raising=False)
    assert runner.main(["--set", str(tmp_path / "x.jsonl"), "--season-id", "x"]) == 2
