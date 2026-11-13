-- RAG V1.5 M2 hardening H-b (docs/rag/RAG_V15_H_B_EMERGENCY_QUARANTINE_ARCHIVE.md): emergency
-- quarantine with typed, immutable evidence, and permanent archive by an authenticated archivist.
-- LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN.
-- Depends on M1 (20261110090100), M2 (20261110120000), M3 (20261111090000), H-a (20261113090000).
--
-- Owner decisions (2026-11-12): D-H2a a separate `archivist` role; D-H2b the original approver does
-- not archive their own approved version directly (approved -> archived).
--
-- What it changes
--   * approved -> quarantined: ONLY private.knowledge_emergency_quarantine_document / _source
--     (service_role or the owner). Closed reason code, 20-2000 character detail, an operator incident
--     or ticket reference, a snapshot and its hash. The status event and the evidence row are written
--     in the same function call: both or neither.
--   * approved -> archived and quarantined -> archived: ONLY public.knowledge_archive_document /
--     _source, as a verified human (aal2) with an active `archivist` role for the source's scope,
--     confirming the exact snapshot hash. The uploader of that version or source never archives it;
--     its approver never archives it directly from approved. An append-only archive record is
--     written with the transition.
--   * The generic operator functions private.knowledge_transition_document / _source refuse those
--     three transitions (42501) for every caller, service_role and owner alike.
--   * Unchanged: the M3 expiry (its own evidence table), supersession archiving inside
--     public.knowledge_decide_document (part of an independently authorized approval), and the
--     demo go-live brake private.knowledge_demo_quarantine_all (demo rows only; on H-a they exist only
--     on an isolated test database).
--
-- What it does NOT claim
--   * operator_reference is a pointer to a record outside the database (ticket, incident, on-call
--     log). The database cannot verify it names a real human; it makes the action traceable.
--   * There is no break-glass archive: without a qualified archivist nothing is archived, and
--     quarantine already removes the material from retrieval. No owner or service fallback.
--   * The database owner and any superuser can still replace these functions or disable triggers:
--     the infrastructure trust boundary of M1/M2, unchanged.

-- ================================================================== archivist role (D-H2a)

alter table public.knowledge_personnel_roles drop constraint knowledge_personnel_roles_role_chk;
alter table public.knowledge_personnel_roles add constraint knowledge_personnel_roles_role_chk
  check (role in ('uploader', 'expert_reviewer', 'approver', 'archivist'));

-- ================================================================== emergency evidence

