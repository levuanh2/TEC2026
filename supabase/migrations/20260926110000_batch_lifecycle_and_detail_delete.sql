-- Follow-up to 20260926090000 / 20260926100000, from the independent review.
--
-- 1. production_batches follow the season lifecycle for client sessions.
--    The Flutter sync upserts the season's `default` batch right before an
--    activity. For a season that ended meanwhile, the activity was refused
--    (55000) but the batch upsert itself still went through, touching a
--    finished season's traceability rows. A client may now create or update a
--    batch only while its season is live and `planned` or `active`, and may not
--    move a batch to another season. Backend/service paths are unchanged.
--
-- 2. Clients do not delete activity detail rows directly. No client does -- the
--    app removes an activity through `soft_delete_activity`, FastAPI through
--    its own transaction -- and a write-scope DELETE policy answered a
--    non-writer with a silent "0 rows". Revoking the privilege makes any
--    direct DELETE an explicit 42501 for everyone.

create or replace function private.enforce_batch_season_open()
returns trigger
language plpgsql
set search_path = ''
as $$
declare v_ok boolean;
begin
  if tg_op = 'UPDATE' and new.crop_season_id is distinct from old.crop_season_id then
    raise exception 'production_batches.crop_season_id is immutable' using errcode = '42501';
  end if;
  select cs.deleted_at is null and cs.status in ('planned'::public.crop_status, 'active'::public.crop_status)
    into v_ok
  from public.crop_seasons cs where cs.id = new.crop_season_id;
  if not coalesce(v_ok, false) then
    raise exception 'crop_season_not_open: the crop season of this batch is not open'
      using errcode = '55000';
  end if;
  return new;
end;
$$;

drop trigger if exists enforce_batch_season_open_trg on public.production_batches;
create trigger enforce_batch_season_open_trg
before insert or update on public.production_batches
for each row
when (pg_catalog.row_security_active('public.production_batches'))
execute function private.enforce_batch_season_open();

do $$
declare t text;
begin
  foreach t in array array[
    'seeding_events','fertilizer_applications','irrigation_events','pesticide_applications',
    'fuel_usages','straw_management_events','harvest_events'
  ] loop
    execute format('drop policy if exists %I on public.%I', t || '_delete', t);
    execute format('revoke delete on public.%I from authenticated', t);
  end loop;
end $$;
