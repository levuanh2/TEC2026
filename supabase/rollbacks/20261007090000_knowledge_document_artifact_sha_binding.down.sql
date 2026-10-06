-- Rollback for migrations/20261007090000_knowledge_document_artifact_sha_binding.sql.
-- Drops ONLY the ST1.1 SHA-binding constraint; ST1 (knowledge_documents_artifact_approval_chk),
-- Migration A's own constraints, triggers, RLS and every row stay as they are. Afterwards an
-- approved version could point at another file's content address again, so roll back only if the
-- forward migration must be withdrawn -- never to approve a version whose artifact is not its own.
-- Not in migrations/: run by hand, in one transaction. Afterwards
-- `supabase migration repair --status reverted 20261007090000`.
begin;
alter table public.knowledge_documents drop constraint if exists knowledge_documents_artifact_sha_binding_chk;
commit;
