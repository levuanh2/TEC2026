-- Rollback for migrations/20261127090000_knowledge_chunks_read_admission.sql. Not in migrations/: run by hand, in ONE
-- transaction, then  supabase migration repair --status reverted 20261127090000
-- Restores the E5.2 helper body and the Migration A chunks policy (the direct read is then NOT admission-aware again:
-- the gap this migration closed comes back). Retrieval and the answer path are unchanged either way.

begin;

drop policy knowledge_chunks_select on public.knowledge_chunks;
create policy knowledge_chunks_select on public.knowledge_chunks
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and exists (select 1 from public.knowledge_documents d where d.id = knowledge_chunks.document_pk)
  );

-- the E5.2 definition, verbatim (migrations/20261120120000_knowledge_pin_generation_e5_2.sql)
create or replace function private.knowledge_generation_admitted_documents(p_crop_season_id uuid)
returns table (document_pk uuid)
language sql
stable
security definer
set search_path = ''
as $$
  with pin as (
    select p.* from private.knowledge_integrity_policy p
     where p.singleton and p.registry_digest is not null and p.extractor_code_digest is not null
       and p.attestation_mode is not null
  ),
  scope as (
    select pl.farm_id, f.cooperative_id as organization_id
      from public.crop_seasons cs
      join public.plots pl on pl.id = cs.plot_id
      join public.farms f on f.id = pl.farm_id
     where cs.id = p_crop_season_id
       and not private.knowledge_read_blocked()
       and private.user_can_read_farm(pl.farm_id)
  ),
  docs as (
    select d.id
      from public.knowledge_documents d
      join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
       and s.approval_assurance = 'verified'
      cross join scope
     where d.status = 'approved' and d.approval_assurance = 'verified'
       and (s.visibility = 'public'
            or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
                and (s.farm_id is null
                     or (s.farm_id = scope.farm_id
                         and exists (select 1 from public.farms f2
                                      where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))))
  )
  select d.id
    from docs d
   cross join pin
   cross join lateral (select r.id, r.report_sha256, r.extractor_version, r.review_version, r.registry_version,
                              r.registry_digest, r.pin_generation
                         from public.knowledge_integrity_reports r where r.document_pk = d.id
                        order by r.recorded_at desc, r.id desc limit 1) r
   where r.pin_generation = pin.generation
     and (r.extractor_version, r.review_version, r.registry_version, r.registry_digest)
         = (pin.extractor_version, pin.review_version, pin.registry_version, pin.registry_digest)
     and not exists (select 1 from public.knowledge_integrity_verifications v
                      where v.report_id = r.id and v.verdict = 'mismatch')
     and exists (select 1 from public.knowledge_integrity_verifications v
                   join public.knowledge_integrity_verifier_keys k on k.key_id = v.key_id and k.status = 'active'
                  where v.report_id = r.id and v.report_sha256 = r.report_sha256 and v.verdict = 'reproduced'
                    and v.pin_generation = pin.generation and v.extractor_code_digest = pin.extractor_code_digest
                    and v.extractor_version = pin.extractor_version and v.registry_digest = pin.registry_digest
                    and (v.signature_checked_in_db or pin.attestation_mode = 'offline_signature_audit'))
     and exists (select 1 from public.knowledge_approval_records a
                   join public.knowledge_integrity_dispositions x
                     on x.review_id = a.review_id and x.report_id = r.id and x.finding_id is null
                    and x.disposition = 'report_reviewed' and x.report_sha256 = r.report_sha256
                  where a.entity_type = 'document' and a.document_pk = d.id and a.decision = 'approve'
                    and a.assurance = 'verified' and a.pin_generation = pin.generation);
$$;

-- the E5.1 answer-time recheck, verbatim (migrations/20261120090000_knowledge_pin_aware_admission_e5_1.sql)
create or replace function public.knowledge_cited_evidence_state(p_crop_season_id uuid, p_chunk_ids text[],
                                                      p_demo boolean default false,
                                                      p_integrity_status boolean default false)
returns table (
  source_id text,
  document_id text,
  document_version text,
  chunk_id text,
  content_sha256 text,
  content_hash_consistent boolean,
  approval_assurance text,
  resolved_finding_types text[],
  integrity_status text
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
  ),
  cited as (
    select d.source_id, d.document_id, d.document_version, c.chunk_id, c.content_sha256,
           c.content_sha256 = pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(c.content, 'UTF8')), 'hex')
             as content_hash_consistent,
           d.approval_assurance::text as approval_assurance,
           coalesce(t.finding_types, '{}') as resolved_finding_types,
           -- no status row (a chunk the definer function does not answer for) is never "current"
           coalesce(i.integrity_status, 'not_current') as integrity_status
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
      left join private.knowledge_cited_integrity_status(p_crop_season_id, p_chunk_ids, p_demo) i
        on i.chunk_id = c.chunk_id
     where c.chunk_id = any (p_chunk_ids)
       and (s.visibility = 'public'
            or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
                and (s.farm_id is null
                     or (s.farm_id = scope.farm_id
                         and exists (select 1 from public.farms f2
                                      where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))))
  )
  select r.source_id, r.document_id, r.document_version, r.chunk_id, r.content_sha256, r.content_hash_consistent,
         r.approval_assurance, r.resolved_finding_types, r.integrity_status
    from cited r
   where p_integrity_status
      or r.integrity_status = 'current'
      or (r.approval_assurance = 'demo_unverified' and r.integrity_status = 'demo_unverified');
end;
$$;

drop function private.knowledge_cited_chunk_hashes(text[]);
drop function private.knowledge_admitted_document_pks();

commit;
