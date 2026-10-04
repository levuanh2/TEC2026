# RAG V1 — Data Contract

Code: `backend/recommendation/rag/` (frozen pydantic v2 models, `extra="forbid"`; pydantic is
already in the production lock — no new dependency). Architecture:
[`RAG_V1_ARCHITECTURE.md`](RAG_V1_ARCHITECTURE.md).

Conventions: identifiers are non-empty strings ≤128 chars (UUID objects from psycopg are
coerced to their string); text fields are stripped and length-bounded; every model is
immutable; an unknown field is a validation error.

---

## 1. `SeasonRagContext` (`context.py`)

The season's authoritative facts, assembled by `build_season_context(scope, facts, mode=)`.

| Field | Type |
|---|---|
| `organization_id`, `farm_id`, `plot_id`, `crop_season_id` | ids from `AuthorizedSeasonScope` |
| `season` | `SeasonFacts` — season_code, crop_type, variety_name, status, planting/expected/actual harvest date, ipcc_water_regime, pre_season_water_regime, cultivation_days |
| `activity` | `ActivityFacts` — total, count_by_type, harvests, harvests_with_area, harvested_area_ha, fertilizer_has_nutrient, first_seeding_at, last_harvest_at |
| `metrics` | `ResourceMetricFacts` — yield_kg, water_m3, fertilizer_kg, total_co2e_kg, water/fertilizer/co2e/cost `_per_kg`, `data_completeness{water,fertilizer,cost,carbon}` |
| `carbon` | `CarbonFacts \| None` — calculation_id, scenario, calculation_kind, total_co2e_kg, water_regime_applied, methodology_tier, mrv_compliant, ef_config_version, engine_version, input_hash, calculated_at, `breakdown[{category, gas, source, co2e_kg}]` |
| `carbon_readiness` | `CarbonReadinessFacts \| None` — can_calculate, blocking_count, input_hash, `missing_inputs[{code,label,flow}]` |
| `signals` | `DeterministicSignal[]` — rule_code, rule_version, type, status, title, reason, compared_to, impact_status, impact_unavailable_reason, co2e_total_kg_before/after/delta, co2e_percent_delta |
| `cv_signals` | `CvSignal[]` — label, confidence, uncertain, model_version, created_at |

Every scalar fact is `Optional`: an absent or null source value stays `None`, never `0`.
No raw ORM/Supabase row is passed on; only the listed fields are picked.

## 2. `RagQuestionRequest` (`models.py`)

| Field | Type | Rule |
|---|---|---|
| `question` | str 1..2000 | stripped |
| `crop_season_id` | id | the only scope input; checked by the access gate |
| `intent` | `RagIntent \| None` | `explain, compare, recommend, what_if, evidence, data_gap, unknown`; None → `unknown` |
| `mode` | `RagMode` | `ask` (stored signals) \| `preview` (fresh signals, `persist=False`); default `ask` |
| `hypothetical` | `HypotheticalChange \| None` | required iff `intent == what_if` |

Absent by design: organization/farm id, role, permission flag, filter, SQL, table name,
persist flag (persistence is a later phase under the existing write gate, decision D4).
`AuthorizedSeasonScope(actor_id, organization_id, farm_id, plot_id, crop_season_id, access)`
is produced only by a `SeasonAccessGate`.

## 3. `RetrievalQuery`

`text` (the question), `intent`, `tenant: TenantScope(organization_id, farm_id?, crop_season_id?)`
(always from the authorized scope), `include_public` (default true), `top_k` 1..50 (default 8).
Built by `retrieval.build_retrieval_query`. The retriever applies `tenant` inside the store query.

## 4. `EvidenceChunk`

| Field | Required | Note |
|---|---|---|
| `source_id`, `document_id`, `chunk_id` | yes | stable ids assigned at ingestion |
| `document_version` | no | |
| `title` | yes | ≤500 |
| `section` | no | |
| `content` | yes | **untrusted** text |
| `source_type` | yes | `guideline \| policy \| methodology \| research \| tenant_document` |
| `visibility` | yes | `public` (no tenant fields) \| `tenant` (`organization_id` required, optional `farm_id`) |
| `url` | no | `https://` only, trusted ingestion metadata |
| `authority` | no | `official \| peer_reviewed \| extension \| internal` |
| `published_at` | no | date |
| `metadata` | no | flat scalar map |

`chunk.ref` → `EvidenceRef`.

## 5. `RagAnswerResult` (`answers.py`)

