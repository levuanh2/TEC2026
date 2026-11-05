-- Rollback of 20261104090000_set_based_activity_read_policies.sql: the per-row
-- SELECT policies exactly as defined in 20260907000000_baseline.sql, then the
-- set function. Access is the same either way; only the plan changes.

drop policy if exists activities_select on public.activities;
create policy activities_select on public.activities for select to authenticated
  using (deleted_at is null and private.user_can_read_batch(production_batch_id));

do $$
declare t text;
begin
  foreach t in array array[
    'seeding_events','fertilizer_applications','irrigation_events','pesticide_applications',
    'fuel_usages','straw_management_events','harvest_events'
  ] loop
    execute format('drop policy if exists %I on public.%I', t || '_select', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_read_batch(a.production_batch_id)))',
      t || '_select', t
    );
  end loop;
end;
$$;

drop function if exists private.readable_batch_ids();
