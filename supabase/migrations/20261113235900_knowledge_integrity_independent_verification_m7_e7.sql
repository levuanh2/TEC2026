-- RAG V1.5 M7 E7 (docs/rag/RAG_V15_M7_E7_INDEPENDENT_VERIFICATION.md): an integrity report authorizes an
-- approval only with an INDEPENDENT, SIGNED verification that re-read the stored chunk text and reproduced
-- the stored claim set under the pinned extractor. LOCAL/CI ONLY until the owner approves a hosted
-- migration (it needs the pgsodium extension and a verifier key custody, section 6). dev3-01 stays OPEN.
-- Depends on E2 (20261113210000).
--
-- E7 (root cause): E2 checks a report's completeness only against the claims the operator STORED. Whoever
-- holds the shared service credential could store fewer claims (or run a weaker extractor) and record a
-- report that is complete relative to them: a falsely clean, admissible report.
--
-- Trust separation:
--   * report producer  (service_role): stores claims and the report, as in E2. Cannot certify them.
--   * verifier         (a separate process holding an Ed25519 PRIVATE key that the producer never has):
--                       re-reads the chunks, re-runs the pinned extractor, signs a canonical statement.
--   * database          verifies the signature with pgsodium.crypto_sign_verify_detached (libsodium) against
--                       a public key the OWNER registered, recomputes the digest of the stored claims and
--                       refuses a statement that does not match. Anyone may submit a statement; only the key
--                       holder can make one that verifies.
--   * owner             pins the extractor code digest and registers / revokes verifier public keys.
-- What it does NOT claim: the database owner / a superuser can replace these functions or register a key
-- (infrastructure boundary, unchanged). Reproducing the claim set proves the operator did not omit, add or
-- alter what the pinned extractor finds; it does not prove that the extractor finds every scientific claim.

-- pgsodium is OPTIONAL (E7.1, 20261114090000): Supabase lists it as pending deprecation. When it is installable it
-- is installed and signatures are verified in the database; otherwise the owner must choose the offline-audit
-- attestation mode explicitly (E7.1), and until then every verification is refused (fail closed).
do $pgsodium$
begin
  if exists (select 1 from pg_catalog.pg_available_extensions where name = 'pgsodium') then
    create extension if not exists pgsodium;
  end if;
end;
$pgsodium$;

-- ================================================================== policy: pinned extractor code digest

alter table private.knowledge_integrity_policy add column extractor_code_digest text;
alter table private.knowledge_integrity_policy add constraint knowledge_integrity_policy_code_chk
  check (extractor_code_digest is null or extractor_code_digest ~ '^[0-9a-f]{64}$');

create function private.knowledge_set_integrity_code_digest(p_extractor_code_digest text)
returns void
language plpgsql
set search_path = ''
as $$
begin
  update private.knowledge_integrity_policy
     set extractor_code_digest = p_extractor_code_digest, set_at = pg_catalog.now(), set_by_session_user = session_user
   where singleton;
end;
$$;
revoke all on function private.knowledge_set_integrity_code_digest(text) from public, anon, authenticated, service_role;

-- ================================================================== verifier keys (owner)

