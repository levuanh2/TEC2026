-- M05 recommendation engine: a new, deliberately separate table from the
-- baseline migration's public.recommendations / resource_metric_snapshots /
-- benchmark_snapshots architecture (2026-09-07). That schema is unused by any
-- application code (zero rows, zero Python references) and hard-requires a
-- FINALIZED cross-farm benchmark plus a successful carbon_calculations row
-- before any row can exist (resource_metric_snapshots.carbon_calculation_id
-- is NOT NULL) — no legitimate cross-farm benchmark data source exists yet,
-- and REAL CO2e is currently blocked by unverified emission factors, so that
-- shape would make this feature permanently empty even for the honest
-- data-completeness rule, which has nothing to do with carbon or benchmarks.
-- Left untouched rather than altered, to avoid a destructive change to an
-- already-tracked (if dormant) schema object.
--
-- This table's evidence comes directly from re-invoking the existing Carbon
-- Engine with an alternate scenario (baseline vs proposed) — never a
-- separately written formula — or, for data_task rows, from the existing
-- resource-metrics completeness flags. `public.recommendation_status`
-- (generated|accepted|dismissed|expired) already exists in the baseline
-- migration and is reused as-is.

create table if not exists public.season_recommendations (
  id uuid primary key default gen_random_uuid(),
  crop_season_id uuid not null references public.crop_seasons(id) on delete cascade,
  rule_code text not null,
  rule_version text not null,
  engine_version text,
  type text not null check (type in ('optimization', 'data_task')),
  status public.recommendation_status not null default 'generated',
  title text not null,
  reason text not null,
  compared_to text,
  -- Carbon impact, present only for type='optimization' rows whose evidence
  -- is a Carbon Engine before/after pair. Null (not 0) when unavailable.
  co2e_total_kg_before numeric(20, 6),
  co2e_total_kg_after numeric(20, 6),
  co2e_total_kg_delta numeric(20, 6),
  co2e_percent_delta numeric(12, 6),
  impact_status text not null check (impact_status in ('available', 'unavailable')),
  impact_unavailable_reason text,
  -- Rule-specific evidence snapshot (e.g. the Carbon Engine input_hash and
  -- water_regime_applied for both scenarios, or the missing-field list for a
  -- data_task) — heterogeneous by rule, kept as JSON for audit/reproducibility
  -- only; never used to derive the normalized columns above.
  evidence jsonb not null default '{}'::jsonb,
  input_hash text not null,
  generated_at timestamptz not null default now(),
  accepted_at timestamptz,
  dismissed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint season_recommendations_title_chk check (btrim(title) <> ''),
  constraint season_recommendations_reason_chk check (btrim(reason) <> ''),
  constraint season_recommendations_status_dates_chk check (
    (status <> 'accepted' or accepted_at is not null)
    and (status <> 'dismissed' or dismissed_at is not null)
  ),
  constraint season_recommendations_optimization_impact_chk check (
    type <> 'optimization' or impact_status is not null
  ),
  -- One live row per rule per season; regenerating with fresh inputs updates
  -- it in place (service layer preserves an already-accepted/dismissed
  -- decision rather than silently resetting it — brief FW M05 §B11/§B12).
  unique (crop_season_id, rule_code)
);

create index if not exists season_recommendations_season_idx
  on public.season_recommendations (crop_season_id)
  where status = 'generated';

alter table public.season_recommendations enable row level security;

-- Reads go through the caller's own RLS-scoped client (SupabaseReadRepository),
-- same as every other domain table — farmer/manager/enterprise/regulator scope
-- is whatever private.user_can_read_crop() already grants for this crop season,
-- no new role logic introduced here.
grant select on public.season_recommendations to authenticated;
create policy season_recommendations_select on public.season_recommendations
  for select to authenticated
  using (private.user_can_read_crop(crop_season_id));

-- Generation and accept/dismiss are backend-trusted writes (service-role
-- connection, same pattern as public.activities' web write path in
-- infrastructure/write_repo.py) — no insert/update policy for `authenticated`
-- is needed or granted; RLS defaults to deny for that role on writes.
