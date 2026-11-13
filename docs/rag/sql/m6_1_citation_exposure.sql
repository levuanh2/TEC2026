-- RAG V1.5 M6.1: recorded deliveries that involved one chunk_id (docs/rag/RAG_V15_M6_1_CITATION_EVENTS.md).
-- READ-ONLY, service_role or owner. Parameter %(chunk_id)s.
--
-- Only requests recorded by the M6.1 prototype appear (local/CI; nothing before it, nothing on a
-- shared database). `exposure` separates
--   cited           the answer the backend emitted cited the chunk (the strongest evidence recorded; that the
--                   caller actually received or read it is NOT proven by this log);
--   retrieved_only  the chunk was a retrieval candidate the answer did not cite (NOT answer exposure).
-- Combine with docs/rag/sql/m6_exposure_window.sql: outside the recorded period only the possible
-- exposure window is known.
select e.request_id,
       case when bool_or(c.role = 'cited') then 'cited' else 'retrieved_only' end as exposure,
       e.response_emitted, e.occurred_at, e.organization_id, e.crop_season_id, e.retrieval_mode, e.outcome,
       e.trace_completeness, min(c.document_version) as document_version, min(c.approval_assurance) as approval_assurance
  from public.knowledge_citation_events e
  join public.knowledge_citation_event_chunks c on c.request_id = e.request_id
 where c.chunk_id = %(chunk_id)s
 group by e.request_id
 order by e.occurred_at, e.request_id;
