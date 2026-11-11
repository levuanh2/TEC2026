-- RAG V1.5 M3 (docs/rag/RAG_V15_SOURCE_CONTENT_INTEGRITY.md §3.2, §6): version validity.
-- LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN: M3 keeps guidance
-- that is no longer in force out of retrieval. It does not judge whether the content is correct.
-- Depends on M1 (20261110090100) and M2 (20261110120000). Design: docs/rag/RAG_V15_M3_EFFECTIVE_DATES.md.
--
-- What changes
--   * public.knowledge_documents gets
--       effective_from, effective_to   the version's own validity window (calendar dates, both
--                                      inclusive, both optional), set at ingestion and part of what
--                                      the expert reviews;
--       supersedes_document_pk         the previously approved version this one replaces (same
--                                      scope only; any document_id);
--       approval_expires_on            set BY THE APPROVAL, never supplied: approval day + 2 years
--                                      (owner decision 2026-11-11). An approval is evidence with a
--                                      shelf life: after it, the version needs a new review.
--   * "Today" is one policy date, the calendar day in Asia/Ho_Chi_Minh, whatever the session
--     TimeZone: private.knowledge_policy_date(now()).
--   * A version is IN FORCE when effective_from <= today <= effective_to (open ends allowed) and
--     today <= approval_expires_on. Retrieval and the document RLS policy serve approved versions
--     only while in force, so an expired version is withheld from the first moment of the next
--     policy day, before any job runs (fail closed).
--   * Approval is refused before effective_from, after effective_to, and while the superseded
--     version is still approved. An expired version cannot enter expert review.
--   * Supersession is atomic: the approval archives the approved version it supersedes in the same
--     transaction (its own audit event names the successor), so there is neither an overlap nor a
--     gap. One approved version per (source_id, document_id) stays enforced by the Migration A index.
--     A demo approval (M2 owner switch) supersedes only a demo-approved version, never a verified one.
--   * The window and the superseded version are frozen from expert_review on and covered by the M2
--     review snapshot hash: changing them invalidates the evidence exactly like any other metadata.
--   * Expiry: private.knowledge_expire_documents (EXECUTE service_role only) moves approved versions
--     that are no longer in force to `quarantined` through the M1 audited transition and writes one
--     immutable public.knowledge_expiry_events row per version. private.knowledge_expiry_due is its
--     read-only dry run. NOTHING SCHEDULES IT: this migration creates no cron job; running it is an
--     operator decision per environment.
--
-- Consequences to know (M1 decision D1 is unchanged): quarantine is one-way. An expired version never
-- returns to approved; the corrected or revalidated text is a NEW version through the full flow.
-- A wrong date is therefore corrected before the review starts (the dates are editable only while
-- the version is review_required or rejected), or by a new version.
--
-- Not in M3: sources have no validity window (a source is a collection; its versions expire);
-- approving a version ahead of its effective_from (scheduled succession) is refused rather than
-- queued; extending an approval before it expires needs a new review of a new version.

-- ================================================================== columns

alter table public.knowledge_documents
  add column effective_from date,
  add column effective_to date,
  add column supersedes_document_pk uuid references public.knowledge_documents(id) on delete restrict,
  add column approval_expires_on date;

comment on column public.knowledge_documents.effective_from is
  'M3: first calendar day (Asia/Ho_Chi_Minh) the version is in force; null = no lower bound.';
comment on column public.knowledge_documents.effective_to is
  'M3: last calendar day (Asia/Ho_Chi_Minh) the version is in force, inclusive; null = no upper bound.';
comment on column public.knowledge_documents.supersedes_document_pk is
  'M3: the previously approved version (same scope) this version replaces; archived by this version''s approval.';
comment on column public.knowledge_documents.approval_expires_on is
  'M3: last calendar day the approval is valid (approval day + 2 years); set by the approval, never supplied.';

-- Versions approved before M3: the same rule, counted from their recorded approval day. (The M2 row
-- trigger is still installed here and does not guard this column.)
update public.knowledge_documents
   set approval_expires_on = ((approved_at at time zone 'Asia/Ho_Chi_Minh')::date + interval '2 years')::date
 where approved_at is not null;