create table public.knowledge_integrity_verifier_keys (
  key_id text primary key,
  public_key bytea not null,
  label text not null,
  status text not null default 'active',
  registered_at timestamptz not null default now(),
  registered_by_session_user text not null default session_user,
  revoked_at timestamptz,
  revoked_reason text,
  constraint knowledge_integrity_verifier_keys_id_chk check (key_id ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
  constraint knowledge_integrity_verifier_keys_pk_chk check (length(public_key) = 32),
  constraint knowledge_integrity_verifier_keys_status_chk check (status in ('active', 'revoked')
    and (status = 'active') = (revoked_at is null))
);
create unique index knowledge_integrity_verifier_keys_public_uidx on public.knowledge_integrity_verifier_keys (public_key);
alter table public.knowledge_integrity_verifier_keys enable row level security;
revoke all on public.knowledge_integrity_verifier_keys from public, anon, authenticated, service_role;
grant select on public.knowledge_integrity_verifier_keys to service_role;

-- registered and revoked only through the owner functions below; a revocation is terminal
create function private.knowledge_verifier_key_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not private.knowledge_m2_write_authorized('knowledge_integrity_verifier_keys') then
    raise exception 'verifier keys are registered and revoked only by the owner functions (% refused)', tg_op
      using errcode = '42501';
  end if;
  if tg_op = 'UPDATE' and not (old.status = 'active' and new.status = 'revoked'
      and (new.key_id, new.public_key, new.label, new.registered_at) is not distinct from
          (old.key_id, old.public_key, old.label, old.registered_at)) then
    raise exception 'a verifier key only goes from active to revoked' using errcode = '42501';
  end if;
  if tg_op = 'DELETE' then
    raise exception 'verifier keys are never deleted (revoke instead)' using errcode = '42501';
  end if;
  return coalesce(new, old);
end;
$$;
revoke all on function private.knowledge_verifier_key_guard() from public, anon, authenticated, service_role;
create trigger knowledge_integrity_verifier_keys_guard
  before insert or update or delete on public.knowledge_integrity_verifier_keys
  for each row execute function private.knowledge_verifier_key_guard();
create trigger knowledge_integrity_verifier_keys_no_truncate
  before truncate on public.knowledge_integrity_verifier_keys
  for each statement execute function private.knowledge_m2_no_truncate();

-- Owner only (no grant). SECURITY DEFINER so the M2 write marker check (current_user = evidence owner) holds.
create function private.knowledge_register_verifier_key(p_key_id text, p_public_key bytea, p_label text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_label is null or length(btrim(p_label)) < 5 then
    raise exception 'a verifier key needs a label naming its custodian' using errcode = '22023';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_integrity_verifier_keys');
  insert into public.knowledge_integrity_verifier_keys (key_id, public_key, label) values (p_key_id, p_public_key, p_label);
  perform private.knowledge_m2_set_marker(null);
end;
$$;
revoke all on function private.knowledge_register_verifier_key(text, bytea, text) from public, anon, authenticated, service_role;

create function private.knowledge_revoke_verifier_key(p_key_id text, p_reason text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_reason is null or length(btrim(p_reason)) < 5 then
    raise exception 'a revocation needs a reason' using errcode = '22023';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_integrity_verifier_keys');
  update public.knowledge_integrity_verifier_keys set status = 'revoked', revoked_at = pg_catalog.now(), revoked_reason = p_reason
   where key_id = p_key_id and status = 'active';
  perform private.knowledge_m2_set_marker(null);
  if not found then
    raise exception 'no active verifier key %', p_key_id using errcode = 'P0002';
  end if;
end;
$$;
revoke all on function private.knowledge_revoke_verifier_key(text, text) from public, anon, authenticated, service_role;

-- ================================================================== canonical claim-set digest (= verifier.py)

create function private.knowledge_claim_set_digest(p_document_pk uuid, p_extractor_version text)
returns text
language sql
stable
set search_path = ''
as $$
  select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce(pg_catalog.string_agg(
           c.claim_id || '|' || c.chunk_id || '|' || c.chunk_content_sha256 || '|' || c.span_start::text || '|'
           || c.span_end::text || '|' || c.kind || '|' || c.status || '|' || coalesce(c.parameter, '') || '|'
           || coalesce(pg_catalog.trim_scale(c.value_min)::text, '') || '|'
           || coalesce(pg_catalog.trim_scale(c.value_max)::text, '') || '|' || coalesce(c.unit, '') || '|'
           || coalesce(c.dimension, '') || '|' || coalesce(pg_catalog.to_char(c.date_iso, 'YYYY-MM-DD'), '') || '|'
           || coalesce(c.stage, '') || '|'
           || pg_catalog.array_to_string(array(select t from pg_catalog.unnest(c.scope_tags) t order by t collate "C"), ','),
           E'\n' order by c.claim_id collate "C"), ''), 'UTF8')), 'hex')
    from public.knowledge_claims c
   where c.document_pk = p_document_pk and c.extractor_version = p_extractor_version;
