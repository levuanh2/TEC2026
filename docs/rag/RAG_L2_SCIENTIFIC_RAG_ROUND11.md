# L2 Scientific RAG — corpus, rights, ground truth, embeddings, evaluation, security (Round 11)

Status 2026-11-28: **engineering + evaluation preparation only.** Nothing here was ingested on hosted, approved, labelled
by an expert, embedded, or sent to an LLM. Every number below is either a fact read from a source (with its origin) or a
local measurement named as such. **No retrieval-quality score is reported: there is no expert-validated label set.**

## D1. Corpus manifest

Scope: crop production only (rice, vegetables, fruit trees, industrial crops). Aquaculture and livestock are out of scope
(they are used only as NEGATIVE evaluation questions, §D4).

Fields per document (all mandatory; an unknown value stays empty and the document is **not approvable**):
`document_id`, title (as printed), issuer (as printed), source URL (publisher's own host, HTTPS), issue date (as printed —
for a VN e-signed PDF read it from the signature widgets), version, SHA-256 of the bytes, format, licence / rights basis,
permitted use, approval status, scope of application (crop · region · season · practice), validity (`effective_from`,
`effective_to`), relation to other versions (replaces / amends).

| ID | Document | Issuer | URL (HTTPS, publisher host) | Issued | Version | SHA-256 | Format | Rights basis | Permitted use now | Approval | Scope |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L2-D1 | Quy trình sản xuất lúa chất lượng cao và phát thải thấp vùng ĐBSCL (annex) | Cục Trồng trọt và BVTV | storage-vnportal.vnpt.vn/cmu-khdn/5342/Vanban/quy-trinh-4043-…-1.pdf | 2025 (number/day blank in the text layer: e-signature widgets) | revises the procedure of QĐ 145/QĐ-TT-CLT (27/3/2024), per its own §I | `0aa5e2ee…f1a2` | PDF 8 pp, text layer | VN administrative document — **D-C2 pending** | local engineering/eval only | not approved | rice · ĐBSCL · high-quality low-emission programme |
| L2-D2 | V/v hướng dẫn biện pháp kỹ thuật quản lý lúa cỏ (lúa ma) | Cục Bảo vệ thực vật (Bộ NN&PTNT) | ppd.gov.vn/FileUpload/Documents/BVTV/2022.8.8- Quy trinh lua co (lua ma).pdf | 2022 (number/day blank in the text layer) | — | `089a8564…1422` (= 2026-10-07 record) | PDF 4 pp, text layer | as D-C2 | local engineering/eval only | not approved | rice · national · weedy rice |
| L2-D3 | Canh tác lúa và cà phê giảm nhẹ biến đổi khí hậu | NAEC (Trung tâm Khuyến nông Quốc gia), named authors | khuyennongvn.gov.vn/data/documents/0/2026/04/02/hangweb/5-canh-tac-lua-cafe-18-3-out.pdf | not printed in the extracted text | — | `36f03ffa…0c13` | PDF 104 pp, text layer (1 page without text) | © authored work, **no licence statement** | background reading only (not approvable) | not approved | rice + coffee · national |
| A-08 | QĐ 2626/QĐ-BTNMT (emission factor list) | Bộ TN&MT | recorded on #85 | signed | — | `cf3f3e13…d468` | PDF 23 pp | as D-C2 | as D-C2 | not approved | carbon factors · national |

Coverage today: rice 3 · coffee (industrial) 1 (D3, not approvable) · vegetables 0 · fruit trees 0. The gap list per topic
and where to look is `RAG_V15_CORPUS_PLAN.md` §3; acquisition follows its §4. Local copies and hashes:
`.tmp/l2-corpus-local/MANIFEST.md` (not committed: document bytes and text stay out of git until rights are settled).

## D2. D-C1 — IPCC rights matrix

What is established (`RAG_V15_E1_RIGHTS_AND_OCR.md` §2, re-checked 2026-11-28):
- The official terms page `https://www.ipcc.ch/copyright/` refuses automated access (HTTP 403 on 2026-11-12, 2026-11-16
  and again on 2026-11-28). The NGGIP site (2006 Guidelines, 2019 Refinement) links to that same page and states no licence
  of its own. **The terms have therefore not been read by any agent.** Bypassing the 403 was refused as a matter of policy.
