-- Rollback for migrations/20261113150000_knowledge_m2_hardening_supersession.sql (RAG V1.5 H-c).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE the H-b rollback, then
--   supabase migration repair --status reverted 20261113150000
--
-- Restores the exact M3 body of private.knowledge_check_cross_source_supersession: a cross-source
-- supersession then needs only the reviewer's recorded reference again (no countersignature). It DROPS
-- the publisher registry, the source bindings, the custodian assignments and the countersignatures, so
-- it REFUSES without set local knowledge.hc_rollback_evidence_exported = 'yes' (export the four tables
-- first).

begin;

do $$
begin
  if coalesce(current_setting('knowledge.hc_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'H-c rollback DROPS the publisher registry and the supersession countersignatures: export'
      ' public.knowledge_publishers, knowledge_source_publishers, knowledge_source_custodians and'
      ' knowledge_supersession_authorizations, then set local knowledge.hc_rollback_evidence_exported = ''yes''';
  end if;
end;
$$;

drop function public.knowledge_custodian_snapshot(uuid);
drop function public.knowledge_countersign_supersession(uuid, text, text, text);
drop function public.knowledge_set_source_custodian_status(uuid, text, text);
drop function public.knowledge_grant_source_custodian(uuid, text, text);
drop function public.knowledge_bind_source_publisher(text, uuid, text);
drop function public.knowledge_set_publisher_status(uuid, text, text);
drop function public.knowledge_register_publisher(text, text, text);
drop table public.knowledge_supersession_authorizations;
drop table public.knowledge_source_custodians;
drop table public.knowledge_source_publishers;
drop table public.knowledge_publishers;

create or replace function private.knowledge_check_cross_source_supersession(p_document_pk uuid, p_sources_checked jsonb)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_doc record;
  v_target_source text;
begin
  select d.source_id, d.supersedes_document_pk, s.status as source_status into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk;
  if v_doc.supersedes_document_pk is null then
    return;
  end if;
  select t.source_id into v_target_source from public.knowledge_documents t
   where t.id = v_doc.supersedes_document_pk;
  if v_target_source = v_doc.source_id then
    return;
  end if;
  if v_doc.source_status is distinct from 'approved' then
    raise exception 'knowledge document %: its source % is %, not approved; it cannot supersede a version of'
      ' another source (%)', p_document_pk, v_doc.source_id, v_doc.source_status, v_target_source
      using errcode = '23514';
  end if;
  if not exists (
      select 1 from pg_catalog.jsonb_array_elements(
                      case when pg_catalog.jsonb_typeof(p_sources_checked) = 'array' then p_sources_checked
                           else '[]'::jsonb end) e
       where pg_catalog.jsonb_typeof(e) = 'object'
         and e ->> 'purpose' = 'cross_source_supersession_authority'
         and e ->> 'supersedes_document_pk' = v_doc.supersedes_document_pk::text
         and pg_catalog.btrim(coalesce(e ->> 'reference', '')) <> '') then
    raise exception 'knowledge document %: it supersedes a version of another source (%); the expert review'
      ' must record the authority for exactly this replacement (sources_checked: purpose'
      ' cross_source_supersession_authority, supersedes_document_pk %, reference)',
      p_document_pk, v_target_source, v_doc.supersedes_document_pk using errcode = '23514';
  end if;
end;
$$;

drop function private.knowledge_supersession_conflicts(uuid, uuid);

commit;
