# RAG V1.5 M3 — Version validity: effective dates, supersession, expiry (2026-11-11, local/CI only)

Migration `supabase/migrations/20261111090000_knowledge_effective_dates_m3.sql`, rollback
`supabase/rollbacks/20261111090000_knowledge_effective_dates_m3.down.sql`. Depends on M1
(`20261110090100`) and M2 (`20261110120000`). **Not applied to hosted Supabase. Nothing is scheduled.**

**What M3 proves and what it does not.** M3 keeps a version out of retrieval when it is not in force:
before its effective date, after it, after its approval's shelf life, or once a successor is approved.
It does **not** prove that the content is correct. **dev3-01 stays OPEN.** The characterization test
`test_rag_source_integrity_gap.py` is not flipped (M7).

## 1. Columns (`public.knowledge_documents`)

| Column | Meaning | Who sets it |
|---|---|---|
| `effective_from` | first calendar day the version is in force; null = no lower bound | operator, at ingestion |
| `effective_to` | last calendar day in force, **inclusive**; null = no upper bound | operator, at ingestion |
| `supersedes_document_pk` | the previously approved version this one replaces | operator, at ingestion |
| `approval_expires_on` | last calendar day the approval is valid: **approval day + 2 years** | the approval itself (row trigger); never supplied |

Checks: `effective_to >= effective_from`; a version never supersedes itself; an approved row always has
`approval_expires_on`. Versions approved before M3 are backfilled from their recorded `approved_at`.

**Owner decision (2026-11-11): an approval is valid for two years.** It is one constant,
`private.knowledge_approval_validity()`.

## 2. One policy date

"Today" is the calendar day in **Asia/Ho_Chi_Minh**: `private.knowledge_policy_date(now())`. It does
not depend on the session `TimeZone` or `DateStyle`. The dates are plain `date` values (a regulation
takes effect on a day, not at an instant), so nothing shifts when a client sits in another zone.

A version is **in force** on day *d* when
`effective_from <= d` (or null) **and** `d <= effective_to` (or null) **and** `d <= approval_expires_on`.
A missing approval expiry is *not* in force (fail closed). `private.knowledge_in_force` is the single
definition; the retrieval function and the document RLS policy inline the same predicate so that the
invoker paths need no new `EXECUTE` grant (a test pins the zone and the three columns in both).

## 3. Retrieval

`public.match_knowledge_chunks_lexical` and the `knowledge_documents_select` policy (which the chunk
policy follows) serve an approved version **only while it is in force**. An expired version disappears
at the first moment of the next policy day, whether or not the expiry step has run. Everything else in
both objects is the Migration A text, unchanged.

## 4. Approval

The document row trigger (the only place every path passes: the verified RPC, the demo path, an owner
with a forged marker) refuses:

| Transition | Refused when | SQLSTATE |
|---|---|---|
| `-> expert_review` | `effective_to` has passed (an expired version is not reviewed) | 23514 |
| `-> approved` | `effective_from` is in the future | 23514 |
| `-> approved` | `effective_to` has passed | 23514 |
| `-> approved` | the version it supersedes is still approved | 23514 |

A version may be **reviewed** before it takes effect; the approval waits for the day. M2's own checks
(reviewer still qualified, evidence complete, snapshot unchanged, separation of duties) are untouched.

**Frozen and hashed.** `effective_from`, `effective_to` and `supersedes_document_pk` are frozen from
`expert_review` on and are part of the M2 review snapshot (`private.knowledge_document_snapshot`). The
keys are present only when set, so a version without them hashes exactly as under M2. Changing them
behind a review invalidates the evidence like any other metadata. They are editable while the version
is `review_required` or `rejected`.

## 5. Supersession

`supersedes_document_pk` may name any version (same or another `document_id`, same or another source)
that **was approved at some time** and lives in **exactly the same scope** (public, or the same
organization and farm). So there is no cross-tenant link, and no cycle (a target is always older
evidence, and its own link was frozen before it was approved).

