# RAG V1.5 — staging rollout runbook, provider status and gates

Date: **2026-11-07**. Branch: `integrate/rag-v15` = #33 (`integrate/rag-v1-27-32`) + test isolation
(`fix/rag-db-test-isolation`) + Gemini/DeepSeek providers, quotas, verification
(`feat/rag-v15-multi-provider`). **D8-C is NOT in this branch** (research branch
`research/rag-d8c-grounded-read`, flag off). Nothing here is merged, deployed or applied to hosted.

**Merge path:** merge through #33 (and this branch's PR), never by closing #33: the state documents,
the test-isolation fix and every V1.5 branch are based on it. If the owner merges #27–#32 one by
one, #33 must still be merged afterwards (its diff then shrinks to docs + V1.5).

## 1. Feature flags and environment (staging only)

| Variable | Staging value | Effect |
|---|---|---|
| `RAG_QA_ENABLED` | `true` | the questions route answers (else 503 `backend_not_configured`) |
| `VITE_AI_QA_ENABLED` | `true` (build time) | the season panel is shown |
| `RAG_LLM_PROVIDER` | **unset** | strategy B baseline: READ composed, action intents 503 |
| `RAG_D8C_ENABLED` | **unset** (not in this branch) | — |
| `RAG_LLM_KILL_SWITCH` | `true` once a provider is ever configured, until its gate passes | no model call at all |
| quotas | defaults: 20 action requests/user/day, 1000 calls/project/day, 5/user/minute, alert $5/day, hard stop $10/day | `infrastructure/llm_quota.py` |

Provider variables when (and only when) a provider gate passes: `RAG_LLM_PROVIDER=gemini|deepseek`,
`RAG_LLM_MODEL=<id listed by verify_llm_provider.py>`, the key in `RAG_LLM_API_KEY` (or
`GEMINI_API_KEY` / `DEEPSEEK_API_KEY`, read only for that provider), `RAG_LLM_PRICE_*` (required by
the cost hard stop), `RAG_LLM_THINKING=disabled` for DeepSeek. Never a `VITE_*` key.

## 2. Synthetic corpus and identities

- Staging knowledge: synthetic `TEST FIXTURE` rows only (as `ai-qa-real.spec.ts` seeds locally); no
  real document is ingested or approved on any shared stack.
- Identities: staging QA farmer (owner, WRITE) + staging cooperative manager of the same HTX + an
  outsider of another HTX. Passwords from the operator's secret store, never in the repo.

## 3. QA matrix (staging)

| Case | Farmer | Manager | Outsider |
|---|---|---|---|
| typed explain / data_gap / evidence / compare | composed, `llm_calls 0` | composed, READ only | 404 |
| recommend | 503 `generation_unavailable` (no provider) or `no_rule_signal` | 404 (no WRITE) | 404 |
| citations | only approved synthetic rows | same | none |
| sign-out then other identity | no stale answer | — | — |
| phone 390 px | no horizontal scroll, 44 px controls | same | — |

Run `ai-qa-real.spec.ts` with `REAL_E2E_BASE_URL=<staging>` serially (1 worker).

## 4. Revert

Unset `RAG_QA_ENABLED` (route → 503) and rebuild with `VITE_AI_QA_ENABLED=false` (panel hidden);
`RAG_LLM_KILL_SWITCH=true` stops every model call without a deploy of new code. No schema change is
part of V1.5 (the durable quota table is a draft outside `supabase/migrations`).

## 5. Provider status (2026-11-07)

| Provider | Credential check (`scripts/verify_llm_provider.py`, one request, no retry) | Status |
|---|---|---|
| Gemini Developer API | `GEMINI_API_KEY` (53 chars) → 401 `credential_type_unsupported` | **BLOCKED_GEMINI_KEY** — create a Gemini Developer API key (AI Studio, billing-enabled project), list models, then benchmark |
| DeepSeek | no `DEEPSEEK_API_KEY` / `RAG_LLM_API_KEY` | **BLOCKED_DEEPSEEK_KEY** |

Candidates: DeepSeek `deepseek-flash` (A), `deepseek-v4-pro` (B) per the official Models & Pricing
page (thinking ON by default there → the adapter sends `thinking: disabled`). Gemini: only ids that
`models.list` returns for the project; 2.5 models are not assumed available. **No real benchmark
result exists; nothing is marked PASS.** Prices are read from configuration; without them the
report says `COST_UNKNOWN` (DeepSeek bills cache-hit input, cache-miss input and output separately,
with peak/off-peak rates — configure the rate that applies).

Benchmark (synthetic fixtures, same cases, prompt and budget for every model):
```
python backend/scripts/verify_llm_provider.py                     # per provider
python backend/scripts/rag_llm_benchmark.py --repeat 3 --out <model>.json
python backend/scripts/rag_llm_benchmark.py --choose gemini-*.json deepseek-*.json
```
Security gates come first (refusal, injection, rule code, citation, no-model cases = 1.0, provider
error rate ≤ 5 %); only then cost; a failing model is never chosen, however cheap.

## 6. Privacy gate (both providers, separately)

