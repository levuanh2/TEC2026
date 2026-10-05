-- RAG V1.3-B — knowledge LEXICAL storage foundation (docs/rag/RAG_V1_RETRIEVAL_ADR.md §9,
-- docs/rag/RAG_V1_SOURCE_POLICY.md). Migration A of two: lexical only.
--
-- NO pgvector: no `vector` extension, no embedding column, no vector index, no vector RPC
-- (E1 = C, lexical-first; a vector Migration B is additive and gated on measured evaluation).
--
-- Three tables, all read-only to clients:
--   knowledge_sources    a publisher/series; carries visibility and tenant scope
--   knowledge_documents  one immutable version of one document (citation identity)
--   knowledge_chunks     citable passages + DB-maintained search fields
-- Ingestion and approval are operator actions (service role / database owner), never a
-- request path: `authenticated` gets SELECT only and RLS shows approved rows in scope, and
-- nothing at all while the caller's Core V1 password change is pending; `anon` gets nothing.
--
-- Retrieval is `public.match_knowledge_chunks_lexical`, SECURITY INVOKER: it runs as the
-- caller (RLS active everywhere), derives organization/farm from the crop season the caller
-- can read, and accepts no scope/visibility/status filter.
--
-- Core V1 tables, functions and policies are not modified.

create extension if not exists pg_trgm with schema extensions;
create extension if not exists unaccent with schema extensions;

create type public.knowledge_status as enum ('review_required', 'approved', 'rejected', 'archived');
-- 'unknown' is the default and can never be approved (CHECK below).
create type public.knowledge_license_basis as enum (
  'unknown', 'official_publication', 'public_domain', 'open_license', 'written_permission', 'tenant_owned'
);

-- ------------------------------------------------------------------ sources

create table public.knowledge_sources (
  source_id text primary key,
  title text not null,
  owner text not null,
  source_type text not null,
  authority text,
  visibility text not null,
  organization_id uuid references public.organizations(id) on delete restrict,
  farm_id uuid references public.farms(id) on delete restrict,
  status public.knowledge_status not null default 'review_required',
  approved_by uuid references auth.users(id) on delete restrict,
  approved_at timestamptz,
  review_note text,
  created_at timestamptz not null default now(),
  constraint knowledge_sources_id_chk check (source_id ~ '^[a-z0-9][a-z0-9-]{1,63}$'),
  constraint knowledge_sources_title_chk check (btrim(title) <> '' and btrim(owner) <> ''),
  constraint knowledge_sources_type_chk check (
    source_type in ('guideline', 'policy', 'methodology', 'research', 'tenant_document')),
  constraint knowledge_sources_authority_chk check (
    authority is null or authority in ('official', 'peer_reviewed', 'extension', 'internal')),
  -- PUBLIC: no organization, no farm. TENANT: an organization (farm optional, see trigger).
  constraint knowledge_sources_scope_chk check (
    (visibility = 'public' and organization_id is null and farm_id is null)
    or (visibility = 'tenant' and organization_id is not null)),
  -- Approval: the publisher was verified by a named human, and how is recorded.
  constraint knowledge_sources_approval_chk check (
    status <> 'approved'
    or (approved_by is not null and approved_at is not null and nullif(btrim(review_note), '') is not null))
);

-- ---------------------------------------------------------------- documents

