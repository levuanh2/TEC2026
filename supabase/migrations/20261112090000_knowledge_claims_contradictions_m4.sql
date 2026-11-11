-- RAG V1.5 M4 (docs/rag/RAG_V15_SOURCE_CONTENT_INTEGRITY.md §3.3, §6): stored claims and
-- contradiction candidates. LOCAL/CI ONLY until the owner approves a hosted migration.
-- dev3-01 stays OPEN: a candidate is a REVIEW AID for a human expert, never a verdict. Nothing here
-- approves, rejects, quarantines, expires or hides anything, and retrieval, the answer path and the
-- approval flow do not read these tables.
-- Depends on M1 (20261110090100), M2 (20261110120000) and M3 (20261111090000).
-- Design: docs/rag/RAG_V15_M4_CLAIMS_CONTRADICTIONS.md.
--
-- What it adds
--   * public.knowledge_claims: one row per claim the deterministic extractor
--     (backend/knowledge/integrity/claims.py) found in one chunk of one document version, under one
--     extractor version. Each row is bound to the exact chunk: its content hash, the character span
--     and the raw text at that span. The database re-checks all three against the stored chunk, so
--     an invalid span, a foreign chunk or a stale hash is refused. The comparison key
--     (parameter|unit) is GENERATED: only an unambiguous quantity with a parameter, a canonical unit
--     and a range has one. Ambiguous and unsupported claims are stored as such and never compared.
--   * public.knowledge_contradiction_candidates: pairs of comparable claims whose value ranges do
--     not overlap, with a classification: contradiction, apparent_contradiction, missing_context or
--     insufficient_evidence. The database derives the classification itself
--     (private.knowledge_classify_claim_pair) from its own rows and refuses a proposal that
--     disagrees, so the stored label never depends on what a caller says.
--   * private.knowledge_document_evidence_state: active (approved, source approved, in force, M3),
--     candidate (review_required, expert_review) or inactive (everything else). A pair with an
--     inactive side is at most insufficient_evidence; a pair of two inactive sides is refused.
--   * private.knowledge_record_claims / private.knowledge_record_contradiction_candidates:
--     SECURITY DEFINER, search_path '', static SQL, EXECUTE service_role only. Both are idempotent
--     (a repeated or concurrent run inserts nothing twice).
--
-- Data boundaries: every row carries the scope of its source (public, or organization and farm),
-- copied by the database, never supplied. Claims of two different tenants, or of two different
-- farms of one tenant, are never paired. Both tables have RLS on and no client policy: tenants and
-- other clients read nothing; service_role reads for operations.
--
-- Evidence lifetime: rows are append-only. No UPDATE and no TRUNCATE for any role, the owner
-- included. A row disappears only together with its chunk or document version, which the M1 rules
-- allow only for a version that was never approved and is not under expert review.
--
-- Not in M4: no automatic quarantine, no change of any status, no read RPC for reviewers, no
-- reference registry (M5), no claim types beyond the extractor's, no numeric tolerance by default.

-- ================================================================== evidence state

-- SECURITY DEFINER: the operator (service_role) reads it for the analysis without any grant on the
-- M3 helpers. It reveals only a status the operator can already read.
create function private.knowledge_document_evidence_state(p_document_pk uuid, out state text, out reason text)
language sql
stable
security definer
set search_path = ''
as $$
  select case when d.status in ('review_required', 'expert_review') then 'candidate'
              when d.status = 'approved' and s.status = 'approved'
                   and private.knowledge_in_force(d.effective_from, d.effective_to, d.approval_expires_on,
                                                  private.knowledge_policy_date(pg_catalog.now())) then 'active'
              else 'inactive' end,
         case when d.status <> 'approved' then d.status::text
              when s.status <> 'approved' then 'source_' || s.status::text
              when not private.knowledge_in_force(d.effective_from, d.effective_to, d.approval_expires_on,
                                                  private.knowledge_policy_date(pg_catalog.now())) then 'not_in_force'
              else 'approved_in_force' end
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk;
$$;
revoke all on function private.knowledge_document_evidence_state(uuid) from public, anon, authenticated, service_role;
grant execute on function private.knowledge_document_evidence_state(uuid) to service_role;

-- ================================================================== claims