The approval archives the approved superseded version **in the same transaction**, before it approves
the new one, with its own audit event (`superseded by <source> / <document> / <version> (document <pk>)`).
There is neither an overlap nor a gap, and a refused approval archives nothing. If the superseded
version is already quarantined or archived, the approval just approves.

One approved version per `(source_id, document_id)` is still the Migration A unique index: a second
version without a declared supersession is refused (23505) as before.

A version may have several successors (one text split into two documents): each approval finds the
target either approved, and archives it, or already archived.

**What is replaced is named in the evidence.** When the link is set, the review snapshot carries a
`supersedes` object next to `supersedes_document_pk`: the superseded version's `source_id`,
`document_id`, `document_version`, `file_sha256`, its source's `owner` and `authority`, and
`cross_source` (true when it belongs to another source). The reviewer and the approver both confirm
the hash of that snapshot, so neither approves a replacement knowing only a uuid.

**Cross-source supersession needs authority, not just a shared scope.** The same scope says who may
read both texts. It does not say that one publisher's text may retire another's. Public knowledge is
one scope, so without a further rule any public source could have another public source's approved
version archived. When the superseded version belongs to **another source**, `private.knowledge_check_cross_source_supersession` refuses
with 23514 unless both hold. It runs **twice**: when the expert reviewer submits `recommend_approval`
(`public.knowledge_submit_expert_review`), and again at the approval
(`public.knowledge_decide_document`).

1. **The replacing version's own source is `approved`.** A version of a source that is still
   `review_required`, or was rejected, quarantined or archived, cannot retire another source's
   approved guidance. It would not even be served in its place.
2. **The expert reviewer recorded the authority for exactly this replacement.** One entry of the
   review's `sources_checked` has `purpose: "cross_source_supersession_authority"`, the superseded
   version's id as `supersedes_document_pk`, and the `reference` that establishes the authority (for
   example the repealing decision, or the publisher's own notice).

**Why at submission.** A review decision is immutable. If the missing authority were found only at
the approval, the approver could do nothing but reject a finished review and the version would need
a new one. Refused at submission, nothing is recorded: the reviewer adds the entry and submits the
same review again, or returns or rejects the version (neither needs the entry). A recorded decision
still cannot be changed. The approval repeats the check as defense in depth, for example when the
replacing source is quarantined between the recommendation and the approval; the reviewer's check is
never a substitute for it.

The rule holds whatever the superseded version's status is now, because the link is a claim of
authority over another source's text. A refused approval archives nothing; the approver can still
reject the review. A **same-source** supersession needs none of this and works as before, whatever
the source's own status.

What this does not do: the database cannot verify that the cited reference really grants the
authority. Two verified, distinct humans (reviewer and approver) are on immutable record for it. The
operator who sets the link is not: the link alone archives nothing.

**Demo path.** `private.knowledge_demo_approve_document` follows the same window rules and gets the same
two-year expiry. It may supersede only a version **of its own source** whose approval is itself a
demo record. Naming a verified (or pre-M2) version, or any version of another source (demo-approved
or not), is refused (42501) whatever that version's status is now: a demo approval has no review, so
it carries no recorded authority and never retires another source's guidance. The verified flow may
replace a demo version.

## 6. Expiry

- `private.knowledge_expiry_due()`: the dry run. Lists the approved versions the next run would
  quarantine, with the cause (the date that passed first, however late the run is). Read-only.
