# RAG V1 — Recommendation Q&A Architecture

Status: **architecture + provider-neutral skeleton, hardened** (branch
`feature/rag-v1-architecture`, base `main` @ `11e5db0`). No LLM, no vector store, no embeddings,
no ingestion, no route, no UI, no migration, no persistence. Typed contracts: [`RAG_V1_DATA_CONTRACT.md`](RAG_V1_DATA_CONTRACT.md).

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
| No read-only what-if | `/v1/carbon/calculate` always persists and needs write authority; `persist=False` runs only inside `RecommendationService.generate` (write-gated) | Kept: WHAT_IF/PREVIEW stay write-gated (D1 closed) |
| Season lineage not exposed | `season_view`/`_farm_view` omit `farm_id`/`cooperative_id` | Behind the `SeasonScopeResolver` port; additive read in V1.3 (D3 closed) |
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

Created (✅) and proposed for later phases (⏳):

```
backend/
  recommendation/
    __init__.py, engine.py, rules.py          (unchanged — Core V1)
    rag/                                      ✅ provider-neutral RAG core
      __init__.py        public surface
      intents.py         RagIntent, RagMode, AccessLevel, INTENT_POLICIES, required_access()
      errors.py          flat typed errors (§15)
      models.py          request, scope, what-if, GroundedFact/FactRef, EvidenceChunk/EvidenceRef,
                         GeneratedAnswer (untrusted shape)
      context.py         SeasonRagContext + build_season_context() (field picking only)
      contracts.py       Protocols: SeasonScopeResolver, SeasonFactsSource, KnowledgeRetriever,
                         AnswerGenerator, WhatIfSimulator
      facts.py           build_fact_catalog(), assert_fact_scope(), has_comparison_basis()
      claims.py          {{fact:id}} placeholders → declared catalog facts
      prose.py           generated-prose policy: placeholder grammar, no raw number, no link
      retrieval.py       build_retrieval_query(), assert_tenant_isolation()
      citations.py       validate_citations(), resolve_citations()
      grounding.py       validate_grounding()
      what_if.py         CarbonScenarioWhatIf, ensure_supported()
      answers.py         GenerationInput, RagAnswerResult (trusted), trusted state copy
      orchestrator.py    RagOrchestrator.answer()
  rag_application.py                          ⏳ thin RagQuestionService + caller-bound
                                                 SeasonScopeResolver / SeasonFactsSource adapters
                                                 (composes SupabaseReadRepository, CarbonService,
                                                 CvService, crop_write_authz; NOT inside service.py)
  infrastructure/
    knowledge_repo.py                         ⏳ KnowledgeRetriever (pgvector / FTS) — V1.3
    llm_generator.py                          ⏳ AnswerGenerator for one provider — V1.4
    knowledge_ingest/ (script/CLI, offline)   ⏳ parse → clean → chunk → embed → index
  api.py                                      ⏳ ONE thin route, POST /v1/crop-seasons/{id}/questions
  tests/
    fixtures/rag_fakes.py                     ✅ FakeScopeResolver, FakeFactsSource, FakeRetriever,
                                                 FakeGenerator, FakeCarbonCalculator
    test_rag_*.py                             ✅
```

No `backend/ai/`, no `rag_service.py` god file, no second "ports/adapters" pattern.

---

## 5. Dependency rules

Allowed:

```
api (route)  →  rag_application (service)  →  recommendation.rag.orchestrator
                                             →  recommendation.rag.contracts (Protocols)
infrastructure adapters  →  implement recommendation.rag.contracts  (structural typing)
recommendation.rag  →  pydantic, stdlib (incl. re), carbon.{SCENARIOS, CarbonEngineError},
                        recommendation.rules.CarbonCalculator
```

Forbidden (enforced by `tests/test_rag_architecture.py` where marked ⛔):

