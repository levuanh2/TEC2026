-- ST1.1 (RAG V1.3): an APPROVED knowledge document version's artifact_ref must be the content
-- address of THAT version's bytes: it starts with `knowledge-artifacts/<file_sha256>/`.
--
-- ST1 (20261006120000, knowledge_documents_artifact_approval_chk) makes approval require an
-- opaque ASCII storage path but does not tie it to the row, so a version with
-- file_sha256 = <A> could be approved pointing at knowledge-artifacts/<B>/x.pdf -- another file's
-- copy. This migration adds that binding, and only that:
--   status = 'approved' requires
--     starts_with(artifact_ref, 'knowledge-artifacts/' || file_sha256 || '/')   in the "C" collation
--   * exact and canonical, no normalisation: file_sha256 is already 64 lowercase hex
--     (knowledge_documents_hash_chk), so an upper-case SHA segment, another SHA, a SHA prefix,
--     a SHA with extra characters before the `/`, or a missing `/` all fail;
--   * written NULL-safe (coalesce(..., false)): a NULL artifact_ref fails here too, never passes
--     by being unknown;
--   * the rest of the path stays ST1's job (positive grammar: no empty / `.` / `..` segment, no
--     trailing `/`, ASCII only, <= 512 chars); nothing of it is repeated here. The bucket name is
--     the one the V1.3-C CLI writes (infrastructure/knowledge_repo.py ARTIFACT_BUCKET).
-- The database still never calls Storage. That the object exists and its bytes hash to
-- file_sha256 remains the external verify-before-approval step (docs/rag/RAG_V1_INGESTION.md).
--
-- Approval-time only, like ST1: drafts (review_required / rejected) are unchanged, may carry no
-- artifact or a mismatched one, and can be corrected before approval (artifact_ref is mutable
-- until the first approval; file_sha256 is immutable from insert). An archived row was approved
-- under this rule and its artifact_ref is frozen by the immutability trigger.
--
-- Additive: one CHECK constraint. No table, column, RLS, grant, trigger, function, lifecycle,
-- retrieval, Storage or Core V1 change. Hosted had 0 knowledge rows when this was written
-- (read-only check 2026-10-07). On a database holding an APPROVED version whose artifact_ref is
-- not its own content address, ADD CONSTRAINT fails and the whole migration rolls back -- fix
-- that row by a reviewed path, never weaken this.

alter table public.knowledge_documents
  add constraint knowledge_documents_artifact_sha_binding_chk check (
    status <> 'approved'
    or coalesce(starts_with(artifact_ref collate "C", 'knowledge-artifacts/' || file_sha256 || '/'), false)
  );

comment on constraint knowledge_documents_artifact_sha_binding_chk on public.knowledge_documents is
  'ST1.1: an approved version''s artifact_ref starts with knowledge-artifacts/<file_sha256>/ -- the '
  'content address of its own bytes. Existence and byte hash are verified outside the database.';
