-- Rollback for migrations/20261003090000_forced_password_stale_token.sql.
-- Restores private.password_change_pending() as 20261002100000 defined it
-- (live auth.users flag only). Touches no data. Re-opens the stale-token gap
-- the forward migration closes. Not in migrations/: run by hand, in one
-- transaction, only if the forward migration must be withdrawn. Afterwards
-- `supabase migration repair --status reverted 20261003090000`.
begin;
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
commit;
