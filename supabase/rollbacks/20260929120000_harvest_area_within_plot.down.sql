-- Rollback for migrations/20260929120000_harvest_area_within_plot.sql.
-- Removes the three triggers and their functions; touches no data.
-- Not in migrations/: run by hand, in one transaction, only if the forward
-- migration must be withdrawn. Afterwards record the withdrawal with
-- `supabase migration repair --status reverted 20260929120000`.
begin;
drop trigger if exists enforce_harvest_area_within_plot_trg on public.harvest_events;
drop trigger if exists enforce_plot_area_covers_harvests_trg on public.plots;
drop trigger if exists enforce_season_plot_covers_harvests_trg on public.crop_seasons;
drop function if exists private.enforce_harvest_area_within_plot();
drop function if exists private.enforce_plot_area_covers_harvests();
drop function if exists private.enforce_season_plot_covers_harvests();
drop function if exists private.raise_harvest_area_exceeds_plot(numeric, numeric);
drop function if exists private.max_live_harvested_area(uuid);
commit;
