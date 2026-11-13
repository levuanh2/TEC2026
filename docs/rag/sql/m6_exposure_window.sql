-- RAG V1.5 M6: exposure window of one chunk_id (docs/rag/RAG_V15_M6_REVOCATION_RUNBOOK.md, section 4).
-- READ-ONLY. Run as service_role or the owner (the event and evidence tables are not client-readable).
-- Parameter: %(chunk_id)s (psql: replace with the literal, or \set and :'chunk_id').
--
-- What it answers: the interval(s) during which retrieval COULD return the chunk, from the audited
-- status history: the version was approved (and, with H-a, verified) and its source was approved.
-- What it does NOT answer: which requests or answers actually cited the chunk. No request-level
-- citation log exists before M6 logging is deployed (runbook section 5), so the window is an upper
-- bound of exposure, not a list of affected answers.
--
-- Limitations, stated: effective_from / effective_to / approval_expires_on narrow the window further
-- and are listed, not subtracted; events before M1 do not exist (M1 invented no history), so a
-- version approved before M1 shows servable_from = null ("before the audit log").
with chunk as (
  select c.chunk_id, c.document_pk, d.source_id, d.document_id, d.document_version, d.status::text as document_status,
         d.approval_assurance, d.effective_from, d.effective_to, d.approval_expires_on
    from public.knowledge_chunks c join public.knowledge_documents d on d.id = c.document_pk
   where c.chunk_id = %(chunk_id)s
),
doc_events as (
  select e.document_pk, e.occurred_at, e.from_status::text as from_status, e.to_status::text as to_status, e.reason
    from public.knowledge_status_events e join chunk on chunk.document_pk = e.document_pk
),
src_events as (
  select e.occurred_at, e.from_status::text as from_status, e.to_status::text as to_status
    from public.knowledge_status_events e join chunk on chunk.source_id = e.source_id
   where e.entity_type = 'source'
)
select chunk.chunk_id, chunk.document_pk, chunk.source_id, chunk.document_id, chunk.document_version,
       chunk.document_status, chunk.approval_assurance,
       (select min(occurred_at) from doc_events where to_status = 'approved') as document_approved_at,
       (select min(occurred_at) from doc_events where from_status = 'approved') as document_left_approved_at,
       (select to_status from doc_events where from_status = 'approved' order by occurred_at limit 1) as document_left_to,
       (select reason from doc_events where from_status = 'approved' order by occurred_at limit 1) as document_left_reason,
       (select max(occurred_at) from src_events where to_status = 'approved') as source_approved_at,
       (select min(occurred_at) from src_events where from_status = 'approved') as source_left_approved_at,
       greatest((select min(occurred_at) from doc_events where to_status = 'approved'),
                (select max(occurred_at) from src_events where to_status = 'approved')) as servable_from,
       least((select min(occurred_at) from doc_events where from_status = 'approved'),
             (select min(occurred_at) from src_events where from_status = 'approved')) as servable_until,
       chunk.effective_from, chunk.effective_to, chunk.approval_expires_on,
       (select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('reason_code', a.reason_code, 'operator_reference',
               a.operator_reference, 'recorded_at', a.recorded_at) order by a.id)
          from public.knowledge_emergency_actions a where a.document_pk = chunk.document_pk
            or (a.entity_type = 'source' and a.source_id = chunk.source_id)) as emergency_actions
  from chunk;
