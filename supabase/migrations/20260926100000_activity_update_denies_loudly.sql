-- Follow-up to 20260926090000: a non-writer's UPDATE is refused with an error
-- instead of silently matching 0 rows.
--
-- With `USING (user_can_write_batch(...))` a farm viewer, a former member or an
-- out-of-scope user updating an activity they can read got "success, 0 rows"
-- (hosted probe, docs/evidence/lifecycle-rls-probe-after.txt). Nothing changed,
-- but a client that does not ask for the row back -- the Flutter app's
-- `updateActivityById` -- cannot tell a refusal from a write.
--
-- Now USING is the READ scope (the rows the caller can already see) and the
-- write rule is the WITH CHECK, which raises 42501. This grants nothing new:
--   * WITH CHECK still requires `user_can_write_activity_batch` on the row's
--     batch AND the recorder rule;
--   * a client cannot move an activity to another batch
--     (`enforce_activity_season_open_trg`, 42501) or a detail row to another
--     activity (`enforce_detail_season_open_trg`, 42501), so the batch checked
--     by WITH CHECK is the row's own batch;
--   * the lifecycle trigger still raises 55000 for a season that is not open.
-- Detail-table DELETE keeps its write-scope USING (a DELETE has no WITH CHECK,
-- so a read-scope USING would let readers delete); no client deletes detail
-- rows directly -- the app soft-deletes the parent through the RPC.

drop policy if exists activities_update on public.activities;
create policy activities_update on public.activities for update to authenticated
  using (private.user_can_read_batch(production_batch_id))
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
    execute format('drop policy if exists %I on public.%I', t || '_update', t);
    execute format(
      'create policy %I on public.%I for update to authenticated using (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_read_batch(a.production_batch_id))) with check (exists (select 1 from public.activities a where a.id = activity_id and private.user_can_write_activity_batch(a.production_batch_id)))',
      t || '_update', t
    );
  end loop;
end $$;