$$;
revoke all on function private.knowledge_claim_set_digest(uuid, text) from public, anon, authenticated, service_role;

-- ================================================================== verification records

create table public.knowledge_integrity_verifications (
  id bigint generated always as identity primary key,
  report_id uuid not null references public.knowledge_integrity_reports (id),
  report_sha256 text not null,
  document_pk uuid not null,
  document_snapshot_sha256 text not null,
  source_snapshot_sha256 text not null,
  extractor_version text not null,
  extractor_code_digest text not null,
  registry_digest text not null,
  claim_set_digest text not null,
  claim_count integer not null,
  chunks_read integer not null,
  verdict text not null,
  missing text[] not null,
  extra text[] not null,
  altered text[] not null,
  key_id text not null references public.knowledge_integrity_verifier_keys (key_id),
  statement text not null,
  signature bytea not null,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  submitted_by_role text not null,
  constraint knowledge_integrity_verifications_verdict_chk check (verdict in ('reproduced', 'mismatch')),
  constraint knowledge_integrity_verifications_sig_chk check (length(signature) = 64)
);
create index knowledge_integrity_verifications_report_idx on public.knowledge_integrity_verifications (report_id);
alter table public.knowledge_integrity_verifications enable row level security;
revoke all on public.knowledge_integrity_verifications from public, anon, authenticated, service_role;
grant select on public.knowledge_integrity_verifications to service_role;
create trigger knowledge_integrity_verifications_guard before insert or update or delete on public.knowledge_integrity_verifications
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_integrity_verifications_no_truncate before truncate on public.knowledge_integrity_verifications
  for each statement execute function private.knowledge_m2_no_truncate();

-- Anyone holding the service credential may SUBMIT a statement; only the key holder can make one that
-- verifies. Everything in it is checked against the database's own state.
create function private.knowledge_record_integrity_verification(p_statement text, p_signature bytea)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_body jsonb;
  v_key record;
  v_report public.knowledge_integrity_reports;
  v_pin record;
  v_stored_digest text;
  v_stored_count integer;
  v_id bigint;
