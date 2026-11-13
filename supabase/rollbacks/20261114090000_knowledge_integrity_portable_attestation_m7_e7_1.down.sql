-- Rollback for migrations/20261114090000_knowledge_integrity_portable_attestation_m7_e7_1.sql (RAG V1.5 M7 E7.1).
-- Not in migrations/: run by hand, in ONE transaction, BEFORE the E7 rollback, then
--   supabase migration repair --status reverted 20261114090000
-- Restores E7's exact recording RPC (service_role relays, pgsodium REQUIRED) and verification check. It
-- REFUSES while any verification was accepted without an in-database signature check (offline audit mode):
-- E7 would treat it as signature-checked. Drops the verifier schema and the NOLOGIN group role (memberships
-- granted to login roles go with it). Needs
--   set local knowledge.e7_1_rollback_confirmed = 'yes'

begin;

do $$
begin
  if coalesce(current_setting('knowledge.e7_1_rollback_confirmed', true), '') <> 'yes' then
    raise exception 'E7.1 rollback restores the service-role verification RPC: set local knowledge.e7_1_rollback_confirmed = ''yes''';
  end if;
  if exists (select 1 from public.knowledge_integrity_verifications where not signature_checked_in_db) then
    raise exception 'E7.1 rollback refused: verifications accepted without an in-database signature check exist;'
      ' E7 would treat them as signature-checked';
  end if;
end;
$$;

drop function knowledge_verifier.record_verification(text, bytea);
drop function knowledge_verifier.verification_input(uuid);
drop schema knowledge_verifier;

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

create or replace function private.knowledge_integrity_verification_problem(p_report public.knowledge_integrity_reports)
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

alter table public.knowledge_integrity_verifications
  drop column signature_checked_in_db, drop column attestation_mode, drop column submitted_by_session_user;
drop function private.knowledge_verifier_caller();
drop function private.knowledge_chunk_hash_problem(uuid);
drop function private.knowledge_set_attestation_mode(text);
drop function private.knowledge_ed25519_verify(bytea, bytea, bytea);
drop function private.knowledge_ed25519_available();
alter table private.knowledge_integrity_policy drop constraint knowledge_integrity_policy_attestation_chk;
alter table private.knowledge_integrity_policy drop column attestation_mode;
drop role if exists knowledge_integrity_verifier;

commit;
