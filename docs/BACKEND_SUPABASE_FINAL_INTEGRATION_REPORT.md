# Backend + Supabase Final Integration Report

## 1. Migration History

See [MIGRATION_HISTORY.md](MIGRATION_HISTORY.md). The chain uses Supabase CLI numeric timestamps and has four ordered files.

## 2. Baseline Migration

`supabase/migrations/20260907000000_baseline.sql` is the Git-tracked full product schema. It was moved from `docs/Data/AgriCarbon_FULL.sql`, rather than copied, so a clean checkout has one schema authority.

## 3. Methodology Migration

`20260908000000_carbon_methodology_alignment.sql` adds IPCC water/pre-season inputs, straw methodology fields, methodology provenance, `gas_kg`, formula metadata, and detailed results view.

## 4. Crop-Season Scope Migration

`20260908000001_carbon_calculation_scope_audit.sql` records the temporary audit fields. `20260908000002_crop_season_carbon_scope.sql` makes Crop Season the required calculation scope, preserves Batch only as nullable traceability, and retains RLS through the crop authorization boundary.

## 5. Database Final Schema

Both the local rebuilt schema and hosted project satisfy:

```text
Farm → Plot → Crop Season
                 ├── Activities
                 ├── Harvest Events
                 ├── Production Batches
                 └── Carbon Calculations
```

`carbon_calculations.crop_season_id` is `NOT NULL`; `production_batch_id` is nullable. The migration guards optional Batch links so they cannot point outside the Crop Season.

## 6. Backend Repository

The existing `infrastructure/supabase_repo.py` is the repository/data-access boundary. It keeps Supabase rows outside `carbon/` and reads tables separately before mapping with `infrastructure/mapping.py`; this prevents one-to-many SQL joins from duplicating yield.

## 7. Supabase Connection

Supabase local was started successfully and used for the rebuild and validator. The hosted project `awazhdqzkktekbwaqiic` was linked through a local PAT (kept outside Git), then verified with the CLI. The MCP OAuth flow remains unavailable because its requested scopes are rejected by the current OAuth service; it is not required for the CLI deployment.

## 8. Data Adapter

`get_crop_bundle()` loads Crop Season, Plot, Farm, active Batches, Activities, and activity detail tables independently. `map_crop_activity_data()` creates `CropActivityData(crop_season_id=...)`; it aggregates all harvest events and does not default water or straw methodology inputs.

## 9. Carbon Calculation Service

`CarbonService.calculate()` loads by `crop_season_id`, invokes the pure engine, and persists `carbon_calculations` with a required Crop Season FK and no batch allocation. The persistence path has factor-set and breakdown provenance handling.

## 10. API

`POST /v1/carbon/calculate` requires `crop_season_id` and supports `awd`, `continuous_flooding`, and `as_recorded`. `GET /v1/crop-seasons/{crop_season_id}/carbon` returns the latest successful season calculation.

## 11. RLS Verification

The local validator passed RLS enabled checks for domain and factor tables, expected carbon/factor policies, authorization functions, and security-invoker result views. The new crop-season policies add access for calculations with a null Batch link; they do not grant client writes.

Hosted role-by-role tests still require dedicated test identities and organization records. The hosted schema has the crop-season policy, but no client/RLS write path was exercised.

## 12. Tests

Existing:

- Carbon-engine and repository/API regression suite.

New:

- Crop Season scope / no-double-counting tests A–E.
- Migration history from a local Supabase empty database.
- Schema validator Unicode-safe console behavior.

Total:

- `93 passed` Python tests.
- `supabase db reset`: all 4 migrations applied.
- `supabase db lint --local`: no schema errors.
- `validate_supabase_schema.py`: all required schema/RLS/view checks passed; one expected empty-factor-set warning.

## 13. Scientific Blockers

There is no published, verified emission-factor set and GWP remains pending verification. The database intentionally contains no fabricated factors. Therefore a real CO2e result remains blocked even though the calculation schema and error paths are ready.

Canonical factor value source remains YAML until an approved import/publish workflow makes the versioned Supabase factor set the single canonical source. Current Supabase factor tables are persistence/audit linkage only; no fake factor was seeded to force a number.

## 14. Security Notes

- `.env.example` now has empty Supabase fields.
- A historical database credential was found in that tracked example file and removed. Treat it as exposed and rotate it before any hosted use.
- Service-role credentials remain backend-only and must never enter Flutter/web clients.
- The hosted database was never reset or dropped. Its pre-existing baseline schema had no migration-history rows; a schema diff verified it matched the tracked baseline, then only `20260907000000` was recorded as already applied. The three additive methodology/scope migrations were then deployed successfully.
- Supabase advisors report no schema errors. Follow-up warnings: enable leaked-password protection in the Dashboard; the two carbon tables intentionally retain both historic batch-read and new crop-season-read SELECT policies so old rows remain readable. The latter is a performance warning, not an RLS bypass.

## 15. Exact commands to run

```powershell
# Local-only rebuild and validation
npx supabase start
npx supabase db reset
$env:SUPABASE_DB_URL='postgresql://postgres:postgres@127.0.0.1:54322/postgres'
python scripts/validate_supabase_schema.py
npx supabase db lint --local
python -m pytest backend/tests -q

# Hosted backend smoke test (MCP OAuth is not required)
Copy-Item backend/.env.example backend/.env
# Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY locally; never commit it.
# Do not use a database password in the backend; use the project URL and service-role key.
```

## 16. Production Readiness

The migration chain is reproducible locally and is deployed to the hosted project. Backend smoke tests remain blocked until `backend/.env` has the correct project URL and backend-only service-role key. Real CO2e remains blocked until an approved verified factor set is published.

MIGRATION REPRODUCIBLE FROM ZERO: YES

SUPABASE CONNECTION: YES (CLI/project link and deployed schema)

BACKEND INTEGRATION: NO (backend credentials/smoke test pending)

API READY: YES

REAL CO2e READY: NO
