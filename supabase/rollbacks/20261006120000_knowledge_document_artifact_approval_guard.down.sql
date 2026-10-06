-- Rollback for migrations/20261006120000_knowledge_document_artifact_approval_guard.sql.
-- Drops ONLY the ST1-DB approval constraint; Migration A's own constraints, triggers, RLS and
-- every row stay as they are. Afterwards a URL-only version could be approved again, so roll
-- back only if the forward migration must be withdrawn -- never to approve a document that
-- lacks a controlled artifact.
-- Not in migrations/: run by hand, in one transaction. Afterwards
-- `supabase migration repair --status reverted 20261006120000`.
begin;
alter table public.knowledge_documents drop constraint if exists knowledge_documents_artifact_approval_chk;
commit;
