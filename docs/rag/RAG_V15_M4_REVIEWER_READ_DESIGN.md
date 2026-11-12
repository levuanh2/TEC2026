# RAG V1.5 M4 follow-up: reviewer read access to claims and contradiction candidates (design)

Status: **DESIGN ONLY (2026-11-12). Nothing here is implemented.** No migration, no RPC, no UI.
Depends on M2 (#56), M3 (#57) and M4 (#58), in that order. dev3-01 stays OPEN.

## 1. Problem

M4 stores claims (`public.knowledge_claims`) and contradiction candidates
(`public.knowledge_contradiction_candidates`). Only `service_role` can read them. The expert
reviewer, who is the person the candidates are for, cannot see them. Today an operator would have to
export rows by hand, which is neither audited nor scoped.

## 2. What the interface is, and is not

One read-only RPC for a verified expert reviewer or approver. It returns the claims of one document
version and the candidates that involve them.

It does **not**:

- change any status, approve, reject, quarantine or block anything;
- make an open candidate a precondition of a review or an approval (M4 stays a review aid; a
  blocking rule would be a separate owner decision and a separate migration);
- say that a candidate is false. Every row is returned with the M4 classification as stored, and the
  response carries a fixed notice that a candidate is unverified.

## 3. Access rule

The caller must pass every check of `private.knowledge_verified_actor()` (M2): database role
`authenticated`, a JWT naming a user at `aal2`, a live aal2 `auth.sessions` row of that user, a
verified MFA factor, not banned, deleted or anonymous, no pending password change. The identity is
`auth.uid()`; the RPC takes no identity parameter.

The caller must hold an **active** `expert_reviewer` or `approver` role
(`private.knowledge_actor_role`) for the scope of the **requested document's source**:
`scope_visibility` equal to the source's visibility, and for a tenant source the same
`scope_organization_id`.

Uploaders and registry admins get nothing: neither needs the candidates to do their duty.

Every refusal is the same error (`42501`, "not available for your knowledge role"), whether the
document does not exist, is in another scope, or the caller has no role. No existence oracle.

## 4. What is returned, and the disclosure rule

Signature (proposed): `public.knowledge_review_claims(p_document_pk uuid)`, `SECURITY DEFINER`,
`search_path = ''`, static SQL, `EXECUTE` for `authenticated` only, `STABLE`.

Rows returned:

1. **Claims of the requested version**: `id`, `claim_id`, `extractor_version`, `chunk_id`,
   `chunk_content_sha256`, `span_start`, `span_end`, `raw_text`, `kind`, `status`, `parameter`,
   `value_min`, `value_max`, `unit`, `dimension`, `date_iso`, `stage`, `scope_tags`, `note`,
   `recorded_at`. Plus the version identity: `source_id`, `document_id`, `document_version`,
   `file_sha256`.
2. **Candidates** where `claim_a` or `claim_b` belongs to the requested version: `classification`,
   `reasons`, `independence`, `tolerance`, `tolerance_rationale`, `analysis_version`, `policy_date`,
   `evidence_state_a`, `evidence_state_b`, `recorded_at`, and for the **other** claim the same
   claim columns and version identity as above.

**The other side of a pair is disclosed only if the caller could read it on its own.** A candidate
row copies "the more private scope of the two claims" (M4). The RPC returns a candidate only when the
caller's role covers **that candidate's** scope **and** the other claim's own scope:

| Requested version | Other claim | Caller's role | Result |
|---|---|---|---|
| public | public | public reviewer | returned |
| tenant org A | public | reviewer for org A | returned (public text is readable by everyone in scope) |
| tenant org A | tenant org A, same farm or org-wide | reviewer for org A | returned |
| public | tenant org A | public reviewer only | **not returned**, and not counted |
| tenant org A | tenant org B | reviewer for org A only | **not returned**, and not counted |

A withheld candidate leaves no trace in the response (no count, no placeholder), so the public
reviewer cannot learn that a tenant document disagrees with a public one.

**Farm scope.** M2 roles are scoped per organization, not per farm. A reviewer for organization A
therefore reads claims of every farm of A. That is the existing M2 boundary; this design does not
widen it. If the owner wants farm-level reviewer roles, that is a change to the M2 registry first.

**No service-role pass-through.** The definer function selects named columns from the two M4 tables
and `knowledge_documents` with a fixed predicate. It takes no table, column, filter or SQL fragment
from the caller, and it returns no row of any other table (no personnel, no approval record, no
chunk content beyond `raw_text`, which is at most 2000 characters and is already bound to the span).

## 5. Evidence and version identity

Each claim row carries what binds it to the reviewed artifact: the document version's `file_sha256`,
the chunk's `content_sha256` at extraction, the character span and the extractor version. The
response also includes `evidence_state` of the requested version as M4 computes it
(`private.knowledge_document_evidence_state`), so the reviewer sees whether a claim comes from
material that is active, a candidate, or inactive.

A reviewer who is reviewing version V under an M2 review should compare `file_sha256` with the hash
they confirmed in `public.knowledge_start_expert_review`. The RPC does not do that comparison for
them and does not require an open review: an approver also needs to read candidates after the
reviewer's recommendation.

## 6. Audit

Reads of review material by privileged humans should be attributable. Proposed: one append-only row
per call in a new table `public.knowledge_review_read_events` (caller user id, session id, personnel
id, role id, document pk, counts returned, timestamp), written by the RPC, same privileges and
guards as the M2 evidence tables. This makes the function `VOLATILE`. Whether the audit row is worth
the extra table is an **owner decision** (see section 9).

## 7. Tests the implementation must have

- every `private.knowledge_verified_actor()` refusal (aal1, no session, expired token, no MFA
  factor, banned, anonymous, pending password change, `service_role`, `anon`, database owner);
- no role, wrong role (uploader), suspended or revoked role, expired role, suspended person;
- wrong scope: public reviewer on a tenant version, org A reviewer on an org B version;
- the five disclosure cases of section 4, including that a withheld candidate changes neither the
  rows nor any count;
- the same error and SQLSTATE for "does not exist" and "not yours";
- no status, event or evidence row changes after a call (apart from the audit row, if adopted);
- an approval of a version with an open `contradiction` candidate still succeeds (no silent block);
- grants: `EXECUTE` for `authenticated` only; the M4 tables keep no client grant and no policy;
- the definer function has a pinned empty `search_path` and appears in `schema-audit.json`.

## 8. Delivery

A separate Draft PR stacked on #58, with its own migration and rollback
(`..._knowledge_review_read_m4_1.sql`), `scripts/ci/policy` updates and a CI-Policy-Change trailer.
Local and CI only. No hosted migration without an owner decision. A web screen is a later step and
must go through the web role-verification gate (no business screen before `/v1/me` confirms the role).

## 9. Owner decisions

1. Approve this access rule (expert reviewer and approver, aal2, scope of the requested version)?
2. Audit table for reads: yes or no?
3. Should an approver see candidates at all, or only the reviewer?
4. Stay non-blocking (recommended), or should an open `contradiction` candidate require an explicit
   reviewer finding before `recommend_approval`? The second is a change to the M2 evidence rules.
