# RAG V1 — Pilot readiness (provider, cost, privacy, corpus, UX, release gates)

Date: **2026-11-07**. Scope: the cumulative Draft PRs #27–#32 on `integrate/rag-v1-27-32`.
State of record: [RAG_V1_STATUS.md](RAG_V1_STATUS.md). Nothing here authorizes a merge, a deploy, a
hosted change, an ingestion or an approval.

## 1. Provider (D5): `BLOCKED_PROVIDER_KEY`

| Check (2026-11-07, sanitized, no key printed) | Result |
|---|---|
| Key present in the operator shell (`GEMINI_API_KEY`) | yes, 53 characters, `AQ.` prefix (Vertex AI express-mode shape), not the 39-char `AIza…` Gemini API key shape |
| `GET generativelanguage.googleapis.com/v1beta/models` (header `x-goog-api-key`) | **HTTP 401 `UNAUTHENTICATED`, reason `ACCESS_TOKEN_TYPE_UNSUPPORTED`** ("API key not valid") |
| same with `?key=` | 401, same reason |
| `aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash-lite:generateContent` (header and `?key=`) | 401, same reason |
| Diagnosis | the credential **type** is refused by both endpoints. It is **not** a disabled API (would be 403 `SERVICE_DISABLED`), **not** billing (403/400 billing), **not** quota (429 `RESOURCE_EXHAUSTED`), **not** model access (404/403 on one model). Most likely a revoked/expired or non-API-key credential. No other key was searched for or used. |

Model availability was **not** verifiable (no authenticated `models.list`). Google's forum reports a
shutdown date of 2026-07-22 for `gemini-2.5-flash-lite`: re-check that both candidates are still
served before benchmarking.

### Setup instructions (owner)

1. Google AI Studio → *Get API key* → create a key in a Cloud project **with billing enabled**
   (paid tier; the free tier may use prompts to improve Google products — not acceptable for farm data).
   Or Vertex AI with a service account (needs a provider-adapter change: OAuth bearer, regional endpoint).
2. In that project enable *Generative Language API*; set a **Cloud Billing budget alert at $5/day**
   (provider-side second line, independent of the app).
3. Put the key only in the backend environment (`/etc/agricarbon/api.env` on EC2, Render env on
   staging): `RAG_LLM_PROVIDER=gemini`, `RAG_LLM_MODEL=<candidate>`, `RAG_LLM_API_KEY=<key>`,
   `RAG_LLM_THINKING_BUDGET=0`, `RAG_LLM_PRICE_INPUT_USD_PER_MTOK`, `RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK`.
   Never a `VITE_*` variable: the web build must not contain it (CI bundle/secret scans).
4. Verify without printing the key: `GET …/v1beta/models` → 200 and both candidate ids listed.

### Benchmark procedure (synthetic fixtures only, no farm data)

```
RAG_LLM_MODEL=gemini-2.5-flash-lite RAG_LLM_PRICE_INPUT_USD_PER_MTOK=0.10 RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK=0.40 \
  python backend/scripts/rag_llm_benchmark.py --repeat 3 --out lite.json
RAG_LLM_MODEL=gemini-2.5-flash RAG_LLM_PRICE_INPUT_USD_PER_MTOK=0.30 RAG_LLM_PRICE_OUTPUT_USD_PER_MTOK=2.50 \
  python backend/scripts/rag_llm_benchmark.py --repeat 3 --out flash.json
python backend/scripts/rag_llm_benchmark.py --choose lite.json flash.json   # cheapest that passes, else exit 3
```

9 cases (AWD and data_task recommendations, a what-if, a pesticide request, a question-borne
injection, off-topic evidence, a season without a stored rule, one without evidence). Gates
(defaults, owner may tighten): grounding success ≥ 0.75; correct refusal, injection resistance,
rule-code validity, citation correctness and "no-model cases skip the provider" = **1.0**. Vietnamese
quality is a heuristic plus a human review of a sample of answers. The harness was validated with
`--fake` (scripted policy-following model: all gates pass) and a careless always-recommend fake (fails
refusal + injection gates). **Real results: none — BLOCKED_PROVIDER_KEY.**

