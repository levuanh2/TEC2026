-- RAG V1.5 M1 (docs/rag/RAG_V15_SOURCE_CONTENT_INTEGRITY.md §3, §6), part 1 of 2: the two new
-- knowledge_status values, and nothing else.
--
-- PostgreSQL refuses to USE an enum value in the transaction that added it ("unsafe use of new
-- value"), so this file only adds them. Every rule that names them (transition matrix, triggers,
-- transition functions, event table) is in 20261110090100_knowledge_status_lifecycle_m1.sql,
-- which the migration runner applies in its own transaction.
--
--   expert_review  a document version that passed ingestion review and waits for the expert stage.
--                  Mandatory between review_required and approved for DOCUMENT VERSIONS (D3).
--                  Sources never use it.
--   quarantined    an approved source or version withdrawn from retrieval pending a decision. It
--                  can only be archived (D1): a correction is a NEW version through the full flow.
--
-- Neither value is retrievable. RLS and public.match_knowledge_chunks_lexical require
-- status = 'approved' on both the document and its source (20261005090000), so both are
-- excluded fail-closed with no change to retrieval.
--
-- Enum values cannot be dropped. The rollback (supabase/rollbacks/20261110090000_*.down.sql)
-- leaves them in the type, unused.

alter type public.knowledge_status add value if not exists 'expert_review' after 'review_required';
alter type public.knowledge_status add value if not exists 'quarantined' after 'approved';