create table public.knowledge_documents (
  id uuid primary key default gen_random_uuid(),
  source_id text not null references public.knowledge_sources(source_id) on delete restrict,
  document_id text not null,
  document_version text not null,
  title text not null,
  language text not null,
  official_url text,
  artifact_ref text,
  file_sha256 text not null,
  normalized_sha256 text not null,
  published_at date,
  imported_at timestamptz not null default now(),
  parser_version text not null,
  normalizer_version text not null,
  chunker_version text not null,
  license_basis public.knowledge_license_basis not null default 'unknown',
  license_reference text,
  status public.knowledge_status not null default 'review_required',
  approved_by uuid references auth.users(id) on delete restrict,
  approved_at timestamptz,
  review_note text,
  constraint knowledge_documents_identity_key unique (source_id, document_id, document_version),
  constraint knowledge_documents_id_chk check (document_id ~ '^[a-z0-9][a-z0-9-]{1,127}$'),
  constraint knowledge_documents_version_chk check (btrim(document_version) <> '' and btrim(title) <> ''),
  constraint knowledge_documents_language_chk check (language ~ '^[a-z]{2}$'),
  constraint knowledge_documents_url_chk check (official_url is null or official_url ~ '^https://\S+$'),
  constraint knowledge_documents_artifact_chk check (
    official_url is not null or nullif(btrim(artifact_ref), '') is not null),
  constraint knowledge_documents_hash_chk check (
    file_sha256 ~ '^[0-9a-f]{64}$' and normalized_sha256 ~ '^[0-9a-f]{64}$'),
  constraint knowledge_documents_pipeline_chk check (
    btrim(parser_version) <> '' and btrim(normalizer_version) <> '' and btrim(chunker_version) <> ''),
  -- Approval: named approver and time, the reviewer's explanation, a KNOWN license basis,
  -- and a reference for the bases that need one. Unknown provenance can never be approved.
  constraint knowledge_documents_approval_chk check (
    status <> 'approved'
    or (approved_by is not null and approved_at is not null and nullif(btrim(review_note), '') is not null
        and license_basis <> 'unknown'
        and (license_basis not in ('open_license', 'written_permission')
             or nullif(btrim(license_reference), '') is not null)))
);

-- At most one approved version per (source_id, document_id); a new review_required version
-- coexists with it until approval archives the old one (same transaction, operator path).
create unique index knowledge_documents_one_approved
  on public.knowledge_documents (source_id, document_id)
  where status = 'approved';

-- ------------------------------------------------------------------- chunks

