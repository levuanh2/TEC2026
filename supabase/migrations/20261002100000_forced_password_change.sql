-- Core V1 closure: a provisioned account must replace its temporary password
-- before it can read or write any business data.
--
-- The flag is Supabase Auth `app_metadata.must_change_password`. Provisioning
-- (FastAPI, service role) sets it to true; only FastAPI clears it, in the same
-- Auth Admin call that sets the new password after verifying the current one
-- (`POST /v1/me/password`). `app_metadata` cannot be written by the user
-- (`PUT /auth/v1/user` ignores it), so no client can clear the flag.
--
-- Enforcement lives HERE, on the live auth.users row (not on a token claim, which
-- could be up to an hour stale): every root authorization helper answers false
-- while the caller's flag is set. That covers Flutter (PostgREST under RLS),
-- FastAPI reads with the caller's JWT, and FastAPI pooled reads/writes that set
-- request.jwt.claims -- all of them reach these helpers. FastAPI additionally
-- answers 403 `password_change_required` before doing any work.
--
-- Still allowed while the flag is set: the caller's own profile and own
-- membership rows (`/v1/me` reports the flag), own devices / sync batches, and
-- public reference data (published factor sets, recommendation rules, MRV step
-- catalog). Accounts without the flag -- every existing user -- are unaffected.
--
-- Rollback: supabase/rollbacks/20261002100000_forced_password_change.down.sql

create or replace function private.password_change_pending()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce((
    select (u.raw_app_meta_data ->> 'must_change_password') = 'true'
    from auth.users u
    where u.id = (select auth.uid())
  ), false);
$$;
revoke all on function private.password_change_pending() from public;

-- Reads of a farm and everything under it (20261002090000 + the flag).
create or replace function private.user_can_read_farm(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select not private.password_change_pending() and (
    exists (
      select 1
      from public.farm_members fm
      join public.farms f on f.id = fm.farm_id
      where fm.farm_id = p_farm
        and fm.user_id = (select auth.uid())
        and (
          fm.farm_role = 'owner'::public.farm_role
          or exists (
            select 1 from public.organization_memberships om
            where om.organization_id = f.cooperative_id
              and om.user_id = fm.user_id
              and (om.ended_at is null or om.ended_at > now())
          )
        )
    )
    or exists (
      select 1 from public.farms f
      where f.id = p_farm
        and (
          private.user_is_org_manager(f.cooperative_id)
          or exists (
            select 1
            from public.organization_data_grants g
            join public.organization_memberships om
              on om.organization_id = g.grantee_organization_id
            where g.source_organization_id = f.cooperative_id
              and om.user_id = (select auth.uid())
              and om.role in ('enterprise_viewer'::public.organization_role, 'regulator'::public.organization_role)
              and (om.ended_at is null or om.ended_at > now())
              and g.valid_from <= current_date
              and (g.valid_to is null or g.valid_to >= current_date)
          )
        )
    )
  );
$$;

-- Writes of a farm and everything under it (20260926090000 + the flag).
create or replace function private.user_can_write_farm(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select not private.password_change_pending() and (
    exists (
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
    )
  );
$$;

create or replace function private.user_can_manage_farm_members(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select not private.password_change_pending() and (
    exists (
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
    )
  );
$$;

create or replace function private.user_is_org_manager(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select not private.password_change_pending() and exists (
    select 1 from public.organization_memberships om
    where om.organization_id = p_org
      and om.user_id = (select auth.uid())
      and om.role = 'cooperative_manager'::public.organization_role
      and (om.ended_at is null or om.ended_at > now())
  );
$$;

create or replace function private.user_is_org_member(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select not private.password_change_pending() and exists (
    select 1 from public.organization_memberships om
    where om.organization_id = p_org
      and om.user_id = (select auth.uid())
      and (om.ended_at is null or om.ended_at > now())
  );
$$;

create or replace function private.user_can_read_organization(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select not private.password_change_pending() and (
    private.user_is_org_member(p_org)
    or exists (
      select 1
      from public.organization_data_grants g
      join public.organization_memberships om
        on om.organization_id = g.grantee_organization_id
      where g.source_organization_id = p_org
        and om.user_id = (select auth.uid())
        and om.role in ('enterprise_viewer'::public.organization_role, 'regulator'::public.organization_role)
        and (om.ended_at is null or om.ended_at > now())
        and g.valid_from <= current_date
        and (g.valid_to is null or g.valid_to >= current_date)
    )
  );
$$;

-- Own profile stays readable (`/v1/me` shows the name on the change screen);
-- other members' profiles follow the flag.
create or replace function private.user_can_read_profile(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_user = (select auth.uid())
  or (not private.password_change_pending() and exists (
    select 1
    from public.organization_memberships mine
    join public.organization_memberships theirs
      on theirs.organization_id = mine.organization_id
    where mine.user_id = (select auth.uid())
      and theirs.user_id = p_user
      and (mine.ended_at is null or mine.ended_at > now())
      and (theirs.ended_at is null or theirs.ended_at > now())
  ));
$$;
