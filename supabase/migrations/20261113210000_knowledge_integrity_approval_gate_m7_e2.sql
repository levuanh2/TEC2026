-- RAG V1.5 M7 E2 (docs/rag/RAG_V15_M7_E2_INTEGRITY_APPROVAL_GATE.md): an expert review can no longer
-- recommend, and an approver can no longer approve, a document version without the integrity report of
-- its exact snapshot and an explicit, evidence-backed disposition of every finding that needs expert
-- review. LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN.
-- Depends on M2 (20261110120000), M3 (20261111090000), M4 (20261112090000), H-a..H-c, M6.
--
-- E2 (root cause): public.knowledge_submit_expert_review and public.knowledge_decide_document checked the
-- reviewer's OWN `findings` list, which the reviewer writes. Nothing tied the review to the integrity
-- analysis of the stored content, so a reviewer who left the detected problem out could recommend
-- approval, and the approver could approve.
--
-- Evidence model (all append-only, RLS on with no policy, SELECT for service_role only; read by reviewers
-- through public.knowledge_review_integrity_report):
--   private.knowledge_integrity_policy      the pinned extractor / review / registry version + digest
--                                           (owner only). Unpinned = every recommendation is refused.
--   public.knowledge_integrity_reports      one materialized report: document + source snapshot hashes
--                                           (the document snapshot covers file sha256, normalized sha256
--                                           and the chunk manifest), versions, registry digest, claim
--                                           counts, limitations, report hash. Written ONLY by
--                                           private.knowledge_record_integrity_report (service_role).
--   public.knowledge_integrity_findings     its findings; `needs_expert_review` is set BY THE DATABASE from
--                                           the finding type (a conflict cannot be filed as information);
--                                           evidence spans copied from the stored M4 claims.
--   public.knowledge_integrity_dispositions the reviewer's acknowledgement of the report and disposition of
--                                           each finding, bound to review, report hash and finding id.
-- Completeness, checked by the database when a report is recorded: every stored M4 claim of the document
-- (same extractor version) that is an extracted qualitative assertion must be named by a finding that
-- needs expert review or declared supported by a named reference; every claim the extractor could not
-- read (ambiguous / unsupported) must be named by an unresolved_claim finding. So a report cannot omit a
-- claim the M4 pipeline stored, and it cannot invent one (every claim id must exist, span-verified, in
-- public.knowledge_claims).
--
-- What it does NOT claim: the database cannot re-run the extractor. A report is as complete as the claims
-- recorded for the snapshot and as right as the pinned registry. The operator pipeline (service_role) is
-- trusted to run the pinned extractor; it cannot fabricate a claim span, downgrade a conflict, or skip a
-- stored claim. An empty registry or zero extracted claims is never "verified": the report carries the
-- limitation and the reviewer must acknowledge it.

-- ================================================================== policy (owner pin)

create table private.knowledge_integrity_policy (
  singleton boolean primary key default true,
  extractor_version text,
  review_version text,
  registry_version text,
  registry_digest text,
  set_at timestamptz,
  set_by_session_user text,
  constraint knowledge_integrity_policy_singleton_chk check (singleton),
  constraint knowledge_integrity_policy_pin_chk check (
    (extractor_version is null and review_version is null and registry_version is null and registry_digest is null)
    or (extractor_version is not null and review_version is not null and registry_version is not null
        and registry_digest ~ '^[0-9a-f]{64}$'))
);
revoke all on private.knowledge_integrity_policy from public, anon, authenticated, service_role;
insert into private.knowledge_integrity_policy (singleton) values (true);

create function private.knowledge_set_integrity_policy(
  p_extractor_version text, p_review_version text, p_registry_version text, p_registry_digest text)
returns void
language plpgsql
set search_path = ''
as $$
begin
  update private.knowledge_integrity_policy
     set extractor_version = p_extractor_version, review_version = p_review_version,
         registry_version = p_registry_version, registry_digest = p_registry_digest,
         set_at = pg_catalog.now(), set_by_session_user = session_user
   where singleton;
end;
$$;
revoke all on function private.knowledge_set_integrity_policy(text, text, text, text)
  from public, anon, authenticated, service_role;

