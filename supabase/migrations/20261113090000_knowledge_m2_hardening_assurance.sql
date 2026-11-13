-- RAG V1.5 M2 hardening H-a (docs/rag/RAG_V15_H_A_DEMO_ASSURANCE_ISOLATION.md): demo assurance is
-- separated at the database, at RLS and at retrieval, and demo approval runs only on an isolated test
-- database. LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN.
-- Depends on M2 (20261110120000), M3 (20261111090000), M4 (20261112090000), M4.1 (20261112120000).
--
-- Owner decision D-H3a (2026-11-12): demo-approved content runs ONLY on a physically or logically
-- isolated local or dedicated test database, never on the shared hosted project.
--
-- What it adds
--   * knowledge_documents.approval_assurance / knowledge_sources.approval_assurance:
--     'verified' | 'demo_unverified' | 'unrecorded', set iff approved_at is set. Written ONLY by a row
--     trigger, from the approval record of the same transaction (the caller's value is ignored), and
--     immutable afterwards. Backfilled from knowledge_approval_records; a row approved before M2 (no
--     record, M1 invented no history) is 'unrecorded', which no read path serves.
--   * Retrieval and RLS serve 'verified' only, on BOTH the version and its source. Demo rows are served
--     only by the separate public.match_knowledge_chunks_lexical_demo, which refuses (42501) unless the
--     database passes the isolation gate, and labels every row with its assurance.
--   * private.knowledge_deployment: the database's isolation declaration, default 'shared'
--     (fail closed). private.knowledge_deployment_isolated() is true only when ALL hold:
--       1. the row is 'isolated_test';
--       2. it is bound to THIS cluster and database: the system_identifier (pg_control_system) and
--          current_database() recorded at declaration equal the live ones, so a dump of a declared
--          database restored anywhere else is not isolated;
--       3. the database holds no account that looks real: every auth.users email is on a reserved test
--          domain (.invalid, .test, .example, .localhost, .local, example.com/.org/.net). A shared
--          project with any real user is therefore never isolated, whatever the row says.
--     The declaration is made by the database owner (no grant to any client or service role), through
--     scripts/ci/knowledge_isolation_gate.py, which first checks from OUTSIDE the database that the
--     connection target is a loopback or private address and not a Supabase-hosted endpoint, and
--     writes what it checked into the attestation.
--   * Demo approval (private.knowledge_demo_require_enabled) additionally needs the gate. The
--     free-text environment_label stays a note; it is no longer a control.
--
-- What it does NOT claim
--   * The database owner (and any superuser) can replace these functions, disable the triggers or
--     forge the declaration row. That is the infrastructure trust boundary of M1 and M2, unchanged:
--     the controls here stop the shared service credential, clients and accidents (a copied database,
--     a flag left on, a staging label on the shared project), not the owner. The gate is verifiable
--     after the fact by anyone who can read the database: compare the recorded binding with
--     pg_control_system() and run the account check (H-a document, section 4).
--   * A database row cannot prove where a database runs. The external half of the gate is the
--     connection-target check of the gate script and the operator's attestation.

-- ================================================================== deployment declaration

create table private.knowledge_deployment (
  singleton boolean primary key default true,
  class text not null default 'shared',
  bound_system_identifier bigint,
  bound_database text,
  attestation text,
  declared_at timestamptz,
  declared_by_session_user text,
  constraint knowledge_deployment_singleton_chk check (singleton),
  constraint knowledge_deployment_class_chk check (class in ('shared', 'isolated_test')),
  constraint knowledge_deployment_binding_chk check (
    (class = 'shared' and bound_system_identifier is null and bound_database is null)
    or (class = 'isolated_test' and bound_system_identifier is not null and bound_database is not null
        and length(btrim(attestation)) between 20 and 2000))
);
comment on table private.knowledge_deployment is
  'H-a: is this database an isolated test database (demo content allowed)? Default shared. Read through '
  'private.knowledge_deployment_isolated(), which re-checks the binding and the accounts on every call.';
revoke all on private.knowledge_deployment from public, anon, authenticated, service_role;
insert into private.knowledge_deployment (singleton) values (true);

create function private.knowledge_deployment_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and private.knowledge_m2_write_authorized('knowledge_deployment') then
    new.declared_at := pg_catalog.now();
    new.declared_by_session_user := session_user;
    return new;
  end if;
  raise exception 'knowledge_deployment is changed only by private.knowledge_declare_isolated_test /'
    ' private.knowledge_declare_shared: % is refused', tg_op using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_deployment_guard() from public, anon, authenticated, service_role;
create trigger knowledge_deployment_guard
  before insert or update or delete on private.knowledge_deployment
  for each row execute function private.knowledge_deployment_guard();
create trigger knowledge_deployment_no_truncate
  before truncate on private.knowledge_deployment
  for each statement execute function private.knowledge_m2_no_truncate();

-- True when any account looks real: an email that is missing or not on a reserved test domain.
create function private.knowledge_has_real_accounts()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from auth.users u
     where u.email is null
        or pg_catalog.lower(pg_catalog.split_part(u.email, '@', 2))
           !~ '^([a-z0-9-]+\.)*([a-z0-9-]+\.(invalid|test|example|localhost|local)|example\.(com|org|net))$');