create table public.knowledge_chunks (
  id bigint generated always as identity primary key,
  document_pk uuid not null references public.knowledge_documents(id) on delete restrict,
  chunk_id text not null,
  ordinal integer not null,
  section_path text,
  page_from integer,
  page_to integer,
  content text not null,
  content_sha256 text not null,
  metadata jsonb not null default '{}'::jsonb,
  -- Maintained by private.knowledge_chunks_search_fields(); any supplied value is replaced.
  search_text text not null,
  search_tsv tsvector not null,
  constraint knowledge_chunks_chunk_key unique (document_pk, chunk_id),
  constraint knowledge_chunks_ordinal_key unique (document_pk, ordinal),
  constraint knowledge_chunks_id_chk check (chunk_id ~ '^[0-9a-f]{20}$'),
  constraint knowledge_chunks_ordinal_chk check (ordinal >= 0),
  constraint knowledge_chunks_pages_chk check (
    (page_from is null or page_from >= 1) and (page_to is null or page_to >= coalesce(page_from, 1))),
  constraint knowledge_chunks_content_chk check (btrim(content) <> ''),
  constraint knowledge_chunks_hash_chk check (content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint knowledge_chunks_metadata_chk check (jsonb_typeof(metadata) = 'object')
);

-- --------------------------------------------------------- search normalization

-- THE search normalization (single source of truth, used by the chunk trigger and by the
-- RPC for the query): NFC, unaccent ("tưới" -> "tuoi", "đ" -> "d"), lower case, collapsed
-- whitespace. STABLE, not IMMUTABLE: unaccent with a dictionary argument is stable, and no
-- expression index depends on it (the GIN indexes are on the stored columns).
create function private.knowledge_search_text(p_text text)
returns text
language sql
stable
parallel safe
set search_path = ''
as $$
  select btrim(regexp_replace(
    lower(extensions.unaccent('extensions.unaccent'::regdictionary, normalize(coalesce(p_text, ''), nfc))),
    '\s+', ' ', 'g'));
$$;
revoke all on function private.knowledge_search_text(text) from public, anon, authenticated;
grant execute on function private.knowledge_search_text(text) to authenticated, service_role;

create function private.knowledge_chunks_search_fields()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.search_text := private.knowledge_search_text(concat_ws(' ', new.section_path, new.content));
  new.search_tsv := to_tsvector('simple'::regconfig, new.search_text);
  return new;
end;
$$;
revoke all on function private.knowledge_chunks_search_fields() from public, anon, authenticated;

create trigger knowledge_chunks_search_fields
  before insert on public.knowledge_chunks
  for each row execute function private.knowledge_chunks_search_fields();

create index knowledge_chunks_search_tsv_idx on public.knowledge_chunks using gin (search_tsv);
create index knowledge_chunks_search_trgm_idx
  on public.knowledge_chunks using gin (search_text extensions.gin_trgm_ops);

-- ----------------------------------------------------------- invariants

-- Sources. Tenant scope: a farm-scoped tenant source is created for a farm of ITS
-- organization. The scope is fixed once created (re-scoping = a new source), so the farm
-- relation is checked at INSERT only: Core V1 does not freeze farms.cooperative_id, the RLS
-- policy and the RPC re-check it at read time (a moved farm makes the source unretrievable),
-- and an operator can still archive such a stale source. The publisher provenance and the
-- approval record are fixed once the source has been approved; status may still move, but
-- `archived` is final (decision ST2: archive-only lifecycle -- re-publishing needs a new,
-- newly approved source) and a source that was ever approved is never deleted.
create function private.enforce_knowledge_source_scope()
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
  if tg_op = 'INSERT' then
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
  if old.status = 'archived' and new.status <> 'archived' then
    raise exception 'knowledge source % is archived; archiving is final', old.source_id using errcode = '23514';
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
revoke all on function private.enforce_knowledge_source_scope() from public, anon, authenticated;

create trigger knowledge_sources_scope
  before insert or update or delete on public.knowledge_sources
  for each row execute function private.enforce_knowledge_source_scope();

-- Citation identity and provenance never change: identity, hashes and pipeline versions
-- are fixed at insert; descriptive provenance, license and the approval record are fixed
-- once a version has been approved. Status may still move (approved -> archived), but
-- `archived` is final (ST2: a withdrawn version never becomes retrievable again; a new
-- version is ingested and approved instead). A version that was ever approved cannot be
-- deleted.
create function private.enforce_knowledge_document_immutability()
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
  if (new.id, new.source_id, new.document_id, new.document_version, new.file_sha256, new.normalized_sha256,
      new.parser_version, new.normalizer_version, new.chunker_version, new.imported_at)
      is distinct from
     (old.id, old.source_id, old.document_id, old.document_version, old.file_sha256, old.normalized_sha256,
      old.parser_version, old.normalizer_version, old.chunker_version, old.imported_at) then
    raise exception 'knowledge document % % % identity/provenance is immutable',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  if old.status = 'archived' and new.status <> 'archived' then
    raise exception 'knowledge document % % % is archived; archiving is final',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
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
revoke all on function private.enforce_knowledge_document_immutability() from public, anon, authenticated;

create trigger knowledge_documents_immutable
  before update or delete on public.knowledge_documents
  for each row execute function private.enforce_knowledge_document_immutability();

-- Chunks belong to a version's content: they are added only while the version is still
-- `review_required` and was never approved (ingest -> review -> approve; the parent row is
-- share-locked so an approval cannot race an insert), never edited, and deleted only while
-- the version was never approved.
create function private.enforce_knowledge_chunk_immutability()
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
  if exists (select 1 from public.knowledge_documents d where d.id = old.document_pk and d.approved_at is not null) then
    raise exception 'knowledge chunk % belongs to an approved version and cannot be deleted', old.chunk_id
      using errcode = '23514';
  end if;
  return old;
end;
$$;
revoke all on function private.enforce_knowledge_chunk_immutability() from public, anon, authenticated;

create trigger knowledge_chunks_immutable
  before insert or update or delete on public.knowledge_chunks
  for each row execute function private.enforce_knowledge_chunk_immutability();

-- ---------------------------------------------------------------------- RLS

alter table public.knowledge_sources enable row level security;
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_chunks enable row level security;

-- Clients read only; writes are denied at the privilege level, not just by RLS.
revoke all on public.knowledge_sources, public.knowledge_documents, public.knowledge_chunks
  from public, anon, authenticated;
grant select on public.knowledge_sources, public.knowledge_documents, public.knowledge_chunks to authenticated;

-- Core V1 forced password change (20261002100000 + 20261003090000): while a change is
-- pending -- the live auth.users flag, or an access token minted with the claim (a stale
-- TOKEN_OLD stays refused after the change) -- the caller sees NO knowledge row. "Public"
-- means public to a valid business user, not a bypass of that state. The decision is
-- private.password_change_pending() itself, unchanged; this definer wrapper only lets the
-- invoker policies below consult it without granting `authenticated` EXECUTE on the Core V1
-- helper.
create function private.knowledge_read_blocked()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select private.password_change_pending();
$$;
revoke all on function private.knowledge_read_blocked() from public, anon, authenticated;
grant execute on function private.knowledge_read_blocked() to authenticated;

-- An APPROVED source in scope: public reference knowledge for any signed-in user without a
-- pending password change; tenant knowledge only for an active member of its organization
-- (existing Core V1 semantics: a former member or a data-grant viewer of another
-- organization is not a member), and for a farm-scoped source only when the caller can read
-- that farm AND the farm still belongs to the source's organization.
create policy knowledge_sources_select on public.knowledge_sources
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and status = 'approved'
    and (
      visibility = 'public'
      or (
        visibility = 'tenant'
        and private.user_is_org_member(organization_id)
        and (
          farm_id is null
          or (private.user_can_read_farm(farm_id)
              and exists (select 1 from public.farms f
                          where f.id = knowledge_sources.farm_id and f.cooperative_id = knowledge_sources.organization_id))
        )
      )
    )
  );

