-- Rollback for migrations/20261112090000_knowledge_claims_contradictions_m4.sql (RAG V1.5 M4).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE any M3 rollback, then
--   supabase migration repair --status reverted 20261112090000
--
-- M4 replaced nothing: this only drops what M4 added. No status, approval, retrieval or expiry
-- behaviour changes. DROPPING THE TABLES DELETES THE STORED CLAIMS AND CONTRADICTION CANDIDATES.
-- They can be regenerated for the same extractor and analysis versions, but the recorded rows
-- (when the database accepted them, in which evidence state) cannot. Export
-- public.knowledge_claims and public.knowledge_contradiction_candidates first, then confirm with
--   set local knowledge.m4_rollback_evidence_exported = 'yes';

begin;

do $$
begin
  if coalesce(current_setting('knowledge.m4_rollback_evidence_exported', true), '') <> 'yes' then
    raise exception 'M4 rollback DROPS the stored claims and contradiction candidates: export them, then'
      ' set local knowledge.m4_rollback_evidence_exported = ''yes''';
  end if;
end;
$$;

drop function private.knowledge_record_contradiction_candidates(text, jsonb);
drop function private.knowledge_classify_claim_pair(bigint, bigint, numeric);
drop function private.knowledge_record_claims(uuid, text, jsonb);
drop table public.knowledge_contradiction_candidates;
drop table public.knowledge_claims;
drop function private.knowledge_claim_evidence_guard();
drop function private.knowledge_document_evidence_state(uuid);

commit;
