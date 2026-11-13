-- RAG V1.5 M7 E7.1 (docs/rag/RAG_V15_M7_E7_1_PORTABLE_ATTESTATION.md): a portable, owner-controlled trust
-- boundary for independent integrity verification that does not DEPEND on pgsodium (Supabase: "pending
-- deprecation", not recommended for new usage), plus chunk-text provenance. LOCAL/CI ONLY until the owner
-- approves a hosted migration. dev3-01 stays OPEN. Depends on E7 (20261113235900).
--
-- 1. A verification is submitted ONLY by the dedicated verifier role `knowledge_integrity_verifier` (a NOLOGIN
--    group; the owner grants it to the verifier's own login role, out of band) through the
--    `knowledge_verifier` schema. The report producer (service_role, authenticator, client roles) has no
--    usage on that schema, and the database refuses if any of them is ever made a member of the group.
--    The DB owner is refused unless it deliberately SETs the verifier role (threat 6 stays out of scope).
-- 2. The Ed25519 signature is verified IN the database whenever pgsodium is installed. Without pgsodium the
--    owner must EXPLICITLY choose `offline_signature_audit`: rows are then accepted on the verifier role's
--    identity, the signature is stored and audited offline (infrastructure/integrity_verifier.py --audit).
--    No mode chosen = every verification refused (fail closed). Rows accepted without an in-database check
--    stop authorizing as soon as the owner switches to `in_database_signature`.
-- 3. The verifier reads only the version under review (knowledge_verifier.verification_input), never the
--    tables: no other document's text, no tenant data beyond the evidence it must re-extract.
-- 4. Chunk provenance: knowledge_chunks.content_sha256 must equal sha256(content UTF-8) (the ingestion
--    contract, knowledge/chunking.py). A version with any other chunk can neither be verified "reproduced"
--    nor pass the gate. Existing rows are NOT rewritten; a legacy version is re-ingested as a new version.

-- ================================================================== the verifier group role and schema

do $role$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'knowledge_integrity_verifier') then
    create role knowledge_integrity_verifier nologin;
  end if;
end;
$role$;

create schema knowledge_verifier;
revoke all on schema knowledge_verifier from public;
grant usage on schema knowledge_verifier to knowledge_integrity_verifier;

-- ================================================================== policy: attestation mode (owner)

alter table private.knowledge_integrity_policy add column attestation_mode text;
alter table private.knowledge_integrity_policy add constraint knowledge_integrity_policy_attestation_chk
  check (attestation_mode is null or attestation_mode in ('in_database_signature', 'offline_signature_audit'));

create function private.knowledge_ed25519_available()
returns boolean
language sql
stable
set search_path = ''
as $$
  select pg_catalog.to_regprocedure('pgsodium.crypto_sign_verify_detached(bytea,bytea,bytea)') is not null;
$$;
revoke all on function private.knowledge_ed25519_available() from public, anon, authenticated, service_role;

-- null = pgsodium is not installed (no in-database verification possible); otherwise the libsodium result
create function private.knowledge_ed25519_verify(p_signature bytea, p_message bytea, p_public_key bytea)
returns boolean
language plpgsql
stable
set search_path = ''
as $$
begin
  if not private.knowledge_ed25519_available() then
    return null;
  end if;
  return pgsodium.crypto_sign_verify_detached(p_signature, p_message, p_public_key);
end;
$$;
revoke all on function private.knowledge_ed25519_verify(bytea, bytea, bytea) from public, anon, authenticated, service_role;

-- Owner only (no grant).
create function private.knowledge_set_attestation_mode(p_mode text)
returns void
language plpgsql
set search_path = ''
as $$
begin
  if p_mode = 'in_database_signature' and not private.knowledge_ed25519_available() then
    raise exception 'in_database_signature needs pgsodium.crypto_sign_verify_detached, which is not installed'
      using errcode = '55000';
  end if;
  update private.knowledge_integrity_policy
     set attestation_mode = p_mode, set_at = pg_catalog.now(), set_by_session_user = session_user
   where singleton;
end;
$$;
revoke all on function private.knowledge_set_attestation_mode(text) from public, anon, authenticated, service_role;

-- ================================================================== chunk provenance

create function private.knowledge_chunk_hash_problem(p_document_pk uuid)
returns text
language sql
stable
set search_path = ''
as $$
  select 'chunk ' || k.chunk_id || ' text does not hash to its recorded content_sha256 (a legacy or altered row:'
         ' re-ingest the document as a new version)'
    from public.knowledge_chunks k
   where k.document_pk = p_document_pk
     and k.content_sha256 is distinct from
         pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(k.content, 'UTF8')), 'hex')
   order by k.ordinal, k.chunk_id
   limit 1;
