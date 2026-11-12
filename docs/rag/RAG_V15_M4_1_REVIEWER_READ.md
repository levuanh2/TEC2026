# RAG V1.5 M4.1: reviewer read access to claims and contradiction candidates

Status: **implemented, local and CI only (2026-11-12).** Migration
`supabase/migrations/20261112120000_knowledge_review_read_m4_1.sql`, rollback
`supabase/rollbacks/20261112120000_knowledge_review_read_m4_1.down.sql`. Not applied to hosted; a
hosted migration needs an owner decision. Depends on M2, M3 and M4. dev3-01 stays OPEN.

The design it follows is `RAG_V15_M4_REVIEWER_READ_DESIGN.md` (PR #59). This file records what was
built and where it differs.

## 1. What it is

One read-only RPC, `public.knowledge_review_claims(p_document_pk uuid) returns jsonb`, for a
verified expert reviewer or approver. It returns the M4 claims of one document version and the
contradiction candidates in which one of those claims takes part.

It is **non-blocking**. It changes no knowledge status, approves and rejects nothing, quarantines
nothing, and no review or approval depends on it. A stored candidate stays a reviewer aid until a
separate blocking policy is designed, reviewed and approved. The response, every claim and every
candidate carry `"assurance": "unverified_analysis"`, and the response has a fixed notice saying so.

## 2. Access

| Check | How |
|---|---|
| Supabase Auth identity, active `aal2` session | `private.knowledge_verified_actor()` (M2): role `authenticated`, JWT at `aal2`, a live aal2 `auth.sessions` row, a verified MFA factor, not banned, deleted or anonymous, no pending password change. The identity is `auth.uid()`; the RPC takes no identity parameter. |
| Active `expert_reviewer` or `approver` role | `private.knowledge_actor_role` (M2): the role and the person are active and inside the role's validity window. |
| Scope | The role's scope must equal the scope of the requested version's source: same visibility, and for a tenant source the same organization. |

Uploaders, registry admins, tenants, `anon`, `service_role` and the database owner get nothing. The
function is `SECURITY DEFINER` with `search_path = ''`, static SQL, `EXECUTE` for `authenticated`
only. It takes one uuid and no table, column, filter or SQL fragment, so it is not a service-role
pass-through.

**Farm scope.** M2 roles are scoped per visibility and organization, not per farm. A reviewer of an
organization reads the claims of every farm of that organization. M4.1 does not widen that boundary
and does not narrow it; farm-level reviewer roles would be a change to the M2 registry.

## 3. Disclosure

Returned: the claims of the requested version (with the version identity, `file_sha256`, the chunk
hash and span), the version's M4 evidence state, and the candidates.

The **other** claim of a candidate is disclosed only if the caller could read that version on their
own:

- the caller holds an active `expert_reviewer` or `approver` role for the scope of its source, or
- it is public knowledge that is active (approved, source approved, in force), which every signed-in
  user can already retrieve.

Otherwise the candidate is withheld entirely: no row, no placeholder, and it is not counted, in the
response or in the audit row.

| Requested version | Other claim | Caller | Result |
|---|---|---|---|
| public | public | public reviewer | returned |
| tenant org A | public, active | reviewer for org A | returned |
| tenant org A | public, not served (draft, quarantined, expired) | reviewer for org A only | withheld |
| public | tenant org A | public reviewer only | withheld |
| tenant org A | tenant org B | anyone | cannot exist: M4 refuses to store a pair across organizations |

## 4. Audit

`public.knowledge_review_read_events`, append-only (the M2 evidence guard and truncate guard; the
owner cannot insert, update, delete or truncate). One row per call that reached the role check:

- `caller_user_id`, `caller_session_id` (the verified identity and session);
- `personnel_id`, `role_id`, `role` (the role the access was granted under; null for a denial);
- `requested_document_pk`, `recorded_at`, `recorded_xact`;
- `outcome` (`granted` or `denied`), `claims_returned`, `candidates_returned`.

It holds no document text and no claim text. Only `service_role` can read it (RLS on, no policy).

**No existence oracle.** A denial is one answer, `{"access": "denied", ...}`, whether the version
does not exist, is in another scope, or the caller holds no reviewer or approver role. The audit row
has the same shape in all three cases: the id as requested, no personnel, no counts. The requested
id has no foreign key, so a row for a missing version is indistinguishable from one for a version
the caller may not read. Withheld candidates are not counted in the row.

## 5. Differences from the design in #59

1. A denial is **returned**, not raised as `42501`. A raised error would roll the audit row back,
   and the owner asked for the access outcome to be recorded. A caller who fails
   `private.knowledge_verified_actor()` (no aal2, no session, service login) still gets `42501` and
   leaves no row.
2. The audit table was an open owner decision in the design; the owner approved it.
3. A tenant reviewer does not see a candidate against public material that is not being served. The
   design table said "public text is readable by everyone in scope"; a public draft is not.

## 6. Known limits

- Every call by a signed-in aal2 user writes one small audit row, denied calls included. Nothing in
  the database rate-limits it; that belongs to the API gateway. The row pins no account (no foreign
  key on the caller).
- Claim and candidate ids come from global sequences. Gaps between ids exist for many reasons and
  are not attributable to a document, but the ids are not opaque.
- The RPC does not compare `file_sha256` with the hash confirmed in an open M2 review; the reviewer
  does. It does not require an open review, because an approver reads candidates after the
  reviewer's recommendation.
- No web screen. One must go through the web role-verification gate.
- The M2 operational risks (database-owner trust boundary, service-role archive and quarantine, demo
  approval) are unchanged by M4.1.

## 7. Rollback

Order is M4.1, M4, M3, M2, M1. The M4 rollback refuses while M4.1 is installed. The M4.1 rollback
drops the read audit, so it needs
`set local knowledge.m4_1_rollback_evidence_exported = 'yes'` after an export.

## 8. Tests

`backend/tests/test_rag_knowledge_m4_1_review_read.py`, against the real database roles:
privileges and append-only audit; every unverified caller is refused without a row; reviewer and
approver in scope; one denial for every other caller and for a missing version; suspended and
revoked roles; the disclosure cases; a stored candidate blocks no approval and a read changes no
status; rollback and replay.
