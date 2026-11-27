# L2 Scientific RAG — capability inventory (2026-11-27)

Scope: the full V1.5 Draft stack (#91 head `46219b2`) merged with main `9b33fef` (#105). Method: a read-only inventory by agy,
every status re-checked by Claude Code against the cited file:line. Spot checks are listed in the last column, and any agy claim not
re-checked is marked. **Status words:**
- **VERIFIED**: wired into the question path, with a test that includes a negative case.
- **IMPLEMENTED**: wired, but not proven by a test.
- **PARTIAL**: incomplete, or not wired into the question path.
- **MISSING**: no code.
- **BLOCKED**: a person, legal or owner item prevents use.

Local/CI only unless stated: hosted has Migration A (lexical foundation) + ST1/ST1.1, **none of M1–M7**.

| # | Capability | Status | Evidence | Re-checked |
|---|---|---|---|---|
| 1 | Document ingestion | VERIFIED (CLI only) | `.md` / `.txt` / text-layer PDF in an isolated child process; `scripts/ingest_knowledge.py`; no app ingestion path (`test_knowledge_architecture.py`); scans refused (no OCR) | parsers + architecture test |
| 2 | Source provenance | BLOCKED for use | ST1/ST1.1 SHA binding on hosted; E7/E7.1 signatures local/CI; corpus rights (D1) and first-party artifacts (E1) open | acquisition table A-01…A-11 (#85) |
| 3 | Document lifecycle | VERIFIED (local/CI) | M1 status machine, M3 effective dates, H-b quarantine/archive, H-c supersession | rollback chain tests |
| 4 | Expert approval | BLOCKED | M2 verified approval + E2 integrity gate + E7 verification enforced in SQL; **0 real experts** (E4/D6) | — |
| 5 | Chunking | VERIFIED | section-path chunker; known gap: running header wipes section_path (C1-04), numbered headings (kn-pdf-2) | not re-checked in detail |
| 6 | Metadata | VERIFIED | per version: hashes, parser/normalizer/chunker versions, licence basis, effective dates | source policy §6 |
| 7 | Embeddings | **MISSING** | `20261005090000…foundation.sql:4` "NO pgvector: no `vector` extension, no embedding column" | **yes** |
| 8 | Lexical retrieval | VERIFIED | `match_knowledge_chunks_lexical`: FTS + trigram, RRF k = 60; approved + verified + in force + approval unexpired + E5.2 admitted, tenant-scoped (`20261120120000:592-602`) | **yes** |
| 9 | Vector retrieval | **MISSING** | as 7 | **yes** |
| 10 | Hybrid retrieval | PARTIAL | lexical-only fusion (FTS + trigram) + `min_fused_score`; no dense side | **yes** |
| 11 | Reranking | PARTIAL | deterministic body/concept overlap re-scorer in `orchestrator._relevant_evidence` (drops instruction-like chunks, chunks with 0 body relevance, and those below half the best score); no learned reranker | **yes** |
| 12 | Citation validation | VERIFIED (local/CI) | core gates + E5 answer-time re-validation under the JWT + E5.1 gate 1 before the model | answer path read |
| 13 | Knowledge tenant isolation | VERIFIED | RPC SECURITY INVOKER + sources / documents RLS, public vs tenant visibility | RPC + policies read |
| 14 | Knowledge versioning | VERIFIED (local/CI) | versions, supersession (H-c), effective dates (M3) | — |
| 15 | Retrieval eligibility | **VERIFIED for the RPC. One gap, fixed in a Draft (below)** | approved + verified + in force + pin-admitted in the RPC and answer gate. **Direct `SELECT` on `knowledge_chunks` was NOT admission-aware** | **yes**, reproduced on a real DB |

## Retrieval paths that return chunk content or citations
| Path | Approved + in force + admitted? | Note |
|---|---|---|
| `POST …/questions` → admitted retriever → orchestrator → E5 gate | yes | the only end-user answer path |
| `match_knowledge_chunks_lexical` | yes (E5.2) | hosted still runs the Migration A version (approved + scope only) |
| `match_knowledge_chunks_lexical_demo` | approved + in force only | refuses unless `knowledge_deployment_isolated()` (42501 on hosted) |
| **direct `SELECT public.knowledge_chunks` (PostgREST, `authenticated`)** | approved + verified + in force, **not admitted** → **fixed by `20261127090000`** (Draft) | before the fix, text of versions suspended by a re-pin was readable (reproduced: `['94c9cface2fdf79ff741']`) |
| `knowledge_cited_evidence_state` (answer recheck) | yes; returns hashes, no content | keeps reporting `not_current` after the fix (definer hash helper) |
| reviewer reads (`knowledge_review_claims`, `knowledge_review_integrity_report`) | no, **intentionally** | aal2 reviewer/approver roles in scope, pre-approval review; spans only |
| verifier read (`knowledge_verifier.verification_input`) | no, **intentionally** | verifier role only, documents under review only |
| operator stores / CLI scripts | no (owner connection, no RLS) | operator tooling, not reachable by clients |

## Blockers
| Code | Status | What would close it |
|---|---|---|
| dev3-01 | **OPEN**. It is NOT "unapproved content retrieved" (that is enforced). It is **poisoned content approved by a human mistake** (a reviewer resolves every integrity finding as a false positive) | E1 (human-verified primary references, so a conflict is authoritative) + E4 (a real expert, ideally a second one for dismissals) + E6 (a real-model replay, paid). Code cannot close it (`RAG_V15_M7_DEV3_01_HARNESS.md` §5) |
| E1 | OPEN | first-party artifacts with rights and claims (corpus plan) |
| E4 / D6 | OPEN / BLOCKED | a named expert appointed by the owner |
| E5.2 | LOCAL/CI ONLY, blocked for hosted | owner approval to apply M1–M7 on hosted (needs E4 to be useful) |
| D1 | BLOCKED | IPCC written permission, or a legal reading of the Vietnamese decisions |
| new: direct chunk read | **fix in Draft** (`fix/rag-chunks-direct-read-admission`) | review + merge on the stack |
