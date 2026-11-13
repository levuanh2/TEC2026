-- RAG V1.5 M7 E7.1: READ-ONLY inventory of chunks whose stored text does not hash to their recorded
-- content_sha256 (docs/rag/RAG_V15_M7_E7_1_PORTABLE_ATTESTATION.md section 3). Counts only, no content.
-- NOT run on hosted by this change; an owner runs it, in a read-only transaction, before choosing remediation
-- (re-ingest the version as a new version). It never rewrites a row.
begin transaction read only;
select d.status::text as document_status,
       count(distinct d.id) as versions,
       count(*) as mismatching_chunks
  from public.knowledge_chunks k
  join public.knowledge_documents d on d.id = k.document_pk
 where k.content_sha256 is distinct from encode(sha256(convert_to(k.content, 'UTF8')), 'hex')
 group by d.status
 order by 1;
rollback;
