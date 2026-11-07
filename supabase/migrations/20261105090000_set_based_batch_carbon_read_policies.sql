-- Set-based SELECT policies for production_batches and carbon_calculations.
--
-- WHY. These are the two RLS reads the API still sends with a per-row policy
-- (backend/infrastructure/read_repo.py through PostgREST with the user's JWT):
-- the Manager organisation/farm rollups read
--   production_batches  where crop_season_id in (<org seasons>)   -- then activities
--   carbon_calculations where crop_season_id in (<org seasons>)
-- and the season hub reads both for one season. production_batches_select calls
-- private.user_can_read_crop(crop_season_id) per row; carbon_calculations has
-- two permissive policies, user_can_read_batch(production_batch_id) OR
-- user_can_read_crop(crop_season_id), each per row. SECURITY DEFINER helpers are
-- never inlined, so every row walks season -> plot -> farm ->
-- user_can_read_farm. Measured on hosted 2026-11-05 (EXPLAIN ANALYZE as the
-- HTX-DEMO-001 manager, 27 seasons, read-only, rolled back): 235 ms for 27
-- batches and 227 ms for 25 calculations of server time; the same reads with
-- the predicates below took 12.6 ms and 25.6 ms. The batch read sits on the
-- rollup's sequential chain (batches -> activities), so it adds directly to
-- the Dashboard's response time. (A farmer filtered by own seasons is ~10 ms
-- either way: few rows.)
--
-- WHAT. private.readable_crop_ids() returns the crop seasons the caller may
-- read: the set form of user_can_read_crop, as readable_batch_ids() (migration
-- 20261104090000) is for user_can_read_batch. The policies test membership in
-- those sets; an uncorrelated `IN (select ...)` is a hashed subplan evaluated
-- once per statement, so user_can_read_farm runs once per FARM.
--
-- SAME ACCESS. user_can_read_crop(c) is
--   exists(crop season c -> its plot -> user_can_read_farm(plot.farm_id)).
-- readable_crop_ids() selects exactly those seasons: the same inner join, the
-- same NOT NULL foreign keys (crop_seasons.plot_id, plots.farm_id -> farms.id),
-- no added or removed deleted_at filter, user_can_read_farm on the same farm id.
-- production_batches keeps its `deleted_at is null`. A calculation without a
-- batch (season-scoped) stays readable through the crop-season policy only, as
-- before: `null in (...)` is never true, like user_can_read_batch(null).
-- Checked on hosted before writing this file: for 14 identities (every active
-- member plus an outsider) the ids visible through the live policies equal the
-- ids selected by these predicates, on both tables (0 mismatches).
-- backend/tests/test_set_based_batch_carbon_reads.py pins it per role.
--
-- ROLLBACK ORDER. carbon_calculations_select depends on readable_batch_ids()
-- from 20261104090000, so roll this migration back BEFORE that one (its
-- down.sql drops the function and fails while this policy exists).
--
-- NOT CHANGED. Insert/update policies, carbon_breakdowns (the API reads it only
-- through the owner connection, pg_carbon_repo, so no user waits on its RLS),
-- every private.user_can_* helper, readable_batch_ids(), grants, and every
-- other table's policies.

create or replace function private.readable_crop_ids()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
  select cs.id
  from public.crop_seasons cs
  join public.plots p on p.id = cs.plot_id
  where p.farm_id in (select f.id from public.farms f where private.user_can_read_farm(f.id));
$$;

comment on function private.readable_crop_ids() is
  'Every crop season the caller may read: the set form of private.user_can_read_crop (same chain, evaluated once per statement).';

revoke all on function private.readable_crop_ids() from public, anon;
grant execute on function private.readable_crop_ids() to authenticated;

drop policy if exists production_batches_select on public.production_batches;
create policy production_batches_select on public.production_batches for select to authenticated
  using (deleted_at is null and crop_season_id in (select private.readable_crop_ids()));

drop policy if exists carbon_calculations_select on public.carbon_calculations;
create policy carbon_calculations_select on public.carbon_calculations for select to authenticated
  using (production_batch_id in (select private.readable_batch_ids()));

drop policy if exists carbon_calculations_select_crop_season on public.carbon_calculations;
create policy carbon_calculations_select_crop_season on public.carbon_calculations for select to authenticated
  using (crop_season_id in (select private.readable_crop_ids()));
