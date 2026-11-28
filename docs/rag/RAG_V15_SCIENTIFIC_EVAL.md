# RAG V1.5 / L2 — Scientific RAG evaluation design

Status: **DESIGN + METRICS CODE. No score has been measured.** There is no labelled scientific corpus yet:
`backend/tests/fixtures/rag_eval/` is empty, and the V1 plan writes labels only after the documents are approved
(C1, `RAG_V1_RETRIEVAL_EVAL_PLAN.md` line 3). Every number below is a definition or a gate, not a result.

## 1. Two evaluations, never mixed

| | Retrieval evaluation | Generation evaluation |
|---|---|---|
| Question | Does the retriever rank the right passages first? | Is the answer supported by the cited passages, and does it abstain when they are not enough? |
| Input | question → ranked chunks | question + retrieved chunks → answer + citations |
| Labels | per query: `expected` / `acceptable` sections (or chunk ids), negatives | per answer: claims, the chunk that supports each claim, the expected abstention |
| Code | `backend/rag_eval.py` (pure) + `scripts/eval_retrieval.py` (real retriever under the caller's JWT) | READ tier: the trusted composer (no model). Action tier (L3): a model; **not run** (no paid call without approval) |
| Who labels | a domain labeller who has not seen retrieval output on HOLDOUT | the same, blind to which method produced the answer |

## 2. Retrieval metrics (positives; negatives use the false-positive rate)

Each metric is the mean of the per-query value (`rag_eval.py` docstring):
- **Precision@k**, k = 1, 3, 5, 10: relevant chunks in the top k divided by k.
- **Recall@k**, k = 1, 3, 5, 8, 10: expected labels found in the top k divided by the expected labels.
  (Fixed 2026-11-27: before, recall@5 reused the top-8 count.)
- **F1@k**: the per-query harmonic mean of the two above.
- **MRR@10**: the reciprocal of the first relevant rank.
- **nDCG@k**: graded gains (expected 2, acceptable 1). Each label is credited once, at its first rank.
- **Hit@k**: at least one relevant chunk in the top k.
- **Negative FPR**: share of negative queries that return any chunk.
- **Empty-result rate.**
- **Retrieval latency** p50/p95, measured on the real retrieval RPC.

Every report gives counts next to rates ("17/21"): with about 24 HOLDOUT queries the intervals are wide.

## 3. Generation metrics (defined; measured only on approved runs)

| Metric | Definition | Status |
|---|---|---|
| Citation accuracy | Cited chunks that (a) were retrieved in this request and (b) support the sentence they are attached to, divided by all citations. (a) is enforced by code (core gate + E5 answer-time gate); (b) needs a human label. | (a) enforced; (b) not measured |
| Groundedness | Answer claims supported by a cited chunk, divided by all claims, labelled per claim | not measured |
| Unsupported claim rate | 1 − groundedness, counted per answer as well (answers with ≥ 1 unsupported claim) | not measured |
| Abstention accuracy | On questions the corpus cannot answer (negatives) and on "insufficient evidence" positives: abstained / should abstain, and the false-abstention rate on answerable ones | READ tier: measurable now with the composer once labels exist |
| Hallucination (numbers) | Any number not equal to a trusted fact. Already structurally impossible for READ answers (placeholders + fact refs); for L3, measured per answer | READ: enforced by code |

## 4. Methods to compare (same corpus, same questions, same labels, same split)

1. **Lexical**: the production RPC `match_knowledge_chunks_lexical`. It is already a lexical fusion: full-text + trigram, RRF k = 60.
2. **Dense**: an embedding model over the same chunks. **MISSING**: no embedding column and no model. A local open model (no API cost) needs an owner decision: model, licence, and where vectors are stored (pgvector on hosted = migration).
3. **Hybrid**: RRF of lexical + dense ranks (no tuned weight, as in the ADR).
4. **Hybrid + reranking**: a cross-encoder over the top 50. **MISSING**, with the same decision as 2.

The decision rule stays the ADR's (`RAG_V1_RETRIEVAL_ADR.md` §174): a method replaces lexical only if it improves the predeclared DEV
metric (MRR@10 or Hit@5) by ≥ 0.05 absolute, with no category losing more than one query. HOLDOUT is scored once, after the
configuration is frozen.

## 5. Benchmark independence
- DEV and HOLDOUT are written before any retrieval run; a topic group lives in one split (the loader enforces it).
- HOLDOUT questions are written by someone who has not read the retrieval code or the DEV failures. An agent that reviewed the code
  cannot write it (it would not be independent).
- No question used during development (`rag_action_dev_v*`, `rag_read_holdout_v2`, benchmark presets) is reused as HOLDOUT.

## 6. Prerequisites (in order)
1. A corpus: approved, verified documents with provenance and rights (`RAG_V15_CORPUS_PLAN.md`); E1 / C1.
2. Labels written on that corpus (DEV, then HOLDOUT).
3. A lexical baseline run (local stack, then staging); no hosted ingestion without approval.
4. Owner decision on dense / rerank (model, licence, storage) before methods 2–4 can run.