-- finding type -> needs expert review (the Python review's _NEEDS_REVIEW); closed set
create function private.knowledge_integrity_finding_blocking(p_type text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select case
    when p_type in ('reference_conflict', 'claim_conflict', 'unsupported_assertion', 'expired_guidance',
                    'not_yet_effective', 'superseded_guidance', 'numeric_reference_mismatch') then true
    when p_type in ('unresolved_claim', 'unreferenced_claim', 'numeric_unresolved') then false
  end;
$$;
revoke all on function private.knowledge_integrity_finding_blocking(text) from public, anon, authenticated, service_role;

-- ================================================================== evidence tables

create table public.knowledge_integrity_reports (
  id uuid primary key default gen_random_uuid(),
  document_pk uuid not null references public.knowledge_documents (id),
  source_id text not null,
  document_id text not null,
  document_version text not null,
  document_snapshot_sha256 text not null,
  source_snapshot_sha256 text not null,
  file_sha256 text not null,
  normalized_sha256 text not null,
  chunk_manifest_sha256 text not null,
  chunk_count integer not null,
  extractor_version text not null,
  review_version text not null,
  registry_version text not null,
  registry_digest text not null,
  claim_count integer not null,
  finding_count integer not null,
  blocking_count integer not null,
  supported_claims jsonb not null,
  limitations jsonb not null,
  report_sha256 text not null unique,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  actor_role text not null,
  session_user_name text not null
);
create index knowledge_integrity_reports_document_idx on public.knowledge_integrity_reports (document_pk, recorded_at);

create table public.knowledge_integrity_findings (
  id bigint generated always as identity primary key,
  report_id uuid not null references public.knowledge_integrity_reports (id),
  finding_key text not null,
  finding_type text not null,
  needs_expert_review boolean not null,
  claim_ids text[] not null,
  reference_ids text[] not null,
  detail text not null,
  evidence jsonb not null,
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_integrity_findings_key unique (report_id, finding_key),
  constraint knowledge_integrity_findings_type_chk check (private.knowledge_integrity_finding_blocking(finding_type) is not null)
);

create table public.knowledge_integrity_dispositions (
  id bigint generated always as identity primary key,
  review_id uuid not null references public.knowledge_expert_reviews (id),
  report_id uuid not null references public.knowledge_integrity_reports (id),
  report_sha256 text not null,
  finding_id bigint references public.knowledge_integrity_findings (id),
  disposition text not null,
  justification text not null,
  evidence jsonb not null,
  actor_personnel_id uuid not null references public.knowledge_personnel (id),
  actor_user_id uuid not null,
  actor_session_id uuid not null,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_integrity_dispositions_kind_chk check (
    (finding_id is null and disposition = 'report_reviewed')
    or (finding_id is not null and disposition in ('confirmed_problem', 'false_positive', 'contextual_difference',
                                                   'needs_more_evidence', 'accepted_with_justification'))),
  constraint knowledge_integrity_dispositions_justification_chk check (length(btrim(justification)) between 20 and 4000)
);
create unique index knowledge_integrity_dispositions_once_uidx
  on public.knowledge_integrity_dispositions (review_id, report_id, coalesce(finding_id, 0));

alter table public.knowledge_integrity_reports enable row level security;
alter table public.knowledge_integrity_findings enable row level security;
alter table public.knowledge_integrity_dispositions enable row level security;
revoke all on public.knowledge_integrity_reports, public.knowledge_integrity_findings,
  public.knowledge_integrity_dispositions from public, anon, authenticated, service_role;
grant select on public.knowledge_integrity_reports, public.knowledge_integrity_findings,
  public.knowledge_integrity_dispositions to service_role;
create trigger knowledge_integrity_reports_guard before insert or update or delete on public.knowledge_integrity_reports
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_integrity_reports_no_truncate before truncate on public.knowledge_integrity_reports
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_integrity_findings_guard before insert or update or delete on public.knowledge_integrity_findings
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_integrity_findings_no_truncate before truncate on public.knowledge_integrity_findings
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_integrity_dispositions_guard before insert or update or delete on public.knowledge_integrity_dispositions
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_integrity_dispositions_no_truncate before truncate on public.knowledge_integrity_dispositions
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== record a report (operator pipeline)

create function private.knowledge_record_integrity_report(
  p_document_pk uuid, p_extractor_version text, p_review_version text, p_registry_version text,
  p_registry_digest text, p_findings jsonb, p_supported jsonb, p_limitations jsonb)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_pin record;
  v_doc record;
  v_snap jsonb;
  v_src_snap jsonb;
  v_item jsonb;
  v_missing text;
  v_id uuid := gen_random_uuid();
  v_claims integer;
  v_findings jsonb := '[]'::jsonb;
  v_sha text;
begin
  select * into v_pin from private.knowledge_integrity_policy where singleton;
  if v_pin.registry_digest is null then
    raise exception 'the integrity policy is not pinned (private.knowledge_set_integrity_policy): no report is accepted'
      using errcode = '42501';
  end if;
  if (p_extractor_version, p_review_version, p_registry_version, p_registry_digest)
     is distinct from (v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest) then
    raise exception 'the report was not produced with the pinned extractor, review and registry (% / % / % %)',
      v_pin.extractor_version, v_pin.review_version, v_pin.registry_version, v_pin.registry_digest using errcode = '23514';
  end if;
  if pg_catalog.jsonb_typeof(coalesce(p_findings, 'null')) <> 'array' or pg_catalog.jsonb_array_length(p_findings) > 2000
     or pg_catalog.jsonb_typeof(coalesce(p_supported, 'null')) <> 'array'
     or pg_catalog.jsonb_typeof(coalesce(p_limitations, 'null')) <> 'array' or pg_catalog.jsonb_array_length(p_limitations) = 0
     or exists (select 1 from pg_catalog.jsonb_array_elements(p_limitations) l
                 where pg_catalog.jsonb_typeof(l) <> 'string' or length(btrim(l #>> '{}')) < 10) then
    raise exception 'a report has findings and supported arrays and at least one stated limitation' using errcode = '22023';
  end if;
  -- the document version must still be under review; the share lock serializes with its approval
  select d.id, d.source_id, d.document_id, d.document_version, d.status, d.file_sha256, d.normalized_sha256 into v_doc
    from public.knowledge_documents d where d.id = p_document_pk for share;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  if v_doc.status not in ('review_required', 'expert_review') then
    raise exception 'knowledge document %: status is %; integrity reports are recorded before approval', p_document_pk,
      v_doc.status using errcode = '23514';
  end if;
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  v_src_snap := private.knowledge_source_snapshot(v_doc.source_id);
  select count(*) into v_claims from public.knowledge_claims c
   where c.document_pk = p_document_pk and c.extractor_version = p_extractor_version;
  -- every stored claim the report names must be a claim of this version, recorded on the current chunk text
  for v_item in select e from pg_catalog.jsonb_array_elements(p_findings) e loop
    if pg_catalog.jsonb_typeof(v_item) <> 'object'
       or private.knowledge_integrity_finding_blocking(v_item ->> 'finding_type') is null
       or pg_catalog.jsonb_typeof(v_item -> 'claim_ids') is distinct from 'array'
       or pg_catalog.jsonb_typeof(coalesce(v_item -> 'reference_ids', '[]')) <> 'array'
       or length(coalesce(v_item ->> 'detail', '')) not between 1 and 2000 then
      raise exception 'a finding has a known finding_type, claim_ids, reference_ids and a detail' using errcode = '22023';
    end if;
    select x into v_missing from pg_catalog.jsonb_array_elements_text(v_item -> 'claim_ids') x
     where not exists (select 1 from public.knowledge_claims c join public.knowledge_chunks k on k.id = c.chunk_pk
                        where c.document_pk = p_document_pk and c.extractor_version = p_extractor_version
                          and c.claim_id = x and c.chunk_content_sha256 = k.content_sha256)
     limit 1;
    if v_missing is not null then
      raise exception 'finding names claim %, which is not a stored claim of this version and chunk text', v_missing
        using errcode = '23503';
    end if;
    v_findings := v_findings || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'finding_type', v_item ->> 'finding_type',
      'needs_expert_review', private.knowledge_integrity_finding_blocking(v_item ->> 'finding_type'),
      'claim_ids', (select coalesce(pg_catalog.jsonb_agg(x order by x), '[]') from
                      (select distinct pg_catalog.jsonb_array_elements_text(v_item -> 'claim_ids') x) q),
      'reference_ids', (select coalesce(pg_catalog.jsonb_agg(x order by x), '[]') from
                          (select distinct pg_catalog.jsonb_array_elements_text(coalesce(v_item -> 'reference_ids', '[]')) x) q),
      'detail', v_item ->> 'detail'));
  end loop;
  if exists (select 1 from pg_catalog.jsonb_array_elements(p_supported) s
              where pg_catalog.jsonb_typeof(s) <> 'object' or length(coalesce(s ->> 'reference_id', '')) = 0
                 or not exists (select 1 from public.knowledge_claims c where c.document_pk = p_document_pk
                                  and c.extractor_version = p_extractor_version and c.claim_id = s ->> 'claim_id'
                                  and c.kind = 'assertion')) then
    raise exception 'a supported claim names a stored assertion claim of this version and the reference that supports it'
      using errcode = '22023';
  end if;
  -- completeness: no stored assertion and no unreadable claim may be left out
  select c.claim_id into v_missing from public.knowledge_claims c
   where c.document_pk = p_document_pk and c.extractor_version = p_extractor_version
     and ((c.kind = 'assertion' and c.status = 'extracted'
           and not exists (select 1 from pg_catalog.jsonb_array_elements(v_findings) f
                            where (f ->> 'needs_expert_review')::boolean and f -> 'claim_ids' ? c.claim_id)
           and not exists (select 1 from pg_catalog.jsonb_array_elements(p_supported) s where s ->> 'claim_id' = c.claim_id))
       or (c.status <> 'extracted'
           and not exists (select 1 from pg_catalog.jsonb_array_elements(v_findings) f
                            where f ->> 'finding_type' = 'unresolved_claim' and f -> 'claim_ids' ? c.claim_id)))
   order by c.claim_id limit 1;
  if v_missing is not null then
    raise exception 'the report omits stored claim % (an assertion needs a finding or a supporting reference; an'
      ' unreadable claim needs an unresolved_claim finding)', v_missing using errcode = '23514';
  end if;
  v_sha := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.jsonb_build_object(
    'document_pk', p_document_pk, 'document_snapshot_sha256', private.knowledge_snapshot_sha256(v_snap),
    'source_snapshot_sha256', private.knowledge_snapshot_sha256(v_src_snap), 'extractor_version', p_extractor_version,
    'review_version', p_review_version, 'registry_version', p_registry_version, 'registry_digest', p_registry_digest,
    'claim_count', v_claims, 'findings', v_findings, 'supported', p_supported, 'limitations', p_limitations,
    'report_id', v_id)::text, 'UTF8')), 'hex');
  perform private.knowledge_m2_set_marker('knowledge_integrity_reports');
  insert into public.knowledge_integrity_reports (id, document_pk, source_id, document_id, document_version,
    document_snapshot_sha256, source_snapshot_sha256, file_sha256, normalized_sha256, chunk_manifest_sha256, chunk_count,
    extractor_version, review_version, registry_version, registry_digest, claim_count, finding_count, blocking_count,
    supported_claims, limitations, report_sha256, actor_role, session_user_name)
  values (v_id, p_document_pk, v_doc.source_id, v_doc.document_id, v_doc.document_version,
    private.knowledge_snapshot_sha256(v_snap), private.knowledge_snapshot_sha256(v_src_snap), v_doc.file_sha256,
    v_doc.normalized_sha256, v_snap -> 'chunks' ->> 'manifest_sha256', (v_snap -> 'chunks' ->> 'count')::integer,
    p_extractor_version, p_review_version, p_registry_version, p_registry_digest, v_claims,
    pg_catalog.jsonb_array_length(v_findings),
    (select count(*) from pg_catalog.jsonb_array_elements(v_findings) f where (f ->> 'needs_expert_review')::boolean),
    p_supported, p_limitations, v_sha, coalesce(nullif(current_setting('role', true), 'none'), session_user), session_user);
  perform private.knowledge_m2_set_marker('knowledge_integrity_findings');
  insert into public.knowledge_integrity_findings (report_id, finding_key, finding_type, needs_expert_review, claim_ids,
    reference_ids, detail, evidence)
  select v_id,
         pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to((f ->> 'finding_type') || '|' || (f -> 'claim_ids')::text
           || '|' || (f -> 'reference_ids')::text || '|' || (f ->> 'detail'), 'UTF8')), 'hex'),
         f ->> 'finding_type', (f ->> 'needs_expert_review')::boolean,
         array(select pg_catalog.jsonb_array_elements_text(f -> 'claim_ids')),
         array(select pg_catalog.jsonb_array_elements_text(f -> 'reference_ids')), f ->> 'detail',
         (select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('claim_id', c.claim_id, 'chunk_id', c.chunk_id,
                   'span', pg_catalog.jsonb_build_array(c.span_start, c.span_end), 'raw_text', c.raw_text,
                   'parameter', c.parameter, 'chunk_content_sha256', c.chunk_content_sha256) order by c.claim_id), '[]')
            from public.knowledge_claims c
           where c.document_pk = p_document_pk and c.extractor_version = p_extractor_version
             and f -> 'claim_ids' ? c.claim_id)
    from (select distinct e as f from pg_catalog.jsonb_array_elements(v_findings) e) q;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function private.knowledge_record_integrity_report(uuid, text, text, text, text, jsonb, jsonb, jsonb)
  from public, anon, authenticated, service_role;
