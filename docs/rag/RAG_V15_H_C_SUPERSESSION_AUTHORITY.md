# RAG V1.5 hardening H-c: cross-source supersession authority

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261113150000_knowledge_m2_hardening_supersession.sql`,
rollback `supabase/rollbacks/20261113150000_knowledge_m2_hardening_supersession.down.sql`. Stacked on
H-b (#66) and H-a (#65). Not applied to hosted. dev3-01 stays OPEN.

Design: `RAG_V15_M2_OPERATIONAL_HARDENING_DESIGN.md` section 5 (H4). Owner decision **D-H4
(2026-11-12)**: option C, target-source custodian countersignature.

## 1. What was wrong (F8)

A version of source B could retire the approved version of source A when B was approved and the
expert reviewer wrote one `sources_checked` entry with a non-empty `reference`. Reviewer and approver
roles are scoped by visibility and organization, not by source or publisher, so any public reviewer
plus any public approver could retire any public publisher's guidance. A non-empty string is not
authority.

## 2. Model

| Object | Written by | Rule |
|---|---|---|
| `knowledge_publishers` | registry admin (aal2) | verified publisher identity: key, legal name, identity evidence; status active / suspended / revoked; not the free-text `knowledge_sources.owner` |
| `knowledge_source_publishers` | registry admin | one **immutable** binding per source, with ownership evidence, to an active publisher |
| `knowledge_source_custodians` | registry admin | a registered person answers for ONE source; only for a source bound to an active publisher; never granted by an admin to themselves; status like every registry row |
| `knowledge_supersession_authorizations` | the custodian (aal2) | the countersignature, append-only |

All four: RLS on, no policy, SELECT for `service_role` only; written only by their functions (M2
registry and evidence guards), never updated except registry status, never deleted or truncated,
also for the owner.

## 3. Countersignature

`public.knowledge_countersign_supersession(successor, successor_snapshot_sha256, target_snapshot_sha256,
statement)`, EXECUTE for `authenticated` only:

- a verified person (`private.knowledge_verified_actor`: aal2, live session, verified factor);
- an active custodian assignment **for the target's source**, the person active, the target bound to
  that publisher, the publisher active. Every other case (no successor, no link, same source, no
  assignment, another source's custodian, a reviewer/approver/archivist role) gets one answer
  (`42501`), no existence oracle;
- the successor still under review (`review_required` or `expert_review`);
- independence: the custodian is not the successor's uploader nor any of its reviewers (canonical
  identity, so a second account is the same human);
- both snapshot hashes equal the current ones (`40001` otherwise);
- a 20-2000 character statement.

The row binds target version, successor version, both snapshot hashes, the publisher, the custodian
assignment, person, user and session. `public.knowledge_custodian_snapshot` lets a custodian read the
hash of the version they countersign.

## 4. Validation (submission and approval)

`private.knowledge_check_cross_source_supersession` (replaced) keeps the M3 rules (approved replacing
source, the reviewer's recorded `cross_source_supersession_authority` entry) and adds: a
countersignature for exactly this successor and target exists such that, **now**,

- both snapshots still hash to the countersigned values (stale content refused);
- the custodian assignment and its person are active;
- the target is still bound to the countersigned publisher and that publisher is active (a
  suspended or revoked publisher voids it);
- the custodian is not the successor's uploader, any of its reviewers, nor the person calling (the
  reviewer at submission, the approver at approval).

It runs when the reviewer recommends approval and again at the final approval, so a revocation, a
publisher change or a content change in between refuses the approval (`23514`) and nothing is
archived.

**Without a valid countersignature the old guidance cannot be superseded through this workflow.** It
can still be quarantined through the H-b emergency procedure.

Unchanged: same-source supersession (no countersignature), and the M3 rule that a demo approval never
supersedes a version of another source.

## 5. What it does not claim

- The countersignature is an authenticated database act (aal2 session, active registry assignment,
  bound hashes). It is **not** a cryptographic signature, and no reference string is treated as one.
- Publisher identity evidence is what the registry admin checked. The database records it; it does
  not verify the outside world.
- The database owner / superuser boundary of M1/M2 is unchanged (H-b document, section 5).

## 6. Concurrency (multi-connection regressions, owner decision 2026-11-13)

The countersignature and the replaced check (now VOLATILE; M3's was STABLE) take **share locks** on the
custodian, person, binding and publisher rows they rely on. A registry status change takes the row
lock. So a revocation or suspension and an approval serialize: whoever commits first wins and the
other sees it (READ COMMITTED re-evaluates the locked row after the wait). Lock order is always
successor version -> registry rows -> target version (approval) and successor -> target -> registry
rows (countersignature, share locks only), so the two never form a cycle with each other or with a
registry update (one row lock).

`backend/tests/test_rag_knowledge_hc_concurrency.py` COMMITS synthetic rows, races two connections and
removes them (verified: no fixture row is left):

| # | Race | Result |
|---|---|---|
| 1 | custodian revocation first, approval waits | approval refused (`23514`), nothing archived |
| 1' | approval first, revocation waits | approval commits (valid when it committed), revocation applies after |
| 2 | publisher suspension vs approval, both orders | as 1 / 1' |
| 3 | publisher suspension vs an in-flight countersignature | suspension waits, then voids every countersignature: the approval is refused |
| 3' | a rebinding attempt on two connections | refused on both (bindings are immutable) |
| 4 | two successors, both countersigned, approved concurrently | the second waits on the target row lock; both approved; target archived exactly once |
| 5 | a countersignature racing an uncommitted chunk insert on the successor | it signs what it can see; once the chunk commits it is stale and the recommendation is refused |
| 5' | an approval waiting on a target emergency quarantine | after the wait the target is quarantined; nothing is archived, no wrong supersession |

Every wait has a `lock_timeout` of 20 s and every test asserts the waiting transaction really waited.
No deadlock occurred. Once a version is under expert review both snapshots are immutable (M2/M3
freeze), so a snapshot cannot go stale while an approval waits; race 5 covers the window before.

## 7. Rollback

One transaction, BEFORE the H-b rollback (the H-b and H-a rollbacks refuse while H-c is installed).
It restores the exact M3 body of the check (test compares it with M3) and drops the four tables, so
it refuses without `set local knowledge.hc_rollback_evidence_exported = 'yes'`. Order: H-c, H-b, H-a,
M4.1, M4, M3, M2, M1.

## 8. Tests

`backend/tests/test_rag_knowledge_hc_supersession.py` (DB, 21): no countersignature refuses (and the
emergency quarantine still works); a valid one supersedes; same-source unchanged; role spoofing
(approver, archivist, reviewer roles, a custodian of the replacing or of another source, service
role, owner); cross-tenant custody; registry admin only, publisher binding needed and immutable, no
self-grant; stale hashes at countersigning; changed successor content; a countersignature for another
pair; custodian suspended/revoked, person revoked, publisher suspended/revoked after the
countersignature; independence from uploader, reviewer and approver; a custodian who becomes the
reviewer; forged inserts and updates refused for the owner; grants; custodian snapshot read; rollback
refusal and verbatim restore. The M3 cross-source tests run with a synthetic custodian
countersignature.
