-- Rollback for migrations/20261113210000_knowledge_integrity_approval_gate_m7_e2.sql (RAG V1.5 M7 E2).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE any M6.1 / H-c / H-b / H-a rollback, then
--   supabase migration repair --status reverted 20261113210000
-- Restores M3's exact public.knowledge_submit_expert_review and public.knowledge_decide_document: approval
-- is then NO LONGER bound to the integrity report (E2 reopens). It DROPS the reports, findings and
-- dispositions, so it refuses without
--   set local knowledge.e2_rollback_confirmed = 'yes'   (export the three tables first)

begin;

do $$
begin
  if coalesce(current_setting('knowledge.e2_rollback_confirmed', true), '') <> 'yes' then
    raise exception 'E2 rollback reopens E2 (approval no longer bound to the integrity report) and DROPS the integrity'
      ' evidence: export it, then set local knowledge.e2_rollback_confirmed = ''yes''';
  end if;
end;
$$;

create or replace function public.knowledge_submit_expert_review(
  p_review_id uuid, p_decision text, p_snapshot_sha256 text, p_checklist jsonb, p_sources_checked jsonb,
  p_findings jsonb, p_rationale text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_rev record;
  v_doc record;
  v_role record;
  v_event bigint;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  select r.* into v_rev from public.knowledge_expert_reviews r where r.id = p_review_id;
  if not found or v_rev.reviewer_user_id <> v_actor.user_id then
    raise exception 'review not available: only the reviewer who started it records its decision' using errcode = '42501';
  end if;
  select d.status, s.visibility, s.organization_id into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = v_rev.document_pk for update of d;
  -- the reviewer must still be active and qualified for this scope
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'expert_reviewer', v_doc.visibility,
                                                         v_doc.organization_id);
  if v_role.role_id is null or v_role.role_id <> v_rev.reviewer_role_id then
    raise exception 'separation of duties: your expert_reviewer role for this scope is no longer active'
      using errcode = '42501';
  end if;
  if v_rev.decision is not null then
    raise exception 'review %: its decision is already recorded (evidence is immutable)', p_review_id
      using errcode = '23514';
  end if;
  if v_doc.status <> 'expert_review' or exists (
      select 1 from public.knowledge_expert_reviews r2
       where r2.document_pk = v_rev.document_pk and r2.seq > v_rev.seq) then
    raise exception 'review %: the version is no longer under this review', p_review_id using errcode = '23514';
  end if;
  perform private.knowledge_check_review_evidence(p_decision, p_checklist, p_sources_checked, p_findings, p_rationale);
  -- M3: a recommendation to approve a version that supersedes a version of ANOTHER source is complete only
  -- with an approved replacing source and the recorded authority. Checked here, where the reviewer can
  -- still fix it, and again by the approval (defense in depth).
  if p_decision = 'recommend_approval' then
    perform private.knowledge_check_cross_source_supersession(v_rev.document_pk, p_sources_checked);
  end if;
  if p_snapshot_sha256 is distinct from v_rev.snapshot_sha256
     or private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(v_rev.document_pk)) <> v_rev.snapshot_sha256 then
    raise exception 'review %: the reviewed content or metadata changed since the review started (evidence invalid)',
      p_review_id using errcode = '23514';
  end if;
  if p_decision = 'reject' then
    v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review', 'rejected', p_rationale, null);
  elsif p_decision = 'return' then
    v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review', 'review_required',
                                                           p_rationale, null);
  end if;
  perform private.knowledge_m2_set_marker('knowledge_expert_reviews.decision');
  update public.knowledge_expert_reviews
     set decision = p_decision, checklist = p_checklist, sources_checked = p_sources_checked, findings = p_findings,
         rationale = p_rationale, decided_at = pg_catalog.now(), decision_session_id = v_actor.session_id,
         decision_event_id = v_event
   where id = p_review_id;
  perform private.knowledge_m2_set_marker(null);
  return p_review_id;
end;
$$;