Before any real season data goes to a provider: data-processing terms and DPA, retention, training
use, region / cross-border transfer (DeepSeek processing location vs Gemini paid tier), the
sensitivity of agricultural business data (yields, costs, emissions of named farms), user notice in
the panel, and consent where required. No automatic fallback between providers exists (a request is
never resent to a second provider). Logs never hold prompts, JWTs, keys or tenant documents.

## 7. Staging GO / NO-GO

**GO for staging with strategy B (no provider)** when: CI + Strict CI green on this branch's exact
head; human code-owner review of the guarded diffs (`backend/main.py`, `route_auth_manifest.py`,
`test_route_positive_auth.py`, `policy.json`, `CODEOWNERS`, `backend/scripts/*`, `test_rag_*_db.py`,
`test_rag_architecture.py`, `intents.py`, `informational.py`, `rag_application.py`, `rag_qa.py`,
`llm_client.py`, `llm_quota.py`); the owner chooses the merge path; staging env per §1; QA matrix §3.

**NO-GO** for: any provider on staging (both keys blocked; privacy gate open), D8-C (semantic safety
not proven with a real model), production (R3 production acceptance CONDITIONAL, 0 approved corpus,
no retrieval DEV/HOLDOUT, no second code owner).

## 8. Final hardening update (2026-11-07) — staging facts and the exact owner actions

**Staging shares the HOSTED Supabase project with production** (render.yaml: the staging web CSP
`connect-src` is `https://awazhdqzkktekbwaqiic.supabase.co`; `SUPABASE_*` are `sync: false` secrets).
Consequences:
- A synthetic corpus on staging would mean writing APPROVED knowledge rows to hosted. Approved
  knowledge can never be deleted (ST2) and public rows would be visible to production users:
  **NOT allowed**. Staging therefore runs with the **empty corpus**: explain / data_gap / compare
  answer from recorded data; `evidence` returns `insufficient_evidence` (expected, not a failure).
- A synthetic-corpus staging needs a **separate staging Supabase project** (all 25 migrations,
  CI seed, QA identities) — an infrastructure change for the owner to approve separately.

D8-B is now topic-aware (question_scope.py): fact intents cite no document; instruction-like and
unrelated chunks are never cited; out-of-scope questions are refused. Independent holdout v1:
relevance 0.825, correct refusals 4/10 (synonyms missed) — staging QA must include free-typed
questions and record any off-topic answer.

### Exact owner actions (in order; none is done by the agent)
1. Human code-owner review of #33 (14 guarded files) → merge #33 with
   `gh pr merge 33 --merge --match-head-commit <#33 head>` (no admin override without an explicit
   written owner decision).
2. Reconcile #38 with the new main: `git merge origin/main` into `integrate/rag-v15` (no rebase,
   no force-push); confirm `git diff origin/main...integrate/rag-v15` shows only V1.5 files; rerun
   CI + Strict CI (`gh workflow run strict-ci.yml --ref integrate/rag-v15`).
3. Human code-owner review of #38 (9 guarded files: CODEOWNERS, llm_client.py, llm_quota.py,
   rag_qa.py, rag_llm_benchmark.py, verify_llm_provider.py, test_rag_questions_route_db.py,
   test_rag_retrieval_db.py, policy.json, plus informational.py / orchestrator.py from the D8-B fix).
4. Staging (only after a deployment approval): on Render `agricarbon-api-staging`
   (`srv-danpuojm8hqs73c59fh0`) set `RAG_QA_ENABLED=true`, leave every `RAG_LLM_*`, `GEMINI_*`,
   `DEEPSEEK_*`, `RAG_D8C_ENABLED` unset; on `agricarbon-web-staging` (`srv-danpuojm8hqs73c59fj0`)
   set `VITE_AI_QA_ENABLED=true`; deploy the exact merged SHA to both (`POST /v1/services/{id}/deploys
   {"commitId": "<sha>"}`), poll until `live`, check `commit.id`. No migration, no hosted data write.
5. Read-only verification: `GET /health`; with a staging QA farmer JWT, `POST
   /v1/crop-seasons/{id}/questions` explain → 200 `system_composed`, `llm_calls 0`; recommend → 503
   `generation_unavailable` or 200 `no_rule_signal`; manager recommend → 404; an outsider → 404.
   Then `ai-qa-real.spec.ts` with `REAL_E2E_BASE_URL=<staging web>` and staging identities, 1 worker
   (the `evidence` assertion expects citations: with the empty hosted corpus, expect that one step to
   report insufficient evidence — run with the spec's evidence step treated as N/A, or after a
   separate staging project exists).
6. Rollback: unset `RAG_QA_ENABLED` (API → 503) and redeploy the web with
   `VITE_AI_QA_ENABLED=false`, or redeploy the previous commit; Cloudflare caches index.html ~300 s.
7. Providers stay OFF until a valid key is supplied for each, `verify_llm_provider.py --probe`
   returns OK, the synthetic benchmark passes every gate, and the privacy/DPA review approves that
   provider. Kill switch: `RAG_LLM_KILL_SWITCH=true`.
