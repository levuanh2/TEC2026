-- Rollback of 20261105090000_set_based_batch_carbon_read_policies.sql: the
-- per-row SELECT policies exactly as defined in 20260907000000_baseline.sql
-- (production_batches_select, carbon_calculations_select) and
-- 20260908000002_crop_season_carbon_scope.sql
-- (carbon_calculations_select_crop_season), then the set function. Access is
-- the same either way; only the plan changes.

drop policy if exists production_batches_select on public.production_batches;
create policy production_batches_select on public.production_batches for select to authenticated
  using (deleted_at is null and private.user_can_read_crop(crop_season_id));

drop policy if exists carbon_calculations_select on public.carbon_calculations;
create policy carbon_calculations_select on public.carbon_calculations for select to authenticated
  using (private.user_can_read_batch(production_batch_id));

drop policy if exists carbon_calculations_select_crop_season on public.carbon_calculations;
create policy carbon_calculations_select_crop_season on public.carbon_calculations for select to authenticated
  using (private.user_can_read_crop(crop_season_id));

drop function if exists private.readable_crop_ids();