$$;
revoke all on function private.knowledge_has_real_accounts() from public, anon, authenticated, service_role;

create function private.knowledge_live_system_identifier()
returns bigint
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_id bigint;
begin
  select c.system_identifier into v_id from pg_catalog.pg_control_system() c;
  return v_id;
exception when others then
  return null;                                               -- unreadable: never isolated
end;
$$;
revoke all on function private.knowledge_live_system_identifier() from public, anon, authenticated, service_role;

create function private.knowledge_deployment_isolated()
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v record;
  v_live bigint;
begin
  select d.class, d.bound_system_identifier, d.bound_database into v
    from private.knowledge_deployment d where d.singleton;
  if v.class is distinct from 'isolated_test' then
    return false;
  end if;
  v_live := private.knowledge_live_system_identifier();
  if v_live is null or v.bound_system_identifier is distinct from v_live
     or v.bound_database is distinct from pg_catalog.current_database() then
    return false;
  end if;
  return not private.knowledge_has_real_accounts();
end;
$$;
revoke all on function private.knowledge_deployment_isolated() from public, anon, authenticated, service_role;
grant execute on function private.knowledge_deployment_isolated() to authenticated, service_role;

-- Owner only (no grant). Binds the declaration to this cluster and database.
create function private.knowledge_declare_isolated_test(p_attestation text)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_live bigint := private.knowledge_live_system_identifier();
begin
  if p_attestation is null or length(btrim(p_attestation)) not between 20 and 2000 then
    raise exception 'an isolated_test declaration needs the attestation of the external gate (20-2000 characters)'
      using errcode = '22023';
  end if;
  if v_live is null then
    raise exception 'pg_control_system() is not readable here: the declaration cannot be bound, so it is refused'
      using errcode = '42501';
  end if;
  if private.knowledge_has_real_accounts() then
    raise exception 'this database holds accounts that are not on a reserved test domain: it is not an isolated'
      ' test database' using errcode = '42501';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_deployment');
  update private.knowledge_deployment
     set class = 'isolated_test', bound_system_identifier = v_live, bound_database = pg_catalog.current_database(),
         attestation = p_attestation
   where singleton;
  perform private.knowledge_m2_set_marker(null);
end;
$$;
revoke all on function private.knowledge_declare_isolated_test(text) from public, anon, authenticated, service_role;

create function private.knowledge_declare_shared()
returns void
language plpgsql
set search_path = ''
as $$
begin
  perform private.knowledge_m2_set_marker('knowledge_deployment');
  update private.knowledge_deployment
     set class = 'shared', bound_system_identifier = null, bound_database = null, attestation = null
   where singleton;
  perform private.knowledge_m2_set_marker(null);
end;
$$;
revoke all on function private.knowledge_declare_shared() from public, anon, authenticated, service_role;

-- RLS helper: demo rows are visible only inside public.match_knowledge_chunks_lexical_demo (which sets
-- the transaction-local knowledge.include_demo) AND only on an isolated database.
create function private.knowledge_demo_read_enabled()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(pg_catalog.current_setting('knowledge.include_demo', true), '') = 'on'
     and private.knowledge_deployment_isolated();
$$;
revoke all on function private.knowledge_demo_read_enabled() from public, anon, authenticated, service_role;
grant execute on function private.knowledge_demo_read_enabled() to authenticated;

-- ================================================================== demo approval needs the gate

