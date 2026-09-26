-- Follow-up from the independent review (round 2): a detail row belongs to a
-- live activity. After an activity is soft-deleted, its detail row could still
-- be inserted or updated by a writer while the season was active, because the
-- detail policies and trigger looked only at the parent's batch/season. The
-- client trigger now also refuses a soft-deleted parent (42501). Backend and
-- cleanup paths (no RLS) are unchanged.

create or replace function private.enforce_activity_detail_season_open()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_batch uuid;
  v_deleted boolean;
begin
  select a.production_batch_id, a.deleted_at is not null into v_batch, v_deleted
  from public.activities a
  where a.id = case when tg_op = 'DELETE' then old.activity_id else new.activity_id end;
  if v_batch is not null and not private.activity_batch_open(v_batch) then
    raise exception 'crop_season_not_open: the crop season of this activity is not active'
      using errcode = '55000';
  end if;
  if tg_op in ('INSERT', 'UPDATE') and coalesce(v_deleted, false) then
    raise exception 'activity_deleted: this activity was deleted' using errcode = '42501';
  end if;
  if tg_op = 'UPDATE' and new.activity_id is distinct from old.activity_id then
    raise exception '%.activity_id is immutable', tg_table_name using errcode = '42501';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;
