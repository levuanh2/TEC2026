-- RAG V1.5 M7 E5.1 (docs/rag/RAG_V15_M7_E5_1_PIN_AWARE_ADMISSION.md): pin-aware evidence admission.
-- LOCAL/CI ONLY until the owner approves a hosted migration (owner decision D-ROLLOUT, 2026-11-20). dev3-01 stays
-- OPEN. Depends on E2 (20261113210000), E7 (20261113235900), E7.1 (20261114090000) and E5 (20261114120000).
--
-- Owner decision D-E5-PIN (2026-11-20): evidence evaluated against an obsolete integrity pin must not automatically
-- remain admissible for AI answers. Before this migration E5 re-checked approval and assurance only, so a version
-- approved under kn-claims-3 stayed citable after the owner moved the pin to kn-claims-4, with no finding.
--
-- A verified approved version is INTEGRITY-CURRENT when, re-evaluated now:
--   1. the owner's pin is complete (extractor, review, registry + digest, extractor code digest, attestation mode);
--   2. its latest integrity report exists and was made under exactly that pin (extractor, review, registry, digest);
--   3. the report is not stale (version and source snapshots, recorded claim count: E2's own check);
--   4. every chunk still hashes to its recorded content hash (E7.1);
--   5. no independent verification of the report says `mismatch`, and one says `reproduced` for the current
--      extractor version, extractor code digest and registry digest, signed by a key that is still active and
--      accepted under the current attestation mode, over the claim set the database recomputes now (E7/E7.1);
--   6. a verified approval record of the version names a review that acknowledged exactly this report.
-- Missing metadata is never read as valid: any absent piece makes the version not current. Nothing here approves,
-- quarantines, re-reports or changes any status; an old human approval is simply no longer admissible evidence
-- under a new pin. The path back is a NEW VERSION reviewed under the new pin (owner decision D-REVIEW).
--
-- Rollback re-activation: the check compares with the pin as it is NOW. If the owner sets the pin back to the
-- exact earlier tuple, the versions approved under that tuple are current again (that is what a rollback means);
-- versions approved under the newer pin are not. Documented and tested; changing it is an owner decision.
--
-- Demo approvals (assurance demo_unverified, isolated test databases only, H-a) have no review and no report by
-- design. They are reported as `demo_unverified`, never as `current`; the backend admits them only in its labelled
-- demo mode, exactly as before.

-- ================================================================== why a version is not integrity-current

-- Null when the version is integrity-current, else a short internal reason code. Owner-only: callable from the
-- SECURITY DEFINER functions below and by an operator session (inventory). Never exposed to a client: the reason
-- names private report state. Lock-free (STABLE) on purpose: the approval gate keeps its own share-locking check
-- (private.knowledge_integrity_verification_problem); this is a read-time admission check.
create function private.knowledge_integrity_admission_problem(p_document_pk uuid)
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_pin record;
  v_report public.knowledge_integrity_reports;
begin
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.registry_digest is null or v_pin.extractor_code_digest is null or v_pin.attestation_mode is null then
    return 'policy_not_pinned';
  end if;
  v_report := private.knowledge_integrity_current_report(p_document_pk);
  if v_report.id is null then
    return 'no_report';
  end if;
  if (v_report.extractor_version, v_report.review_version, v_report.registry_version, v_report.registry_digest)
     is distinct from (v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest) then
    return 'report_not_under_current_pin';
  end if;
  if private.knowledge_integrity_report_problem(v_report) is not null then
    return 'report_stale';
  end if;
  if private.knowledge_chunk_hash_problem(p_document_pk) is not null then
    return 'chunk_hash_inconsistent';
  end if;
  if exists (select 1 from public.knowledge_integrity_verifications v
              where v.report_id = v_report.id and v.verdict = 'mismatch') then
    return 'verification_mismatch';
  end if;
  if not exists (
       select 1
         from public.knowledge_integrity_verifications v
         join public.knowledge_integrity_verifier_keys k on k.key_id = v.key_id and k.status = 'active'
        where v.report_id = v_report.id and v.report_sha256 = v_report.report_sha256 and v.verdict = 'reproduced'
          and v.document_snapshot_sha256 = v_report.document_snapshot_sha256
          and v.extractor_version = v_pin.extractor_version
          and v.extractor_code_digest = v_pin.extractor_code_digest
          and v.registry_digest = v_pin.registry_digest
          and (v.signature_checked_in_db or v_pin.attestation_mode = 'offline_signature_audit')
          and v.claim_set_digest = private.knowledge_claim_set_digest(p_document_pk, v_report.extractor_version)) then
    return 'not_verified_under_current_pin';
  end if;
  if not exists (
       select 1
         from public.knowledge_approval_records a
         join public.knowledge_integrity_dispositions x
           on x.review_id = a.review_id and x.report_id = v_report.id and x.finding_id is null
          and x.disposition = 'report_reviewed' and x.report_sha256 = v_report.report_sha256
        where a.entity_type = 'document' and a.document_pk = p_document_pk and a.decision = 'approve'
          and a.assurance = 'verified') then
    return 'approval_not_bound_to_report';
  end if;
  return null;
end;
$$;
revoke all on function private.knowledge_integrity_admission_problem(uuid) from public, anon, authenticated, service_role;

-- ================================================================== per cited chunk, for the caller

-- For each chunk the caller may retrieve for this season (same scope as retrieval and as
-- private.knowledge_cited_resolved_finding_types): `current`, `not_current` or, for an isolated demo approval
-- asked for in demo mode, `demo_unverified`. SECURITY DEFINER (the E2/E7 tables and the pin are not client-
-- readable) but it answers only for chunks the caller could retrieve, and only with one of those three words.
create function private.knowledge_cited_integrity_status(p_crop_season_id uuid, p_chunk_ids text[], p_demo boolean)
returns table (chunk_id text, integrity_status text)
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
  admissible as materialized (
    select c.chunk_id, d.id as document_pk, d.approval_assurance::text as assurance
      from public.knowledge_chunks c
      join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
       and (d.approval_assurance = 'verified'
            or (p_demo and d.approval_assurance = 'demo_unverified' and private.knowledge_deployment_isolated()))
       and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
       and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
       and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
      join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
       and (s.approval_assurance = 'verified'
            or (p_demo and s.approval_assurance = 'demo_unverified' and private.knowledge_deployment_isolated()))
      cross join scope
     where c.chunk_id = any (p_chunk_ids[1:50])
       and (s.visibility = 'public'
            or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
                and (s.farm_id is null
                     or (s.farm_id = scope.farm_id
                         and exists (select 1 from public.farms f2
                                      where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))))
  ),
  documents as materialized (
    select x.document_pk,
           case when x.assurance = 'demo_unverified' then 'demo_unverified'
                when private.knowledge_integrity_admission_problem(x.document_pk) is null then 'current'
                else 'not_current' end as integrity_status
      from (select distinct a.document_pk, a.assurance from admissible a) x
  )
  select a.chunk_id, d.integrity_status from admissible a join documents d on d.document_pk = a.document_pk;
$$;
revoke all on function private.knowledge_cited_integrity_status(uuid, text[], boolean)
  from public, anon, authenticated, service_role;
grant execute on function private.knowledge_cited_integrity_status(uuid, text[], boolean) to authenticated;

-- ================================================================== the answer-time check, pin-aware

-- Replaces E5's function (same name, one more argument with a default). Every row gains `integrity_status`.
-- p_integrity_status = false (what an E5 backend sends: three arguments) EXCLUDES every verified row that is not
-- integrity-current, so a backend that predates E5.1 can never admit stale evidence; it sees the chunk as no longer
-- admissible and refuses (fail closed). p_integrity_status = true (the E5.1 backend) returns those rows labelled
-- `not_current`, so the answer can say why it was refused. Either way nothing about other tenants is returned.
drop function public.knowledge_cited_evidence_state(uuid, text[], boolean);

create function public.knowledge_cited_evidence_state(p_crop_season_id uuid, p_chunk_ids text[],
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
revoke all on function public.knowledge_cited_evidence_state(uuid, text[], boolean, boolean)
  from public, anon, authenticated, service_role;
grant execute on function public.knowledge_cited_evidence_state(uuid, text[], boolean, boolean) to authenticated;

-- ================================================================== operator inventory (owner session only)

-- Every approved version with the state of its integrity evidence under the CURRENT pin: the input of the
-- versioned re-review workflow (docs/rag/RAG_V15_M7_E5_1_PIN_AWARE_ADMISSION.md section 6). Read-only. Owner-only:
-- it names report versions and reasons, which are private review state.
create function private.knowledge_integrity_admission_inventory()
returns table (
  document_pk uuid,
  source_id text,
  document_id text,
  document_version text,
  approval_assurance text,
  report_id uuid,
  report_extractor_version text,
  report_recorded_at timestamptz,
  admission_problem text
)
language sql
stable
set search_path = ''
as $$
  select d.id, d.source_id, d.document_id, d.document_version, d.approval_assurance::text, r.id,
         r.extractor_version, r.recorded_at,
         case when d.approval_assurance = 'verified' then private.knowledge_integrity_admission_problem(d.id)
              else 'not_verified_assurance' end
    from public.knowledge_documents d
    left join lateral (select (private.knowledge_integrity_current_report(d.id)).*) r on true
   where d.status = 'approved'
   order by d.source_id, d.document_id, d.document_version, d.id;
$$;
revoke all on function private.knowledge_integrity_admission_inventory() from public, anon, authenticated, service_role;
