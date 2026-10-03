-- Round 5.1: a harvest may not claim more hectares than its plot has.
--
-- Farmer Web and FastAPI already refuse `harvested_area_ha > plots.area_ha`
-- (422 `harvested_area_exceeds_plot`). Flutter writes harvest_events straight
-- to PostgREST from its offline queue, so the rule has to live in the
-- database to hold on every write path.
--
-- The rule spans three tables (harvest_events -> activities -> batches ->
-- crop_seasons -> plots), so it cannot be a CHECK constraint. It is enforced
-- from each side that can break it:
--   1. harvest_events  insert, or update of harvested_area_ha / activity_id
--   2. plots           update of area_ha (shrinking below a recorded harvest)
--   3. crop_seasons    update of plot_id (moving a season to a smaller plot)
-- Equal is allowed. NULL harvested area or NULL plot area applies no bound —
-- nothing is guessed. Negative/zero areas are already refused by
-- `harvest_area_chk` / the plots area check.
--
-- Unlike the lifecycle triggers these fire for EVERY writer (client sessions,
-- the FastAPI backend role, seed scripts): the invariant is about the data,
-- not about who writes it.
--
-- Error contract: SQLSTATE 23514 (check_violation) and a message starting
-- `harvested_area_exceeds_plot:` — Flutter maps it to a fix-the-record state
-- (never retried as-is), FastAPI to its existing 422.
--
-- Preflight: the migration refuses to apply if existing rows already violate
-- the rule. It never edits or deletes data. Rollback:
-- supabase/rollbacks/20260929120000_harvest_area_within_plot.down.sql

do $$
declare
  v_count bigint;
begin
  select count(*) into v_count
  from public.harvest_events h
  join public.activities a on a.id = h.activity_id
  join public.production_batches b on b.id = a.production_batch_id
  join public.crop_seasons cs on cs.id = b.crop_season_id
  join public.plots p on p.id = cs.plot_id
  where h.harvested_area_ha is not null
    and p.area_ha is not null
    and h.harvested_area_ha > p.area_ha
    and a.deleted_at is null and b.deleted_at is null and cs.deleted_at is null;
  if v_count > 0 then
    raise exception 'preflight: % live harvest record(s) already exceed their plot area; fix them before applying this migration', v_count;
  end if;
end;
$$;

-- Largest live harvested area recorded in a season, or NULL.
create or replace function private.max_live_harvested_area(p_crop_season uuid)
returns numeric
language sql
stable
security definer
set search_path = ''
as $$
  select max(h.harvested_area_ha)
  from public.harvest_events h
  join public.activities a on a.id = h.activity_id
  join public.production_batches b on b.id = a.production_batch_id
  where b.crop_season_id = p_crop_season
    and a.deleted_at is null and b.deleted_at is null;
$$;
revoke all on function private.max_live_harvested_area(uuid) from public;

create or replace function private.raise_harvest_area_exceeds_plot(p_harvested numeric, p_plot numeric)
returns void
language plpgsql
immutable
set search_path = ''
as $$
begin
  raise exception 'harvested_area_exceeds_plot: harvested area % ha is larger than the plot area % ha',
    p_harvested, p_plot
    using errcode = '23514',
          detail = pg_catalog.json_build_object('harvested_area_ha', p_harvested, 'plot_area_ha', p_plot)::text,
          hint = 'Diện tích thu hoạch không được lớn hơn diện tích thửa.';
end;
$$;
revoke all on function private.raise_harvest_area_exceeds_plot(numeric, numeric) from public;

-- 1. The harvest side. SECURITY DEFINER so the bound never depends on what
--    the writer's RLS lets it read (a plot hidden from the writer must not
--    mean "no bound").
create or replace function private.enforce_harvest_area_within_plot()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_plot_area numeric;
begin
  if new.harvested_area_ha is null then
    return new;
  end if;
  select p.area_ha into v_plot_area
  from public.activities a
  join public.production_batches b on b.id = a.production_batch_id
  join public.crop_seasons cs on cs.id = b.crop_season_id
  join public.plots p on p.id = cs.plot_id
  where a.id = new.activity_id;
  if v_plot_area is not null and new.harvested_area_ha > v_plot_area then
    perform private.raise_harvest_area_exceeds_plot(new.harvested_area_ha, v_plot_area);
  end if;
  return new;
end;
$$;
revoke all on function private.enforce_harvest_area_within_plot() from public;

drop trigger if exists enforce_harvest_area_within_plot_trg on public.harvest_events;
create trigger enforce_harvest_area_within_plot_trg
before insert or update of harvested_area_ha, activity_id on public.harvest_events
for each row
execute function private.enforce_harvest_area_within_plot();

-- 2. The plot side: shrinking a plot below a recorded harvest.
create or replace function private.enforce_plot_area_covers_harvests()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_max numeric;
begin
  if new.area_ha is null or new.area_ha >= coalesce(old.area_ha, new.area_ha) then
    return new;  -- growing (or unchanged) can never break the rule
  end if;
  select max(private.max_live_harvested_area(cs.id)) into v_max
  from public.crop_seasons cs
  where cs.plot_id = new.id and cs.deleted_at is null;
  if v_max is not null and v_max > new.area_ha then
    perform private.raise_harvest_area_exceeds_plot(v_max, new.area_ha);
  end if;
  return new;
end;
$$;
revoke all on function private.enforce_plot_area_covers_harvests() from public;

drop trigger if exists enforce_plot_area_covers_harvests_trg on public.plots;
create trigger enforce_plot_area_covers_harvests_trg
before update of area_ha on public.plots
for each row
execute function private.enforce_plot_area_covers_harvests();

-- 3. The season side: moving a season onto a smaller plot.
create or replace function private.enforce_season_plot_covers_harvests()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_max numeric;
  v_plot_area numeric;
begin
  if new.plot_id is not distinct from old.plot_id then
    return new;
  end if;
  select p.area_ha into v_plot_area from public.plots p where p.id = new.plot_id;
  v_max := private.max_live_harvested_area(new.id);
  if v_plot_area is not null and v_max is not null and v_max > v_plot_area then
    perform private.raise_harvest_area_exceeds_plot(v_max, v_plot_area);
  end if;
  return new;
end;
$$;
revoke all on function private.enforce_season_plot_covers_harvests() from public;

drop trigger if exists enforce_season_plot_covers_harvests_trg on public.crop_seasons;
create trigger enforce_season_plot_covers_harvests_trg
before update of plot_id on public.crop_seasons
for each row
execute function private.enforce_season_plot_covers_harvests();
