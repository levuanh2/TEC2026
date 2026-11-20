-- Rollback for migrations/20261120120000_knowledge_pin_generation_e5_2.sql (RAG V1.5 M7 E5.2). Not in migrations/: run by hand, in ONE
-- transaction, FIRST (before the E5.1 rollback), then
--   supabase migration repair --status reverted 20261120120000
--
-- READ THIS FIRST. A CODE rollback never needs this: an E5.1, E5 or older backend is bound by E5.2 in the database
-- (retrieval and knowledge_cited_evidence_state decide admission). Use it only if the E5.2 stamping or gate changes
-- themselves malfunction (for example they block every approval). It:
--   * refuses unless the session states  set local knowledge.e5_2_rollback = 'safe-refusal-acknowledged';
--   * removes the generation bump and the stamps, and restores the E2 / E7.1 / E5.1 gate checks (tuple-only), so
--     reviews and approvals keep working under E5.1 rules;
--   * KEEPS the generation-bound retrieval (match_knowledge_chunks_lexical + knowledge_generation_admitted_documents)
--     and clears the pin as one final logged generation. Nothing made after the rollback is stamped, so retrieval
--     serves NO verified document, for every backend version (pre-E5 included), until E5.2 is re-applied: SAFE
--     REFUSAL. READ answers built from season data keep working; RECOMMEND/EVIDENCE answer insufficient_evidence;
--   * keeps the audit: the generation log (still append-only), the pin row's generation and every pin_generation
--     stamp stay; generations are never deleted or lowered. Re-applying E5.2 starts a generation above all of them,
--     so nothing approved before it (or during the rolled-back period) becomes current again: re-review.

begin;

do $$
begin
  if coalesce(current_setting('knowledge.e5_2_rollback', true), '') <> 'safe-refusal-acknowledged' then
    raise exception 'E5.2 rollback refused: it restores tuple-only pin checks (a pin set back to an earlier tuple'
      ' re-admits its approvals) and clears the pin. A code rollback does not need it. To proceed, run'
      ' set local knowledge.e5_2_rollback = ''safe-refusal-acknowledged'' in this transaction' using errcode = '55000';
  end if;
end;
$$;

drop trigger knowledge_integrity_reports_pin_generation on public.knowledge_integrity_reports;
drop trigger knowledge_integrity_verifications_pin_generation on public.knowledge_integrity_verifications;
drop trigger knowledge_approval_records_pin_generation on public.knowledge_approval_records;
drop trigger knowledge_integrity_policy_generation on private.knowledge_integrity_policy;
drop trigger knowledge_integrity_policy_generation_log on private.knowledge_integrity_policy;
drop trigger knowledge_integrity_policy_no_truncate on private.knowledge_integrity_policy;
drop trigger knowledge_integrity_reports_pin_generation_frozen on public.knowledge_integrity_reports;
drop trigger knowledge_integrity_verifications_pin_generation_frozen on public.knowledge_integrity_verifications;
drop trigger knowledge_approval_records_pin_generation_frozen on public.knowledge_approval_records;
drop function private.knowledge_pin_generation_frozen();
drop function private.knowledge_stamp_pin_generation();
drop function private.knowledge_pin_generation_next();
drop function private.knowledge_pin_generation_record();
drop function private.knowledge_corpus_integrity_inventory();

-- the gate's checks and admission: exactly as before E5.2 (retrieval is NOT restored: see the header)
create or replace function private.knowledge_integrity_report_problem(p_report public.knowledge_integrity_reports)
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_pin record;
  v_doc record;
begin
  if p_report.id is null then
    return 'no integrity report has been recorded for this version';
  end if;
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.registry_digest is null then
    return 'the integrity policy is not pinned';
  end if;
  if (p_report.extractor_version, p_report.review_version, p_report.registry_version, p_report.registry_digest)
     is distinct from (v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest) then
    return 'the report was made with an extractor, review or registry that is no longer the pinned one';
  end if;
  select d.source_id into v_doc from public.knowledge_documents d where d.id = p_report.document_pk;
  if p_report.document_snapshot_sha256
       <> private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(p_report.document_pk))
     or p_report.source_snapshot_sha256 <> private.knowledge_snapshot_sha256(private.knowledge_source_snapshot(v_doc.source_id)) then
    return 'the version or its source changed after the report (stale report)';
  end if;
  if p_report.claim_count <> (select count(*) from public.knowledge_claims c
                               where c.document_pk = p_report.document_pk and c.extractor_version = p_report.extractor_version) then
    return 'claims were recorded after the report; the report does not cover them';
  end if;
  return null;
end;
$$;

create or replace function private.knowledge_integrity_verification_problem(p_report public.knowledge_integrity_reports)
returns text
language plpgsql
set search_path = ''
as $$
declare
  v_pin record;
  v_ok record;
  v_chunks text;
