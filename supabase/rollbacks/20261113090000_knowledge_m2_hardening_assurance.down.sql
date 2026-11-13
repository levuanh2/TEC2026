-- Rollback for migrations/20261113090000_knowledge_m2_hardening_assurance.sql (RAG V1.5 H-a).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE the M4.1 rollback (and after any H-b /
-- H-c rollback), then
--   supabase migration repair --status reverted 20261113090000
--
-- Restores the exact pre-H-a bodies: M3 retrieval and document policy, the base source policy, the M2
-- demo switch check and the M4 evidence state. AFTER THIS, RETRIEVAL NO LONGER READS ASSURANCE: every
-- approved row is served again, demo-approved ones included. So the rollback REFUSES
--   * while any approved version or source has demo_unverified assurance, unless this database passes
--     the isolation gate (run private.knowledge_demo_quarantine_all first on a shared database);
--   * while any approved row is 'unrecorded' (approved before M2), unless the operator confirms that
--     re-serving them is intended: set local knowledge.ha_rollback_reserve_unrecorded = 'yes';
--   * without set local knowledge.ha_rollback_confirmed = 'yes'.
-- The approval records keep the assurance of every approval; only the copied column is dropped.

begin;

do $$
declare
  v_demo integer;
  v_unrecorded integer;
begin
  if coalesce(current_setting('knowledge.ha_rollback_confirmed', true), '') <> 'yes' then
    raise exception 'H-a rollback makes retrieval ignore approval assurance: confirm with'
      ' set local knowledge.ha_rollback_confirmed = ''yes''';
  end if;
  if to_regclass('public.knowledge_emergency_actions') is not null
     or to_regclass('public.knowledge_supersession_authorizations') is not null then
    raise exception 'H-a rollback refused: H-b or H-c is installed; roll those back first';
  end if;
  select (select count(*) from public.knowledge_documents where status = 'approved' and approval_assurance = 'demo_unverified')
       + (select count(*) from public.knowledge_sources where status = 'approved' and approval_assurance = 'demo_unverified'),
         (select count(*) from public.knowledge_documents where status = 'approved' and approval_assurance = 'unrecorded')
       + (select count(*) from public.knowledge_sources where status = 'approved' and approval_assurance = 'unrecorded')
    into v_demo, v_unrecorded;
  if v_demo > 0 and not private.knowledge_deployment_isolated() then
    raise exception 'H-a rollback refused: % approved demo row(s) would be served on a database that is not an'
      ' isolated test database; run private.knowledge_demo_quarantine_all first', v_demo;
  end if;
  if v_unrecorded > 0 and coalesce(current_setting('knowledge.ha_rollback_reserve_unrecorded', true), '') <> 'yes' then
    raise exception 'H-a rollback refused: % approved row(s) without an approval record would be served again;'
      ' quarantine them, or confirm with set local knowledge.ha_rollback_reserve_unrecorded = ''yes''', v_unrecorded;
  end if;
end;
$$;

drop function public.match_knowledge_chunks_lexical_demo(uuid, text, integer);

drop policy knowledge_sources_select on public.knowledge_sources;
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

create or replace function private.knowledge_demo_require_enabled()
returns void
language plpgsql
set search_path = ''
as $$
begin
  if not coalesce((select m.enabled from private.knowledge_demo_mode m where m.singleton for share), false) then
    raise exception 'demo approval is switched off (private.knowledge_demo_mode); use the verified M2 flow'
      using errcode = '42501';
  end if;
end;
$$;

create or replace function private.knowledge_document_evidence_state(p_document_pk uuid, out state text, out reason text)
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

drop trigger knowledge_documents_zz_assurance on public.knowledge_documents;
drop trigger knowledge_sources_zz_assurance on public.knowledge_sources;
drop function private.knowledge_stamp_approval_assurance();
alter table public.knowledge_documents drop constraint knowledge_documents_approval_assurance_chk;
alter table public.knowledge_sources drop constraint knowledge_sources_approval_assurance_chk;
alter table public.knowledge_documents drop column approval_assurance;
alter table public.knowledge_sources drop column approval_assurance;

drop function private.knowledge_demo_read_enabled();
drop function private.knowledge_declare_shared();
drop function private.knowledge_declare_isolated_test(text);
drop function private.knowledge_deployment_isolated();
drop function private.knowledge_live_system_identifier();
drop function private.knowledge_has_real_accounts();
drop table private.knowledge_deployment;
drop function private.knowledge_deployment_guard();

commit;
