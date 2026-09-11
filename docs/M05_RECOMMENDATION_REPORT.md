# M05 — Recommendation Engine (quantified impact) — implementation report

Builds a deterministic, versioned rule engine that reuses the existing Carbon
Engine for every carbon-impact number — never a separately written formula —
on top of the FW-1/FW-2 Farmer Web foundation. No Carbon/MRV code changed;
the only backend touch outside `recommendation/`+`schemas.py`+`api.py`+
`main.py` is a small, targeted exception-handling fix (see §Real Data).

## A. Current state before this task (audit)

No recommendation code existed. `supabase/migrations/20260907000000_baseline.sql`
already had a full dormant schema (`recommendations`, `resource_metric_snapshots`,
`benchmark_snapshots`, `recommendation_rules` — zero rows, zero Python
references anywhere in `backend/`) built around a cross-farm-benchmark
architecture that hard-requires a *finalized* benchmark and a *successful*
carbon_calculations row before any row can exist
(`resource_metric_snapshots.carbon_calculation_id not null`). No cross-farm
benchmark data source exists anywhere in this codebase (only per-farm/org
self-aggregation in `read_repo.py::farm_performance`). `docs/FINAL_MVP_GAP_MATRIX.md`
independently confirmed FR-1b-07/08/09 as NOT STARTED. The Carbon Engine
already exposes `SCENARIOS = ("awd", "continuous_flooding", "as_recorded")`
and `CarbonService.calculate(..., persist=False)` for what-if calls — this
task's entire "impact evaluator" is just calling that twice and diffing.

## B. Recommendation Architecture

```text
RULE ENGINE:      backend/recommendation/rules.py — pure functions, each
                   returning zero or one GeneratedRecommendation. No CH4/N2O
                   math (enforced by tests/test_recommendation_no_carbon_duplication.py,
                   an AST-based check that fails the build if a forbidden
                   methodology identifier — efc/sfw/sfp/gwp/ch4/n2o/ef1fr —
                   ever appears as a real Python identifier in this package).
SERVICE:           backend/service.py::RecommendationService — farmer-scope
                   check (mirrors ActivityWriteService), idempotent
                   generate(), set_status() for accept/dismiss.
IMPACT EVALUATOR:  the *existing* CarbonService — a rule calls
                   `carbon.calculate(crop_season_id, "as_recorded", persist=False)`
                   then `calculate(crop_season_id, "awd", persist=False)` and
                   subtracts total_co2e_kg. No new Carbon code.
REPOSITORY:        backend/infrastructure/recommendation_repo.py — service-role
                   psycopg, same trust model as write_repo.py (authorization
                   established by the caller via SupabaseReadRepository/RLS
                   *before* this repository is touched).
```

Data model: `public.season_recommendations` (new migration
`20260911120000_season_recommendations.sql`), deliberately separate from the
dormant baseline schema — see the migration's own header comment for why
altering that schema instead would have been riskier and still wrong-shaped.
RLS: `select` for `authenticated` scoped by the existing
`private.user_can_read_crop(crop_season_id)` function (same helper
`crop_seasons`/`production_batches` already use); no insert/update grant to
`authenticated` — generation and accept/dismiss are backend-trusted writes,
exactly like activity writes.

## C. Rules Implemented

| Rule | Preconditions | Impact | Production availability |
|---|---|---|---|
| `water.awd_from_continuous_flooding` (R1, optimization) | `as_recorded` Carbon calc succeeds; recorded regime is literally `irrigated_continuous_flooding`; `awd` scenario also calculates; resulting CO2e delta `> 0` | `co2e_total_kg_before/after/delta/percent_delta` from two real Carbon Engine calls | **0 rows today** — blocked by `gwp.ch4` (OI-05), exactly as expected; verified end-to-end with the test factor fixture instead |
| `data.completeness.{yield,water,fertilizer,cost}` (R3, data_task) | the corresponding `metrics()` field/flag is missing | none — `impact_status` is always `unavailable`, `co2e_total_kg_delta` is always `null` | real, appears whenever a real season is missing that field (verified live — see §K) |

R2 (benchmark rules: `fertilizer_n_above_benchmark`, `pesticide_above_benchmark`,
`seed_rate_high`, `awd_drainage_too_few`, `straw_burned`) is **not
implemented** — no legitimate cross-farm/HTX benchmark data source exists in
this codebase, and the brief explicitly forbids inventing one or an
"official" target value. This is the deliberate "quality > count" choice
(brief §B5): two fully evidenced rule families over six weak ones.