- The 2019 Refinement front matter carries an IPCC copyright notice and no reproduction terms. Download availability is
  not a licence. Some IPCC reports are also published by Cambridge University Press under their own notices; those apply
  to those editions only.

| Material | Use for | Category | Basis / next step |
|---|---|---|---|
| Emission-factor VALUES with a table reference (e.g. Tier 1 defaults in `emission_factors.yaml`) | engine configuration, citation by table number | **cite-only (facts + reference)** — individual values with attribution | existing practice; a systematic compilation is flagged in E1 §3 for owner/counsel |
| Short quotation (a sentence or definition) inside an answer, attributed | answer text | **cite / quote** — only if the official terms allow it; not confirmed | owner reads the terms page in a browser and records the clause |
| Full chapters as retrieval chunks (2006 GL Vol.4 Ch.2/5/11, 2019 Refinement) | corpus (stored, chunked, served) | **needs written permission** (storage/retrieval/compilation in a system) | request to the IPCC Secretariat (`copyright@ipcc.ch`, as recorded in E1 §2); store request + reply hash |
| Figures / tables owned by third parties inside IPCC reports | anything | **insufficient basis** | never copied; cite the IPCC table number only |
| CUP CC-licensed editions of a specific report (if any) | corpus | **per edition**: only that edition, only under its stated licence (e.g. NC-ND = no derivative/commercial) | read the edition's own notice; not assumed for methodology reports |
| AR5 WG1 Ch.8 (GWP values) | GWP values in the engine | cite-only (values + reference) | as row 1 |

Rule: each IPCC item gets its own row in the source registry; no IPCC text becomes a chunk until the row says
`written_permission` (with reference) or a licence that permits storage and display.

## D3. D-C2 — Vietnamese legal and technical documents

Applies to: Quyết định, Thông tư, Nghị định, QCVN, quy trình kỹ thuật, văn bản sửa đổi/thay thế.

| Must be kept | Where it lives today | Gap |
|---|---|---|
| Số hiệu (e.g. 4043/QĐ-BNN-TT) | `knowledge_documents.document_version` / title (free text) | **no dedicated field**: propose `legal_number` (text, unique per issuer) |
| Ngày ban hành | `knowledge_documents.published_at` | used for both "published" and "issued": propose `issued_on` |
| Ngày hiệu lực / hết hiệu lực | `effective_from` / `effective_to` (M3); approval refused outside the window; retrieval returns only in-force versions | — |
| Cơ quan ban hành | `knowledge_sources.owner` + publisher registry (H-C) | — |
| Trạng thái hiệu lực | derived: in force = window contains today AND not superseded (M3) | "partly amended" is not a state |
| Thay thế | `supersedes_document_pk` (M3): approving the successor archives the predecessor atomically; cross-source supersession needs a countersigned authorization (H-C) | — |
| Sửa đổi, bổ sung (partial) | — | **gap**: propose `amends_document_pk` + section list; until then a partly amended document is approved only together with a review note listing the amended sections, and the amending document is ingested as its own version |

Procedure per document:
1. Acquire from the issuer's portal (HTTPS); hash; text layer required (scan-only → refused, no OCR in V1.3).
2. Read number/date/issuer AS PRINTED (from signature widgets if blank in the text layer); never infer them.
3. Search the document itself for "thay thế", "bãi bỏ", "sửa đổi, bổ sung", "có hiệu lực từ" and record every relation;
   check the issuer's legal database for later amendments before approval.
4. Set `effective_from/to` only from the document or the amending document; unknown = not approvable.
5. Example from the corpus: L2-D1 says it revises the QĐ 145/QĐ-TT-CLT procedure. If 145 is ever ingested, it must be the
   superseded version (archived), and question `l2v0-15` (§D4) checks that the assistant does not present 145 as current.

The chatbot never presents an expired or superseded version as current: retrieval admits only approved, verified,
in-force, pin-admitted chunks (M3 + E5.1/E5.2), and answer-time re-validation (E5) refuses a citation whose document
left force between retrieval and answer.

## D4. D-C3 — Expert ground truth workflow (no official label exists yet)

