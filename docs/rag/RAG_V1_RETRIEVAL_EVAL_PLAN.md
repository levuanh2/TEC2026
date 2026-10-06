# RAG V1 Retrieval Evaluation Plan

Status: **HARDENED (V1.3-A)** — design only; labels are written after documents are approved (C1).
This is the **RAG V1 retrieval evaluation set**, a small internal regression set — not an official
benchmark and not a measure of answer quality. Related:
[RAG_V1_RETRIEVAL_ADR.md](RAG_V1_RETRIEVAL_ADR.md), [RAG_V1_SOURCE_POLICY.md](RAG_V1_SOURCE_POLICY.md).

## 1. Purpose

Measure, instead of assume: (a) the lexical baseline (E1 = C), (b) chunking parameters, (c) the
lexical relevance cutoff, (d) later, whether vector/hybrid clears the adoption gate, (e) whether a
reranker is needed, and (f) whether V1.3 retrieval is done. Retrieval only: no generation, no LLM judge.

## 2. Preconditions

Labels can only name **approved, ingested** documents. Until then V1.3-C/F tests use a tiny fixture
corpus for correctness and security only — never for metrics.

## 3. Dataset: 64 queries, split before any tuning

| | Per category | Total | Used for |
|---|---|---|---|
| **DEV** | 5 | **40** | chunking selection, lexical/vector/hybrid selection, relevance cutoffs, reranker decision |
| **HOLDOUT** | 3 | **24** | the final done gate only, run once after the configuration is frozen |
| **Total** | 8 | **64** | 8 categories × 8 queries |

- Files: `backend/tests/fixtures/rag_eval/retrieval_eval_v1.dev.jsonl` and
  `retrieval_eval_v1.holdout.jsonl`, frozen; changes only by a reviewed commit that bumps
  `set_version`.
- **Split rule (anti-leakage):** queries are written in *topic groups*; a whole group goes to DEV or
  to HOLDOUT, so a paraphrase, no-diacritic variant or translation of a DEV query never appears in
  HOLDOUT. The split is made by the labeler before any retrieval run and recorded in the files.
- **No retuning on HOLDOUT.** If HOLDOUT fails, the fix is designed on DEV evidence; a new HOLDOUT
  run after a change is reported together with the earlier failing run, and repeated HOLDOUT-driven
  iterations require writing a fresh HOLDOUT.

Record shape:

```json
{"id": "dev-explain-001", "set_version": 1, "split": "dev", "group": "awd-concept",
 "category": "concept", "intent": "explain",
 "question": "AWD là gì và vì sao giảm phát thải mê-tan?",
 "expected": [{"source_id": "<approved>", "document_id": "<approved>", "section_path": "<section>", "chunk_ids": ["<id>"]}],
 "acceptable": [{"source_id": "<id>", "document_id": "<id>", "section_path": "<section>"}],
 "negative": false, "notes": "why these sections answer it"}
```

Labels name **document sections**; no benchmark value or number is invented in a label. A negative
query has `negative: true` and empty `expected`.

## 4. Categories (8 × 8)

| Category | Intent | Question themes (labels after C1) |
|---|---|---|
| Concept | EXPLAIN | what AWD / "1 phải 5 giảm" are; why flooded fields emit CH4 |
| Mechanism | EXPLAIN | how drainage lowers CH4; how N fertilizer leads to N2O; straw and CH4 |
| Evidence | EVIDENCE | which source supports AWD; which guideline defines water regimes |
| Recommend-support | RECOMMEND | evidence on water-regime change, fertilizer management, straw management |
| Methodology | COMPARE | water-regime scaling factors (definition, not values); Tier 1 vs Tier 2 |
| Data gap | DATA_GAP | which activity data the methodology needs for rice CH4/N2O |
| Robustness | any | no-diacritic Vietnamese, acronym-only, misspellings, English terms |
| **Negative** | any | in-domain-sounding questions the corpus does not answer |

If the approved corpus cannot support 8 honest queries in a category, the gap is reported and the
category is relabeled only by a reviewed set-version bump — never padded with weak queries.

## 5. Metrics

Per method and per chunking variant, on DEV (and once on HOLDOUT):

- **Hit@k** (k = 1, 3, 5, 8) and **Recall@k** (k = 5, 8) on non-negative queries;
- **MRR@10** on non-negative queries;
- **Source precision@5** where labels list documents;
- **Negative false-positive rate (FPR):** share of negative queries for which the retriever returns
  any chunk above the method's cutoff;
- **Empty-result rate** on non-negative queries (cost of the cutoff).

Every run writes a JSON report (set version, split, corpus hashes, chunker/normalizer versions,
method, cutoff, per-query ranks and scores). **Every failed query is inspected by hand** and its
cause noted (label error, chunk split, vocabulary mismatch, missing source, cutoff).

Absolute numbers are reported with counts (e.g. "17/21"), because 24 HOLDOUT queries give wide
uncertainty.

## 6. Selection rules on DEV (fixed before measuring)

- **Relevance cutoff (per method):** chosen on DEV to keep negative FPR ≤ 10 % while maximizing
  Hit@5; lexical, vector and fused scores are on different scales and each method gets its own
  cutoff — scores are never compared across methods.
- **Chunking variant:** highest DEV MRR@10; ties → fewer chunks.
- **Vector/hybrid (only after the lexical baseline, ADR §5 gate):** adopted only if it improves DEV
  MRR@10 or Hit@5 by **≥ 0.05 absolute** over lexical, with no category regression beyond one query
  (inspected by hand), and only if the Render memory gate, model revision/license check and (for a
  hosted API) data-residency approval pass.
- **Reranker considered** only if ≥ 20 % of DEV non-negative queries have their first expected chunk
  at rank 9–20.
- Once chosen, the configuration (method, chunker version, cutoff, top_k) is **frozen** and recorded.

## 7. Done gate (HOLDOUT, frozen configuration)

All of:

1. **Hit@5 ≥ 0.80** and **MRR@10 ≥ 0.60** on HOLDOUT non-negative queries (21 queries: ≥ 17 hits);
2. **negative FPR ≤ 10 %** on HOLDOUT negatives — with 3 HOLDOUT negatives this means **0 false
   positives**; the DEV negative FPR (5 queries) is reported alongside;
3. the retriever can return **no evidence** for negative queries (empty result is a valid outcome);
4. **all security/isolation tests pass** (§8).

These thresholds are agreed proposals, not facts about the corpus; a miss is reported as a miss.

## 8. Security / isolation tests (must all pass; separate from metrics)

Public retrieval works; correct-tenant retrieval works; cross-organization tenant chunk never
returned; farm-scoped chunk not returned for another farm or after the farm moves organization;
unauthorized season denied before retrieval; scope/organization/visibility cannot come from the
request; `review_required` / `rejected` / `archived` source or version never retrievable; unknown
status fails closed; approval without approver/time/license basis rejected by the database; tenant
source with an organization-less scope or a farm of another organization rejected by the database;
document text cannot change filters; injected instructions in a chunk stay plain evidence; source URL
only from trusted metadata; stable chunk ids across re-ingestion; duplicate ingestion adds no
chunks; `top_k` clamped.

## 9. Reproducibility

Lexical runs execute in CI against the local Supabase stack with the fixture corpus (correctness and
security). The metric runs over the approved corpus are operator/nightly jobs (no network in PR CI);
their reports are committed with any change to retrieval parameters.
