-- RAG V1.5 H-a: read-only inventory of approved knowledge with NO approval record (docs/rag/
-- RAG_V15_H_A_DEMO_ASSURANCE_ISOLATION.md, section 2.4). Run as service_role or the owner, BEFORE applying
-- H-a (to know what the fail-closed backfill will withhold) and after it (to track remediation).
-- It reads only; it never classifies a row as verified and never writes a record.
--
-- One row per version or source that was ever approved (approved_at set) and has no `approve` approval
-- record of its own. `currently_approved` rows are the ones H-a stops serving (`unrecorded`).
-- Works with and without H-a installed (it does not read approval_assurance).
select 'document' as entity_type, d.id::text as entity_key, d.source_id, d.document_id, d.document_version,
       d.status::text as status, d.status = 'approved' as currently_approved, d.approved_at, d.approved_by,
       d.file_sha256, d.artifact_ref,
       (select count(*) from public.knowledge_chunks c where c.document_pk = d.id) as chunks,
       (select count(*) from public.knowledge_status_events e where e.document_pk = d.id) as status_events
  from public.knowledge_documents d
 where d.approved_at is not null
   and not exists (select 1 from public.knowledge_approval_records a
                    where a.entity_type = 'document' and a.document_pk = d.id and a.decision = 'approve')
union all
select 'source', s.source_id, s.source_id, null, null, s.status::text, s.status = 'approved', s.approved_at,
       s.approved_by, null, null,
       (select count(*) from public.knowledge_documents d where d.source_id = s.source_id),
       (select count(*) from public.knowledge_status_events e where e.entity_type = 'source' and e.source_id = s.source_id)
  from public.knowledge_sources s
 where s.approved_at is not null
   and not exists (select 1 from public.knowledge_approval_records a
                    where a.entity_type = 'source' and a.source_id = s.source_id and a.decision = 'approve')
 order by 1, 3, 4, 5;
