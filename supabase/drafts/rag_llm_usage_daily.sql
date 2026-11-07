-- DRAFT — NOT A MIGRATION, NOT APPLIED ANYWHERE. Lives outside supabase/migrations on purpose.
-- Durable per-day model-call counters for RAG quotas when the API runs on more than one
-- instance (infrastructure/llm_quota.py InProcessQuotaStore is exact for one process only).
-- To adopt: copy into supabase/migrations/<timestamp>_rag_llm_usage_daily.sql with the
-- rollback below, update scripts/ci/policy/migrations.sha256 and the db_audit snapshot, run
-- Normal + Strict CI, then the one-migration hosted gate with explicit owner approval.
--
-- No prompt, answer, question or key is stored: a pseudonymous user key (salted sha256
-- prefix, never auth.users.id), counts and USD. Service role only; clients see nothing.

create table if not exists private.rag_llm_usage_daily (
  usage_day date not null,
  user_key text not null check (user_key ~ '^[0-9a-f]{16}$' or user_key = '*project*'),
  requests integer not null default 0 check (requests >= 0),
  cost_usd numeric(14, 6) not null default 0 check (cost_usd >= 0),
  updated_at timestamptz not null default now(),
  primary key (usage_day, user_key)
);
revoke all on private.rag_llm_usage_daily from public, anon, authenticated;

-- Atomic reserve: increments the user's and the project's counters only when both stay
-- within their limits and the day's cost is below the hard stop; returns false otherwise.
create or replace function private.rag_llm_usage_reserve(
  p_day date, p_user_key text, p_user_limit integer, p_project_limit integer, p_cost_hard_stop numeric
) returns boolean
language plpgsql
set search_path = ''
as $$
declare
  v_project private.rag_llm_usage_daily;
  v_user integer;
begin
  insert into private.rag_llm_usage_daily (usage_day, user_key) values (p_day, '*project*')
    on conflict do nothing;
  select * into v_project from private.rag_llm_usage_daily
    where usage_day = p_day and user_key = '*project*' for update;
  if v_project.requests >= p_project_limit
     or (p_cost_hard_stop is not null and v_project.cost_usd >= p_cost_hard_stop) then
    return false;
  end if;
  insert into private.rag_llm_usage_daily (usage_day, user_key) values (p_day, p_user_key)
    on conflict do nothing;
  select requests into v_user from private.rag_llm_usage_daily
    where usage_day = p_day and user_key = p_user_key for update;
  if v_user >= p_user_limit then
    return false;
  end if;
  update private.rag_llm_usage_daily set requests = requests + 1, updated_at = now()
    where usage_day = p_day and user_key in (p_user_key, '*project*');
  return true;
end;
$$;
revoke all on function private.rag_llm_usage_reserve(date, text, integer, integer, numeric)
  from public, anon, authenticated;