$$;
revoke all on function private.knowledge_chunk_hash_problem(uuid) from public, anon, authenticated, service_role;

-- ================================================================== caller identity

-- The role the verifier function runs for (SECURITY DEFINER hides it in current_user). Refuses the report
-- producer, the client roles, the DB owner's own identity, and a misconfigured group.
create function private.knowledge_verifier_caller()
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_role text := coalesce(nullif(pg_catalog.current_setting('role', true), 'none'), session_user);
begin
  if exists (select 1 from pg_catalog.unnest(array['service_role', 'authenticator', 'authenticated', 'anon']) r(name)
              where exists (select 1 from pg_catalog.pg_roles x where x.rolname = r.name)
                and pg_catalog.pg_has_role(r.name, 'knowledge_integrity_verifier', 'MEMBER')) then
    raise exception 'the verifier role is misconfigured: a service or client role is a member of'
      ' knowledge_integrity_verifier, so it is not independent of the report producer' using errcode = '42501';
  end if;
  if v_role in ('service_role', 'authenticator', 'authenticated', 'anon', 'postgres', 'supabase_admin')
     or not pg_catalog.pg_has_role(v_role, 'knowledge_integrity_verifier', 'USAGE') then
    raise exception 'only the independent verifier role (knowledge_integrity_verifier) may do this (caller %)', v_role
      using errcode = '42501';
  end if;
  return v_role;
end;
$$;
revoke all on function private.knowledge_verifier_caller() from public, anon, authenticated, service_role;

-- ================================================================== verification records: provenance of the check

alter table public.knowledge_integrity_verifications
  add column signature_checked_in_db boolean not null default true,   -- every E7 row was checked by pgsodium
  add column attestation_mode text,
  add column submitted_by_session_user text;
alter table public.knowledge_integrity_verifications alter column signature_checked_in_db drop default;

-- ================================================================== what the verifier may read

-- Only the version under review that the report is about: its report, chunk text, stored claims and the pin.
create function knowledge_verifier.verification_input(p_report_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_report public.knowledge_integrity_reports;
  v_doc record;
  v_pin record;
begin
  perform private.knowledge_verifier_caller();
  select r.* into v_report from public.knowledge_integrity_reports r where r.id = p_report_id;
  select d.source_id, d.document_id, d.document_version, d.status into v_doc
    from public.knowledge_documents d where d.id = v_report.document_pk;
  if v_report.id is null or v_doc.status::text not in ('review_required', 'expert_review') then
    raise exception 'no integrity report % of a version under review', p_report_id using errcode = 'P0002';
  end if;
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  return pg_catalog.jsonb_build_object(
    'report', pg_catalog.jsonb_build_object('id', v_report.id, 'document_pk', v_report.document_pk,
      'report_sha256', v_report.report_sha256, 'document_snapshot_sha256', v_report.document_snapshot_sha256,
      'source_snapshot_sha256', v_report.source_snapshot_sha256, 'chunk_count', v_report.chunk_count,
      'extractor_version', v_report.extractor_version, 'registry_digest', v_report.registry_digest),
    'document_ref', v_doc.source_id || '/' || v_doc.document_id || '@' || v_doc.document_version,
    'pin', pg_catalog.jsonb_build_object('extractor_version', v_pin.extractor_version,
      'extractor_code_digest', v_pin.extractor_code_digest, 'registry_digest', v_pin.registry_digest),
    'chunks', coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('chunk_id', k.chunk_id,
        'content', k.content, 'content_sha256', k.content_sha256) order by k.ordinal, k.chunk_id)
      from public.knowledge_chunks k where k.document_pk = v_report.document_pk), '[]'::jsonb),
    'claims', coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('claim_id', c.claim_id,
        'chunk_id', c.chunk_id, 'chunk_content_sha256', c.chunk_content_sha256, 'span_start', c.span_start,
        'span_end', c.span_end, 'kind', c.kind, 'status', c.status, 'parameter', c.parameter,
        'value_min', pg_catalog.trim_scale(c.value_min)::text, 'value_max', pg_catalog.trim_scale(c.value_max)::text,
        'unit', c.unit, 'dimension', c.dimension, 'date_iso', pg_catalog.to_char(c.date_iso, 'YYYY-MM-DD'),
        'stage', c.stage, 'scope_tags', pg_catalog.to_jsonb(c.scope_tags)) order by c.claim_id collate "C")
      from public.knowledge_claims c
     where c.document_pk = v_report.document_pk and c.extractor_version = v_report.extractor_version), '[]'::jsonb));