alter table public.knowledge_documents
  add constraint knowledge_documents_effective_window_chk check (
    effective_from is null or effective_to is null or effective_to >= effective_from),
  add constraint knowledge_documents_supersedes_self_chk check (
    supersedes_document_pk is null or supersedes_document_pk <> id),
  add constraint knowledge_documents_approval_expiry_chk check (
    status <> 'approved' or approval_expires_on is not null);

create index knowledge_documents_supersedes_idx on public.knowledge_documents (supersedes_document_pk)
  where supersedes_document_pk is not null;

-- ================================================================== policy date

create function private.knowledge_policy_time_zone()
returns text
language sql
immutable
set search_path = ''
as $$
  select 'Asia/Ho_Chi_Minh'::text;
$$;
revoke all on function private.knowledge_policy_time_zone() from public, anon, authenticated, service_role;

-- The calendar day of an instant in the policy zone: independent of the session TimeZone.
create function private.knowledge_policy_date(p_at timestamptz)
returns date
language sql
stable
set search_path = ''
as $$
  select (p_at at time zone private.knowledge_policy_time_zone())::date;
$$;
revoke all on function private.knowledge_policy_date(timestamptz) from public, anon, authenticated, service_role;

-- Owner decision (2026-11-11): an approval is valid for two years.
create function private.knowledge_approval_validity()
returns interval
language sql
immutable
set search_path = ''
as $$
  select interval '2 years';
$$;
revoke all on function private.knowledge_approval_validity() from public, anon, authenticated, service_role;

-- The single definition of "in force on p_on" (both window ends inclusive; a missing approval expiry
-- is NOT in force). The retrieval function and the RLS policy inline the same predicate.
create function private.knowledge_in_force(p_from date, p_to date, p_approval_expires_on date, p_on date)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select (p_from is null or p_from <= p_on) and (p_to is null or p_to >= p_on)
     and coalesce(p_approval_expires_on >= p_on, false);
$$;
revoke all on function private.knowledge_in_force(date, date, date, date) from public, anon, authenticated, service_role;

-- ================================================================== supersession

-- 23503 / 23514 unless `p_target` may be superseded by a version of `p_source_id`: it exists, was
-- approved at some time (so chains cannot loop: a target is always older evidence), and lives in
-- exactly the same scope (public, or the same organization and farm). No cross-tenant link.
create function private.knowledge_check_supersedes(p_source_id text, p_target uuid)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_target record;
  v_own record;
begin
  select t.approved_at, s.visibility, s.organization_id, s.farm_id into v_target
    from public.knowledge_documents t join public.knowledge_sources s on s.source_id = t.source_id
   where t.id = p_target;
  if not found then
    raise exception 'the superseded version % does not exist', p_target using errcode = '23503';
  end if;
  select s.visibility, s.organization_id, s.farm_id into v_own
    from public.knowledge_sources s where s.source_id = p_source_id;
  if (v_target.visibility, v_target.organization_id, v_target.farm_id)
      is distinct from (v_own.visibility, v_own.organization_id, v_own.farm_id) then
    raise exception 'a version supersedes only a version of the same scope' using errcode = '23514';
  end if;
  if v_target.approved_at is null then
    raise exception 'only a version that was approved can be superseded (% never was)', p_target
      using errcode = '23514';
  end if;
end;
$$;
revoke all on function private.knowledge_check_supersedes(text, uuid) from public, anon, authenticated, service_role;
-- the document row trigger runs as the writer: the operator (service_role) may set the link at ingestion
grant execute on function private.knowledge_check_supersedes(text, uuid) to service_role;

-- Called by the approval functions (definer context) right before they approve `p_document_pk`:
-- archives the approved version it supersedes, with its own audit event naming the successor.
-- Returns that event id, or null when there is nothing to archive. A demo approval (p_demo) refuses
-- a superseded version whose approval is not a demo record, whatever its status is now.
-- A version may have several successors (one text split into two documents): each approval finds
-- the target either approved (and archives it) or already archived.
create function private.knowledge_supersede_for(p_document_pk uuid, p_demo boolean)
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  v_doc record;
  v_status public.knowledge_status;