Draft material (local only, `.tmp/l2-corpus-local/eval-draft-v0/questions.jsonl`): 15 questions written by the agent
from the 3 documents (12 positive, 2 out-of-scope negatives, 1 legal-version trap), each `label_status:
draft_unvalidated`, `expected: []`, with 5 candidate passages picked by plain lexical overlap. Sanity check of the
picker (not a score): the page the author read is among the top-5 candidates for 12/12 positives. Observations for the
expert: the two out-of-scope questions still draw high-overlap candidates (a negative must stay empty), and D3 competes
with D1 on fertiliser questions (possible source conflict → M4 claims/contradictions).

Workflow:
1. **Panel**: two named domain experts (E4) per crop topic + one adjudicator. Each signs the form (identity, affiliation,
   date, conflicts of interest).
2. **Independent pass**: each expert sees the question and the candidate passages (shuffled, no scores, no method name)
   and marks every passage `expected` (answers it), `acceptable` (partly/background) or `not_relevant`, may add a
   passage not in the list (by document/page/paragraph), and marks the question `answerable` / `not_answerable_in_corpus`.
3. **Agreement**: Cohen's κ per topic on the 3-level grade, reported with the set. κ < 0.6 on a topic → that topic is
   re-briefed and re-labelled; it is not used.
4. **Disagreement**: same grade → final. One `expected` vs one `acceptable` → `acceptable`. `expected` vs `not_relevant`
   → the adjudicator decides with a written reason; no majority vote by a model.
5. **Freeze**: the adjudicated set gets `label_set_id` (e.g. `rice-v1`), `validated_by` (all names), `validated_at`, and the
   SHA-256 of the JSONL; split into dev/holdout by topic group (no group in both splits, `rag_eval.load_eval_set` enforces it).
6. **Versioning**: a change of any label = a new `label_set_id`; old sets are kept; every score names the set id and hash.
   A corpus change that removes a labelled chunk invalidates the affected rows (re-label, never silently drop).

Form (one per expert per question): question id · question · for each passage: grade (2/1/0) + one-line reason ·
missing passage (doc/page/para) · answerable? · confidence (low/med/high) · time spent · signature/date.

`rag_eval_framework.load_provenance` refuses `expert_validated` without `validated_by`, `label_set_id` and `validated_at`;
`compare_methods` names no winner unless EVERY query of the split is validated under one set id.

## D5. Embedding models (comparison from model cards — NOT downloaded, NOT measured; D-C4 pending)

| Model | Params (card) | Dim | Max tokens | Licence | Vietnamese | Notes |
|---|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | not read (card truncated) | 384 | 512 | not read | not stated | e5 family needs `query:`/`passage:` prefixes (confirmed on base/large) |
| intfloat/multilingual-e5-base | not stated | 768 | 512 | MIT | "100 languages from xlm-roberta" (VN not named) | init xlm-roberta-base; prefixes required |
| intfloat/multilingual-e5-large | not stated | 1024 | 512 | MIT | as base | init xlm-roberta-large; prefixes required |
| BAAI/bge-m3 | not stated | 1024 | 8192 | MIT | ">100 languages" (VN not named) | dense + sparse + multi-vector; no query instruction |
| AITeamVN/Vietnamese_Embedding | 0.6B | 1024 | 2048 | Apache-2.0 | **explicit**: fine-tuned from bge-m3 for Vietnamese; Legal Zalo 2021 Acc@1 0.7274 (card) | legal-domain training, not agriculture |
| Alibaba-NLP/gte-multilingual-base | 305M | 768 (128–768) | 8192 | Apache-2.0 | ">70 languages" (VN not named) | native in recent transformers, otherwise `trust_remote_code` with a pinned revision |
| bkai-foundation-models/vietnamese-bi-encoder | 0.1B | 768 | 256 | Apache-2.0 | **explicit** (PhoBERT-base-v2) | input MUST be word-segmented (pyvi/underthesea) |
| BAAI/bge-reranker-v2-m3 (reranker) | 0.6B | — | 512 in the card example | Apache-2.0 | multilingual (VN not named) | scores (query, passage) pairs |

