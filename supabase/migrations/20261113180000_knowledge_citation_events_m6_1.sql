-- RAG V1.5 M6.1 (docs/rag/RAG_V15_M6_1_CITATION_EVENTS.md): metadata-only citation events, a LOCAL/CI
-- PROTOTYPE. Recording is REFUSED on any database that does not pass the H-a isolation gate
-- (private.knowledge_deployment_isolated()), so this cannot log on the shared hosted project even if
-- the migration were applied there. Not enabled, not deployed. dev3-01 stays OPEN.
-- Depends on H-a (20261113090000).
--
-- One event per answered question (request UUID), with the scope DERIVED from the crop season (never
-- supplied by the caller), the retrieval mode, the outcome, whether the backend emitted a response body (NOT proof that the caller received it), and how
-- complete the trace is. Chunk rows distinguish what was RETRIEVED from what was CITED; their document
-- version and approval assurance are DERIVED from the chunk id. No question, answer, prompt, email,
-- user id, key or secret is stored: there is no column for any of them.
--
-- Retention is a configurable policy (private.knowledge_citation_settings.retention_days); 30 days is
-- the initial LOCAL/CI TEST value, not a production privacy decision. Events are append-only; the only
-- deletion is the retention purge, which is itself recorded.

-- ================================================================== settings

create table private.knowledge_citation_settings (
  singleton boolean primary key default true,
  retention_days integer not null default 30,
  note text not null default 'LOCAL/CI test value; a production retention period needs an owner privacy decision',
  constraint knowledge_citation_settings_singleton_chk check (singleton),
  constraint knowledge_citation_settings_retention_chk check (retention_days between 1 and 400)
);
revoke all on private.knowledge_citation_settings from public, anon, authenticated, service_role;
insert into private.knowledge_citation_settings (singleton) values (true);

-- ================================================================== tables

