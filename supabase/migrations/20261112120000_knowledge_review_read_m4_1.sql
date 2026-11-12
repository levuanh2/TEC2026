-- RAG V1.5 M4.1 (docs/rag/RAG_V15_M4_1_REVIEWER_READ.md): read-only access for verified
-- reviewers to the M4 claims and contradiction candidates of one document version.
-- LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN.
-- Depends on M2 (20261110120000), M3 (20261111090000) and M4 (20261112090000).
--
-- What it adds
--   * public.knowledge_review_claims(p_document_pk uuid) returns jsonb. SECURITY DEFINER,
--     search_path '', static SQL, EXECUTE for `authenticated` only. The caller is the verified human
--     of M2 (private.knowledge_verified_actor: a live aal2 session, a verified MFA factor, ...) and
--     must hold an ACTIVE expert_reviewer or approver role for the scope of the requested version's
--     source. Uploaders, registry admins, tenants, service and owner logins get nothing.
--   * public.knowledge_review_read_events: one append-only row per call that reached the role check,
--     granted or denied. No document text, no claim text: identities, the requested version id, the
--     outcome and the counts returned.
--
-- NON-BLOCKING. The function reads. It changes no knowledge status, approves and rejects nothing,
-- quarantines nothing, and no review or approval depends on it. Every claim and candidate it
-- returns is labelled unverified analysis: a stored candidate is a review aid, never a finding.
--
-- Disclosure
--   * Claims of the requested version, and the candidates in which one of them takes part.
--   * The OTHER claim of a candidate is disclosed only if the caller could read that version
--     independently: the caller holds an active expert_reviewer or approver role for the scope of
--     its source, or it is public knowledge that is active (approved, source approved, in force),
--     i.e. text every signed-in user can already retrieve. Otherwise the candidate is withheld
--     entirely: no row, no placeholder, and it is not counted, in the response or in the audit row.
--   * A denial is one answer, {"access": "denied"}, whether the version does not exist, is in
--     another scope, or the caller holds no reviewer or approver role. It is returned, not raised,
--     so that the denial itself is audited; the audit row is the same in all three cases (the
--     requested id as given, no personnel, no counts), and only service_role reads the audit table.
--   * Denied calls are recorded up to private.knowledge_review_read_denied_cap() (20) rows per
--     caller in any rolling hour, so an account without a role cannot grow the append-only table
--     without bound (at most 20 small rows an hour, and it needs a verified MFA factor to write
--     even one). A denied call above the cap gets the same answer and is COUNTED, not dropped:
--     public.knowledge_review_read_denied_overflow keeps one row per caller and clock hour with the
--     number of such calls and the first and last time. So probing past the cap stays visible (who,
--     when, how many); what is not kept is the id each of those calls asked for. The cap is counted
--     under a per-caller advisory lock. Granted reads are always recorded: only registered
--     reviewers and approvers can make them. Neither table holds text or pins an account (no
--     foreign key on the caller).
--   * Roles are scoped per visibility and organization (M2), not per farm: a reviewer of an
--     organization reads the claims of every farm of that organization. M4.1 does not widen that.

-- ================================================================== audit

