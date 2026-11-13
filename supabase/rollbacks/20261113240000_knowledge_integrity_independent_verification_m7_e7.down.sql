-- Rollback for migrations/20261113240000_knowledge_integrity_independent_verification_m7_e7.sql (RAG V1.5 M7 E7).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE the E2 rollback, then
--   supabase migration repair --status reverted 20261113240000
-- Restores E2's exact gate: approvals no longer need an independent verification (E7 reopens). It DROPS the
-- verifications and the verifier key registry, so it refuses without
--   set local knowledge.e7_rollback_confirmed = 'yes'   (export both tables first)
-- The pgsodium extension is left installed (other objects may use it).

begin;

do $$
begin
  if coalesce(current_setting('knowledge.e7_rollback_confirmed', true), '') <> 'yes' then
    raise exception 'E7 rollback reopens E7 and DROPS the verification evidence and verifier keys: export them, then'
      ' set local knowledge.e7_rollback_confirmed = ''yes''';
  end if;
end;
$$;

create or replace function private.knowledge_integrity_gate(p_document_pk uuid, p_review_id uuid)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_rev record;
  v_report public.knowledge_integrity_reports;
  v_problem text;
  v_bad record;
begin
  select r.id, r.snapshot_sha256, r.reviewer_personnel_id into v_rev from public.knowledge_expert_reviews r
   where r.id = p_review_id and r.document_pk = p_document_pk;
  v_report := private.knowledge_integrity_current_report(p_document_pk);
  v_problem := private.knowledge_integrity_report_problem(v_report);
  if v_problem is not null then
    raise exception 'integrity gate (E2): %; approval needs the integrity report of this exact version', v_problem
      using errcode = '23514';
  end if;
  perform 1 from public.knowledge_integrity_reports r where r.id = v_report.id for share;
  if v_rev.snapshot_sha256 is distinct from v_report.document_snapshot_sha256 then
    raise exception 'integrity gate (E2): the review and the integrity report are of different snapshots' using errcode = '23514';
  end if;
  if not exists (select 1 from public.knowledge_integrity_dispositions d
                  where d.review_id = p_review_id and d.report_id = v_report.id and d.finding_id is null
                    and d.report_sha256 = v_report.report_sha256 and d.actor_personnel_id = v_rev.reviewer_personnel_id) then
    raise exception 'integrity gate (E2): the expert reviewer has not acknowledged the current integrity report'
      ' (public.knowledge_dispose_integrity_finding with report_reviewed)' using errcode = '23514';
  end if;
  select f.id, f.finding_type, d.disposition into v_bad
    from public.knowledge_integrity_findings f
    left join public.knowledge_integrity_dispositions d
      on d.finding_id = f.id and d.review_id = p_review_id and d.report_sha256 = v_report.report_sha256
     and d.actor_personnel_id = v_rev.reviewer_personnel_id
   where f.report_id = v_report.id
     and (d.disposition in ('confirmed_problem', 'needs_more_evidence')
          or (f.needs_expert_review and (d.disposition is null
                                         or d.disposition not in ('false_positive', 'contextual_difference'))))
   order by f.id limit 1;
  if v_bad.id is not null then
    raise exception 'integrity gate (E2): finding % (%) is %; it must be resolved as false_positive or'
      ' contextual_difference with evidence, otherwise the version is rejected or returned', v_bad.id, v_bad.finding_type,
      coalesce(v_bad.disposition, 'not dispositioned') using errcode = '23514';
  end if;
end;
$$;

drop function private.knowledge_integrity_verification_problem(public.knowledge_integrity_reports);
drop function private.knowledge_record_integrity_verification(text, bytea);
drop table public.knowledge_integrity_verifications;
drop function private.knowledge_claim_set_digest(uuid, text);
drop function private.knowledge_revoke_verifier_key(text, text);
drop function private.knowledge_register_verifier_key(text, bytea, text);
drop table public.knowledge_integrity_verifier_keys;
drop function private.knowledge_verifier_key_guard();
drop function private.knowledge_set_integrity_code_digest(text);
alter table private.knowledge_integrity_policy drop constraint knowledge_integrity_policy_code_chk;
alter table private.knowledge_integrity_policy drop column extractor_code_digest;

commit;
