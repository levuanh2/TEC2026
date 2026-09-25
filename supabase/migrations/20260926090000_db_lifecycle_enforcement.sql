-- P1: season lifecycle + active-membership authorization for EVERY write client.
--
-- Before this migration the lifecycle rule ("activities only in an `active`
-- season") lived in FastAPI alone. Flutter writes through PostgREST under RLS,
-- and a hosted probe (docs/evidence/lifecycle-rls-probe-before.txt) showed:
--   * an owner could insert/update activities, change detail rows and soft-
--     delete in `harvested`, `closed` and `planned` seasons;
--   * a former member whose farm role outlived their cooperative membership
--     could still insert activities and create seasons.
--
-- WHAT THIS CHANGES
--   1. `user_can_write_farm` / `user_can_manage_farm_members`: a farm role counts
--      only with an ACTIVE membership of the farm's cooperative, on a farm that
--      is not deleted. Every helper built on them (`user_can_write_crop`,
--      `user_can_write_batch`, `user_can_delete_activity`) inherits it.
--   2. `private.activity_batch_open` -- the lifecycle rule in ONE place: the
--      batch is live and not closed/cancelled, its season is live and `active`.
--      `private.user_can_write_activity_batch` = authorization AND lifecycle,
--      the canonical helper for activity mutation.
--   3. Activity + detail-table policies use it for new rows.
--   4. Triggers (client sessions only, i.e. when RLS is active -- backend
--      service paths, seeds and cleanup are unchanged) raise SQLSTATE 55000
--      `crop_season_not_open` for any mutation of an activity or detail row in
--      a season that is not open. A trigger, not only a policy USING clause:
--      a USING clause silently filters an UPDATE to 0 rows, and the Flutter
--      client's update does not ask for the row back, so it would report a
--      write that never happened as synced.
--   5. `soft_delete_activity` refuses a closed season the same way.
--   6. Season status transitions for clients follow one table
--      (`private.crop_season_transition_allowed`), which FastAPI's close
--      endpoint uses too: no reopening a harvested/closed/cancelled season, no
--      client-created season in a finished state.
--   7. `production_batch_id` of an activity is immutable to clients: an
--      activity cannot be moved between batches/seasons from outside the backend.
--
-- Data audit before writing this (hosted, 2026-09-26): 6 live seasons, all
-- `active`; no non-active season holds activities; 0 owner/editor roles without
-- an active membership. Nothing historical is rewritten.

-- --------------------------------------------------------------------------
-- 1. Active membership is mandatory for farm write authority
-- --------------------------------------------------------------------------
create or replace function private.user_can_write_farm(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.farm_members fm
    join public.farms f on f.id = fm.farm_id
    where fm.farm_id = p_farm
      and fm.user_id = (select auth.uid())
      and fm.farm_role in ('owner'::public.farm_role, 'editor'::public.farm_role)
      and f.deleted_at is null
      and exists (
        select 1 from public.organization_memberships om
        where om.organization_id = f.cooperative_id
          and om.user_id = fm.user_id
          and (om.ended_at is null or om.ended_at > now())
      )
  )
  or exists (
    select 1 from public.farms f
    where f.id = p_farm and f.deleted_at is null and private.user_is_org_manager(f.cooperative_id)
  );
$$;

create or replace function private.user_can_manage_farm_members(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.farm_members fm
    join public.farms f on f.id = fm.farm_id
    where fm.farm_id = p_farm
      and fm.user_id = (select auth.uid())
      and fm.farm_role = 'owner'::public.farm_role
      and f.deleted_at is null
      and exists (
        select 1 from public.organization_memberships om
        where om.organization_id = f.cooperative_id
          and om.user_id = fm.user_id
          and (om.ended_at is null or om.ended_at > now())
      )
  )
  or exists (
    select 1 from public.farms f
    where f.id = p_farm and f.deleted_at is null and private.user_is_org_manager(f.cooperative_id)
  );
$$;

-- --------------------------------------------------------------------------
-- 2. The lifecycle rule and the canonical activity-mutation helper
-- --------------------------------------------------------------------------
create or replace function private.activity_batch_open(p_batch uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.production_batches pb
    join public.crop_seasons cs on cs.id = pb.crop_season_id
    where pb.id = p_batch
      and pb.deleted_at is null
      and pb.status not in ('closed'::public.batch_status, 'cancelled'::public.batch_status)
      and cs.deleted_at is null
      and cs.status = 'active'::public.crop_status
  );
$$;

create or replace function private.user_can_write_activity_batch(p_batch uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select private.user_can_write_batch(p_batch) and private.activity_batch_open(p_batch);
$$;

-- Status changes a client (or FastAPI) may make. Same-status updates are not a
-- transition and are always allowed (an edit of other columns).
create or replace function private.crop_season_transition_allowed(
  p_from public.crop_status, p_to public.crop_status)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select p_from = p_to or (p_from, p_to) in (
    ('planned'::public.crop_status,   'active'::public.crop_status),
    ('planned'::public.crop_status,   'cancelled'::public.crop_status),
    ('active'::public.crop_status,    'harvested'::public.crop_status),
    ('active'::public.crop_status,    'closed'::public.crop_status),
    ('active'::public.crop_status,    'cancelled'::public.crop_status),
    ('harvested'::public.crop_status, 'closed'::public.crop_status)
  );
$$;

revoke all on function private.activity_batch_open(uuid) from public;
revoke all on function private.user_can_write_activity_batch(uuid) from public;
revoke all on function private.crop_season_transition_allowed(public.crop_status, public.crop_status) from public;
grant execute on function private.activity_batch_open(uuid) to authenticated, service_role;
grant execute on function private.user_can_write_activity_batch(uuid) to authenticated, service_role;
grant execute on function private.crop_season_transition_allowed(public.crop_status, public.crop_status) to authenticated, service_role;

-- --------------------------------------------------------------------------
-- 3. Policies: new/changed rows must be writable AND open
-- --------------------------------------------------------------------------
drop policy if exists activities_insert on public.activities;
create policy activities_insert on public.activities for insert to authenticated
  with check (
    private.user_can_write_activity_batch(production_batch_id)
    and (recorded_by is null or recorded_by = (select auth.uid()))
  );

drop policy if exists activities_update on public.activities;
create policy activities_update on public.activities for update to authenticated
  using (private.user_can_write_batch(production_batch_id))
  with check (
    private.user_can_write_activity_batch(production_batch_id)
    and (recorded_by is null or recorded_by = (select auth.uid()))
  );

do $$
declare t text;
begin
  foreach t in array array[
    'seeding_events','fertilizer_applications','irrigation_events','pesticide_applications',
    'fuel_usages','straw_management_events','harvest_events'
  ] loop
    execute format('drop policy if exists %I on public.%I', t || '_insert', t);
    execute format(
      'create policy %I on public.%I for insert to authenticated with check (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_activity_batch(a.production_batch_id)))',
      t || '_insert', t
    );
    execute format('drop policy if exists %I on public.%I', t || '_update', t);
    execute format(
      'create policy %I on public.%I for update to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_batch(a.production_batch_id))) with check (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_activity_batch(a.production_batch_id)))',
      t || '_update', t
    );
    -- Delete keeps the authorization USING; the lifecycle part is the trigger
    -- below, so a closed season answers with an error instead of 0 rows.
  end loop;
end $$;

-- --------------------------------------------------------------------------
-- 4. Loud lifecycle refusal for client sessions
-- --------------------------------------------------------------------------
create or replace function private.enforce_activity_season_open()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op in ('UPDATE', 'DELETE') and not private.activity_batch_open(old.production_batch_id) then
    raise exception 'crop_season_not_open: the crop season of this activity is not active'
      using errcode = '55000';
  end if;
  if tg_op in ('INSERT', 'UPDATE') then
    if not private.activity_batch_open(new.production_batch_id) then
      raise exception 'crop_season_not_open: the crop season of this activity is not active'
        using errcode = '55000';
    end if;
    if tg_op = 'UPDATE' and new.production_batch_id is distinct from old.production_batch_id then
      raise exception 'activities.production_batch_id is immutable' using errcode = '42501';
    end if;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

drop trigger if exists enforce_activity_season_open_trg on public.activities;
create trigger enforce_activity_season_open_trg
before insert or update on public.activities
for each row
when (pg_catalog.row_security_active('public.activities'))
execute function private.enforce_activity_season_open();

create or replace function private.enforce_activity_detail_season_open()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_batch uuid;
begin
  select a.production_batch_id into v_batch
  from public.activities a
  where a.id = case when tg_op = 'DELETE' then old.activity_id else new.activity_id end;
  if v_batch is not null and not private.activity_batch_open(v_batch) then
    raise exception 'crop_season_not_open: the crop season of this activity is not active'
      using errcode = '55000';
  end if;
  if tg_op = 'UPDATE' and new.activity_id is distinct from old.activity_id then
    raise exception '%.activity_id is immutable', tg_table_name using errcode = '42501';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

do $$
declare t text;
begin
  foreach t in array array[
    'seeding_events','fertilizer_applications','irrigation_events','pesticide_applications',
    'fuel_usages','straw_management_events','harvest_events'
  ] loop
    execute format('drop trigger if exists enforce_detail_season_open_trg on public.%I', t);
    execute format(
      'create trigger enforce_detail_season_open_trg before insert or update or delete on public.%I for each row when (pg_catalog.row_security_active(%L)) execute function private.enforce_activity_detail_season_open()',
      t, 'public.' || t
    );
  end loop;
end $$;

-- --------------------------------------------------------------------------
-- 5. Soft delete refuses a closed season
-- --------------------------------------------------------------------------
create or replace function public.soft_delete_activity(p_activity_id uuid)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare v_batch uuid;
begin
  if p_activity_id is null then
    raise exception 'p_activity_id is required' using errcode = '22004';
  end if;
  if not private.user_can_delete_activity(p_activity_id) then
    raise exception 'not allowed to delete activity %', p_activity_id
      using errcode = '42501';
  end if;
  select production_batch_id into v_batch from public.activities where id = p_activity_id;
  if not private.activity_batch_open(v_batch) then
    raise exception 'crop_season_not_open: the crop season of this activity is not active'
      using errcode = '55000';
  end if;
  update public.activities
     set deleted_at = now()
   where id = p_activity_id
     and deleted_at is null;
  return true;
end;
$$;
revoke all on function public.soft_delete_activity(uuid) from public;
grant execute on function public.soft_delete_activity(uuid) to authenticated;

-- --------------------------------------------------------------------------
-- 6. Season lifecycle for client sessions
-- --------------------------------------------------------------------------
create or replace function private.enforce_crop_season_lifecycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    -- A client starts or plans a season; it never creates a finished one.
    if new.status not in ('planned'::public.crop_status, 'active'::public.crop_status) then
      raise exception 'illegal_crop_season_transition: a new season must be planned or active'
        using errcode = '55000';
    end if;
    return new;
  end if;
  if old.deleted_at is not null then
    raise exception 'crop_season_not_open: this crop season was deleted' using errcode = '55000';
  end if;
  if not private.crop_season_transition_allowed(old.status, new.status) then
    raise exception 'illegal_crop_season_transition: % -> % is not allowed', old.status, new.status
      using errcode = '55000';
  end if;
  return new;
end;
$$;

drop trigger if exists enforce_crop_season_lifecycle_trg on public.crop_seasons;
create trigger enforce_crop_season_lifecycle_trg
before insert or update on public.crop_seasons
for each row
when (pg_catalog.row_security_active('public.crop_seasons'))
execute function private.enforce_crop_season_lifecycle();
