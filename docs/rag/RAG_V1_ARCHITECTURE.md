# RAG V1 — Recommendation Q&A Architecture

Status: **architecture + provider-neutral skeleton** (branch `feature/rag-v1-architecture`,
base `main` @ `11e5db0`). No LLM, no vector store, no embeddings, no ingestion, no route,
no UI, no migration. Typed contracts: [`RAG_V1_DATA_CONTRACT.md`](RAG_V1_DATA_CONTRACT.md).

RAG is the **OPTIMIZE** layer of MEASURE → UNDERSTAND → OPTIMIZE → ACT. It explains,
compares, recommends, simulates and cites **around one crop season's authoritative data and
a controlled document corpus**. It is not a general agronomy chatbot, it never diagnoses
disease (CV's job), never prescribes pesticides, never gives medical/veterinary advice, and
never invents a benchmark, a Carbon result, an emission factor or a citation.

---

## 1. Current recommendation architecture (audited, Core V1 @ `11e5db0`)

```
POST /v1/crop-seasons/{id}/recommendations/generate          api.py:787
  ├─ Depends(_read_repo)  → SupabaseReadRepository bound to the caller JWT (RLS)
  ├─ Depends(_recommendation_service) → RecommendationService singleton (main.py:198)
  └─ _recommendation_or_http: RecommendationAccessError → 404 not_found  api.py:775
        │
RecommendationService.generate                                  service.py:754
  ├─ me()["roles"] ∋ "farmer"                (else RecommendationAccessError)
  ├─ read_repository.season(id)              READ gate = RLS user_can_read_crop
  ├─ write_repository.assert_can_write(...)  early WRITE gate (crop_write_authz)
  ├─ read_repository.metrics(id)             Resource Metrics (authoritative)
  ├─ recommendation.generate_recommendations(id, carbon=CarbonService, metrics)
  │     ├─ rules.evaluate_awd_rule → CarbonService.calculate(id, "as_recorded"|"awd", persist=False)
  │     └─ rules.evaluate_data_completeness(metrics)   (pure)
  └─ write_repository.save_generated(...)    ONE transaction, re-checks WRITE gate
        └─ infrastructure/recommendation_repo.py  (psycopg, service-role, upsert + prune)

GET   /v1/crop-seasons/{id}/recommendations   → read_repository.recommendations (RLS read)
PATCH /v1/recommendations/{id}                → RecommendationService.set_status (WRITE gate in txn)
```

| Question | Answer (real code) |
|---|---|
| A. Route | `backend/api.py:782-806` (3 routes); DI placeholders `api.py:177`, wiring `main.py:198-199` |
| B. Service | `backend/service.py:734` `RecommendationService` |
| C. Rule evaluation | `backend/recommendation/rules.py` (pure functions), orchestrated by `recommendation/engine.py::generate_recommendations` |
| D. Impact via Carbon | `rules.CarbonCalculator` Protocol, satisfied by `service.CarbonService.calculate(..., persist=False)`; impact = `before.total_co2e_kg - after.total_co2e_kg` of two engine runs |
| E. Persistence | `backend/infrastructure/recommendation_repo.py::PostgresRecommendationRepository` (`season_recommendations`) |
| F. Authorization | READ: caller-JWT `SupabaseReadRepository` (RLS). WRITE: `infrastructure/crop_write_authz.py::assert_can_write_crop` = `private.user_can_write_crop` AND active `farmer` membership in the season's own organization, evaluated inside the write transaction |
| G. Service-role boundary | `recommendation_repo`, `cv_repo`, `pg_carbon_repo`/`supabase_repo` (Carbon) use service role and bypass RLS; every service-role call is preceded by a caller-scoped gate (RLS read, `CropAccessChecker`, or `assert_can_write_crop`) |
| H. Reusable abstractions | `CarbonCalculator` Protocol; pure `generate_recommendations`; `CarbonService.calculate(persist=False)`/`stored()`/`readiness()`; `SupabaseReadRepository.season/metrics/activity_summary/recommendations`; `crop_write_authz`; `api_errors.error_detail` envelope; `dependency_overrides` DI |

Rule engine and persistence are **already separated** (engine returns `GeneratedRecommendation`
dataclasses; the repo persists them). RAG can extend Recommendation without a rewrite.

### Carbon, Metrics, Authorization flows

- **Carbon** — single source: `carbon.calculate_carbon` (pure: stdlib + yaml), reached only
  through `service.CarbonService` (`calculate`, `stored`, `readiness`, `status_many`). Web and
  Flutter call `/v1/carbon/*`; neither holds a formula or factor (verified by grep; client
  mentions of "GWP" are copy text only). **One** Carbon source of truth.
- **Resource Metrics** — single source: `SupabaseReadRepository._compute_metric_totals`
  (`infrastructure/read_repo.py:469`), exposed as `metrics()`, `farm_metrics()`,
  `organization_metrics()`; aggregate = Σ numerator / Σ yield; any missing value → `null`.
- **Authorization** — read = RLS through a per-request, caller-JWT client; Carbon reads also
  use `CropAccessChecker` before the service-role repo; Carbon persist uses
  `CropPersistChecker`; Recommendation/CV writes use `crop_write_authz`. Forced password change
  is enforced by `_password_change_guard` (router dependency) and in the database.

### Architecture debt (recorded, NOT fixed this round)

| Debt | Where | Impact on RAG |
|---|---|---|
| God module | `service.py` (1386 lines, 9 services) | RAG application wiring must NOT be added there; use a sibling module (§4) |
| Business calculation in infrastructure | Resource Metrics live inside `read_repo.py` | None if RAG only *reads* `metrics()`; never re-derive |
| No read-only what-if | `/v1/carbon/calculate` always persists and needs write authority; `persist=False` runs only inside `RecommendationService.generate` (write-gated) | Read-tier what-if is a new capability → Open Decision D1 |
| Season lineage not exposed | `season_view`/`_farm_view` omit `farm_id`/`cooperative_id` | Tenant filter needs `organization_id`; a future additive read method (no schema change) → D3 |
| Large route module | `api.py` 1178 lines | Future RAG route must be one thin handler |

---

## 2. Current dependency map

```
             main.py  (composition root: settings, singletons, dependency_overrides)
               │
               ▼
             api.py   (FastAPI routes, HTTP error mapping)
               │
               ▼
           service.py (application services)  ─────────┐
           │      │        │          │                 │
           ▼      ▼        ▼          ▼                 ▼
     carbon/  recommendation/  mrv/   schemas.py   infrastructure/
     (pure)   (pure rules)    (render) (pydantic)   (supabase / psycopg / auth adapters)
       ▲          │                                   │
       └──────────┘ (CarbonEngineError only)          └──▶ carbon/ (mapping uses models)
```

- Import direction is strictly downward. `infrastructure/` never imports `service`/`api`/
  `recommendation`; `carbon/` imports nothing from the app; `recommendation/` imports only
  `carbon.CarbonEngineError`. **No circular import.**
- Repository boundary: `infrastructure/*_repo.py`; protocols `CarbonRepository`,
  `CropAccessChecker`, `CropPersistChecker`.
- Provider boundary: none yet (no external model provider exists).
- God service: `service.py` (module-level, not one class).

---

## 3. Proposed RAG placement

RAG serves Recommendation, so it lives **inside** the recommendation package, following the
repo's own convention: pure domain/application package at `backend/<domain>/`, Protocols
declared next to their consumer (like `rules.CarbonCalculator`), concrete adapters in
`backend/infrastructure/`, wiring in `main.py`.

```
Recommendation application (future RagQuestionService, thin)
        │
        ▼
recommendation/rag/orchestrator.py   ← pure orchestration, no I/O of its own
        │
        ▼
recommendation/rag/contracts.py      ← Protocols (ports)
      ↙            ↘
retrieval adapters   generation adapters      (infrastructure/, future phases)
```

---

## 4. Project tree

Created this round (✅) and proposed for later phases (⏳):

```
backend/
  recommendation/
    __init__.py, engine.py, rules.py          (unchanged — Core V1)
    rag/                                      ✅ provider-neutral RAG core
      __init__.py        public surface
      intents.py         RagIntent, RagMode, AccessLevel, evidence policy, required_access()
      errors.py          flat typed errors (§15)
      models.py          RagQuestionRequest, RetrievalQuery, EvidenceChunk, EvidenceRef,
                         GeneratedAnswer, GenerationInput, RagAnswerResult, ...
      context.py         SeasonRagContext + build_season_context() (field picking only)
      contracts.py       Protocols: SeasonAccessGate, SeasonFactsSource, KnowledgeRetriever,
                         AnswerGenerator, WhatIfSimulator; AuthorizedSeasonScope
      retrieval.py       build_retrieval_query(), assert_tenant_isolation()
      citations.py       validate_citations(), resolve_citations()
      grounding.py       validate_grounding()
      what_if.py         HypotheticalChange, WhatIfResult, CarbonScenarioWhatIf
      orchestrator.py    RagOrchestrator.answer()
  rag_application.py                          ⏳ thin RagQuestionService + caller-bound
                                                 SeasonAccessGate / SeasonFactsSource adapters
                                                 (composes SupabaseReadRepository, CarbonService,
                                                 CvService; NOT inside service.py)
  infrastructure/
    knowledge_repo.py                         ⏳ KnowledgeRetriever (pgvector / FTS) — V1.3
    llm_generator.py                          ⏳ AnswerGenerator for one provider — V1.4
    knowledge_ingest/ (script/CLI, offline)   ⏳ parse → clean → chunk → embed → index
  api.py                                      ⏳ ONE thin route, POST /v1/crop-seasons/{id}/questions
  tests/
    fixtures/rag_fakes.py                     ✅ FakeAccessGate, FakeFactsSource, FakeRetriever,
                                                 FakeGenerator, FakeCarbonCalculator
    test_rag_*.py                             ✅
docs/rag/RAG_V1_ARCHITECTURE.md, RAG_V1_DATA_CONTRACT.md   ✅
```

No `backend/ai/`, no `rag_service.py` god file, no second "ports/adapters" pattern.

---

## 5. Dependency rules

Allowed:

```
api (route)  →  rag_application (service)  →  recommendation.rag.orchestrator
                                             →  recommendation.rag.contracts (Protocols)
infrastructure adapters  →  implement recommendation.rag.contracts  (structural typing)
recommendation.rag  →  pydantic, stdlib, carbon.{SCENARIOS, CarbonEngineError},
                        recommendation.rules.CarbonCalculator
```

Forbidden (enforced by `tests/test_rag_architecture.py` where marked ⛔):

| From | To | |
|---|---|---|
| `recommendation.rag` | any vendor SDK (openai, anthropic, google, cohere, langchain, …) | ⛔ |
| `recommendation.rag` | vector vendors (pgvector, chromadb, pinecone, qdrant, faiss, …) | ⛔ |
| `recommendation.rag` | `supabase`, `psycopg`, `httpx`, `requests`, `fastapi`, `infrastructure`, `service`, `api`, `main` | ⛔ |
| `recommendation.rag` | `carbon.engine/methodology/factors` (formulas, factors, GWP) | ⛔ |
| `recommendation.rag` | float literals (copied factors) | ⛔ |
| `recommendation` core (`engine`, `rules`, `__init__`) | `recommendation.rag` (core must not depend on RAG) | ⛔ |
| prompt builder (inside generator adapter) | database client | design rule |
| retriever adapter | CarbonEngine / CarbonService | design rule |
| LLM adapter | Supabase tables | design rule |
| React / Flutter | vector store or LLM provider | design rule (only `/v1` API) |

---

## 6. Q&A intents

| Intent | Example | Grounding source | External evidence required |
|---|---|---|---|
| `explain` | "Tại sao vụ này carbon cao?", "0.58 kg CO2e/kg nghĩa là gì?" | `SeasonRagContext` (Carbon breakdown, metrics) | no (cited if used) |
| `compare` | "Nước/kg cao hơn benchmark không?" | benchmark **must** be a retrieved, cited source (none exists today — M05 doc §R2) | **yes** |
| `recommend` | "Tôi nên cải thiện gì trước?" | deterministic signals + cited guidance | **yes** |
| `what_if` | "Nếu chuyển sang AWD thì sao?" | `WhatIfResult` from `CarbonService` (`persist=False`) | no |
| `evidence` | "Nguồn tài liệu nào hỗ trợ?" | retrieved chunks | **yes** |
| `data_gap` | "Tôi còn thiếu dữ liệu nào?" | `data_completeness`, Carbon readiness, data-task signals | no |
| `unknown` | anything unclassified | treated conservatively | **yes** |

Intent comes from the typed request today; a classifier port is a later phase. The route
never branches on intent — policy lives in `intents.py`.

---

## 7. Request lifecycle

```
POST /v1/crop-seasons/{id}/questions (future)  — Depends(_read_repo) caller JWT
  1. RagQuestionRequest validated (extra=forbid: no org/permission/filter/table fields)
  2. access_gate.authorize(crop_season_id, required_access(intent, mode))   ← FIRST, before any AI cost
       → AuthorizedSeasonScope (org/farm/plot/season resolved by RLS, never by client)
  3. context = build_season_context(scope, facts, mode)    authoritative reads, field picking only
  4. what_if = simulator.simulate(scope, hypothetical)     only for intent=what_if
  5. query   = build_retrieval_query(question, intent, scope)  tenant filter from scope
  6. evidence = retriever.retrieve(query)                   → RetrievalUnavailable on failure
  7. assert_tenant_isolation(evidence, scope)              → TenantIsolationViolation (fail closed)
  8. no evidence + evidence-required intent → RagAnswerResult(status=insufficient_evidence)  (no LLM call)
  9. raw = generator.generate(GenerationInput)              → GenerationUnavailable on failure
 10. GeneratedAnswer.model_validate(raw)                    → InvalidGeneratedSchema (no regex parsing)
 11. validate_grounding(answer, intent, evidence, context)  → CitationMismatch / GroundingFailed
 12. RagAnswerResult assembled by trusted code: citations resolved from chunk metadata,
     signals/what-if numbers copied from authoritative sources, never from the generator
```

---

## 8. Retrieval / generation split

**Ingestion (offline, never in a request):** document → parse → clean → chunk → metadata
(`source_id`, `document_id`, `document_version`, `chunk_id`, visibility, organization) →
embed → index. A CLI/job under `infrastructure/knowledge_ingest/` (V1.3+).

**Query (per request):** season context → query builder → retrieve (filters first) →
optional rerank → `EvidenceChunk`s → generation → grounding. Retriever never persists and
never calls Carbon; generator never touches the DB.

---

## 9. Deterministic rules vs RAG

Rules are unchanged this round. Classification of what exists today:

| Rule / element | Class | RAG may |
|---|---|---|
| R1 trigger: recorded regime = `irrigated_continuous_flooding` AND engine AWD delta > 0 (`rules.evaluate_awd_rule`) | **A. HARD** | never add/remove an AWD recommendation |
| R1 `co2e_total_kg_before/after/delta/percent` | **A. HARD** (CarbonService authoritative) | quote, never recompute |
| R1 `impact_status=unavailable` + reason | **A. HARD** | explain, never fill a number |
| R3 data-completeness triggers (`yield`, `water`, `fertilizer`, `cost` missing) | **A. HARD** | never mark data as present |
| R3 "not a quantified result" | **A. HARD** | never attach an impact to a `data_task` |
| water regime (`ipcc_water_regime`, `pre_season_water_regime`) | **B. SIGNAL** | use as context |
| `data_completeness`, Carbon readiness `missing_inputs` | **B. SIGNAL** | use for DATA_GAP |
| CV inference (label/confidence/uncertain) | **B. SIGNAL** (optional) | mention as recorded; never re-diagnose |
| recommendation `status` (accepted/dismissed) | **B. SIGNAL** | respect the farmer's decision |
| `title`, `reason`, `compared_to` copy | **C. PRESENTATION** | rephrase/explain in plain Vietnamese |
| R2 fertilizer/pesticide/seed benchmarks | **not implemented** (no benchmark source) | must NOT be invented; COMPARE requires cited evidence |

Enforced structurally: `GeneratedAnswer` has no numeric Carbon/metric fields (`extra=forbid`);
a generated recommendation that names a `rule_code` must match an existing signal; the result's
`signals` and `what_if` are copied from authoritative sources.

---

## 10. What-if design

```
question → intent WHAT_IF → HypotheticalChange (typed, allow-listed)
        → validate allowed field (V1: water_regime_scenario ∈ {awd, continuous_flooding})
        → CarbonScenarioWhatIf.simulate(scope, change)
             ├─ CarbonService.calculate(id, "as_recorded", persist=False)
             └─ CarbonService.calculate(id, change.scenario, persist=False)
        → WhatIfResult(available | unavailable, engine numbers, input hashes, persisted=False)
        → answer generation (explains the numbers, cannot supply them)
```

- The real season is never mutated; `persist=False` is hard-coded in the adapter and the
  result type pins `persisted: Literal[False]`.
- `CarbonEngineError` → `status="unavailable"` with the engine's reason (same behaviour as R1).
- Fertilizer reduction ("giảm 10% phân") is **not supported**: `CarbonService` has no
  hypothetical-activity input today. Adding one is a Carbon service API extension → D2.
- A later real change goes through the normal activity write flow, never through RAG.

---

## 11. Authorization

Authorization runs **before** any context read, retrieval, or generation.

| Mode | Gate | Persistence |
|---|---|---|
| `ask` (EXPLAIN/COMPARE/…) | read access to the season (RLS `user_can_read_crop` via caller JWT) | none |
| `preview` (fresh deterministic signals) | read access (see D1) | none — `persist=False` everywhere |
| `persist` (future, not in V1 skeleton) | existing Core V1 write gate: `crop_write_authz.assert_can_write_crop` (farmer, same org, `user_can_write_crop`), re-checked in the write txn | via existing `RecommendationService` path; new storage needs a schema decision (D4) |

`required_access(intent, mode)` is the single place that maps a request to an `AccessLevel`.
The gate adapter reuses existing checks (no duplicated permission SQL). Viewer = read-only,
former owner = historical read only, manager ≠ farmer-only writes — all inherited unchanged.
A denied/unknown season → `RagAccessDenied` → 404 `not_found` (same as Recommendation/CV).
The orchestrator rejects a scope whose `crop_season_id` differs from the request.

---

## 12. Tenant isolation

| Knowledge | Namespace | Filter |
|---|---|---|
| PUBLIC (approved guides, agronomy docs, policy/methodology docs) | `visibility="public"`, `organization_id=None` | none beyond public |
| TENANT PRIVATE (HTX/farm documents) | `visibility="tenant"` | `organization_id` (+ optional `farm_id` / `crop_season_id` metadata) |

- `RetrievalQuery.tenant` is built **only** from `AuthorizedSeasonScope`; the request has no
  organization field.
- The retriever adapter must apply filters inside the store query (before ranking), never by
  asking the LLM.
- The orchestrator re-checks every returned chunk (`assert_tenant_isolation`); any foreign
  tenant chunk → `TenantIsolationViolation`, fail closed, nothing generated. Cross-tenant
  evidence is a security failure, not a quality issue.

---

## 13. Grounding and citations

- Citation = `EvidenceRef(source_id, chunk_id)` that must exist in **this request's**
  retrieved evidence. Unknown source, unknown chunk, duplicate ref in a list → `CitationMismatch`.
- Every generated recommendation (an expert claim) needs ≥1 valid citation, else
  `GroundingFailed`; evidence-required intents with zero citations → `GroundingFailed`.
- A generated recommendation naming a `rule_code` absent from the season's signals → `GroundingFailed`.
- Insufficient evidence is a **valid result** (`status="insufficient_evidence"`), not an error.
- URL/title/section/version shown to users come from trusted chunk metadata
  (`resolve_citations`), never from generated text. The generator cannot emit URLs.
- Failed grounding is never persisted (fail closed).

---

## 14. Prompt-injection boundary

Retrieved text is **untrusted data**. Architecture contract:

1. Application policy (system prompt, rules, output schema) is owned by the generator adapter
   and sent in the provider's system/instruction channel; evidence is sent separately as
   delimited data (`GenerationInput.evidence`), never concatenated into policy.
2. Evidence cannot change permissions: authorization already happened (step 2) and tenant
   filtering is in code.
3. Evidence cannot change Carbon/metrics: those numbers are not in the generator's output
   schema; the result copies them from authoritative sources.
4. Evidence cannot trigger DB/tool calls: the generator contract has no tools in V1.
5. Evidence cannot override deterministic rules or invent citations: grounding rejects it.
6. Secrets never enter `GenerationInput` (no tokens, keys, raw rows).

`tests/test_rag_orchestrator.py` includes an injected-chunk case proving 3 and 5.

---

## 15. Error model

Flat, small (`recommendation/rag/errors.py`), each with a stable `code` for the existing
`{"detail": {"error": {"code", "message"}}}` envelope:

| Error | Proposed HTTP (future route) |
|---|---|
| `RagAccessDenied` | 404 `not_found` (no enumeration) |
| `UnsupportedHypothetical` | 422 `unsupported_hypothetical` |
| `RetrievalUnavailable` | 503 `retrieval_unavailable` |
| `GenerationUnavailable` | 503 `generation_unavailable` |
| `InvalidGeneratedSchema` | 502 `invalid_generated_schema` |
| `GroundingFailed` / `CitationMismatch` (subclass) | 502 `grounding_failed` / `citation_mismatch` |
| `TenantIsolationViolation` | 500 `tenant_isolation_violation` + security log |
| insufficient evidence | **200**, `status="insufficient_evidence"` |

---

## 16. Observability (design only)

Per request, one structured log line in the existing `key=value` style plus `Server-Timing`
phases (`infrastructure/profiling`): `request_id`, `intent`, `mode`, `status`,
`retrieval_ms`, `evidence_count` (public/tenant), `generation_ms`, `grounding_result`
(ok/citation_mismatch/grounding_failed), `insufficient_evidence` flag, `provider_error` class.
Rates (insufficient-evidence rate, provider failure rate) derive from these lines.

Never logged: JWT, passwords, service-role/provider keys, the full prompt, the full
`SeasonRagContext`, evidence text of tenant documents, farmer names.

---

## 17. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Global `backend/ai/` package | competes with the existing domain-package convention; would pull Carbon/auth knowledge into a grab-bag |
| One `rag_service.py` god service | `service.py` already shows the cost of that shape |
| LLM computes impact / CO2e | violates the single Carbon source of truth |
| Prompt-enforced tenant isolation | not a security control; filters must be in code/store |
| Regex/JSON-in-text parsing of model output | brittle; structured output validated by `GeneratedAnswer` instead |
| Replace deterministic rules with RAG | rules are explainable, versioned and tested; RAG adds explanation/evidence |
| Persist answers in `season_recommendations` now | needs new columns (citations, question) → schema decision D4 |
| Agentic tool-calling LLM with DB tools | breaks "generator has no DB access"; deferred indefinitely |

---

## 18. Future phases

| Phase | Scope | Gate |
|---|---|---|
| V1.3 Retrieval | ingestion CLI, `knowledge_repo.py` (pgvector or Postgres FTS), migration for `knowledge_documents/chunks` with RLS, `rag_application.py` adapters, D3 lineage read | decisions D1/D3, migration approval |
| V1.4 Generation | one provider adapter behind `AnswerGenerator`, structured output, prompt policy, offline eval set | D5 provider choice |
| V1.5 API + UI | thin route, Farmer Web Q&A panel (read-only), observability | API catalog + OpenAPI update |
| V1.6 What-if+ | hypothetical activity inputs in `CarbonService` (D2) | Carbon owner approval |
| V1.7 Persist | store grounded answers/citations (D4) under existing write gate | schema decision |

## Open decisions (none blocks this skeleton)

- **D1** Read-tier what-if/preview: Core V1 only runs `persist=False` engine calls for farmers
  with write authority. The brief asks for read-tier preview. Skeleton follows the brief in
  one function (`required_access`); a product owner must confirm before a route exposes it.
- **D2** Hypothetical activity changes (fertilizer −10 %, straw) need a `CarbonService`
  hypothetical-input API — a Carbon-owner decision (no formula change).
- **D3** `organization_id`/`farm_id` for the tenant filter need an additive, RLS-scoped
  season-lineage read (no schema change).
- **D4** Persisting Q&A answers/citations needs new storage (migration).
- **D5** LLM provider, data-residency and cost limits.
