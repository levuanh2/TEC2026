-- Core V1 closure: a farm editor/viewer whose cooperative membership has ended
-- no longer reads that farm.
--
-- `private.user_can_read_farm` granted read on ANY `farm_members` row, with no
-- look at the cooperative membership. 20260926090000 made the WRITE helpers
-- require an active membership in the farm's cooperative but left reads
-- unchanged, so a removed editor/viewer kept reading another farmer's farm --
-- plots, seasons, batches, activities and detail rows, Carbon results,
-- recommendations, plant images (DB and Storage), CV results and the farm's
-- member list all chain through this helper.
--
-- Rule now (first branch only):
--   farm_members row for the caller AND
--     ( farm_role = 'owner'
--       OR an active membership (ended_at is null or > now()) in the farm's
--          cooperative )
-- The manager / data-grant branch is unchanged (it already required an active
-- membership).
--
-- Deliberately UNCHANGED, pending a product decision: a farm OWNER whose
-- cooperative membership ended still reads their own farm's history. Whether a
-- farmer removed from the HTX keeps read access to their own records is not
-- settled by any contract; see docs/CORE_V1_CLOSURE.md. Writes stay refused
-- for them (user_can_write_farm, 20260926090000).
--
-- Reads only; no data is touched. Rollback:
-- supabase/rollbacks/20261002090000_former_member_farm_reads.down.sql

create or replace function private.user_can_read_farm(p_farm uuid)
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
$$;
