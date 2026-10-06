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
| 012 | `20260915100000_restrict_mrv_exports_storage_client_access.sql` | P0 fix M7 (docs audit). The baseline `mrv_files_storage_*` policies covered both `mrv-evidence` and `mrv-exports`, so after `20260913150000` made export objects real artifacts, any organization reader (farmer, grant regulator/enterprise viewer) could list and download them straight from the Storage API, and a manager could upload/replace/delete them from a client. Replaces the four policies with identical ones scoped to `mrv-evidence` only; no client policy covers `mrv-exports`, so every client operation on it is denied and the backend (service role) is the only reader/writer. Buckets stay private; `plant-images` untouched. Verified on hosted: a leak reproduction through the real Storage API before apply, then `backend/tests/test_p0_security_policies.py` and `backend/scripts/hosted_p0_security_smoke.py` after apply. (Orders 010/011 are `20260913120000` and `20260913150000`, not yet described in this table.) | 001, 011 |
| 013 | `20260915120000_mrv_export_calculation_crop_season_scope.sql` | P1 / M3 blocker found by hosted verification. The baseline trigger `private.validate_mrv_export_calculation` still required `carbon_calculations.production_batch_id` to be one of the case's `mrv_case_batches`, but since `20260908000002` a calculation is crop-season scoped and the backend writes `production_batch_id` as NULL — so the first MRV export backed by any real persisted calculation would have failed. Same trigger and factor-set rule; the scope rule now requires the calculation's crop season to have a batch linked to the case (how the export service derives its seasons). Out-of-scope seasons are still rejected. Hosted had 0 `carbon_calculations` / `mrv_export_calculations` rows, so nothing was re-interpreted. Reproduced and verified with `backend/tests/test_p1_correctness_policies.py` (rolled back) and `backend/scripts/hosted_p1_correctness_smoke.py`. | 004, 012 |
| 022 | `20261005090000_knowledge_retrieval_lexical_foundation.sql` | RAG Migration A: `knowledge_sources`, `knowledge_documents`, `knowledge_chunks` (approval record, license basis, lifecycle and immutability triggers, RLS for approved public/tenant knowledge), the lexical RPC `match_knowledge_chunks_lexical`, and `private.knowledge_read_blocked()` (no knowledge reads while a password change is pending). Lexical only, no vector. Applied to hosted 2026-10-06. (Orders 014–021 are not yet described in this table.) | 001, 020, 021 |
| 023 | `20261006120000_knowledge_document_artifact_approval_guard.sql` | ST1-DB: one CHECK `knowledge_documents_artifact_approval_chk` — an approved version needs `artifact_ref` that is an opaque ASCII storage path (positive grammar, `C` collation, ≤ 512 chars); `official_url` alone never suffices. Applied to hosted 2026-10-06 (0 knowledge rows). Rollback: `supabase/rollbacks/20261006120000_*.down.sql` | 022 |
| 024 | `20261007090000_knowledge_document_artifact_sha_binding.sql` | ST1.1: one CHECK `knowledge_documents_artifact_sha_binding_chk` — an approved version's `artifact_ref` starts with `knowledge-artifacts/<file_sha256>/` (its own content address). Does not check that the Storage object exists or its bytes; that stays outside the database (`docs/rag/RAG_V1_INGESTION.md` §1). Not applied to hosted. Rollback: `supabase/rollbacks/20261007090000_*.down.sql` | 022, 023 |

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

## Hosted migration runbook

Process finding from the P1 DB lifecycle rollout (2026-09-26): follow-up migrations were applied to hosted under the approval given for the first one, and the commands were chained so a later step would still run after an earlier one failed. Nothing went wrong, and the applied history is not rewritten. The rules below apply from now on.

1. **Approval per batch.** Every apply to the hosted/production project needs the user's explicit approval for that batch of migrations. Approval of one migration does not cover follow-ups written later, unless the user approved the whole batch by name.
2. **Fail-fast.** Stop at the first failure. Nothing after a failed step may run.
   - Bash: chain with `&&`, or use `set -euo pipefail`.
   - PowerShell 5.1: `A; if ($?) { B }`, or `$ErrorActionPreference = 'Stop'` plus a check of `$LASTEXITCODE` after each native command.
   - Never use `;` (or a newline in a script without stop-on-error) between "apply migration", "run its test" and "apply the next migration".
3. **One migration, then its check.** Apply one migration, run its verification, and only if that passes move to the next one. A failing check leaves the later migrations unapplied.
4. **Before merging**, confirm the repository and hosted histories match. Read-only query: `select version, name, statements from supabase_migrations.schema_migrations order by version`. Compare the versions, names, order and SQL with `supabase/migrations/`. Do not merge if they differ.
5. **Never edit an applied migration.** A defect gets a new migration.