grant execute on function private.knowledge_record_integrity_report(uuid, text, text, text, text, jsonb, jsonb, jsonb)
  to service_role;

-- ================================================================== the applicable report

-- The latest report of the version; null when there is none. Validity is the gate's business.
create function private.knowledge_integrity_current_report(p_document_pk uuid)
returns public.knowledge_integrity_reports
language sql
stable
set search_path = ''
as $$
  select r.* from public.knowledge_integrity_reports r where r.document_pk = p_document_pk
   order by r.recorded_at desc, r.id desc limit 1;
$$;
revoke all on function private.knowledge_integrity_current_report(uuid) from public, anon, authenticated, service_role;

-- Why the latest report cannot be relied on, or null when it can.
create function private.knowledge_integrity_report_problem(p_report public.knowledge_integrity_reports)
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
revoke all on function private.knowledge_integrity_report_problem(public.knowledge_integrity_reports)
  from public, anon, authenticated, service_role;

-- ================================================================== reviewer: acknowledge and dispose

create function public.knowledge_dispose_integrity_finding(
  p_review_id uuid, p_report_sha256 text, p_finding_id bigint, p_disposition text, p_justification text,
  p_evidence jsonb default '[]'::jsonb)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_rev record;
  v_report public.knowledge_integrity_reports;
  v_finding record;
  v_problem text;
  v_id bigint;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  select r.* into v_rev from public.knowledge_expert_reviews r where r.id = p_review_id;
  if not found or v_rev.reviewer_user_id <> v_actor.user_id then
    raise exception 'review not available: only the reviewer who started it records its dispositions' using errcode = '42501';
  end if;
  if v_rev.decision is not null then
    raise exception 'review %: its decision is already recorded (evidence is immutable)', p_review_id using errcode = '23514';
  end if;
  perform 1 from public.knowledge_personnel p join public.knowledge_personnel_roles r on r.personnel_id = p.id
   where p.id = v_rev.reviewer_personnel_id and r.id = v_rev.reviewer_role_id and p.status = 'active' and r.status = 'active'
     and r.valid_from <= pg_catalog.now() and (r.valid_until is null or r.valid_until > pg_catalog.now());
  if not found then
    raise exception 'separation of duties: your expert_reviewer role for this scope is no longer active' using errcode = '42501';
  end if;
  v_report := private.knowledge_integrity_current_report(v_rev.document_pk);
  v_problem := private.knowledge_integrity_report_problem(v_report);
  if v_problem is not null then
    raise exception 'review %: %', p_review_id, v_problem using errcode = '23514';
  end if;
  if p_report_sha256 is distinct from v_report.report_sha256 then
    raise exception 'review %: the integrity report you read is not the current one; read it again', p_review_id
      using errcode = '40001';
  end if;
  if p_finding_id is null then
    if p_disposition is distinct from 'report_reviewed' then
      raise exception 'the report itself is acknowledged with report_reviewed' using errcode = '22023';
    end if;
  else
    select f.* into v_finding from public.knowledge_integrity_findings f where f.id = p_finding_id and f.report_id = v_report.id;
    if not found then
      raise exception 'finding % is not a finding of the current report', p_finding_id using errcode = '23503';
    end if;
    if p_disposition in ('false_positive', 'contextual_difference') and not (
        pg_catalog.jsonb_typeof(p_evidence) = 'array' and pg_catalog.jsonb_array_length(p_evidence) > 0
        and not exists (select 1 from pg_catalog.jsonb_array_elements(p_evidence) e
                         where pg_catalog.jsonb_typeof(e) <> 'object' or length(btrim(coalesce(e ->> 'reference', ''))) < 5
                            or length(btrim(coalesce(e ->> 'locator', ''))) < 1)) then
      raise exception 'a % disposition names its evidence: [{reference, locator}] for the primary text it relies on',
        p_disposition using errcode = '22023';
    end if;
    if p_disposition = 'contextual_difference' and not (p_evidence @? '$[*] ? (exists(@.conditions))') then
      raise exception 'a contextual_difference names the conditions that make the statements compatible' using errcode = '22023';
    end if;
    if p_disposition = 'accepted_with_justification' and v_finding.needs_expert_review then
      raise exception 'a finding that needs expert review is resolved only as false_positive or contextual_difference'
        ' with evidence, or confirmed (reject / return)' using errcode = '22023';
    end if;
  end if;
  if p_justification is null or length(btrim(p_justification)) < 20 then
    raise exception 'a disposition needs a justification (at least 20 characters)' using errcode = '22023';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_integrity_dispositions');
  insert into public.knowledge_integrity_dispositions (review_id, report_id, report_sha256, finding_id, disposition,
    justification, evidence, actor_personnel_id, actor_user_id, actor_session_id)
  values (p_review_id, v_report.id, v_report.report_sha256, p_finding_id, p_disposition, pg_catalog.btrim(p_justification),
          coalesce(p_evidence, '[]'::jsonb), v_rev.reviewer_personnel_id, v_actor.user_id, v_actor.session_id)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