## D. Carbon Reuse (exact call path, proving no duplicated formula)

```text
recommendation/rules.py::evaluate_awd_rule()
  → carbon.calculate(crop_season_id, "as_recorded", persist=False)   [CarbonCalculator Protocol]
  → carbon.calculate(crop_season_id, "awd", persist=False)
      → service.py::CarbonService.calculate()                        [same class /v1/carbon/* uses]
          → self._repo.get_crop_bundle(crop_season_id)
          → infrastructure/mapping.py::map_crop_activity_data(bundle)
          → carbon.calculate_carbon(activity_data, scenario, self._params)  [the ONE real engine]
  → delta = baseline.result.total_co2e_kg - proposed.result.total_co2e_kg
```

`rules.py` imports only `carbon.CarbonEngineError` (the error hierarchy) —
never `carbon.methodology`/`carbon.factors` internals, never
`calculate_carbon` directly (asserted by
`test_recommendation_no_carbon_duplication.py::test_recommendation_rules_only_import_carbon_error_types_not_methodology`).
The only number this module ever produces is a plain subtraction of two
numbers the real engine returned.

## E. Quantified Impact — deterministic test example

`tests/test_recommendation_engine.py::test_awd_rule_recommends_when_baseline_is_continuous_flooding`
reuses the exact same fixture (`tests/fixtures/demo_crop.json`) and test
factor set (`tests/fixtures/test_factors.yaml`) that `test_carbon_engine.py`
already verifies by hand — this file does not recompute the expected numbers,
it imports the already-verified constants:

```text
CF_TOTAL (continuous flooding, same demo data) = 5435.4
AWD_TOTAL (awd, same demo data)                = 2920.8
delta                                          = 2514.6
percent                                        = 46.27%
```

The rule's output is asserted `== pytest.approx(...)` against these, and
`carbon.calls == ["as_recorded", "awd"]` asserts it called the real engine
exactly twice, nothing more.

## F. Scientific Blocking Behavior

```text
REAL CO2e READY: NO — docs/CARBON_METHOD.md OI-05, gwp.ch4 unverified.
RECOMMENDATION BEHAVIOR WHEN BLOCKED: the as_recorded Carbon calculation
  itself raises MissingEmissionFactorError for every real season today ->
  evaluate_awd_rule() returns None -> the optimization rule is silently
  absent from the list (never a fabricated/placeholder row). The data_task
  rule is completely independent of Carbon and keeps working normally.
```

## G. API

```text
GET   /v1/crop-seasons/{crop_season_id}/recommendations           — list (any role with read scope, via RLS)
POST  /v1/crop-seasons/{crop_season_id}/recommendations/generate  — idempotent regenerate (farmer scope only)
PATCH /v1/recommendations/{recommendation_id}                     — {"status": "accepted"|"dismissed"} (farmer scope only)
```

Cross-scope / non-farmer / unknown-id all normalize to `404 not_found`,
matching the activities write contract exactly. Unauthenticated → `401`.

## H. Lifecycle

`generated` → `accepted` | `dismissed` (one-way in this MVP; no public
"un-dismiss"). Regenerating (`POST .../generate`) upserts by
`(crop_season_id, rule_code)`: an already-`accepted`/`dismissed` row's
decision and timestamp are preserved — only `generated`-status rows get their
evidence refreshed, and a `generated` row whose rule no longer applies is
pruned. Verified in `test_recommendation_api.py` (idempotent regeneration,
prune-on-resolved, accepted-row-survives-regeneration).

## I. Farmer UX