begin
  select d.source_id, d.document_id, d.document_version, d.supersedes_document_pk into v_doc
    from public.knowledge_documents d where d.id = p_document_pk;
  if v_doc.supersedes_document_pk is null then
    return null;
  end if;
  select t.status into v_status from public.knowledge_documents t
   where t.id = v_doc.supersedes_document_pk for update;
  -- whatever the target's status today: a demo version never claims to succeed a verified one
  if p_demo and not exists (
      select 1 from public.knowledge_approval_records a
       where a.entity_type = 'document' and a.document_pk = v_doc.supersedes_document_pk
         and a.decision = 'approve' and a.assurance = 'demo_unverified') then
    raise exception 'knowledge document %: a demo approval never supersedes a version that was not demo-approved'
      ' (ingest it without the link, or use the verified flow)', p_document_pk
      using errcode = '42501';
  end if;
  if v_status is distinct from 'approved' then
    return null;
  end if;
  return private.knowledge_apply_document_transition(
    v_doc.supersedes_document_pk, 'approved', 'archived',
    pg_catalog.left((case when p_demo then 'DEMO - NOT EXPERT-REVIEWED: ' else '' end)
                    || 'superseded by ' || v_doc.source_id || ' / ' || v_doc.document_id || ' / '
                    || v_doc.document_version || ' (document ' || p_document_pk::text || ')', 2000),
    null);
end;
$$;
revoke all on function private.knowledge_supersede_for(uuid, boolean) from public, anon, authenticated, service_role;

-- ================================================================== snapshot (replaced)

create or replace function private.knowledge_document_snapshot(p_document_pk uuid)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'document', pg_catalog.jsonb_build_object(
      'id', d.id, 'source_id', d.source_id, 'document_id', d.document_id, 'document_version', d.document_version,
      'title', d.title, 'language', d.language, 'official_url', d.official_url, 'artifact_ref', d.artifact_ref,
      'file_sha256', d.file_sha256, 'normalized_sha256', d.normalized_sha256, 'published_at', d.published_at,
      'imported_at', pg_catalog.to_char(d.imported_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), 'parser_version', d.parser_version, 'normalizer_version', d.normalizer_version,
      'chunker_version', d.chunker_version, 'license_basis', d.license_basis, 'license_reference', d.license_reference)
      -- M3: the validity window and the superseded version are part of what is reviewed. Keys are
      -- present only when set, so a version without them hashes exactly as it did under M2.
      || pg_catalog.jsonb_strip_nulls(pg_catalog.jsonb_build_object(
           'effective_from', d.effective_from, 'effective_to', d.effective_to,
           'supersedes_document_pk', d.supersedes_document_pk)),
    'source', (select pg_catalog.jsonb_build_object(
      'source_id', s.source_id, 'title', s.title, 'owner', s.owner, 'source_type', s.source_type,
      'authority', s.authority, 'visibility', s.visibility, 'organization_id', s.organization_id,
      'farm_id', s.farm_id, 'created_at', pg_catalog.to_char(s.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
      from public.knowledge_sources s where s.source_id = d.source_id),
    'chunks', (select pg_catalog.jsonb_build_object(
      'count', count(*),
      'manifest_sha256', pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce(
        pg_catalog.string_agg(c.ordinal::text || ':' || c.chunk_id || ':' || c.content_sha256, E'\n' order by c.ordinal),
        ''), 'UTF8')), 'hex'))
      from public.knowledge_chunks c where c.document_pk = d.id))
  from public.knowledge_documents d where d.id = p_document_pk;
$$;

-- ================================================================== document row trigger (replaced)