create table public.knowledge_emergency_actions (
  id bigint generated always as identity primary key,
  recorded_at timestamptz not null default now(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  entity_type text not null,
  source_id text not null,
  document_pk uuid,
  -- the knowledge_status_events row of the same call; no foreign key, as the M2 evidence tables (the
  -- append-only log keeps its own TRUNCATE refusal)
  status_event_id bigint not null unique,
  reason_code text not null,
  reason_detail text not null,
  operator_reference text not null,
  snapshot jsonb not null,
  snapshot_sha256 text not null,
  db_role text not null,
  session_user_name text not null,
  constraint knowledge_emergency_actions_entity_chk check (
    (entity_type = 'document' and document_pk is not null) or (entity_type = 'source' and document_pk is null)),
  constraint knowledge_emergency_actions_reason_code_chk check (reason_code in (
    'integrity_mismatch', 'provenance_withdrawn', 'rights_withdrawn', 'harmful_content_report',
    'superseding_law', 'demo_go_live', 'operator_error_containment')),
  constraint knowledge_emergency_actions_detail_chk check (length(btrim(reason_detail)) between 20 and 2000),
  constraint knowledge_emergency_actions_reference_chk check (length(btrim(operator_reference)) between 3 and 200),
  constraint knowledge_emergency_actions_sha_chk check (snapshot_sha256 ~ '^[0-9a-f]{64}$')
);
create index knowledge_emergency_actions_document_idx on public.knowledge_emergency_actions (document_pk)
  where document_pk is not null;
create index knowledge_emergency_actions_source_idx on public.knowledge_emergency_actions (source_id);
alter table public.knowledge_emergency_actions enable row level security;
revoke all on public.knowledge_emergency_actions from public, anon, authenticated, service_role;
grant select on public.knowledge_emergency_actions to service_role;
create trigger knowledge_emergency_actions_guard
  before insert or update or delete on public.knowledge_emergency_actions
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_emergency_actions_no_truncate
  before truncate on public.knowledge_emergency_actions
  for each statement execute function private.knowledge_m2_no_truncate();

create table public.knowledge_archive_records (
  id bigint generated always as identity primary key,
  recorded_at timestamptz not null default now(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  entity_type text not null,
  source_id text not null,
  document_pk uuid,
  from_status public.knowledge_status not null,
  -- the knowledge_status_events row of the same call; no foreign key, as the M2 evidence tables (the
  -- append-only log keeps its own TRUNCATE refusal)
  status_event_id bigint not null unique,
  archivist_personnel_id uuid not null references public.knowledge_personnel (id),
  archivist_role_id uuid not null references public.knowledge_personnel_roles (id),
  archivist_user_id uuid not null,
  archivist_session_id uuid not null,
  reason_code text not null,
  rationale text not null,
  snapshot jsonb not null,
  snapshot_sha256 text not null,
  constraint knowledge_archive_records_entity_chk check (
    (entity_type = 'document' and document_pk is not null) or (entity_type = 'source' and document_pk is null)),
  constraint knowledge_archive_records_from_chk check (from_status in ('approved', 'quarantined')),
  constraint knowledge_archive_records_reason_code_chk check (reason_code in (
    'withdrawn_by_publisher', 'repealed_or_replaced', 'quarantine_concluded', 'rights_ended',
    'duplicate_version', 'retention_policy')),
  constraint knowledge_archive_records_rationale_chk check (length(btrim(rationale)) between 20 and 2000),
  constraint knowledge_archive_records_sha_chk check (snapshot_sha256 ~ '^[0-9a-f]{64}$')
);
create index knowledge_archive_records_document_idx on public.knowledge_archive_records (document_pk)
  where document_pk is not null;
create index knowledge_archive_records_source_idx on public.knowledge_archive_records (source_id);
alter table public.knowledge_archive_records enable row level security;
revoke all on public.knowledge_archive_records from public, anon, authenticated, service_role;
grant select on public.knowledge_archive_records to service_role;
create trigger knowledge_archive_records_guard
  before insert or update or delete on public.knowledge_archive_records
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_archive_records_no_truncate
  before truncate on public.knowledge_archive_records
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== emergency quarantine (H1)

create function private.knowledge_emergency_check(p_reason_code text, p_reason_detail text, p_operator_reference text)
returns void
language plpgsql
immutable
set search_path = ''
as $$
begin
  if p_reason_code is null or p_reason_code not in ('integrity_mismatch', 'provenance_withdrawn', 'rights_withdrawn',
       'harmful_content_report', 'superseding_law', 'demo_go_live', 'operator_error_containment') then
    raise exception 'emergency quarantine needs a reason code from the closed list (integrity_mismatch,'
      ' provenance_withdrawn, rights_withdrawn, harmful_content_report, superseding_law, demo_go_live,'
      ' operator_error_containment)' using errcode = '22023';
  end if;
  if p_reason_detail is null or length(btrim(p_reason_detail)) not between 20 and 2000 then
    raise exception 'emergency quarantine needs a detailed reason (20-2000 characters)' using errcode = '22023';
  end if;
  if p_operator_reference is null or length(btrim(p_operator_reference)) not between 3 and 200 then
    raise exception 'emergency quarantine needs the operator incident or ticket reference (3-200 characters)'
      using errcode = '22023';
  end if;
end;
$$;
revoke all on function private.knowledge_emergency_check(text, text, text) from public, anon, authenticated, service_role;

create function private.knowledge_emergency_quarantine_document(
  p_document_pk uuid, p_reason_code text, p_reason_detail text, p_operator_reference text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_doc record;
  v_snap jsonb;
  v_event bigint;
  v_id bigint;
begin
  perform private.knowledge_emergency_check(p_reason_code, p_reason_detail, p_operator_reference);
  select d.source_id into v_doc from public.knowledge_documents d where d.id = p_document_pk for update;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  v_event := private.knowledge_apply_document_transition(p_document_pk, 'approved', 'quarantined',
    pg_catalog.left('EMERGENCY ' || p_reason_code || ' [' || pg_catalog.btrim(p_operator_reference) || ']: '
                    || pg_catalog.btrim(p_reason_detail), 2000), null);
  perform private.knowledge_m2_set_marker('knowledge_emergency_actions');
  insert into public.knowledge_emergency_actions
    (entity_type, source_id, document_pk, status_event_id, reason_code, reason_detail, operator_reference,
     snapshot, snapshot_sha256, db_role, session_user_name)
  values ('document', v_doc.source_id, p_document_pk, v_event, p_reason_code, pg_catalog.btrim(p_reason_detail),
          pg_catalog.btrim(p_operator_reference), v_snap, private.knowledge_snapshot_sha256(v_snap),
          coalesce(nullif(current_setting('role', true), 'none'), session_user), session_user)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function private.knowledge_emergency_quarantine_document(uuid, text, text, text)
  from public, anon, authenticated, service_role;
grant execute on function private.knowledge_emergency_quarantine_document(uuid, text, text, text) to service_role;

create function private.knowledge_emergency_quarantine_source(
  p_source_id text, p_reason_code text, p_reason_detail text, p_operator_reference text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_snap jsonb;
  v_event bigint;
  v_id bigint;
begin
  perform private.knowledge_emergency_check(p_reason_code, p_reason_detail, p_operator_reference);
  perform 1 from public.knowledge_sources s where s.source_id = p_source_id for update;
  if not found then
    raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
  end if;
  v_snap := private.knowledge_source_snapshot(p_source_id);
  v_event := private.knowledge_apply_source_transition(p_source_id, 'approved', 'quarantined',
    pg_catalog.left('EMERGENCY ' || p_reason_code || ' [' || pg_catalog.btrim(p_operator_reference) || ']: '
                    || pg_catalog.btrim(p_reason_detail), 2000), null);
  perform private.knowledge_m2_set_marker('knowledge_emergency_actions');
  insert into public.knowledge_emergency_actions
    (entity_type, source_id, document_pk, status_event_id, reason_code, reason_detail, operator_reference,
     snapshot, snapshot_sha256, db_role, session_user_name)
  values ('source', p_source_id, null, v_event, p_reason_code, pg_catalog.btrim(p_reason_detail),
          pg_catalog.btrim(p_operator_reference), v_snap, private.knowledge_snapshot_sha256(v_snap),
          coalesce(nullif(current_setting('role', true), 'none'), session_user), session_user)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function private.knowledge_emergency_quarantine_source(text, text, text, text)
  from public, anon, authenticated, service_role;
grant execute on function private.knowledge_emergency_quarantine_source(text, text, text, text) to service_role;

-- ================================================================== permanent archive (H2)

create function private.knowledge_archive_check(p_reason_code text, p_rationale text, p_snapshot_sha256 text)
returns void
language plpgsql
immutable
set search_path = ''
as $$
begin
  if p_reason_code is null or p_reason_code not in ('withdrawn_by_publisher', 'repealed_or_replaced',
       'quarantine_concluded', 'rights_ended', 'duplicate_version', 'retention_policy') then
    raise exception 'archive needs a reason code from the closed list (withdrawn_by_publisher, repealed_or_replaced,'
      ' quarantine_concluded, rights_ended, duplicate_version, retention_policy)' using errcode = '22023';
  end if;
  if p_rationale is null or length(btrim(p_rationale)) not between 20 and 2000 then
    raise exception 'archive needs a rationale (20-2000 characters)' using errcode = '22023';
  end if;
  if p_snapshot_sha256 is null or p_snapshot_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'archive needs the sha256 of the snapshot being archived (public.knowledge_review_snapshot)'
      using errcode = '22023';
  end if;
end;
$$;
revoke all on function private.knowledge_archive_check(text, text, text) from public, anon, authenticated, service_role;

-- True when personnel record p_a and any of p_others are the same human (canonical identity key).
create function private.knowledge_same_person(p_a uuid, p_others uuid[])
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (select 1 from pg_catalog.unnest(p_others) o(id)
                  where o.id is not null
                    and (o.id = p_a or private.knowledge_person_identity(o.id) = private.knowledge_person_identity(p_a)));
$$;
revoke all on function private.knowledge_same_person(uuid, uuid[]) from public, anon, authenticated, service_role;

create function public.knowledge_archive_document(
  p_document_pk uuid, p_snapshot_sha256 text, p_reason_code text, p_rationale text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_doc record;
  v_role record;
  v_snap jsonb;
  v_uploaders uuid[];
  v_approvers uuid[];
  v_event bigint;
  v_id bigint;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  perform private.knowledge_archive_check(p_reason_code, p_rationale, p_snapshot_sha256);
  select d.status, d.source_id, s.visibility, s.organization_id into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk for update of d;
  -- one answer for a missing version and one out of the caller's scope: no existence oracle
  if not found then
    raise exception 'archive is not available for your knowledge role' using errcode = '42501';
  end if;
  select r.personnel_id, r.role_id into v_role
    from private.knowledge_actor_role(v_actor.user_id, 'archivist', v_doc.visibility, v_doc.organization_id) r;
  if v_role.role_id is null then
    raise exception 'archive is not available for your knowledge role' using errcode = '42501';
  end if;
  if v_doc.status not in ('approved', 'quarantined') then
    raise exception 'knowledge document %: status is %; only approved or quarantined versions are archived',
      p_document_pk, v_doc.status using errcode = '23514';
  end if;
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  if private.knowledge_snapshot_sha256(v_snap) <> p_snapshot_sha256 then
    raise exception 'knowledge document %: the snapshot changed since you read it (stale hash); read it again',
      p_document_pk using errcode = '40001';
  end if;
  select pg_catalog.array_agg(u.uploader_personnel_id) into v_uploaders
    from public.knowledge_upload_attestations u where u.document_pk = p_document_pk;
  if private.knowledge_same_person(v_role.personnel_id, v_uploaders) then
    raise exception 'knowledge document %: the uploader of a version never archives it (separation of duties)',
      p_document_pk using errcode = '42501';
  end if;
  if v_doc.status = 'approved' then
    select pg_catalog.array_agg(a.approver_personnel_id) into v_approvers
      from public.knowledge_approval_records a
     where a.entity_type = 'document' and a.document_pk = p_document_pk and a.decision = 'approve';
    if private.knowledge_same_person(v_role.personnel_id, v_approvers) then
      raise exception 'knowledge document %: its approver never archives an approved version directly (D-H2b);'
        ' another archivist, or quarantine first', p_document_pk using errcode = '42501';
    end if;
  end if;
  v_event := private.knowledge_apply_document_transition(p_document_pk, v_doc.status, 'archived',
    pg_catalog.left('ARCHIVE ' || p_reason_code || ': ' || pg_catalog.btrim(p_rationale), 2000), null);
  perform private.knowledge_m2_set_marker('knowledge_archive_records');
  insert into public.knowledge_archive_records
    (entity_type, source_id, document_pk, from_status, status_event_id, archivist_personnel_id, archivist_role_id,
     archivist_user_id, archivist_session_id, reason_code, rationale, snapshot, snapshot_sha256)
  values ('document', v_doc.source_id, p_document_pk, v_doc.status, v_event, v_role.personnel_id, v_role.role_id,
          v_actor.user_id, v_actor.session_id, p_reason_code, pg_catalog.btrim(p_rationale), v_snap, p_snapshot_sha256)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function public.knowledge_archive_document(uuid, text, text, text) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_archive_document(uuid, text, text, text) to authenticated;

create function public.knowledge_archive_source(
  p_source_id text, p_snapshot_sha256 text, p_reason_code text, p_rationale text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_src record;
  v_role record;
  v_snap jsonb;
  v_uploaders uuid[];
  v_approvers uuid[];
  v_event bigint;
  v_id bigint;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  perform private.knowledge_archive_check(p_reason_code, p_rationale, p_snapshot_sha256);
  select s.status, s.visibility, s.organization_id into v_src
    from public.knowledge_sources s where s.source_id = p_source_id for update;
  if not found then
    raise exception 'archive is not available for your knowledge role' using errcode = '42501';
  end if;
  select r.personnel_id, r.role_id into v_role
    from private.knowledge_actor_role(v_actor.user_id, 'archivist', v_src.visibility, v_src.organization_id) r;
  if v_role.role_id is null then
    raise exception 'archive is not available for your knowledge role' using errcode = '42501';
  end if;
  if v_src.status not in ('approved', 'quarantined') then
    raise exception 'knowledge source %: status is %; only approved or quarantined sources are archived',
      p_source_id, v_src.status using errcode = '23514';
  end if;
  v_snap := private.knowledge_source_snapshot(p_source_id);
  if private.knowledge_snapshot_sha256(v_snap) <> p_snapshot_sha256 then
    raise exception 'knowledge source %: the snapshot changed since you read it (stale hash); read it again',
      p_source_id using errcode = '40001';
  end if;
  select pg_catalog.array_agg(u.uploader_personnel_id) into v_uploaders
    from public.knowledge_upload_attestations u where u.entity_type = 'source' and u.source_id = p_source_id;
  if private.knowledge_same_person(v_role.personnel_id, v_uploaders) then
    raise exception 'knowledge source %: the uploader of a source never archives it (separation of duties)',
      p_source_id using errcode = '42501';
  end if;
  if v_src.status = 'approved' then
    select pg_catalog.array_agg(a.approver_personnel_id) into v_approvers
      from public.knowledge_approval_records a
     where a.entity_type = 'source' and a.source_id = p_source_id and a.decision = 'approve';
    if private.knowledge_same_person(v_role.personnel_id, v_approvers) then
      raise exception 'knowledge source %: its approver never archives an approved source directly (D-H2b);'
        ' another archivist, or quarantine first', p_source_id using errcode = '42501';
    end if;
  end if;
  v_event := private.knowledge_apply_source_transition(p_source_id, v_src.status, 'archived',
    pg_catalog.left('ARCHIVE ' || p_reason_code || ': ' || pg_catalog.btrim(p_rationale), 2000), null);
  perform private.knowledge_m2_set_marker('knowledge_archive_records');
  insert into public.knowledge_archive_records
    (entity_type, source_id, document_pk, from_status, status_event_id, archivist_personnel_id, archivist_role_id,
     archivist_user_id, archivist_session_id, reason_code, rationale, snapshot, snapshot_sha256)
  values ('source', p_source_id, null, v_src.status, v_event, v_role.personnel_id, v_role.role_id,
          v_actor.user_id, v_actor.session_id, p_reason_code, pg_catalog.btrim(p_rationale), v_snap, p_snapshot_sha256)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function public.knowledge_archive_source(text, text, text, text) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_archive_source(text, text, text, text) to authenticated;

-- ================================================================== snapshot read (replaced)

-- The M2 wrapper, plus the archivist: the hash an archivist confirms is computed by the same function.
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
      select 1 from unnest(array['uploader', 'expert_reviewer', 'approver', 'archivist']) r(role)
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

-- ================================================================== operator functions (replaced)

-- The M2 bodies, plus: quarantine and archive are refused here for every caller. Argument checks and
-- the M2 refusals come first, with the same SQLSTATEs.
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
  if p_to in ('quarantined', 'archived') then
    -- a stale or unknown request is reported as in M1, before the H-b refusal
    select s.status into v_status from public.knowledge_sources s where s.source_id = p_source_id;
    if not found then
      raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
    end if;
    if v_status <> p_from then
      raise exception 'knowledge source %: status is %, not % (changed concurrently or a stale request)',
        p_source_id, v_status, p_from using errcode = '23514';
    end if;
  end if;
  if p_to = 'quarantined' then
    raise exception 'knowledge source %: quarantine is an emergency action with evidence (H-b): use'
      ' private.knowledge_emergency_quarantine_source(source, reason_code, reason_detail, operator_reference)',
      p_source_id using errcode = '42501';
  end if;
  if p_to = 'archived' then
    raise exception 'knowledge source %: archive is permanent and needs an authenticated archivist (H-b): use'
      ' public.knowledge_archive_source with an aal2 session; operator and owner logins cannot archive',
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
  if p_to in ('quarantined', 'archived') then
    -- a stale or unknown request is reported as in M1, before the H-b refusal
    select d.status into v_status from public.knowledge_documents d where d.id = p_document_pk;
    if not found then
      raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
    end if;
    if v_status <> p_from then
      raise exception 'knowledge document %: status is %, not % (changed concurrently or a stale request)',
        p_document_pk, v_status, p_from using errcode = '23514';
    end if;
  end if;
  if p_to = 'quarantined' then
    raise exception 'knowledge document %: quarantine is an emergency action with evidence (H-b): use'
      ' private.knowledge_emergency_quarantine_document(document, reason_code, reason_detail, operator_reference)',
      p_document_pk using errcode = '42501';
  end if;
  if p_to = 'archived' then
    raise exception 'knowledge document %: archive is permanent and needs an authenticated archivist (H-b): use'
      ' public.knowledge_archive_document with an aal2 session; operator and owner logins cannot archive',
      p_document_pk using errcode = '42501';
  end if;
  return private.knowledge_apply_document_transition(p_document_pk, p_from, p_to, p_reason, p_approved_by);
end;
$$;
