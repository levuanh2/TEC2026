-- Rollback for migrations/20261002090000_former_member_farm_reads.sql.
-- Restores the previous private.user_can_read_farm (any farm_members row
-- reads, whatever the cooperative membership); touches no data.
-- Not in migrations/: run by hand, in one transaction, only if the forward
-- migration must be withdrawn. Afterwards record the withdrawal with
-- `supabase migration repair --status reverted 20261002090000`.
begin;
create or replace function private.user_can_read_farm(p_farm uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.farm_members fm
    where fm.farm_id = p_farm and fm.user_id = (select auth.uid())
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
commit;
