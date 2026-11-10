-- RAG V1.5 M1 (docs/rag/RAG_V15_SOURCE_CONTENT_INTEGRITY.md §3, §6), part 2 of 2: controlled,
-- audited status transitions for knowledge sources and document versions. LOCAL/CI ONLY until the
-- owner approves a hosted migration. dev3-01 stays OPEN: this makes quarantine possible and every
-- decision auditable. It does not judge content.
--
-- Owner decisions (2026-11-10):
--   D1  quarantine is one-way: approved -> quarantined -> archived. Never quarantined -> approved.
--       A corrected or revalidated text is a NEW document_version through the full flow. The old
--       version keeps its approval record unchanged (it is evidence of what was approved and when).
--   D2  every status change is an explicit, audited transition: an append-only
--       public.knowledge_status_events row is written in the same transaction as the status
--       change, by private.knowledge_transition_source / private.knowledge_transition_document.
--       A direct UPDATE of `status` is refused, and an INSERT starts at review_required.
--   D3  document versions pass expert_review: review_required -> expert_review -> approved.
--       review_required -> approved is refused. Sources keep their own flow (no expert_review).
--       Passing expert_review records that the stage was completed. It does NOT prove that a
--       qualified expert approved the content: evidence records and distinct
--       uploader/reviewer/approver checks are M2.
--
-- Transition matrix (private.knowledge_status_transition_allowed; enforced in the functions AND in
-- the row triggers):
--   document  review_required -> expert_review | rejected
--             rejected        -> review_required                (re-review after a correction note)
--             expert_review   -> approved | rejected | review_required
--             approved        -> quarantined | archived
--             quarantined     -> archived
--             archived        terminal
--   source    review_required <-> rejected; review_required | rejected -> approved   (unchanged)
--             approved        -> quarantined | archived
--             quarantined     -> archived
--             archived        terminal
-- Replacing an approved version: in ONE transaction, archive (or quarantine) the old version,
-- then approve the new one (knowledge_documents_one_approved allows one approved version).
--
-- Authorization model:
--   * `authenticated` and `anon` get nothing new: no EXECUTE on the transition functions, no
--     privilege on the event table. They keep SELECT on the knowledge tables under the unchanged
--     approved-only RLS.
--   * The transition functions are SECURITY DEFINER (static SQL, pinned search_path), EXECUTE
--     only for service_role. The database owner can call them too.
--   * A status change passes the row trigger only when BOTH hold:
--       (a) current_user is the owner of public.knowledge_status_events. That is true inside the
--           definer functions; service_role or authenticated can never be that role, so a GUC
--           they set themselves does not help;
--       (b) the transaction-local setting `knowledge.status_transition` names exactly this row
--           and this target status. The function sets it right before its UPDATE and clears it
--           right after.
--     RESIDUAL (documented, M2): a session that IS the owner (the `postgres` role the operator CLI
--     connects as) could deliberately forge (b), just as it could DISABLE TRIGGER or drop this
--     migration's objects. Ordinary direct UPDATEs by that role are refused like everyone
--     else's. A dedicated non-owner operator role is M2.
--   * Actor attribution records only what the database itself verified: session_user (the login
--     role) and the effective caller role. Human identity is NOT verified in M1: operators share
--     the `postgres` / service_role logins. `stated_approver` is the approver the caller named
--     for an approval (it also fills approved_by, which the approval CHECK requires). It is
--     recorded as stated, not verified.
--   * Event privacy: RLS on, no policy, no grant to anon/authenticated. Only service_role
--     (SELECT) and the owner can read events, so no tenant ever sees another tenant's or any
--     operator's history.
--
-- Chunks: content is frozen from expert_review on. A chunk can only be deleted while its version
-- is review_required or rejected and was never approved. Before M1, "never approved" was enough,
-- which would have let an expert_review version's content change under review.
--
-- Unchanged: retrieval (RLS + match_knowledge_chunks_lexical stay approved-only on document AND
-- source, so expert_review and quarantined are excluded fail-closed), the approval CHECKs, ST1
-- and ST1.1 artifact rules, one approved version per document, immutable identity/provenance,
-- the frozen approval record, chunk inserts, tenant scope, and review_required ingestion. Existing
-- rows are not touched and no history is invented: there is no backfilled event and no
-- fabricated expert_review.

