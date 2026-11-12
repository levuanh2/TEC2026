# RAG V1.5 M2 — Verified expert approval (2026-11-10, local/CI only)

Migration `supabase/migrations/20261110120000_knowledge_verified_expert_approval_m2.sql`, rollback
`supabase/rollbacks/20261110120000_knowledge_verified_expert_approval_m2.down.sql`. **Not applied to
hosted Supabase.** Owner decision: Option A (Supabase Auth identity, aal2, owner-managed personnel
registry, authenticated PostgreSQL RPCs, verified roles, immutable evidence, separation of duties).

**What M2 proves and what it does not.** M2 makes every review and approval decision attributable to a
verified, registered, distinct human, bound to the exact content and metadata that human reviewed. It
does **not** prove that the content is correct. **dev3-01 stays OPEN.** The characterization test
`test_rag_source_integrity_gap.py` is not flipped (M7).

## 1. Identity

Every M2 RPC first calls `private.knowledge_verified_actor()`. It refuses (42501) unless all of these hold:

| Check | Source |
|---|---|
| the caller's role is `authenticated` | `current_setting('role')`, what PostgREST sets from the verified JWT |
| the JWT claim `role` is `authenticated` and `sub` is set | `auth.jwt()`, `auth.uid()` |
| the JWT claim `aal` is `aal2` and `exp` is in the future | `auth.jwt()` |
| `session_id` names a live `auth.sessions` row **of this user** with `aal = aal2` | Auth's own table |
| the user has a `verified` `auth.mfa_factors` row | Auth's own table |
| the user is not deleted, banned or anonymous, and has no pending forced password change | `auth.users`, `private.password_change_pending()` |

No RPC takes the caller's identity as a parameter. The FastAPI pooled path sets only `{sub, role}`, so
it can never pass (fail closed): human decisions go through PostgREST with the person's own access token.
`service_role` is not a member of `authenticated` and cannot log in, so the backend key can never act as a person.

Professional qualification is **not** inferred from MFA or from having an account. It comes only from
the registry.

## 2. Registry (owner-managed)

| Table | Purpose |
|---|---|
| `knowledge_registry_admins` | Trust root: who may verify personnel. Written **only by the database owner**. Insert active, revoke once. |
| `knowledge_personnel` | One verified human per row. One Auth account per row (`auth_user_id` unique). `identity_reference` is the verifier's de-duplication handle (a staff or registry number, not a national ID); live rows are unique by it, case-insensitive. Also holds identity method + evidence, organization, `verified_by` (an admin, never the person), and status (`active`/`suspended`/`revoked`, revoked is terminal). |
| `knowledge_personnel_roles` | `uploader` / `expert_reviewer` / `approver` per scope (`public`, or `tenant` + organization), with qualification category, method and evidence, validity window, `verified_by`, and status. |

Registry RPCs, callable by an active registry admin with an aal2 session:
`knowledge_register_personnel`, `knowledge_grant_personnel_role`, `knowledge_set_personnel_status`,
`knowledge_set_personnel_role_status`. An admin never registers, grants or changes their own record.
After the insert only the status fields change (re-register for new facts). Nothing is ever deleted.

Without onboarded personnel, every review and approval fails closed.

## 3. Flow and RPC contracts (all `public`, SECURITY DEFINER, `search_path ''`, static SQL, EXECUTE `authenticated` only)

```
uploader   knowledge_attest_document_upload(document_pk, file_sha256, normalized_sha256, statement) -> attestation id
           knowledge_attest_source_upload(source_id, statement) -> attestation id
reviewer   knowledge_start_expert_review(document_pk, file_sha256, reason) -> review id
               review_required -> expert_review; freezes the snapshot
           knowledge_submit_expert_review(review_id, decision, snapshot_sha256, checklist, sources_checked, findings, rationale)
               decision recommend_approval (status unchanged) | reject (-> rejected) | return (-> review_required)
approver   knowledge_decide_document(review_id, decision approve|reject, snapshot_sha256, rationale) -> approval record id
               expert_review -> approved | rejected
           knowledge_approve_source(source_id, snapshot_sha256, rationale) -> approval record id
               review_required | rejected -> approved (sources keep their flow: no expert_review)
any role   knowledge_review_snapshot(document_pk | source_id) -> (snapshot, snapshot_sha256)
               only for a caller holding a knowledge role in that scope
```

