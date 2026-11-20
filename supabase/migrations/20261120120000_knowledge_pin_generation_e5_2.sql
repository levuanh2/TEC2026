-- RAG V1.5 M7 E5.2 (docs/rag/RAG_V15_M7_E5_2_PIN_GENERATION.md): pin generations, generation-bound evidence and
-- admission-aware retrieval. LOCAL/CI ONLY: BLOCKED FOR HOSTED until the owner approves (D-ROLLOUT, 2026-11-20).
-- dev3-01 stays OPEN. Depends on E2, E7, E7.1, E5 and E5.1 (20261120090000).
--
-- P1 (rollback re-activation). E5.1 compared evidence with the pin TUPLE, so setting the pin back to an earlier
-- tuple re-admitted every approval made under it. E5.2 adds a security EPOCH, the pin generation:
--   * every UPDATE of the pin row (any of the owner functions, a repeated identical pin, a direct owner UPDATE)
--     makes generation = previous + 1, under the row lock, so concurrent changes serialize and a failed
--     transaction consumes nothing; a supplied value is ignored, the row cannot be deleted or truncated;
--   * every generation is logged, append-only, with the tuple it pinned (private.knowledge_integrity_pin_generations);
--   * every report, verification and approval record is stamped AT INSERT, by a trigger, with the generation it was
--     made in (read under a share lock of the pin row; a report or verification whose tuple is not the pinned one is
--     refused); a client cannot supply or change the stamp; rows made before E5.2 keep NULL (never current);
--   * the approval gate requires the report and the verification of the CURRENT generation; admission (E5.1 gates and
--     retrieval) requires report, verification and approval of the current generation.
-- A -> B -> A, or A -> A, therefore never revives anything: the evidence is of an earlier generation.
--
-- P3 (retrieval starvation). Retrieval selects only chunks of versions admitted in the current generation BEFORE
-- ranking and before top_k (private.knowledge_generation_admitted_documents: indexed lookups, no hashing). The full
-- E5.1 check (snapshot, chunk hashes, recomputed claim-set digest) stays in gate 1 and gate 2. A backend that
-- predates E5.1 (or E5) therefore never receives a chunk of a version not admitted IN THE CURRENT GENERATION; it can
-- still receive one whose content hash, snapshot or claim set no longer matches (gates 1 and 2 catch those).
--
-- Applying (or re-applying after a rollback) STARTS A NEW GENERATION strictly above every recorded one: evidence
-- made before is never current again (owner rule: no generation is assigned to old approvals to legitimize them).

-- ================================================================== the epoch

alter table private.knowledge_integrity_policy add column if not exists generation bigint not null default 0;

create table if not exists private.knowledge_integrity_pin_generations (
  generation bigint primary key,
  extractor_version text,
  review_version text,
  registry_version text,
  registry_digest text,
  extractor_code_digest text,
  attestation_mode text,
  complete boolean not null,
  reason text not null,
  changed_at timestamptz not null default clock_timestamp(),
  changed_by_session_user text not null default session_user,
  changed_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_integrity_pin_generations_reason_chk
    check (reason in ('pin_change', 'migration_apply', 'schema_rollback_unpinned'))
);
revoke all on private.knowledge_integrity_pin_generations from public, anon, authenticated, service_role;

-- E5.2's own truncate guard (no dependency on M2 objects: the log outlives an E5.2 rollback).
create or replace function private.knowledge_pin_no_truncate()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception '%: truncate is refused (integrity pin and its generation log)', tg_table_name using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_pin_no_truncate() from public, anon, authenticated, service_role;

