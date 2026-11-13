-- Rollback for migrations/20261113120000_knowledge_m2_hardening_operator.sql (RAG V1.5 H-b).
-- Not in migrations/: run by hand, in ONE transaction, after any H-c rollback and BEFORE the H-a
-- rollback, then
--   supabase migration repair --status reverted 20261113120000
--
-- Restores the exact M2 bodies of private.knowledge_transition_source / _document (service_role can
-- quarantine AND archive again through them, with a free-text reason only) and of
-- public.knowledge_review_snapshot. It DROPS the emergency and archive evidence, so it REFUSES unless
--   * set local knowledge.hb_rollback_evidence_exported = 'yes' (export both tables first), and
--   * H-c is not installed.
-- `archivist` role rows cannot be deleted (registry rows are permanent): if any exist, the widened
-- role CHECK is kept (no function reads the role after the rollback); otherwise it is restored.

begin;

do $$
begin
  if coalesce(current_setting('knowledge.hb_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'H-b rollback DROPS the emergency quarantine and archive evidence: export'
      ' public.knowledge_emergency_actions and public.knowledge_archive_records, then'
      ' set local knowledge.hb_rollback_evidence_exported = ''yes''';
  end if;
  if to_regclass('public.knowledge_supersession_authorizations') is not null then
    raise exception 'H-b rollback refused: H-c is installed; roll it back first';
  end if;
end;
$$;

drop function public.knowledge_archive_document(uuid, text, text, text);
drop function public.knowledge_archive_source(text, text, text, text);
drop function private.knowledge_same_person(uuid, uuid[]);
drop function private.knowledge_archive_check(text, text, text);
drop function private.knowledge_emergency_quarantine_document(uuid, text, text, text);
drop function private.knowledge_emergency_quarantine_source(text, text, text, text);
drop function private.knowledge_emergency_check(text, text, text);
drop table public.knowledge_archive_records;
drop table public.knowledge_emergency_actions;

do $$
begin
  if not exists (select 1 from public.knowledge_personnel_roles where role = 'archivist') then
    alter table public.knowledge_personnel_roles drop constraint knowledge_personnel_roles_role_chk;
    alter table public.knowledge_personnel_roles add constraint knowledge_personnel_roles_role_chk
      check (role in ('uploader', 'expert_reviewer', 'approver'));
  else
    raise notice 'H-b rollback: archivist role rows exist; the widened role CHECK is kept';
  end if;
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
  if p_to = 'approved' then
    -- a stale or unknown request is reported as in M1, before the M2 refusal
    select s.status into v_status from public.knowledge_sources s where s.source_id = p_source_id;
    if not found then
      raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
    end if;
    if v_status <> p_from then
      raise exception 'knowledge source %: status is %, not % (changed concurrently or a stale request)',
        p_source_id, v_status, p_from using errcode = '23514';
    end if;
    raise exception 'knowledge source %: approval is a verified human decision (M2): the approver calls'
      ' public.knowledge_approve_source with an aal2 session; operator and owner logins cannot approve',
      p_source_id using errcode = '42501';
  end if;
  return private.knowledge_apply_source_transition(p_source_id, p_from, p_to, p_reason, p_approved_by);
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
  v_status public.knowledge_status;
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
  if p_to in ('expert_review', 'approved') or (p_from = 'expert_review' and p_to = 'review_required') then
    select d.status into v_status from public.knowledge_documents d where d.id = p_document_pk;
    if not found then
      raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
    end if;
    if v_status <> p_from then
      raise exception 'knowledge document %: status is %, not % (changed concurrently or a stale request)',
        p_document_pk, v_status, p_from using errcode = '23514';
    end if;
    raise exception 'knowledge document %: % -> % is a verified human decision (M2): use'
      ' public.knowledge_start_expert_review / knowledge_submit_expert_review / knowledge_decide_document'
      ' with an aal2 session; operator and owner logins cannot review or approve', p_document_pk, p_from, p_to
      using errcode = '42501';
  end if;
  return private.knowledge_apply_document_transition(p_document_pk, p_from, p_to, p_reason, p_approved_by);
end;
$$;

create or replace function public.knowledge_review_snapshot(p_document_pk uuid default null, p_source_id text default null)
returns table (snapshot jsonb, snapshot_sha256 text)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_src record;
  v_snap jsonb;
begin
  select a.user_id into v_actor from private.knowledge_verified_actor() a;
  if (p_document_pk is null) = (p_source_id is null) then
    raise exception 'name exactly one of a document version or a source' using errcode = '22023';
  end if;
  select s.visibility, s.organization_id into v_src from public.knowledge_sources s
   where s.source_id = coalesce(p_source_id, (select d.source_id from public.knowledge_documents d where d.id = p_document_pk));
  if not found or not exists (
      select 1 from unnest(array['uploader', 'expert_reviewer', 'approver']) r(role)
       where (private.knowledge_actor_role(v_actor.user_id, r.role, v_src.visibility, v_src.organization_id)).role_id is not null) then
    raise exception 'not available for your knowledge role' using errcode = '42501';
  end if;
  v_snap := case when p_document_pk is not null then private.knowledge_document_snapshot(p_document_pk)
                 else private.knowledge_source_snapshot(p_source_id) end;
  if v_snap is null then
    raise exception 'not available for your knowledge role' using errcode = '42501';
  end if;
  return query select v_snap, private.knowledge_snapshot_sha256(v_snap);
end;
$$;

commit;
