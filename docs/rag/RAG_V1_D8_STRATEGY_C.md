# D8 Strategy C — grounded informational LLM for READ intents (RESEARCH PROPOSAL)

Branch: `research/rag-d8-strategy-c` only. **Not** part of #27–#32, **not** a replacement for
strategy B, no production path. Date: 2026-11-07. Baseline: [RAG_V1_STATUS.md](RAG_V1_STATUS.md).

## 1. Why

Strategy B (owner-approved interim MVP) is safe because no model writes READ text. Measured cost of
that safety on a real local stack: 5 differently-worded *explain* questions → 1 answer; 3 *evidence*
questions → 1 fixed sentence + citations; "Phát thải bao nhiêu?" and "Năng suất ra sao?" both get the
status line. That is **PRODUCT_GAP**: it is a deterministic report with search, not conversational
RAG. Strategy C lets a model *phrase* READ answers while keeping B's guarantees.

## 2. The four answer classes stay distinct

| Class | Written by | May contain | Shown as |
|---|---|---|---|
| Deterministic informational (B) | trusted templates | descriptions + `{{fact}}` | "Hệ thống soạn — không dùng AI" |
| Retrieved evidence | ingestion metadata | citations only (title, section, URL) | "Nguồn tài liệu" |
| Grounded informational (C, new) | model, READ capability | descriptions of facts/evidence, never advice | "Trợ lý AI viết (chỉ mô tả, không khuyến nghị)" |
| Model action explanation (existing, WRITE) | model, ACTION capability | explanation of a stored M05 `rule_code` | "Trợ lý AI giải thích khuyến nghị đã có" |
| Stored M05 recommendation | deterministic rules | title/reason/impact as stored | M05 cards (authoritative) |

## 3. Design

1. **Structured facts in, structured claims out.** The model receives the same `GenerationInput`
   (INFORMATIONAL_SAFE facts + chunks as delimited JSON data, policy only in the system channel).
   It returns `sentences: [{text, fact_refs[], evidence_refs[], claim_type}]` where `claim_type ∈
   {describe_fact, describe_gap, quote_evidence, compare_values}`. No free paragraph; every sentence
   must reference ≥ 1 fact or ≥ 1 cited chunk. Numbers only as `{{fact}}` placeholders (existing prose gate).
2. **READ cannot produce actions — structurally.** The READ schema keeps no recommendation slot;
   ACTION_CONTEXT facts are never in the input (existing `usable_facts`). A READ answer cannot cite
   a rule signal.
3. **Semantic advice prevention (the D8 question).** Keyword lists are not a boundary. Layers:
   (a) claim_type whitelist — no `advise`; (b) an independent classifier pass (a second, smaller
   model call or a fine-tuned local classifier) labels each sentence `descriptive | directive |
   evaluative`; any `directive`/`evaluative` → the whole answer falls back to strategy B (fail
   closed, never edited); (c) Vietnamese imperative/modal patterns ("nên", "hãy", "cần phải",
   "khuyên") as a *detector feeding the eval*, not as the guard.
4. **Prompt-injection protection.** Chunks are data in a JSON field, never concatenated with policy;
   output is schema-validated; a chunk flagged by ingestion (imperatives addressed to an assistant)
   is retrievable but carried with `untrusted_instructions=true`; the eval set contains injected
   chunks and questions; any echo of an injected instruction is a hard failure.
5. **Tenant isolation.** Unchanged and upstream of the model: caller-JWT scope resolver, RLS RPC,
   `assert_tenant_isolation`, `assert_fact_scope`. The model never receives an id it could use to
   reach another tenant; citations resolve only against the retrieved set.
6. **Fallback.** Any provider error, gate failure, classifier "unsure", over-budget or kill switch →
   strategy B answer (with a "Hệ thống soạn" badge), never an error and never a partial model answer.
7. **Cost/privacy.** READ calls are far more frequent than WRITE: C must ship with the quota/budget
   design of RAG_V1_PILOT_READINESS.md §2 and the privacy review of §3; managers' READ questions
   would send farm facts to the provider — the DPA must cover that explicitly.

## 4. Evaluation before any use (unsupported-claim and hallucination)

A frozen Vietnamese set (≥ 200 items, DEV/HOLDOUT split), built from approved-corpus seasons:
paraphrase families per intent (≥ 5 wordings), questions whose answer is not in the facts/evidence,
injected chunks/questions, advice-baiting READ questions ("nên làm gì?" from a manager), comparison
traps (no basis), numbers stated in words.

| Metric | Gate (proposal) |
|---|---|
| Unsupported-claim rate (a sentence whose fact/evidence refs do not entail it; 2 human raters + adjudication) | ≤ 2 % |
| Hallucinated number/entity | 0 |
| Directive/evaluative sentence in a READ answer (after the guard) | 0 |
| Injection echo | 0 |
| Correct "insufficient" on unanswerable | ≥ 95 % |
| Paraphrase consistency (same facts → same content) | ≥ 90 % |
| Answer reflects the question (rater: "answers what was asked") vs B baseline | ≥ +40 pts over B |
| Cross-tenant citation | 0 (structural) |
| p95 latency / cost per READ answer | owner thresholds |

Only after HOLDOUT passes would a change to the production path be proposed — as its own PR, with
`test_rag_architecture.py` updated deliberately (code-owner review), and B kept as the fallback.

## 5. Out of scope here

No code on the production path, no provider calls with farm data, no change to the season endpoint's
contract, no embeddings.