-- The M2 trigger plus the M3 rules (each marked M3 below).
create or replace function private.enforce_knowledge_document_immutability()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_today date;
begin
  if tg_op = 'DELETE' then
    if old.approved_at is not null then
      raise exception 'knowledge document % % % was approved and cannot be deleted',
        old.source_id, old.document_id, old.document_version using errcode = '23514';
    end if;
    if old.status = 'expert_review' then
      raise exception 'knowledge document % % % is under expert review and cannot be deleted',
        old.source_id, old.document_id, old.document_version using errcode = '23514';
    end if;
    return old;
  end if;
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
    if new.approval_expires_on is not null then
      raise exception 'knowledge document % % %: approval_expires_on is set by the approval itself',
        new.source_id, new.document_id, new.document_version using errcode = '23514';
    end if;
    if new.supersedes_document_pk is not null then
      perform private.knowledge_check_supersedes(new.source_id, new.supersedes_document_pk);
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
  -- M3: a (changed) superseded version is validated; the approval expiry is set only by an approval.
  if new.supersedes_document_pk is distinct from old.supersedes_document_pk
     and new.supersedes_document_pk is not null then
    perform private.knowledge_check_supersedes(new.source_id, new.supersedes_document_pk);
  end if;
  if new.status = 'approved' and old.status <> 'approved' then
    v_today := private.knowledge_policy_date(pg_catalog.now());
    new.approval_expires_on := (v_today + private.knowledge_approval_validity())::date;
  elsif new.approval_expires_on is distinct from old.approval_expires_on then
    raise exception 'knowledge document % % %: approval_expires_on is set by the approval itself',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  -- M2 freeze: what the expert reviews is exactly what gets approved.
  if old.status = 'expert_review'
     and (new.title, new.language, new.official_url, new.artifact_ref, new.published_at, new.license_basis,
          new.license_reference, new.effective_from, new.effective_to,
          new.supersedes_document_pk)
         is distinct from
         (old.title, old.language, old.official_url, old.artifact_ref, old.published_at, old.license_basis,
          old.license_reference, old.effective_from, old.effective_to,
          old.supersedes_document_pk) then
    raise exception 'knowledge document % % % is under expert review; its artifact, license, metadata, validity window'
      ' and superseded version are frozen (return it to review_required, or ingest a new version)',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  if new.status <> old.status then
    if not private.knowledge_status_transition_allowed('document', old.status, new.status) then
      raise exception 'knowledge document % % %: status % -> % is not allowed',
        old.source_id, old.document_id, old.document_version, old.status, new.status using errcode = '23514';
    end if;
    if new.status = 'expert_review' and not exists (
        select 1 from public.knowledge_expert_reviews r
         where r.document_pk = old.id and r.decision is null
           and r.recorded_xact = pg_catalog.pg_current_xact_id())
       and not exists (                                    -- or the owner-switched, labelled demo path
        select 1 from public.knowledge_approval_records a
         where a.document_pk = old.id and a.assurance = 'demo_unverified'
           and a.recorded_xact = pg_catalog.pg_current_xact_id()) then
      raise exception 'knowledge document % % %: expert review starts only with a verified reviewer'
        ' (public.knowledge_start_expert_review)', old.source_id, old.document_id, old.document_version
        using errcode = '42501';
    end if;
    -- M3: an expired version is not sent to an expert, and nothing is approved outside its window
    -- or while the version it supersedes is still approved (the approval archives that one first).
    if new.status = 'expert_review' and new.effective_to is not null
       and new.effective_to < private.knowledge_policy_date(pg_catalog.now()) then
      raise exception 'knowledge document % % %: effective_to % has passed; an expired version is not reviewed',
        old.source_id, old.document_id, old.document_version, new.effective_to using errcode = '23514';
    end if;
    if new.status = 'approved' then
      if new.effective_from is not null and new.effective_from > v_today then
        raise exception 'knowledge document % % %: not in force before % (policy date %); approve it then',
          old.source_id, old.document_id, old.document_version, new.effective_from, v_today
          using errcode = '23514';
      end if;
      if new.effective_to is not null and new.effective_to < v_today then
        raise exception 'knowledge document % % %: effective_to % has passed (policy date %); approval refused',
          old.source_id, old.document_id, old.document_version, new.effective_to, v_today
          using errcode = '23514';
      end if;
      if exists (select 1 from public.knowledge_documents t
                  where t.id = new.supersedes_document_pk and t.status = 'approved') then
        raise exception 'knowledge document % % %: the version it supersedes is still approved',
          old.source_id, old.document_id, old.document_version using errcode = '23514';
      end if;
    end if;
    if new.status = 'approved' and not exists (
        select 1 from public.knowledge_approval_records a
         where a.entity_type = 'document' and a.document_pk = old.id and a.decision = 'approve'
           and a.approver_user_id = new.approved_by
           and a.recorded_xact = pg_catalog.pg_current_xact_id()) then
      raise exception 'knowledge document % % %: approval needs a verified approval record'
        ' (public.knowledge_decide_document)', old.source_id, old.document_id, old.document_version
        using errcode = '42501';
    end if;
  end if;
  if old.approved_at is not null
     and (new.title, new.language, new.official_url, new.artifact_ref, new.published_at, new.license_basis,
          new.license_reference, new.approved_by, new.approved_at, new.review_note,
          new.effective_from, new.effective_to, new.supersedes_document_pk)
         is distinct from
         (old.title, old.language, old.official_url, old.artifact_ref, old.published_at, old.license_basis,
          old.license_reference, old.approved_by, old.approved_at, old.review_note,
          old.effective_from, old.effective_to, old.supersedes_document_pk) then
    raise exception 'knowledge document % % % was approved; its provenance and approval record are immutable',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  return new;