create or replace function private.knowledge_demo_require_enabled()
returns void
language plpgsql
set search_path = ''
as $$
begin
  if not private.knowledge_deployment_isolated() then
    raise exception 'demo approval runs only on an isolated test database (owner decision D-H3a): this database is'
      ' not declared and verified isolated (private.knowledge_deployment_isolated())' using errcode = '42501';
  end if;
  if not coalesce((select m.enabled from private.knowledge_demo_mode m where m.singleton for share), false) then
    raise exception 'demo approval is switched off (private.knowledge_demo_mode); use the verified M2 flow'
      using errcode = '42501';
  end if;
end;
$$;

-- ================================================================== approval assurance column

alter table public.knowledge_documents add column approval_assurance text;
alter table public.knowledge_sources add column approval_assurance text;

-- Backfill: the approval records decide; any demo record wins (fail closed); no record = 'unrecorded'.
update public.knowledge_sources s
   set approval_assurance = coalesce((
         select case when bool_or(a.assurance = 'demo_unverified') then 'demo_unverified'
                     when bool_or(a.assurance = 'verified') then 'verified' end
           from public.knowledge_approval_records a
          where a.entity_type = 'source' and a.source_id = s.source_id and a.decision = 'approve'), 'unrecorded')
 where s.approved_at is not null;
update public.knowledge_documents d
   set approval_assurance = coalesce((
         select case when bool_or(a.assurance = 'demo_unverified') then 'demo_unverified'
                     when bool_or(a.assurance = 'verified') then 'verified' end
           from public.knowledge_approval_records a
          where a.entity_type = 'document' and a.document_pk = d.id and a.decision = 'approve'), 'unrecorded')
 where d.approved_at is not null;

alter table public.knowledge_documents add constraint knowledge_documents_approval_assurance_chk check (
  approval_assurance in ('verified', 'demo_unverified', 'unrecorded')
  and (approved_at is null) = (approval_assurance is null));
alter table public.knowledge_sources add constraint knowledge_sources_approval_assurance_chk check (
  approval_assurance in ('verified', 'demo_unverified', 'unrecorded')
  and (approved_at is null) = (approval_assurance is null));

do $backfill$
declare
  v text;
begin
  select pg_catalog.string_agg(t || ' ' || coalesce(a, 'none') || '=' || n, ', ' order by t, a) into v
    from (select 'documents' t, approval_assurance a, count(*) n from public.knowledge_documents group by 2
          union all
          select 'sources', approval_assurance, count(*) from public.knowledge_sources group by 2) x;
  raise notice 'H-a approval_assurance backfill: %', coalesce(v, 'no rows');
end;
$backfill$;

create function private.knowledge_stamp_approval_assurance()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_assurance text;
begin
  if tg_op = 'INSERT' then
    if new.approval_assurance is not null then
      raise exception '%: approval_assurance is set by the approval itself', tg_table_name using errcode = '23514';
    end if;
    return new;
  end if;
  if new.status = 'approved' and old.status <> 'approved' then
    if tg_table_name = 'knowledge_documents' then
      select case when bool_or(a.assurance = 'demo_unverified') then 'demo_unverified'
                  when bool_or(a.assurance = 'verified') then 'verified' end into v_assurance
        from public.knowledge_approval_records a
       where a.entity_type = 'document' and a.document_pk = (to_jsonb(old) ->> 'id')::uuid and a.decision = 'approve'
         and a.approver_user_id = new.approved_by and a.recorded_xact = pg_catalog.pg_current_xact_id();
    else
      select case when bool_or(a.assurance = 'demo_unverified') then 'demo_unverified'
                  when bool_or(a.assurance = 'verified') then 'verified' end into v_assurance
        from public.knowledge_approval_records a
       where a.entity_type = 'source' and a.source_id = (to_jsonb(old) ->> 'source_id') and a.decision = 'approve'
         and a.approver_user_id = new.approved_by and a.recorded_xact = pg_catalog.pg_current_xact_id();
    end if;
    if v_assurance is null then
      raise exception '%: an approval needs this transaction''s approval record', tg_table_name using errcode = '42501';
    end if;
    new.approval_assurance := v_assurance;                   -- whatever the writer put there
    return new;
  end if;
  if new.approval_assurance is distinct from old.approval_assurance then
    raise exception '%: approval_assurance is immutable', tg_table_name using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function private.knowledge_stamp_approval_assurance() from public, anon, authenticated, service_role;
-- named to fire after knowledge_documents_immutable / knowledge_sources_scope (same event, name order)
create trigger knowledge_documents_zz_assurance
  before insert or update on public.knowledge_documents
  for each row execute function private.knowledge_stamp_approval_assurance();
