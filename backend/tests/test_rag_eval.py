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


# -- precision@k, recall@k, f1@k, ndcg@k (L2 evaluation, 2026-11-27) ------------------------------

import math  # noqa: E402

from rag_eval import EvalQuery, Label, f1_at, ndcg_at, precision_at, recall_at  # noqa: E402

A, B, C = Label("s", "d", "A"), Label("s", "d", "B"), Label("s", "d", "C")


def _graded():
    # expected A and B, acceptable C; ranking: Z, A, A > A.1, C, B
    query = EvalQuery("g", "dev", "g", "concept", "explain", "q", False, (A, B), (C,))
    return judge(query, [_chunk("Z"), _chunk("A"), _chunk("A > A.1"), _chunk("C"), _chunk("B")], 1.0)


def test_precision_counts_relevant_chunks_over_k_and_never_rewards_a_short_list():
    o = _graded()
    assert o.relevant_ranks == (2, 3, 4, 5)
    assert [precision_at(o, k) for k in (1, 3, 5, 10)] == [0.0, 2 / 3, 4 / 5, 4 / 10]


def test_recall_counts_expected_labels_found_within_k():
    o = _graded()
    assert [recall_at(o, k) for k in (1, 3, 5, 10)] == [0.0, 0.5, 1.0, 1.0]


def test_f1_is_the_per_query_harmonic_mean():
    o = _graded()
    assert f1_at(o, 1) == 0.0
    assert f1_at(o, 3) == pytest.approx(4 / 7)
    assert f1_at(o, 5) == pytest.approx(8 / 9)


def test_ndcg_credits_each_label_once_with_graded_gains():
    o = _graded()
    ideal = 2 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    dcg5 = 2 / math.log2(3) + 1 / math.log2(5) + 2 / math.log2(6)  # A@2, C@4, B@5 (A > A.1 is not a 2nd credit)
    assert ndcg_at(o, 5) == pytest.approx(dcg5 / ideal)
    assert ndcg_at(o, 1) == 0.0
    perfect = judge(EvalQuery("p", "dev", "p", "concept", "explain", "q", False, (A, B), (C,)),
                    [_chunk("A"), _chunk("B"), _chunk("C")], 1.0)
    assert ndcg_at(perfect, 3) == pytest.approx(1.0)


def test_recall_at_5_no_longer_counts_a_label_found_at_rank_7():
    # Before: expected_found was measured in the top 8 and reused for every k, so recall@5 == recall@8.
    query = EvalQuery("r", "dev", "r", "concept", "explain", "q", False, (A,))
    o = judge(query, [_chunk("Z")] * 6 + [_chunk("A")], 1.0)
    report = score([query], [o])
    assert report["recall@5"] == 0.0 and report["recall@8"] == 1.0 and report["recall@10"] == 1.0


def test_score_reports_every_requested_cutoff_over_positives_only(tmp_path):
    queries = load_eval_set(_write(tmp_path, [_q("p1"), _q("n1", negative=True, category="negative")]))
    outcomes = [judge(queries[0], [_chunk()], 1.0), judge(queries[1], [_chunk("Z")], 1.0)]
    report = score(queries, outcomes)
    for k in (1, 3, 5, 10):
        assert f"precision@{k}" in report and f"f1@{k}" in report and f"ndcg@{k}" in report and f"recall@{k}" in report
    assert report["precision@1"] == 1.0 and report["precision@3"] == pytest.approx(1 / 3)
    assert report["ndcg@1"] == 1.0  # the negative query's false positive is not averaged in