revoke all on function public.knowledge_dispose_integrity_finding(uuid, text, bigint, text, text, jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.knowledge_dispose_integrity_finding(uuid, text, bigint, text, text, jsonb) to authenticated;

-- Reviewers, approvers and uploaders of the version's scope read the current report (as JSON).
create function public.knowledge_review_integrity_report(p_document_pk uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_src record;
  v_report public.knowledge_integrity_reports;
begin
  select a.user_id into v_actor from private.knowledge_verified_actor() a;
  select s.visibility, s.organization_id into v_src from public.knowledge_documents d
    join public.knowledge_sources s on s.source_id = d.source_id where d.id = p_document_pk;
  if not found or not exists (
      select 1 from unnest(array['uploader', 'expert_reviewer', 'approver']) r(role)
       where (private.knowledge_actor_role(v_actor.user_id, r.role, v_src.visibility, v_src.organization_id)).role_id is not null) then
    raise exception 'not available for your knowledge role' using errcode = '42501';
  end if;
  v_report := private.knowledge_integrity_current_report(p_document_pk);
  if v_report.id is null then
    return pg_catalog.jsonb_build_object('report', null, 'problem', 'no integrity report has been recorded for this version');
  end if;
  return pg_catalog.jsonb_build_object(
    'report', pg_catalog.to_jsonb(v_report) - 'actor_role' - 'session_user_name' - 'recorded_xact',
    'problem', private.knowledge_integrity_report_problem(v_report),
    'findings', (select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(f) - 'recorded_xact' order by f.id), '[]')
                   from public.knowledge_integrity_findings f where f.report_id = v_report.id));
