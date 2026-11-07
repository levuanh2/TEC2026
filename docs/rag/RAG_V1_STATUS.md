# RAG V1 — Current Status (single source of truth)

Verified **2026-11-07** on `integrate/rag-v1-27-32` (cumulative #27–#32 over `main` @ `27c6cfa`).
The other RAG documents keep their design history; when one of them disagrees with this page about
*state* (what is applied, merged, decided or deployed), this page wins.

## 1. Database: what the SQL enforces (source-verified)

25 migrations in `supabase/migrations/`, 25 names in `scripts/ci/policy/migrations.sha256` (1:1).

| Item | Migration | Enforced by the database | Hosted (per recorded apply gate; not re-read on 2026-11-07) |
|---|---|---|---|
| Migration A — knowledge tables, RLS, lexical RPC | `20261005090000_knowledge_retrieval_lexical_foundation.sql` | `knowledge_sources` / `knowledge_documents` / `knowledge_chunks`, RLS on all three, clients get `SELECT` only (`authenticated`), writes only by owner/service role; approval needs approver + timestamp + note + known `license_basis` (+ `license_reference` for `open_license`/`written_permission`); at most one approved version per `(source_id, document_id)` (`knowledge_documents_one_approved`); chunks immutable, insert only under a never-approved `review_required` document; ever-approved rows cannot be deleted; `archived` only from `approved` and terminal (ST2); forced-password-change callers see no knowledge | applied 2026-10-06 04:57 UTC |
| Lexical RPC | same file, `public.match_knowledge_chunks_lexical(p_crop_season_id uuid, p_query text, p_top_k int default 8)` | `SECURITY INVOKER`, `search_path = ''`: caller RLS resolves the season → farm/org scope (no readable season → 0 rows); returns only `approved` document **and** `approved` source; `public` rows or `tenant` rows of the season's organization (and, for farm rows, the season's farm still in that org); FTS + trigram fused score; `EXECUTE` to `authenticated`, `service_role` only | applied with Migration A |
| ST1 — approval needs a controlled artifact | `20261006120000_knowledge_document_artifact_approval_guard.sql` | `knowledge_documents_artifact_approval_chk`: an `approved` row needs a non-null, ≤ 512-char, opaque ASCII storage path `artifact_ref` (no URL, no `..`, no leading/trailing `/`) — `official_url` alone never approves | applied 2026-10-06 16:55 UTC |
| ST1.1 (migration 024) — artifact bound to its hash | `20261007090000_knowledge_document_artifact_sha_binding.sql` | `knowledge_documents_artifact_sha_binding_chk`: an `approved` row's `artifact_ref` starts with `knowledge-artifacts/<file_sha256>/` (C collation) | applied 2026-10-06 18:35 UTC (PR #11) |
| Storage artifact | none (by design) | **Not DB-enforced:** the `knowledge-artifacts` bucket exists (created 2026-10-06 via the Storage API: private, 50 MiB, md/txt/pdf, no `storage.objects` client policy), but object **existence** and **byte SHA-256 == `file_sha256`** stay the external verify-before-approval step (`knowledge_repo.verify` + the audit SQL in [RAG_V1_INGESTION.md](RAG_V1_INGESTION.md) §5) | bucket created 2026-10-06 |

Hosted knowledge content: **0 approved documents** (recorded). No ingestion has run on hosted. A
read-only re-check of hosted metadata was **not** performed in this pass (it needs the owner's
explicit OK); do it before the first real approval: migration history = 25, both ST constraints
present, `select count(*) from public.knowledge_documents where status = 'approved'` = 0.

## 2. Application (Draft PRs #27–#32, none merged, none deployed)

| Layer | State |
|---|---|
| Retrieval | lexical-first, evidence-first (`rag_application.py`, PR #27). No embeddings, no vector store, no Migration B. |
| D8 | **CLOSED with strategy B** — owner-approved 2026-11-07 as an **interim controlled MVP, not the final conversational AI**. READ intents (explain, compare, evidence, data_gap) are fixed Vietnamese templates composed by `recommendation/rag/informational.py`; **no model writes READ text**. A model is reachable only for WRITE-tier action intents (recommend, what_if) and every recommendation must name an existing stored M05 `rule_code`; with no stored rule, RECOMMEND returns `no_rule_signal` before retrieval/model. |
| Known product gap | READ answers do **not** reflect the question's wording: different questions of one intent get the same template (**PRODUCT_GAP**, measured on a real local stack 2026-11-07: 5 explain questions → 1 template, 3 evidence questions → 1 sentence). The panel now says so ("mẫu cố định") and pre-selects the intent from the typed question, but conversational RAG is **not** done. The D8 strategy C proposal (grounded READ LLM) is on the separate research branch `research/rag-d8-strategy-c` (`docs/rag/RAG_V1_D8_STRATEGY_C.md`) and does not replace B in #27–#32. |
| Route | `POST /v1/crop-seasons/{id}/questions` (PR #29), off unless `RAG_QA_ENABLED=true`; nothing persisted (D4). |
| UI | Farmer + Management season panel (PR #32), off unless `VITE_AI_QA_ENABLED=true`. |
| Provider | Gemini adapter (`infrastructure/llm_client.py`), server env only. Candidates `gemini-2.5-flash-lite`, `gemini-2.5-flash` (D5). Real-model benchmark **BLOCKED_PROVIDER_KEY** (2026-11-07: HTTP 401 `ACCESS_TOKEN_TYPE_UNSUPPORTED`). |
| Corpus | No real document approved. Only synthetic `TEST FIXTURE` rows in local/CI stacks. |
| Carbon numbers | Every Carbon result is an IPCC Tier 1 default estimate (`mrv_compliant = false`); answers that show one carry a trusted "chưa đạt yêu cầu MRV" limitation. |