| Field | Origin |
|---|---|
| `status` | `generated \| insufficient_evidence` |
| `intent`, `mode`, `crop_season_id` | request / authorized scope |
| `answer`, `rationale`, `recommendations[]`, `limitations[]`, `confidence` | grounded `GeneratedAnswer` |
| `evidence[]` (`CitedEvidence`) | `resolve_citations` from trusted chunk metadata |
| `insufficient_reason` | `no_evidence_retrieved \| generator_declined`, set iff insufficient |
| `signals[]` | copied from `SeasonRagContext.signals` (authoritative) |
| `what_if` | `WhatIfResult` from the Carbon service, or None |
| `basis` | `AnswerBasis(carbon_calculation_id, carbon_input_hash, ef_config_version, signal_rule_codes)` |

The generator's own output contract is `GeneratedAnswer`: `status`, `answer`, `rationale?`,
`recommendations[AnswerRecommendation(title, actions[], evidence_refs[], rule_code?)]`,
`evidence_refs[]`, `limitations[]`, `confidence?` — **no numeric field, no URL field**.
Validated with `GeneratedAnswer.model_validate`; never parsed from text.

## 6. `EvidenceRef`

`(source_id, chunk_id)`, hashable. Valid only if that exact pair was retrieved for this
request. Duplicate in one list, unknown source, or unknown chunk → `CitationMismatch`.

## 7. Insufficient evidence

A valid result, not an exception:

- evidence-required intent (`compare, recommend, evidence, unknown`) and the retriever returned
  nothing → `insufficient_evidence / no_evidence_retrieved`; the generator is **not called**;
- the generator returns `status="insufficient_evidence"` (no recommendations allowed) →
  `insufficient_evidence / generator_declined`.

Deterministic `signals` and `what_if` numbers are still returned.

## 8. What-if (`what_if.py`, `models.py`)

`HypotheticalChange(kind="water_regime_scenario", scenario ∈ {awd, continuous_flooding})` —
the allow-list is derived from `carbon.SCENARIOS` minus the baseline `as_recorded`.

`WhatIfResult(change, status available|unavailable, unavailable_reason, baseline_total_co2e_kg,
hypothetical_total_co2e_kg, delta_co2e_kg, baseline_input_hash, hypothetical_input_hash,
engine_version, ef_config_version, persisted: Literal[False])`.
`available` ⇒ all three totals present; `unavailable` ⇒ a reason and no number.
`CarbonScenarioWhatIf(carbon: CarbonCalculator)` calls `calculate(..., persist=False)` twice.

## 9. Source-of-truth matrix

| Context field | Source (Core V1) | Transform allowed | Business calculation allowed |
|---|---|---|---|
| scope ids | `SeasonAccessGate` (caller JWT + RLS; lineage read D3) | none | **NO** |
| `season.*` | `SupabaseReadRepository.season()` (`season_view`) | pick, ISO date → date | **NO** |
| `activity.*` | `SupabaseReadRepository.activity_summary()` | pick | **NO** |
| `metrics.*` | `SupabaseReadRepository.metrics()` (`_compute_metric_totals`) | pick, numeric str → float | **NO** (never Σ, ÷, or null→0) |
| `carbon.*` | `CarbonService.stored(id, "as_recorded")` | pick, UUID → str | **NO** |
| `carbon_readiness.*` | `CarbonService.readiness(id)` | pick | **NO** |
| `signals` (ask) | `SupabaseReadRepository.recommendations()` | pick | **NO** |
| `signals` (preview) | `recommendation.generate_recommendations(id, carbon=CarbonService, metrics)` (`persist=False`) | pick | **NO** |
| `cv_signals` | `CvService.list()` | pick | **NO** (no re-diagnosis) |
| `what_if.*` | `CarbonService.calculate(id, scenario, persist=False)` ×2 | before − after (same as rule R1) | **NO** |
| `evidence[*]` display | `EvidenceChunk` trusted metadata | none | **NO** |

`SeasonFactsSource` methods map 1:1 to the "Source" column; a future adapter composes those
calls and never queries a business table itself.

## 10. Forbidden calculations in the RAG layer

- CO2e, CH4, N2O, GWP, emission factors, scaling factors, or any Carbon formula.
- Resource Metric numerators, denominators, per-kg ratios, or aggregation; `null → 0`.
- Benchmarks of any kind (none exist in Core V1; only a cited source may supply one).
- Recommendation triggers or thresholds (the deterministic rules own them).
- Authorization decisions (gates reuse RLS / `crop_write_authz`).
- Copied numeric constants — enforced: no float literal in `recommendation/rag/`.