create table public.knowledge_claims (
  id bigint generated always as identity primary key,
  document_pk uuid not null references public.knowledge_documents(id) on delete cascade,
  chunk_pk bigint not null references public.knowledge_chunks(id) on delete cascade,
  source_id text not null,
  document_id text not null,
  document_version text not null,
  chunk_id text not null,
  -- the chunk content this claim was read from (public.knowledge_chunks.content_sha256 at extraction)
  chunk_content_sha256 text not null,
  extractor_version text not null,
  claim_id text not null,
  -- character span in the chunk content: substr(content, span_start + 1, span_end - span_start) = raw_text
  span_start integer not null,
  span_end integer not null,
  raw_text text not null,
  kind text not null,
  status text not null,
  parameter text,
  value_min numeric,
  value_max numeric,
  unit text,
  dimension text,
  date_iso date,
  stage text,
  scope_tags text[] not null default '{}',
  note text not null default '',
  -- one parameter in one canonical unit; null = not comparable (ambiguous, unsupported, no parameter)
  comparison_key text generated always as (
    case when kind = 'quantity' and status = 'extracted' and parameter is not null and unit is not null
              and value_min is not null and value_max is not null
         then parameter || '|' || unit end) stored,
  -- the scope of the source, copied by the database (the source scope is immutable)
  visibility text not null,
  organization_id uuid,
  farm_id uuid,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  actor_role text not null,
  constraint knowledge_claims_identity_key unique (document_pk, extractor_version, claim_id),
  constraint knowledge_claims_version_chk check (extractor_version ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
  constraint knowledge_claims_id_chk check (claim_id ~ '^cl-[0-9a-f]{16}$'),
  constraint knowledge_claims_span_chk check (
    span_start >= 0 and span_end > span_start and char_length(raw_text) = span_end - span_start
    and char_length(raw_text) <= 2000),
  constraint knowledge_claims_kind_chk check (kind in ('quantity', 'date', 'stage', 'assertion')),
  constraint knowledge_claims_status_chk check (status in ('extracted', 'ambiguous', 'unsupported')),
  constraint knowledge_claims_hash_chk check (chunk_content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint knowledge_claims_value_chk check (
    (value_min is null) = (value_max is null) and (value_min is null or value_min <= value_max)
    and (value_min is null or (kind = 'quantity' and unit is not null))),
  constraint knowledge_claims_text_chk check (
    (parameter is null or parameter ~ '^[a-z0-9][a-z0-9_.]{1,95}$')
    and (unit is null or (btrim(unit) <> '' and length(unit) <= 32))
    and (dimension is null or dimension ~ '^[a-z][a-z_]{1,31}$')
    and (stage is null or stage ~ '^[a-z][a-z_]{1,47}$')
    and length(note) <= 500 and cardinality(scope_tags) <= 16),
  constraint knowledge_claims_scope_chk check (
    (visibility = 'public' and organization_id is null and farm_id is null)
    or (visibility = 'tenant' and organization_id is not null))
);
create index knowledge_claims_comparison_idx on public.knowledge_claims (comparison_key, extractor_version)
  where comparison_key is not null;
create index knowledge_claims_chunk_idx on public.knowledge_claims (chunk_pk);
comment on table public.knowledge_claims is
  'M4: claims the deterministic extractor found, bound to the exact chunk span. A review aid, not a statement of fact.';

-- ================================================================== contradiction candidates

create table public.knowledge_contradiction_candidates (
  id bigint generated always as identity primary key,
  claim_a bigint not null references public.knowledge_claims(id) on delete cascade,
  claim_b bigint not null references public.knowledge_claims(id) on delete cascade,
  comparison_key text not null,
  classification text not null,
  reasons text[] not null,
  independence text not null,
  tolerance numeric not null default 0,
  tolerance_rationale text not null default '',
  analysis_version text not null,
  -- what the database saw when it accepted the pair
  policy_date date not null,
  evidence_state_a text not null,
  evidence_state_b text not null,
  -- the more private scope of the two claims
  visibility text not null,
  organization_id uuid,
  farm_id uuid,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  actor_role text not null,
  constraint knowledge_contradiction_candidates_pair_key
    unique (claim_a, claim_b, analysis_version, policy_date, classification),
  constraint knowledge_contradiction_candidates_order_chk check (claim_a < claim_b),
  constraint knowledge_contradiction_candidates_class_chk check (
    classification in ('contradiction', 'apparent_contradiction', 'missing_context', 'insufficient_evidence')),
  constraint knowledge_contradiction_candidates_state_chk check (
    evidence_state_a in ('active', 'candidate', 'inactive') and evidence_state_b in ('active', 'candidate', 'inactive')
    and not (evidence_state_a = 'inactive' and evidence_state_b = 'inactive')
    -- inactive material is never a contradiction of current guidance
    and ((evidence_state_a = 'inactive' or evidence_state_b = 'inactive') = (classification = 'insufficient_evidence'))),
  constraint knowledge_contradiction_candidates_independence_chk check (
    independence in ('same_document', 'same_source', 'independent_source')),
  constraint knowledge_contradiction_candidates_tolerance_chk check (
    tolerance >= 0 and length(tolerance_rationale) <= 1000
    and (tolerance = 0 or btrim(tolerance_rationale) <> '')),
  constraint knowledge_contradiction_candidates_version_chk check (analysis_version ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
  constraint knowledge_contradiction_candidates_reasons_chk check (cardinality(reasons) between 1 and 16),
  constraint knowledge_contradiction_candidates_scope_chk check (
    (visibility = 'public' and organization_id is null and farm_id is null)
    or (visibility = 'tenant' and organization_id is not null))
);
create index knowledge_contradiction_candidates_b_idx on public.knowledge_contradiction_candidates (claim_b);
comment on table public.knowledge_contradiction_candidates is
  'M4: pairs of comparable claims with disjoint values, classified by the database. A review aid, never a verdict.';

-- ================================================================== privileges and guards

alter table public.knowledge_claims enable row level security;
alter table public.knowledge_contradiction_candidates enable row level security;
revoke all on public.knowledge_claims, public.knowledge_contradiction_candidates
  from public, anon, authenticated, service_role;
grant select on public.knowledge_claims, public.knowledge_contradiction_candidates to service_role;

-- Append-only. INSERT only inside the recording functions (the M2 write marker: current_user is the
-- evidence owner and the transaction-local marker names the table). UPDATE never. DELETE only as the
-- cascade of a deleted chunk or document version (claims) or of a deleted claim (candidates): the M1
-- triggers allow that only for a version that was never approved and is not under expert review.
create function private.knowledge_claim_evidence_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if not private.knowledge_m2_write_authorized(tg_table_name) then
      raise exception '%: rows are written only by the M4 recording functions', tg_table_name using errcode = '42501';
    end if;
    return new;
  end if;
  -- nested: an expression is planned only when reached, and each table has its own columns
  if tg_op = 'DELETE' then
    if tg_table_name = 'knowledge_claims' then
      if not exists (select 1 from public.knowledge_documents d where d.id = old.document_pk)
         or not exists (select 1 from public.knowledge_chunks c where c.id = old.chunk_pk) then
        return old;
      end if;
    elsif tg_table_name = 'knowledge_contradiction_candidates' then
      if not exists (select 1 from public.knowledge_claims c where c.id = old.claim_a)
         or not exists (select 1 from public.knowledge_claims c where c.id = old.claim_b) then
        return old;
      end if;
    end if;
  end if;
  raise exception '% is append-only evidence: % is refused', tg_table_name, tg_op using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_claim_evidence_guard() from public, anon, authenticated, service_role;

create trigger knowledge_claims_guard
  before insert or update or delete on public.knowledge_claims
  for each row execute function private.knowledge_claim_evidence_guard();
create trigger knowledge_claims_no_truncate
  before truncate on public.knowledge_claims
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_contradiction_candidates_guard
  before insert or update or delete on public.knowledge_contradiction_candidates
  for each row execute function private.knowledge_claim_evidence_guard();
create trigger knowledge_contradiction_candidates_no_truncate
  before truncate on public.knowledge_contradiction_candidates
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== recording claims

-- Stores the claims of one document version under one extractor version. p_claims is the extractor's
-- output (a JSON array). Every element is checked against the stored chunk: it must be a chunk of
-- this version, and the raw text must be exactly the chunk content at the span. Idempotent: an
-- identical claim is skipped; the same claim id with other facts under the same extractor version
-- is refused (the extractor changed without a version bump). Returns the number of rows inserted.
create function private.knowledge_record_claims(p_document_pk uuid, p_extractor_version text, p_claims jsonb)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_doc record;
  v_item jsonb;
  v_chunk record;
  v_start integer;
  v_end integer;
  v_tags text[];
  v_new record;
  v_old record;
  v_id bigint;
  v_count integer := 0;
begin
  if p_extractor_version is null or p_extractor_version !~ '^[a-z0-9][a-z0-9._-]{1,63}$' then
    raise exception 'claims need an extractor version' using errcode = '22023';
  end if;
  if p_claims is null or pg_catalog.jsonb_typeof(p_claims) <> 'array' or pg_catalog.jsonb_array_length(p_claims) > 5000 then
    raise exception 'claims are a JSON array of at most 5000 items' using errcode = '22023';
  end if;
  select d.id, d.source_id, d.document_id, d.document_version, s.visibility, s.organization_id, s.farm_id
    into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk for share of d;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  for v_item in select e from pg_catalog.jsonb_array_elements(p_claims) e loop
    if pg_catalog.jsonb_typeof(v_item) <> 'object'
       or pg_catalog.jsonb_typeof(v_item -> 'chunk_id') is distinct from 'string'
       or pg_catalog.jsonb_typeof(v_item -> 'claim_id') is distinct from 'string'
       or pg_catalog.jsonb_typeof(v_item -> 'raw_text') is distinct from 'string'
       or pg_catalog.jsonb_typeof(v_item -> 'span_start') is distinct from 'number'
       or pg_catalog.jsonb_typeof(v_item -> 'span_end') is distinct from 'number'
       or coalesce(pg_catalog.jsonb_typeof(v_item -> 'scope_tags'), 'array') <> 'array'
       or coalesce(pg_catalog.jsonb_typeof(v_item -> 'value_min'), 'null') not in ('number', 'null')
       or coalesce(pg_catalog.jsonb_typeof(v_item -> 'value_max'), 'null') not in ('number', 'null')
       or (pg_catalog.jsonb_typeof(v_item -> 'date_iso') = 'string'
           and (v_item ->> 'date_iso') !~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$')
       or coalesce(pg_catalog.jsonb_typeof(v_item -> 'date_iso'), 'null') not in ('string', 'null')
       or exists (select 1 from pg_catalog.jsonb_array_elements(coalesce(v_item -> 'scope_tags', '[]'::jsonb)) t
                   where pg_catalog.jsonb_typeof(t) <> 'string')
       or (v_item ->> 'span_start') !~ '^[0-9]{1,9}$' or (v_item ->> 'span_end') !~ '^[0-9]{1,9}$' then
      raise exception 'a claim names its chunk, id, raw text and an integer span; values are numbers and a date is yyyy-mm-dd'
        using errcode = '22023';
    end if;
    v_start := (v_item ->> 'span_start')::integer;
    v_end := (v_item ->> 'span_end')::integer;
    select c.id, c.content, c.content_sha256 into v_chunk
      from public.knowledge_chunks c where c.document_pk = p_document_pk and c.chunk_id = v_item ->> 'chunk_id';
    if not found then
      raise exception 'claim %: chunk % is not a chunk of this document version', v_item ->> 'claim_id',
        v_item ->> 'chunk_id' using errcode = '23503';
    end if;
    if v_end <= v_start or v_end > char_length(v_chunk.content)
       or substr(v_chunk.content, v_start + 1, v_end - v_start) is distinct from (v_item ->> 'raw_text') then
      raise exception 'claim %: the evidence span [%, %) is not this text in chunk %', v_item ->> 'claim_id',
        v_start, v_end, v_item ->> 'chunk_id' using errcode = '23514';
    end if;
    select coalesce(pg_catalog.array_agg(distinct t order by t), '{}') into v_tags
      from pg_catalog.jsonb_array_elements_text(coalesce(v_item -> 'scope_tags', '[]'::jsonb)) t;
    select v_item ->> 'kind' as kind, v_item ->> 'status' as status, v_item ->> 'parameter' as parameter,
           (v_item ->> 'value_min')::numeric as value_min, (v_item ->> 'value_max')::numeric as value_max,
           v_item ->> 'unit' as unit, v_item ->> 'dimension' as dimension, (v_item ->> 'date_iso')::date as date_iso,
           v_item ->> 'stage' as stage, coalesce(v_item ->> 'note', '') as note
      into v_new;
    perform private.knowledge_m2_set_marker('knowledge_claims');
    insert into public.knowledge_claims (document_pk, chunk_pk, source_id, document_id, document_version, chunk_id,
      chunk_content_sha256, extractor_version, claim_id, span_start, span_end, raw_text, kind, status, parameter,
      value_min, value_max, unit, dimension, date_iso, stage, scope_tags, note, visibility, organization_id, farm_id,
      actor_role)
    values (p_document_pk, v_chunk.id, v_doc.source_id, v_doc.document_id, v_doc.document_version,
      v_item ->> 'chunk_id', v_chunk.content_sha256, p_extractor_version, v_item ->> 'claim_id', v_start, v_end,
      v_item ->> 'raw_text', v_new.kind, v_new.status, v_new.parameter, v_new.value_min, v_new.value_max, v_new.unit,
      v_new.dimension, v_new.date_iso, v_new.stage, v_tags, v_new.note, v_doc.visibility, v_doc.organization_id,
      v_doc.farm_id, coalesce(nullif(current_setting('role', true), 'none'), session_user))
    on conflict (document_pk, extractor_version, claim_id) do nothing
    returning id into v_id;
    perform private.knowledge_m2_set_marker(null);
    if v_id is not null then
      v_count := v_count + 1;
    else
      select c.chunk_pk, c.span_start, c.span_end, c.raw_text, c.kind, c.status, c.parameter, c.value_min, c.value_max,
             c.unit, c.dimension, c.date_iso, c.stage, c.scope_tags, c.note into v_old
        from public.knowledge_claims c
       where c.document_pk = p_document_pk and c.extractor_version = p_extractor_version
         and c.claim_id = v_item ->> 'claim_id';
      if (v_old.chunk_pk, v_old.span_start, v_old.span_end, v_old.raw_text, v_old.kind, v_old.status, v_old.parameter,
          v_old.value_min, v_old.value_max, v_old.unit, v_old.dimension, v_old.date_iso, v_old.stage, v_old.scope_tags,
          v_old.note)
         is distinct from
         (v_chunk.id, v_start, v_end, v_item ->> 'raw_text', v_new.kind, v_new.status, v_new.parameter, v_new.value_min,
          v_new.value_max, v_new.unit, v_new.dimension, v_new.date_iso, v_new.stage, v_tags, v_new.note) then
        raise exception 'claim % is already stored with other facts under extractor version % (bump the version)',
          v_item ->> 'claim_id', p_extractor_version using errcode = '23514';
      end if;
    end if;
  end loop;
  return v_count;
end;
$$;

-- ================================================================== classifying a pair

-- The database's own reading of one pair of stored claims. `comparable` is false (with the reason)
-- when the pair must not be reported at all; otherwise `classification` is the only label the pair
-- may carry. p_tolerance widens both ranges; it is 0 unless the caller supplies a justified value.
create function private.knowledge_classify_claim_pair(
  p_claim_a bigint, p_claim_b bigint, p_tolerance numeric,
  out comparable boolean, out reason text, out classification text, out comparison_key text,
  out evidence_state_a text, out evidence_state_b text, out independence text,
  out visibility text, out organization_id uuid, out farm_id uuid)
language plpgsql
stable
set search_path = ''
as $$
declare
  v_a record;
  v_b record;
  v_reason_a text;
  v_reason_b text;
  v_explained boolean;
begin
  comparable := false;
  select c.*, d.effective_from, d.effective_to, d.supersedes_document_pk into v_a
    from public.knowledge_claims c join public.knowledge_documents d on d.id = c.document_pk where c.id = p_claim_a;
  if not found then reason := 'unknown_claim'; return; end if;
  select c.*, d.effective_from, d.effective_to, d.supersedes_document_pk into v_b
    from public.knowledge_claims c join public.knowledge_documents d on d.id = c.document_pk where c.id = p_claim_b;
  if not found then reason := 'unknown_claim'; return; end if;
  if v_a.comparison_key is null or v_a.comparison_key is distinct from v_b.comparison_key
     or v_a.extractor_version <> v_b.extractor_version then
    reason := 'not_comparable'; return;
  end if;
  comparison_key := v_a.comparison_key;
  if v_a.chunk_pk = v_b.chunk_pk then reason := 'same_chunk'; return; end if;
  -- data boundary: public with anything; a tenant only with itself, and not two different farms
  if v_a.visibility = 'tenant' and v_b.visibility = 'tenant'
     and (v_a.organization_id <> v_b.organization_id
          or (v_a.farm_id is not null and v_b.farm_id is not null and v_a.farm_id <> v_b.farm_id)) then
    reason := 'scope_boundary'; return;
  end if;
  if v_a.stage is not null and v_b.stage is not null and v_a.stage <> v_b.stage then
    reason := 'different_stage'; return;
  end if;
  select s.state, s.reason into evidence_state_a, v_reason_a from private.knowledge_document_evidence_state(v_a.document_pk) s;
  select s.state, s.reason into evidence_state_b, v_reason_b from private.knowledge_document_evidence_state(v_b.document_pk) s;
  if evidence_state_a = 'inactive' and evidence_state_b = 'inactive' then reason := 'both_inactive'; return; end if;
  if v_a.value_min <= v_b.value_max + p_tolerance and v_b.value_min <= v_a.value_max + p_tolerance then
    reason := 'consistent'; return;
  end if;
  comparable := true;
  independence := case when v_a.document_pk = v_b.document_pk then 'same_document'
                       when v_a.source_id = v_b.source_id then 'same_source' else 'independent_source' end;
  if v_a.visibility = 'tenant' then
    visibility := 'tenant'; organization_id := v_a.organization_id; farm_id := coalesce(v_a.farm_id, case
      when v_b.visibility = 'tenant' then v_b.farm_id end);
  elsif v_b.visibility = 'tenant' then
    visibility := 'tenant'; organization_id := v_b.organization_id; farm_id := v_b.farm_id;
  else
    visibility := 'public';
  end if;
  if evidence_state_a = 'inactive' or evidence_state_b = 'inactive' then
    classification := 'insufficient_evidence'; return;
  end if;
  v_explained := v_a.document_pk <> v_b.document_pk and (
    -- one version supersedes the other, directly or through a chain (bounded walk, no cycles by M3)
    exists (with recursive chain(id, depth) as (
              select d.supersedes_document_pk, 1 from public.knowledge_documents d
               where d.id in (v_a.document_pk, v_b.document_pk) and d.supersedes_document_pk is not null
              union
              select d.supersedes_document_pk, chain.depth + 1 from chain
                join public.knowledge_documents d on d.id = chain.id
               where d.supersedes_document_pk is not null and chain.depth < 64)
            select 1 from chain where chain.id in (v_a.document_pk, v_b.document_pk))
    or (v_a.effective_to is not null and v_b.effective_from is not null and v_a.effective_to < v_b.effective_from)
    or (v_b.effective_to is not null and v_a.effective_from is not null and v_b.effective_to < v_a.effective_from)
    or (v_a.source_id = v_b.source_id and v_a.document_id = v_b.document_id));
  if v_explained then
    classification := 'apparent_contradiction';
  elsif (v_a.stage is null) <> (v_b.stage is null) or v_a.scope_tags <> v_b.scope_tags then
    classification := 'missing_context';
  else
    classification := 'contradiction';
  end if;
end;
$$;
revoke all on function private.knowledge_classify_claim_pair(bigint, bigint, numeric)
  from public, anon, authenticated, service_role;

-- ================================================================== recording candidates

-- Stores candidate pairs proposed by the analysis (backend/knowledge/integrity/contradictions.py).
-- The database classifies every pair itself and refuses a proposal that is not comparable or whose
-- classification differs from its own (23514): a stored label is always the database's. Idempotent
-- per (pair, analysis version, policy date, classification). Returns the number of rows inserted.
create function private.knowledge_record_contradiction_candidates(p_analysis_version text, p_candidates jsonb)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_item jsonb;
  v_a bigint;
  v_b bigint;
  v_tolerance numeric;
  v_rationale text;
  v_reasons text[];
  v_pair record;
  v_id bigint;
  v_count integer := 0;
  v_today date := private.knowledge_policy_date(pg_catalog.now());
begin
  if p_analysis_version is null or p_analysis_version !~ '^[a-z0-9][a-z0-9._-]{1,63}$' then
    raise exception 'candidates need an analysis version' using errcode = '22023';
  end if;
  if p_candidates is null or pg_catalog.jsonb_typeof(p_candidates) <> 'array'
     or pg_catalog.jsonb_array_length(p_candidates) > 5000 then
    raise exception 'candidates are a JSON array of at most 5000 items' using errcode = '22023';
  end if;
  for v_item in select e from pg_catalog.jsonb_array_elements(p_candidates) e loop
    if pg_catalog.jsonb_typeof(v_item) <> 'object'
       or (v_item ->> 'claim_a') is null or (v_item ->> 'claim_a') !~ '^[0-9]{1,18}$'
       or (v_item ->> 'claim_b') is null or (v_item ->> 'claim_b') !~ '^[0-9]{1,18}$'
       or pg_catalog.jsonb_typeof(v_item -> 'classification') is distinct from 'string'
       or pg_catalog.jsonb_typeof(v_item -> 'reasons') is distinct from 'array'
       or coalesce(pg_catalog.jsonb_typeof(v_item -> 'tolerance'), 'number') <> 'number' then
      raise exception 'a candidate names two claims, a classification and its reasons' using errcode = '22023';
    end if;
    v_a := (v_item ->> 'claim_a')::bigint;
    v_b := (v_item ->> 'claim_b')::bigint;
    v_tolerance := coalesce((v_item ->> 'tolerance')::numeric, 0);
    v_rationale := coalesce(v_item ->> 'tolerance_rationale', '');
    if v_a >= v_b or v_tolerance < 0 or (v_tolerance > 0 and btrim(v_rationale) = '') then
      raise exception 'a candidate orders its claims (a < b); a tolerance is >= 0 and justified' using errcode = '22023';
    end if;
    -- both claims stay as they are until this transaction ends (rows are immutable; this blocks a
    -- concurrent cascade delete of a draft)
    perform 1 from public.knowledge_claims c where c.id in (v_a, v_b) order by c.id for share;
    select * into v_pair from private.knowledge_classify_claim_pair(v_a, v_b, v_tolerance);
    if not v_pair.comparable then
      raise exception 'claims % and % are not a reportable pair (%)', v_a, v_b, v_pair.reason using errcode = '23514';
    end if;
    if v_pair.classification is distinct from (v_item ->> 'classification') then
      raise exception 'claims % and %: the database classifies this pair as %, not %', v_a, v_b,
        v_pair.classification, v_item ->> 'classification' using errcode = '23514';
    end if;
    if v_pair.independence is distinct from coalesce(v_item ->> 'independence', v_pair.independence) then
      raise exception 'claims % and %: independence is %', v_a, v_b, v_pair.independence using errcode = '23514';
    end if;
    select coalesce(pg_catalog.array_agg(t), '{}') into v_reasons
      from pg_catalog.jsonb_array_elements_text(v_item -> 'reasons') t;
    perform private.knowledge_m2_set_marker('knowledge_contradiction_candidates');
    insert into public.knowledge_contradiction_candidates (claim_a, claim_b, comparison_key, classification, reasons,
      independence, tolerance, tolerance_rationale, analysis_version, policy_date, evidence_state_a, evidence_state_b,
      visibility, organization_id, farm_id, actor_role)
    values (v_a, v_b, v_pair.comparison_key, v_pair.classification, v_reasons, v_pair.independence, v_tolerance,
      v_rationale, p_analysis_version, v_today, v_pair.evidence_state_a, v_pair.evidence_state_b, v_pair.visibility,
      v_pair.organization_id, v_pair.farm_id, coalesce(nullif(current_setting('role', true), 'none'), session_user))
    on conflict (claim_a, claim_b, analysis_version, policy_date, classification) do nothing
    returning id into v_id;
    perform private.knowledge_m2_set_marker(null);
    if v_id is not null then
      v_count := v_count + 1;
    end if;
  end loop;
  return v_count;
end;
$$;

revoke all on function private.knowledge_record_claims(uuid, text, jsonb) from public, anon, authenticated, service_role;
revoke all on function private.knowledge_record_contradiction_candidates(text, jsonb)
  from public, anon, authenticated, service_role;
grant execute on function private.knowledge_record_claims(uuid, text, jsonb) to service_role;
grant execute on function private.knowledge_record_contradiction_candidates(text, jsonb) to service_role;
