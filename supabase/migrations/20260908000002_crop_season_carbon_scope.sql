-- ============================================================================
-- AgriCarbon — lock carbon calculation scope to crop season
-- Date: 2026-09-08
-- Follows: 20260908000000_carbon_methodology_alignment.sql,
--          20260908000001_carbon_calculation_scope_audit.sql
--
-- DATA-PRESERVING MIGRATION.  It neither resets nor deletes data.  The only
-- narrowing change is making the already-added crop_season_id mandatory after
-- deterministic backfill from each existing calculation's batch.
-- ============================================================================

begin;

-- Existing rows predate crop_season_id.  A batch has exactly one crop season,
-- so this backfill does not allocate or infer any emissions.
update public.carbon_calculations c
set crop_season_id = pb.crop_season_id
from public.production_batches pb
where c.production_batch_id = pb.id
  and c.crop_season_id is null;

-- Fail closed rather than make a calculation with an unknown cultivation scope.
do $$
begin
  if exists (
    select 1 from public.carbon_calculations where crop_season_id is null
  ) then
    raise exception
      'Cannot lock carbon calculation scope: existing rows without a traceable crop_season_id require manual remediation';
  end if;
end $$;

alter table public.carbon_calculations
  alter column crop_season_id set not null,
  alter column production_batch_id drop not null;

-- The old batch-based unique constraint is retained for compatibility. Existing
-- historical rows may already contain batch-level duplicates, so do not delete
-- or rewrite them in this migration. This partial season key governs new
-- whole-season rows (which always have a NULL batch link).
create unique index if not exists carbon_calculations_season_input_uniq
  on public.carbon_calculations (crop_season_id, scenario, factor_set_id, input_hash)
  where production_batch_id is null;

-- A batch link is optional traceability only.  If supplied, it must belong to
-- the same season; it never changes the calculation's cultivation scope.
create or replace function private.assert_calculation_batch_matches_season()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if new.production_batch_id is not null and not exists (
    select 1
    from public.production_batches pb
    where pb.id = new.production_batch_id
      and pb.crop_season_id = new.crop_season_id
  ) then
    raise exception 'production_batch_id must belong to carbon_calculations.crop_season_id';
  end if;
  return new;
end;
$$;

create trigger carbon_calculations_batch_scope_guard
before insert or update of production_batch_id, crop_season_id
on public.carbon_calculations
for each row execute function private.assert_calculation_batch_matches_season();

-- Keep the authorization boundary at the same Farm -> Plot -> Crop Season
-- hierarchy.  These additive policies preserve read access for old rows and
-- make a scope-level calculation visible when its optional batch FK is NULL.
create policy carbon_calculations_select_crop_season
on public.carbon_calculations for select to authenticated
using (private.user_can_read_crop(crop_season_id));

create policy carbon_breakdowns_select_crop_season
on public.carbon_breakdowns for select to authenticated
using (exists (
  select 1 from public.carbon_calculations c
  where c.id = calculation_id
    and private.user_can_read_crop(c.crop_season_id)
));

comment on table public.carbon_calculations is
  'One calculation is scoped to one crop season. CH4/N2O/fuel/straw cultivation totals are never copied per harvest batch.';
comment on column public.carbon_calculations.crop_season_id is
  'Required natural scope of cultivation emissions. area_ha and cultivation_days resolve through this crop season and its plot.';
comment on column public.carbon_calculations.production_batch_id is
  'Optional traceability reference only; null for a whole-season calculation. It MUST NOT define cultivation-emission scope or per-kg yield.';

commit;