begin
  if p_statement is null or p_signature is null or length(p_signature) <> 64 or length(p_statement) > 200000 then
    raise exception 'a verification is a signed statement (64-byte Ed25519 signature)' using errcode = '22023';
  end if;
  begin
    v_body := p_statement::jsonb;
  exception when others then
    raise exception 'the statement is not JSON' using errcode = '22023';
  end;
  if v_body ->> 'format' is distinct from 'kn-integrity-verification-1' then
    raise exception 'unknown verification format' using errcode = '22023';
  end if;
  select k.key_id, k.public_key, k.status into v_key from public.knowledge_integrity_verifier_keys k
   where k.key_id = v_body ->> 'key_id' for share;
  if v_key.key_id is null or v_key.status <> 'active' then
    raise exception 'verification refused: % is not an active registered verifier key', v_body ->> 'key_id'
      using errcode = '42501';
  end if;
  if not pgsodium.crypto_sign_verify_detached(p_signature, pg_catalog.convert_to(p_statement, 'UTF8'), v_key.public_key) then
    raise exception 'verification refused: the signature does not verify with key %', v_key.key_id using errcode = '42501';
  end if;
  select r.* into v_report from public.knowledge_integrity_reports r where r.id = (v_body ->> 'report_id')::uuid for share;
  if v_report.id is null or v_report.report_sha256 is distinct from v_body ->> 'report_sha256'
     or v_report.document_pk::text is distinct from v_body ->> 'document_pk'
     or v_report.document_snapshot_sha256 is distinct from v_body ->> 'document_snapshot_sha256'
     or v_report.source_snapshot_sha256 is distinct from v_body ->> 'source_snapshot_sha256' then
    raise exception 'verification refused: it is not a statement about this report and its snapshots' using errcode = '23514';
  end if;
  if private.knowledge_integrity_report_problem(v_report) is not null then
    raise exception 'verification refused: %', private.knowledge_integrity_report_problem(v_report) using errcode = '23514';
  end if;
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.extractor_code_digest is null then
    raise exception 'verification refused: the extractor code digest is not pinned' using errcode = '42501';
  end if;
  if (v_body ->> 'extractor_version', v_body ->> 'extractor_code_digest', v_body ->> 'registry_digest')
     is distinct from (v_pin.extractor_version, v_pin.extractor_code_digest, v_pin.registry_digest) then
    raise exception 'verification refused: the verifier ran another extractor or registry than the pinned one'
      using errcode = '23514';
  end if;
  v_stored_digest := private.knowledge_claim_set_digest(v_report.document_pk, v_report.extractor_version);
  select count(*) into v_stored_count from public.knowledge_claims c
   where c.document_pk = v_report.document_pk and c.extractor_version = v_report.extractor_version;
  -- a statement that says "reproduced" must be literally true of the stored claims
  if v_body ->> 'verdict' = 'reproduced' and (v_body ->> 'claim_set_digest' is distinct from v_stored_digest
      or (v_body ->> 'claim_count')::integer <> v_stored_count
      or (v_body ->> 'chunks_read')::integer <> v_report.chunk_count) then
    raise exception 'verification refused: the verifier''s claim set is not the stored one' using errcode = '23514';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_integrity_verifications');
  insert into public.knowledge_integrity_verifications (report_id, report_sha256, document_pk, document_snapshot_sha256,
    source_snapshot_sha256, extractor_version, extractor_code_digest, registry_digest, claim_set_digest, claim_count,
    chunks_read, verdict, missing, extra, altered, key_id, statement, signature, submitted_by_role)
  values (v_report.id, v_report.report_sha256, v_report.document_pk, v_report.document_snapshot_sha256,
    v_report.source_snapshot_sha256, v_body ->> 'extractor_version', v_body ->> 'extractor_code_digest',
    v_body ->> 'registry_digest', v_body ->> 'claim_set_digest', (v_body ->> 'claim_count')::integer,
    (v_body ->> 'chunks_read')::integer, v_body ->> 'verdict',
    array(select pg_catalog.jsonb_array_elements_text(coalesce(v_body -> 'missing', '[]'))),
    array(select pg_catalog.jsonb_array_elements_text(coalesce(v_body -> 'extra', '[]'))),
    array(select pg_catalog.jsonb_array_elements_text(coalesce(v_body -> 'altered', '[]'))),
    v_key.key_id, p_statement, p_signature, coalesce(nullif(current_setting('role', true), 'none'), session_user))
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function private.knowledge_record_integrity_verification(text, bytea) from public, anon, authenticated, service_role;
grant execute on function private.knowledge_record_integrity_verification(text, bytea) to service_role;

-- Why the report has no usable independent verification, or null. Share-locks the key it relies on, so
-- a revocation and an approval serialize.
create function private.knowledge_integrity_verification_problem(p_report public.knowledge_integrity_reports)
returns text
language plpgsql
set search_path = ''
as $$
declare
  v_pin record;
  v_ok record;
begin
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.extractor_code_digest is null then
    return 'the extractor code digest is not pinned: no report can be independently verified';
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
     and v.claim_set_digest = private.knowledge_claim_set_digest(p_report.document_pk, p_report.extractor_version)
   order by v.id desc limit 1
   for share of k;
  if v_ok.id is null then
    return 'no valid independent verification (signed by an active verifier key, for the pinned extractor and'
      ' registry) reproduces this report''s claim set';
  end if;
  return null;
end;
$$;
revoke all on function private.knowledge_integrity_verification_problem(public.knowledge_integrity_reports)
  from public, anon, authenticated, service_role;

-- ================================================================== the gate (replaced)

-- E2's gate, plus the independent verification of the report.
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
  -- M7 E7: an independent, signed verification must reproduce this report's claim set
  v_problem := private.knowledge_integrity_verification_problem(v_report);
  if v_problem is not null then
    raise exception 'integrity gate (E7): %', v_problem using errcode = '23514';
  end if;
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