begin
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.extractor_code_digest is null then
    return 'the extractor code digest is not pinned: no report can be independently verified';
  end if;
  if v_pin.attestation_mode is null then
    return 'the owner has not chosen an attestation mode: no verification is accepted';
  end if;
  -- the text that is served must still be the text whose hash the claims and the report are bound to
  v_chunks := private.knowledge_chunk_hash_problem(p_report.document_pk);
  if v_chunks is not null then
    return v_chunks;
  end if;
  if exists (select 1 from public.knowledge_integrity_verifications v
              where v.report_id = p_report.id and v.verdict = 'mismatch') then
    return 'an independent verification found the stored claim set does not reproduce (missing, extra or altered claims)';
  end if;
  select v.id into v_ok
    from public.knowledge_integrity_verifications v
    join public.knowledge_integrity_verifier_keys k on k.key_id = v.key_id and k.status = 'active'
   where v.report_id = p_report.id and v.report_sha256 = p_report.report_sha256 and v.verdict = 'reproduced'
     and v.document_snapshot_sha256 = p_report.document_snapshot_sha256
     and v.extractor_version = v_pin.extractor_version and v.extractor_code_digest = v_pin.extractor_code_digest
     and v.registry_digest = v_pin.registry_digest
     and (v.signature_checked_in_db or v_pin.attestation_mode = 'offline_signature_audit')
     and v.claim_set_digest = private.knowledge_claim_set_digest(p_report.document_pk, p_report.extractor_version)
   order by v.id desc limit 1
   for share of k;
  if v_ok.id is null then
    return 'no valid independent verification (signed by an active verifier key, accepted under the current'
      ' attestation mode, for the pinned extractor and registry) reproduces this report''s claim set';
  end if;
  return null;
end;
$$;

create or replace function private.knowledge_integrity_admission_problem(p_document_pk uuid)
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_pin record;
  v_report public.knowledge_integrity_reports;
begin
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.registry_digest is null or v_pin.extractor_code_digest is null or v_pin.attestation_mode is null then
    return 'policy_not_pinned';
  end if;
  v_report := private.knowledge_integrity_current_report(p_document_pk);
  if v_report.id is null then
    return 'no_report';
  end if;
  if (v_report.extractor_version, v_report.review_version, v_report.registry_version, v_report.registry_digest)
     is distinct from (v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest) then
    return 'report_not_under_current_pin';
  end if;
  if private.knowledge_integrity_report_problem(v_report) is not null then
    return 'report_stale';
  end if;
  if private.knowledge_chunk_hash_problem(p_document_pk) is not null then
    return 'chunk_hash_inconsistent';
  end if;
  if exists (select 1 from public.knowledge_integrity_verifications v
              where v.report_id = v_report.id and v.verdict = 'mismatch') then
    return 'verification_mismatch';
  end if;
  if not exists (
       select 1
         from public.knowledge_integrity_verifications v
         join public.knowledge_integrity_verifier_keys k on k.key_id = v.key_id and k.status = 'active'
        where v.report_id = v_report.id and v.report_sha256 = v_report.report_sha256 and v.verdict = 'reproduced'
          and v.document_snapshot_sha256 = v_report.document_snapshot_sha256
          and v.extractor_version = v_pin.extractor_version
          and v.extractor_code_digest = v_pin.extractor_code_digest
          and v.registry_digest = v_pin.registry_digest
          and (v.signature_checked_in_db or v_pin.attestation_mode = 'offline_signature_audit')
          and v.claim_set_digest = private.knowledge_claim_set_digest(p_document_pk, v_report.extractor_version)) then
    return 'not_verified_under_current_pin';
  end if;
  if not exists (
       select 1
         from public.knowledge_approval_records a
         join public.knowledge_integrity_dispositions x
           on x.review_id = a.review_id and x.report_id = v_report.id and x.finding_id is null
          and x.disposition = 'report_reviewed' and x.report_sha256 = v_report.report_sha256
        where a.entity_type = 'document' and a.document_pk = p_document_pk and a.decision = 'approve'
          and a.assurance = 'verified') then
    return 'approval_not_bound_to_report';
  end if;
  return null;
end;
$$;

-- SAFE REFUSAL: clear the pin as one final, logged generation (the log guard is kept and checks the row).
update private.knowledge_integrity_policy
   set extractor_version = null, review_version = null, registry_version = null, registry_digest = null,
       extractor_code_digest = null, attestation_mode = null, generation = generation + 1,
       set_at = pg_catalog.now(), set_by_session_user = session_user
 where singleton;
insert into private.knowledge_integrity_pin_generations (generation, extractor_version, review_version, registry_version,
  registry_digest, extractor_code_digest, attestation_mode, complete, reason)
select p.generation, null, null, null, null, null, null, false, 'schema_rollback_unpinned'
  from private.knowledge_integrity_policy p where p.singleton;

-- KEPT on purpose: private.knowledge_integrity_pin_generations with its guard triggers and functions
-- (knowledge_pin_generation_log_guard, knowledge_pin_no_truncate), the policy column `generation`, the
-- pin_generation columns of reports, verifications and approval records (audit), and the generation-bound
-- retrieval with its explanation signal (safe refusal: answers say documents await a re-check). The E5.1 rollback that follows, and the rollbacks after it, do not depend on them;
-- H-a's rollback replaces the retrieval function with its predecessor as before.

commit;
