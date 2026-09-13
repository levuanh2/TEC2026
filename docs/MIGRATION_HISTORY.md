# AgriCarbon Migration History

The database is now reconstructed only from the version-controlled files in `supabase/migrations/`. The baseline was previously stored at `docs/Data/AgriCarbon_FULL.sql`; Git history confirms it was tracked, and it has been moved rather than copied so there is one authoritative schema source.

| Order | Migration | Purpose | Depends on |
|---:|---|---|---|
| 001 | `20260907000000_baseline.sql` | Full product schema: `private`, `audit`, `pm`, public enums/tables/functions/triggers/indexes/RLS/policies/views, and storage policies | Supabase-provided `auth` and `storage` schemas |
| 002 | `20260908000000_carbon_methodology_alignment.sql` | IPCC/MRV fields, methodology metadata, carbon breakdown audit fields, and detailed carbon view | 001 |
| 003 | `20260908000001_carbon_calculation_scope_audit.sql` | Initial audit columns recording crop-season methodology inputs | 001, 002 |
| 004 | `20260908000002_crop_season_carbon_scope.sql` | Locks Carbon Calculation scope to Crop Season; optional batch traceability | 001, 002, 003 |
| 005 | `20260908000003_carbon_success_allows_unknown_yield.sql` | Relaxes `carbon_success_chk`: a succeeded calculation only requires `total_co2e_kg`, not `yield_kg`. Found during pre-connection audit — the engine's documented "known total, unknown yield" success state (SRS FR-1a-11/NFR-03) violated the original CHECK and would have rejected every persist call for a season without a harvest record yet. Verified end-to-end against local Supabase (real insert, not in-memory). | 001, 004 |
| 006 | `20260908134822_grant_private_schema_service_role.sql` | Grants the service role usage on `private` so backend repositories can call the access helpers | 001 |
| 007 | `20260910080441_farmer_web_activity_idempotency.sql` | `activities.web_idempotency_key` plus a per-recorder unique index, for Farmer Web submissions that have no registered device | 001 |
| 008 | `20260911120000_season_recommendations.sql` | Season recommendation storage (M05) | 001 |
| 009 | `20260913090000_allow_owner_soft_delete_activities.sql` | Lets a scoped recorder soft-delete their own activity from a client that writes through RLS, and pins the ownership fields that decision rests on. Found at runtime on a real device: a client can never set `deleted_at` itself, because PostgreSQL applies SELECT policies to the new row of an UPDATE and `activities_select` requires `deleted_at is null`. Adds `private.user_can_delete_activity`, the `public.soft_delete_activity(uuid)` entry point, and a trigger making `recorded_by` / `activity_type` / `(device_id, client_event_id)` immutable to clients; `activities_update` additionally refuses to hand an unowned row to a third party. `activities_select` is deliberately unchanged. Verified against the hosted database as role `authenticated` with a real JWT claim. | 001, 007 |

## Object ownership

### Baseline

Creates schemas (`private`, `audit`, `pm`); controlled enums; product/PM tables including `crop_seasons`, `production_batches`, `activities`, activity-detail tables, `emission_factor_sets`, `emission_factors`, `carbon_calculations`, and `carbon_breakdowns`; helper/validation/auth functions; update/audit/business triggers; indexes; RLS and policies; public/PM views; and policies on `storage.objects`.

It references `auth.users` and `storage.objects`, which must be supplied by the Supabase runtime. It is therefore validated with Supabase local development, not a bare PostgreSQL container.

### Methodology alignment

Adds IPCC water/pre-season enums and Crop Season data fields; straw dry-matter and timing fields; carbon breakdown `gas_kg`, formula expression/metadata and methodology provenance; carbon methodology status/fields; and `v_carbon_results_detailed`.

### Crop-season scope migrations

`20260908b` introduced recorded scope/input columns but retained a batch-required FK as a temporary guard. `20260908c` backfills the season FK from existing batch links, makes the season FK required, makes Batch nullable, adds a new-season duplicate guard, validates optional batch/season compatibility, and keeps RLS readable through the Crop Season boundary.

## From-zero command

```powershell
npx supabase start
npx supabase db reset
python scripts/validate_supabase_schema.py
```

Re-run and verified 2026-09-08 (post-audit): all 5 migrations apply clean from zero, validator all-PASS (one expected empty-factor-set WARN), and a real end-to-end smoke test against the local instance (seed → `SupabaseCarbonRepository` → engine → persist) succeeded for both a season with yield and a season without yield — the exact case migration 005 fixes.

Run these only against a local Supabase environment. `db reset` is destructive to that local test database and must never target a hosted project.

## Hosted-project reconciliation (2026-09-08)

The linked hosted project already contained a schema matching the tracked baseline, but its Supabase migration history was empty. A read-only `supabase db diff --from linked --to migrations` confirmed the only schema deltas were the three expected methodology/scope migrations. Therefore `20260907000000` was recorded as applied with `supabase migration repair`; no baseline SQL was re-run. The three additive migrations were then deployed and the remote migration history now matches all four files. This is reconciliation of an existing baseline, not a replacement for the from-zero chain above.