-- ------------------------------------------------------------------ transition matrix

create function private.knowledge_status_transition_allowed(
  p_entity text, p_from public.knowledge_status, p_to public.knowledge_status)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select case p_entity
    when 'document' then (p_from::text || '>' || p_to::text) = any (array[
      'review_required>expert_review', 'review_required>rejected',
      'rejected>review_required',
      'expert_review>approved', 'expert_review>rejected', 'expert_review>review_required',
      'approved>quarantined', 'approved>archived',
      'quarantined>archived'])
    when 'source' then (p_from::text || '>' || p_to::text) = any (array[
      'review_required>rejected', 'rejected>review_required',
      'review_required>approved', 'rejected>approved',
      'approved>quarantined', 'approved>archived',
      'quarantined>archived'])
    else false
  end;
$$;
revoke all on function private.knowledge_status_transition_allowed(text, public.knowledge_status,
  public.knowledge_status) from public, anon, authenticated;
grant execute on function private.knowledge_status_transition_allowed(text, public.knowledge_status,
  public.knowledge_status) to service_role;

-- ------------------------------------------------------------------ append-only event log

create table public.knowledge_status_events (
  id bigint generated always as identity primary key,
  entity_type text not null,
  source_id text not null,
  document_pk uuid,
  document_id text,
  document_version text,
  from_status public.knowledge_status not null,
  to_status public.knowledge_status not null,
  reason text not null,
  -- The approver the caller named for an approval transition. NOT verified in M1 (see header).
  stated_approver uuid,
  -- What the database verified about the caller: the login role and the effective role.
  actor_session_user text not null,
  actor_role text not null,
  transaction_id xid8 not null default pg_catalog.pg_current_xact_id(),
  occurred_at timestamptz not null default now(),
  constraint knowledge_status_events_entity_chk check (
    (entity_type = 'source' and document_pk is null and document_id is null and document_version is null)
    or (entity_type = 'document' and document_pk is not null and document_id is not null
        and document_version is not null)),
  constraint knowledge_status_events_change_chk check (from_status <> to_status),
  constraint knowledge_status_events_reason_chk check (btrim(reason) <> '' and length(reason) <= 2000),
  constraint knowledge_status_events_approver_chk check (
    (to_status = 'approved') = (stated_approver is not null))
);
-- No foreign key: the log is history and must outlive a never-approved draft that is deleted.
create index knowledge_status_events_source_idx on public.knowledge_status_events (source_id, id);
create index knowledge_status_events_document_idx on public.knowledge_status_events (document_pk, id)
  where document_pk is not null;

alter table public.knowledge_status_events enable row level security;
-- No policy: clients read nothing. Writes only through the definer transition functions.
revoke all on public.knowledge_status_events from public, anon, authenticated, service_role;
grant select on public.knowledge_status_events to service_role;

create function private.knowledge_status_events_append_only()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'knowledge_status_events is append-only: % is refused', tg_op using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_status_events_append_only() from public, anon, authenticated;

create trigger knowledge_status_events_append_only
  before update or delete on public.knowledge_status_events
  for each row execute function private.knowledge_status_events_append_only();
create trigger knowledge_status_events_no_truncate
  before truncate on public.knowledge_status_events
  for each statement execute function private.knowledge_status_events_append_only();

-- ------------------------------------------------------------------ transition authorization

-- True only inside a controlled transition of exactly this row to exactly this status, see the
-- header: (a) the caller is the event log's owner (the definer function), (b) the marker matches.
create function private.knowledge_status_transition_authorized(
  p_entity text, p_key text, p_to public.knowledge_status)
