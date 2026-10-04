-- Core V1 closure: an access token minted while the temporary password was
-- still in force stays refused after the password is changed.
--
-- 20261002100000 made every root authorization helper answer false while
-- private.password_change_pending() is true, and that function read ONLY the
-- live auth.users flag. Changing the password clears the flag and revokes the
-- refresh tokens, but an access token minted with the temporary password stays
-- valid until it expires (up to an hour). Once the live flag was false, that
-- token -- held by whoever knew the temporary password, e.g. the provisioning
-- manager -- read and wrote the farmer's data through PostgREST.
--
-- Rule now (fail closed): pending when EITHER
--   * the request's JWT carries app_metadata.must_change_password = true
--     (the claim it was minted with; PostgREST verifies the signature, so it
--     cannot be forged or edited), OR
--   * the authoritative auth.users flag is still set (a token minted before
--     provisioning set the flag, or a claim-less backend session).
-- A token minted after the change carries no/false claim and the live flag is
-- false: normal permission evaluation. Every helper that calls this function
-- (the 7 root authorization helpers of 20261002100000) follows; their bodies
-- are unchanged.
--
-- FastAPI pooled paths set request.jwt.claims to {sub, role} only: the claim
-- branch is false there and the live flag decides, as before; FastAPI's own
-- guard already refuses a token whose claim is true.
--
-- Rollback: supabase/rollbacks/20261003090000_forced_password_stale_token.down.sql

create or replace function private.password_change_pending()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(((select auth.jwt()) -> 'app_metadata' ->> 'must_change_password') = 'true', false)
  or coalesce((
    select (u.raw_app_meta_data ->> 'must_change_password') = 'true'
    from auth.users u
    where u.id = (select auth.uid())
  ), false);
$$;
revoke all on function private.password_change_pending() from public;
