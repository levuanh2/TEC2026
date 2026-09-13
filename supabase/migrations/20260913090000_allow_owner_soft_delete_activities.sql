-- Let a scoped recorder soft-delete their own activity from a client that writes
-- through RLS (the Flutter app), without weakening `activities_select`, and pin
-- the ownership fields that decision depends on.
--
-- WHY THE UPDATE PATH CANNOT BE FIXED BY A POLICY
--   PostgreSQL applies SELECT policies to BOTH the existing row and the NEW row
--   of an UPDATE whenever the statement needs read access to the relation — any
--   WHERE or RETURNING naming a column does (CREATE POLICY, "Policies Applied by
--   Command Type", footnote 1). `activities_select` requires `deleted_at is
--   null`, so for any client `update public.activities set deleted_at = now()`
--   fails 42501 no matter what `activities_update`'s own WITH CHECK says.
--   Reproduced against this database as role `authenticated`, same user, same
--   row: `set deleted_at = null` succeeds (1 row); `set deleted_at = now()`
--   fails 42501 with RETURNING, without RETURNING, and through PostgREST's
--   count CTE. The only policy shape that would let the UPDATE through is one
--   that lets clients SELECT their soft-deleted rows, which defeats the point of
--   the soft delete. So the delete intent gets its own entry point instead, and
--   the SELECT policy is left exactly as it was.
--
-- WHAT THIS ADDS
--   * `private.user_can_delete_activity` — the ownership rule, in one place:
--     in-scope production batch AND the caller is the recorder. Same shape and
--     same helpers as the existing policies, and the same rule the FastAPI
--     endpoint enforces (`write_repo.soft_delete` filters `recorded_by = actor`).
--   * `public.soft_delete_activity(uuid)` — the client entry point. Raises 42501
--     when the caller is not entitled, so a cross-scope attempt is an honest,
--     permanent denial rather than a silent no-op; idempotent otherwise.
--   * `private.enforce_activity_ownership_immutable` — a client cannot reassign
--     `recorded_by`, retype an activity out from under its detail row, or rewrite
--     the `(device_id, client_event_id)` idempotency key. Without this a caller
--     could claim another member's row and then delete it. It stands down when
--     row-level security is not active for the caller, so service-role paths
--     (backend writes, seeds, imports, backfills) are unchanged.
--   * `activities_update` also refuses to let a caller hand an unowned row to a
--     third party; the trigger covers every other reassignment.

-- --------------------------------------------------------------------------
-- 1. Ownership rule
-- --------------------------------------------------------------------------

create or replace function private.user_can_delete_activity(p_activity uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  -- Deliberately NOT filtered on `deleted_at`: an already soft-deleted row must
  -- still resolve so a repeated delete is idempotent instead of "denied".
  select exists (
    select 1 from public.activities a
    where a.id = p_activity
      and a.recorded_by = (select auth.uid())
      and private.user_can_write_batch(a.production_batch_id)
  );
$$;

-- --------------------------------------------------------------------------
-- 2. Client entry point for the soft delete
-- --------------------------------------------------------------------------

create or replace function public.soft_delete_activity(p_activity_id uuid)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if p_activity_id is null then
    raise exception 'p_activity_id is required' using errcode = '22004';
  end if;

  if not private.user_can_delete_activity(p_activity_id) then
    -- Same code the RLS policies produce, so clients need one classification.
    raise exception 'not allowed to delete activity %', p_activity_id
      using errcode = '42501';
  end if;

  -- Runs as the function owner, so `activities_select` is not re-applied to the
  -- new row. Only `deleted_at` is touched: scope and ownership cannot move here.
  -- `touch_activity_row_trg` bumps `row_version`/`updated_at`, and
  -- `audit_change_trg` records it as an ordinary update.
  update public.activities
     set deleted_at = now()
   where id = p_activity_id
     and deleted_at is null;

  -- True for "it is deleted now", whether this call or an earlier one did it.
  return true;
end;
$$;

revoke all on function public.soft_delete_activity(uuid) from public;
grant execute on function public.soft_delete_activity(uuid) to authenticated;

-- --------------------------------------------------------------------------
-- 3. Ownership / identity fields are immutable to clients
-- --------------------------------------------------------------------------

create or replace function private.enforce_activity_ownership_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- Adopting an unowned legacy row is allowed (and `activities_update`'s WITH
  -- CHECK restricts that to the caller themselves). Everything else is pinned.
  if old.recorded_by is not null
     and new.recorded_by is distinct from old.recorded_by then
    raise exception 'activities.recorded_by is immutable' using errcode = '42501';
  end if;

  -- Retyping would orphan the detail row: `private.enforce_activity_type` only
  -- guards the detail tables' own writes, not a later change to the parent.
  if new.activity_type is distinct from old.activity_type then
    raise exception 'activities.activity_type is immutable' using errcode = '42501';
  end if;

  -- The offline idempotency key. Rewriting it would let one device claim
  -- another device's row, or split one logical entry into two.
  if old.device_id is not null and new.device_id is distinct from old.device_id then
    raise exception 'activities.device_id is immutable' using errcode = '42501';
  end if;
  if old.client_event_id is not null
     and new.client_event_id is distinct from old.client_event_id then
    raise exception 'activities.client_event_id is immutable' using errcode = '42501';
  end if;

  return new;
end;
$$;

drop trigger if exists enforce_activity_ownership_immutable_trg on public.activities;
create trigger enforce_activity_ownership_immutable_trg
before update on public.activities
for each row
when (pg_catalog.row_security_active('public.activities'))
execute function private.enforce_activity_ownership_immutable();

-- --------------------------------------------------------------------------
-- 4. A client may only ever write its own id into `recorded_by`
-- --------------------------------------------------------------------------

drop policy if exists activities_update on public.activities;
create policy activities_update on public.activities for update to authenticated
  using (private.user_can_write_batch(production_batch_id))
  with check (
    private.user_can_write_batch(production_batch_id)
    and (recorded_by is null or recorded_by = (select auth.uid()))
  );
