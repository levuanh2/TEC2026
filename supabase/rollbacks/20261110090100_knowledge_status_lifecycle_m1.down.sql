-- Rollback for migrations/20261110090100_knowledge_status_lifecycle_m1.sql AND
-- migrations/20261110090000_knowledge_status_m1_values.sql (RAG V1.5 M1).
-- Not in migrations/: run by hand, in ONE transaction, then
--   supabase migration repair --status reverted 20261110090100
--   supabase migration repair --status reverted 20261110090000
--
-- Refuses while any source or document version is in expert_review or quarantined: their rows
-- would otherwise be stranded in a state the restored Migration A triggers do not know.
-- Restores the three Migration A trigger functions verbatim (sources, documents, chunks) (direct status updates become possible
-- again, without audit) and drops M1's functions and the event log. DROPPING THE LOG DELETES THE
-- AUDIT HISTORY: export it first (copy public.knowledge_status_events to a file).
-- The enum values expert_review / quarantined stay in public.knowledge_status: PostgreSQL cannot
-- drop enum values. After this rollback nothing can reach them (the restored triggers allow only
-- the Migration A transitions).
begin;

do $$
begin
  if exists (select 1 from public.knowledge_sources where status::text in ('expert_review', 'quarantined'))
     or exists (select 1 from public.knowledge_documents where status::text in ('expert_review', 'quarantined')) then
    raise exception 'M1 rollback refused: rows are in expert_review or quarantined; archive/reject them first';
  end if;
end;
$$;

drop function if exists private.knowledge_transition_document(uuid, public.knowledge_status, public.knowledge_status, text, uuid);
drop function if exists private.knowledge_transition_source(text, public.knowledge_status, public.knowledge_status, text, uuid);

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
  if new.status in ('review_required', 'rejected') and (new.approved_by is not null or new.approved_at is not null) then
    raise exception 'knowledge source %: an approval record requires status approved', new.source_id
      using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if new.status = 'archived' then
      raise exception 'knowledge source %: only an approved source can be archived', new.source_id
        using errcode = '23514';
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
  if new.status <> old.status
     and not ((old.status in ('review_required', 'rejected') and new.status in ('review_required', 'rejected', 'approved'))
              or (old.status = 'approved' and new.status = 'archived')) then
    raise exception 'knowledge source %: status % -> % is not allowed (drafts -> approved; approved -> archived only; archived is final)',
      old.source_id, old.status, new.status using errcode = '23514';
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
  if new.status in ('review_required', 'rejected') and (new.approved_by is not null or new.approved_at is not null) then
    raise exception 'knowledge document % % %: an approval record requires status approved',
      new.source_id, new.document_id, new.document_version using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if new.status = 'archived' then
      raise exception 'knowledge document % % %: only an approved version can be archived',
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
  if new.status <> old.status
     and not ((old.status in ('review_required', 'rejected') and new.status in ('review_required', 'rejected', 'approved'))
              or (old.status = 'approved' and new.status = 'archived')) then
    raise exception 'knowledge document % % %: status % -> % is not allowed (drafts -> approved; approved -> archived only; archived is final)',
      old.source_id, old.document_id, old.document_version, old.status, new.status using errcode = '23514';
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
                 for share) then
    raise exception 'knowledge chunk % belongs to an approved version and cannot be deleted', old.chunk_id
      using errcode = '23514';
  end if;
  return old;
end;
$$;

drop function if exists private.knowledge_status_transition_authorized(text, text, public.knowledge_status);
drop table if exists public.knowledge_status_events;
drop function if exists private.knowledge_status_events_append_only();
drop function if exists private.knowledge_status_transition_allowed(text, public.knowledge_status, public.knowledge_status);

commit;