Refusals: 42501 for identity, role, scope or separation-of-duties failures (an out-of-scope row looks
exactly like a missing one); 23514 for a wrong state, stale or changed content, or an open blocking
finding; 22023 for malformed evidence. A refusal writes nothing.

**Separation of duties.** uploader ≠ expert reviewer ≠ approver, compared by personnel id, auth user
id **and** `identity_reference` (case-insensitive, including revoked records). One human with a second
account is still one human. Several accounts or AI agents are not distinct humans. The registry admin
must verify that each record is a different person.

**Approval preconditions** (`knowledge_decide_document`, decision `approve`):
- the caller is a verified approver in scope, distinct from the uploader and the reviewer;
- the review is the version's current one, its decision is `recommend_approval`, and it is not decided yet;
- the reviewer's person and role are still active and valid (row-share-locked against concurrent suspension);
- the evidence is re-validated: complete checklist, at least one checked source, no open blocking finding;
- the version's current snapshot (document, source and chunk manifest) equals the reviewed snapshot,
  and the approver confirms the same hash.

Then, in one transaction: the approval record, the audited M1 transition with
`approved_by = auth.uid()`, and the event id linked into the record.

## 4. Evidence (immutable: no UPDATE, DELETE or TRUNCATE, even by the owner)

| Table | Bound to |
|---|---|
| `knowledge_upload_attestations` | version or source; file + normalized SHA-256; uploader personnel/role/user/session; statement |
| `knowledge_expert_reviews` | version (source_id, document_id, document_version); attestation; reviewer personnel/role/user/session; qualification category; **snapshot** jsonb + SHA-256; start event; then once: decision, checklist (6 required booleans), sources_checked, findings (kind, severity, status, resolution), rationale, decision session, decision event |
| `knowledge_approval_records` | review (unique) or source; attestation; decision; `assurance` (`verified` / `demo_unverified`); approver personnel/role/user/session; snapshot + SHA-256 at decision time; rationale; status event |

The snapshot (`private.knowledge_document_snapshot`) covers the version's identity, provenance,
`artifact_ref`, file/normalized hashes, license, pipeline versions, the source's identity, scope and
provenance, and a manifest hash of the chunks. **Freeze:** from `expert_review` on, the version's
decision metadata (title, language, official_url, artifact_ref, published_at, license basis/reference)
cannot change (23514); chunks were already frozen by M1. Source metadata is not frozen (sources have
their own flow), but any change makes the snapshot differ, and both submission and approval are refused.
The approver can still reject. Evidence is never reused: a returned or rejected review is closed, each
review belongs to one version, and each review gets one decision.

The row triggers enforce the same rules for any writer. Entering `expert_review` needs this
transaction's new review row, and entering `approved` needs this transaction's approve record. A forged
M1 marker alone therefore no longer starts a review or approves anything.

## 5. Operator path after M2

`private.knowledge_transition_source/_document` (service_role) still do triage and fail-closed moves:
reject, re-open after rejection, `expert_review -> rejected` (abandon a review), quarantine and archive.
They refuse the transitions M2 owns, after their M1 argument and staleness checks: document
`-> expert_review`, `-> approved`, `expert_review -> review_required`, and source `-> approved` (42501).
This applies to the owner login too.

## 6. Demo approvals (owner decision 2026-11-10)

The system is still in testing, and demos need approved documents before experts are onboarded. The
owner chose a demo path that cannot be mistaken for a verified approval:

- `private.knowledge_demo_mode` is a single row, **off by default**. Only the database owner can change
  it, and turning it on needs `environment_label` in `local | ci | demo | staging` plus a note.
- `private.knowledge_demo_approve_document(document_pk, approved_by, reason)` and
  `private.knowledge_demo_approve_source(source_id, approved_by, reason)` (EXECUTE service_role only)
  work only while the switch is on. They write an approval record with `assurance = 'demo_unverified'`
  (no review, no personnel; `approved_by` is **stated**, as in M1). Every review note and audit reason
  starts with `DEMO - NOT EXPERT-REVIEWED: `. The same transitions, approval CHECKs (license, ST1, ST1.1)
  and the one-approved-version rule apply. Demo-approved content **is retrievable**; that is the point.
- `private.knowledge_demo_quarantine_all(reason)` quarantines every version and source whose current
  approval is a demo record, whatever the switch says. That is the go-live step, and it is one-way (D1).

```sql
-- owner login, a NON-production database only
update private.knowledge_demo_mode set enabled = true, environment_label = 'demo', note = 'cooperative demo, 2026-11';
select private.knowledge_demo_approve_source(:source_id, :owner_auth_uuid, 'demo corpus');
select private.knowledge_demo_approve_document(:doc_id, :owner_auth_uuid, 'demo corpus');
-- before production
select private.knowledge_demo_quarantine_all('go-live: demo approvals withdrawn');
update private.knowledge_demo_mode set enabled = false, environment_label = null, note = null;
-- list what is demo-approved
select entity_type, source_id, document_pk, decided_at from public.knowledge_approval_records
 where assurance = 'demo_unverified' order by decided_at;
```

## 7. Runbook: onboarding real personnel (owner)

1. Enable MFA (TOTP) in Supabase Auth for the environment. It is off in `supabase/config.toml`
   (`[auth.mfa.totp]`), so locally nobody can reach aal2 and every M2 RPC fails closed until it is on.
2. Each person creates their own account and enrols TOTP.
3. Owner login: `insert into public.knowledge_registry_admins (auth_user_id, note) values (:admin_uuid, :why);`
   (the admin should not also be a reviewer or approver of the same documents).
4. The registry admin (aal2 session) calls `knowledge_register_personnel` and
   `knowledge_grant_personnel_role` for each person, with the real verification method and evidence
   reference. Never register fictional people or invent evidence.
5. From then on, uploader → reviewer → approver use the RPCs with their own sessions (e.g. supabase-js
   `rpc(...)` after `auth.mfa.challengeAndVerify`).

## 8. Trust boundary and remaining limitations

- The database owner (`postgres`) and PostgREST's `authenticator` login can `SET ROLE authenticated`
  and set `request.jwt.claims`. The owner can also insert `auth.sessions` rows, set the M2 write
  markers, disable triggers or drop these objects. M2 removes every **routine** owner/operator approval
  path, but it cannot make a superuser-equivalent login unable to rewrite its own database. Protect
  those credentials; they are infrastructure.
- The registry is only as good as the registry admins' verification. A sole owner who registers
  sock-puppet accounts defeats separation of duties. That is a governance control, not a technical one.
- No UI/API for reviewers to list their queue or read non-approved drafts (RLS stays approved-only).
  They need an out-of-band artifact channel or a later read RPC.
- An approved version is replaced in two steps: an operator archives or quarantines the old one, then
  the approver approves the new one. Retrieval is briefly fail-closed in between. M3 `supersedes` can
  make this atomic.
- Effective dates, expiry and supersession are M3. Claims, contradictions and the reference registry are M4/M5.
- A registered person's Auth account cannot be deleted (evidence and registry rows reference it,
  `on delete restrict`): revoke the personnel record instead. GoTrue's admin delete then fails.
- Demo approvals exist only while the owner switch is on, but once made they are retrievable until quarantined.