-- An APPROVED version of a source the caller may see (that source's own RLS applies). The
-- password guard is repeated on each table so no read path depends on the chain alone.
create policy knowledge_documents_select on public.knowledge_documents
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and status = 'approved'
    and exists (select 1 from public.knowledge_sources s where s.source_id = knowledge_documents.source_id)
  );

-- A chunk of a version the caller may see.
create policy knowledge_chunks_select on public.knowledge_chunks
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and exists (select 1 from public.knowledge_documents d where d.id = knowledge_chunks.document_pk)
  );

-- -------------------------------------------------------------- lexical RPC

-- Candidates: full-text and trigram, at most 50 each.
--   * Full-text matches ANY lexeme of the normalized question (an OR of plainto_tsquery's
--     lexemes): a farmer asks a sentence ("AWD là gì và vì sao ...") and the 'simple' config
--     has no stopwords, so requiring every word would find nothing. ts_rank_cd ranks passages
--     covering more of the question higher. Postgres FTS has no IDF, so frequent function words
--     also match; that is measured on the DEV split (a stopword list would be tuning).
--   * Trigram (`q <% search_text`, i.e. word_similarity >= the pg_trgm default threshold,
--     ranked by word_similarity) serves short queries, acronyms and misspellings.
-- The two rank lists are
-- fused by Reciprocal Rank Fusion, sum(1 / (60 + rank)) (k = 60, Cormack et al. 2009):
-- ranks, not raw scores, so no tuned weight. Ties break on stable citation identity.
-- `fused_score` is only comparable within this lexical method; a relevance cutoff is the
-- caller's, calibrated on the DEV evaluation split. An empty result is a valid answer.
--
-- Scope comes only from the crop season the caller can read (RLS on crop_seasons, plots,
-- farms): an unreadable or unknown season returns nothing, not even public chunks. A caller
-- with a pending password change gets nothing twice over: no readable season, and no
-- knowledge row under the knowledge RLS above.
create function public.match_knowledge_chunks_lexical(
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
revoke all on function public.match_knowledge_chunks_lexical(uuid, text, integer) from public, anon, authenticated;
grant execute on function public.match_knowledge_chunks_lexical(uuid, text, integer) to authenticated, service_role;
