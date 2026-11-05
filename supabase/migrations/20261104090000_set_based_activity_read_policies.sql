-- Set-based SELECT policies for activities and their seven detail tables.
--
-- WHY. `activities_select` called private.user_can_read_batch(production_batch_id)
-- for every row, and each call walks batch -> season -> plot -> farm ->
-- private.user_can_read_farm (password_change_pending, memberships, manager,
-- data grants). SECURITY DEFINER functions are never inlined, so Postgres runs
-- that chain once per row of the scanned table. Measured on hosted
-- (2026-11-04, EXPLAIN ANALYZE as the HTX-DEMO-001 manager, read-only and
-- rolled back): reading the 258 visible activities took 2.3 s and their
-- fertilizer rows 3.7 s, all CPU on buffer hits (58k / 95k); for every one of
-- the 13 users with a membership the plain `select id from activities` took
-- 3.7-7.3 s, even for a user who sees 0 rows. Concurrent Dashboard rollups then
-- hit `statement_timeout = 8s` for `authenticated` and the API answered 500.
--
-- WHAT. One security-definer set function, private.readable_batch_ids(),
-- returns the batches the caller may read; the policies test membership in
-- that set. An uncorrelated `IN (select ...)` is evaluated once per statement
-- as a hashed subplan, so user_can_read_farm runs once per FARM instead of
-- once per activity row (measured: ~150 ms for every one of the 13 users).
--
-- SAME ACCESS. user_can_read_batch(b) is
--   exists(batch b -> its crop season -> its plot -> user_can_read_farm(plot.farm_id)).
-- readable_batch_ids() selects exactly those batches: the same inner joins,
-- the same NOT NULL foreign keys (production_batches.crop_season_id,
-- crop_seasons.plot_id, plots.farm_id), no added or removed `deleted_at`
-- filter, and user_can_read_farm applied to the same farm id (taken from
-- public.farms, which every plots.farm_id references). Checked on hosted before
-- writing this file: for each of the 13 users with a membership, the activity
-- ids visible through the current policy equal the ids selected by the new
-- predicate, and the same for all seven detail tables (detail rows of a
-- soft-deleted activity stay hidden: the detail policies' subquery on
-- public.activities is itself subject to activities_select, as before).
-- backend/tests/test_set_based_activity_reads.py pins the equivalence per role.
--
-- NOT CHANGED. Insert/update policies (single-row checks, not the hot path),
-- every private.user_can_* helper (still used by other policies, FastAPI and
-- the tests), grants, and every other table's policies.

create or replace function private.readable_batch_ids()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
  select pb.id
  from public.production_batches pb
  join public.crop_seasons cs on cs.id = pb.crop_season_id
  join public.plots p on p.id = cs.plot_id
  where p.farm_id in (select f.id from public.farms f where private.user_can_read_farm(f.id));
$$;

comment on function private.readable_batch_ids() is
  'Every production batch the caller may read: the set form of private.user_can_read_batch (same chain, evaluated once per statement).';

revoke all on function private.readable_batch_ids() from public, anon;
grant execute on function private.readable_batch_ids() to authenticated;

drop policy if exists activities_select on public.activities;
create policy activities_select on public.activities for select to authenticated
  using (deleted_at is null and production_batch_id in (select private.readable_batch_ids()));

do $$
declare t text;
begin
  foreach t in array array[
    'seeding_events','fertilizer_applications','irrigation_events','pesticide_applications',
    'fuel_usages','straw_management_events','harvest_events'
  ] loop
    execute format('drop policy if exists %I on public.%I', t || '_select', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and a.production_batch_id in (select private.readable_batch_ids())))',
      t || '_select', t
    );
  end loop;
end;
$$;
