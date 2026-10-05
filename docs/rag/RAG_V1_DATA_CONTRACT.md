# RAG V1 — Data Contract

Code: `backend/recommendation/rag/` (frozen pydantic v2 models, `extra="forbid"`; pydantic is
already in the production lock — no new dependency). Architecture:
[`RAG_V1_ARCHITECTURE.md`](RAG_V1_ARCHITECTURE.md).

Conventions: identifiers are non-empty strings ≤128 chars (UUID objects from psycopg are
coerced to their string); text fields are stripped and length-bounded; every model is
immutable; an unknown field is a validation error. Nothing in this contract is persisted
(decision D4: RAG V1 is ephemeral).

---

## 1. `SeasonRagContext` (`context.py`)

The season's authoritative data, assembled by `build_season_context(scope, facts, mode=)`.

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
| `benchmarks` | `BenchmarkFacts[]` — benchmark_id, metric, value, unit, label, source_reference, organization_id, status; **only `status="finalized"` kept** (empty in Core V1) |
| `comparison_seasons` | `ComparisonSeasonFacts[]` — crop_season_id, organization_id, season_code, planting_date, `metrics` (same shape as above); other seasons the caller may read |

Every scalar is `Optional`: an absent or null source value stays `None`, never `0`. No raw
ORM/Supabase row is passed on; only the listed fields are picked. The context is input to the
fact catalog (§3), not to the generator.

## 2. `RagQuestionRequest` (`models.py`)

| Field | Type | Rule |
|---|---|---|
| `question` | str 1..2000 | stripped |
| `crop_season_id` | id | the only scope input; checked by the scope resolver |
| `intent` | `RagIntent \| None` | `explain, compare, recommend, what_if, evidence, data_gap, unknown`; None → `unknown` |
| `mode` | `RagMode` | `ask` (stored signals) \| `preview` (fresh signals, `persist=False`, **WRITE**); default `ask` |
| `hypothetical` | `HypotheticalChange \| None` | required iff `intent == what_if` |

Absent by design: organization/farm id, role, permission flag, filter, SQL, table name, persist
flag, conversation id.

**Access matrix** (`intents.INTENT_POLICIES`, `required_access(intent, mode)`):

| Intent | Required access | Persistence | Evidence |
|---|---|---|---|
| explain | READ | none | system facts; documents optional |
| compare | READ | none | ≥1 comparison fact, else `no_comparison_basis` |
| evidence | READ | none | ≥1 document citation |
| data_gap | READ | none | system facts |
| recommend | WRITE | none | ≥1 document citation per answer and per recommendation |
| what_if | WRITE | none | ≥1 what-if fact |
| unknown | READ | none | none — `needs_clarification` |
| `mode=preview` (any intent) | WRITE | none | per intent |

READ = Core V1 read scope. WRITE = active `farmer` membership in the season's organization AND
`private.user_can_write_crop` (`crop_write_authz`).

## 3. `AuthorizedSeasonScope` and `SeasonScopeResolver` (D3)

`AuthorizedSeasonScope(actor_id, organization_id, farm_id, plot_id, crop_season_id, access)`.
Produced only by `SeasonScopeResolver.resolve(crop_season_id, level)` (`contracts.py`), which
must reuse Core V1 checks (RLS read + lineage through the caller-bound read repository; WRITE via
`crop_write_authz`) and raise `RagAccessDenied` for unknown, out-of-scope or under-privileged
callers. No permission ever comes from the request; the RAG core never queries the lineage.

## 4. `GroundedFact` / `FactRef` — system facts

`GroundedFact` (`models.py`, built only by `facts.build_fact_catalog(context, what_if)`):

| Field | Type | Note |
|---|---|---|
| `fact_id` | `[A-Za-z0-9_.:-]+`, ≤200 | stable within the request; built by trusted code |
| `kind` | `FactKind` | season_attribute, resource_metric, carbon_total, carbon_intensity, carbon_breakdown, data_completeness, carbon_readiness, rule_signal, cv_signal, benchmark, comparison_season, what_if |
| `value` | str \| int \| float \| bool \| None | None = "not available", never 0 |
| `unit` | str \| None | `kg`, `m3`, `kg CO2e`, `m3/kg`, `kg/kg`, `kg CO2e/kg`, `VND/kg`, `fraction` |
| `source` | str | `season`, `resource_metrics`, `carbon_service`, `recommendation_rules`, `cv_service`, `benchmark` |
| `provenance` | flat map | calculation_id, input_hash, engine/ef versions, rule_code/version, benchmark source, … |
| `crop_season_id`, `organization_id` | id \| None | scope; None only for a public benchmark |
| `authoritative` | `Literal[True]` | |

Fact id convention: `current.metrics.<metric>`, `current.carbon.total_co2e_kg`,
`current.carbon.breakdown.<i>`, `current.completeness.<group>`, `current.readiness.*`,
`current.season.<attr>`, `current.signal.<rule_code>.<field>`, `current.cv.<i>.<field>`,
`what_if.<scenario>.<field>`, `benchmark.<benchmark_id>`, `season.<crop_season_id>.metrics.<metric>`.