create table public.knowledge_citation_events (
  request_id uuid primary key,
  occurred_at timestamptz not null default now(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  crop_season_id uuid not null,
  organization_id uuid not null,
  farm_id uuid not null,
  retrieval_mode text not null,
  outcome text not null,
  response_emitted boolean not null,
  trace_completeness text not null,
  retention_until timestamptz not null,
  constraint knowledge_citation_events_mode_chk check (retrieval_mode in ('production', 'demo')),
  constraint knowledge_citation_events_outcome_chk check (
    outcome in ('generated', 'insufficient_evidence', 'policy_rejected', 'error')),
  constraint knowledge_citation_events_trace_chk check (
    trace_completeness in ('complete', 'retrieval_unavailable', 'not_reached')),
  constraint knowledge_citation_events_emitted_chk check (not response_emitted or outcome <> 'error')
);
create index knowledge_citation_events_scope_idx on public.knowledge_citation_events (organization_id, occurred_at);
create index knowledge_citation_events_retention_idx on public.knowledge_citation_events (retention_until);

create table public.knowledge_citation_event_chunks (
  request_id uuid not null references public.knowledge_citation_events (request_id) on delete cascade,
  role text not null,
  chunk_id text not null,
  document_pk uuid not null,
  source_id text not null,
  document_id text not null,
  document_version text not null,
  approval_assurance text not null,
  primary key (request_id, role, chunk_id),
  constraint knowledge_citation_event_chunks_role_chk check (role in ('retrieved', 'cited')),
  constraint knowledge_citation_event_chunks_assurance_chk check (approval_assurance in ('verified', 'demo_unverified'))
);
create index knowledge_citation_event_chunks_chunk_idx on public.knowledge_citation_event_chunks (chunk_id);

create table public.knowledge_citation_purges (
  id bigint generated always as identity primary key,
  purged_at timestamptz not null default now(),
  cutoff timestamptz not null,
  events_deleted integer not null,
  db_role text not null
);

-- RLS on, NO policy: no client role reads the log, organization managers included. Farm + season +
-- time + cited chunk ids reveal what a farm asked about even without the question text, so reading is
-- service_role only (incident response, tenant-scoped exports) until the owner decides who else may
-- (docs section 5). Nobody writes except the definer functions below.
alter table public.knowledge_citation_events enable row level security;
alter table public.knowledge_citation_event_chunks enable row level security;
alter table public.knowledge_citation_purges enable row level security;
revoke all on public.knowledge_citation_events, public.knowledge_citation_event_chunks,
  public.knowledge_citation_purges from public, anon, authenticated, service_role;
grant select on public.knowledge_citation_events, public.knowledge_citation_event_chunks to service_role;
grant select on public.knowledge_citation_purges to service_role;

-- Append-only: INSERT only inside the record function, DELETE only inside the purge, never UPDATE.
create function private.knowledge_citation_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' and private.knowledge_m2_write_authorized('knowledge_citation_events') then
    return new;
  end if;
  if tg_op = 'DELETE' and private.knowledge_m2_write_authorized('knowledge_citation_events.purge') then
    return old;
  end if;
  raise exception '% is an append-only citation log: % is refused (record / purge functions only)', tg_table_name, tg_op
    using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_citation_guard() from public, anon, authenticated, service_role;
create trigger knowledge_citation_events_guard
  before insert or update or delete on public.knowledge_citation_events
  for each row execute function private.knowledge_citation_guard();
create trigger knowledge_citation_events_no_truncate
  before truncate on public.knowledge_citation_events
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_citation_event_chunks_guard
  before insert or update or delete on public.knowledge_citation_event_chunks
  for each row execute function private.knowledge_citation_guard();
create trigger knowledge_citation_event_chunks_no_truncate
  before truncate on public.knowledge_citation_event_chunks
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_citation_purges_guard
  before update or delete on public.knowledge_citation_purges
  for each row execute function private.knowledge_citation_guard();
create trigger knowledge_citation_purges_no_truncate
  before truncate on public.knowledge_citation_purges
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== record

-- Called by the backend with the service credential after it answered. Everything except the request
-- id, the season, the mode, the outcome, the delivery flag, the trace completeness and the two lists
-- of chunk ids is derived here.
create function private.knowledge_record_citation_event(
  p_request_id uuid, p_crop_season_id uuid, p_retrieval_mode text, p_outcome text, p_response_emitted boolean,
  p_trace_completeness text, p_retrieved jsonb, p_cited jsonb)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_scope record;
  v_days integer;
  v_bad text;
begin
  if not private.knowledge_deployment_isolated() then
    raise exception 'citation events are a local/CI prototype (M6.1): recording is refused on a database that is'
      ' not a verified isolated test database' using errcode = '42501';
  end if;
  if p_request_id is null or pg_catalog.jsonb_typeof(coalesce(p_retrieved, 'null')) <> 'array'
     or pg_catalog.jsonb_typeof(coalesce(p_cited, 'null')) <> 'array' then
    raise exception 'a citation event needs a request id and two arrays of chunk ids' using errcode = '22023';
  end if;
  if exists (select 1 from pg_catalog.jsonb_array_elements(p_retrieved || p_cited) e
              where pg_catalog.jsonb_typeof(e) <> 'string') then
    raise exception 'chunk ids are strings' using errcode = '22023';
  end if;
  select (p.farm_id) as farm_id, f.cooperative_id as organization_id into v_scope
    from public.crop_seasons cs join public.plots p on p.id = cs.plot_id join public.farms f on f.id = p.farm_id
   where cs.id = p_crop_season_id;
  if v_scope.farm_id is null then
    raise exception 'crop season % does not exist', p_crop_season_id using errcode = 'P0002';
  end if;
  -- cited is a subset of retrieved
  select c into v_bad from pg_catalog.jsonb_array_elements_text(p_cited) c
   where c not in (select r from pg_catalog.jsonb_array_elements_text(p_retrieved) r) limit 1;
  if v_bad is not null then
    raise exception 'chunk % is cited but was not retrieved for this request', v_bad using errcode = '22023';
  end if;
  -- every chunk is an approved, served chunk visible in this scope (public, or this organization's)
  select r into v_bad from pg_catalog.jsonb_array_elements_text(p_retrieved) r
   where not exists (
     select 1 from public.knowledge_chunks c
       join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
            and d.approval_assurance in ('verified', 'demo_unverified')
       join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
            and s.approval_assurance in ('verified', 'demo_unverified')
      where c.chunk_id = r
        and (s.visibility = 'public' or (s.organization_id = v_scope.organization_id
                                         and (s.farm_id is null or s.farm_id = v_scope.farm_id))))
   limit 1;
  if v_bad is not null then
    raise exception 'chunk % is not an approved chunk of this scope: a citation event cannot name it', v_bad
      using errcode = '42501';
  end if;
  select st.retention_days into v_days from private.knowledge_citation_settings st where st.singleton;
  perform private.knowledge_m2_set_marker('knowledge_citation_events');
  insert into public.knowledge_citation_events (request_id, crop_season_id, organization_id, farm_id, retrieval_mode,
    outcome, response_emitted, trace_completeness, retention_until)
  values (p_request_id, p_crop_season_id, v_scope.organization_id, v_scope.farm_id, p_retrieval_mode, p_outcome,
          p_response_emitted, p_trace_completeness, pg_catalog.now() + pg_catalog.make_interval(days => v_days));
  insert into public.knowledge_citation_event_chunks (request_id, role, chunk_id, document_pk, source_id, document_id,
    document_version, approval_assurance)
  select p_request_id, x.role, c.chunk_id, d.id, d.source_id, d.document_id, d.document_version,
         case when d.approval_assurance = 'verified' and s.approval_assurance = 'verified' then 'verified'
              else 'demo_unverified' end
    from (select distinct 'retrieved' as role, r as chunk_id from pg_catalog.jsonb_array_elements_text(p_retrieved) r
          union select distinct 'cited', c from pg_catalog.jsonb_array_elements_text(p_cited) c) x
    join public.knowledge_chunks c on c.chunk_id = x.chunk_id
    join public.knowledge_documents d on d.id = c.document_pk
    join public.knowledge_sources s on s.source_id = d.source_id;
  perform private.knowledge_m2_set_marker(null);
end;
$$;
revoke all on function private.knowledge_record_citation_event(uuid, uuid, text, text, boolean, text, jsonb, jsonb)
  from public, anon, authenticated, service_role;
grant execute on function private.knowledge_record_citation_event(uuid, uuid, text, text, boolean, text, jsonb, jsonb)
  to service_role;

-- ================================================================== retention

create function private.knowledge_purge_citation_events()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_cutoff timestamptz := pg_catalog.now();
  v_count integer;
begin
  perform private.knowledge_m2_set_marker('knowledge_citation_events.purge');
  delete from public.knowledge_citation_events e where e.retention_until < v_cutoff;
  get diagnostics v_count = row_count;
  perform private.knowledge_m2_set_marker(null);
  insert into public.knowledge_citation_purges (cutoff, events_deleted, db_role)
  values (v_cutoff, v_count, coalesce(nullif(current_setting('role', true), 'none'), session_user));
  return v_count;
end;
$$;
revoke all on function private.knowledge_purge_citation_events() from public, anon, authenticated, service_role;
grant execute on function private.knowledge_purge_citation_events() to service_role;
