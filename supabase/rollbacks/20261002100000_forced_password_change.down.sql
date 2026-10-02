-- Rollback for migrations/20261002100000_forced_password_change.sql.
-- Restores the seven authorization helpers exactly as they were after
-- 20261002090000 (captured with pg_get_functiondef before the forward
-- migration was applied) and drops private.password_change_pending().
-- Touches no data; app_metadata.must_change_password stays on the Auth users
-- but no longer restricts anything. Not in migrations/: run by hand, in one
-- transaction, only if the forward migration must be withdrawn. Afterwards
-- `supabase migration repair --status reverted 20261002100000`.
begin;
CREATE OR REPLACE FUNCTION private.user_can_read_farm(p_farm uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select exists (
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
  );
$function$;
CREATE OR REPLACE FUNCTION private.user_can_write_farm(p_farm uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
$function$;
CREATE OR REPLACE FUNCTION private.user_can_manage_farm_members(p_farm uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
$function$;
CREATE OR REPLACE FUNCTION private.user_is_org_manager(p_org uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select exists (
    select 1 from public.organization_memberships om
    where om.organization_id = p_org
      and om.user_id = (select auth.uid())
      and om.role = 'cooperative_manager'::public.organization_role
      and (om.ended_at is null or om.ended_at > now())
  );
$function$;
CREATE OR REPLACE FUNCTION private.user_is_org_member(p_org uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select exists (
    select 1 from public.organization_memberships om
    where om.organization_id = p_org
      and om.user_id = (select auth.uid())
      and (om.ended_at is null or om.ended_at > now())
  );
$function$;
CREATE OR REPLACE FUNCTION private.user_can_read_organization(p_org uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select
    private.user_is_org_member(p_org)
    or exists (
      select 1
      from public.organization_data_grants g
      join public.organization_memberships om
        on om.organization_id = g.grantee_organization_id
      where g.source_organization_id = p_org
        and om.user_id = (select auth.uid())
        and om.role in ('enterprise_viewer'::public.organization_role,'regulator'::public.organization_role)
        and (om.ended_at is null or om.ended_at > now())
        and g.valid_from <= current_date
        and (g.valid_to is null or g.valid_to >= current_date)
    );
$function$;
CREATE OR REPLACE FUNCTION private.user_can_read_profile(p_user uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select p_user = (select auth.uid())
  or exists (
    select 1
    from public.organization_memberships mine
    join public.organization_memberships theirs
      on theirs.organization_id = mine.organization_id
    where mine.user_id = (select auth.uid())
      and theirs.user_id = p_user
      and (mine.ended_at is null or mine.ended_at > now())
      and (theirs.ended_at is null or theirs.ended_at > now())
  );
$function$;
drop function if exists private.password_change_pending();
commit;
