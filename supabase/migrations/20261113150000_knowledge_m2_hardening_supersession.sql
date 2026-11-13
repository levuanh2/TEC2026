-- RAG V1.5 M2 hardening H-c (docs/rag/RAG_V15_H_C_SUPERSESSION_AUTHORITY.md): cross-source supersession
-- needs a countersignature by a custodian of the TARGET source. LOCAL/CI ONLY until the owner approves a
-- hosted migration. dev3-01 stays OPEN.
-- Depends on M2 (20261110120000), M3 (20261111090000), H-a (20261113090000), H-b (20261113120000).
--
-- Owner decision D-H4 (2026-11-12): option C, target-source custodian countersignature.
--
-- What it adds
--   * public.knowledge_publishers: verified publisher identities, registered by a registry admin with
--     identity evidence (not the free-text knowledge_sources.owner). Status active -> suspended ->
--     revoked like every registry row.
--   * public.knowledge_source_publishers: one immutable binding source -> publisher, by a registry admin,
--     with ownership evidence.
--   * public.knowledge_source_custodians: a person (M2 personnel) who answers for ONE source, granted by
--     a registry admin; never to themselves; only for a source bound to an active publisher.
--   * public.knowledge_supersession_authorizations: the countersignature. An aal2 custodian of the
--     target source states that THIS successor version may retire THIS target version, bound to both
--     snapshot hashes and to the target's publisher binding. Append-only.
--   * private.knowledge_check_cross_source_supersession (replaced): the M3 rules (approved replacing
--     source, the reviewer's recorded authority) AND a valid countersignature, checked when the
--     reviewer recommends approval and again at the final approval:
--       - the target and successor snapshots are unchanged since the countersignature (stale refused);
--       - the custodian assignment, its person and the target's publisher are still active, and the
--         target is still bound to the same publisher;
--       - the custodian is not the successor's uploader, any of its reviewers, nor the person deciding
--         now (reviewer at submission, approver at approval), by canonical identity.
--     No valid countersignature: the old guidance cannot be superseded through this workflow. It can
--     still be quarantined by the emergency procedure (H-b).
--   * Unchanged: same-source supersession (no countersignature), the rule that a demo approval never
--     supersedes a version of another source (M3 private.knowledge_supersede_for).
--
-- What it does NOT claim
--   * The countersignature is an authenticated database act (aal2 session, active registry assignment,
--     bound hashes), not a cryptographic signature. A non-empty reference string proves nothing and is
--     no longer enough on its own.
--   * Publisher identity evidence is what the registry admin checked; the database records it, it does
--     not verify the outside world.
--   * The database owner / superuser boundary of M1/M2 is unchanged.

-- ================================================================== registry tables

create table public.knowledge_publishers (
  id uuid primary key default gen_random_uuid(),
  publisher_key text not null,
  legal_name text not null,
  identity_evidence text not null,
  registered_by_user_id uuid not null,
  registered_at timestamptz not null default now(),
  status text not null default 'active',
  status_changed_at timestamptz,
  status_changed_by uuid,
  status_reason text,
  constraint knowledge_publishers_key_chk check (publisher_key ~ '^[a-z0-9][a-z0-9._-]{2,79}$'),
  constraint knowledge_publishers_name_chk check (length(btrim(legal_name)) between 3 and 300),
  constraint knowledge_publishers_evidence_chk check (length(btrim(identity_evidence)) between 10 and 2000),
  constraint knowledge_publishers_status_chk check (status in ('active', 'suspended', 'revoked'))
);
create unique index knowledge_publishers_key_uidx on public.knowledge_publishers (publisher_key);

create table public.knowledge_source_publishers (
  source_id text primary key references public.knowledge_sources (source_id),
  publisher_id uuid not null references public.knowledge_publishers (id),
  ownership_evidence text not null,
  bound_by_user_id uuid not null,
  bound_at timestamptz not null default now(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  constraint knowledge_source_publishers_evidence_chk check (length(btrim(ownership_evidence)) between 10 and 2000)
);

create table public.knowledge_source_custodians (
  id uuid primary key default gen_random_uuid(),
  personnel_id uuid not null references public.knowledge_personnel (id),
  source_id text not null references public.knowledge_sources (source_id),
  publisher_id uuid not null references public.knowledge_publishers (id),
  evidence text not null,
  granted_by_user_id uuid not null,
  granted_at timestamptz not null default now(),
  status text not null default 'active',
  status_changed_at timestamptz,
  status_changed_by uuid,
  status_reason text,
  constraint knowledge_source_custodians_evidence_chk check (length(btrim(evidence)) between 10 and 2000),
  constraint knowledge_source_custodians_status_chk check (status in ('active', 'suspended', 'revoked'))
);
create unique index knowledge_source_custodians_active_uidx on public.knowledge_source_custodians (personnel_id, source_id)
  where status <> 'revoked';

create table public.knowledge_supersession_authorizations (
  id uuid primary key default gen_random_uuid(),
  recorded_at timestamptz not null default now(),
  recorded_xact xid8 not null default pg_catalog.pg_current_xact_id(),
  target_document_pk uuid not null references public.knowledge_documents (id),
  target_source_id text not null,
  target_snapshot_sha256 text not null,
  successor_document_pk uuid not null references public.knowledge_documents (id),
  successor_source_id text not null,
  successor_snapshot_sha256 text not null,
  publisher_id uuid not null references public.knowledge_publishers (id),
  custodian_id uuid not null references public.knowledge_source_custodians (id),
  custodian_personnel_id uuid not null references public.knowledge_personnel (id),
  custodian_user_id uuid not null,
  custodian_session_id uuid not null,
  statement text not null,
  constraint knowledge_supersession_authorizations_sha_chk check (
    target_snapshot_sha256 ~ '^[0-9a-f]{64}$' and successor_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  constraint knowledge_supersession_authorizations_cross_chk check (target_source_id <> successor_source_id),
  constraint knowledge_supersession_authorizations_statement_chk check (length(btrim(statement)) between 20 and 2000)
);
create index knowledge_supersession_authorizations_pair_idx
  on public.knowledge_supersession_authorizations (successor_document_pk, target_document_pk);

alter table public.knowledge_publishers enable row level security;
alter table public.knowledge_source_publishers enable row level security;
alter table public.knowledge_source_custodians enable row level security;
alter table public.knowledge_supersession_authorizations enable row level security;
revoke all on public.knowledge_publishers, public.knowledge_source_publishers, public.knowledge_source_custodians,
  public.knowledge_supersession_authorizations from public, anon, authenticated, service_role;
grant select on public.knowledge_publishers, public.knowledge_source_publishers, public.knowledge_source_custodians,
  public.knowledge_supersession_authorizations to service_role;

-- registry rows: the M2 registry guard (written only by the RPCs; afterwards only status changes)
create trigger knowledge_publishers_guard
  before insert or update or delete on public.knowledge_publishers
  for each row execute function private.knowledge_personnel_guard();
create trigger knowledge_publishers_no_truncate
  before truncate on public.knowledge_publishers
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_source_custodians_guard
  before insert or update or delete on public.knowledge_source_custodians
  for each row execute function private.knowledge_personnel_guard();
create trigger knowledge_source_custodians_no_truncate
  before truncate on public.knowledge_source_custodians
  for each statement execute function private.knowledge_m2_no_truncate();
-- bindings and countersignatures: the M2 evidence guard (INSERT inside the RPC only, then immutable)
create trigger knowledge_source_publishers_guard
  before insert or update or delete on public.knowledge_source_publishers
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_source_publishers_no_truncate
  before truncate on public.knowledge_source_publishers
  for each statement execute function private.knowledge_m2_no_truncate();
create trigger knowledge_supersession_authorizations_guard
  before insert or update or delete on public.knowledge_supersession_authorizations
  for each row execute function private.knowledge_evidence_guard();
create trigger knowledge_supersession_authorizations_no_truncate
  before truncate on public.knowledge_supersession_authorizations
  for each statement execute function private.knowledge_m2_no_truncate();

-- ================================================================== registry RPCs (registry admin, aal2)

create function public.knowledge_register_publisher(p_publisher_key text, p_legal_name text, p_identity_evidence text)
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
  if p_publisher_key is null or pg_catalog.lower(pg_catalog.btrim(p_publisher_key)) !~ '^[a-z0-9][a-z0-9._-]{2,79}$'
     or p_legal_name is null or length(btrim(p_legal_name)) not between 3 and 300
     or p_identity_evidence is null or length(btrim(p_identity_evidence)) not between 10 and 2000 then
    raise exception 'a publisher needs a key ([a-z0-9._-], 3-80), a legal name and identity evidence (10-2000)'
      using errcode = '22023';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_publishers');
  insert into public.knowledge_publishers (publisher_key, legal_name, identity_evidence, registered_by_user_id)
  values (pg_catalog.lower(pg_catalog.btrim(p_publisher_key)), pg_catalog.btrim(p_legal_name),
          pg_catalog.btrim(p_identity_evidence), v_admin.user_id)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

create function public.knowledge_set_publisher_status(p_publisher_id uuid, p_status text, p_reason text)
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
  perform private.knowledge_m2_set_marker('knowledge_publishers');
  update public.knowledge_publishers
     set status = p_status, status_changed_at = pg_catalog.now(), status_changed_by = v_admin.user_id,
         status_reason = p_reason
   where id = p_publisher_id;
  perform private.knowledge_m2_set_marker(null);
  if not found then
    raise exception 'publisher % does not exist', p_publisher_id using errcode = 'P0002';
  end if;
end;
$$;

create function public.knowledge_bind_source_publisher(p_source_id text, p_publisher_id uuid, p_ownership_evidence text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
begin
  select a.user_id into v_admin from private.knowledge_registry_admin_actor() a;
  if p_ownership_evidence is null or length(btrim(p_ownership_evidence)) not between 10 and 2000 then
    raise exception 'a source-publisher binding needs ownership evidence (10-2000 characters)' using errcode = '22023';
  end if;
  if not exists (select 1 from public.knowledge_publishers p where p.id = p_publisher_id and p.status = 'active') then
    raise exception 'publisher % is not an active verified publisher', p_publisher_id using errcode = '23514';
  end if;
  if not exists (select 1 from public.knowledge_sources s where s.source_id = p_source_id) then
    raise exception 'knowledge source % does not exist', p_source_id using errcode = 'P0002';
  end if;
  if exists (select 1 from public.knowledge_source_publishers b where b.source_id = p_source_id) then
    raise exception 'knowledge source %: its publisher binding is immutable (register a new source instead)',
      p_source_id using errcode = '23514';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_source_publishers');
  insert into public.knowledge_source_publishers (source_id, publisher_id, ownership_evidence, bound_by_user_id)
  values (p_source_id, p_publisher_id, pg_catalog.btrim(p_ownership_evidence), v_admin.user_id);
  perform private.knowledge_m2_set_marker(null);
end;
$$;

create function public.knowledge_grant_source_custodian(p_personnel_id uuid, p_source_id text, p_evidence text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_admin record;
  v_publisher uuid;
  v_id uuid;
begin
  select a.user_id into v_admin from private.knowledge_registry_admin_actor() a;
  if p_evidence is null or length(btrim(p_evidence)) not between 10 and 2000 then
    raise exception 'a custodian assignment needs evidence (10-2000 characters)' using errcode = '22023';
  end if;
  if not exists (select 1 from public.knowledge_personnel p where p.id = p_personnel_id and p.status = 'active') then
    raise exception 'personnel % is not active', p_personnel_id using errcode = '23514';
  end if;
  if exists (select 1 from public.knowledge_personnel p where p.id = p_personnel_id and p.auth_user_id = v_admin.user_id) then
    raise exception 'a registry admin never makes themselves a source custodian' using errcode = '42501';
  end if;
  select b.publisher_id into v_publisher
    from public.knowledge_source_publishers b join public.knowledge_publishers p on p.id = b.publisher_id
   where b.source_id = p_source_id and p.status = 'active';
  if v_publisher is null then
    raise exception 'knowledge source % is not bound to an active verified publisher', p_source_id using errcode = '23514';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_source_custodians');
  insert into public.knowledge_source_custodians (personnel_id, source_id, publisher_id, evidence, granted_by_user_id)
  values (p_personnel_id, p_source_id, v_publisher, pg_catalog.btrim(p_evidence), v_admin.user_id)
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

create function public.knowledge_set_source_custodian_status(p_custodian_id uuid, p_status text, p_reason text)
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
  perform private.knowledge_m2_set_marker('knowledge_source_custodians');
  update public.knowledge_source_custodians
     set status = p_status, status_changed_at = pg_catalog.now(), status_changed_by = v_admin.user_id,
         status_reason = p_reason
   where id = p_custodian_id;
  perform private.knowledge_m2_set_marker(null);
  if not found then
    raise exception 'custodian assignment % does not exist', p_custodian_id using errcode = 'P0002';
  end if;
end;
$$;

-- ================================================================== independence

-- The personnel records whose humans must not countersign a replacement of p_successor: its uploaders,
-- its reviewers and (when signed in) the caller.
create function private.knowledge_supersession_conflicts(p_successor uuid, p_caller uuid)
returns uuid[]
language sql
stable
set search_path = ''
as $$
  select coalesce(pg_catalog.array_agg(x.id), '{}') from (
    select u.uploader_personnel_id as id from public.knowledge_upload_attestations u where u.document_pk = p_successor
    union select r.reviewer_personnel_id from public.knowledge_expert_reviews r where r.document_pk = p_successor
    union select p.id from public.knowledge_personnel p where p_caller is not null and p.auth_user_id = p_caller) x;
$$;

-- ================================================================== countersignature

create function public.knowledge_countersign_supersession(
  p_successor_document_pk uuid, p_successor_snapshot_sha256 text, p_target_snapshot_sha256 text, p_statement text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_succ record;
  v_target record;
  v_cust record;
  v_id uuid;
begin
  select a.user_id, a.session_id into v_actor from private.knowledge_verified_actor() a;
  if p_statement is null or length(btrim(p_statement)) not between 20 and 2000 then
    raise exception 'a countersignature needs a statement (20-2000 characters)' using errcode = '22023';
  end if;
  select d.id, d.source_id, d.status, d.supersedes_document_pk into v_succ
    from public.knowledge_documents d where d.id = p_successor_document_pk for share;
  if v_succ.id is not null then
    select t.id, t.source_id into v_target from public.knowledge_documents t
     where t.id = v_succ.supersedes_document_pk for share;
  end if;
  -- the caller must hold an active custodian assignment for the target's source; anything else (no
  -- successor, no link, same source, no assignment) gets one answer: no existence oracle
  select c.id, c.personnel_id, c.publisher_id into v_cust
    from public.knowledge_source_custodians c
    join public.knowledge_personnel p on p.id = c.personnel_id
    join public.knowledge_source_publishers b on b.source_id = c.source_id and b.publisher_id = c.publisher_id
    join public.knowledge_publishers pub on pub.id = c.publisher_id
   where v_target.id is not null and v_target.source_id <> v_succ.source_id
     and c.source_id = v_target.source_id and c.status = 'active' and p.status = 'active'
     and p.auth_user_id = v_actor.user_id and pub.status = 'active'
   limit 1
   for share of c, p, b, pub;
  if v_cust.id is null then
    raise exception 'countersignature not available: you are not an active custodian of the superseded source'
      using errcode = '42501';
  end if;
  if v_succ.status not in ('review_required', 'expert_review') then
    raise exception 'knowledge document %: status is %; only a version still under review is countersigned',
      p_successor_document_pk, v_succ.status using errcode = '23514';
  end if;
  if private.knowledge_same_person(v_cust.personnel_id,
                                   private.knowledge_supersession_conflicts(p_successor_document_pk, null)) then
    raise exception 'separation of duties: the custodian is the uploader or a reviewer of the replacing version'
      using errcode = '42501';
  end if;
  if p_successor_snapshot_sha256 is distinct from
       private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(p_successor_document_pk))
     or p_target_snapshot_sha256 is distinct from
       private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(v_target.id)) then
    raise exception 'the replacing or the superseded version changed since you read it (stale hash)' using errcode = '40001';
  end if;
  perform private.knowledge_m2_set_marker('knowledge_supersession_authorizations');
  insert into public.knowledge_supersession_authorizations
    (target_document_pk, target_source_id, target_snapshot_sha256, successor_document_pk, successor_source_id,
     successor_snapshot_sha256, publisher_id, custodian_id, custodian_personnel_id, custodian_user_id,
     custodian_session_id, statement)
  values (v_target.id, v_target.source_id, p_target_snapshot_sha256, p_successor_document_pk, v_succ.source_id,
          p_successor_snapshot_sha256, v_cust.publisher_id, v_cust.id, v_cust.personnel_id, v_actor.user_id,
          v_actor.session_id, pg_catalog.btrim(p_statement))
  returning id into v_id;
  perform private.knowledge_m2_set_marker(null);
  return v_id;
end;
$$;

-- A custodian reads the hash of the superseded version they countersign (the M2 wrapper does not
-- answer a custodian, who may hold no visibility-scoped role).
create function public.knowledge_custodian_snapshot(p_document_pk uuid)
returns table (snapshot jsonb, snapshot_sha256 text)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_actor record;
  v_snap jsonb;
begin
  select a.user_id into v_actor from private.knowledge_verified_actor() a;
  -- the version itself, or the version it supersedes, must belong to a source the caller is custodian of
  if not exists (
      select 1 from public.knowledge_documents d
        join public.knowledge_source_custodians c on c.status = 'active'
        join public.knowledge_personnel p on p.id = c.personnel_id and p.status = 'active' and p.auth_user_id = v_actor.user_id
        left join public.knowledge_documents t on t.id = d.supersedes_document_pk
       where d.id = p_document_pk and (c.source_id = d.source_id or c.source_id = t.source_id)) then
    raise exception 'not available for your custodian assignment' using errcode = '42501';
  end if;
  v_snap := private.knowledge_document_snapshot(p_document_pk);
  return query select v_snap, private.knowledge_snapshot_sha256(v_snap);
end;
$$;

-- ================================================================== the check (replaced)

-- M3 rules unchanged, plus a valid countersignature (see the header). Called by the reviewer's
-- recommendation and by the approval, so the caller is the person deciding now. VOLATILE (M3: stable):
-- it share-locks the custodian, person, binding and publisher rows it relies on, so a concurrent
-- revocation or suspension either commits first (and is seen: the approval is refused) or waits for
-- this transaction to end (the approval was valid when it committed). Never both.
create or replace function private.knowledge_check_cross_source_supersession(p_document_pk uuid, p_sources_checked jsonb)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_doc record;
  v_target_source text;
  v_ok boolean;
begin
  select d.source_id, d.supersedes_document_pk, s.status as source_status into v_doc
    from public.knowledge_documents d join public.knowledge_sources s on s.source_id = d.source_id
   where d.id = p_document_pk;
  if v_doc.supersedes_document_pk is null then
    return;
  end if;
  select t.source_id into v_target_source from public.knowledge_documents t
   where t.id = v_doc.supersedes_document_pk;
  if v_target_source = v_doc.source_id then
    return;
  end if;
  if v_doc.source_status is distinct from 'approved' then
    raise exception 'knowledge document %: its source % is %, not approved; it cannot supersede a version of'
      ' another source (%)', p_document_pk, v_doc.source_id, v_doc.source_status, v_target_source
      using errcode = '23514';
  end if;
  if not exists (
      select 1 from pg_catalog.jsonb_array_elements(
                      case when pg_catalog.jsonb_typeof(p_sources_checked) = 'array' then p_sources_checked
                           else '[]'::jsonb end) e
       where pg_catalog.jsonb_typeof(e) = 'object'
         and e ->> 'purpose' = 'cross_source_supersession_authority'
         and e ->> 'supersedes_document_pk' = v_doc.supersedes_document_pk::text
         and pg_catalog.btrim(coalesce(e ->> 'reference', '')) <> '') then
    raise exception 'knowledge document %: it supersedes a version of another source (%); the expert review'
      ' must record the authority for exactly this replacement (sources_checked: purpose'
      ' cross_source_supersession_authority, supersedes_document_pk %, reference)',
      p_document_pk, v_target_source, v_doc.supersedes_document_pk using errcode = '23514';
  end if;
  -- H-c (D-H4): a custodian of the target source countersigned exactly this replacement, of exactly
  -- this content, and nothing it relied on has changed since
  select true into v_ok
    from public.knowledge_supersession_authorizations a
    join public.knowledge_source_custodians c on c.id = a.custodian_id and c.status = 'active'
    join public.knowledge_personnel p on p.id = a.custodian_personnel_id and p.status = 'active'
    join public.knowledge_source_publishers b on b.source_id = a.target_source_id and b.publisher_id = a.publisher_id
    join public.knowledge_publishers pub on pub.id = a.publisher_id and pub.status = 'active'
   where a.successor_document_pk = p_document_pk and a.target_document_pk = v_doc.supersedes_document_pk
     and a.target_source_id = v_target_source and c.source_id = v_target_source
     and a.successor_snapshot_sha256 = private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(p_document_pk))
     and a.target_snapshot_sha256
         = private.knowledge_snapshot_sha256(private.knowledge_document_snapshot(v_doc.supersedes_document_pk))
     and not private.knowledge_same_person(a.custodian_personnel_id,
                                           private.knowledge_supersession_conflicts(p_document_pk, auth.uid()))
   order by a.recorded_at desc
   limit 1
   for share of c, p, b, pub;
  if v_ok is null then
    raise exception 'knowledge document %: it supersedes a version of another source (%); that needs a current'
      ' countersignature by an independent, active custodian of % (public.knowledge_countersign_supersession).'
      ' Without it the old guidance cannot be superseded here; it can still be quarantined (H-b)',
      p_document_pk, v_target_source, v_target_source using errcode = '23514';
  end if;
end;
$$;

-- ================================================================== grants

do $grants$
declare
  f text;
begin
  foreach f in array array[
    'public.knowledge_register_publisher(text, text, text)',
    'public.knowledge_set_publisher_status(uuid, text, text)',
    'public.knowledge_bind_source_publisher(text, uuid, text)',
    'public.knowledge_grant_source_custodian(uuid, text, text)',
    'public.knowledge_set_source_custodian_status(uuid, text, text)',
    'public.knowledge_countersign_supersession(uuid, text, text, text)',
    'public.knowledge_custodian_snapshot(uuid)']
  loop
    execute pg_catalog.format('revoke all on function %s from public, anon, authenticated, service_role', f);
    execute pg_catalog.format('grant execute on function %s to authenticated', f);
  end loop;
end;
$grants$;
revoke all on function private.knowledge_supersession_conflicts(uuid, uuid) from public, anon, authenticated, service_role;