| From | To | |
|---|---|---|
| `recommendation.rag` | any vendor SDK (openai, anthropic, google, cohere, langchain, …) | ⛔ |
| `recommendation.rag` | vector vendors (pgvector, chromadb, pinecone, qdrant, faiss, …) | ⛔ |
| `recommendation.rag` | `supabase`, `psycopg`, `httpx`, `requests`, `fastapi`, `infrastructure`, `service`, `api`, `main` | ⛔ |
| `recommendation.rag` | `carbon.engine/methodology/factors` (formulas, factors, GWP) | ⛔ |
| `recommendation.rag` | factor configuration / files (`yaml`, `os`, `pathlib`, `open()`, `emission_factors`, `.yaml`, `ParameterSet`) | ⛔ |
| `recommendation` core (`engine`, `rules`, `__init__`) | `recommendation.rag` (core must not depend on RAG) | ⛔ |
| app layers (`api`, `main`, `service`, `infrastructure`) | `recommendation.rag` (not wired in V1) | ⛔ |
| prompt builder (inside generator adapter) | database client | design rule |
| retriever adapter | CarbonEngine / CarbonService | design rule |
| LLM adapter | Supabase tables | design rule |
| React / Flutter | vector store or LLM provider | design rule (only `/v1` API) |

Numbers are protected **behaviourally**, not by guessing what a literal means: the earlier
"no float literal in `rag/`" AST rule was too broad and is removed. Instead, tests prove that
every authoritative value comes from an injected Core V1 service (`CarbonCalculator`, the facts
source) and that a generated number needs a `FactRef` (§13).

---

## 6. Q&A intents and access matrix

Policy lives in one table, `intents.INTENT_POLICIES`; the route never branches on intent.

| Intent | Required access (Core V1) | Persistence | Grounding | May recommend |
|---|---|---|---|---|
| `explain` | READ | none | system facts; documents optional | no |
| `compare` | READ | none | ≥1 comparison fact (finalized benchmark or another authorized season) — else `insufficient_evidence / no_comparison_basis` | no |
| `evidence` | READ | none | ≥1 retrieved document citation | no |
| `data_gap` | READ | none | completeness / readiness / data-task facts | no |
| `recommend` | **WRITE** | none | ≥1 document citation; every recommendation cited | yes |
| `what_if` | **WRITE** | none (`persist=False`) | ≥1 what-if fact from `CarbonService` | yes |
| `unknown` | READ | none | — returns `needs_clarification`, runs nothing else | no |
| any intent, `mode=preview` | **WRITE** | none | fresh deterministic signals | per intent |

READ = Core V1 read scope (RLS `user_can_read_crop`).
WRITE = Core V1 recommendation/CV write authority: **active `farmer` membership in the season's
organization AND `private.user_can_write_crop`** (`infrastructure/crop_write_authz.py`).

**WHAT_IF V1 = water regime only: AWD ↔ continuous flooding** (against the recorded baseline).
Fertilizer amount, straw, pesticide, seed rate or any other activity change: **NOT SUPPORTED IN
V1** → `UnsupportedWhatIfDimension` (§10).

**COMPARE** has two legitimate forms only:
- A. this season vs another season the caller may read, using that season's authoritative metrics;
- B. this season vs a **finalized, source-backed benchmark** (`status="finalized"`).

Core V1 has no benchmark source, so B is empty today; COMPARE then answers
"Không có benchmark hoặc vụ đối chiếu đủ điều kiện để so sánh." "HTX average", "regional
average" or "industry standard" are never invented: a benchmark number can only be a
`GroundedFact`.

**UNKNOWN** (no intent, or `unknown`) is never a backdoor to RECOMMEND/WHAT_IF: after the READ
check it returns `status="needs_clarification"` with trusted copy and loads no context, runs no
Carbon call, no retrieval and no generation. It cannot carry a hypothetical (schema).
A future intent classifier may map a question to a concrete intent; the access matrix then
applies to that intent.

---

## 7. Request lifecycle

