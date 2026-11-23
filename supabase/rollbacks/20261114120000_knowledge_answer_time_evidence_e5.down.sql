-- Rollback for migrations/20261114120000_knowledge_answer_time_evidence_e5.sql (RAG V1.5 M7 E5).
-- Not in migrations/: run by hand, in ONE transaction, FIRST (before E7.1), then
--   supabase migration repair --status reverted 20261114120000
-- Drops the answer-time evidence check: a backend that still calls it then refuses every cited answer
-- (fail closed, 503), so deploy a backend without E5 first. It REFUSES while a citation event records the
-- E5 outcome `evidence_refused` (the M6.1 constraint could not be restored without deleting evidence).

begin;

do $$
begin
  if exists (select 1 from public.knowledge_citation_events where outcome = 'evidence_refused') then
    raise exception 'E5 rollback refused: citation events with outcome evidence_refused exist (export and purge them'
      ' through the M6.1 retention path first)';
  end if;
end;
$$;

alter table public.knowledge_citation_events drop constraint knowledge_citation_events_outcome_chk;
alter table public.knowledge_citation_events add constraint knowledge_citation_events_outcome_chk check (
  outcome in ('generated', 'insufficient_evidence', 'policy_rejected', 'error'));
alter table public.knowledge_citation_event_chunks drop constraint knowledge_citation_event_chunks_assurance_chk;
alter table public.knowledge_citation_event_chunks add constraint knowledge_citation_event_chunks_assurance_chk
  check (approval_assurance in ('verified', 'demo_unverified'));
create or replace function private.knowledge_record_citation_event(
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
drop function public.knowledge_cited_evidence_state(uuid, text[], boolean);
drop function private.knowledge_cited_resolved_finding_types(uuid, text[]);

commit;
