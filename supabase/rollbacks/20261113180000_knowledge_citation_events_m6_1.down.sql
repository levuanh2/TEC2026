-- Rollback for migrations/20261113180000_knowledge_citation_events_m6_1.sql (RAG V1.5 M6.1 prototype).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE any H-c / H-b / H-a rollback, then
--   supabase migration repair --status reverted 20261113180000
-- It DROPS the citation events (metadata only, local/CI prototype): it refuses without
--   set local knowledge.m6_1_rollback_evidence_exported = 'yes'
-- M6.1 replaced nothing.

begin;

do $$
begin
  if coalesce(current_setting('knowledge.m6_1_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'M6.1 rollback DROPS the citation events: export them, then'
      ' set local knowledge.m6_1_rollback_evidence_exported = ''yes''';
  end if;
end;
$$;

drop function private.knowledge_purge_citation_events();
drop function private.knowledge_record_citation_event(uuid, uuid, text, text, boolean, text, jsonb, jsonb);
drop table public.knowledge_citation_event_chunks;
drop table public.knowledge_citation_events;
drop table public.knowledge_citation_purges;
drop function private.knowledge_citation_guard();
drop table private.knowledge_citation_settings;

commit;
