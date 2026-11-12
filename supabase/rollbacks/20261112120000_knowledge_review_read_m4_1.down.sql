-- Rollback for migrations/20261112120000_knowledge_review_read_m4_1.sql (RAG V1.5 M4.1).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE any M4 rollback, then
--   supabase migration repair --status reverted 20261112120000
--
-- M4.1 replaced nothing: this only drops what M4.1 added. No status, approval, retrieval, expiry or
-- claim behaviour changes. DROPPING THE TABLES DELETES THE READ AUDIT. Export
-- public.knowledge_review_read_events and public.knowledge_review_read_denied_overflow first, then confirm with
--   set local knowledge.m4_1_rollback_evidence_exported = 'yes';

begin;

do $$
begin
  if coalesce(current_setting('knowledge.m4_1_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'M4.1 rollback DROPS the reviewer read audit: export it, then'
      ' set local knowledge.m4_1_rollback_evidence_exported = ''yes''';
  end if;
end;
$$;

drop function public.knowledge_review_claims(uuid);
drop function private.knowledge_review_claim_json(bigint);
drop function private.knowledge_review_read_denied_cap();
drop table public.knowledge_review_read_events;
drop table public.knowledge_review_read_denied_overflow;
drop function private.knowledge_review_read_overflow_guard();

commit;
