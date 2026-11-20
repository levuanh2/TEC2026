-- Rollback for migrations/20261120090000_knowledge_pin_aware_admission_e5_1.sql (RAG V1.5 M7 E5.1).
-- Not in migrations/: run by hand, in ONE transaction, FIRST (before the E5 rollback), then
--   supabase migration repair --status reverted 20261120090000
-- Restores E5's three-argument answer-time check exactly (no pin check). Deploy a backend WITHOUT E5.1 first: an
-- E5.1 backend calls the four-argument function, which this drops, so it then refuses every answer that cites a
-- document (fail closed, 503). After this rollback stale-pin approvals are admissible again (the E5 residual).
-- Nothing was written by E5.1 (no table, no row): no data to keep or purge.

begin;

drop function public.knowledge_cited_evidence_state(uuid, text[], boolean, boolean);
drop function private.knowledge_cited_integrity_status(uuid, text[], boolean);
drop function private.knowledge_integrity_admission_inventory();
drop function private.knowledge_integrity_admission_problem(uuid);

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

commit;
