-- RAG V1.5 M7 E5 (docs/rag/RAG_V15_M7_E5_ANSWER_TIME_CONTROL.md): answer-time re-validation of cited evidence.
-- LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN. Depends on M6.1 (20261113180000),
-- E2 (20261113210000) and E7.1 (20261114090000).
--
-- After the model answered and the orchestrator resolved its citations, and immediately before the response is
-- built, the backend asks the database, UNDER THE CALLER'S JWT, which of the cited chunks are STILL admissible
-- for this crop season with the same predicate retrieval used (approved + verified version and source, in force
-- today, tenant scope derived from the season), plus their current version and content hash. Any cited chunk
-- that is missing, changed or no longer admissible makes the backend discard the whole model answer.
--
-- Consistency boundary: the check sees the database as of its own statement. A status change committed AFTER
-- that statement and before the bytes reach the client is not caught (documented; the M6.1 exposure query
-- covers that window after the fact). Nothing here approves, quarantines or judges scientific truth.

-- ================================================================== caveats (finding types only, never content)

-- For each cited chunk the caller may retrieve for this season: the integrity finding types of its version's
-- current report that the expert resolved as false_positive or contextual_difference. SECURITY DEFINER (the E2
-- tables are not client-readable) but it answers only for chunks the caller could retrieve: the season must be
-- readable by the caller and the chunk admissible for that season's tenant, exactly as in retrieval.
create function private.knowledge_cited_resolved_finding_types(p_crop_season_id uuid, p_chunk_ids text[])
returns table (chunk_id text, finding_types text[])
language sql
stable
security definer
set search_path = ''
as $$
  with scope as (
    select p.farm_id, f.cooperative_id as organization_id
      from public.crop_seasons cs
      join public.plots p on p.id = cs.plot_id
      join public.farms f on f.id = p.farm_id
     where cs.id = p_crop_season_id
       and not private.knowledge_read_blocked()
       and private.user_can_read_farm(p.farm_id)
  ),
  admissible as (
    select c.chunk_id, d.id as document_pk
      from public.knowledge_chunks c
      join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
       and d.approval_assurance = 'verified'
       and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
       and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
       and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
      join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
       and s.approval_assurance = 'verified'
      cross join scope
     where c.chunk_id = any (p_chunk_ids[1:50])
       and (s.visibility = 'public'
            or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
                and (s.farm_id is null
                     or (s.farm_id = scope.farm_id
                         and exists (select 1 from public.farms f2
                                      where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))))
  )
  select a.chunk_id,
         coalesce((select pg_catalog.array_agg(distinct f.finding_type order by f.finding_type)
                     from public.knowledge_integrity_findings f
                     join public.knowledge_integrity_dispositions x on x.finding_id = f.id
                    where f.report_id = (private.knowledge_integrity_current_report(a.document_pk)).id
                      and x.disposition in ('false_positive', 'contextual_difference')), '{}')
    from admissible a;
$$;
revoke all on function private.knowledge_cited_resolved_finding_types(uuid, text[]) from public, anon, authenticated, service_role;
grant execute on function private.knowledge_cited_resolved_finding_types(uuid, text[]) to authenticated;

-- ================================================================== the answer-time check (caller's JWT)

create function public.knowledge_cited_evidence_state(p_crop_season_id uuid, p_chunk_ids text[], p_demo boolean default false)
returns table (
  source_id text,
  document_id text,
  document_version text,
  chunk_id text,
  content_sha256 text,
  content_hash_consistent boolean,
  approval_assurance text,
  resolved_finding_types text[]
)
language plpgsql
stable
security invoker
set search_path = ''
as $$
begin
  if p_chunk_ids is null or pg_catalog.cardinality(p_chunk_ids) > 50 then
    raise exception 'between 0 and 50 cited chunk ids' using errcode = '22023';
  end if;
  if p_demo and not private.knowledge_deployment_isolated() then
    raise exception 'demo knowledge is served only on an isolated test database (owner decision D-H3a)'
      using errcode = '42501';
  end if;
  return query
  with scope as (
    select p.farm_id, f.cooperative_id as organization_id
      from public.crop_seasons cs
      join public.plots p on p.id = cs.plot_id
      join public.farms f on f.id = p.farm_id
     where cs.id = p_crop_season_id
  )
  select d.source_id, d.document_id, d.document_version, c.chunk_id, c.content_sha256,
         c.content_sha256 = pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(c.content, 'UTF8')), 'hex'),
         d.approval_assurance::text,
         coalesce(t.finding_types, '{}')
    from public.knowledge_chunks c
    join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
     and (d.approval_assurance = 'verified' or (p_demo and d.approval_assurance = 'demo_unverified'))
     and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
     and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
     and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
     and (s.approval_assurance = 'verified' or (p_demo and s.approval_assurance = 'demo_unverified'))
    cross join scope
    left join private.knowledge_cited_resolved_finding_types(p_crop_season_id, p_chunk_ids) t
      on t.chunk_id = c.chunk_id
   where c.chunk_id = any (p_chunk_ids)
     and (s.visibility = 'public'
          or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
              and (s.farm_id is null
                   or (s.farm_id = scope.farm_id
                       and exists (select 1 from public.farms f2
                                    where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))));
end;
$$;
revoke all on function public.knowledge_cited_evidence_state(uuid, text[], boolean) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_cited_evidence_state(uuid, text[], boolean) to authenticated;

-- ================================================================== M6.1: the answer-time refusal is an outcome

alter table public.knowledge_citation_events drop constraint knowledge_citation_events_outcome_chk;
alter table public.knowledge_citation_events add constraint knowledge_citation_events_outcome_chk check (
  outcome in ('generated', 'insufficient_evidence', 'policy_rejected', 'evidence_refused', 'error'));

-- An evidence_refused event can name a chunk whose assurance is no longer verified or demo: record it truthfully.
alter table public.knowledge_citation_event_chunks drop constraint knowledge_citation_event_chunks_assurance_chk;
alter table public.knowledge_citation_event_chunks add constraint knowledge_citation_event_chunks_assurance_chk
  check (approval_assurance in ('verified', 'demo_unverified', 'unrecorded'));

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
  -- every chunk is an approved, served chunk visible in this scope (public, or this organization's).
  -- M7 E5: an `evidence_refused` event names chunks that LEFT that state between retrieval and the answer-time
  -- check (that is why it was refused): for it, existence in this scope is enough; the status is not re-required.
  select r into v_bad from pg_catalog.jsonb_array_elements_text(p_retrieved) r
   where not exists (
     select 1 from public.knowledge_chunks c
       join public.knowledge_documents d on d.id = c.document_pk
            and ((d.status = 'approved' and d.approval_assurance in ('verified', 'demo_unverified'))
                 or p_outcome = 'evidence_refused')
       join public.knowledge_sources s on s.source_id = d.source_id
            and ((s.status = 'approved' and s.approval_assurance in ('verified', 'demo_unverified'))
                 or p_outcome = 'evidence_refused')
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
              when 'demo_unverified' in (d.approval_assurance, s.approval_assurance) then 'demo_unverified'
              else 'unrecorded' end
    from (select distinct 'retrieved' as role, r as chunk_id from pg_catalog.jsonb_array_elements_text(p_retrieved) r
          union select distinct 'cited', c from pg_catalog.jsonb_array_elements_text(p_cited) c) x
    join public.knowledge_chunks c on c.chunk_id = x.chunk_id
    join public.knowledge_documents d on d.id = c.document_pk
    join public.knowledge_sources s on s.source_id = d.source_id;
  perform private.knowledge_m2_set_marker(null);
end;
$$;