## 2. Cost, quotas, kill switch

Prices (Gemini Developer API standard paid tier, per 1M tokens; re-check before use):
flash-lite $0.10 in / $0.40 out; flash $0.30 in / $2.50 out (thinking tokens bill as output).

| Estimate per action answer (≈ 3,500 in / 500 out tokens) | flash-lite | flash (thinking 0) |
|---|---|---|
| USD per answer | ≈ $0.0006 | ≈ $0.0023 (≈ $0.005 with ~1k thinking tokens) |
| One user at the 20/day cap | ≈ $0.011/day | ≈ $0.046/day |
| Answers per $5/day | ≈ 9,000 | ≈ 2,200 |

Only WRITE-tier farmers' `recommend`/`what_if` ever reach the provider; READ answers cost $0. A
RECOMMEND without a stored M05 rule or without evidence is answered before the provider (0 tokens).

**Proposal (server-enforced, owner-adjustable; not implemented in #27–#32):**
- `RAG_LLM_MAX_ACTION_REQUESTS_PER_USER_PER_DAY=20`, `RAG_LLM_MAX_ACTION_REQUESTS_PER_PROJECT_PER_DAY`
  (e.g. 1,000), `RAG_LLM_DAILY_BUDGET_ALERT_USD=5` (log + alert at the threshold),
  `RAG_LLM_DAILY_BUDGET_HARD_STOP_USD` (e.g. 10 → `generation_unavailable` for the rest of the UTC day).
- Counted after authorization and before the provider call, keyed by the JWT `sub` (never a client
  field); a refusal is 429 `quota_exceeded` with Vietnamese copy; READ never counts.
- Pilot storage: one API container today (EC2 t3.small) → an in-process counter is exact but resets on
  restart; production needs a durable counter (`rag_usage_daily(user_id, day, requests, cost_usd)`,
  service-role only, RLS deny-all) = **a new migration with its own approval**.
- Kill switch: unset `RAG_LLM_PROVIDER` (restart) → every action intent is 503
  `generation_unavailable`; `RAG_QA_ENABLED=false` removes the route's service entirely (503
  `backend_not_configured`); `VITE_AI_QA_ENABLED=false` hides the panel on the next build.

## 3. Privacy / data processing

What an action request sends to the provider (`rag_qa.build_action_request`): the question text,
the season's trusted facts (metrics, Carbon numbers, rule titles/reasons, completeness), up to
`top_k` retrieved chunks, the allowed rule codes. Comparison-season fact ids embed season UUIDs. No
names, emails, phone numbers or tokens are added by the server, **but the free-text question can
contain anything the farmer types.** Nothing is persisted by AgriCarbon (D4); the log line has
usage, never question/evidence text.

**No real farm data may reach a provider until a privacy/data-processing review is approved**
(paid-tier terms, retention, region, DPA, user notice in the panel). Until then provider runs use
only `rag_llm_benchmark.py` fixtures.

## 4. Knowledge corpus — approval readiness

No real document is approved anywhere. Status per candidate (C1 gate records of 2026-10-07; SHA
values are of the downloaded bytes then and must be re-verified, `knowledge_repo.verify`, before any
approval):

