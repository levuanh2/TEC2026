-- RAG Q&A per-user question rate limit (READ-only pilot safeguard A12).
--
-- Version 20261106090000 (written 2026-11-23) on purpose: it sorts after main's newest
-- migration (20261105090000) and before the integrate/rag-v15 stack's first one
-- (20261110090000), so this file can land on main before or after that stack without
-- forcing the stack's migrations to be renumbered (check_migrations.py: a new migration must
-- sort after the newest one on its base). If the stack reaches main first, renumber THIS file.
--
-- Backend-only. `POST /v1/crop-seasons/{id}/questions` calls
-- private.consume_rag_question_quota once per question, AFTER Supabase Auth has verified
-- the caller's JWT and BEFORE any season, Carbon or knowledge read. The key is the
-- verified auth user id, never a request field, an IP address or a crop season id.
--
-- Atomic: one call = one transaction holding a per-user advisory lock, so concurrent
-- requests of the same user are serialised and can never exceed the limits; different
-- users never wait on each other. Sliding windows: the last 60 seconds and the last
-- 24 hours. Only ALLOWED questions are recorded, so retrying while limited does not
-- extend the wait. Nothing about the question is stored: user id + timestamp only.
--
-- The limits are arguments supplied by the server (env RAG_QA_RATE_LIMIT_PER_MINUTE /
-- _PER_DAY); no client role can call the function or read the table.

create table private.rag_question_events (
  user_id uuid not null references auth.users (id) on delete cascade,
  asked_at timestamptz not null
);

comment on table private.rag_question_events is
  'Allowed RAG Q&A questions per verified user (timestamps only, kept <= 24 h). Backend-only; see private.consume_rag_question_quota.';

create index rag_question_events_user_asked_at on private.rag_question_events (user_id, asked_at);
create index rag_question_events_asked_at on private.rag_question_events (asked_at);

alter table private.rag_question_events enable row level security;
alter table private.rag_question_events force row level security;
revoke all on table private.rag_question_events from public, anon, authenticated;

create function private.consume_rag_question_quota(
  p_user_id uuid, p_per_minute integer, p_per_day integer
)
returns table (allowed boolean, limit_window text, retry_after_seconds integer)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_minute integer;
  v_day integer;
  v_expires timestamptz;
begin
  if p_user_id is null or p_per_minute is null or p_per_day is null
     or p_per_minute < 1 or p_per_day < 1 then
    raise exception 'consume_rag_question_quota: invalid arguments' using errcode = '22023';
  end if;

  -- Serialise this user's questions only (transaction-scoped; released at commit/rollback).
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('agricarbon.rag_question_quota:' || p_user_id::text, 0));

  -- Rows older than the longest window are never needed again (any user).
  delete from private.rag_question_events e where e.asked_at <= v_now - interval '1 day';

  select count(*) filter (where e.asked_at > v_now - interval '1 minute'), count(*)
    into v_minute, v_day
    from private.rag_question_events e
   where e.user_id = p_user_id;

  if v_day >= p_per_day then
    -- The question that must expire for the count to drop below the limit.
    select e.asked_at into v_expires
      from private.rag_question_events e
     where e.user_id = p_user_id
     order by e.asked_at
     offset (v_day - p_per_day) limit 1;
    return query select false, 'day'::text,
      greatest(1, pg_catalog.ceil(extract(epoch from (v_expires + interval '1 day' - v_now)))::integer);
    return;
  end if;

  if v_minute >= p_per_minute then
    select e.asked_at into v_expires
      from private.rag_question_events e
     where e.user_id = p_user_id and e.asked_at > v_now - interval '1 minute'
     order by e.asked_at
     offset (v_minute - p_per_minute) limit 1;
    return query select false, 'minute'::text,
      greatest(1, pg_catalog.ceil(extract(epoch from (v_expires + interval '1 minute' - v_now)))::integer);
    return;
  end if;

  insert into private.rag_question_events (user_id, asked_at) values (p_user_id, v_now);
  return query select true, null::text, 0;
end;
$$;

comment on function private.consume_rag_question_quota(uuid, integer, integer) is
  'Atomically checks and records one RAG Q&A question for a verified user (sliding 1 min / 24 h windows). Backend-only.';

revoke all on function private.consume_rag_question_quota(uuid, integer, integer) from public, anon, authenticated;
grant execute on function private.consume_rag_question_quota(uuid, integer, integer) to service_role;