-- The log is append-only, and a row can only state the pin row as it is now (written by the pin trigger, by this
-- migration, or by the rollback's final unpin).
create or replace function private.knowledge_pin_generation_log_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_pin record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'the pin generation log is append-only' using errcode = '42501';
  end if;
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if new.generation is distinct from v_pin.generation
     or (new.extractor_version, new.review_version, new.registry_version, new.registry_digest,
         new.extractor_code_digest, new.attestation_mode)
        is distinct from (v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest,
                          v_pin.extractor_code_digest, v_pin.attestation_mode) then
    raise exception 'a pin generation log row must state the current pin row' using errcode = '42501';
  end if;
  return new;
end;
$$;
revoke all on function private.knowledge_pin_generation_log_guard() from public, anon, authenticated, service_role;
create or replace trigger knowledge_integrity_pin_generations_guard
  before insert or update or delete on private.knowledge_integrity_pin_generations
  for each row execute function private.knowledge_pin_generation_log_guard();
create or replace trigger knowledge_integrity_pin_generations_no_truncate
  before truncate on private.knowledge_integrity_pin_generations
  for each statement execute function private.knowledge_pin_no_truncate();

-- This migration starts a generation strictly above any recorded one (a re-apply after a rollback included). Any
-- E5.2 pin trigger still present (a re-run without the rollback) is removed first and re-created below, so the bump
-- is logged once, as `migration_apply`.
drop trigger if exists knowledge_integrity_policy_generation on private.knowledge_integrity_policy;
drop trigger if exists knowledge_integrity_policy_generation_log on private.knowledge_integrity_policy;
update private.knowledge_integrity_policy
   set generation = greatest(generation,
                             coalesce((select max(g.generation) from private.knowledge_integrity_pin_generations g), 0)) + 1
 where singleton;
insert into private.knowledge_integrity_pin_generations (generation, extractor_version, review_version, registry_version,
  registry_digest, extractor_code_digest, attestation_mode, complete, reason)
select p.generation, p.extractor_version, p.review_version, p.registry_version, p.registry_digest,
       p.extractor_code_digest, p.attestation_mode,
       p.registry_digest is not null and p.extractor_code_digest is not null and p.attestation_mode is not null,
       'migration_apply'
  from private.knowledge_integrity_policy p where p.singleton;

-- Every UPDATE of the pin row is a new generation (identical values included: an explicit re-pin is a new epoch).
create or replace function private.knowledge_pin_generation_next()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'the integrity pin row cannot be deleted (unpin it with private.knowledge_set_integrity_policy)'
      using errcode = '42501';
  end if;
  new.generation := old.generation + 1;                 -- under the row lock; any supplied value is ignored
  return new;
end;
$$;
revoke all on function private.knowledge_pin_generation_next() from public, anon, authenticated, service_role;

create or replace function private.knowledge_pin_generation_record()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  insert into private.knowledge_integrity_pin_generations (generation, extractor_version, review_version,
    registry_version, registry_digest, extractor_code_digest, attestation_mode, complete, reason)
  values (new.generation, new.extractor_version, new.review_version, new.registry_version, new.registry_digest,
          new.extractor_code_digest, new.attestation_mode,
          new.registry_digest is not null and new.extractor_code_digest is not null and new.attestation_mode is not null,
          'pin_change');
  return null;
end;
$$;
revoke all on function private.knowledge_pin_generation_record() from public, anon, authenticated, service_role;

create or replace trigger knowledge_integrity_policy_generation
  before update or delete on private.knowledge_integrity_policy
  for each row execute function private.knowledge_pin_generation_next();
create or replace trigger knowledge_integrity_policy_generation_log
  after update on private.knowledge_integrity_policy
  for each row execute function private.knowledge_pin_generation_record();
create or replace trigger knowledge_integrity_policy_no_truncate
  before truncate on private.knowledge_integrity_policy
  for each statement execute function private.knowledge_pin_no_truncate();

-- ================================================================== generation stamps (trusted, at insert)

alter table public.knowledge_integrity_reports add column if not exists pin_generation bigint;
alter table public.knowledge_integrity_verifications add column if not exists pin_generation bigint;
alter table public.knowledge_approval_records add column if not exists pin_generation bigint;

-- SECURITY DEFINER: the pin row is private whoever inserts. Share-locks the pin row, so a stamp and a pin change
-- serialize: a row is stamped with the generation whose tuple it was made under, or refused.
create or replace function private.knowledge_stamp_pin_generation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_pin record;
begin
  select * into v_pin from private.knowledge_integrity_policy where singleton for share;
  if v_pin.generation is null then
    raise exception 'the integrity pin row is missing: nothing can be stamped' using errcode = '42501';
  end if;
  -- (nested IFs: PL/pgSQL may evaluate both sides of AND, and only these tables have these fields)
  if tg_table_name = 'knowledge_integrity_reports' then
    if (new.extractor_version, new.review_version, new.registry_version, new.registry_digest)
       is distinct from (v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest) then
      raise exception 'the pin changed while the report was recorded: record it again under the current pin'
        using errcode = '23514';
    end if;
  elsif tg_table_name = 'knowledge_integrity_verifications' then
    if (new.extractor_version, new.extractor_code_digest, new.registry_digest)
       is distinct from (v_pin.extractor_version, v_pin.extractor_code_digest, v_pin.registry_digest)
       or new.attestation_mode is distinct from v_pin.attestation_mode then
      raise exception 'the pin changed while the verification was recorded: verify again under the current pin'
        using errcode = '23514';
    end if;
  end if;
  new.pin_generation := v_pin.generation;               -- any supplied value is ignored
  return new;
end;
$$;
revoke all on function private.knowledge_stamp_pin_generation() from public, anon, authenticated, service_role;

-- Defence in depth (the M2/E2 evidence guards already refuse it): a stamp never changes once written.
create or replace function private.knowledge_pin_generation_frozen()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.pin_generation is distinct from old.pin_generation then
    raise exception '%: pin_generation is written once, at insert', tg_table_name using errcode = '42501';
  end if;
  return new;
end;
$$;
revoke all on function private.knowledge_pin_generation_frozen() from public, anon, authenticated, service_role;
create or replace trigger knowledge_integrity_reports_pin_generation_frozen
  before update on public.knowledge_integrity_reports
  for each row execute function private.knowledge_pin_generation_frozen();
create or replace trigger knowledge_integrity_verifications_pin_generation_frozen
  before update on public.knowledge_integrity_verifications
  for each row execute function private.knowledge_pin_generation_frozen();
create or replace trigger knowledge_approval_records_pin_generation_frozen
  before update on public.knowledge_approval_records
  for each row execute function private.knowledge_pin_generation_frozen();

create or replace trigger knowledge_integrity_reports_pin_generation
  before insert on public.knowledge_integrity_reports
  for each row execute function private.knowledge_stamp_pin_generation();
create or replace trigger knowledge_integrity_verifications_pin_generation
  before insert on public.knowledge_integrity_verifications
  for each row execute function private.knowledge_stamp_pin_generation();
create or replace trigger knowledge_approval_records_pin_generation
  before insert on public.knowledge_approval_records
  for each row execute function private.knowledge_stamp_pin_generation();

-- ================================================================== the approval gate's checks (replaced)

-- E2's check, plus: the report must be of the CURRENT generation.
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
  if p_report.pin_generation is null then
    return 'the report has no pin generation (recorded before E5.2): record a new report';
  end if;
  if p_report.pin_generation is distinct from v_pin.generation then
    return 'the report was recorded in an earlier pin generation (the pin was changed since): record a new report';
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
revoke all on function private.knowledge_integrity_report_problem(public.knowledge_integrity_reports)
  from public, anon, authenticated, service_role;

-- E7.1's check, plus: share-locks the pin row (an approval and a pin change serialize) and accepts only a
-- verification of the CURRENT generation.
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
  select * into v_pin from private.knowledge_integrity_policy where singleton for share;
  if v_pin.extractor_code_digest is null then
    return 'the extractor code digest is not pinned: no report can be independently verified';
  end if;
  if v_pin.attestation_mode is null then
    return 'the owner has not chosen an attestation mode: no verification is accepted';
  end if;
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
     and v.pin_generation = v_pin.generation
     and (v.signature_checked_in_db or v_pin.attestation_mode = 'offline_signature_audit')
     and v.claim_set_digest = private.knowledge_claim_set_digest(p_report.document_pk, p_report.extractor_version)
   order by v.id desc limit 1
   for share of k;
  if v_ok.id is null then
    return 'no valid independent verification (signed by an active verifier key, accepted under the current'
      ' attestation mode, for the pinned extractor and registry, in the current pin generation) reproduces this'
      ' report''s claim set';
  end if;
  return null;
end;
$$;
revoke all on function private.knowledge_integrity_verification_problem(public.knowledge_integrity_reports)
  from public, anon, authenticated, service_role;

-- ================================================================== admission (E5.1 replaced: generation-bound)

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
  if v_pin.registry_digest is null or v_pin.extractor_code_digest is null or v_pin.attestation_mode is null
     or v_pin.generation is null then
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
  if v_report.pin_generation is null then
    return 'generation_missing';
  end if;
  if v_report.pin_generation <> v_pin.generation then
    return 'report_from_earlier_generation';
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
          and v.pin_generation = v_pin.generation
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
  -- the SAME approval record (one that acknowledged this report) must be of the current generation
  if not exists (
       select 1
         from public.knowledge_approval_records a
         join public.knowledge_integrity_dispositions x
           on x.review_id = a.review_id and x.report_id = v_report.id and x.finding_id is null
          and x.disposition = 'report_reviewed' and x.report_sha256 = v_report.report_sha256
        where a.entity_type = 'document' and a.document_pk = p_document_pk and a.decision = 'approve'
          and a.assurance = 'verified' and a.pin_generation = v_pin.generation) then
    return 'approval_from_earlier_generation';
  end if;
  return null;
end;
$$;
revoke all on function private.knowledge_integrity_admission_problem(uuid) from public, anon, authenticated, service_role;

-- ================================================================== admission-aware retrieval

-- The verified, approved versions the caller may retrieve for this season that were ADMITTED IN THE CURRENT
-- GENERATION: latest report of the pinned tuple and generation; a reproduced verification of it in this generation by
-- an active key under the current attestation mode, and no mismatch; an approval of this generation that acknowledged
-- that report. Indexed lookups only (no snapshot, chunk or claim hashing: gates 1 and 2 still run the full E5.1 check).
-- SECURITY DEFINER (the pin and the E2/E7 tables are private); answers only with document ids the caller may
-- retrieve for this season (same scope as retrieval), and nothing for an unreadable season.
create or replace function private.knowledge_generation_admitted_documents(p_crop_season_id uuid)
returns table (document_pk uuid)
language sql
stable
security definer
set search_path = ''
as $$
  with pin as (
    select p.* from private.knowledge_integrity_policy p
     where p.singleton and p.registry_digest is not null and p.extractor_code_digest is not null
       and p.attestation_mode is not null
  ),
  scope as (
    select pl.farm_id, f.cooperative_id as organization_id
      from public.crop_seasons cs
      join public.plots pl on pl.id = cs.plot_id
      join public.farms f on f.id = pl.farm_id
     where cs.id = p_crop_season_id
       and not private.knowledge_read_blocked()
       and private.user_can_read_farm(pl.farm_id)
  ),
  docs as (
    select d.id
      from public.knowledge_documents d
      join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
       and s.approval_assurance = 'verified'
      cross join scope
     where d.status = 'approved' and d.approval_assurance = 'verified'
       and (s.visibility = 'public'
            or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
                and (s.farm_id is null
                     or (s.farm_id = scope.farm_id
                         and exists (select 1 from public.farms f2
                                      where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))))
  )
  select d.id
    from docs d
   cross join pin
   cross join lateral (select r.id, r.report_sha256, r.extractor_version, r.review_version, r.registry_version,
                              r.registry_digest, r.pin_generation
                         from public.knowledge_integrity_reports r where r.document_pk = d.id
                        order by r.recorded_at desc, r.id desc limit 1) r
   where r.pin_generation = pin.generation
     and (r.extractor_version, r.review_version, r.registry_version, r.registry_digest)
         = (pin.extractor_version, pin.review_version, pin.registry_version, pin.registry_digest)
     and not exists (select 1 from public.knowledge_integrity_verifications v
                      where v.report_id = r.id and v.verdict = 'mismatch')
     and exists (select 1 from public.knowledge_integrity_verifications v
                   join public.knowledge_integrity_verifier_keys k on k.key_id = v.key_id and k.status = 'active'
                  where v.report_id = r.id and v.report_sha256 = r.report_sha256 and v.verdict = 'reproduced'
                    and v.pin_generation = pin.generation and v.extractor_code_digest = pin.extractor_code_digest
                    and v.extractor_version = pin.extractor_version and v.registry_digest = pin.registry_digest
                    and (v.signature_checked_in_db or pin.attestation_mode = 'offline_signature_audit'))
     and exists (select 1 from public.knowledge_approval_records a
                   join public.knowledge_integrity_dispositions x
                     on x.review_id = a.review_id and x.report_id = r.id and x.finding_id is null
                    and x.disposition = 'report_reviewed' and x.report_sha256 = r.report_sha256
                  where a.entity_type = 'document' and a.document_pk = d.id and a.decision = 'approve'
                    and a.assurance = 'verified' and a.pin_generation = pin.generation);
$$;
revoke all on function private.knowledge_generation_admitted_documents(uuid) from public, anon, authenticated, service_role;
-- service_role may call retrieval (granted since Migration A); it has no farm scope (auth.uid() is null), so it gets
-- no admitted document: service-role retrieval of verified knowledge is fail-closed. No answer path uses it.
grant execute on function private.knowledge_generation_admitted_documents(uuid) to authenticated, service_role;

-- ================================================================== the explanation signal (caller scope, boolean)

-- With retrieval admission-aware, a request whose documents were all suspended by a re-pin retrieves nothing and the
-- backend can no longer tell "nothing approved" from "approved but awaiting re-check". This answers exactly that, for
-- the caller's own season scope (public sources and the caller's own tenant, the retrieval predicate) and with ONE
-- boolean: is there an approved, verified version in force that is NOT admitted in the current generation? No count,
-- no id, no title, nothing for an unreadable season. It is an explanation, never an admission: the answer stays
-- insufficient_evidence and no document is used.
create or replace function private.knowledge_scope_has_suspended_evidence(p_crop_season_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  with scope as (
    select pl.farm_id, f.cooperative_id as organization_id
      from public.crop_seasons cs
      join public.plots pl on pl.id = cs.plot_id
      join public.farms f on f.id = pl.farm_id
     where cs.id = p_crop_season_id
       and not private.knowledge_read_blocked()
       and private.user_can_read_farm(pl.farm_id)
  )
  select exists (
    select 1
      from public.knowledge_documents d
      join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
       and s.approval_assurance = 'verified'
      cross join scope
     where d.status = 'approved' and d.approval_assurance = 'verified'
       and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
       and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
       and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
       and (s.visibility = 'public'
            or (s.visibility = 'tenant' and s.organization_id = scope.organization_id
                and (s.farm_id is null
                     or (s.farm_id = scope.farm_id
                         and exists (select 1 from public.farms f2
                                      where f2.id = s.farm_id and f2.cooperative_id = s.organization_id)))))
       and not exists (select 1 from private.knowledge_generation_admitted_documents(p_crop_season_id) g
                        where g.document_pk = d.id));
$$;
revoke all on function private.knowledge_scope_has_suspended_evidence(uuid) from public, anon, authenticated, service_role;
grant execute on function private.knowledge_scope_has_suspended_evidence(uuid) to authenticated;

create or replace function public.knowledge_evidence_awaiting_recheck(p_crop_season_id uuid)
returns table (awaiting boolean)
language sql
stable
security invoker
set search_path = ''
as $$
  select private.knowledge_scope_has_suspended_evidence(p_crop_season_id);
$$;
revoke all on function public.knowledge_evidence_awaiting_recheck(uuid) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_evidence_awaiting_recheck(uuid) to authenticated;

-- Retrieval (H-a's function, replaced): identical except the generation-admitted join in `eligible`.
create or replace function public.match_knowledge_chunks_lexical(
  p_crop_season_id uuid,
  p_query text,
  p_top_k integer default 8
)
returns table (
  source_id text,
  document_id text,
  document_version text,
  chunk_id text,
  ordinal integer,
  title text,
  section_path text,
  page_from integer,
  page_to integer,
  content text,
  metadata jsonb,
  source_type text,
  authority text,
  visibility text,
  organization_id uuid,
  farm_id uuid,
  official_url text,
  published_at date,
  fused_score double precision,
  fts_rank integer,
  trgm_rank integer
)
language sql
stable
security invoker
set search_path = ''
as $$
  with scope as (
    select p.farm_id, f.cooperative_id as organization_id
    from public.crop_seasons cs
    join public.plots p on p.id = cs.plot_id
    join public.farms f on f.id = p.farm_id
    where cs.id = p_crop_season_id
  ),
  q as (
    select private.knowledge_search_text(left(p_query, 1000)) as text
  ),
  query as (
    select q.text, replace(plainto_tsquery('simple'::regconfig, q.text)::text, ' & ', ' | ')::tsquery as tsq
    from q where q.text <> ''
  ),
  eligible as (
    select c.id, c.chunk_id, c.ordinal, c.section_path, c.page_from, c.page_to, c.content, c.metadata,
           c.search_text, c.search_tsv,
           d.source_id, d.document_id, d.document_version, d.title, d.official_url, d.published_at,
           s.source_type, s.authority, s.visibility, s.organization_id, s.farm_id
    from public.knowledge_chunks c
    join public.knowledge_documents d on d.id = c.document_pk and d.status = 'approved'
      -- H-a: expert-verified approvals only
      and d.approval_assurance = 'verified'
      -- M3: in force today (policy date), whether or not the expiry job has run yet
      and (d.effective_from is null or d.effective_from <= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and (d.effective_to is null or d.effective_to >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date)
      and d.approval_expires_on >= (pg_catalog.now() at time zone 'Asia/Ho_Chi_Minh')::date
    join public.knowledge_sources s on s.source_id = d.source_id and s.status = 'approved'
      and s.approval_assurance = 'verified'
    -- M7 E5.2: only versions admitted in the CURRENT pin generation are ranked (no stale chunk takes a slot)
    join private.knowledge_generation_admitted_documents(p_crop_season_id) ga on ga.document_pk = d.id
    cross join scope
    where s.visibility = 'public'
       or (s.visibility = 'tenant'
           and s.organization_id = scope.organization_id
           and (s.farm_id is null
                or (s.farm_id = scope.farm_id
                    and exists (select 1 from public.farms f2
                                where f2.id = s.farm_id and f2.cooperative_id = s.organization_id))))
  ),
  fts as (
    select e.id, row_number() over (
             order by ts_rank_cd(e.search_tsv, query.tsq) desc,
                      e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id)::integer as rnk
    from eligible e cross join query
    where e.search_tsv @@ query.tsq
    order by rnk
    limit 50
  ),
  trgm as (
    select e.id, row_number() over (
             order by extensions.word_similarity(query.text, e.search_text) desc,
                      e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id)::integer as rnk
    from eligible e cross join query
    where query.text operator(extensions.<%) e.search_text
    order by rnk
    limit 50
  ),
  fused as (
    select coalesce(fts.id, trgm.id) as id, fts.rnk as fts_rank, trgm.rnk as trgm_rank,
           coalesce(1.0 / (60 + fts.rnk), 0) + coalesce(1.0 / (60 + trgm.rnk), 0) as fused_score
    from fts full join trgm on trgm.id = fts.id
  )
  select e.source_id, e.document_id, e.document_version, e.chunk_id, e.ordinal, e.title, e.section_path,
         e.page_from, e.page_to, e.content, e.metadata, e.source_type, e.authority, e.visibility,
         e.organization_id, e.farm_id, e.official_url, e.published_at,
         fused.fused_score::double precision, fused.fts_rank, fused.trgm_rank
  from fused join eligible e on e.id = fused.id
  order by fused.fused_score desc, e.source_id, e.document_id, e.document_version, e.ordinal, e.chunk_id
  limit least(greatest(coalesce(p_top_k, 8), 1), 50);
$$;


-- ================================================================== corpus impact inventory (owner session only)

-- Every document version (any status) with the state of its integrity evidence in the CURRENT generation: the input
-- of the read-only re-pin impact assessment (backend/scripts/knowledge_repin_impact.py). No content, no title.
-- Owner-only: it names private review state of every tenant.
create or replace function private.knowledge_corpus_integrity_inventory()
returns table (
  document_pk uuid,
  source_id text,
  document_status text,
  approval_assurance text,
  source_status text,
  source_assurance text,
  visibility text,
  current_generation bigint,
  report_id uuid,
  report_extractor_version text,
  report_generation bigint,
  verified_in_generation bigint,
  approved_in_generation bigint,
  open_blocking_findings integer,
  admission_problem text
)
language sql
stable
set search_path = ''
as $$
  select d.id, d.source_id, d.status::text, d.approval_assurance::text, s.status::text, s.approval_assurance::text,
         s.visibility::text, p.generation, r.id, r.extractor_version, r.pin_generation,
         (select max(v.pin_generation) from public.knowledge_integrity_verifications v
           where v.report_id = r.id and v.verdict = 'reproduced'),
         (select max(a.pin_generation) from public.knowledge_approval_records a
           where a.entity_type = 'document' and a.document_pk = d.id and a.decision = 'approve'),
         (select count(*)::integer from public.knowledge_integrity_findings f
           where f.report_id = r.id and f.needs_expert_review),
         case when d.status <> 'approved' then 'not_approved'
              when d.approval_assurance <> 'verified' then 'not_verified_assurance'
              else private.knowledge_integrity_admission_problem(d.id) end
    from public.knowledge_documents d
    join public.knowledge_sources s on s.source_id = d.source_id
    cross join private.knowledge_integrity_policy p
    left join lateral (select x.* from public.knowledge_integrity_reports x where x.document_pk = d.id
                        order by x.recorded_at desc, x.id desc limit 1) r on true
   where p.singleton
   order by d.source_id, d.document_id, d.document_version, d.id;
$$;
revoke all on function private.knowledge_corpus_integrity_inventory() from public, anon, authenticated, service_role;
