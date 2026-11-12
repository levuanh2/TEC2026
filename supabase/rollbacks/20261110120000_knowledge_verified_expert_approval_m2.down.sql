-- Rollback for migrations/20261110120000_knowledge_verified_expert_approval_m2.sql (RAG V1.5 M2).
-- Not in migrations/: run by hand, in ONE transaction, then
--   set local knowledge.m2_rollback_evidence_exported = 'yes';   -- after exporting the evidence
--   supabase migration repair --status reverted 20261110120000
--
-- Refuses while any document version is in expert_review (its review evidence would be dropped
-- while the version is mid-decision). Restores the M1 trigger functions and the M1 operator
-- functions verbatim (copied from 20261110090100): SECURITY DOWNGRADE, approvals become operator
-- transitions with a STATED approver again. Drops the M2 RPCs, helpers, registry and evidence tables.
-- DROPPING THE TABLES DELETES THE REVIEW AND APPROVAL EVIDENCE: export them first (copy
-- public.knowledge_registry_admins, knowledge_personnel, knowledge_personnel_roles,
-- knowledge_upload_attestations, knowledge_expert_reviews, knowledge_approval_records to files).
-- The M1 event log is kept (its rows of M2 decisions stay as history).
begin;

do $$
begin
  if coalesce(current_setting('knowledge.m2_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'M2 rollback refused: it DROPS the review/approval evidence and the registry. Export them, then'
      ' run: set local knowledge.m2_rollback_evidence_exported = ''yes'';';
  end if;
  if exists (select 1 from public.knowledge_documents where status = 'expert_review') then
    raise exception 'M2 rollback refused: document versions are in expert_review; let the reviewer decide or reject them first';
  end if;
end;
$$;

drop function if exists public.knowledge_register_personnel(uuid, text, text, text, text, uuid);
drop function if exists public.knowledge_grant_personnel_role(uuid, text, text, uuid, text, text, text, timestamptz);
drop function if exists public.knowledge_set_personnel_status(uuid, text, text);
drop function if exists public.knowledge_set_personnel_role_status(uuid, text, text);
drop function if exists public.knowledge_attest_document_upload(uuid, text, text, text);
drop function if exists public.knowledge_attest_source_upload(text, text);
drop function if exists public.knowledge_start_expert_review(uuid, text, text);
drop function if exists public.knowledge_submit_expert_review(uuid, text, text, jsonb, jsonb, jsonb, text);
drop function if exists public.knowledge_decide_document(uuid, text, text, text);
drop function if exists public.knowledge_approve_source(text, text, text);
drop function if exists public.knowledge_review_snapshot(uuid, text);
drop function if exists public.knowledge_cancel_expert_review(uuid, text);
drop function if exists private.knowledge_demo_quarantine_all(text);
drop function if exists private.knowledge_demo_approve_source(text, uuid, text);
drop function if exists private.knowledge_demo_approve_document(uuid, uuid, text);
drop table if exists private.knowledge_demo_mode;
drop function if exists private.knowledge_demo_require_enabled();
drop function if exists private.knowledge_demo_reason(text);
drop function if exists private.knowledge_demo_mode_stamp();

create or replace function private.enforce_knowledge_source_scope()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.approved_at is not null then
      raise exception 'knowledge source % was approved and cannot be deleted (archive it)', old.source_id
        using errcode = '23514';
    end if;
    return old;
  end if;
  -- D2 first: a status change outside a controlled transition is refused as such, whatever else
  -- the statement does.
  if tg_op = 'UPDATE' and new.status <> old.status
     and not private.knowledge_status_transition_authorized('source', old.source_id, new.status) then
    raise exception 'knowledge source %: status % -> % must go through private.knowledge_transition_source'
      ' (a direct status update is refused)', old.source_id, old.status, new.status using errcode = '42501';
  end if;
  if new.status in ('review_required', 'rejected') and (new.approved_by is not null or new.approved_at is not null) then
    raise exception 'knowledge source %: an approval record requires status approved', new.source_id
      using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'review_required' then
      raise exception 'knowledge source %: a new source starts review_required; every later status is a'
        ' controlled transition (private.knowledge_transition_source)', new.source_id using errcode = '23514';
    end if;
    if new.farm_id is not null and not exists (
        select 1 from public.farms f where f.id = new.farm_id and f.cooperative_id = new.organization_id) then
      raise exception 'knowledge source %: farm % does not belong to organization %',
        new.source_id, new.farm_id, new.organization_id using errcode = '23514';
    end if;
    return new;
  end if;
  if (new.source_id, new.visibility, new.organization_id, new.farm_id, new.created_at)
      is distinct from (old.source_id, old.visibility, old.organization_id, old.farm_id, old.created_at) then
    raise exception 'knowledge source % scope is immutable', old.source_id using errcode = '23514';
  end if;
  if new.status <> old.status then
    if not private.knowledge_status_transition_allowed('source', old.status, new.status) then
      raise exception 'knowledge source %: status % -> % is not allowed', old.source_id, old.status, new.status
        using errcode = '23514';
    end if;
  end if;
  if old.approved_at is not null
     and (new.title, new.owner, new.source_type, new.authority, new.approved_by, new.approved_at, new.review_note)
         is distinct from
         (old.title, old.owner, old.source_type, old.authority, old.approved_by, old.approved_at, old.review_note) then
    raise exception 'knowledge source % was approved; its provenance and approval record are immutable',
      old.source_id using errcode = '23514';
  end if;
  return new;
end;
$$;

create or replace function private.enforce_knowledge_document_immutability()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.approved_at is not null then
      raise exception 'knowledge document % % % was approved and cannot be deleted',
        old.source_id, old.document_id, old.document_version using errcode = '23514';
    end if;
    return old;
  end if;
  -- D2 first: a status change outside a controlled transition is refused as such, whatever else
  -- the statement does.
  if tg_op = 'UPDATE' and new.status <> old.status
     and not private.knowledge_status_transition_authorized('document', old.id::text, new.status) then
    raise exception 'knowledge document % % %: status % -> % must go through private.knowledge_transition_document'
      ' (a direct status update is refused)',
      old.source_id, old.document_id, old.document_version, old.status, new.status using errcode = '42501';
  end if;
  if new.status in ('review_required', 'rejected', 'expert_review')
     and (new.approved_by is not null or new.approved_at is not null) then
    raise exception 'knowledge document % % %: an approval record requires status approved',
      new.source_id, new.document_id, new.document_version using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'review_required' then
      raise exception 'knowledge document % % %: a new version starts review_required; every later status is'
        ' a controlled transition (private.knowledge_transition_document)',
        new.source_id, new.document_id, new.document_version using errcode = '23514';
    end if;
    return new;
  end if;
  if (new.id, new.source_id, new.document_id, new.document_version, new.file_sha256, new.normalized_sha256,
      new.parser_version, new.normalizer_version, new.chunker_version, new.imported_at)
      is distinct from
     (old.id, old.source_id, old.document_id, old.document_version, old.file_sha256, old.normalized_sha256,
      old.parser_version, old.normalizer_version, old.chunker_version, old.imported_at) then
    raise exception 'knowledge document % % % identity/provenance is immutable',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  if new.status <> old.status then
    if not private.knowledge_status_transition_allowed('document', old.status, new.status) then
      raise exception 'knowledge document % % %: status % -> % is not allowed',
        old.source_id, old.document_id, old.document_version, old.status, new.status using errcode = '23514';
    end if;
  end if;
  if old.approved_at is not null
     and (new.title, new.language, new.official_url, new.artifact_ref, new.published_at, new.license_basis,
          new.license_reference, new.approved_by, new.approved_at, new.review_note)
         is distinct from
         (old.title, old.language, old.official_url, old.artifact_ref, old.published_at, old.license_basis,
          old.license_reference, old.approved_by, old.approved_at, old.review_note) then
    raise exception 'knowledge document % % % was approved; its provenance and approval record are immutable',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  return new;
end;
$$;

create or replace function private.knowledge_transition_source(
  p_source_id text,
  p_from public.knowledge_status,
  p_to public.knowledge_status,
  p_reason text,
  p_approved_by uuid default null)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_status public.knowledge_status;
  v_event bigint;
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'knowledge source %: a transition needs a reason (1-2000 characters)', p_source_id
      using errcode = '22023';
  end if;
  if not private.knowledge_status_transition_allowed('source', p_from, p_to) then
    raise exception 'knowledge source %: status % -> % is not allowed', p_source_id, p_from, p_to
      using errcode = '23514';
  end if;
  if (p_to = 'approved') <> (p_approved_by is not null) then
    raise exception 'knowledge source %: an approver is named exactly for an approval', p_source_id
      using errcode = '22023';
  end if;
  select s.status into v_status from public.knowledge_sources s where s.source_id = p_source_id for update;
  if not found then
    raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
  end if;
  if v_status <> p_from then
    raise exception 'knowledge source %: status is %, not % (changed concurrently or a stale request)',
      p_source_id, v_status, p_from using errcode = '23514';
  end if;
  perform pg_catalog.set_config('knowledge.status_transition', 'source|' || p_source_id || '|' || p_to::text, true);
  if p_to = 'approved' then
    update public.knowledge_sources
       set status = p_to, approved_by = p_approved_by, approved_at = now(), review_note = p_reason
     where source_id = p_source_id;
  else
    update public.knowledge_sources set status = p_to where source_id = p_source_id;
  end if;
  perform pg_catalog.set_config('knowledge.status_transition', '', true);
  insert into public.knowledge_status_events
    (entity_type, source_id, from_status, to_status, reason, stated_approver, actor_session_user, actor_role)
  values ('source', p_source_id, p_from, p_to, p_reason, p_approved_by, session_user,
          coalesce(nullif(current_setting('role', true), 'none'), session_user))
  returning id into v_event;
  return v_event;
end;
$$;

create or replace function private.knowledge_transition_document(
  p_document_pk uuid,
  p_from public.knowledge_status,
  p_to public.knowledge_status,
  p_reason text,
  p_approved_by uuid default null)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_doc record;
  v_event bigint;
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'knowledge document %: a transition needs a reason (1-2000 characters)', p_document_pk
      using errcode = '22023';
  end if;
  if not private.knowledge_status_transition_allowed('document', p_from, p_to) then
    raise exception 'knowledge document %: status % -> % is not allowed', p_document_pk, p_from, p_to
      using errcode = '23514';
  end if;
  if (p_to = 'approved') <> (p_approved_by is not null) then
    raise exception 'knowledge document %: an approver is named exactly for an approval', p_document_pk
      using errcode = '22023';
  end if;
  select d.status, d.source_id, d.document_id, d.document_version into v_doc
    from public.knowledge_documents d where d.id = p_document_pk for update;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  if v_doc.status <> p_from then
    raise exception 'knowledge document %: status is %, not % (changed concurrently or a stale request)',
      p_document_pk, v_doc.status, p_from using errcode = '23514';
  end if;
  perform pg_catalog.set_config('knowledge.status_transition',
                                'document|' || p_document_pk::text || '|' || p_to::text, true);
  if p_to = 'approved' then
    update public.knowledge_documents
       set status = p_to, approved_by = p_approved_by, approved_at = now(), review_note = p_reason
     where id = p_document_pk;
  else
    update public.knowledge_documents set status = p_to where id = p_document_pk;
  end if;
  perform pg_catalog.set_config('knowledge.status_transition', '', true);
  insert into public.knowledge_status_events
    (entity_type, source_id, document_pk, document_id, document_version, from_status, to_status, reason,
     stated_approver, actor_session_user, actor_role)
  values ('document', v_doc.source_id, p_document_pk, v_doc.document_id, v_doc.document_version, p_from, p_to,
          p_reason, p_approved_by, session_user, coalesce(nullif(current_setting('role', true), 'none'), session_user))
  returning id into v_event;
  return v_event;
end;
$$;

revoke all on function private.knowledge_transition_source(text, public.knowledge_status, public.knowledge_status,
  text, uuid) from public, anon, authenticated;
grant execute on function private.knowledge_transition_source(text, public.knowledge_status,
  public.knowledge_status, text, uuid) to service_role;
revoke all on function private.knowledge_transition_document(uuid, public.knowledge_status, public.knowledge_status,
  text, uuid) from public, anon, authenticated;
grant execute on function private.knowledge_transition_document(uuid, public.knowledge_status,
  public.knowledge_status, text, uuid) to service_role;

drop table public.knowledge_approval_records;
drop table public.knowledge_expert_reviews;
drop table public.knowledge_upload_attestations;
drop table public.knowledge_personnel_roles;
drop table public.knowledge_personnel;
drop table public.knowledge_registry_admins;
drop function private.knowledge_identity_key(text);

drop function private.knowledge_apply_document_transition(uuid, public.knowledge_status, public.knowledge_status, text, uuid);
drop function private.knowledge_apply_source_transition(text, public.knowledge_status, public.knowledge_status, text, uuid);
drop function private.knowledge_check_review_evidence(text, jsonb, jsonb, jsonb, text);
drop function private.knowledge_snapshot_sha256(jsonb);
drop function private.knowledge_source_snapshot(text);
drop function private.knowledge_document_snapshot(uuid);
drop function private.knowledge_registry_admin_actor();
drop function private.knowledge_person_identity(uuid);
-- (dropped after the personnel table, whose index and CHECK use it)
drop function private.knowledge_actor_role(uuid, text, text, uuid);
drop function private.knowledge_verified_actor();
drop function private.knowledge_personnel_guard();
drop function private.knowledge_registry_admin_guard();
drop function private.knowledge_evidence_guard();
drop function private.knowledge_m2_set_marker(text);
drop function private.knowledge_m2_no_truncate();
drop function private.knowledge_m2_write_authorized(text);

commit;
