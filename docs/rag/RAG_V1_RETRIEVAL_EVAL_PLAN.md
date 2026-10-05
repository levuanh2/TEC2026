# RAG V1 Retrieval Evaluation Plan

Status: **PROPOSED — awaiting approval** (V1.3-A). This is the **RAG V1 retrieval evaluation set**,
a small internal regression set — not an official benchmark and not a measure of answer quality.
Related: [RAG_V1_RETRIEVAL_ADR.md](RAG_V1_RETRIEVAL_ADR.md), [RAG_V1_SOURCE_POLICY.md](RAG_V1_SOURCE_POLICY.md).

## 1. Purpose

Decide, with measurements instead of assumptions, (a) lexical vs vector vs hybrid retrieval,
(b) the chunking parameters, (c) whether a reranker is needed, and (d) whether retrieval is good
enough to call V1.3 done. Retrieval only: no generation, no LLM judge.

## 2. Preconditions

Labels can only be written against **approved, ingested** documents (decision C1). Until then the
set is designed here, and V1.3-C uses a tiny fixture corpus for unit tests only (not for metrics).

## 3. Dataset

- **Size:** 40 queries to start (≥ 6 per category), frozen in
  `backend/tests/fixtures/rag_eval/retrieval_eval_v1.jsonl`; changes only by a reviewed commit that
  bumps the set version.
- **Languages:** mostly Vietnamese (farmer phrasing, with and without diacritics), some English
  (methodology terms), including acronyms (AWD, 1P5G, IPCC, CH4/N2O).
- **Record shape:**

```json
{"id": "q-explain-001", "set_version": 1, "intent": "explain",
 "question": "AWD là gì và vì sao giảm phát thải mê-tan?",
 "expected": [{"document_id": "<approved id>", "section_path": "<section>", "chunk_ids": ["<id>"]}],
 "acceptable": [{"document_id": "<id>", "section_path": "<section>"}],
 "tenant": null, "notes": "why these sections answer it"}
```

`expected` = chunks a correct retriever must surface; `acceptable` = also relevant, not required.
Labels name **document sections**, never benchmark values; no numbers are invented in a label.

## 4. Query categories

| Category | Intent | Examples (questions only; labels after C1) |
|---|---|---|
| Concept | EXPLAIN | what AWD is; why flooded fields emit CH4; why draining reduces CH4 |
| Mechanism | EXPLAIN | how nitrogen fertilizer leads to N2O; how straw incorporation affects CH4 |
| Evidence | EVIDENCE | which source supports AWD for rice; which guideline defines water regimes |
| Recommend-support | RECOMMEND | evidence on water-regime change; fertilizer management practices; straw management alternatives |
| Methodology | COMPARE | what a scaling factor for water regime is; Tier 1 vs Tier 2 meaning |
| Data gap | DATA_GAP | which inputs the methodology needs for rice CH4 (only if the corpus covers it) |
| Negative / out-of-corpus | any | questions with no relevant document (expect low scores / nothing above threshold) |
| Robustness | any | no-diacritic Vietnamese, acronyms only, misspellings |

## 5. Metrics

Per method (lexical, vector, hybrid) and per chunking variant:

- **Hit@k** (k = 1, 3, 5, 8): at least one `expected` chunk in the top k;
- **Recall@k** (k = 5, 8): fraction of `expected` chunks in the top k;
- **MRR@10**: reciprocal rank of the first `expected` chunk;
- **Source precision@5**: share of the top 5 from an `expected`/`acceptable` document (only where
  the label lists documents);
- negatives: share of out-of-corpus queries whose top-1 score is above the chosen threshold.

Every run writes a JSON report (set version, corpus hashes, embedder model id, chunker version,
metrics, per-query ranks). **Every failed query is inspected by hand** and its cause noted (label
error, chunking split, vocabulary mismatch, missing source).

## 6. Decision rules (fixed before measuring)

- **Hybrid over single method** only if it improves MRR@10 or Hit@5 by ≥ 0.05 absolute over the
  best single method on the full set without lowering any category's Hit@5.
- **Vector (embedding E1) adopted** only if vector or hybrid beats lexical by that margin **and**
  the backend stays within the Render Free memory budget with the model loaded.
- **Reranker considered** only if ≥ 20 % of queries have their first expected chunk at rank 9–20.
- **Chunking variant** chosen by MRR@10, ties broken by smaller chunk count.
- **V1.3 retrieval "done"** proposal: Hit@5 ≥ 0.8 and MRR@10 ≥ 0.6 on non-negative queries, plus
  all security tests green. These thresholds are proposals for approval, not facts.

## 7. Security / isolation tests (separate from metrics, must all pass)

Public retrieval works; correct-tenant retrieval works; cross-organization tenant chunk never
returned; unauthorized season denied before retrieval; scope cannot come from the request;
`review_required` / `rejected` / `archived` never retrievable; unknown source/status fails closed;
document text cannot change filters; injected instructions in a chunk stay plain evidence; source
URL only from trusted metadata; stable chunk ids across re-ingestion; duplicate ingestion adds no
active chunks; vectors from another `embedding_model_id` are never compared.

## 8. Reproducibility

Lexical and fake-embedder runs execute in CI against the local Supabase stack with the fixture
corpus. The full metric run over the approved corpus is an operator/nightly job (no network in PR
CI); its report is committed alongside any change to retrieval parameters.
