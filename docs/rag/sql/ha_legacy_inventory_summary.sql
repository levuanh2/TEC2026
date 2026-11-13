-- RAG V1.5 H-a: READ-ONLY category summary of approved knowledge and its approval evidence
-- (docs/rag/RAG_V15_H_A_HOSTED_INVENTORY_PROCEDURE.md). Counts and identifiers only: NO title, NO content,
-- NO chunk text. Works with and without H-a installed: it derives the assurance from the approval records
-- exactly as the H-a backfill does (a demo record wins, a verified record next, no record = unrecorded).
with src as (
  select s.source_id, s.status::text as status, s.approved_at is not null as ever_approved,
         coalesce((select case when bool_or(a.assurance = 'demo_unverified') then 'demo_unverified'
                               when bool_or(a.assurance = 'verified') then 'verified' end
                     from public.knowledge_approval_records a
                    where a.entity_type = 'source' and a.source_id = s.source_id and a.decision = 'approve'),
                  'unrecorded') as assurance
    from public.knowledge_sources s
),
doc as (
  select d.id, d.source_id, d.status::text as status, d.approved_at is not null as ever_approved,
         coalesce((select case when bool_or(a.assurance = 'demo_unverified') then 'demo_unverified'
                               when bool_or(a.assurance = 'verified') then 'verified' end
                     from public.knowledge_approval_records a
                    where a.entity_type = 'document' and a.document_pk = d.id and a.decision = 'approve'),
                  'unrecorded') as assurance,
         (select count(*) from public.knowledge_chunks c where c.document_pk = d.id) as chunks
    from public.knowledge_documents d
)
select 'approved sources' as category, assurance, count(*) as rows, null::bigint as chunks
  from src where status = 'approved' group by assurance
union all
select 'approved documents', assurance, count(*), sum(chunks)
  from doc where status = 'approved' group by assurance
union all
-- versions whose own record is fine but whose SOURCE would be withheld (H-a requires both verified)
select 'approved verified documents withheld by their unrecorded or demo source', s.assurance, count(*), sum(d.chunks)
  from doc d join src s on s.source_id = d.source_id
 where d.status = 'approved' and d.assurance = 'verified' and s.status = 'approved' and s.assurance <> 'verified'
 group by s.assurance
union all
-- application impact: chunks served today that H-a would stop serving (approved version + approved source,
-- one of them not verified). Effective dates are not applied here; this is an upper bound.
select 'served chunks H-a would withhold (upper bound)', null, count(*), sum(d.chunks)
  from doc d join src s on s.source_id = d.source_id
 where d.status = 'approved' and s.status = 'approved' and (d.assurance <> 'verified' or s.assurance <> 'verified')
 order by 1, 2;