`FactRef(fact_id)` — only an id. A generator cannot state, override or round a value.
`assert_fact_scope` rejects any fact outside the caller's organization (except a public
benchmark) or outside {this season, authorized comparison seasons} → `TenantIsolationViolation`.

## 5. `RetrievalQuery`

`text` (the question), `intent`, `tenant: TenantScope(organization_id, farm_id?, crop_season_id?)`
(always from the authorized scope), `include_public` (default true), `top_k` 1..50 (default 8).
Built by `retrieval.build_retrieval_query`. The retriever applies `tenant` inside the store query.

## 6. `EvidenceChunk` / `EvidenceRef` — knowledge evidence

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

`EvidenceRef(source_id, chunk_id)`, hashable: valid only if that exact pair was retrieved for this
request. Duplicate in one list, unknown source or unknown chunk → `CitationMismatch`. A fact id
is never a valid `EvidenceRef` and a chunk id is never a valid `FactRef`.

## 7. `GeneratedAnswer` (UNTRUSTED) and `RagAnswerResult` (TRUSTED)

`GenerationInput(question, intent, capability, facts: GroundedFact[], evidence: EvidenceChunk[])` —
what a generator sees. No raw context, no policy, no secrets. `capability`
(`informational | action_producing`) comes from `INTENT_POLICIES[intent]` (validator-enforced);
neither the caller nor the model chooses it.

| Intent | Capability | Access |
|---|---|---|
| EXPLAIN / COMPARE / EVIDENCE / DATA_GAP | INFORMATIONAL | READ |
| RECOMMEND / WHAT_IF | ACTION_PRODUCING | WRITE |
| UNKNOWN | none — no generation | READ |

`GeneratedAnswer` — the full untrusted shape (validated by `model_validate`):
`status (generated | insufficient_evidence)`, `answer`, `rationale?`,
`recommendations[AnswerRecommendation(title, actions[], evidence_refs[], fact_refs[], rule_code?)]`,
`evidence_refs[]`, `fact_refs[]`, `limitations[]`, `confidence?`.
**Per capability:** INFORMATIONAL generation (READ-tier intents) is parsed with `InformationalAnswer` —
the same fields **without `recommendations`** (emitting it, even empty, is `InvalidGeneratedSchema`) —
and then lifted to `GeneratedAnswer` with no recommendations for grounding. ACTION_PRODUCING
generation uses `GeneratedAnswer`. Free text can still phrase advice: D8 (ARCHITECTURE §11).

**No numeric field, no URL field, no fact value.** Quantities appear as `{{fact:<fact_id>}}`.
Its prose fields may hold no numeric character, no link, no brace outside that exact
placeholder grammar and only letters, marks, whitespace and plain sentence punctuation
(`prose.py`, ARCHITECTURE §13 rule 4); "CO2e"/"CH4", years, "1 phải 5 giảm" and "TP.HCM" are
rejected on purpose in V1.

Validation order: schema → document citations → generated-prose policy (placeholder grammar, no
raw number, no link) → fact references → intent policy
→ trusted fact rendering. `GeneratedAnswer` is **untrusted structured output**; it is never
returned to a client.

`RagAnswerResult` — **trusted assembled output**, built by the orchestrator only:

| Field | Origin |
|---|---|
| `status` | `generated \| insufficient_evidence \| needs_clarification` |
| `intent`, `mode`, `crop_season_id` | request / authorized scope |
| `answer` | grounded answer **rendered** by `render_answer` (no placeholder left); trusted copy for non-generated states |
| `answer_template` | grounded answer with `{{fact:<id>}}` kept; set for `generated` and `generator_declined`, None for trusted-copy states |
| `rationale`, `recommendations[]` (title, actions), `limitations[]` | grounded text, rendered |
| `confidence` | grounded `GeneratedAnswer` |
| `facts[]` | exactly the referenced `GroundedFact`s from the catalog, canonical values unchanged |
| `evidence[]` (`CitedEvidence`) | `resolve_citations` from trusted chunk metadata |
| `insufficient_reason` | `no_evidence_retrieved \| no_comparison_basis \| generator_declined`, set iff insufficient |
| `signals[]` | copied from `SeasonRagContext.signals` |
| `what_if` | `WhatIfResult` from the Carbon service, or None |
| `basis` | `AnswerBasis(carbon_calculation_id, carbon_input_hash, ef_config_version, signal_rule_codes)`; None for `needs_clarification` |

Only a `generated` result carries recommendations; a `generated` result always has
`answer_template`.

**Client contract.** Default clients display `answer` (and the rendered rationale,
recommendations, limitations) directly — no placeholder replacement needed. Advanced clients may
use `answer_template` + `facts` to highlight numbers, show units/provenance or build a richer UI.

**Rendering rules** (`answers.format_fact`): `None` → `chưa có dữ liệu` (never `0`); bool →
`có`/`không`; string as stored; number → exact stored value with Vietnamese grouping (`.`
thousands, `,` decimals, trailing fraction zeros dropped, no rounding) + the fact's own unit;
`fraction` → bare number (no ×100). Unknown/malformed placeholder or non-finite value →
`FactReferenceMismatch`.