RAM/VRAM and embedding speed are **not reported**: they must be measured on the target machine (CPU EC2 t3.small has
2 GB RAM: a 0.6B F32 model, ~2.4 GB of weights by arithmetic, does not fit; this is arithmetic, not a measurement).
Agriculture-domain quality is unknown for all of them until the expert set exists. Proposed D-C4 shortlist for a LOCAL
offline experiment (no production change): bge-m3, AITeamVN/Vietnamese_Embedding, multilingual-e5-base; reranker
bge-reranker-v2-m3. All four have permissive licences per their cards.

## D6. Evaluation framework (`backend/rag_eval.py` + `backend/rag_eval_framework.py`)

- Retrieval: Precision@K, Recall@K, F1@K, nDCG@K (graded: expected 2, acceptable 1), MRR@10, hit@K, negative FPR,
  empty-result rate, latency p50/p95 (measured around the retriever call).
- Method comparison: `compare_methods(queries, {"lexical": f, "dense": g, "hybrid": h, "hybrid+rerank": r}, provenance)`;
  a method that is not configured is `not_run`, never scored; **on draft labels the output says "NO CONCLUSION" and
  names no best method.**
- Answers: citation accuracy (cited chunk was served for that question, approved, same version), hallucinated-citation
  rate, unapproved-citation rate, version-mismatch rate, unsupported-claim rate (claims no valid citation supports, per the
  judge's `supported_by`); unjudged answers are refused.
- Tests: `tests/test_rag_eval_framework.py` (toy rankings; arithmetic and refusal rules only).
- Next: a runner that feeds the real lexical RPC on a LOCAL stack with the local corpus ingested (`ingest_knowledge.py`,
  local only), then the same queries through dense/hybrid once D-C4 allows a model.

## D7. Security test map (existing tests; run in CI `Backend DB integration` on #108 `f158fe5`, 17/17)

| Requirement | Tests (file → examples) |
|---|---|
| Unapproved documents are not retrieved | `test_rag_retrieval_db.py`, `test_knowledge_ingest_db.py` → `test_review_required_chunks_are_not_retrievable_until_an_operator_approves`; `test_rag_knowledge_chunks_read_admission.py` (#108: direct SELECT honours pin admission) |
| Unapproved documents are not cited | `test_rag_answer_integrity.py` → `test_a_chunk_the_database_no_longer_returns_is_refused_and_one_bad_citation_is_enough`; `test_rag_knowledge_m7_e5_answer_time.py` (answer-time re-validation) |
| Cross-tenant isolation | `test_knowledge_ingest_tenant_redaction.py`, `test_rag_retrieval_db.py` → `test_two_tenants_are_never_paired`, `test_tenant_source_with_a_farm_of_another_organization_is_refused_atomically` |
| Prompt injection from documents | `test_rag_grounding.py` / `test_rag_orchestrator.py` → `test_instruction_like_evidence_is_never_sent_or_cited`, `test_injection_only_evidence_means_no_model_call`, `test_injected_instructions_stay_inert_evidence` |
| Citation provenance | `test_rag_knowledge_artifact_approval.py`, `test_knowledge_integrity*.py` → `test_forged_or_altered_artifact_is_a_mismatch`, `test_a_draft_cannot_be_approved_until_it_has_a_controlled_artifact` |
| Document version mismatch | `test_rag_knowledge_m3_validity.py`, `test_rag_knowledge_m7_e5_1_pin_admission.py`, `test_rag_knowledge_m7_e5_2_pin_generation.py` → `test_new_document_version_coexists_with_new_chunk_ids`, `test_existing_version_in_any_status_is_never_touched_or_reactivated` |
| Unauthorized access | `test_rag_knowledge_postgrest.py` → `test_anon_still_reads_nothing`; route tests (401/404 for foreign seasons) |
| Hallucinated citations | `test_rag_grounding.py` (citation ⊆ retrieved), `test_rag_answer_integrity.py`; new metric `hallucinated_citation_rate` (D6) |

Gaps (not covered by a test today): (1) a negative question must retrieve nothing above the cutoff on the REAL corpus —
needs the local corpus ingested; (2) "partly amended" legal documents (D3 gap); (3) dense/hybrid retrieval has no
admission test because it does not exist — any dense path must reuse the same admission SQL, never a separate index
without status/tenant/pin filters.