returns boolean
language sql
stable
set search_path = ''
as $$
  select current_user = (select r.rolname from pg_catalog.pg_class c
                         join pg_catalog.pg_roles r on r.oid = c.relowner
                         where c.oid = 'public.knowledge_status_events'::pg_catalog.regclass)
     and coalesce(current_setting('knowledge.status_transition', true), '')
         = p_entity || '|' || p_key || '|' || p_to::text;
$$;
revoke all on function private.knowledge_status_transition_authorized(text, text, public.knowledge_status)
  from public, anon, authenticated;
-- service_role reaches the row trigger on a direct UPDATE. EXECUTE on this check lets the trigger
-- refuse it with its own message instead of a missing-privilege error. It grants no write.
grant execute on function private.knowledge_status_transition_authorized(text, text, public.knowledge_status)
  to service_role;

-- ------------------------------------------------------------------ row triggers (replaced)

-- Same as 20261005090000 except: an INSERT starts review_required (D2); a status change must be a
-- controlled transition (D2) along the matrix above (D1); quarantined -> archived is allowed. Scope,
-- provenance and the frozen approval record are unchanged.
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

-- Same as 20261005090000 except: an INSERT starts review_required (D2); expert_review carries no
-- approval record; a status change must be a controlled transition (D2) along the matrix above
-- (D1, D3). Identity, provenance and the frozen approval record are unchanged.
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

-- Chunks (replaced): same as 20261005090000 except that a DELETE is allowed only while the version
-- is a draft (review_required or rejected) and was never approved. Before M1 "never approved" was
-- enough. With expert_review, the content an expert is reviewing must be exactly the content that
-- gets approved, so it is frozen from the moment the version enters expert_review. An INSERT already
-- needed review_required (unchanged). The parent row is share-locked as before, so a delete waits
-- for a transition in flight and then re-checks.
create or replace function private.enforce_knowledge_chunk_immutability()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if not exists (select 1 from public.knowledge_documents d
                   where d.id = new.document_pk and d.status = 'review_required' and d.approved_at is null
                   for share) then
      raise exception 'knowledge chunk %: its version is not open for ingestion (only a never-approved'
        ' review_required version accepts chunks)', new.chunk_id using errcode = '23514';
    end if;
    return new;
  end if;
  if tg_op = 'UPDATE' then
    raise exception 'knowledge chunk % is immutable', old.chunk_id using errcode = '23514';
  end if;
  if not exists (select 1 from public.knowledge_documents d
                 where d.id = old.document_pk and d.approved_at is null
                   and d.status in ('review_required', 'rejected')
                 for share) then
    raise exception 'knowledge chunk % belongs to a version under expert review or approved and cannot be deleted',
      old.chunk_id using errcode = '23514';
  end if;
  return old;
end;
$$;

-- ------------------------------------------------------------------ controlled transitions

-- One explicit transition of one source. p_from is the status the caller expects: if the row was
-- changed concurrently, the call fails, nothing changes and no event is written. The row lock
-- serializes concurrent transitions of the same source. Returns the event id. An approval sets
-- approved_by = p_approved_by (stated, see header), approved_at = now() and review_note = p_reason.
-- Every other transition must not name an approver.
create function private.knowledge_transition_source(
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
revoke all on function private.knowledge_transition_source(text, public.knowledge_status, public.knowledge_status,
  text, uuid) from public, anon, authenticated;
grant execute on function private.knowledge_transition_source(text, public.knowledge_status,
  public.knowledge_status, text, uuid) to service_role;

-- One explicit transition of one document version (by its primary key), same contract as above.
-- The approval CHECKs (approver, time, note, known license, ST1 artifact, ST1.1 SHA binding) and the
-- one-approved-version index are checked by the UPDATE itself, so a refused approval writes no event.
create function private.knowledge_transition_document(
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
revoke all on function private.knowledge_transition_document(uuid, public.knowledge_status, public.knowledge_status,
  text, uuid) from public, anon, authenticated;
grant execute on function private.knowledge_transition_document(uuid, public.knowledge_status,
  public.knowledge_status, text, uuid) to service_role;