end;
$$;
revoke all on function public.knowledge_review_integrity_report(uuid) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_review_integrity_report(uuid) to authenticated;

-- ================================================================== the gate

-- Raises 23514 unless: the current report is valid for the version as it is now, the review was made on
-- that same snapshot, its reviewer acknowledged that exact report, no finding of it is confirmed or left
-- for more evidence, and every finding that needs expert review is resolved by that reviewer as
-- false_positive or contextual_difference with evidence. Share-locks the report rows it relies on.
create function private.knowledge_integrity_gate(p_document_pk uuid, p_review_id uuid)
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
revoke all on function private.knowledge_integrity_gate(uuid, uuid) from public, anon, authenticated, service_role;

-- ================================================================== the RPCs (replaced)

-- M3's public.knowledge_submit_expert_review, plus the gate on a recommendation to approve.
create or replace function public.knowledge_submit_expert_review(
  p_review_id uuid, p_decision text, p_snapshot_sha256 text, p_checklist jsonb, p_sources_checked jsonb,
  p_findings jsonb, p_rationale text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_rev record;
  v_doc record;
  v_role record;
  v_event bigint;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  select r.* into v_rev from public.knowledge_expert_reviews r where r.id = p_review_id;
  if not found or v_rev.reviewer_user_id <> v_actor.user_id then
    raise exception 'review not available: only the reviewer who started it records its decision' using errcode = '42501';
  end if;
  select d.status, s.visibility, s.organization_id into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = v_rev.document_pk for update of d;
  -- the reviewer must still be active and qualified for this scope
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'expert_reviewer', v_doc.visibility,
                                                         v_doc.organization_id);
  if v_role.role_id is null or v_role.role_id <> v_rev.reviewer_role_id then
    raise exception 'separation of duties: your expert_reviewer role for this scope is no longer active'
      using errcode = '42501';
  end if;
  if v_rev.decision is not null then
    raise exception 'review %: its decision is already recorded (evidence is immutable)', p_review_id
      using errcode = '23514';
  end if;
  if v_doc.status <> 'expert_review' or exists (
      select 1 from public.knowledge_expert_reviews r2
       where r2.document_pk = v_rev.document_pk and r2.seq > v_rev.seq) then
    raise exception 'review %: the version is no longer under this review', p_review_id using errcode = '23514';
  end if;
  perform private.knowledge_check_review_evidence(p_decision, p_checklist, p_sources_checked, p_findings, p_rationale);
  -- M3: a recommendation to approve a version that supersedes a version of ANOTHER source is complete only
  -- with an approved replacing source and the recorded authority. Checked here, where the reviewer can
  -- still fix it, and again by the approval (defense in depth).
  if p_decision = 'recommend_approval' then
    perform private.knowledge_check_cross_source_supersession(v_rev.document_pk, p_sources_checked);
    -- M7 E2: the integrity report of this exact version, acknowledged, every needs-review finding resolved
    perform private.knowledge_integrity_gate(v_rev.document_pk, p_review_id);
  end if;
  if p_snapshot_sha256 is distinct from v_rev.snapshot_sha256
     or private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(v_rev.document_pk)) <> v_rev.snapshot_sha256 then
    raise exception 'review %: the reviewed content or metadata changed since the review started (evidence invalid)',
      p_review_id using errcode = '23514';
  end if;
  if p_decision = 'reject' then
    v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review', 'rejected', p_rationale, null);
  elsif p_decision = 'return' then
    v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review', 'review_required',
                                                           p_rationale, null);
  end if;
  perform private.knowledge_m2_set_marker('knowledge_expert_reviews.decision');
  update public.knowledge_expert_reviews
     set decision = p_decision, checklist = p_checklist, sources_checked = p_sources_checked, findings = p_findings,
         rationale = p_rationale, decided_at = pg_catalog.now(), decision_session_id = v_actor.session_id,
         decision_event_id = v_event
   where id = p_review_id;
  perform private.knowledge_m2_set_marker(null);
  return p_review_id;
