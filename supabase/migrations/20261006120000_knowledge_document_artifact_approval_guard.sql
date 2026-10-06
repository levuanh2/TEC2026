-- ST1-DB (RAG V1.3): an APPROVED knowledge document version must carry a controlled artifact
-- reference to its original bytes. official_url alone never satisfies artifact provenance.
--
-- Migration A (20261005090000) accepts `official_url OR artifact_ref`
-- (knowledge_documents_artifact_chk) and its approval CHECK (knowledge_documents_approval_chk)
-- does not look at artifact_ref, so a URL-only version could be approved by hand.
--
-- Rule added -- minimal and structural, deliberately independent of the storage layout:
--   status = 'approved' requires artifact_ref to be
--     * present (NOT NULL -- written out: a NULL comparison would make a CHECK pass),
--     * non-blank: at least one non-whitespace character (tabs/newlines count as blank --
--       btrim() alone would only strip spaces),
--     * not a URL (no `://`): copying official_url into artifact_ref is no stored copy.
--   Refusals are SQLSTATE 23514.
-- The database never calls Storage. That the reference resolves to the controlled immutable
-- copy whose bytes hash to file_sha256 stays the ingestion/approver responsibility: the V1.3-C
-- CLI always stores the bytes in the private `knowledge-artifacts` bucket, content-addressed,
-- and writes `knowledge-artifacts/<file_sha256>/<safe-name>`; the approval checklist re-verifies
-- it (docs/rag/RAG_V1_INGESTION.md). file_sha256 itself is already NOT NULL and hex-checked.
-- Every existing approval invariant still applies (approver, time, review note, known
-- license_basis, license_reference for open_license/written_permission). Drafts
-- (review_required / rejected) are unchanged. An archived row was approved under this rule and
-- its artifact_ref is frozen by the immutability trigger.
--
-- Additive: one CHECK constraint. No table, column, RLS, grant, trigger, function, lifecycle,
-- retrieval, Storage or Core V1 change. Hosted had 0 knowledge rows when this was written
-- (read-only check 2026-10-06); on a database holding an approved version without an artifact
-- the ADD CONSTRAINT fails and the whole migration rolls back -- fix that row, never weaken this.

alter table public.knowledge_documents
  add constraint knowledge_documents_artifact_approval_chk check (
    status <> 'approved'
    or (artifact_ref is not null
        and artifact_ref ~ '[^[:space:]]'
        and position('://' in artifact_ref) = 0)
  );

comment on constraint knowledge_documents_artifact_approval_chk on public.knowledge_documents is
  'ST1-DB: an approved version needs a non-blank, non-URL artifact_ref (the controlled stored copy); '
  'official_url alone is never enough.';