```
POST /v1/crop-seasons/{id}/questions (future)  — Depends(_read_repo) caller JWT
  1. RagQuestionRequest validated (extra=forbid: no org/permission/filter/table/persist field)
  2. scope_resolver.resolve(crop_season_id, required_access(intent, mode))     ← FIRST
       → AuthorizedSeasonScope (season → plot → farm → org via Core V1 checks, never the client)
  3. intent UNKNOWN → needs_clarification (stop)
  4. what-if dimension unsupported → UnsupportedWhatIfDimension (stop; calculator untouched)
  5. context  = build_season_context(scope, facts_source, mode)    authoritative reads, picking only
  6. what_if  = simulator.simulate(scope, hypothetical)             only for intent=what_if
  7. catalog  = build_fact_catalog(context, what_if)                trusted GroundedFacts
     assert_fact_scope(catalog, scope, context)                     → TenantIsolationViolation
  8. COMPARE without a comparison fact → insufficient_evidence / no_comparison_basis (no model call)
  9. evidence = retriever.retrieve(build_retrieval_query(...))      → RetrievalUnavailable
     assert_tenant_isolation(evidence, scope)                       → TenantIsolationViolation
 10. no documents + intent needs documents → insufficient_evidence / no_evidence_retrieved
 11. raw = generator.generate(GenerationInput(question, intent, facts=catalog, evidence))
                                                                    → GenerationUnavailable
 12. ASSEMBLY BOUNDARY (§13):
       UNTRUSTED raw → GeneratedAnswer.model_validate         → InvalidGeneratedSchema
                     → document citations                     → CitationMismatch
                     → fact references + numeric claims       → FactReferenceMismatch / GroundingFailed
                     → intent policy                          → GroundingFailed
                     → trusted fact rendering (render_answer)  → FactReferenceMismatch
                     → TRUSTED RagAnswerResult (assembled by the orchestrator)
```

`GeneratedAnswer` is **untrusted structured output**; `RagAnswerResult` is **trusted assembled
output**. The renderer never runs before grounding, and a generator can never supply the final
`answer`, `answer_template` or a fact value (unknown fields are schema errors).

---

## 8. Retrieval / generation split

**Ingestion (offline, never in a request):** document → parse → clean → chunk → metadata
(`source_id`, `document_id`, `document_version`, `chunk_id`, visibility, organization) →
embed → index. A CLI/job under `infrastructure/knowledge_ingest/` (V1.3+).

**Query (per request):** season context → facts → query builder → retrieve (filters first) →
optional rerank → `EvidenceChunk`s → generation → grounding. Retriever never persists and
never calls Carbon; generator never touches the DB.

---

## 9. Deterministic rules vs RAG

Rules are unchanged. RAG may never override a HARD element.

| Element | Class | RAG may |
|---|---|---|
| Authorization (read scope, write authority, access matrix) | **HARD** | nothing — decided before RAG work |
| Data-completeness constraints (`data_completeness`, R3 triggers for yield/water/fertilizer/cost) | **HARD** | never mark data present; never attach an impact to a `data_task` |
| Rule activation and thresholds (R1: recorded regime = continuous flooding AND engine delta > 0) | **HARD** | never add, remove or re-trigger a rule; `rule_code` must exist |
| Carbon results and impact (`co2e_total_kg_*`, `impact_status`, what-if numbers) | **HARD** (CarbonService) | reference by `FactRef` only |
| What-if scenario validation (water regime only, allow-listed scenarios) | **HARD** | nothing |
| Accepted/dismissed recommendation state | **HARD** | respect it; never re-propose a dismissed rule as new |
| Water regime (`ipcc_water_regime`, `pre_season_water_regime`) | **SIGNAL** | use as context |
| Carbon readiness (`missing_inputs`, `can_calculate`) | **SIGNAL** | use for DATA_GAP |
| CV inference (label/confidence/uncertain) | **SIGNAL** | mention as recorded; never re-diagnose or prescribe |
| Season status and other contextual attributes | **SIGNAL** | use as context |
| Wording, explanation order, concise rationale (`title`, `reason`, `compared_to` copy) | **PRESENTATION** | rephrase in plain Vietnamese |
| R2 fertilizer/pesticide/seed benchmarks | not implemented (no source) | never invented |

---

## 10. What-if design

```
question → intent WHAT_IF → HypotheticalChange(dimension, scenario)
        → ensure_supported(change)        dimension ∉ {water_regime} → UnsupportedWhatIfDimension
        → CarbonScenarioWhatIf.simulate(scope, change)   (re-checks support itself)
             ├─ CarbonService.calculate(id, "as_recorded", persist=False)
             └─ CarbonService.calculate(id, change.scenario, persist=False)
        → WhatIfResult(available | unavailable, engine numbers, input hashes, persisted=False)
        → what_if.<scenario>.* GroundedFacts → answer references them by FactRef
```