end;
$$;

-- M3's public.knowledge_decide_document, plus the gate on an approval (re-checked inside the approval).
create or replace function public.knowledge_decide_document(
  p_review_id uuid, p_decision text, p_snapshot_sha256 text, p_rationale text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_rev record;
  v_doc record;
  v_role record;
  v_reviewer record;
  v_att record;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  if p_decision is null or p_decision not in ('approve', 'reject') then
    raise exception 'approval decision must be approve or reject' using errcode = '22023';
  end if;
  if p_rationale is null or btrim(p_rationale) = '' or length(p_rationale) > 2000 then
    raise exception 'an approval decision needs a rationale (1-2000 characters)' using errcode = '22023';
  end if;
  select r.* into v_rev from public.knowledge_expert_reviews r where r.id = p_review_id;
  select d.id, d.status, s.visibility, s.organization_id into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = v_rev.document_pk for update of d;
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'approver', v_doc.visibility,
                                                         v_doc.organization_id);
  if v_rev.id is null or v_role.role_id is null then
    raise exception 'review not available for your knowledge role (approver)' using errcode = '42501';
  end if;
  select a.id, a.uploader_personnel_id, a.uploader_user_id into v_att
    from public.knowledge_upload_attestations a where a.id = v_rev.upload_attestation_id;
  if v_role.personnel_id in (v_rev.reviewer_personnel_id, v_att.uploader_personnel_id)
     or v_actor.user_id in (v_rev.reviewer_user_id, v_att.uploader_user_id)
     or v_role.identity_reference in (private.knowledge_person_identity(v_rev.reviewer_personnel_id),
                                      private.knowledge_person_identity(v_att.uploader_personnel_id)) then
    raise exception 'separation of duties: the approver must be a different person from the uploader and the reviewer'
      using errcode = '42501';
  end if;
  if v_doc.status <> 'expert_review' or exists (
      select 1 from public.knowledge_expert_reviews r2
       where r2.document_pk = v_rev.document_pk and r2.seq > v_rev.seq) then
    raise exception 'review %: the version is not under this review (it is %)', p_review_id, v_doc.status
      using errcode = '23514';
  end if;
  if v_rev.decision is distinct from 'recommend_approval' then
    raise exception 'review %: the expert has not recommended approval', p_review_id using errcode = '23514';
  end if;
  if exists (select 1 from public.knowledge_approval_records a where a.review_id = p_review_id) then
    raise exception 'review %: already decided', p_review_id using errcode = '23514';
  end if;
  if p_decision = 'approve' then
    -- the reviewer is still active and still holds the role used (suspension or revocation in between refuses)
    select 1 as ok into v_reviewer
      from public.knowledge_personnel p join public.knowledge_personnel_roles r on r.personnel_id = p.id
     where p.id = v_rev.reviewer_personnel_id and r.id = v_rev.reviewer_role_id and p.status = 'active'
       and r.status = 'active' and r.valid_from <= pg_catalog.now()
       and (r.valid_until is null or r.valid_until > pg_catalog.now())
     for share of p, r;
    if v_reviewer.ok is null then
      raise exception 'review %: the expert reviewer is no longer active and qualified', p_review_id
        using errcode = '42501';
    end if;
    -- evidence is re-validated: complete, no open blocking finding
    perform private.knowledge_check_review_evidence(v_rev.decision, v_rev.checklist, v_rev.sources_checked,
                                                    v_rev.findings, v_rev.rationale);
    -- M3: replacing a version of ANOTHER source needs an approved source and the reviewer's recorded authority
    perform private.knowledge_check_cross_source_supersession(v_rev.document_pk, v_rev.sources_checked);
    -- M7 E2: the integrity report of this exact version, acknowledged, every needs-review finding resolved
    perform private.knowledge_integrity_gate(v_rev.document_pk, p_review_id);
  end if;
  v_snap := private.knowledge_document_snapshot(v_rev.document_pk);
  if p_snapshot_sha256 is distinct from v_rev.snapshot_sha256
     or private.knowledge_snapshot_sha256(v_snap) <> v_rev.snapshot_sha256 then
    if p_decision = 'approve' then
      raise exception 'review %: the version or its source changed since the review (evidence invalid; approval refused)',
        p_review_id using errcode = '23514';
    end if;
  end if;
  -- the record first (the row trigger requires it for an approval), then the audited transition
  perform private.knowledge_m2_set_marker('knowledge_approval_records');
  insert into public.knowledge_approval_records (id, entity_type, source_id, document_pk, review_id,
    upload_attestation_id, decision, approver_personnel_id, approver_role_id, approver_user_id, approver_session_id,
    snapshot, snapshot_sha256, rationale, status_event_id)
  values (v_id, 'document', v_rev.source_id, v_rev.document_pk, p_review_id, v_att.id, p_decision, v_role.personnel_id,
          v_role.role_id, v_actor.user_id, v_actor.session_id, v_snap, private.knowledge_snapshot_sha256(v_snap),
          p_rationale, 0);
  perform private.knowledge_m2_set_marker(null);
  if p_decision = 'approve' then
    -- M3: the approval of a version archives the approved version it supersedes, in this transaction
    perform private.knowledge_supersede_for(v_rev.document_pk, false);
  end if;
  v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review',
    (case when p_decision = 'approve' then 'approved' else 'rejected' end)::public.knowledge_status,
    p_rationale, case when p_decision = 'approve' then v_actor.user_id end);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;