- `private.knowledge_expire_documents(p_limit default 100, 1–1000)`: moves approved versions that are
  no longer in force to `quarantined` through the M1 audited transition and writes one
  `public.knowledge_expiry_events` row per version (cause, the dates, the policy date and zone, the
  audit event id, the caller's role), in the caller's transaction. Rows locked by another transaction
  are skipped (`SKIP LOCKED`), so two runs never double-expire or block each other.

Both are `SECURITY DEFINER`, `search_path ''`, static SQL, `EXECUTE` for `service_role` only.
`knowledge_expiry_events` is immutable for every role, the owner included (insert only inside the
function; no update, delete or truncate), has RLS on and no client policy.

**Nothing schedules the expiry step.** The migration creates no cron job. Running it (by hand, or from
a scheduler) is an operator decision per environment and needs its own approval on hosted. Retrieval
does not depend on it: section 3 already withholds the version.

### Expiry is one-way

M1 decision D1 is unchanged: `quarantined` goes only to `archived`. **An expired version never returns
to approved.** The corrected or revalidated text is a **new version** through the full M2 flow. So:

- A wrong date is corrected **before the review starts** (or after a rejection). After approval it is
  immutable; the fix is a new version that supersedes the old one.
- An approval cannot be extended. Before `approval_expires_on`, ingest and approve a new version that
  supersedes the current one (the switch is atomic); after it, the old version is already withheld.
- With the M2 rule of three distinct verified people and one human owner today, a real re-approval is
  not possible yet. Only the owner-switched demo path produces approved versions.

## 7. Rollback

Newest first: M3, then M2, then M1 (the M2 rollback now refuses while M3 is installed). The M3 rollback
restores verbatim the Migration A policy and retrieval function and the M2 snapshot, row trigger,
`knowledge_decide_document` and `knowledge_demo_approve_document`. It **drops the expiry evidence and
every validity window**, so it needs `set local knowledge.m3_rollback_evidence_exported = 'yes'`
after an export. It refuses while

- an approved version is not in force (the rollback would make it retrievable again; run the expiry
  step first, and quarantine with the operator transition any version it leaves), or
- a version is under expert review with a window or a superseded version (its snapshot covers them).

## 8. Tests

`backend/tests/test_rag_knowledge_m3_validity.py` (synthetic fixture identities only): privileges and
grants; the policy date across four session zones, midnight, a leap day; in-force boundaries; the
approval expiry (never supplied, zone-independent, demo path too); approval on the first and last day,
refusal before and after the window; frozen columns; the snapshot hash (unchanged without M3 fields,
independent of `TimeZone`/`DateStyle`, invalidated by a changed window); retrieval and RLS withholding
an out-of-force approved version before any expiry run; expiry (causes, limit, idempotence, evidence,
immutability, tenant versions, tenants reading no evidence); a **committed concurrency test** (two
expiry runs race on one version); supersession (atomic, cross-document, cross-scope refusals, demo
rules, refused approval archives nothing); cross-source supersession (an unapproved or rejected
replacing source is refused, a missing or mismatched recorded authority is refused when the reviewer
recommends approval and the same review can then be completed, the approval checks again, an
authorized replacement archives and its evidence names the superseded version, same-source is
unchanged, a demo approval never supersedes a version of another source);
rollback refusals, verbatim restore and replay.

Time cannot be mocked in PostgreSQL. The tests reach "the day after" by lifting the row trigger inside
the test transaction and rewriting a date, which only a database owner can do.

## 9. Limits and open decisions

- **Sources have no validity window.** A source is a collection; its versions expire.
- **No scheduled succession.** A version cannot be approved ahead of its `effective_from`, so a
  successor is approved on the day it takes effect (the old one is served until then). Queuing an
  approval for a future date would need overlapping-window rules (an exclusion constraint) and is not
  in M3.
- **No extension of an approval.** See section 6. Whether to allow a verified re-confirmation that
  extends `approval_expires_on` without a new version is an open owner decision.
- **Ingestion does not set the M3 columns yet.** `backend/knowledge` has no manifest fields for them;
  an operator sets them with SQL while the version is `review_required`. A follow-up can add them to
  the ingestion manifest.
- **Roles are scoped per visibility and organization, not per source.** An approver of the public
  scope can approve a version of any public source. The cross-source rule adds the reviewer's recorded
  authority and an approved replacing source on top of that; a per-source or per-publisher approver
  role would be a registry change (M2), not M3.
- **The two-year period and the policy zone are constants** in the migration. Changing either is a new
  migration.
- **The same infrastructure trust boundary as M1/M2.** A database owner can lift triggers or rewrite
  rows. M3 adds no routine path for it.
- M3 does not check that the dates are *right*. The expert confirms them (`version_and_dates_checked`
  in the M2 checklist); a wrong date entered and approved is served for its window.