end;
$$;

-- ================================================================== approvals (replaced)

-- public.knowledge_decide_document: the M2 function plus one step (the supersession).
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

-- private.knowledge_demo_approve_document: the M2 function plus the demo-only supersession.
create or replace function private.knowledge_demo_approve_document(p_document_pk uuid, p_approved_by uuid, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_reason text := private.knowledge_demo_reason(p_reason);
  v_doc record;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  perform private.knowledge_demo_require_enabled();
  if p_approved_by is null then
    raise exception 'a demo approval names the (stated) approver account' using errcode = '22023';
  end if;
  select d.status, d.source_id into v_doc from public.knowledge_documents d where d.id = p_document_pk for update;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  if v_doc.status not in ('review_required', 'expert_review') then
    raise exception 'knowledge document %: status % cannot be demo-approved', p_document_pk, v_doc.status
      using errcode = '23514';
  end if;
  -- M3: a demo approval replaces only a demo-approved version, never a verified one
  perform private.knowledge_supersede_for(p_document_pk, true);
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  perform private.knowledge_m2_set_marker('knowledge_approval_records');
  insert into public.knowledge_approval_records (id, entity_type, source_id, document_pk, decision, assurance,
    approver_user_id, snapshot, snapshot_sha256, rationale, status_event_id)
  values (v_id, 'document', v_doc.source_id, p_document_pk, 'approve', 'demo_unverified', p_approved_by, v_snap,
          private.knowledge_snapshot_sha256(v_snap), v_reason, 0);
  perform private.knowledge_m2_set_marker(null);
  if v_doc.status = 'review_required' then
    perform private.knowledge_apply_document_transition(p_document_pk, 'review_required', 'expert_review', v_reason, null);
  end if;
  v_event := private.knowledge_apply_document_transition(p_document_pk, 'expert_review', 'approved', v_reason,
                                                         p_approved_by);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

-- ================================================================== retrieval (replaced)

-- Same policy and function as 20261005090000 plus the in-force window. The zone literal equals
-- private.knowledge_policy_time_zone() (pinned by a test): the expression is inlined so the invoker
-- paths need no new EXECUTE grant.
drop policy knowledge_documents_select on public.knowledge_documents;
create policy knowledge_documents_select on public.knowledge_documents
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and status = 'approved'
    and (effective_from is null or effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
    and (effective_to is null or effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
    and approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    and exists (select 1 from public.knowledge_sources s where s.source_id = knowledge_documents.source_id)
  );

create or replace function public.match_knowledge_chunks_lexical(
  p_crop_season_id uuid,
  p_query text,
  p_top_k integer default 8
)
returns table (
  source_id text,
  document_id text,
  document_version text,
  chunk_id text,
  ordinal integer,
  title text,
  section_path text,
  page_from integer,
  page_to integer,
  content text,
  metadata jsonb,
  source_type text,
  authority text,
  visibility text,
  organization_id uuid,
  farm_id uuid,
  official_url text,
  published_at date,
  fused_score double precision,
  fts_rank integer,
  trgm_rank integer
)
language sql
stable
security invoker
set search_path = ''
as $$
  with scope as (
    select p.farm_id, f.cooperative_id as organization_id
    from public.crop_seasons cs
    join public.plots p on p.id = cs.plot_id
    join public.farms f on f.id = p.farm_id
    where cs.id = p_crop_season_id
  ),
  q as (
    select private.knowledge_search_text(left(p_query, 1000)) as text
  ),
  query as (
    select q.text, replace(plainto_tsquery('simple'::regconfig, q.text)::text, ' & ', ' | ')::tsquery as tsq
    from q where q.text <> ''
  ),
  eligible as (
    select c.id, c.chunk_id, c.ordinal, c.section_path, c.page_from, c.page_to, c.content, c.metadata,
           c.search_text, c.search_tsv,
           d.source_id, d.document_id, d.document_version, d.title, d.official_url, d.published_at,
           s.source_type, s.authority, s.visibility, s.organization_id, s.farm_id
    from public.knowledge_chunks c
    join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
      -- M3: in force today (policy date), whether or not the expiry job has run yet
      and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
    cross join scope
    where s.visibility = 'public'
       or (s.visibility = 'tenant'
           and s.organization_id = scope.organization_id
           and (s.farm_id is null
                or (s.farm_id = scope.farm_id
                    and exists (select 1 from public.farms f2
                                where f2.id = s.farm_id and f2.cooperative_id = s.organization_id))))
  ),
  fts as (
    select e.id, row_number() over (
             order by ts_rank_cd(e.search_tsv, query.tsq) desc,
                      e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id)::integer as rnk
    from eligible e cross join query
    where e.search_tsv @@ query.tsq
    order by rnk
    limit 50
  ),
  trgm as (
    select e.id, row_number() over (
             order by extensions.word_similarity(query.text, e.search_text) desc,
                      e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id)::integer as rnk
    from eligible e cross join query
    where query.text operator(extensions.<%) e.search_text
    order by rnk
    limit 50
  ),
  fused as (
    select coalesce(fts.id, trgm.id) as id, fts.rnk as fts_rank, trgm.rnk as trgm_rank,
           coalesce(1.0 / (60 + fts.rnk), 0) + coalesce(1.0 / (60 + trgm.rnk), 0) as fused_score
    from fts full join trgm on trgm.id = fts.id
  )
  select e.source_id, e.document_id, e.document_version, e.chunk_id, e.ordinal, e.title, e.section_path,
         e.page_from, e.page_to, e.content, e.metadata, e.source_type, e.authority, e.visibility,
         e.organization_id, e.farm_id, e.official_url, e.published_at,
         fused.fused_score::double precision, fused.fts_rank, fused.trgm_rank
  from fused join eligible e on e.id = fused.id
  order by fused.fused_score desc, e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id
  limit least(greatest(coalesce(p_top_k, 8), 1), 50);
$$;

-- ================================================================== expiry

-- One immutable row per automatic expiry: which version, why, on which policy date, and the M1 audit
-- event of its approved -> quarantined transition.
create table public.knowledge_expiry_events (
  id bigint generated always as identity primary key,
  document_pk uuid not null references public.knowledge_documents(id) on delete restrict,
  source_id text not null,
  document_id text not null,
  document_version text not null,
  cause text not null,
  effective_to date,
  approval_expires_on date,
  policy_date date not null,
  policy_time_zone text not null,
  -- the M1 audit event of the transition (no FK, like the M2 evidence tables: the event log stays
  -- independent, and it is append-only for every role)
  status_event_id bigint not null,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_current_xact_id(),
  actor_session_user text not null default session_user,
  actor_role text not null,
  constraint knowledge_expiry_events_document_key unique (document_pk),
  constraint knowledge_expiry_events_status_event_key unique (status_event_id),
  constraint knowledge_expiry_events_cause_chk check (
    (cause = 'effective_to_passed' and effective_to is not null and effective_to < policy_date)
    or (cause = 'approval_validity_passed' and approval_expires_on is not null
        and approval_expires_on < policy_date))
);
comment on table public.knowledge_expiry_events is
  'M3: immutable evidence of automatic expiry (approved -> quarantined). Written only by private.knowledge_expire_documents.';

alter table public.knowledge_expiry_events enable row level security;
revoke all on public.knowledge_expiry_events from public, anon, authenticated, service_role;
grant select on public.knowledge_expiry_events to service_role;

create function private.knowledge_expiry_events_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' and private.knowledge_m2_write_authorized('knowledge_expiry_events') then
    return new;
  end if;
  raise exception 'knowledge_expiry_events is immutable evidence written only by'
    ' private.knowledge_expire_documents: % is refused', tg_op using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_expiry_events_guard() from public, anon, authenticated, service_role;
create trigger knowledge_expiry_events_guard
  before insert or update or delete on public.knowledge_expiry_events
  for each row execute function private.knowledge_expiry_events_guard();
create trigger knowledge_expiry_events_no_truncate
  before truncate on public.knowledge_expiry_events
  for each statement execute function private.knowledge_m2_no_truncate();

-- Dry run: the approved versions the next expiry run would quarantine, and why. Read-only.
create function private.knowledge_expiry_due()
returns table (document_pk uuid, source_id text, document_id text, document_version text, cause text,
               effective_to date, approval_expires_on date, policy_date date)
language sql
stable
security definer
set search_path = ''
as $$
  select d.id, d.source_id, d.document_id, d.document_version,
         -- the date that passed FIRST is the cause, however late the run is
         case when d.effective_to < t.today and d.effective_to <= d.approval_expires_on
              then 'effective_to_passed' else 'approval_validity_passed' end,
         d.effective_to, d.approval_expires_on, t.today
    from public.knowledge_documents d
   cross join (select private.knowledge_policy_date(pg_catalog.now()) as today) t
   where d.status = 'approved' and (d.effective_to < t.today or d.approval_expires_on < t.today)
   order by d.id;
$$;

-- The controlled expiry step: at most p_limit approved versions that are no longer in force go to
-- `quarantined` (M1 audited transition, one-way), each with its evidence row, in the caller's
-- transaction. Rows locked by another transaction are skipped (a concurrent run or a concurrent
-- operator transition never double-expires or blocks). Returns how many it quarantined. The audit
-- reason is written in ISO dates whatever the caller's DateStyle.
create function private.knowledge_expire_documents(p_limit integer default 100)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_today date := private.knowledge_policy_date(pg_catalog.now());
  v_zone text := private.knowledge_policy_time_zone();
  v_row record;
  v_cause text;
  v_event bigint;
  v_count integer := 0;
begin
  if p_limit is null or p_limit < 1 or p_limit > 1000 then
    raise exception 'an expiry run handles 1-1000 versions' using errcode = '22023';
  end if;
  for v_row in
    select d.id, d.source_id, d.document_id, d.document_version, d.effective_to, d.approval_expires_on
      from public.knowledge_documents d
     where d.status = 'approved' and (d.effective_to < v_today or d.approval_expires_on < v_today)
     order by d.id
     limit p_limit
       for update of d skip locked
  loop
    -- the date that passed FIRST is the cause, however late the run is
    v_cause := case when v_row.effective_to < v_today and v_row.effective_to <= v_row.approval_expires_on
                    then 'effective_to_passed' else 'approval_validity_passed' end;
    v_event := private.knowledge_apply_document_transition(
      v_row.id, 'approved', 'quarantined',
      'EXPIRED (automatic): ' || case when v_cause = 'effective_to_passed'
                                      then 'effective_to ' || pg_catalog.to_char(v_row.effective_to, 'YYYY-MM-DD')
                                      else 'approval validity '
                                           || pg_catalog.to_char(v_row.approval_expires_on, 'YYYY-MM-DD') end
        || ' passed on policy date ' || pg_catalog.to_char(v_today, 'YYYY-MM-DD') || ' (' || v_zone
        || '); a new version is required',
      null);
    perform private.knowledge_m2_set_marker('knowledge_expiry_events');
    insert into public.knowledge_expiry_events (document_pk, source_id, document_id, document_version, cause,
      effective_to, approval_expires_on, policy_date, policy_time_zone, status_event_id, actor_role)
    values (v_row.id, v_row.source_id, v_row.document_id, v_row.document_version, v_cause, v_row.effective_to,
            v_row.approval_expires_on, v_today, v_zone, v_event,
            coalesce(nullif(current_setting('role', true), 'none'), session_user));
    perform private.knowledge_m2_set_marker(null);
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;

revoke all on function private.knowledge_expiry_due() from public, anon, authenticated, service_role;
revoke all on function private.knowledge_expire_documents(integer) from public, anon, authenticated, service_role;
grant execute on function private.knowledge_expiry_due() to service_role;
grant execute on function private.knowledge_expire_documents(integer) to service_role;