| Candidate | Publisher / official URL | Version | Rights basis | Quality | Status | Approver |
|---|---|---|---|---|---|---|
| QĐ 4043/QĐ-TTTV-TTBVTV — Quy trình lúa CLC-PTT ĐBSCL (procedure annex) | Cục Trồng trọt và BVTV; copy on Cà Mau extension bucket `storage-vnportal.vnpt.vn/cmu-khdn/5342/…/quy-trinh-4043-…-1.pdf` (no issuer landing page) | 10/11/2025 | administrative document of a state agency (`official_publication`) — needs owner confirmation | Word-export PDF, text layer, 14 chunks; 3 issuer signatures **validated strictly to the official Ban Cơ yếu G2 root with CRLs**; SHA-256 `0aa5e2ee…f1a2`; blocker: top-level "1./2./3." sections not detected → **PR #30 (kn-pdf-2) targets exactly this**; diagram/prose conflict on straw (3 vs 2 weeks); decision page (effectivity) absent | **closest to admissible**; re-run dry run on #30 | none yet |
| QĐ 4801/QĐ-BNNMT (MRV pilot) | `dcc.mae.gov.vn` item 45 | 14/11/2025 | `official_publication` | official PDF is the 1-page decision only; SHA `0221402c…fe5d`; MRV annex unpublished | **HOLD_PARTIAL** (human, 2026-10-07): only as legal metadata, or with the official annex | — |
| QĐ 1490/QĐ-TTg (1 triệu ha) | `datafiles.chinhphu.vn/…/1490-ttg.signed.pdf` | 27/11/2023 | `official_publication` | scan only (no text layer), SHA `bf9bed53…9115`; pipeline refuses `no_text_layer` | **BLOCKED** (needs an OCR policy decision or a text edition) | — |
| NAEC "Canh tác lúa và cà phê giảm nhẹ BĐKH" | `khuyennongvn.gov.vn/…/5-canh-tac-lua-cafe-18-3-out.pdf` | cover 2025, posted 02/04/2026 | **ambiguous**: "© Trung tâm Khuyến nông quốc gia", authored book (not an administrative text) → **written permission** needed | InDesign, 218 chunks; running header wipes section paths; factors conflict with the registry (SFp, N2O) | **PARTIAL** — rights + normalizer | — |
| NAEC QĐ 145 handbook (2024) | NAEC | 2024 | unknown | 38/78 pages image-only | not admissible as is | — |
| Official AWD guidance; "1 phải 5 giảm" | expected Cục TT&BVTV / NAEC | — | — | **no official artifact obtained** | NOT_OBTAINED | — |
| Cục BVTV letter on weedy rice (lúa cỏ) | `ppd.gov.vn/FileUpload/…/2022.8.8- Quy trinh lua co (lua ma).pdf` | 08/2022 | administrative document | clean Word export, 10 chunks, SHA `089a8564…1422`; modest relevance | **admissible candidate** (not a rice-emission source) | — |
| IPCC 2019 Refinement V4 Ch.5 / Ch.11, IPCC 2006 V4 Ch.2, AR5 WG1 Ch.8 | `ipcc-nggip.iges.or.jp`, `ipcc.ch` | 2019 / 2006 / 2013 | **written permission required**: IPCC terms do not allow commercial storage/retrieval or derivative compilation without permission; a public PDF is **not** a license | born-digital, parse cleanly | **NOT admissible** for the corpus (citable as references in Carbon docs only) | — |

Approval checklist for every row: rights basis recorded (`license_basis` ≠ unknown, `license_reference`
for permission), artifact uploaded to `knowledge-artifacts/<file_sha256>/…`, download + SHA-256 ==
`file_sha256` (`knowledge_repo.verify`), the zero-orphan audit SQL of [RAG_V1_INGESTION.md](RAG_V1_INGESTION.md) §5,
a named human approver, then the one-document hosted gate.

## 5. Retrieval evaluation readiness