create trigger knowledge_sources_zz_assurance
  before insert or update on public.knowledge_sources
  for each row execute function private.knowledge_stamp_approval_assurance();

-- ================================================================== RLS (replaced)

-- Verified only, on the source and on the version; demo rows only inside the demo RPC on an isolated
-- database; 'unrecorded' never.
drop policy knowledge_sources_select on public.knowledge_sources;
create policy knowledge_sources_select on public.knowledge_sources
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and status = 'approved'
    and (approval_assurance = 'verified'
         or (approval_assurance = 'demo_unverified' and (select private.knowledge_demo_read_enabled())))
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

drop policy knowledge_documents_select on public.knowledge_documents;
create policy knowledge_documents_select on public.knowledge_documents
  for select to authenticated
  using (
    not (select private.knowledge_read_blocked())
    and status = 'approved'
    and (approval_assurance = 'verified'
         or (approval_assurance = 'demo_unverified' and (select private.knowledge_demo_read_enabled())))
    and (effective_from is null or effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
    and (effective_to is null or effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
    and approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    and exists (select 1 from public.knowledge_sources s where s.source_id = knowledge_documents.source_id)
  );

-- ================================================================== retrieval (replaced)

-- The M3 function, verified only (version AND source). Signature and columns unchanged.
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
      -- H-a: expert-verified approvals only
      and d.approval_assurance = 'verified'
      -- M3: in force today (policy date), whether or not the expiry job has run yet
      and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
      and s.approval_assurance = 'verified'
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

-- Demo retrieval: isolated databases only, explicit call, every row labelled. Same scope rules.
create function public.match_knowledge_chunks_lexical_demo(
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
  trgm_rank integer,
  approval_assurance text
)
language plpgsql
volatile
security invoker
set search_path = ''
as $$
#variable_conflict use_column
begin
  if not private.knowledge_deployment_isolated() then
    raise exception 'demo knowledge is served only on an isolated test database (owner decision D-H3a)'
      using errcode = '42501';
  end if;
  -- lets the RLS policies show demo rows to this caller for the rest of THIS transaction only
  perform pg_catalog.set_config('knowledge.include_demo', 'on', true);
  return query
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
           s.source_type, s.authority, s.visibility, s.organization_id, s.farm_id,
           case when d.approval_assurance = 'verified' and s.approval_assurance = 'verified' then 'verified'
                else 'demo_unverified' end as assurance
    from public.knowledge_chunks c
    join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
      and d.approval_assurance in ('verified', 'demo_unverified')
      and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
      and s.approval_assurance in ('verified', 'demo_unverified')
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
         fused.fused_score::double precision, fused.fts_rank, fused.trgm_rank, e.assurance
  from fused join eligible e on e.id = fused.id
  order by fused.fused_score desc, e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id
  limit least(greatest(coalesce(p_top_k, 8), 1), 50);
end;
$$;
revoke all on function public.match_knowledge_chunks_lexical_demo(uuid, text, integer) from public, anon, authenticated, service_role;
grant execute on function public.match_knowledge_chunks_lexical_demo(uuid, text, integer) to authenticated;

-- ================================================================== M4 evidence state (replaced)

-- 'active' now also needs verified assurance on both sides, so a demo or unrecorded approval is never
-- "public knowledge every signed-in user can retrieve" for the M4.1 disclosure rule.
create or replace function private.knowledge_document_evidence_state(p_document_pk uuid, out state text, out reason text)
language sql
stable
security definer
set search_path = ''
as $$
  select case when d.status in ('review_required', 'expert_review') then 'candidate'
              when d.status = 'approved' and s.status = 'approved'
                   and d.approval_assurance = 'verified' and s.approval_assurance = 'verified'
                   and private.knowledge_in_force(d.effective_from, d.effective_to, d.approval_expires_on,
                                                  private.knowledge_policy_date(pg_catalog.now())) then 'active'
              else 'inactive' end,
         case when d.status <> 'approved' then d.status::text
              when s.status <> 'approved' then 'source_' || s.status::text
              when d.approval_assurance is distinct from 'verified' then 'assurance_' || coalesce(d.approval_assurance, 'none')
              when s.approval_assurance is distinct from 'verified' then 'source_assurance_' || coalesce(s.approval_assurance, 'none')
              when not private.knowledge_in_force(d.effective_from, d.effective_to, d.approval_expires_on,
                                                  private.knowledge_policy_date(pg_catalog.now())) then 'not_in_force'
              else 'approved_in_force' end
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk;
$$;
