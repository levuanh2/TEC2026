# RAG V1.5 M2 operational hardening (implementation-ready design)

Status: **DESIGN ONLY (2026-11-12). Nothing here is implemented.** No migration, no code, no hosted
change. Base: `integrate/rag-v15` at `f424fb2` (M1, M2, M3, M4 merged). dev3-01 stays OPEN.

Why a design and not a migration in this PR: every change below replaces a function that M2 or M3
defines (`private.knowledge_transition_source`, `private.knowledge_transition_document`,
`private.knowledge_demo_approve_*`, `public.match_knowledge_chunks_lexical`,
`private.knowledge_check_cross_source_supersession`). M4.1 (#60, migration `20261112120000`) is
still a Draft. A hardening migration must be numbered after it and its rollback must restore the
bodies that are current at that time, so it is written once #60 is merged or rejected. Section 7
gives the order.

These risks were **acknowledged for integrate-only development and are not accepted for a hosted
deployment**. H1 to H4 are preconditions of any hosted M2 migration.

## 1. Current state (verified against `f424fb2`)

| # | Fact | Where |
|---|---|---|
| F1 | `service_role` may call `private.knowledge_transition_document` / `_source` for `approved -> quarantined`, `approved -> archived` and `quarantined -> archived`. The only input checks are a reason of 1 to 2000 characters and the transition matrix. | M1 `20261110090100`, replaced in M2 `20261110120000` lines 784 to 870 |
| F2 | Each transition writes one append-only `knowledge_status_events` row with the reason and the database role. It does not record **which human** asked: the service credential is shared. | M1 |
| F3 | `archived` is terminal. A mistaken archive is recovered only by a new version. | M1 matrix |
| F4 | A demo approval writes an approval record with `assurance = 'demo_unverified'` and a note prefix, then sets the same `status = 'approved'` as a verified approval. | M2 lines 1755 to 1840 |
| F5 | Retrieval (`public.match_knowledge_chunks_lexical`) and the document RLS policy select on `status = 'approved'` and the in-force window. Neither reads `assurance`. A demo-approved chunk is returned exactly like a verified one, with no marker. | M3 lines 711 to 812 |
| F6 | The demo switch requires `environment_label in ('local','ci','demo','staging')`. The label is text typed by whoever turns the switch on. Nothing ties it to the actual database. | M2 lines 1685 to 1697 |
| F7 | Staging shares the hosted Supabase project with production data. | project memory, `RAG_V15` notes |
| F8 | Cross-source supersession needs the replacing source to be approved and one `sources_checked` entry with `purpose = cross_source_supersession_authority`, the target id and a non-empty `reference`. The reviewer and approver roles are scoped by visibility and organization, not by source or publisher. Any public reviewer plus any public approver can retire a version of any public source. | M3 lines 233 to 275; M2 `private.knowledge_actor_role` |
| F9 | Demo approval never supersedes a version of another source (fixed in `7cdbc69`). | M3 `private.knowledge_supersede_for` |

## 2. H1: emergency quarantine stays a service operation, with a typed reason and evidence

Decision: `approved -> quarantined` remains callable by `service_role`. It is the brake, and it must
work when no qualified human is signed in.

Changes:

1. New table `public.knowledge_emergency_actions`, append-only (the M2 evidence guard and truncate
   guard), `SELECT` for `service_role` only:

   | Column | Rule |
   |---|---|
   | `id`, `recorded_at`, `recorded_xact` | as the M2 evidence tables |
   | `entity_type`, `source_id`, `document_pk` | the row quarantined |
   | `status_event_id` | FK to the `knowledge_status_events` row of the same transaction, unique |
   | `reason_code` | closed list: `integrity_mismatch`, `provenance_withdrawn`, `rights_withdrawn`, `harmful_content_report`, `superseding_law`, `demo_go_live`, `operator_error_containment` |
   | `reason_detail` | 20 to 2000 characters |
   | `operator_reference` | non-empty: the ticket, incident or on-call record that names the human. The database cannot verify it; it makes the action traceable outside the database |
   | `snapshot`, `snapshot_sha256` | `private.knowledge_document_snapshot` / `_source_snapshot` at the moment of quarantine |
   | `db_role`, `session_user_name` | as observed |

2. New `private.knowledge_emergency_quarantine_document(p_document_pk, p_reason_code, p_reason_detail,
   p_operator_reference)` and `_source(...)`, `SECURITY DEFINER`, `EXECUTE` for `service_role` only.
   They perform the transition and write the evidence row in one transaction.

3. `private.knowledge_transition_document` / `_source` **refuse** `approved -> quarantined` with
   `42501` and name the new function. So a quarantine without the evidence row is impossible, for
   the owner login too (the row trigger already requires the transition marker).

4. Expiry (`private.knowledge_expire_documents`) keeps its own path and its own evidence table.

Not changed: quarantine is one-way (M1 D1).

Tests: every reason code accepted and anything else refused; too-short detail refused; missing
operator reference refused; the generic transition refuses quarantine; evidence row immutable;
status event and evidence row share the transaction (a failed insert leaves the document approved);
`authenticated` and `anon` cannot execute; expiry still works.

## 3. H2: permanent archive needs an authenticated, authorized human

Decision: `approved -> archived` and `quarantined -> archived` are no longer available to the
shared service credential.

1. New role value `archivist` in `knowledge_personnel_roles.role` (scope: visibility and
   organization, as the other roles). Granted by a registry admin like any role.
   **Owner decision D-H2a:** a separate `archivist` role (recommended: archiving is custodial, not
   a content judgement), or reuse `approver`.

2. New `public.knowledge_archive_document(p_document_pk, p_snapshot_sha256, p_reason_code,
   p_rationale)` and `public.knowledge_archive_source(...)`, `SECURITY DEFINER`, `EXECUTE` for
   `authenticated` only:
   - `private.knowledge_verified_actor()` (aal2 session, verified MFA factor);
   - an active `archivist` role for the scope of the source;
   - `p_snapshot_sha256` must equal the current snapshot hash (the human states what they archive);
   - separation of duties: the archivist is not the uploader of that version. **Owner decision
     D-H2b:** also forbid the approver of that version (recommended for `approved -> archived`;
     not needed for `quarantined -> archived`);
   - writes an append-only `public.knowledge_archive_records` row (personnel id, role id, user id,
     session id, snapshot, hash, reason code, rationale) and performs the transition.

3. `private.knowledge_transition_document` / `_source` refuse both archive transitions with `42501`.

4. Supersession (M3) keeps archiving the replaced version inside `public.knowledge_decide_document`.
   That path is already a verified human decision with its own approval record.

5. Break-glass. If no archivist exists (a new deployment), nothing can be archived, and nothing
   needs to be: quarantine already removes material from retrieval. There is **no** service-role
   fallback. The registry admin grants the role.

Tests: service role and owner refused on both archive transitions; uploader refused; wrong scope
refused; stale snapshot hash refused; aal1 refused; record immutable; supersession unaffected;
M1/M2/M3 archive tests moved to the new path through `tests/knowledge_status_paths.py`.

## 4. H3: demo assurance is separated at the database and at retrieval

Problem (F4 to F7): after a demo approval, nothing on the read path distinguishes unverified
content from verified content, and the only gate is a typed label.

### 4.1 Database separation

1. A generated, non-forgeable column on the row itself:
   `knowledge_documents.approval_assurance text` and `knowledge_sources.approval_assurance text`,
   values `verified` or `demo_unverified`, null unless approved. Written **only** by the row trigger
   from the approval record of the same transaction (the trigger already looks that record up).
   Immutable afterwards. A CHECK ties `status = 'approved'` to a non-null value.
   Backfill in the migration from `knowledge_approval_records`; an approved row with no record
   fails the migration (fail-closed, nothing is guessed).

2. A database-level deployment class, set by the database owner once, not by the caller:
   `private.knowledge_deployment (singleton, class text check (class in ('isolated_test','shared')),
   set_at, set_by_session_user)`, default **`shared`** (fail-closed), no grant to any client or
   service role, no function for `service_role` to change it.
   - `private.knowledge_demo_require_enabled()` additionally requires `class = 'isolated_test'`.
   - The free-text `environment_label` stays as a note. It stops being a control.
   - Consequence: on hosted (class `shared`, never changed), demo approval is impossible even if
     someone turns the switch on. Staging shares the hosted database (F7), so staging cannot demo
     approve either. That is intended: an environment label is not a security boundary.
   - **Owner decision D-H3a:** demos that need approved content run on an isolated project
     (recommended), or the owner accepts demo content on the shared project with the retrieval
     separation of 4.2 as the only control.

### 4.2 Retrieval separation

`public.match_knowledge_chunks_lexical` and the document RLS policy add:

```sql
and d.approval_assurance = 'verified' and s.approval_assurance = 'verified'
```

by default. Demo-approved content is returned only when **both** hold: the deployment class is
`isolated_test`, and the caller passes `p_include_demo => true`. Each returned row then carries
`assurance` so the answer path can label it. The answer path (`rag_application.py`, guarded) must
show "DEMO, NOT EXPERT-REVIEWED" for such a citation and must never mix a demo citation into an
answer without the label. On a `shared` deployment the parameter is ignored and logged.

M4 already reports demo material through `private.knowledge_document_evidence_state`; it switches
to the new column.

### 4.3 Local fixtures keep working

The synthetic test stacks (local, CI) need approved documents. The replacement path:

- `scripts/ci/seed_ci_db.py` and the test fixtures set the deployment class to `isolated_test`
  through the owner connection they already use for migrations, then use the demo approval as today.
- Tests that assert retrieval of approved content either pass `p_include_demo => true` (fixtures
  that are demo-approved) or go through the verified flow with synthetic personnel
  (`tests/knowledge_status_paths.py` already does this for M2 to M4).
- A CI assertion: a fresh database is class `shared`, the demo switch is off, and a demo approval
  attempt fails.

Tests: demo-approved chunk absent from default retrieval; present with the flag only on
`isolated_test`; absent with the flag on `shared`; a verified chunk unaffected; RLS policy matches
retrieval; assurance column cannot be updated by owner, service or definer functions outside the
approval; backfill refuses an approved row without a record; `demo_quarantine_all` still works.

## 5. H4: authority for cross-source supersession

Problem (F8): organization-level reviewer and approver roles decide that source B replaces a
version of source A. For public sources this is every public reviewer for every publisher.

Evaluation of three options:

| Option | What | Cost | Verdict |
|---|---|---|---|
| A. Keep organization-level authority, evidence entry only (today) | none | none | weakest: one reviewer and one approver can retire any public guidance |
| B. Per-source role scope: `knowledge_personnel_roles.scope_source_id` (nullable); a role with a source scope applies to that source only | one column, `knowledge_actor_role` gains a parameter, registry admin grants per source | registry grows with sources; every existing role must be re-granted or stays organization-wide | precise, but heavy for same-source work that does not need it |
| C. A separate **supersession authority** record: the approver of the **target** source's scope (or a holder of a new `source_custodian` role for that source) must countersign a cross-source replacement | one evidence table, one RPC, a check in `knowledge_decide_document` | one more human step, only for the rare cross-source case | **recommended** |

Recommended design (C):

1. `knowledge_sources.publisher_key text` (normalized publisher identity; today `owner` is free
   text). Same publisher on both sides: the existing rule is enough.
2. Different publishers: `public.knowledge_authorize_cross_source_supersession(p_document_pk,
   p_target_document_pk, p_snapshot_sha256, p_authority_reference, p_rationale)`, called by a
   verified human who holds `source_custodian` for the **target** source (granted per source by the
   registry admin) and who is neither the uploader, reviewer nor approver of the replacing version.
   Writes an append-only `knowledge_supersession_authorizations` row.
3. `private.knowledge_check_cross_source_supersession` (submission and approval time, both kept)
   additionally requires that row for exactly this pair and this snapshot hash.
4. Demo approval: unchanged, never cross-source (F9).

**Owner decision D-H4:** option C (recommended), B, or stay with A for integrate and decide before
hosted. If no custodian exists for a source, a cross-source replacement of it is impossible; the
old version can still be quarantined (H1) or archived (H2) on its own evidence.

Tests: same publisher unaffected; different publisher without authorization refused at submission
and at approval; authorization by the reviewer or approver of the replacing version refused;
custodian of another source refused; stale snapshot refused; record immutable.

## 6. What this does not fix

- The database-owner trust boundary. The owner login can replace any function. Mitigation is
  organizational (who holds the owner credential, migration review, CODEOWNERS), not SQL.
- `operator_reference` in H1 is a pointer, not an identity.
- Read-side labelling in 4.2 depends on the answer path honouring `assurance`; that is application
  code and needs its own tests.
- Farm-level reviewer scope (roles stay per organization).

## 7. Delivery order

1. #60 (M4.1) merged or rejected by the owner.
2. Migration H-a `..._knowledge_m2_hardening_assurance.sql`: 4.1 and 4.2, with rollback. First,
   because it closes the path by which unverified content reaches retrieval.
3. Migration H-b `..._knowledge_m2_hardening_operator.sql`: H1 and H2.
4. Migration H-c `..._knowledge_m2_hardening_supersession.sql`: H4, after D-H4.
5. Each is its own Draft PR with CI, `scripts/ci/policy` updates and a CI-Policy-Change trailer.
   Rollback order: H-c, H-b, H-a, M4.1, M4, M3, M2, M1.
6. No hosted migration of M1 to M4.1 before H-a and H-b are merged.

## 8. Owner decisions

| Id | Question | Recommended |
|---|---|---|
| D-H2a | `archivist` role or reuse `approver` | separate role |
| D-H2b | may the approver of a version archive it | no for `approved -> archived` |
| D-H3a | where demos with approved content run | an isolated project; shared project never demo approves |
| D-H4 | cross-source authority model | option C |