create table public.knowledge_review_read_events (
  id bigint generated always as identity primary key,
  -- auth.uid() of the verified caller. Deliberately no foreign key: a denied row is written for ANY
  -- signed-in aal2 user, and an append-only row with ON DELETE RESTRICT would make that account
  -- undeletable after one call. A granted row is tied to the registry by personnel_id and role_id.
  caller_user_id uuid not null,
  caller_session_id uuid not null,
  -- the role the access was granted under (null for a denial)
  personnel_id uuid references public.knowledge_personnel(id) on delete restrict,
  role_id uuid references public.knowledge_personnel_roles(id) on delete restrict,
  role text,
  -- the id AS REQUESTED. Deliberately no foreign key: a denied request may name a version that does
  -- not exist, and the row must not tell the two apart.
  requested_document_pk uuid not null,
  outcome text not null,
  claims_returned integer,
  candidates_returned integer,
  recorded_at timestamptz not null default clock_timestamp(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_review_read_events_outcome_chk check (outcome in ('granted', 'denied')),
  constraint knowledge_review_read_events_shape_chk check (
    (outcome = 'granted' and personnel_id is not null and role_id is not null
     and role in ('expert_reviewer', 'approver') and claims_returned >= 0 and candidates_returned >= 0)
    or (outcome = 'denied' and personnel_id is null and role_id is null and role is null
        and claims_returned is null and candidates_returned is null))
);
create index knowledge_review_read_events_document_idx
  on public.knowledge_review_read_events (requested_document_pk, recorded_at);
create index knowledge_review_read_events_caller_idx
  on public.knowledge_review_read_events (caller_user_id, recorded_at);
comment on table public.knowledge_review_read_events is
  'M4.1: who read the M4 claims and contradiction candidates of which document version, and how many rows. '
  'Append-only. Holds no document or claim text.';

alter table public.knowledge_review_read_events enable row level security;
revoke all on public.knowledge_review_read_events from public, anon, authenticated, service_role;
grant select on public.knowledge_review_read_events to service_role;

-- INSERT only inside public.knowledge_review_claims (the M2 write marker); never UPDATE, DELETE or
-- TRUNCATE, the owner included: the M2 evidence guard and truncate guard, reused.
create trigger knowledge_review_read_events_guard
  before insert or update or delete on public.knowledge_review_read_events
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_review_read_events_no_truncate
  before truncate on public.knowledge_review_read_events
  for each statement execute function private.knowledge_m2_no_truncate();

-- Denied calls above the cap: one row per caller and clock hour (UTC), a counter. Not append-only by
-- row, but it can only be created by the read function and can only grow: the guard below refuses
-- every other insert, every update that is not "more calls, later last_at", and every delete.
create table public.knowledge_review_read_denied_overflow (
  caller_user_id uuid not null,
  window_start timestamptz not null,
  suppressed_calls integer not null,
  first_at timestamptz not null default clock_timestamp(),
  last_at timestamptz not null default clock_timestamp(),
  constraint knowledge_review_read_denied_overflow_pkey primary key (caller_user_id, window_start),
  constraint knowledge_review_read_denied_overflow_chk check (
    suppressed_calls > 0 and last_at >= first_at
    and window_start = pg_catalog.date_trunc('hour', window_start, 'UTC'))
);
comment on table public.knowledge_review_read_denied_overflow is
  'M4.1: how many denied reviewer-read calls of one caller in one clock hour were above the recorded cap. '
  'Holds no document id and no text.';
alter table public.knowledge_review_read_denied_overflow enable row level security;
revoke all on public.knowledge_review_read_denied_overflow from public, anon, authenticated, service_role;
grant select on public.knowledge_review_read_denied_overflow to service_role;

create function private.knowledge_review_read_overflow_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if private.knowledge_m2_write_authorized('knowledge_review_read_denied_overflow') then
    if tg_op = 'INSERT' and new.suppressed_calls = 1 then
      return new;
    end if;
    if tg_op = 'UPDATE' and new.caller_user_id = old.caller_user_id and new.window_start = old.window_start
       and new.first_at = old.first_at and new.suppressed_calls = old.suppressed_calls + 1
       and new.last_at >= old.last_at then
      return new;
    end if;
  end if;
  raise exception '% is a grow-only counter written by the reviewer read function: % is refused', tg_table_name, tg_op
    using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_review_read_overflow_guard() from public, anon, authenticated, service_role;
create trigger knowledge_review_read_denied_overflow_guard
  before insert or update or delete on public.knowledge_review_read_denied_overflow
  for each row execute function private.knowledge_review_read_overflow_guard();
create trigger knowledge_review_read_denied_overflow_no_truncate
  before truncate on public.knowledge_review_read_denied_overflow
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== read

-- How many DENIED calls of one caller are recorded per rolling hour (see the header).
create function private.knowledge_review_read_denied_cap()
returns integer
language sql
immutable
set search_path = ''
as $$ select 20 $$;
revoke all on function private.knowledge_review_read_denied_cap() from public, anon, authenticated, service_role;

-- One claim as the reviewer sees it: what was read, from exactly which chunk span of which version.
create function private.knowledge_review_claim_json(p_claim_id bigint)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'assurance', 'unverified_analysis',
    'id', c.id, 'claim_id', c.claim_id, 'extractor_version', c.extractor_version,
    'document_pk', c.document_pk, 'source_id', c.source_id, 'document_id', c.document_id,
    'document_version', c.document_version, 'file_sha256', d.file_sha256,
    'chunk_id', c.chunk_id, 'chunk_content_sha256', c.chunk_content_sha256,
    'span_start', c.span_start, 'span_end', c.span_end, 'raw_text', c.raw_text,
    'kind', c.kind, 'status', c.status, 'parameter', c.parameter, 'value_min', c.value_min,
    'value_max', c.value_max, 'unit', c.unit, 'dimension', c.dimension, 'date_iso', c.date_iso,
    'stage', c.stage, 'scope_tags', c.scope_tags, 'note', c.note,
    'recorded_at', pg_catalog.to_char(c.recorded_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
  from public.knowledge_claims c join public.knowledge_documents d on d.id = c.document_pk
  where c.id = p_claim_id;
$$;
revoke all on function private.knowledge_review_claim_json(bigint) from public, anon, authenticated, service_role;

create function public.knowledge_review_claims(p_document_pk uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_doc record;
  v_role record;
  v_role_name text;
  v_state record;
  v_claims jsonb;
  v_candidates jsonb;
  v_claim_count integer;
  v_candidate_count integer;
  v_recent_denials integer;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  if p_document_pk is null then
    raise exception 'name a document version' using errcode = '22023';
  end if;
  select d.id, d.source_id, d.document_id, d.document_version, d.file_sha256, d.status,
         s.visibility, s.organization_id
    into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk;
  if v_doc.id is not null then
    v_role_name := 'expert_reviewer';
    select * into v_role from private.knowledge_actor_role(v_actor.user_id, v_role_name, v_doc.visibility,
                                                           v_doc.organization_id);
    if v_role.role_id is null then
      v_role_name := 'approver';
      select * into v_role from private.knowledge_actor_role(v_actor.user_id, v_role_name, v_doc.visibility,
                                                             v_doc.organization_id);
    end if;
  end if;
  if v_doc.id is null or v_role.role_id is null then
    -- one answer and one audit shape, whatever the reason; at most the cap of rows per caller and hour
    perform pg_catalog.pg_advisory_xact_lock(
      pg_catalog.hashtextextended('knowledge_review_read_denied:' || v_actor.user_id::text, 0));
    select count(*) into v_recent_denials
      from public.knowledge_review_read_events e
     where e.caller_user_id = v_actor.user_id and e.outcome = 'denied'
       and e.recorded_at > pg_catalog.clock_timestamp() - interval '1 hour';
    if v_recent_denials < private.knowledge_review_read_denied_cap() then
      perform private.knowledge_m2_set_marker('knowledge_review_read_events');
      insert into public.knowledge_review_read_events (caller_user_id, caller_session_id, requested_document_pk, outcome)
      values (v_actor.user_id, v_actor.session_id, p_document_pk, 'denied');
      perform private.knowledge_m2_set_marker(null);
    else
      -- above the cap: counted, one row per caller and clock hour
      perform private.knowledge_m2_set_marker('knowledge_review_read_denied_overflow');
      insert into public.knowledge_review_read_denied_overflow as o (caller_user_id, window_start, suppressed_calls)
      values (v_actor.user_id, pg_catalog.date_trunc('hour', pg_catalog.clock_timestamp(), 'UTC'), 1)
      on conflict (caller_user_id, window_start)
      do update set suppressed_calls = o.suppressed_calls + 1, last_at = pg_catalog.clock_timestamp();
      perform private.knowledge_m2_set_marker(null);
    end if;
    return pg_catalog.jsonb_build_object('access', 'denied',
                                         'notice', 'not available for your knowledge role');
  end if;

  select e.state, e.reason into v_state from private.knowledge_document_evidence_state(p_document_pk) e;

  select coalesce(pg_catalog.jsonb_agg(private.knowledge_review_claim_json(c.id) order by c.id), '[]'::jsonb),
         count(*)
    into v_claims, v_claim_count
    from public.knowledge_claims c where c.document_pk = p_document_pk;

  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
           'assurance', 'unverified_analysis',
           'id', k.id, 'classification', k.classification, 'reasons', k.reasons, 'independence', k.independence,
           'comparison_key', k.comparison_key, 'tolerance', k.tolerance, 'tolerance_rationale', k.tolerance_rationale,
           'analysis_version', k.analysis_version, 'policy_date', k.policy_date,
           'evidence_state_a', k.evidence_state_a, 'evidence_state_b', k.evidence_state_b,
           'recorded_at', pg_catalog.to_char(k.recorded_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
           'claim_a', private.knowledge_review_claim_json(k.claim_a),
           'claim_b', private.knowledge_review_claim_json(k.claim_b)) order by k.id), '[]'::jsonb),
         count(*)
    into v_candidates, v_candidate_count
    from public.knowledge_contradiction_candidates k
    join public.knowledge_claims a on a.id = k.claim_a
    join public.knowledge_claims b on b.id = k.claim_b
    -- o: the claim on the other side (the pair itself when both claims are of the requested version)
    join public.knowledge_claims o on o.id = case when a.document_pk = p_document_pk then k.claim_b else k.claim_a end
   where (a.document_pk = p_document_pk or b.document_pk = p_document_pk)
     and (o.document_pk = p_document_pk
          -- the caller could read the other version independently: a reviewer or approver of its scope ...
          or (private.knowledge_actor_role(v_actor.user_id, 'expert_reviewer', o.visibility, o.organization_id)).role_id
             is not null
          or (private.knowledge_actor_role(v_actor.user_id, 'approver', o.visibility, o.organization_id)).role_id
             is not null
          -- ... or it is public knowledge every signed-in user can already retrieve
          or (o.visibility = 'public'
              and (private.knowledge_document_evidence_state(o.document_pk)).state = 'active'));

  perform private.knowledge_m2_set_marker('knowledge_review_read_events');
  insert into public.knowledge_review_read_events (caller_user_id, caller_session_id, personnel_id, role_id, role,
    requested_document_pk, outcome, claims_returned, candidates_returned)
  values (v_actor.user_id, v_actor.session_id, v_role.personnel_id, v_role.role_id, v_role_name, p_document_pk,
          'granted', v_claim_count, v_candidate_count);
  perform private.knowledge_m2_set_marker(null);

  return pg_catalog.jsonb_build_object(
    'access', 'granted',
    'assurance', 'unverified_analysis',
    'notice', 'UNVERIFIED ANALYSIS. Claims are what a deterministic extractor read from the text; a contradiction'
              ' candidate is a pair of such readings that may disagree. Neither is a finding, a verdict or'
              ' evidence that a document is wrong. Nothing here changes or blocks a review or an approval.',
    'role', v_role_name,
    'document', pg_catalog.jsonb_build_object(
      'document_pk', v_doc.id, 'source_id', v_doc.source_id, 'document_id', v_doc.document_id,
      'document_version', v_doc.document_version, 'file_sha256', v_doc.file_sha256, 'status', v_doc.status,
      'evidence_state', v_state.state, 'evidence_state_reason', v_state.reason),
    'claims', v_claims,
    'candidates', v_candidates);
end;
$$;
revoke all on function public.knowledge_review_claims(uuid) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_review_claims(uuid) to authenticated;