create or replace function public.knowledge_decide_document(
  p_review_id uuid, p_decision text, p_snapshot_sha256 text, p_rationale text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_rev record;
  v_doc record;
  v_role record;
  v_reviewer record;
  v_att record;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  if p_decision is null or p_decision not in ('approve', 'reject') then
    raise exception 'approval decision must be approve or reject' using errcode = '22023';
  end if;
  if p_rationale is null or btrim(p_rationale) = '' or length(p_rationale) > 2000 then
    raise exception 'an approval decision needs a rationale (1-2000 characters)' using errcode = '22023';
  end if;
  select r.* into v_rev from public.knowledge_expert_reviews r where r.id = p_review_id;
  select d.id, d.status, s.visibility, s.organization_id into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = v_rev.document_pk for update of d;
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'approver', v_doc.visibility,
                                                         v_doc.organization_id);
  if v_rev.id is null or v_role.role_id is null then
    raise exception 'review not available for your knowledge role (approver)' using errcode = '42501';
  end if;
  select a.id, a.uploader_personnel_id, a.uploader_user_id into v_att
    from public.knowledge_upload_attestations a where a.id = v_rev.upload_attestation_id;
  if v_role.personnel_id in (v_rev.reviewer_personnel_id, v_att.uploader_personnel_id)
     or v_actor.user_id in (v_rev.reviewer_user_id, v_att.uploader_user_id)
     or v_role.identity_reference in (private.knowledge_person_identity(v_rev.reviewer_personnel_id),
                                      private.knowledge_person_identity(v_att.uploader_personnel_id)) then
    raise exception 'separation of duties: the approver must be a different person from the uploader and the reviewer'
      using errcode = '42501';
  end if;
  if v_doc.status <> 'expert_review' or exists (
      select 1 from public.knowledge_expert_reviews r2
       where r2.document_pk = v_rev.document_pk and r2.seq > v_rev.seq) then
    raise exception 'review %: the version is not under this review (it is %)', p_review_id, v_doc.status
      using errcode = '23514';
  end if;
  if v_rev.decision is distinct from 'recommend_approval' then
    raise exception 'review %: the expert has not recommended approval', p_review_id using errcode = '23514';
  end if;
  if exists (select 1 from public.knowledge_approval_records a where a.review_id = p_review_id) then
    raise exception 'review %: already decided', p_review_id using errcode = '23514';
  end if;
  if p_decision = 'approve' then
    -- the reviewer is still active and still holds the role used (suspension or revocation in between refuses)
    select 1 as ok into v_reviewer
      from public.knowledge_personnel p join public.knowledge_personnel_roles r on r.personnel_id = p.id
     where p.id = v_rev.reviewer_personnel_id and r.id = v_rev.reviewer_role_id and p.status = 'active'
       and r.status = 'active' and r.valid_from <= pg_catalog.now()
       and (r.valid_until is null or r.valid_until > pg_catalog.now())
     for share of p, r;
    if v_reviewer.ok is null then
      raise exception 'review %: the expert reviewer is no longer active and qualified', p_review_id
        using errcode = '42501';
    end if;
    -- evidence is re-validated: complete, no open blocking finding
    perform private.knowledge_check_review_evidence(v_rev.decision, v_rev.checklist, v_rev.sources_checked,
                                                    v_rev.findings, v_rev.rationale);
    -- M3: replacing a version of ANOTHER source needs an approved source and the reviewer's recorded authority
    perform private.knowledge_check_cross_source_supersession(v_rev.document_pk, v_rev.sources_checked);
  end if;
  v_snap := private.knowledge_document_snapshot(v_rev.document_pk);
  if p_snapshot_sha256 is distinct from v_rev.snapshot_sha256
     or private.knowledge_snapshot_sha256(v_snap) <> v_rev.snapshot_sha256 then
    if p_decision = 'approve' then
      raise exception 'review %: the version or its source changed since the review (evidence invalid; approval refused)',
        p_review_id using errcode = '23514';
    end if;
  end if;
  -- the record first (the row trigger requires it for an approval), then the audited transition
  perform private.knowledge_m2_set_marker('knowledge_approval_records');
  insert into public.knowledge_approval_records (id, entity_type, source_id, document_pk, review_id,
    upload_attestation_id, decision, approver_personnel_id, approver_role_id, approver_user_id, approver_session_id,
    snapshot, snapshot_sha256, rationale, status_event_id)
  values (v_id, 'document', v_rev.source_id, v_rev.document_pk, p_review_id, v_att.id, p_decision, v_role.personnel_id,
          v_role.role_id, v_actor.user_id, v_actor.session_id, v_snap, private.knowledge_snapshot_sha256(v_snap),
          p_rationale, 0);
  perform private.knowledge_m2_set_marker(null);
  if p_decision = 'approve' then
    -- M3: the approval of a version archives the approved version it supersedes, in this transaction
    perform private.knowledge_supersede_for(v_rev.document_pk, false);
  end if;
  v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review',
    (case when p_decision = 'approve' then 'approved' else 'rejected' end)::public.knowledge_status,
    p_rationale, case when p_decision = 'approve' then v_actor.user_id end);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

drop function private.knowledge_integrity_gate(uuid, uuid);
drop function public.knowledge_review_integrity_report(uuid);
drop function public.knowledge_dispose_integrity_finding(uuid, text, bigint, text, text, jsonb);
drop function private.knowledge_integrity_report_problem(public.knowledge_integrity_reports);
drop function private.knowledge_integrity_current_report(uuid);
drop function private.knowledge_record_integrity_report(uuid, text, text, text, text, jsonb, jsonb, jsonb);
drop table public.knowledge_integrity_dispositions;
drop table public.knowledge_integrity_findings;
drop table public.knowledge_integrity_reports;
drop function private.knowledge_integrity_finding_blocking(text);
drop function private.knowledge_set_integrity_policy(text, text, text, text);
drop table private.knowledge_integrity_policy;

commit;
