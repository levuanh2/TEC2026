-- RAG V1.5 M2 (docs/rag/RAG_V15_SOURCE_CONTENT_INTEGRITY.md §3.5, §3.6, §6): verified expert approval.
-- LOCAL/CI ONLY until the owner approves a hosted migration. dev3-01 stays OPEN: M2 makes every
-- review and approval decision attributable to verified, distinct, registered humans and binds it to
-- the exact reviewed content. It does NOT prove that the content is factually correct.
--
-- Owner decision (2026-11-10): Option A. Supabase Auth identity (auth.uid() of a live aal2 session),
-- an owner-managed knowledge personnel registry, authenticated PostgreSQL RPCs, verified role
-- assignments, immutable review evidence, separation of duties.
--
-- What changes
--   * Registry: public.knowledge_registry_admins (trust root, written by the database owner only),
--     public.knowledge_personnel (one verified human per row, one Supabase Auth account per human),
--     public.knowledge_personnel_roles (uploader | expert_reviewer | approver, per scope, with the
--     qualification category, method, evidence and the verifying registry admin).
--   * Evidence: public.knowledge_upload_attestations, public.knowledge_expert_reviews,
--     public.knowledge_approval_records. Immutable: no UPDATE, DELETE or TRUNCATE, even by the owner.
--   * RPCs (public, EXECUTE for `authenticated` only, SECURITY DEFINER, static SQL, search_path ''):
--       registry  knowledge_register_personnel, knowledge_grant_personnel_role,
--                 knowledge_set_personnel_status, knowledge_set_personnel_role_status
--       uploader  knowledge_attest_document_upload, knowledge_attest_source_upload
--       reviewer  knowledge_start_expert_review, knowledge_submit_expert_review
--       approver  knowledge_decide_document, knowledge_approve_source
--     Every one starts with private.knowledge_verified_actor(): the caller's role is `authenticated`,
--     the JWT (as PostgREST verified it) names a user and `aal2`, its session_id is a live aal2
--     auth.sessions row of that user, the user has a verified MFA factor, is not banned, deleted or
--     anonymous and has no pending password change. The identity is auth.uid(); no RPC accepts the
--     caller's own identity as a parameter.
--   * The M1 operator functions (service_role) keep quarantine, archive and the triage transitions,
--     and now REFUSE the transitions M2 owns: document -> expert_review, document -> approved,
--     document expert_review -> review_required, source -> approved. An operator may still move a
--     document expert_review -> rejected (fail closed: the review is abandoned, nothing becomes
--     retrievable). The row triggers additionally require the matching evidence row written in the
--     same transaction, so a forged M1 marker alone no longer approves anything.
--   * Freeze: from expert_review on, the document's decision metadata (title, language, official_url,
--     artifact_ref, published_at, license_basis, license_reference) is immutable, like its chunks since
--     M1. Source metadata is not frozen (a source has its own flow), but it is part of the review
--     snapshot: any change after the review started makes the snapshot differ and approval is refused.
--
-- Separation of duties (checked in the RPCs, per decision):
--   uploader != expert reviewer != approver, compared by personnel id, auth user id AND the
--   registry's identity_reference (case-insensitive, including revoked records), so one human who was
--   registered twice is still one human. A registry admin cannot register, grant or change their own
--   record. Several accounts or several AI agents are not distinct humans: the registry admin must
--   verify that each personnel record is a different person (identity method + evidence).
--
-- Trust boundary (documented, not removable in SQL): the database owner (`postgres`) and the
-- PostgREST login (`authenticator`) can SET ROLE authenticated and set request.jwt.claims; the owner
-- can also insert auth.sessions rows, disable triggers or drop these objects. M2 removes every ROUTINE
-- owner/operator approval path (an owner session calling the M1 function is refused like
-- service_role), but it cannot make a superuser-equivalent login unable to rewrite its own database.
-- The registry is only as good as the registry admins' verification.
--
-- Unchanged: retrieval (approved-only on version AND source), the approval CHECKs (ST1, ST1.1,
-- license), one approved version per document, M1 quarantine rules (one-way, archived terminal,
-- republish = new version), the event log and its append-only rules, tenant scope.

-- ================================================================== registry

create table public.knowledge_registry_admins (
  auth_user_id uuid primary key references auth.users(id) on delete restrict,
  status text not null default 'active',
  note text not null,
  added_at timestamptz not null default now(),
  added_by_session_user text not null default session_user,
  revoked_at timestamptz,
  constraint knowledge_registry_admins_status_chk check (status in ('active', 'revoked')),
  constraint knowledge_registry_admins_revoked_chk check ((status = 'revoked') = (revoked_at is not null)),
  constraint knowledge_registry_admins_note_chk check (btrim(note) <> '' and length(note) <= 2000)
);
comment on table public.knowledge_registry_admins is
  'M2 trust root: who may verify knowledge personnel. Written only by the database owner (no grant to any '
  'client or service role). A registry admin never verifies their own personnel record.';

create table public.knowledge_personnel (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null references auth.users(id) on delete restrict,
  display_name text not null,
  -- An opaque handle the verifier used to tell humans apart (e.g. a staff or registry number). Not a
  -- secret and not a national ID number. Two records of one human must carry the same value.
  identity_reference text not null,
  identity_verification_method text not null,
  identity_evidence_ref text not null,
  organization_id uuid references public.organizations(id) on delete restrict,
  status text not null default 'active',
  verified_by uuid not null references auth.users(id) on delete restrict,
  verified_at timestamptz not null default now(),
  status_changed_at timestamptz,
  status_changed_by uuid references auth.users(id) on delete restrict,
  status_reason text,
  constraint knowledge_personnel_account_key unique (auth_user_id),
  constraint knowledge_personnel_text_chk check (
    btrim(display_name) <> '' and length(display_name) <= 200
    and btrim(identity_reference) <> '' and length(identity_reference) <= 200
    and btrim(identity_evidence_ref) <> '' and length(identity_evidence_ref) <= 1000),
  constraint knowledge_personnel_method_chk check (identity_verification_method in (
    'in_person', 'video_call', 'organization_attestation', 'official_id_checked_offline')),
  constraint knowledge_personnel_status_chk check (status in ('active', 'suspended', 'revoked')),
  constraint knowledge_personnel_not_self_verified_chk check (verified_by <> auth_user_id),
  constraint knowledge_personnel_status_change_chk check (
    (status_changed_at is null) = (status_changed_by is null)
    and (status_changed_at is null) = (status_reason is null))
);
-- The verifier's de-duplication handle, canonicalized: Unicode NFKC, case-folded, letters and digits
-- only. 'ID-9999', 'id 9999 ' and 'ＩＤ９９９９' are one human.
create function private.knowledge_identity_key(p_reference text)
returns text
language sql
immutable
strict
set search_path = ''
as $$
  select pg_catalog.lower(pg_catalog.regexp_replace(normalize(p_reference, NFKC), '[^[:alnum:]]', '', 'g'));
$$;
revoke all on function private.knowledge_identity_key(text) from public, anon, authenticated, service_role;
alter table public.knowledge_personnel
  add constraint knowledge_personnel_identity_key_chk check (private.knowledge_identity_key(identity_reference) <> '');
-- One live record per human.
create unique index knowledge_personnel_identity_key
  on public.knowledge_personnel (private.knowledge_identity_key(identity_reference)) where status <> 'revoked';