`web-dashboard/src/farmer/Recommendations.tsx`, wired into `FarmerHome`
(`FarmerExperience.tsx`) replacing the old static "Chưa có khuyến nghị định
lượng" placeholder card with a real one. Calls `generateRecommendations()`
(idempotent) on load — no separate "Generate" button. Card shows title,
reason, `Tác động ước tính` (only for `type=optimization`, rendered as the
formatted CO2e delta when `impact_status=available` or the honest "Chưa thể
ước tính" otherwise — never a fabricated number, brief §B25), `compared_to`
source line, and `[Bỏ qua] [Đã hiểu]`. No raw JSON, no Carbon jargon in the
primary card, no chatbot.

## J. Real Data

```text
REAL FARMER AUTH: PASS — fresh DEMO-FARM-01 QA identity
REAL RECOMMENDATION API: PASS — POST generate / GET list / PATCH status all 200
ACTIONABLE REAL RECOMMENDATIONS: 0 optimization rows (expected — REAL CO2e blocked)
EMPTY/BLOCKED STATE: not applicable — real season had a genuine data_task row
  ("Bổ sung chi phí vật tư") instead of the empty state; accepted it through
  the real UI end to end (honest, low-stakes, non-destructive — only that
  row's status/timestamp; the underlying activities/metrics are untouched)
```

### Real integration blockers found and fixed (genuine, narrow — brief §0 exception)

Unit tests (fakes) were 194/194 green before any real E2E ran; two more
real, non-Carbon-methodology bugs surfaced only against the real
hosted/browser stack, exactly like FW-2's CORS/migration lessons:

1. **Unhandled transient infra exception crashed the whole endpoint.**
   `evaluate_awd_rule()` only caught `CarbonEngineError`, but a dropped
   Supabase connection mid-request (`httpx.RemoteProtocolError`) is not one
   — it 500'd `/recommendations/generate` entirely, taking the unrelated
   `data_task` rule down with it. Fixed: catch `Exception` broadly around
   both Carbon what-if calls, log it distinctly from an expected
   `CarbonEngineError` (`logger.exception(...)`), degrade to the same
   "rule not evaluable now" behavior either way. Two new tests
   (`test_awd_rule_suppressed_not_crashed_by_a_transient_infra_error`,
   the proposed-scenario equivalent) lock this in.
2. **psycopg returns `uuid` columns as Python `UUID` objects.**
   `RecommendationResponse.id`/`.crop_season_id` are declared `str`; FastAPI's
   response serialization rejected the raw `UUID`, 500ing every
   generate/accept/dismiss call (the read-only list route was unaffected —
   PostgREST already serializes `uuid` as a JSON string). Fixed with a
   `_normalize()` helper in `recommendation_repo.py` applied at every
   row-return point; regression-tested with a fake psycopg connection that
   returns real `uuid.UUID` objects
   (`tests/test_recommendation_repo_uuid_normalization.py`).

## K. Tests

```text
backend:        196 passed (165 pre-existing + 31 new: rule engine determinism/
                 insufficient-data/infra-resilience, service/API auth+lifecycle,
                 no-Carbon-duplication architecture check, UUID normalization)
Vitest:         60 passed (58 pre-existing + 2 new: recommendation response mapping)
build:           passed
Farmer mock:     1 passed (unaffected — recommendations empty-state assertion
                 implicit via existing screenshot; mock mode never calls
                 generate/list per usingMockData guard)
Farmer real:     1 passed (farmer-real-recommendations.spec.ts, gated behind
                 REAL_E2E + FARMER_REAL_E2E + FARMER_REAL_RECOMMENDATIONS_E2E)
Management:      1 passed (web-smoke.spec.ts, rerun — no Management code touched)
```

## L. Remaining Gaps

```text
CV field validation           → not part of this task
Seeding/Pesticide/Straw Farmer writes → FW-2 scope, not M05
MRV export generation         → docs/API_CATALOG.md "Chưa có" section, unrelated
REAL CO2e scientific factors  → still blocked, OI-05 (gwp.ch4 unverified)
Flutter runtime verification  → SDK still unavailable in this environment
R2 benchmark rules            → no legitimate cross-farm/HTX data source yet
```

## M. Final Status

```text
M05 RECOMMENDATION MVP: DONE
```

Software fully implemented and tested (rule engine, quantified-impact
evaluator, repository, API, Farmer UX) with the DONE-condition checklist all
green:

```text
DETERMINISTIC RULE ENGINE: PASS
QUANTIFIED IMPACT: PASS
NO DUPLICATED CARBON FORMULA: PASS
NO FABRICATED IMPACT: PASS
INSUFFICIENT-DATA BEHAVIOR: PASS
AUTH/RLS: PASS
FARMER API/UI INTEGRATION: PASS
REGRESSION: PASS
```

Production carbon-impact numbers remain blocked by external scientific
factors (OI-05), not by anything in this implementation — exactly the
state the brief anticipated as an acceptable DONE outcome.