- **V1 scope:** `dimension="water_regime"`, `scenario ∈ {awd, continuous_flooding}` (from
  `carbon.SCENARIOS` minus the baseline).
- **Not supported in V1:** `fertilizer_amount`, `straw_management`, `pesticide`, `seed_rate`,
  `other_activity`. They are representable so they can be refused with a typed error — never
  guessed by a model, never computed in RAG, never silently ignored. The refusal happens after
  authorization and before any context read or Carbon call.
- The real season is never mutated; `persisted: Literal[False]`.
- `CarbonEngineError` → `status="unavailable"` with the engine's reason (same as rule R1).
- **D2 (future):** a `CarbonService` hypothetical-input extension (no formula change) would add
  dimensions; a later real change still goes through the normal activity write flow.

---

## 11. Authorization

Authorization runs **before** context loading, what-if, retrieval and generation (§6 matrix).

- **D1 (closed):** RECOMMEND, WHAT_IF and `mode=preview` keep Core V1 write semantics even with
  `persist=False`. No new access for viewers, managers, former owners or other organizations.
  A manager/viewer preview would be a separate product decision and endpoint/mode — not in V1.
- **D3 (closed, implementation deferred):** `SeasonScopeResolver.resolve(crop_season_id, level)`
  authorizes and resolves season → plot → farm → organization into `AuthorizedSeasonScope
  (actor_id, organization_id, farm_id, plot_id, crop_season_id, access)`. The RAG core never
  reads that lineage itself. The V1.3 adapter (in `rag_application.py`) must reuse Core V1
  boundaries: the caller-bound `SupabaseReadRepository` (RLS) for READ and lineage, and
  `crop_write_authz.assert_can_write_crop` for WRITE. Additive read method only, no schema change.
- Permissions never come from the request. A refusal at any level is `RagAccessDenied` → 404
  `not_found` (same as Recommendation/CV: neither scope nor the refusing rule can be probed).
- The orchestrator rejects a scope whose `crop_season_id` differs from the request.

---

## 12. Tenant isolation

| Knowledge | Namespace | Filter |
|---|---|---|
| PUBLIC (approved guides, agronomy docs, policy/methodology docs) | `visibility="public"`, `organization_id=None` | none beyond public |
| TENANT PRIVATE (HTX/farm documents) | `visibility="tenant"` | `organization_id` (+ optional `farm_id`) |
| SYSTEM FACTS | `GroundedFact.organization_id` / `crop_season_id` | caller's org (or None for a public benchmark); this season or an authorized comparison season |

- `RetrievalQuery.tenant` is built **only** from `AuthorizedSeasonScope`.
- The retriever adapter must filter inside the store query (before ranking), never via the LLM.
- Backstops in code: `assert_tenant_isolation` (documents) and `assert_fact_scope` (facts). Any
  foreign item → `TenantIsolationViolation`, fail closed, nothing generated.

---

## 13. Grounding: system facts, knowledge evidence, numeric claims

Two grounding channels, **never mixed**:

| | SYSTEM FACT | KNOWLEDGE EVIDENCE |
|---|---|---|
| What | an authoritative AgriCarbon value | a retrieved approved document passage |
| Type | `GroundedFact(fact_id, kind, value, unit, source, provenance, crop_season_id, organization_id, authoritative=True)` | `EvidenceChunk` |
| Built by | trusted code: `facts.build_fact_catalog(context, what_if)` | ingestion + retriever |
| Referenced by | `FactRef(fact_id)` | `EvidenceRef(source_id, chunk_id)` |
| Invalid ref | `FactReferenceMismatch` | `CitationMismatch` |

Fact ids are `<subject>.<group>.<name>`: `current.metrics.water_per_kg`,
`current.carbon.total_co2e_kg`, `current.signal.<rule_code>.co2e_total_kg_delta`,
`what_if.awd.delta_co2e_kg`, `benchmark.<benchmark_id>`, `season.<id>.metrics.co2e_per_kg`.
A fact id is never accepted as a document citation and vice versa (tested both ways).

**Quantitative claim policy (V1):**