create table public.knowledge_personnel_roles (
  id uuid primary key default gen_random_uuid(),
  personnel_id uuid not null references public.knowledge_personnel(id) on delete restrict,
  role text not null,
  scope_visibility text not null,
  scope_organization_id uuid references public.organizations(id) on delete restrict,
  qualification_category text not null,
  qualification_method text not null,
  qualification_evidence_ref text not null,
  valid_from timestamptz not null default now(),
  valid_until timestamptz,
  status text not null default 'active',
  verified_by uuid not null references auth.users(id) on delete restrict,
  verified_at timestamptz not null default now(),
  status_changed_at timestamptz,
  status_changed_by uuid references auth.users(id) on delete restrict,
  status_reason text,
  constraint knowledge_personnel_roles_role_chk check (role in ('uploader', 'expert_reviewer', 'approver')),
  constraint knowledge_personnel_roles_scope_chk check (
    (scope_visibility = 'public' and scope_organization_id is null)
    or (scope_visibility = 'tenant' and scope_organization_id is not null)),
  constraint knowledge_personnel_roles_qualification_chk check (
    qualification_category ~ '^[a-z][a-z0-9_]{1,63}$'
    and qualification_method in ('credential_document_checked', 'employer_attestation', 'public_registry_lookup',
                                 'owner_assessment')
    and btrim(qualification_evidence_ref) <> '' and length(qualification_evidence_ref) <= 1000),
  constraint knowledge_personnel_roles_validity_chk check (valid_until is null or valid_until > valid_from),
  constraint knowledge_personnel_roles_status_chk check (status in ('active', 'suspended', 'revoked')),
  constraint knowledge_personnel_roles_status_change_chk check (
    (status_changed_at is null) = (status_changed_by is null)
    and (status_changed_at is null) = (status_reason is null))
);
create unique index knowledge_personnel_roles_live_key
  on public.knowledge_personnel_roles (personnel_id, role, scope_visibility,
                                       coalesce(scope_organization_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where status <> 'revoked';

-- ================================================================== evidence

create table public.knowledge_upload_attestations (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null,
  source_id text not null references public.knowledge_sources(source_id) on delete restrict,
  document_pk uuid references public.knowledge_documents(id) on delete restrict,
  file_sha256 text,
  normalized_sha256 text,
  uploader_personnel_id uuid not null references public.knowledge_personnel(id) on delete restrict,
  uploader_role_id uuid not null references public.knowledge_personnel_roles(id) on delete restrict,
  uploader_user_id uuid not null references auth.users(id) on delete restrict,
  auth_session_id uuid not null,
  statement text not null,
  attested_at timestamptz not null default now(),
  constraint knowledge_upload_attestations_entity_chk check (
    (entity_type = 'source' and document_pk is null and file_sha256 is null and normalized_sha256 is null)
    or (entity_type = 'document' and document_pk is not null
        and file_sha256 ~ '^[0-9a-f]{64}$' and normalized_sha256 ~ '^[0-9a-f]{64}$')),
  constraint knowledge_upload_attestations_statement_chk check (btrim(statement) <> '' and length(statement) <= 2000)
);
create unique index knowledge_upload_attestations_document_key
  on public.knowledge_upload_attestations (document_pk) where entity_type = 'document';
create unique index knowledge_upload_attestations_source_key
  on public.knowledge_upload_attestations (source_id) where entity_type = 'source';

create table public.knowledge_expert_reviews (
  id uuid primary key default gen_random_uuid(),
  -- order of reviews of a version (now() is constant inside a transaction, so started_at cannot order them)
  seq bigint generated always as identity,
  document_pk uuid not null references public.knowledge_documents(id) on delete restrict,
  source_id text not null,
  document_id text not null,
  document_version text not null,
  upload_attestation_id uuid not null references public.knowledge_upload_attestations(id) on delete restrict,
  reviewer_personnel_id uuid not null references public.knowledge_personnel(id) on delete restrict,
  reviewer_role_id uuid not null references public.knowledge_personnel_roles(id) on delete restrict,
  reviewer_user_id uuid not null references auth.users(id) on delete restrict,
  reviewer_session_id uuid not null,
  qualification_category text not null,
  -- Everything the decision depends on, captured when the review starts (private.knowledge_document_snapshot).
  snapshot jsonb not null,
  snapshot_sha256 text not null,
  started_at timestamptz not null default now(),
  start_event_id bigint not null,
  -- The reviewer's decision (one immutable row each: start, then the decision).
  decision text,
  checklist jsonb,
  sources_checked jsonb,
  findings jsonb,
  rationale text,
  decided_at timestamptz,
  decision_session_id uuid,
  decision_event_id bigint,
  -- set only when a registry admin cancelled the review (decision 'cancelled')
  cancelled_by uuid references auth.users(id) on delete restrict,
  -- the top-level transaction that wrote the row (the row triggers match it; xmin would be a subtransaction)
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_expert_reviews_hash_chk check (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  constraint knowledge_expert_reviews_decision_chk check (
    decision is null or decision in ('recommend_approval', 'reject', 'return', 'cancelled')),
  constraint knowledge_expert_reviews_cancelled_chk check ((decision = 'cancelled') = (cancelled_by is not null)),
  constraint knowledge_expert_reviews_decided_chk check (
    (decision is null and checklist is null and sources_checked is null and findings is null and rationale is null
     and decided_at is null and decision_session_id is null and decision_event_id is null)
    or (decision is not null and checklist is not null and sources_checked is not null and findings is not null
        and rationale is not null and decided_at is not null and decision_session_id is not null
        -- recommend_approval changes no status (the version stays expert_review for the approver)
        and ((decision = 'recommend_approval') = (decision_event_id is null))))
);
create index knowledge_expert_reviews_document_idx on public.knowledge_expert_reviews (document_pk, seq);

create table public.knowledge_approval_records (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null,
  source_id text not null references public.knowledge_sources(source_id) on delete restrict,
  document_pk uuid references public.knowledge_documents(id) on delete restrict,
  review_id uuid references public.knowledge_expert_reviews(id) on delete restrict,
  upload_attestation_id uuid references public.knowledge_upload_attestations(id) on delete restrict,
  decision text not null,
  -- 'verified': an M2 decision of a verified, distinct human (every evidence column set).
  -- 'demo_unverified': the owner-switched demo path (section "demo approvals"): NO review, NO verified
  -- personnel, approver stated by the operator. Never evidence of expert review.
  assurance text not null default 'verified',
  approver_personnel_id uuid references public.knowledge_personnel(id) on delete restrict,
  approver_role_id uuid references public.knowledge_personnel_roles(id) on delete restrict,
  approver_user_id uuid not null references auth.users(id) on delete restrict,
  approver_session_id uuid,
  snapshot jsonb not null,
  snapshot_sha256 text not null,
  rationale text not null,
  status_event_id bigint not null,
  decided_at timestamptz not null default now(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_approval_records_entity_chk check (
    (entity_type = 'source' and document_pk is null and review_id is null and decision = 'approve')
    or (entity_type = 'document' and document_pk is not null and (review_id is not null or assurance <> 'verified'))),
  constraint knowledge_approval_records_assurance_chk check (
    (assurance = 'verified' and upload_attestation_id is not null and approver_personnel_id is not null
     and approver_role_id is not null and approver_session_id is not null)
    or (assurance = 'demo_unverified' and decision = 'approve' and review_id is null and upload_attestation_id is null
        and approver_personnel_id is null and approver_role_id is null and approver_session_id is null
        and starts_with(rationale, 'DEMO - NOT EXPERT-REVIEWED: '))),
  constraint knowledge_approval_records_decision_chk check (decision in ('approve', 'reject')),
  constraint knowledge_approval_records_hash_chk check (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  constraint knowledge_approval_records_rationale_chk check (btrim(rationale) <> '' and length(rationale) <= 4000),
  constraint knowledge_approval_records_review_key unique (review_id)
);
create index knowledge_approval_records_document_idx on public.knowledge_approval_records (document_pk)
  where document_pk is not null;
create index knowledge_approval_records_source_idx on public.knowledge_approval_records (source_id, decided_at);

-- ================================================================== privileges (tables)

-- RLS on, no client policy: clients and tenants read nothing (no cross-tenant view of personnel or
-- evidence). service_role may read for operations and audit; nobody but the definer RPCs writes.
alter table public.knowledge_registry_admins enable row level security;
alter table public.knowledge_personnel enable row level security;
alter table public.knowledge_personnel_roles enable row level security;
alter table public.knowledge_upload_attestations enable row level security;
alter table public.knowledge_expert_reviews enable row level security;
alter table public.knowledge_approval_records enable row level security;
revoke all on public.knowledge_registry_admins, public.knowledge_personnel, public.knowledge_personnel_roles,
  public.knowledge_upload_attestations, public.knowledge_expert_reviews, public.knowledge_approval_records
  from public, anon, authenticated, service_role;
grant select on public.knowledge_registry_admins, public.knowledge_personnel, public.knowledge_personnel_roles,
  public.knowledge_upload_attestations, public.knowledge_expert_reviews, public.knowledge_approval_records
  to service_role;

-- ================================================================== write guards

-- True only inside an M2 RPC writing `p_table` (current_user is the owner of the evidence tables, i.e.
-- the definer function, and the transaction-local marker names the table). Same construction and the
-- same documented residual as M1's marker: an owner session could forge it.
create function private.knowledge_m2_write_authorized(p_table text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select current_user = (select r.rolname from pg_catalog.pg_class c
                         join pg_catalog.pg_roles r on r.oid = c.relowner
                         where c.oid = 'public.knowledge_approval_records'::pg_catalog.regclass)
     and coalesce(current_setting('knowledge.m2_write', true), '') = p_table;
$$;
revoke all on function private.knowledge_m2_write_authorized(text) from public, anon, authenticated, service_role;

create function private.knowledge_m2_set_marker(p_table text)
returns void
language sql
set search_path = ''
as $$
  select pg_catalog.set_config('knowledge.m2_write', coalesce(p_table, ''), true);
$$;
revoke all on function private.knowledge_m2_set_marker(text) from public, anon, authenticated, service_role;

-- TRUNCATE skips row triggers, so every M2 table refuses it with its own statement trigger (its own
-- function: M2 does not depend on M1's event-log function, so each rollback stays independent).
create function private.knowledge_m2_no_truncate()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception '% is append-only evidence/registry: TRUNCATE is refused', tg_table_name using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_m2_no_truncate() from public, anon, authenticated, service_role;

-- Evidence: INSERT only inside its RPC; never UPDATE, DELETE or TRUNCATE (even the owner).
create function private.knowledge_evidence_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if not private.knowledge_m2_write_authorized(tg_table_name) then
      raise exception '%: rows are written only by the M2 knowledge RPCs', tg_table_name using errcode = '42501';
    end if;
    return new;
  end if;
  -- The only changes ever allowed, each once, each inside its own RPC step: the audit event id of the
  -- transition the row backs (written right after the row in the same transaction, because the row
  -- trigger needs the row first), and the reviewer's decision.
  if tg_op = 'UPDATE' and (to_jsonb(old) ->> 'recorded_xact')::xid8 = pg_catalog.pg_current_xact_id() then
    if tg_table_name = 'knowledge_expert_reviews'
       and private.knowledge_m2_write_authorized('knowledge_expert_reviews.start_event')
       and (to_jsonb(old) ->> 'start_event_id')::bigint = 0 and (to_jsonb(new) ->> 'start_event_id')::bigint > 0
       and (to_jsonb(new) - 'start_event_id') = (to_jsonb(old) - 'start_event_id') then
      return new;
    end if;
    if tg_table_name = 'knowledge_approval_records'
       and private.knowledge_m2_write_authorized('knowledge_approval_records.status_event')
       and (to_jsonb(old) ->> 'status_event_id')::bigint = 0 and (to_jsonb(new) ->> 'status_event_id')::bigint > 0
       and (to_jsonb(new) - 'status_event_id') = (to_jsonb(old) - 'status_event_id') then
      return new;
    end if;
  end if;
  if tg_op = 'UPDATE' and tg_table_name = 'knowledge_expert_reviews'
     and private.knowledge_m2_write_authorized('knowledge_expert_reviews.decision')
     and (to_jsonb(old) ->> 'decision') is null and (to_jsonb(new) ->> 'decision') is not null
     and (to_jsonb(old) ->> 'start_event_id')::bigint > 0
     and (to_jsonb(new) - array['decision', 'checklist', 'sources_checked', 'findings', 'rationale', 'decided_at',
                                'decision_session_id', 'decision_event_id', 'cancelled_by'])
         = (to_jsonb(old) - array['decision', 'checklist', 'sources_checked', 'findings', 'rationale', 'decided_at',
                                  'decision_session_id', 'decision_event_id', 'cancelled_by']) then
    return new;
  end if;
  raise exception '% is immutable evidence: % is refused', tg_table_name, tg_op using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_evidence_guard() from public, anon, authenticated, service_role;

create trigger knowledge_upload_attestations_guard
  before insert or update or delete on public.knowledge_upload_attestations
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_upload_attestations_no_truncate
  before truncate on public.knowledge_upload_attestations
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_expert_reviews_guard
  before insert or update or delete on public.knowledge_expert_reviews
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_expert_reviews_no_truncate
  before truncate on public.knowledge_expert_reviews
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_approval_records_guard
  before insert or update or delete on public.knowledge_approval_records
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_approval_records_no_truncate
  before truncate on public.knowledge_approval_records
  for each statement execute function private.knowledge_m2_no_truncate();

-- Registry admins: the owner inserts active rows and may revoke (terminal); nothing else.
create function private.knowledge_registry_admin_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if new.status <> 'active' or new.revoked_at is not null then
      raise exception 'knowledge_registry_admins: a new registry admin starts active' using errcode = '23514';
    end if;
    return new;
  end if;
  if tg_op = 'UPDATE' and old.status = 'active' and new.status = 'revoked'
     and (new.auth_user_id, new.note, new.added_at, new.added_by_session_user)
         is not distinct from (old.auth_user_id, old.note, old.added_at, old.added_by_session_user) then
    return new;
  end if;
  raise exception 'knowledge_registry_admins: % is refused (only active -> revoked)', tg_op using errcode = '42501';
end;
$$;
revoke all on function private.knowledge_registry_admin_guard() from public, anon, authenticated, service_role;
create trigger knowledge_registry_admins_guard
  before update or delete on public.knowledge_registry_admins
  for each row execute function private.knowledge_registry_admin_guard();
create trigger knowledge_registry_admins_insert_guard
  before insert on public.knowledge_registry_admins
  for each row execute function private.knowledge_registry_admin_guard();
create trigger knowledge_registry_admins_no_truncate
  before truncate on public.knowledge_registry_admins
  for each statement execute function private.knowledge_m2_no_truncate();

-- Personnel and roles: written only by the registry RPCs. After the insert, only the status fields
-- change (active <-> suspended, any -> revoked, revoked terminal). Never deleted.
create function private.knowledge_personnel_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not private.knowledge_m2_write_authorized(tg_table_name) then
    raise exception '%: rows are written only by the M2 registry RPCs (% refused)', tg_table_name, tg_op
      using errcode = '42501';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'active' or new.status_changed_at is not null then
      raise exception '%: a new row starts active', tg_table_name using errcode = '23514';
    end if;
    return new;
  end if;
  if tg_op = 'DELETE' then
    raise exception '%: rows are never deleted (revoke instead)', tg_table_name using errcode = '42501';
  end if;
  if old.status = 'revoked' or new.status = old.status
     or not ((old.status, new.status) in (('active', 'suspended'), ('suspended', 'active'),
                                          ('active', 'revoked'), ('suspended', 'revoked'))) then
    raise exception '%: status % -> % is not allowed (revoked is terminal)', tg_table_name, old.status, new.status
      using errcode = '23514';
  end if;
  if (to_jsonb(new) - array['status', 'status_changed_at', 'status_changed_by', 'status_reason'])
     is distinct from (to_jsonb(old) - array['status', 'status_changed_at', 'status_changed_by', 'status_reason']) then
    raise exception '%: only the status of a verified record changes (re-register for new facts)', tg_table_name
      using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function private.knowledge_personnel_guard() from public, anon, authenticated, service_role;
create trigger knowledge_personnel_guard
  before insert or update or delete on public.knowledge_personnel
  for each row execute function private.knowledge_personnel_guard();
create trigger knowledge_personnel_no_truncate
  before truncate on public.knowledge_personnel
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_personnel_roles_guard
  before insert or update or delete on public.knowledge_personnel_roles
  for each row execute function private.knowledge_personnel_guard();
create trigger knowledge_personnel_roles_no_truncate
  before truncate on public.knowledge_personnel_roles
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== verified actor

-- The authenticated human behind this call, or an exception. Everything is read from what PostgREST
-- verified (the JWT claims) AND cross-checked against Auth's own tables.
create function private.knowledge_verified_actor(out user_id uuid, out session_id uuid)
language plpgsql
stable
set search_path = ''
as $$
declare
  v_claims jsonb := auth.jwt();
  v_exp numeric;
begin
  if coalesce(current_setting('role', true), '') <> 'authenticated'
     or coalesce(v_claims ->> 'role', '') <> 'authenticated' then
    raise exception 'knowledge review and approval need an authenticated personal session'
      ' (service and owner logins cannot act as a person)' using errcode = '42501';
  end if;
  user_id := auth.uid();
  if user_id is null then
    raise exception 'knowledge review and approval need an authenticated user' using errcode = '42501';
  end if;
  if coalesce(v_claims ->> 'aal', '') <> 'aal2' then
    raise exception 'knowledge review and approval need multi-factor authentication (aal2)' using errcode = '42501';
  end if;
  begin
    v_exp := (v_claims ->> 'exp')::numeric;
    knowledge_verified_actor.session_id := (v_claims ->> 'session_id')::uuid;
  exception when others then
    v_exp := null; knowledge_verified_actor.session_id := null;
  end;
  if v_exp is null or v_exp <= extract(epoch from pg_catalog.now()) then
    raise exception 'knowledge review and approval need an unexpired access token' using errcode = '42501';
  end if;
  if knowledge_verified_actor.session_id is null or not exists (
      select 1 from auth.sessions s
       where s.id = knowledge_verified_actor.session_id and s.user_id = knowledge_verified_actor.user_id
         and s.aal = 'aal2'::auth.aal_level
         and (s.not_after is null or s.not_after > pg_catalog.now())) then
    raise exception 'knowledge review and approval need a live aal2 session of this user' using errcode = '42501';
  end if;
  if not exists (select 1 from auth.mfa_factors f
                  where f.user_id = knowledge_verified_actor.user_id and f.status = 'verified'::auth.factor_status) then
    raise exception 'knowledge review and approval need a verified MFA factor' using errcode = '42501';
  end if;
  if not exists (select 1 from auth.users u
                  where u.id = knowledge_verified_actor.user_id and u.deleted_at is null and not u.is_anonymous
                    and (u.banned_until is null or u.banned_until <= pg_catalog.now())) then
    raise exception 'knowledge review and approval need an active, non-anonymous user' using errcode = '42501';
  end if;
  if private.password_change_pending() then
    raise exception 'knowledge review and approval are blocked while a password change is pending'
      using errcode = '42501';
  end if;
end;
$$;
revoke all on function private.knowledge_verified_actor() from public, anon, authenticated, service_role;

-- The active role assignment of an active person for `p_role` covering a source's scope, or null.
create function private.knowledge_actor_role(
  p_user uuid, p_role text, p_visibility text, p_organization uuid,
  out personnel_id uuid, out role_id uuid, out qualification_category text, out identity_reference text)
language sql
stable
set search_path = ''
as $$
  select p.id, r.id, r.qualification_category, private.knowledge_identity_key(p.identity_reference)
    from public.knowledge_personnel p
    join public.knowledge_personnel_roles r on r.personnel_id = p.id
   where p.auth_user_id = p_user and p.status = 'active' and r.status = 'active' and r.role = p_role
     and r.valid_from <= pg_catalog.now() and (r.valid_until is null or r.valid_until > pg_catalog.now())
     and r.scope_visibility = p_visibility
     and r.scope_organization_id is not distinct from (case when p_visibility = 'tenant' then p_organization end)
   order by r.verified_at, r.id
   limit 1;
$$;
revoke all on function private.knowledge_actor_role(uuid, text, text, uuid) from public, anon, authenticated, service_role;

-- The canonical identity key of a personnel record: the same human, however many records or accounts.
create function private.knowledge_person_identity(p_personnel uuid)
returns text
language sql
stable
set search_path = ''
as $$
  select private.knowledge_identity_key(p.identity_reference) from public.knowledge_personnel p where p.id = p_personnel;
$$;
revoke all on function private.knowledge_person_identity(uuid) from public, anon, authenticated, service_role;

-- The registry admin behind this call (verified actor + active admin row), or an exception.
create function private.knowledge_registry_admin_actor(out user_id uuid, out session_id uuid)
language plpgsql
stable
set search_path = ''
as $$
begin
  select a.user_id, a.session_id into user_id, session_id from private.knowledge_verified_actor() a;
  if not exists (select 1 from public.knowledge_registry_admins ra
                  where ra.auth_user_id = knowledge_registry_admin_actor.user_id and ra.status = 'active') then
    raise exception 'only an active knowledge registry admin manages knowledge personnel' using errcode = '42501';
  end if;
end;
$$;
revoke all on function private.knowledge_registry_admin_actor() from public, anon, authenticated, service_role;

-- ================================================================== snapshots

-- Everything an approval decision depends on: the version's identity, provenance, artifact, license
-- and pipeline; its source's identity, scope and provenance; and a manifest of its chunks. jsonb
-- normalizes key order, and every timestamptz is rendered as fixed UTC text, so the text form (and its
-- hash) is the same for equal content whatever the caller's session TimeZone.
create function private.knowledge_document_snapshot(p_document_pk uuid)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'document', pg_catalog.jsonb_build_object(
      'id', d.id, 'source_id', d.source_id, 'document_id', d.document_id, 'document_version', d.document_version,
      'title', d.title, 'language', d.language, 'official_url', d.official_url, 'artifact_ref', d.artifact_ref,
      'file_sha256', d.file_sha256, 'normalized_sha256', d.normalized_sha256, 'published_at', d.published_at,
      'imported_at', pg_catalog.to_char(d.imported_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), 'parser_version', d.parser_version, 'normalizer_version', d.normalizer_version,
      'chunker_version', d.chunker_version, 'license_basis', d.license_basis, 'license_reference', d.license_reference),
    'source', (select pg_catalog.jsonb_build_object(
      'source_id', s.source_id, 'title', s.title, 'owner', s.owner, 'source_type', s.source_type,
      'authority', s.authority, 'visibility', s.visibility, 'organization_id', s.organization_id,
      'farm_id', s.farm_id, 'created_at', pg_catalog.to_char(s.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
      from public.knowledge_sources s where s.source_id = d.source_id),
    'chunks', (select pg_catalog.jsonb_build_object(
      'count', count(*),
      'manifest_sha256', pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce(
        pg_catalog.string_agg(c.ordinal::text || ':' || c.chunk_id || ':' || c.content_sha256, E'\n' order by c.ordinal),
        ''), 'UTF8')), 'hex'))
      from public.knowledge_chunks c where c.document_pk = d.id))
  from public.knowledge_documents d where d.id = p_document_pk;
$$;
revoke all on function private.knowledge_document_snapshot(uuid) from public, anon, authenticated, service_role;

create function private.knowledge_source_snapshot(p_source_id text)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'source_id', s.source_id, 'title', s.title, 'owner', s.owner, 'source_type', s.source_type,
    'authority', s.authority, 'visibility', s.visibility, 'organization_id', s.organization_id,
    'farm_id', s.farm_id, 'created_at', pg_catalog.to_char(s.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
  from public.knowledge_sources s where s.source_id = p_source_id;
$$;
revoke all on function private.knowledge_source_snapshot(text) from public, anon, authenticated, service_role;

create function private.knowledge_snapshot_sha256(p_snapshot jsonb)
returns text
language sql
immutable
set search_path = ''
as $$
  select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_snapshot::text, 'UTF8')), 'hex');
$$;
revoke all on function private.knowledge_snapshot_sha256(jsonb) from public, anon, authenticated, service_role;
-- Clients compute the hash they confirm with the same function, through this read-only wrapper: it
-- returns the hash of a document version or source only to a verified actor holding a knowledge role
-- in that scope (no existence oracle for anyone else).
create function public.knowledge_review_snapshot(p_document_pk uuid default null, p_source_id text default null)
returns table (snapshot jsonb, snapshot_sha256 text)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_src record;
  v_snap jsonb;
begin
  select a.user_id into v_actor from private.knowledge_verified_actor() a;
  if (p_document_pk is null) = (p_source_id is null) then
    raise exception 'name exactly one of a document version or a source' using errcode = '22023';
  end if;
  select s.visibility, s.organization_id into v_src from public.knowledge_sources s
   where s.source_id = coalesce(p_source_id, (select d.source_id from public.knowledge_documents d where d.id = p_document_pk));
  if not found or not exists (
      select 1 from unnest(array['uploader', 'expert_reviewer', 'approver']) r(role)
       where (private.knowledge_actor_role(v_actor.user_id, r.role, v_src.visibility, v_src.organization_id)).role_id is not null) then
    raise exception 'not available for your knowledge role' using errcode = '42501';
  end if;
  v_snap := case when p_document_pk is not null then private.knowledge_document_snapshot(p_document_pk)
                 else private.knowledge_source_snapshot(p_source_id) end;
  if v_snap is null then
    raise exception 'not available for your knowledge role' using errcode = '42501';
  end if;
  return query select v_snap, private.knowledge_snapshot_sha256(v_snap);
end;
$$;
revoke all on function public.knowledge_review_snapshot(uuid, text) from public, anon, authenticated, service_role;
grant execute on function public.knowledge_review_snapshot(uuid, text) to authenticated;

-- ================================================================== shared transition core

-- The M1 transition bodies, unchanged, as internal functions with no grant: only definer functions
-- (owned by the event log's owner) reach them. The M1 operator functions and the M2 RPCs call them.
create function private.knowledge_apply_source_transition(
  p_source_id text, p_from public.knowledge_status, p_to public.knowledge_status, p_reason text,
  p_approved_by uuid)
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  v_status public.knowledge_status;
  v_event bigint;
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'knowledge source %: a transition needs a reason (1-2000 characters)', p_source_id
      using errcode = '22023';
  end if;
  if not private.knowledge_status_transition_allowed('source', p_from, p_to) then
    raise exception 'knowledge source %: status % -> % is not allowed', p_source_id, p_from, p_to
      using errcode = '23514';
  end if;
  if (p_to = 'approved') <> (p_approved_by is not null) then
    raise exception 'knowledge source %: an approver is named exactly for an approval', p_source_id
      using errcode = '22023';
  end if;
  select s.status into v_status from public.knowledge_sources s where s.source_id = p_source_id for update;
  if not found then
    raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
  end if;
  if v_status <> p_from then
    raise exception 'knowledge source %: status is %, not % (changed concurrently or a stale request)',
      p_source_id, v_status, p_from using errcode = '23514';
  end if;
  perform pg_catalog.set_config('knowledge.status_transition', 'source|' || p_source_id || '|' || p_to::text, true);
  if p_to = 'approved' then
    update public.knowledge_sources
       set status = p_to, approved_by = p_approved_by, approved_at = now(), review_note = p_reason
     where source_id = p_source_id;
  else
    update public.knowledge_sources set status = p_to where source_id = p_source_id;
  end if;
  perform pg_catalog.set_config('knowledge.status_transition', '', true);
  insert into public.knowledge_status_events
    (entity_type, source_id, from_status, to_status, reason, stated_approver, actor_session_user, actor_role)
  values ('source', p_source_id, p_from, p_to, p_reason, p_approved_by, session_user,
          coalesce(nullif(current_setting('role', true), 'none'), session_user))
  returning id into v_event;
  return v_event;
end;
$$;
revoke all on function private.knowledge_apply_source_transition(text, public.knowledge_status,
  public.knowledge_status, text, uuid) from public, anon, authenticated, service_role;

create function private.knowledge_apply_document_transition(
  p_document_pk uuid, p_from public.knowledge_status, p_to public.knowledge_status, p_reason text,
  p_approved_by uuid)
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  v_doc record;
  v_event bigint;
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'knowledge document %: a transition needs a reason (1-2000 characters)', p_document_pk
      using errcode = '22023';
  end if;
  if not private.knowledge_status_transition_allowed('document', p_from, p_to) then
    raise exception 'knowledge document %: status % -> % is not allowed', p_document_pk, p_from, p_to
      using errcode = '23514';
  end if;
  if (p_to = 'approved') <> (p_approved_by is not null) then
    raise exception 'knowledge document %: an approver is named exactly for an approval', p_document_pk
      using errcode = '22023';
  end if;
  select d.status, d.source_id, d.document_id, d.document_version into v_doc
    from public.knowledge_documents d where d.id = p_document_pk for update;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  if v_doc.status <> p_from then
    raise exception 'knowledge document %: status is %, not % (changed concurrently or a stale request)',
      p_document_pk, v_doc.status, p_from using errcode = '23514';
  end if;
  perform pg_catalog.set_config('knowledge.status_transition',
                                'document|' || p_document_pk::text || '|' || p_to::text, true);
  if p_to = 'approved' then
    update public.knowledge_documents
       set status = p_to, approved_by = p_approved_by, approved_at = now(), review_note = p_reason
     where id = p_document_pk;
  else
    update public.knowledge_documents set status = p_to where id = p_document_pk;
  end if;
  perform pg_catalog.set_config('knowledge.status_transition', '', true);
  insert into public.knowledge_status_events
    (entity_type, source_id, document_pk, document_id, document_version, from_status, to_status, reason,
     stated_approver, actor_session_user, actor_role)
  values ('document', v_doc.source_id, p_document_pk, v_doc.document_id, v_doc.document_version, p_from, p_to,
          p_reason, p_approved_by, session_user, coalesce(nullif(current_setting('role', true), 'none'), session_user))
  returning id into v_event;
  return v_event;
end;
$$;
revoke all on function private.knowledge_apply_document_transition(uuid, public.knowledge_status,
  public.knowledge_status, text, uuid) from public, anon, authenticated, service_role;

-- ================================================================== M1 operator functions (replaced)

-- Same contract as M1 (argument checks first, with the same SQLSTATEs), but the transitions M2 owns
-- are refused here for every caller, service_role and owner alike.
create or replace function private.knowledge_transition_source(
  p_source_id text,
  p_from public.knowledge_status,
  p_to public.knowledge_status,
  p_reason text,
  p_approved_by uuid default null)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_status public.knowledge_status;
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'knowledge source %: a transition needs a reason (1-2000 characters)', p_source_id
      using errcode = '22023';
  end if;
  if not private.knowledge_status_transition_allowed('source', p_from, p_to) then
    raise exception 'knowledge source %: status % -> % is not allowed', p_source_id, p_from, p_to
      using errcode = '23514';
  end if;
  if (p_to = 'approved') <> (p_approved_by is not null) then
    raise exception 'knowledge source %: an approver is named exactly for an approval', p_source_id
      using errcode = '22023';
  end if;
  if p_to = 'approved' then
    -- a stale or unknown request is reported as in M1, before the M2 refusal
    select s.status into v_status from public.knowledge_sources s where s.source_id = p_source_id;
    if not found then
      raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
    end if;
    if v_status <> p_from then
      raise exception 'knowledge source %: status is %, not % (changed concurrently or a stale request)',
        p_source_id, v_status, p_from using errcode = '23514';
    end if;
    raise exception 'knowledge source %: approval is a verified human decision (M2): the approver calls'
      ' public.knowledge_approve_source with an aal2 session; operator and owner logins cannot approve',
      p_source_id using errcode = '42501';
  end if;
  return private.knowledge_apply_source_transition(p_source_id, p_from, p_to, p_reason, p_approved_by);
end;
$$;

create or replace function private.knowledge_transition_document(
  p_document_pk uuid,
  p_from public.knowledge_status,
  p_to public.knowledge_status,
  p_reason text,
  p_approved_by uuid default null)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_status public.knowledge_status;
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'knowledge document %: a transition needs a reason (1-2000 characters)', p_document_pk
      using errcode = '22023';
  end if;
  if not private.knowledge_status_transition_allowed('document', p_from, p_to) then
    raise exception 'knowledge document %: status % -> % is not allowed', p_document_pk, p_from, p_to
      using errcode = '23514';
  end if;
  if (p_to = 'approved') <> (p_approved_by is not null) then
    raise exception 'knowledge document %: an approver is named exactly for an approval', p_document_pk
      using errcode = '22023';
  end if;
  if p_to in ('expert_review', 'approved') or (p_from = 'expert_review' and p_to = 'review_required') then
    select d.status into v_status from public.knowledge_documents d where d.id = p_document_pk;
    if not found then
      raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
    end if;
    if v_status <> p_from then
      raise exception 'knowledge document %: status is %, not % (changed concurrently or a stale request)',
        p_document_pk, v_status, p_from using errcode = '23514';
    end if;
    raise exception 'knowledge document %: % -> % is a verified human decision (M2): use'
      ' public.knowledge_start_expert_review / knowledge_submit_expert_review / knowledge_decide_document'
      ' with an aal2 session; operator and owner logins cannot review or approve', p_document_pk, p_from, p_to
      using errcode = '42501';
  end if;
  return private.knowledge_apply_document_transition(p_document_pk, p_from, p_to, p_reason, p_approved_by);
end;
$$;

-- ================================================================== row triggers (replaced)

-- Source: the M1 trigger plus one rule: a status change to approved needs this transaction's approval
-- record for exactly this source (public.knowledge_approve_source writes it first).
create or replace function private.enforce_knowledge_source_scope()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.approved_at is not null then
      raise exception 'knowledge source % was approved and cannot be deleted (archive it)', old.source_id
        using errcode = '23514';
    end if;
    return old;
  end if;
  if tg_op = 'UPDATE' and new.status <> old.status
     and not private.knowledge_status_transition_authorized('source', old.source_id, new.status) then
    raise exception 'knowledge source %: status % -> % must go through private.knowledge_transition_source'
      ' (a direct status update is refused)', old.source_id, old.status, new.status using errcode = '42501';
  end if;
  if new.status in ('review_required', 'rejected') and (new.approved_by is not null or new.approved_at is not null) then
    raise exception 'knowledge source %: an approval record requires status approved', new.source_id
      using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'review_required' then
      raise exception 'knowledge source %: a new source starts review_required; every later status is a'
        ' controlled transition (private.knowledge_transition_source)', new.source_id using errcode = '23514';
    end if;
    if new.farm_id is not null and not exists (
        select 1 from public.farms f where f.id = new.farm_id and f.cooperative_id = new.organization_id) then
      raise exception 'knowledge source %: farm % does not belong to organization %',
        new.source_id, new.farm_id, new.organization_id using errcode = '23514';
    end if;
    return new;
  end if;
  if (new.source_id, new.visibility, new.organization_id, new.farm_id, new.created_at)
      is distinct from (old.source_id, old.visibility, old.organization_id, old.farm_id, old.created_at) then
    raise exception 'knowledge source % scope is immutable', old.source_id using errcode = '23514';
  end if;
  if new.status <> old.status then
    if not private.knowledge_status_transition_allowed('source', old.status, new.status) then
      raise exception 'knowledge source %: status % -> % is not allowed', old.source_id, old.status, new.status
        using errcode = '23514';
    end if;
    -- M2: an approval is backed by this transaction's verified approval record of this source.
    if new.status = 'approved' and not exists (
        select 1 from public.knowledge_approval_records a
         where a.entity_type = 'source' and a.source_id = old.source_id and a.decision = 'approve'
           and a.approver_user_id = new.approved_by
           and a.recorded_xact = pg_catalog.pg_current_xact_id()) then
      raise exception 'knowledge source %: approval needs a verified approval record (public.knowledge_approve_source)',
        old.source_id using errcode = '42501';
    end if;
  end if;
  if old.approved_at is not null
     and (new.title, new.owner, new.source_type, new.authority, new.approved_by, new.approved_at, new.review_note)
         is distinct from
         (old.title, old.owner, old.source_type, old.authority, old.approved_by, old.approved_at, old.review_note) then
    raise exception 'knowledge source % was approved; its provenance and approval record are immutable',
      old.source_id using errcode = '23514';
  end if;
  return new;
end;
$$;

-- Document: the M1 trigger plus M2 rules: entering expert_review needs this transaction's new review
-- of this version; approval needs this transaction's approve record of this version; the decision
-- metadata is frozen from expert_review on; a version with evidence is never deleted (FK restrict).
create or replace function private.enforce_knowledge_document_immutability()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.approved_at is not null then
      raise exception 'knowledge document % % % was approved and cannot be deleted',
        old.source_id, old.document_id, old.document_version using errcode = '23514';
    end if;
    if old.status = 'expert_review' then
      raise exception 'knowledge document % % % is under expert review and cannot be deleted',
        old.source_id, old.document_id, old.document_version using errcode = '23514';
    end if;
    return old;
  end if;
  if tg_op = 'UPDATE' and new.status <> old.status
     and not private.knowledge_status_transition_authorized('document', old.id::text, new.status) then
    raise exception 'knowledge document % % %: status % -> % must go through private.knowledge_transition_document'
      ' (a direct status update is refused)',
      old.source_id, old.document_id, old.document_version, old.status, new.status using errcode = '42501';
  end if;
  if new.status in ('review_required', 'rejected', 'expert_review')
     and (new.approved_by is not null or new.approved_at is not null) then
    raise exception 'knowledge document % % %: an approval record requires status approved',
      new.source_id, new.document_id, new.document_version using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'review_required' then
      raise exception 'knowledge document % % %: a new version starts review_required; every later status is'
        ' a controlled transition (private.knowledge_transition_document)',
        new.source_id, new.document_id, new.document_version using errcode = '23514';
    end if;
    return new;
  end if;
  if (new.id, new.source_id, new.document_id, new.document_version, new.file_sha256, new.normalized_sha256,
      new.parser_version, new.normalizer_version, new.chunker_version, new.imported_at)
      is distinct from
     (old.id, old.source_id, old.document_id, old.document_version, old.file_sha256, old.normalized_sha256,
      old.parser_version, old.normalizer_version, old.chunker_version, old.imported_at) then
    raise exception 'knowledge document % % % identity/provenance is immutable',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  -- M2 freeze: what the expert reviews is exactly what gets approved.
  if old.status = 'expert_review'
     and (new.title, new.language, new.official_url, new.artifact_ref, new.published_at, new.license_basis,
          new.license_reference)
         is distinct from
         (old.title, old.language, old.official_url, old.artifact_ref, old.published_at, old.license_basis,
          old.license_reference) then
    raise exception 'knowledge document % % % is under expert review; its artifact, license and metadata are'
      ' frozen (return it to review_required, or ingest a new version)',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  if new.status <> old.status then
    if not private.knowledge_status_transition_allowed('document', old.status, new.status) then
      raise exception 'knowledge document % % %: status % -> % is not allowed',
        old.source_id, old.document_id, old.document_version, old.status, new.status using errcode = '23514';
    end if;
    if new.status = 'expert_review' and not exists (
        select 1 from public.knowledge_expert_reviews r
         where r.document_pk = old.id and r.decision is null
           and r.recorded_xact = pg_catalog.pg_current_xact_id())
       and not exists (                                    -- or the owner-switched, labelled demo path
        select 1 from public.knowledge_approval_records a
         where a.document_pk = old.id and a.assurance = 'demo_unverified'
           and a.recorded_xact = pg_catalog.pg_current_xact_id()) then
      raise exception 'knowledge document % % %: expert review starts only with a verified reviewer'
        ' (public.knowledge_start_expert_review)', old.source_id, old.document_id, old.document_version
        using errcode = '42501';
    end if;
    if new.status = 'approved' and not exists (
        select 1 from public.knowledge_approval_records a
         where a.entity_type = 'document' and a.document_pk = old.id and a.decision = 'approve'
           and a.approver_user_id = new.approved_by
           and a.recorded_xact = pg_catalog.pg_current_xact_id()) then
      raise exception 'knowledge document % % %: approval needs a verified approval record'
        ' (public.knowledge_decide_document)', old.source_id, old.document_id, old.document_version
        using errcode = '42501';
    end if;
  end if;
  if old.approved_at is not null
     and (new.title, new.language, new.official_url, new.artifact_ref, new.published_at, new.license_basis,
          new.license_reference, new.approved_by, new.approved_at, new.review_note)
         is distinct from
         (old.title, old.language, old.official_url, old.artifact_ref, old.published_at, old.license_basis,
          old.license_reference, old.approved_by, old.approved_at, old.review_note) then
    raise exception 'knowledge document % % % was approved; its provenance and approval record are immutable',
      old.source_id, old.document_id, old.document_version using errcode = '23514';
  end if;
  return new;
end;
$$;

-- ================================================================== JSON evidence validation

-- 22023 unless the reviewer's evidence is well-formed; for recommend_approval also complete: every
-- checklist item true, at least one checked reference, and no open blocking finding.
create function private.knowledge_check_review_evidence(
  p_decision text, p_checklist jsonb, p_sources_checked jsonb, p_findings jsonb, p_rationale text)
returns void
language plpgsql
immutable
set search_path = ''
as $$
declare
  v_required constant text[] := array['provenance_verified', 'artifact_sha256_verified', 'license_verified',
                                      'version_and_dates_checked', 'scope_checked', 'claims_checked'];
  v_key text;
  v_item jsonb;
begin
  if p_decision is null or p_decision not in ('recommend_approval', 'reject', 'return') then
    raise exception 'review decision must be recommend_approval, reject or return' using errcode = '22023';
  end if;
  -- 2000: a reject/return rationale is also the audited transition's reason (M1 bound)
  if p_rationale is null or btrim(p_rationale) = '' or length(p_rationale) > 2000 then
    raise exception 'a review needs a rationale (1-2000 characters)' using errcode = '22023';
  end if;
  if p_checklist is null or pg_catalog.jsonb_typeof(p_checklist) <> 'object'
     or p_sources_checked is null or pg_catalog.jsonb_typeof(p_sources_checked) <> 'array'
     or p_findings is null or pg_catalog.jsonb_typeof(p_findings) <> 'array'
     or pg_catalog.pg_column_size(p_checklist) + pg_catalog.pg_column_size(p_sources_checked)
        + pg_catalog.pg_column_size(p_findings) > 65536
     or pg_catalog.jsonb_array_length(p_sources_checked) > 100 or pg_catalog.jsonb_array_length(p_findings) > 200 then
    raise exception 'review evidence: checklist is an object, sources_checked and findings are arrays (bounded size)'
      using errcode = '22023';
  end if;
  foreach v_key in array v_required loop
    if pg_catalog.jsonb_typeof(p_checklist -> v_key) is distinct from 'boolean' then
      raise exception 'review checklist item % must be answered true or false', v_key using errcode = '22023';
    end if;
  end loop;
  if exists (select 1 from pg_catalog.jsonb_object_keys(p_checklist) k where k <> all (v_required)) then
    raise exception 'review checklist has an unknown item' using errcode = '22023';
  end if;
  for v_item in select e from pg_catalog.jsonb_array_elements(p_sources_checked) e loop
    if pg_catalog.jsonb_typeof(v_item) <> 'object' or pg_catalog.jsonb_typeof(v_item -> 'reference') <> 'string'
       or btrim(v_item ->> 'reference') = '' or length(v_item ->> 'reference') > 1000 then
      raise exception 'each checked source names a reference' using errcode = '22023';
    end if;
  end loop;
  for v_item in select e from pg_catalog.jsonb_array_elements(p_findings) e loop
    if pg_catalog.jsonb_typeof(v_item) <> 'object'
       or coalesce(v_item ->> 'kind', '') not in ('contradiction', 'exception', 'reference_mismatch', 'other')
       or coalesce(v_item ->> 'severity', '') not in ('blocking', 'non_blocking')
       or coalesce(v_item ->> 'status', '') not in ('open', 'resolved', 'accepted_exception')
       or pg_catalog.jsonb_typeof(v_item -> 'description') <> 'string' or btrim(v_item ->> 'description') = ''
       or (v_item ->> 'status' <> 'open'
           and (pg_catalog.jsonb_typeof(v_item -> 'resolution') is distinct from 'string'
                or btrim(v_item ->> 'resolution') = '')) then
      raise exception 'each finding has kind, severity, status, description, and a resolution unless open'
        using errcode = '22023';
    end if;
    if v_item ->> 'status' = 'accepted_exception' and v_item ->> 'kind' = 'contradiction' then
      raise exception 'a contradiction is resolved, never accepted as an exception' using errcode = '22023';
    end if;
  end loop;
  if p_decision = 'recommend_approval' then
    if exists (select 1 from unnest(v_required) k where (p_checklist ->> k)::boolean is not true) then
      raise exception 'recommend_approval needs every checklist item verified (true)' using errcode = '22023';
    end if;
    if pg_catalog.jsonb_array_length(p_sources_checked) = 0 then
      raise exception 'recommend_approval needs at least one checked source' using errcode = '22023';
    end if;
    if exists (select 1 from pg_catalog.jsonb_array_elements(p_findings) e
                where e ->> 'severity' = 'blocking' and e ->> 'status' = 'open') then
      raise exception 'recommend_approval is refused while a blocking finding is open' using errcode = '23514';
    end if;
  end if;
end;
$$;
revoke all on function private.knowledge_check_review_evidence(text, jsonb, jsonb, jsonb, text)
  from public, anon, authenticated, service_role;

-- ================================================================== registry RPCs

create function public.knowledge_register_personnel(
  p_auth_user_id uuid, p_display_name text, p_identity_reference text, p_identity_verification_method text,
  p_identity_evidence_ref text, p_organization_id uuid default null)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
  v_id uuid;
begin
  select a.user_id into v_admin from private.knowledge_registry_admin_actor() a;
  if p_auth_user_id is null or p_auth_user_id = v_admin.user_id then
    raise exception 'a registry admin registers another person, never themselves' using errcode = '42501';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_personnel');
  insert into public.knowledge_personnel (auth_user_id, display_name, identity_reference, identity_verification_method,
                                          identity_evidence_ref, organization_id, verified_by)
  values (p_auth_user_id, p_display_name, p_identity_reference, p_identity_verification_method, p_identity_evidence_ref,
          p_organization_id, v_admin.user_id)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

create function public.knowledge_grant_personnel_role(
  p_personnel_id uuid, p_role text, p_scope_visibility text, p_scope_organization_id uuid,
  p_qualification_category text, p_qualification_method text, p_qualification_evidence_ref text,
  p_valid_until timestamptz default null)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
  v_person record;
  v_id uuid;
begin
  select a.user_id into v_admin from private.knowledge_registry_admin_actor() a;
  select p.auth_user_id, p.status into v_person from public.knowledge_personnel p where p.id = p_personnel_id for share;
  if not found or v_person.status <> 'active' then
    raise exception 'knowledge personnel % is not an active record', p_personnel_id using errcode = '23514';
  end if;
  if v_person.auth_user_id = v_admin.user_id then
    raise exception 'a registry admin never grants a knowledge role to themselves' using errcode = '42501';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_personnel_roles');
  insert into public.knowledge_personnel_roles (personnel_id, role, scope_visibility, scope_organization_id,
    qualification_category, qualification_method, qualification_evidence_ref, valid_until, verified_by)
  values (p_personnel_id, p_role, p_scope_visibility, p_scope_organization_id, p_qualification_category,
          p_qualification_method, p_qualification_evidence_ref, p_valid_until, v_admin.user_id)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

create function public.knowledge_set_personnel_status(p_personnel_id uuid, p_status text, p_reason text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
begin
  select a.user_id into v_admin from private.knowledge_registry_admin_actor() a;
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'a status change needs a reason (1-2000 characters)' using errcode = '22023';
  end if;
  if exists (select 1 from public.knowledge_personnel p where p.id = p_personnel_id and p.auth_user_id = v_admin.user_id) then
    raise exception 'a registry admin never changes their own personnel record' using errcode = '42501';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_personnel');
  update public.knowledge_personnel
     set status = p_status, status_changed_at = pg_catalog.now(), status_changed_by = v_admin.user_id,
         status_reason = p_reason
   where id = p_personnel_id;
  if not found then
    raise exception 'knowledge personnel % does not exist', p_personnel_id using errcode = 'P0002';
  end if;
  perform private.knowledge_m2_set_marker(null);
end;
$$;

create function public.knowledge_set_personnel_role_status(p_role_id uuid, p_status text, p_reason text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
begin
  select a.user_id into v_admin from private.knowledge_registry_admin_actor() a;
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'a status change needs a reason (1-2000 characters)' using errcode = '22023';
  end if;
  if exists (select 1 from public.knowledge_personnel_roles r join public.knowledge_personnel p on p.id = r.personnel_id
              where r.id = p_role_id and p.auth_user_id = v_admin.user_id) then
    raise exception 'a registry admin never changes their own knowledge role' using errcode = '42501';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_personnel_roles');
  update public.knowledge_personnel_roles
     set status = p_status, status_changed_at = pg_catalog.now(), status_changed_by = v_admin.user_id,
         status_reason = p_reason
   where id = p_role_id;
  if not found then
    raise exception 'knowledge role % does not exist', p_role_id using errcode = 'P0002';
  end if;
  perform private.knowledge_m2_set_marker(null);
end;
$$;

-- ================================================================== uploader RPCs

-- The uploader takes responsibility for an ingested version: a verified uploader in the source's
-- scope confirms the exact file and normalized-text hashes. Once per version, while review_required.
create function public.knowledge_attest_document_upload(
  p_document_pk uuid, p_file_sha256 text, p_normalized_sha256 text, p_statement text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_doc record;
  v_role record;
  v_id uuid;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  select d.id, d.status, d.source_id, d.file_sha256, d.normalized_sha256, s.visibility, s.organization_id into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk for update of d;
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'uploader', v_doc.visibility, v_doc.organization_id);
  if v_doc.id is null or v_role.role_id is null then
    raise exception 'document not available for your knowledge role (uploader)' using errcode = '42501';
  end if;
  if v_doc.status <> 'review_required' then
    raise exception 'knowledge document %: an upload is attested while review_required (it is %)', p_document_pk,
      v_doc.status using errcode = '23514';
  end if;
  if p_file_sha256 is distinct from v_doc.file_sha256 or p_normalized_sha256 is distinct from v_doc.normalized_sha256 then
    raise exception 'knowledge document %: the attested hashes do not match the stored version', p_document_pk
      using errcode = '23514';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_upload_attestations');
  insert into public.knowledge_upload_attestations (entity_type, source_id, document_pk, file_sha256, normalized_sha256,
    uploader_personnel_id, uploader_role_id, uploader_user_id, auth_session_id, statement)
  values ('document', v_doc.source_id, p_document_pk, p_file_sha256, p_normalized_sha256, v_role.personnel_id,
          v_role.role_id, v_actor.user_id, v_actor.session_id, p_statement)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

create function public.knowledge_attest_source_upload(p_source_id text, p_statement text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_src record;
  v_role record;
  v_id uuid;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  select s.source_id, s.status, s.visibility, s.organization_id into v_src
    from public.knowledge_sources s where s.source_id = p_source_id for update;
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'uploader', v_src.visibility, v_src.organization_id);
  if v_src.source_id is null or v_role.role_id is null then
    raise exception 'source not available for your knowledge role (uploader)' using errcode = '42501';
  end if;
  if v_src.status not in ('review_required', 'rejected') then
    raise exception 'knowledge source %: an upload is attested before approval (it is %)', p_source_id, v_src.status
      using errcode = '23514';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_upload_attestations');
  insert into public.knowledge_upload_attestations (entity_type, source_id, uploader_personnel_id, uploader_role_id,
    uploader_user_id, auth_session_id, statement)
  values ('source', p_source_id, v_role.personnel_id, v_role.role_id, v_actor.user_id, v_actor.session_id, p_statement)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

-- ================================================================== reviewer RPCs

-- A verified expert reviewer in scope, who is not the uploader, starts the review of an attested
-- version: review_required -> expert_review. The snapshot (and its hash) is frozen in the review row
-- and the reviewer confirms the artifact hash they are reviewing.
create function public.knowledge_start_expert_review(p_document_pk uuid, p_file_sha256 text, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_doc record;
  v_role record;
  v_att record;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  select d.id, d.status, d.source_id, d.document_id, d.document_version, d.file_sha256, s.visibility, s.organization_id
    into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk for update of d;
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'expert_reviewer', v_doc.visibility,
                                                         v_doc.organization_id);
  if v_doc.id is null or v_role.role_id is null then
    raise exception 'document not available for your knowledge role (expert_reviewer)' using errcode = '42501';
  end if;
  if v_doc.status <> 'review_required' then
    raise exception 'knowledge document %: expert review starts from review_required (it is %)', p_document_pk,
      v_doc.status using errcode = '23514';
  end if;
  if p_file_sha256 is distinct from v_doc.file_sha256 then
    raise exception 'knowledge document %: the artifact hash you reviewed is not this version''s', p_document_pk
      using errcode = '23514';
  end if;
  select a.id, a.uploader_personnel_id, a.uploader_user_id into v_att
    from public.knowledge_upload_attestations a where a.entity_type = 'document' and a.document_pk = p_document_pk;
  if not found then
    raise exception 'knowledge document %: no verified uploader has attested this version', p_document_pk
      using errcode = '23514';
  end if;
  if v_att.uploader_personnel_id = v_role.personnel_id or v_att.uploader_user_id = v_actor.user_id
     or private.knowledge_person_identity(v_att.uploader_personnel_id) = v_role.identity_reference then
    raise exception 'separation of duties: the uploader cannot be the expert reviewer' using errcode = '42501';
  end if;
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  -- The review row comes first (the row trigger requires it), its start event right after.
  perform private.knowledge_m2_set_marker('knowledge_expert_reviews');
  insert into public.knowledge_expert_reviews (id, document_pk, source_id, document_id, document_version,
    upload_attestation_id, reviewer_personnel_id, reviewer_role_id, reviewer_user_id, reviewer_session_id,
    qualification_category, snapshot, snapshot_sha256, start_event_id)
  values (v_id, p_document_pk, v_doc.source_id, v_doc.document_id, v_doc.document_version, v_att.id,
          v_role.personnel_id, v_role.role_id, v_actor.user_id, v_actor.session_id, v_role.qualification_category,
          v_snap, private.knowledge_snapshot_sha256(v_snap), 0);
  perform private.knowledge_m2_set_marker(null);
  v_event := private.knowledge_apply_document_transition(p_document_pk, 'review_required', 'expert_review',
                                                         p_reason, null);
  -- start_event_id is set by this definer only, inside the same transaction (decision marker absent:
  -- a second, generic writer path is not needed). Done with a dedicated marker.
  perform private.knowledge_m2_set_marker('knowledge_expert_reviews.start_event');
  update public.knowledge_expert_reviews set start_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

-- The reviewer who started the review records the decision once, with the evidence:
--   recommend_approval  version stays expert_review for an approver (complete evidence required)
--   reject              expert_review -> rejected
--   return              expert_review -> review_required (a correction; a later review starts afresh)
-- p_snapshot_sha256 is the snapshot the reviewer examined: it must equal the frozen one and the current one.
create function public.knowledge_submit_expert_review(
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


-- A registry admin cancels a review that cannot finish (the reviewer left, lost their MFA device, was
-- suspended, or does not answer): expert_review -> review_required, recorded on the review as decision
-- 'cancelled' with the admin, the reason and the audit event. Fail closed: nothing is approved, the
-- version needs a fresh review by an eligible reviewer, and the cancelled review can never be reused.
create function public.knowledge_cancel_expert_review(p_review_id uuid, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
  v_rev record;
  v_status public.knowledge_status;
  v_event bigint;
begin
  select a.user_id, a.session_id into v_admin from private.knowledge_registry_admin_actor() a;
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 2000 then
    raise exception 'a cancellation needs a reason (1-2000 characters)' using errcode = '22023';
  end if;
  select r.* into v_rev from public.knowledge_expert_reviews r where r.id = p_review_id;
  if not found then
    raise exception 'review % does not exist', p_review_id using errcode = 'P0002';
  end if;
  select d.status into v_status from public.knowledge_documents d where d.id = v_rev.document_pk for update;
  if v_rev.decision is not null and v_rev.decision <> 'recommend_approval' then
    raise exception 'review %: already closed (%)', p_review_id, v_rev.decision using errcode = '23514';
  end if;
  if v_status <> 'expert_review' or exists (
      select 1 from public.knowledge_expert_reviews r2 where r2.document_pk = v_rev.document_pk and r2.seq > v_rev.seq)
     or exists (select 1 from public.knowledge_approval_records a where a.review_id = p_review_id) then
    raise exception 'review %: the version is not under this review', p_review_id using errcode = '23514';
  end if;
  if v_rev.decision = 'recommend_approval' then
    raise exception 'review %: the expert already decided; the approver approves or rejects it', p_review_id
      using errcode = '23514';
  end if;
  v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review', 'review_required',
                                                         'review cancelled by a registry admin: ' || p_reason, null);
  perform private.knowledge_m2_set_marker('knowledge_expert_reviews.decision');
  update public.knowledge_expert_reviews
     set decision = 'cancelled', checklist = '{}'::jsonb, sources_checked = '[]'::jsonb, findings = '[]'::jsonb,
         rationale = p_reason, decided_at = pg_catalog.now(), decision_session_id = v_admin.session_id,
         decision_event_id = v_event, cancelled_by = v_admin.user_id
   where id = p_review_id;
  perform private.knowledge_m2_set_marker(null);
  return p_review_id;
end;
$$;

-- ================================================================== approver RPCs

-- The approver decides on a recommended review: approve (expert_review -> approved) or reject
-- (expert_review -> rejected). Refused unless the caller is a verified approver in scope, distinct
-- from the uploader and the reviewer; the reviewer is still active and qualified; the review is the
-- current one, recommends approval and has complete evidence with no open blocking finding; and the
-- version and its source still match the reviewed snapshot exactly (p_snapshot_sha256 included).
create function public.knowledge_decide_document(
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
  v_event := private.knowledge_apply_document_transition(v_rev.document_pk, 'expert_review',
    (case when p_decision = 'approve' then 'approved' else 'rejected' end)::public.knowledge_status,
    p_rationale, case when p_decision = 'approve' then v_actor.user_id end);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

-- Source approval keeps the source flow (review_required | rejected -> approved; no expert_review):
-- a verified approver in the source's scope, not its attested uploader, approves exactly the source
-- metadata they confirm (p_snapshot_sha256).
create function public.knowledge_approve_source(p_source_id text, p_snapshot_sha256 text, p_rationale text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_src record;
  v_role record;
  v_att record;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  if p_rationale is null or btrim(p_rationale) = '' or length(p_rationale) > 2000 then
    raise exception 'an approval decision needs a rationale (1-2000 characters)' using errcode = '22023';
  end if;
  select s.source_id, s.status, s.visibility, s.organization_id into v_src
    from public.knowledge_sources s where s.source_id = p_source_id for update;
  select * into v_role from private.knowledge_actor_role(v_actor.user_id, 'approver', v_src.visibility, v_src.organization_id);
  if v_src.source_id is null or v_role.role_id is null then
    raise exception 'source not available for your knowledge role (approver)' using errcode = '42501';
  end if;
  if v_src.status not in ('review_required', 'rejected') then
    raise exception 'knowledge source %: status % cannot be approved', p_source_id, v_src.status using errcode = '23514';
  end if;
  select a.id, a.uploader_personnel_id, a.uploader_user_id into v_att
    from public.knowledge_upload_attestations a where a.entity_type = 'source' and a.source_id = p_source_id;
  if not found then
    raise exception 'knowledge source %: no verified uploader has attested it', p_source_id using errcode = '23514';
  end if;
  if v_att.uploader_personnel_id = v_role.personnel_id or v_att.uploader_user_id = v_actor.user_id
     or private.knowledge_person_identity(v_att.uploader_personnel_id) = v_role.identity_reference then
    raise exception 'separation of duties: the uploader cannot approve' using errcode = '42501';
  end if;
  v_snap := private.knowledge_source_snapshot(p_source_id);
  if p_snapshot_sha256 is distinct from private.knowledge_snapshot_sha256(v_snap) then
    raise exception 'knowledge source %: the metadata you confirmed is not the current metadata', p_source_id
      using errcode = '23514';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_approval_records');
  insert into public.knowledge_approval_records (id, entity_type, source_id, upload_attestation_id, decision,
    approver_personnel_id, approver_role_id, approver_user_id, approver_session_id, snapshot, snapshot_sha256,
    rationale, status_event_id)
  values (v_id, 'source', p_source_id, v_att.id, 'approve', v_role.personnel_id, v_role.role_id, v_actor.user_id,
          v_actor.session_id, v_snap, private.knowledge_snapshot_sha256(v_snap), p_rationale, 0);
  perform private.knowledge_m2_set_marker(null);
  v_event := private.knowledge_apply_source_transition(p_source_id, v_src.status, 'approved', p_rationale,
                                                       v_actor.user_id);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;


-- ================================================================== demo approvals (owner decision)

-- Owner decision (2026-11-10, mid-M2): the system is still in testing, and demos need approved
-- documents before any qualified expert is onboarded. So a DEMO approval path exists next to the
-- verified one, built to be impossible to mistake for it:
--   * an owner-only switch, OFF by default (migrations never turn it on); only the database owner can
--     change it (no grant to any client or service role), and turning it on names a non-production
--     environment label and a note;
--   * private.knowledge_demo_approve_document / _source (EXECUTE service_role only) approve only
--     while the switch is on, write an approval record with assurance = 'demo_unverified' and no
--     review or personnel, prefix every note and audit reason with "DEMO - NOT EXPERT-REVIEWED", and
--     go through the same audited transitions, approval CHECKs (license, ST1, ST1.1) and one-approved-
--     version rule as everything else;
--   * private.knowledge_demo_quarantine_all quarantines every version and source whose current
--     approval is a demo record, in one call, whatever the switch says (the go-live step).
-- The verified flow and every M2 check are unchanged. A demo approval proves nothing about content.

create table private.knowledge_demo_mode (
  singleton boolean primary key default true,
  enabled boolean not null default false,
  environment_label text,
  note text,
  changed_at timestamptz,
  changed_by_session_user text,
  constraint knowledge_demo_mode_singleton_chk check (singleton),
  constraint knowledge_demo_mode_enable_chk check (
    not enabled or (environment_label in ('local', 'ci', 'demo', 'staging')
                    and nullif(btrim(note), '') is not null and length(note) <= 2000))
);
revoke all on private.knowledge_demo_mode from public, anon, authenticated, service_role;
insert into private.knowledge_demo_mode (singleton, enabled) values (true, false);

create function private.knowledge_demo_mode_stamp()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op <> 'UPDATE' then
    raise exception 'knowledge_demo_mode is a single row; only UPDATE it' using errcode = '42501';
  end if;
  new.changed_at := pg_catalog.now();
  new.changed_by_session_user := session_user;
  return new;
end;
$$;
revoke all on function private.knowledge_demo_mode_stamp() from public, anon, authenticated, service_role;
create trigger knowledge_demo_mode_stamp
  before update or delete on private.knowledge_demo_mode
  for each row execute function private.knowledge_demo_mode_stamp();
create trigger knowledge_demo_mode_no_insert
  before insert on private.knowledge_demo_mode
  for each row execute function private.knowledge_demo_mode_stamp();
create trigger knowledge_demo_mode_no_truncate
  before truncate on private.knowledge_demo_mode
  for each statement execute function private.knowledge_m2_no_truncate();

create function private.knowledge_demo_reason(p_reason text)
returns text
language plpgsql
immutable
set search_path = ''
as $$
begin
  if p_reason is null or btrim(p_reason) = '' or length(p_reason) > 1900 then
    raise exception 'a demo approval needs a reason (1-1900 characters)' using errcode = '22023';
  end if;
  return 'DEMO - NOT EXPERT-REVIEWED: ' || p_reason;
end;
$$;
revoke all on function private.knowledge_demo_reason(text) from public, anon, authenticated, service_role;

create function private.knowledge_demo_require_enabled()
returns void
language plpgsql
set search_path = ''
as $$
begin
  if not coalesce((select m.enabled from private.knowledge_demo_mode m where m.singleton for share), false) then
    raise exception 'demo approval is switched off (private.knowledge_demo_mode); use the verified M2 flow'
      using errcode = '42501';
  end if;
end;
$$;
revoke all on function private.knowledge_demo_require_enabled() from public, anon, authenticated, service_role;

-- p_approved_by is STATED by the operator (e.g. the owner's own account), exactly as in M1.
create function private.knowledge_demo_approve_document(p_document_pk uuid, p_approved_by uuid, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_reason text := private.knowledge_demo_reason(p_reason);
  v_doc record;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  perform private.knowledge_demo_require_enabled();
  if p_approved_by is null then
    raise exception 'a demo approval names the (stated) approver account' using errcode = '22023';
  end if;
  select d.status, d.source_id into v_doc from public.knowledge_documents d where d.id = p_document_pk for update;
  if not found then
    raise exception 'knowledge document % does not exist', p_document_pk using errcode = 'P0002';
  end if;
  if v_doc.status not in ('review_required', 'expert_review') then
    raise exception 'knowledge document %: status % cannot be demo-approved', p_document_pk, v_doc.status
      using errcode = '23514';
  end if;
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  perform private.knowledge_m2_set_marker('knowledge_approval_records');
  insert into public.knowledge_approval_records (id, entity_type, source_id, document_pk, decision, assurance,
    approver_user_id, snapshot, snapshot_sha256, rationale, status_event_id)
  values (v_id, 'document', v_doc.source_id, p_document_pk, 'approve', 'demo_unverified', p_approved_by, v_snap,
          private.knowledge_snapshot_sha256(v_snap), v_reason, 0);
  perform private.knowledge_m2_set_marker(null);
  if v_doc.status = 'review_required' then
    perform private.knowledge_apply_document_transition(p_document_pk, 'review_required', 'expert_review', v_reason, null);
  end if;
  v_event := private.knowledge_apply_document_transition(p_document_pk, 'expert_review', 'approved', v_reason,
                                                         p_approved_by);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

create function private.knowledge_demo_approve_source(p_source_id text, p_approved_by uuid, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_reason text := private.knowledge_demo_reason(p_reason);
  v_status public.knowledge_status;
  v_snap jsonb;
  v_event bigint;
  v_id uuid := gen_random_uuid();
begin
  perform private.knowledge_demo_require_enabled();
  if p_approved_by is null then
    raise exception 'a demo approval names the (stated) approver account' using errcode = '22023';
  end if;
  select s.status into v_status from public.knowledge_sources s where s.source_id = p_source_id for update;
  if not found then
    raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
  end if;
  if v_status not in ('review_required', 'rejected') then
    raise exception 'knowledge source %: status % cannot be demo-approved', p_source_id, v_status
      using errcode = '23514';
  end if;
  v_snap := private.knowledge_source_snapshot(p_source_id);
  perform private.knowledge_m2_set_marker('knowledge_approval_records');
  insert into public.knowledge_approval_records (id, entity_type, source_id, decision, assurance, approver_user_id,
    snapshot, snapshot_sha256, rationale, status_event_id)
  values (v_id, 'source', p_source_id, 'approve', 'demo_unverified', p_approved_by, v_snap,
          private.knowledge_snapshot_sha256(v_snap), v_reason, 0);
  perform private.knowledge_m2_set_marker(null);
  v_event := private.knowledge_apply_source_transition(p_source_id, v_status, 'approved', v_reason, p_approved_by);
  perform private.knowledge_m2_set_marker('knowledge_approval_records.status_event');
  update public.knowledge_approval_records set status_event_id = v_event where id = v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

-- Go-live: quarantine (fail closed, one-way) every approved version and source whose CURRENT approval
-- is a demo record. Works with the switch on or off. Returns how many rows it quarantined.
create function private.knowledge_demo_quarantine_all(p_reason text)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_reason text := private.knowledge_demo_reason(p_reason);
  v_row record;
  v_count integer := 0;
begin
  for v_row in
    select d.id from public.knowledge_documents d
     where d.status = 'approved' and exists (
       select 1 from public.knowledge_approval_records a
        where a.document_pk = d.id and a.assurance = 'demo_unverified' and a.approver_user_id = d.approved_by)
     order by d.id for update of d
  loop
    perform private.knowledge_apply_document_transition(v_row.id, 'approved', 'quarantined', v_reason, null);
    v_count := v_count + 1;
  end loop;
  for v_row in
    select s.source_id from public.knowledge_sources s
     where s.status = 'approved' and exists (
       select 1 from public.knowledge_approval_records a
        where a.entity_type = 'source' and a.source_id = s.source_id and a.assurance = 'demo_unverified')
     order by s.source_id for update of s
  loop
    perform private.knowledge_apply_source_transition(v_row.source_id, 'approved', 'quarantined', v_reason, null);
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;

revoke all on function private.knowledge_demo_approve_document(uuid, uuid, text) from public, anon, authenticated, service_role;
revoke all on function private.knowledge_demo_approve_source(text, uuid, text) from public, anon, authenticated, service_role;
revoke all on function private.knowledge_demo_quarantine_all(text) from public, anon, authenticated, service_role;
grant execute on function private.knowledge_demo_approve_document(uuid, uuid, text) to service_role;
grant execute on function private.knowledge_demo_approve_source(text, uuid, text) to service_role;
grant execute on function private.knowledge_demo_quarantine_all(text) to service_role;

-- ================================================================== RPC privileges

do $grants$
declare
  v_fn text;
begin
  foreach v_fn in array array[
    'public.knowledge_register_personnel(uuid, text, text, text, text, uuid)',
    'public.knowledge_grant_personnel_role(uuid, text, text, uuid, text, text, text, timestamptz)',
    'public.knowledge_set_personnel_status(uuid, text, text)',
    'public.knowledge_set_personnel_role_status(uuid, text, text)',
    'public.knowledge_attest_document_upload(uuid, text, text, text)',
    'public.knowledge_attest_source_upload(text, text)',
    'public.knowledge_start_expert_review(uuid, text, text)',
    'public.knowledge_submit_expert_review(uuid, text, text, jsonb, jsonb, jsonb, text)',
    'public.knowledge_decide_document(uuid, text, text, text)',
    'public.knowledge_approve_source(text, text, text)',
    'public.knowledge_cancel_expert_review(uuid, text)'] loop
    execute 'revoke all on function ' || v_fn || ' from public, anon, authenticated, service_role';
    execute 'grant execute on function ' || v_fn || ' to authenticated';
  end loop;
end;
$grants$;