end;
$$;
revoke all on function knowledge_verifier.verification_input(uuid) from public, anon, authenticated, service_role;
grant execute on function knowledge_verifier.verification_input(uuid) to knowledge_integrity_verifier;

-- ================================================================== recording (replaces E7's service-role RPC)

drop function private.knowledge_record_integrity_verification(text, bytea);

create function knowledge_verifier.record_verification(p_statement text, p_signature bytea)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_caller text;
  v_body jsonb;
  v_key record;
  v_report public.knowledge_integrity_reports;
  v_pin record;
  v_sig boolean;
  v_stored_digest text;
  v_stored_count integer;
  v_id bigint;
begin
  v_caller := private.knowledge_verifier_caller();
  if p_statement is null or p_signature is null or length(p_signature) <> 64 or length(p_statement) > 2000000 then
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
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.attestation_mode is null then
    raise exception 'verification refused: the owner has not chosen an attestation mode' using errcode = '42501';
  end if;
  select k.key_id, k.public_key, k.status into v_key from public.knowledge_integrity_verifier_keys k
   where k.key_id = v_body ->> 'key_id' for share;
  if v_key.key_id is null or v_key.status <> 'active' then
    raise exception 'verification refused: % is not an active registered verifier key', v_body ->> 'key_id'
      using errcode = '42501';
  end if;
  v_sig := private.knowledge_ed25519_verify(p_signature, pg_catalog.convert_to(p_statement, 'UTF8'), v_key.public_key);
  if v_sig is null and v_pin.attestation_mode <> 'offline_signature_audit' then
    raise exception 'verification refused: in_database_signature is required but pgsodium is not installed'
      using errcode = '42501';
  elsif v_sig is false then
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
  if v_body ->> 'verdict' = 'reproduced' then
    -- a statement that says "reproduced" must be literally true of the stored claims and chunk text
    if v_body ->> 'claim_set_digest' is distinct from v_stored_digest
       or (v_body ->> 'claim_count')::integer <> v_stored_count
       or (v_body ->> 'chunks_read')::integer <> v_report.chunk_count then
      raise exception 'verification refused: the verifier''s claim set is not the stored one' using errcode = '23514';
    end if;
    if private.knowledge_chunk_hash_problem(v_report.document_pk) is not null then
      raise exception 'verification refused: %', private.knowledge_chunk_hash_problem(v_report.document_pk)
        using errcode = '23514';
    end if;
  end if;
  perform private.knowledge_m2_set_marker('knowledge_integrity_verifications');
  insert into public.knowledge_integrity_verifications (report_id, report_sha256, document_pk, document_snapshot_sha256,
    source_snapshot_sha256, extractor_version, extractor_code_digest, registry_digest, claim_set_digest, claim_count,
    chunks_read, verdict, missing, extra, altered, key_id, statement, signature, submitted_by_role,
    signature_checked_in_db, attestation_mode, submitted_by_session_user)
  values (v_report.id, v_report.report_sha256, v_report.document_pk, v_report.document_snapshot_sha256,
    v_report.source_snapshot_sha256, v_body ->> 'extractor_version', v_body ->> 'extractor_code_digest',
    v_body ->> 'registry_digest', v_body ->> 'claim_set_digest', (v_body ->> 'claim_count')::integer,
    (v_body ->> 'chunks_read')::integer, v_body ->> 'verdict',
    array(select pg_catalog.jsonb_array_elements_text(coalesce(v_body -> 'missing', '[]'))),
    array(select pg_catalog.jsonb_array_elements_text(coalesce(v_body -> 'extra', '[]'))),
    array(select pg_catalog.jsonb_array_elements_text(coalesce(v_body -> 'altered', '[]'))),
    v_key.key_id, p_statement, p_signature, v_caller, v_sig is true, v_pin.attestation_mode, session_user)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function knowledge_verifier.record_verification(text, bytea) from public, anon, authenticated, service_role;
grant execute on function knowledge_verifier.record_verification(text, bytea) to knowledge_integrity_verifier;

-- ================================================================== the gate's verification check (replaced)

-- Why the report has no usable independent verification, or null. Share-locks the key it relies on, so
-- a revocation and an approval serialize.
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
revoke all on function private.knowledge_integrity_verification_problem(public.knowledge_integrity_reports)
  from public, anon, authenticated, service_role;