1. A generator never writes a business number. It writes `{{fact:<fact_id>}}` in text and lists
   the id in `fact_refs`. Business numbers are Carbon totals/intensity/breakdown, resource
   metrics, benchmarks, rule impacts, what-if impacts, costs and percentages.
2. `GeneratedAnswer` has no numeric, URL or fact-value field; `FactRef` is only an id.
3. Every `fact_ref` and placeholder must exist in this request's catalog, and every placeholder
   must be declared in `fact_refs`.
4. **Generated prose policy (`prose.py`, fail closed, decided after PR #6 review).** It applies
   to every generator-controlled text field (`GeneratedAnswer.texts()`: `answer`, `rationale`,
   recommendation `title` and `actions`, `limitations`) and never to trusted data
   (`GroundedFact` values, `EvidenceChunk` content, chunk metadata, Carbon/metrics/benchmark
   results). Outside canonical placeholders the prose may contain:
   - **no numeric character at all** (`str.isnumeric`: any script's digits, superscripts,
     subscripts, fractions) → `GroundingFailed("number without a system fact")`. V1 does not
     guess which numbers are harmless. Known casualties, rejected on purpose until an explicit
     trusted allowlist or structured source exists (decided before V1.4 with D6): years
     ("vụ 2026"), "1 phải 5 giảm", agronomic measures ("15 cm", "3 lần"), list/ordinal
     numbering, inline markers like "[1]", and **gas names with digits** (`CO2`, `CO2e`, `CH4`,
     `N2O`) — the generator must write "khí mê-tan", "khí nhà kính", … or the allowlist must
     cover them. A unit appended by the trusted renderer ("kg CO2e") is not affected: the rule
     runs on the template, before rendering.
   - **no link** — `scheme://`, `www.`, `mailto:`/`javascript:`/`data:`/`file:`/`tel:`, a
     bare domain (`.com/.net/.org/.info/.io/.gov/.edu/.int/.vn`), a Markdown link `[..](..)`
     or HTML (`<a`, `href`) → `GroundingFailed("link in generated text")`. A source URL reaches
     a client only as trusted `CitedEvidence.url`, resolved from chunk metadata via `EvidenceRef`
     (which has no URL field).
   - **no brace** — the only reserved syntax is exactly `{{fact:<fact_id>}}` (`fact_id` =
     `[A-Za-z0-9_.:-]+`). `{{ fact:id }}`, `{{FACT:id}}`, `{{fact:}}`, `{fact:id}`, unbalanced
     braces, … → `FactReferenceMismatch("malformed fact placeholder")`.
   Numbers spelled out in words are still not detected (known gap, MEDIUM); rule 1 plus the
   provider prompt cover them.
5. **Server-side trusted rendering (decided).** After grounding passes, `answers.render_answer`
   replaces every placeholder in `answer`, `rationale`, recommendation titles/actions and
   `limitations` with `format_fact(fact)`. The result keeps all three views:
   - `answer` — rendered text; default Web/Flutter clients display it as-is and never need to
     implement placeholder replacement;
   - `answer_template` — the grounded text with `{{fact:<id>}}` kept (provenance, highlighting,
     debugging);
   - `facts` — the referenced `GroundedFact`s with canonical values, units and provenance.
   Advanced clients may use `answer_template` + `facts` to highlight numbers or open provenance.
6. **Renderer rules.** It only looks up an id in the validated catalog, formats it and substitutes
   it. It never calculates, converts units, rounds, infers a missing value, queries a DB or calls
   a provider.
   - `None` → `chưa có dữ liệu` (never `0`); booleans → `có` / `không`; strings as stored.
   - Numbers: the stored value's exact shortest representation, Vietnamese grouping
     (`.` thousands, `,` decimals), only trailing fraction zeros dropped
     (`2900.0 kg CO2e` → `2.900 kg CO2e`, `0.58` → `0,58`, `0.1+0.2` → `0,30000000000000004`).
     No precision metadata exists on facts today, so none is invented; a display-precision field
     would be a later, explicit contract change.
   - Unit: the fact's own unit appended verbatim (`kg CO2e`, `m3`, `VND/kg`, …). The
     dimensionless `fraction` is shown as the bare number — never ×100 into `%`, which would be
     a unit conversion. A generator must not repeat the unit after a placeholder.
   - Unknown id, malformed placeholder (the renderer re-applies the placeholder grammar of
     rule 4 before substituting) or non-finite value → `FactReferenceMismatch` (fail closed);
     no raw `{{...}}` ever reaches a client.
7. **Known V1 consequence (D6):** a quantity quoted from a cited document ("bón 100 kg N/ha")
   is rejected too, because documents are not system facts. This fails closed and may reject
   many real-model RECOMMEND answers. Whether, and how, cited document quantities are allowed
   (e.g. verbatim-quote spans checked against chunk text) is decided before V1.4.
   Server-side rendering and the prose policy do **not** change D6 (quoted document numbers are
   rejected by the no-raw-number rule), nor the known gap that numbers spelled out in words are
   not detected (MEDIUM).
8. **Canonical facts are not presentation values (D7, decided; display deferred).** String facts
   render exactly as stored, so a code such as `irrigated_continuous_flooding` can appear inside
   a Vietnamese sentence, and `fraction` facts (`co2e_percent_delta`) render as `0,2069`, not
   `20,69%`. This is accepted for V1:
   - `GroundedFact.value` and `GroundedFact.unit` always hold the **canonical** value and unit.
     The grounding core (`facts.py`, grounding, renderer) never converts a fraction to a
     percentage, changes a unit, localizes an enum or replaces a code with a label, and never
     mutates a fact to suit a UI.
   - Farmer-friendly display (`0.2069 fraction` → `20,69%`, `irrigated_continuous_flooding` →
     "Tưới ngập liên tục") belongs to a later trusted **presentation layer** (server or client)
     that may derive `display_value` / `display_label` from the canonical fact without changing
     it. No backend Vietnamese label exists for IPCC water-regime codes today (`mrv/labels.py`
     covers other vocabularies).
   - Deferred to the presentation / Q&A UI phase; not a blocker for this skeleton.

**Other grounding rules:** document citations must be chunks retrieved for this request
(unknown source/chunk, duplicates rejected); recommendations only for action-producing intents,
each with ≥1 document citation and no invented `rule_code`; documents required for
RECOMMEND/EVIDENCE; COMPARE must reference a comparison fact; WHAT_IF must reference a what-if
fact. URL/title/section shown to users come from trusted chunk metadata. Insufficient evidence is
a valid result. Failed grounding is never returned.

---

## 14. Prompt-injection boundary

Retrieved text is **untrusted data**. Architecture contract:

1. Application policy (system prompt, rules, output schema) is owned by the generator adapter
   and sent in the provider's system/instruction channel; evidence is sent separately as
   delimited data (`GenerationInput.evidence`), never concatenated into policy.
2. Evidence cannot change permissions: authorization already happened (step 2) and tenant
   filtering is in code.
3. Evidence cannot change Carbon/metrics/benchmarks: numbers reach the answer only through
   trusted `GroundedFact`s.
4. Evidence cannot trigger DB/tool calls: the generator contract has no tools in V1.
5. Evidence cannot override deterministic rules, invent citations or invent facts: grounding
   rejects it.
6. Secrets never enter `GenerationInput` (no tokens, keys, raw rows).

`tests/test_rag_orchestrator.py` injects a chunk demanding a zero Carbon value, a "90%" claim,
an invented source, an invented fact and an invented rule; each is rejected.

---

## 15. Error model

Flat, small (`recommendation/rag/errors.py`), each with a stable `code` for the existing
`{"detail": {"error": {"code", "message"}}}` envelope:

| Error | Proposed HTTP (future route) |
|---|---|
| `RagAccessDenied` | 404 `not_found` (no enumeration, no rule disclosure) |
| `UnsupportedWhatIfDimension` | 422 `unsupported_what_if_dimension` |
| `RetrievalUnavailable` | 503 `retrieval_unavailable` |
| `GenerationUnavailable` | 503 `generation_unavailable` |
| `InvalidGeneratedSchema` | 502 `invalid_generated_schema` |
| `GroundingFailed` / `CitationMismatch` / `FactReferenceMismatch` (subclasses) | 502 |
| `TenantIsolationViolation` | 500 `tenant_isolation_violation` + security log |
| insufficient evidence / needs clarification | **200**, `status` field |

---

## 16. Observability (design only)

Per request, one structured log line in the existing `key=value` style plus `Server-Timing`
phases (`infrastructure/profiling`): `request_id`, `intent`, `mode`, `status`,
`retrieval_ms`, `evidence_count` (public/tenant), `fact_count`, `generation_ms`,
`grounding_result` (ok/citation_mismatch/fact_reference_mismatch/grounding_failed),
`insufficient_reason`, `provider_error` class. Rates (insufficient-evidence, clarification,
provider failure) derive from these lines.

Never logged: JWT, passwords, service-role/provider keys, the full prompt, the full
`SeasonRagContext` or fact catalog, evidence text of tenant documents, farmer names.

---

## 17. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Global `backend/ai/` package | competes with the existing domain-package convention |
| One `rag_service.py` god service | `service.py` already shows the cost of that shape |
| LLM computes impact / CO2e / benchmarks | violates the single Carbon/Metrics source of truth |
| Model writes numbers, NLP checks them afterwards | unreliable; placeholders + facts prevent it structurally |
| Client-side placeholder rendering only | every client (Web, Flutter) would need its own renderer; one miss shows raw `{{fact:...}}` to farmers |
| Prompt-enforced tenant isolation | not a security control; filters must be in code/store |
| Regex/JSON-in-text parsing of model output | brittle; `GeneratedAnswer.model_validate` instead |
| Replace deterministic rules with RAG | rules are explainable, versioned and tested |
| Read-tier RECOMMEND/WHAT_IF preview | would widen Core V1 permissions (D1) |
| Persist Q&A in `season_recommendations` or new tables in V1 | answers are ephemeral (D4) |
| Agentic tool-calling LLM with DB tools | breaks "generator has no DB access" |
| Blanket "no float literal" AST rule | guessed business meaning from any number; replaced by import + behavioural tests |

---

## 18. Future phases

| Phase | Scope | Gate |
|---|---|---|
| V1.3 Retrieval | ingestion CLI, `knowledge_repo.py` (pgvector or Postgres FTS), migration for knowledge documents/chunks with RLS, `rag_application.py` adapters (D3 resolver + facts source) | migration approval |
| V1.4 Generation | one provider adapter behind `AnswerGenerator`, structured output, prompt policy, offline eval set | D5, D6 |
| V1.5 API + UI | thin route, Farmer Web Q&A panel (displays `answer`), optional fact highlighting from `answer_template` + `facts`, observability | API catalog + OpenAPI update |
| V1.6 What-if+ | hypothetical activity inputs in `CarbonService` | D2 |
| later | Q&A history/audit | D4 reopened as its own phase |

## Decisions

Closed:
- **D1** Access matrix: READ for EXPLAIN/COMPARE/EVIDENCE/DATA_GAP/UNKNOWN; Core V1 WRITE for
  RECOMMEND, WHAT_IF and `mode=preview`, even with `persist=False`.
- **D3** `SeasonScopeResolver` port resolves and authorizes scope; adapter deferred to V1.3,
  reusing RLS + `crop_write_authz`, no schema change, no DB access in the RAG core.
- **D4** RAG V1 is **ephemeral**: no question history, generated answer, retrieved evidence set
  or conversation is stored; no migration. Deterministic Recommendation persistence is
  unchanged. History/audit later = separate phase + migration + retention/privacy decision.
- **D7** Canonical facts are not presentation values: `GroundedFact.value`/`unit` stay
  canonical; a later presentation layer may add `display_value`/`display_label` (percent,
  Vietnamese enum labels) without mutating them. Implementation deferred to the presentation /
  Q&A UI phase.

Open (future, none blocks this skeleton):
- **D2** `CarbonService` hypothetical-input extension (no formula change) for fertilizer/straw/
  pesticide/seed-rate what-ifs — Carbon owner decision.
- **D5** LLM provider, data residency and cost limits.
- **D6** Quantities quoted from cited documents: allowed or not, and how they are verified.
- Benchmark source: where finalized benchmarks come from (none exists; COMPARE-B stays empty).
