"""Retrieval-eval metrics (rag_eval.py) on hand-built rankings — no database."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_eval import EvalSetError, judge, load_eval_set, score  # noqa: E402


def _write(tmp_path, rows):
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def _q(id, *, group=None, split="dev", negative=False, expected=None, category="concept"):
    return {"id": id, "split": split, "group": group or id, "category": category, "intent": "explain",
            "question": f"q {id}", "negative": negative,
            "expected": [] if negative else (expected or [{"source_id": "s", "document_id": "d", "section_path": "A"}])}


def _chunk(section="A", source="s", doc="d", chunk="c"):
    return {"source_id": source, "document_id": doc, "section": section, "chunk_id": chunk}


def test_loader_rejects_leakage_duplicates_and_bad_labels(tmp_path):
    with pytest.raises(EvalSetError, match="two splits"):
        load_eval_set(_write(tmp_path, [_q("a", group="g"), _q("b", group="g", split="holdout")]))
    with pytest.raises(EvalSetError, match="duplicate"):
        load_eval_set(_write(tmp_path, [_q("a"), _q("a", group="x")]))
    with pytest.raises(EvalSetError, match="negative"):
        load_eval_set(_write(tmp_path, [{**_q("n", negative=True), "expected": [{"source_id": "s", "document_id": "d"}]}]))
    with pytest.raises(EvalSetError, match="positive"):
        load_eval_set(_write(tmp_path, [{**_q("p"), "expected": []}]))
    with pytest.raises(EvalSetError, match="split"):
        load_eval_set(_write(tmp_path, [_q("a", split="train")]))


def test_section_labels_match_the_section_and_its_subsections():
    rows = [_chunk("B"), _chunk("A > A.1")]
    from rag_eval import EvalQuery, Label
    query = EvalQuery("x", "dev", "g", "concept", "explain", "q", False, (Label("s", "d", "A"),))
    outcome = judge(query, rows, 5.0)
    assert outcome.first_rank == 2 and outcome.expected_found == 1


def test_chunk_id_labels_are_exact():
    from rag_eval import EvalQuery, Label
    query = EvalQuery("x", "dev", "g", "concept", "explain", "q", False, (Label("s", "d", None, ("c2",)),))
    assert judge(query, [_chunk(chunk="c1"), _chunk(chunk="c2")], 1.0).first_rank == 2


def test_metrics_hit_mrr_fpr_and_empty_rate(tmp_path):
    queries = load_eval_set(_write(tmp_path, [_q("p1"), _q("p2"), _q("p3"), _q("n1", negative=True, category="negative"),
                                              _q("n2", negative=True, category="negative")]))
    rankings = {"p1": [_chunk()], "p2": [_chunk("Z"), _chunk("Z"), _chunk()], "p3": [],
                "n1": [], "n2": [_chunk("Z")]}
    outcomes = [judge(q, rankings[q.id], float(i)) for i, q in enumerate(queries)]
    report = score(queries, outcomes)
    assert report["hit@1"] == {"count": 1, "of": 3, "rate": 1 / 3}
    assert report["hit@3"]["count"] == 2 and report["hit@5"]["count"] == 2
    assert report["mrr@10"] == pytest.approx((1 + 1 / 3) / 3)
    assert report["negative_fpr"] == {"count": 1, "of": 2, "rate": 0.5}
    assert report["empty_result_rate"]["count"] == 1
    assert sorted(report["failed_queries"]) == ["n2", "p3"]
    assert report["categories"]["negative"]["negative_false_positive"] == 1


def test_one_split_per_score(tmp_path):
    queries = load_eval_set(_write(tmp_path, [_q("a", split="dev"), _q("b", split="holdout")]))
    with pytest.raises(EvalSetError, match="one split"):
        score(queries, [judge(q, [], 0.0) for q in queries])
