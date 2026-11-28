"""L2 eval framework (rag_eval_framework.py): label provenance, method comparison, answer metrics.
Toy rankings only — no model, database or provider. Numbers here test the arithmetic, not a method."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_eval import EvalSetError, load_eval_set  # noqa: E402
from rag_eval_framework import (  # noqa: E402
    DRAFT, VALIDATED, Citation, Claim, JudgedAnswer, answer_metrics, compare_methods, label_status, load_provenance,
)


def _write(tmp_path, rows):
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def _row(id, **extra):
    return {"id": id, "split": "dev", "group": id, "category": "concept", "intent": "explain", "question": f"q {id}",
            "expected": [{"source_id": "s", "document_id": "d", "section_path": "A"}], **extra}


VALID = {"label_status": VALIDATED, "validated_by": ["expert-1"], "label_set_id": "rice-v1", "validated_at": "2026-12-01"}


def _chunk(section, chunk_id="c"):
    return {"source_id": "s", "document_id": "d", "section": section, "chunk_id": chunk_id}


def good(q):
    return [_chunk("A", "a1"), _chunk("B", "b1")]


def bad(q):
    return [_chunk("B", "b1"), _chunk("C", "c1")]


# -- provenance -------------------------------------------------------------------------------------

def test_a_row_without_status_is_a_draft_and_nothing_is_official(tmp_path):
    path = _write(tmp_path, [_row("q1"), _row("q2", **VALID)])
    status = label_status(load_eval_set(path), load_provenance(path))
    assert status == {"queries": 2, "expert_validated": 1, "official": False, "label_set_id": None, "status": DRAFT}


def test_validated_needs_a_named_expert_a_set_id_and_a_date(tmp_path):
    for missing in ("validated_by", "label_set_id", "validated_at"):
        row = _row("q1", **{k: v for k, v in VALID.items() if k != missing})
        with pytest.raises(EvalSetError):
            load_provenance(_write(tmp_path, [row]))
    with pytest.raises(EvalSetError):
        load_provenance(_write(tmp_path, [_row("q1", label_status="approved_by_model")]))


def test_two_label_sets_in_one_split_are_not_official(tmp_path):
    path = _write(tmp_path, [_row("q1", **VALID), _row("q2", **{**VALID, "label_set_id": "rice-v2"})])
    assert label_status(load_eval_set(path), load_provenance(path))["official"] is False


# -- method comparison --------------------------------------------------------------------------------

def test_draft_labels_score_every_method_but_name_no_winner(tmp_path):
    path = _write(tmp_path, [_row("q1"), _row("q2")])
    out = compare_methods(load_eval_set(path), {"lexical": good, "dense": bad, "rerank": None}, load_provenance(path))
    assert out["methods"]["lexical"]["mrr@10"] == 1.0 and out["methods"]["dense"]["mrr@10"] == 0.0
    assert out["methods"]["rerank"] == {"not_run": "retriever not configured"}
    assert out["best_by_metric"] is None and out["conclusion"].startswith("NO CONCLUSION")


def test_official_labels_name_the_best_method(tmp_path):
    path = _write(tmp_path, [_row("q1", **VALID), _row("q2", **VALID)])
    out = compare_methods(load_eval_set(path), {"lexical": good, "dense": bad}, load_provenance(path))
    assert out["label_status"]["official"] is True
    assert out["best_by_metric"]["mrr@10"] == ["lexical"] and out["best_by_metric"]["ndcg@10"] == ["lexical"]
    assert out["methods"]["lexical"]["latency_ms"]["p50"] is not None


# -- answer metrics ---------------------------------------------------------------------------------------

def _answer(citations, claims=(), served=None, approved=("a1", "b1"), judged_by="expert-1"):
    return JudgedAnswer("q1", tuple(citations), served if served is not None else {"a1": "v1", "b1": "v1", "x9": "v1"},
                        frozenset(approved), tuple(claims), judged_by)


def test_citation_accuracy_counts_only_served_approved_current_chunks():
    out = answer_metrics([_answer([
        Citation("s", "a1", "v1"),      # ok
        Citation("s", "zz", "v1"),      # never served: hallucinated
        Citation("s", "x9", "v1"),      # served but not approved
        Citation("s", "b1", "v0"),      # approved, old version
    ])])
    assert out["citation_accuracy"] == {"count": 1, "of": 4, "rate": 0.25}
    assert out["hallucinated_citation_rate"]["count"] == 1
    assert out["unapproved_citation_rate"]["count"] == 1
    assert out["version_mismatch_rate"]["count"] == 1


def test_a_claim_is_supported_only_by_a_valid_citation_the_judge_accepted():
    out = answer_metrics([_answer(
        [Citation("s", "a1", "v1"), Citation("s", "x9", "v1")],
        claims=[Claim("k1", ("a1",)),      # supported by a valid citation
                Claim("k2", ("x9",)),      # "supported" only by an unapproved chunk
                Claim("k3", ()),           # judge found no support
                Claim("k4", ("b1",))])])   # b1 supports it but was not cited
    assert out["unsupported_claim_rate"] == {"count": 3, "of": 4, "rate": 0.75}


def test_unjudged_answers_are_refused_and_empty_inputs_give_no_rate():
    with pytest.raises(EvalSetError):
        answer_metrics([_answer([], judged_by=None)])
    out = answer_metrics([_answer([])])
    assert out["citation_accuracy"]["rate"] is None and out["unsupported_claim_rate"]["rate"] is None
    assert out["answers_without_citation"] == ["q1"]