**Canonical, not presentation (D7).** `GroundedFact.value` and `unit` are canonical and are never
converted, localized or mutated for display (`0.2069` stays `0.2069 fraction`;
`irrigated_continuous_flooding` stays the raw code). A later trusted presentation layer may
derive `display_value` / `display_label` (e.g. `20,69%`, "Tưới ngập liên tục") from them;
deferred to the presentation / Q&A UI phase.

## 8. Insufficient evidence and clarification

Valid results, not exceptions:

| State | When | Model called |
|---|---|---|
| `needs_clarification` | intent `unknown` / missing (after READ check) | no; no context, Carbon or retrieval either |
| `insufficient_evidence / no_comparison_basis` | COMPARE with no finalized benchmark and no comparison season — answer "Không có benchmark hoặc vụ đối chiếu đủ điều kiện để so sánh." | no |
| `insufficient_evidence / no_evidence_retrieved` | RECOMMEND/EVIDENCE with no retrieved document | no |
| `insufficient_evidence / generator_declined` | generator returned `insufficient_evidence` (no recommendations allowed) | yes |

Deterministic `signals` and `what_if` numbers are still returned when insufficient.

## 9. What-if (`models.py`, `what_if.py`)

`HypotheticalChange(dimension: WhatIfDimension, scenario?)`:

| Dimension | V1 | Rule |
|---|---|---|
| `water_regime` | **supported** | `scenario ∈ {awd, continuous_flooding}` (from `carbon.SCENARIOS` minus `as_recorded`) |
| `fertilizer_amount`, `straw_management`, `pesticide`, `seed_rate`, `other_activity` | **not supported** | no `scenario`; refused with `UnsupportedWhatIfDimension` after authorization, before any read or Carbon call |
| anything else | invalid | request validation error |

`WhatIfResult(change, status available|unavailable, unavailable_reason, baseline_total_co2e_kg,
hypothetical_total_co2e_kg, delta_co2e_kg, baseline_input_hash, hypothetical_input_hash,
engine_version, ef_config_version, persisted: Literal[False])`; `available` ⇒ all three totals,
`unavailable` ⇒ a reason and no number. `CarbonScenarioWhatIf(carbon: CarbonCalculator)` calls
`calculate(..., persist=False)` twice and refuses unsupported dimensions itself too. Its values
reach the answer only as `what_if.<scenario>.*` facts.

## 10. Source-of-truth matrix

| Data | Source (Core V1) | Transform allowed | Business calculation allowed |
|---|---|---|---|
| scope ids | `SeasonScopeResolver` (caller JWT + RLS + `crop_write_authz`) | none | **NO** |
| `season.*` | `SupabaseReadRepository.season()` (`season_view`) | pick, ISO date → date | **NO** |
| `activity.*` | `SupabaseReadRepository.activity_summary()` | pick | **NO** |
| `metrics.*` | `SupabaseReadRepository.metrics()` (`_compute_metric_totals`) | pick, numeric str → float | **NO** (never Σ, ÷, or null→0) |
| `carbon.*` | `CarbonService.stored(id, "as_recorded")` | pick, UUID → str | **NO** |
| `carbon_readiness.*` | `CarbonService.readiness(id)` | pick | **NO** |
| `signals` (ask) | `SupabaseReadRepository.recommendations()` | pick | **NO** |
| `signals` (preview, WRITE) | `recommendation.generate_recommendations(id, carbon=CarbonService, metrics)` | pick | **NO** |
| `cv_signals` | `CvService.list()` | pick | **NO** (no re-diagnosis) |
| `benchmarks` | finalized benchmark source (none in Core V1 → `[]`) | pick, drop unfinalized | **NO** (never invented) |
| `comparison_seasons` | `metrics()` of other seasons the caller can read (RLS) | pick, drop the season itself | **NO** |
| `what_if.*` | `CarbonService.calculate(id, scenario, persist=False)` ×2 | before − after (same as rule R1) | **NO** |
| `GroundedFact` | the rows above | copy value, attach id/unit/provenance | **NO** |
| `evidence[*]` display | `EvidenceChunk` trusted metadata | none | **NO** |
| any number in an answer | a referenced `GroundedFact` | server-side rendering: format value + own unit | **NO** — generator never supplies it; renderer never calculates |

`SeasonFactsSource` methods map 1:1 to the "Source" column; a future adapter composes those
calls and never queries a business table itself.

## 11. Forbidden in the RAG layer

- CO2e, CH4, N2O, GWP, emission factors, scaling factors, or any Carbon formula; loading factor
  configuration (`config/*.yaml`, `ParameterSet`) or any file.
- Resource Metric numerators, denominators, per-kg ratios, aggregation; `null → 0`.
- Benchmarks of any kind unless finalized and source-backed.
- Recommendation triggers or thresholds (the deterministic rules own them).
- Authorization decisions (resolvers reuse RLS / `crop_write_authz`).
- Any business number written by a generator instead of referenced as a `GroundedFact`.
- Storing questions, answers, evidence sets or conversations (D4).
