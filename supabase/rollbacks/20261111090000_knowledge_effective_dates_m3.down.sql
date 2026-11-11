-- Rollback for migrations/20261111090000_knowledge_effective_dates_m3.sql (RAG V1.5 M3).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE any M2 rollback, then
--   supabase migration repair --status reverted 20261111090000
--
-- Restores verbatim: the Migration A document policy and retrieval function, and the M2 snapshot,
-- document row trigger, public.knowledge_decide_document and private.knowledge_demo_approve_document.
-- Drops the M3 functions, public.knowledge_expiry_events and the four M3 columns.
-- DROPPING THEM DELETES THE EXPIRY EVIDENCE AND EVERY VALIDITY WINDOW: export
-- public.knowledge_expiry_events and the columns effective_from, effective_to,
-- supersedes_document_pk, approval_expires_on of public.knowledge_documents first, then confirm with
--   set local knowledge.m3_rollback_evidence_exported = 'yes';
-- Refuses while
--   * an approved version is not in force (rolling back would make it retrievable again: run
--     private.knowledge_expire_documents first; a version it does not take, e.g. one whose
--     effective_from an owner moved into the future, is quarantined with the operator transition
--     private.knowledge_transition_document(id, 'approved', 'quarantined', reason)), or
--   * a version is in expert_review with a window or a superseded version (its review snapshot
--     hashes them; return or decide it first).
-- The M1 event log keeps the expiry and supersession events as history.

begin;

do $$
begin
  if coalesce(current_setting('knowledge.m3_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'M3 rollback DROPS the expiry evidence and the validity windows: export them, then'
      ' set local knowledge.m3_rollback_evidence_exported = ''yes''';
  end if;
  if exists (select 1 from public.knowledge_documents d
              where d.status = 'approved'
                and not private.knowledge_in_force(d.effective_from, d.effective_to, d.approval_expires_on,
                                                   private.knowledge_policy_date(pg_catalog.now()))) then
    raise exception 'M3 rollback refused: approved versions are no longer in force (they would become'
      ' retrievable again); run private.knowledge_expire_documents, then quarantine any version it'
      ' leaves with private.knowledge_transition_document';
  end if;
  if exists (select 1 from public.knowledge_documents d
              where d.status = 'expert_review'
                and (d.effective_from is not null or d.effective_to is not null
                     or d.supersedes_document_pk is not null)) then
    raise exception 'M3 rollback refused: versions are in expert_review with a validity window or a'
      ' superseded version (their review snapshot covers them)';
  end if;
end;
$$;

drop policy knowledge_documents_select on public.knowledge_documents;
create policy knowledge_documents_select on public.knowledge_documents
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and status = 'approved'
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
      'chunker_version', d.chunker_version, 'license_basis', d.license_basis, 'license_reference', d.license_reference),
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
  -- M2 freeze: what the expert reviews is exactly what gets approved.
  if old.status = 'expert_review'
     and (new.title, new.language, new.official_url, new.artifact_ref, new.published_at, new.license_basis,
          new.license_reference)
         is distinct from
         (old.title, old.language, old.official_url, old.artifact_ref, old.published_at, old.license_basis,
          old.license_reference) then
    raise exception 'knowledge document % % % is under expert review; its artifact, license and metadata are'
      ' frozen (return it to review_required, or ingest a new version)',
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
  v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review',
    (case when p_decision = 'approve' then 'approved' else 'rejected' end)::public.knowledge_status,
    p_rationale, case when p_decision = 'approve' then v_actor.user_id end);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

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

drop function private.knowledge_expire_documents(integer);
drop function private.knowledge_expiry_due();
drop table public.knowledge_expiry_events;
drop function private.knowledge_expiry_events_guard();
drop function private.knowledge_supersede_for(uuid, boolean);
drop function private.knowledge_check_supersedes(text, uuid);

drop index public.knowledge_documents_supersedes_idx;
alter table public.knowledge_documents
  drop constraint knowledge_documents_approval_expiry_chk,
  drop constraint knowledge_documents_supersedes_self_chk,
  drop constraint knowledge_documents_effective_window_chk,
  drop column approval_expires_on,
  drop column supersedes_document_pk,
  drop column effective_to,
  drop column effective_from;

drop function private.knowledge_in_force(date, date, date, date);
drop function private.knowledge_approval_validity();
drop function private.knowledge_policy_date(timestamptz);
drop function private.knowledge_policy_time_zone();

commit;
