-- Rollback for migrations/20261005090000_knowledge_retrieval_lexical_foundation.sql.
-- Drops ONLY the objects that migration created, in dependency order: the lexical RPC,
-- the three knowledge tables (with their triggers, policies and indexes), the private
-- helper/trigger functions, the two enums and the two extensions it installed. No Core V1
-- table, function or policy is touched. DESTROYS every knowledge source/document/chunk row.
-- Not in migrations/: run by hand, in one transaction, only if the forward migration must
-- be withdrawn. Afterwards `supabase migration repair --status reverted 20261005090000`.
begin;
drop function if exists public.match_knowledge_chunks_lexical(uuid, text, integer);
drop table if exists public.knowledge_chunks;
drop table if exists public.knowledge_documents;
drop table if exists public.knowledge_sources;
drop function if exists private.enforce_knowledge_chunk_immutability();
drop function if exists private.enforce_knowledge_document_immutability();
drop function if exists private.enforce_knowledge_source_scope();
drop function if exists private.knowledge_chunks_search_fields();
drop function if exists private.knowledge_search_text(text);
drop type if exists public.knowledge_license_basis;
drop type if exists public.knowledge_status;
drop extension if exists unaccent;
drop extension if exists pg_trgm;
commit;