Runner: `backend/rag_eval.py` + `scripts/eval_retrieval.py` (PR #31), tested on fixtures through the
real retriever (`test_rag_eval_db.py`). Real evaluation is **BLOCKED until an authorized corpus
exists**. Then: label DEV/HOLDOUT questions per approved document (incl. negative queries), run the
lexical baseline, tune `RAG_RETRIEVAL_MIN_FUSED_SCORE`/`top_k` on DEV only, freeze, evaluate HOLDOUT
once; record Hit@k, Recall, MRR, negative-query behaviour, citation stability and latency. No
embeddings/vector search without measured lexical failure on HOLDOUT.

Evidence already seen on the synthetic local corpus (2026-11-07): an off-topic question ("Hướng dẫn
bón phân lúa") still retrieved an AWD-fixture chunk → the min-score cutoff must be tuned on real DEV
data; negative queries are a required eval category.

## 6. Farmer / Manager UX (Phase 7)

Verified on a real local stack (`web-dashboard/tests/e2e/ai-qa-real.spec.ts`): typed questions,
system-composed vs AI labels, approved-only citations, injection text never shown, the farmer's
action request reaching the provider gate, 390 px phone layout with 44 px controls, no answer
surviving sign-out, a manager never offered/served action capability, and zero browser→provider calls.

Remaining gaps:
1. **PRODUCT_GAP — READ answers are templates.** 5 differently-worded explain questions → one answer;
   evidence answers are one fixed sentence + citations. The panel now says "mẫu cố định".
2. Intent still has to be right; the typed-question hint is a keyword heuristic (Vietnamese, folded).
3. READ users cannot ask about recorded M05 recommendations (ACTION_CONTEXT by design); the M05 cards
   remain the place to understand them, and only a WRITE farmer's action answer lists them.
4. Explain covers status, water regime, Carbon total/intensity and yield only — not water/fertilizer/
   cost metrics or the activity summary.
5. Compare: other seasons of the **same plot** only (≤ 3), no benchmark source → mostly
   `no_comparison_basis` today; managers cannot compare across plots/farms.
6. Supporting documents open only via `official_url`; no in-app view of the controlled artifact.
7. Season-scoped only: a cooperative (HTX) question ("which farms lack water data?") has no home. A
   separate org-level assistant is proposed on the research branch (`research/rag-d8-strategy-c`,
   `docs/rag/RAG_V1_HTX_ASSISTANT_PROPOSAL.md`); the season endpoint's access contract is unchanged.
8. What-if exists in the API but not in the panel.

## 7. Release gates

### Staging — GO only when all hold
1. Owner/code-owner review of the guarded diffs, listed separately: `backend/main.py`,
   `backend/tests/route_auth_manifest.py`, `backend/tests/test_route_positive_auth.py`,
   `scripts/ci/policy/policy.json`, `.github/CODEOWNERS`, `backend/scripts/*`, and the newly guarded
   `test_rag_architecture.py`, `test_rag_questions_route_db.py`, `test_rag_retrieval_db.py`,
   `recommendation/rag/intents.py`, `recommendation/rag/informational.py`, `rag_application.py`,
   `rag_qa.py`, `infrastructure/llm_client.py`. An agent review or a self-written trailer is not that review.
2. Combined integration CI green (Normal + Strict) at the exact head SHA that will be merged.
3. Merge sequence #27 → #28 → #29 → #31 → #30 → #32 (or the integration PR) with `--match-head-commit`.
4. Staging env: `RAG_QA_ENABLED=true`, `VITE_AI_QA_ENABLED=true`, **no provider** (strategy-B baseline).
5. Staging knowledge = empty or synthetic fixtures only; no real document ingested.
6. `ai-qa-real.spec.ts` passes against staging with staging QA identities, run serially.

### Production — NO-GO until all hold (in addition to staging)
1. R3 production authenticated QA and human review closed (separate blockers, still open).
2. A real corpus: ≥ 1 document through C1, rights recorded, artifact SHA verified, zero-orphan audit,
   named approver, hosted one-document gate.
3. Retrieval DEV/HOLDOUT evaluation on that corpus meets owner-set thresholds.
4. Owner accepts the PRODUCT_GAP messaging for an MVP (or strategy C passes its own evaluation).
5. If any provider is enabled: valid key, benchmark gates pass for the chosen model, privacy/DPA
   approval, server-enforced quotas + budget alert + kill switch implemented and tested.
6. Read-only hosted verification: migration history = repo, ST1/ST1.1 constraints present,
   approved-document audit = 0 orphans.
7. A second human CODEOWNER (today `enforce_admins` is off and the only code owner is the author).
