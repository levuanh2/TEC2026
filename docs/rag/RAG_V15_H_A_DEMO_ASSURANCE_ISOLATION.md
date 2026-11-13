# RAG V1.5 hardening H-a: demo assurance isolation

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261113090000_knowledge_m2_hardening_assurance.sql`,
rollback `supabase/rollbacks/20261113090000_knowledge_m2_hardening_assurance.down.sql`. Not applied to
hosted; a hosted migration needs a separate owner decision (section 8). dev3-01 stays OPEN.

Design: `RAG_V15_M2_OPERATIONAL_HARDENING_DESIGN.md` section 4 (H3). Owner decision **D-H3a
(2026-11-12)**: demo-approved content runs ONLY on a physically or logically isolated local or
dedicated test database, never on the shared hosted Supabase project.

## 1. What was wrong (H3)

M2 lets the owner switch on a demo approval path (`private.knowledge_demo_mode`) that approves a
version without a verified expert. The approval record says `assurance = 'demo_unverified'`, but
the row itself is just `status = 'approved'`, and retrieval, RLS and the M4 evidence state read the
row. So a demo approval on the shared project would be served to every farmer as approved
guidance, and the only thing that said "this is a demo" was a free-text `environment_label` that
the caller writes.

## 2. What H-a changes

| Layer | Before | After |
|---|---|---|
| Row | `status = 'approved'` | plus `approval_assurance` in `verified` / `demo_unverified` / `unrecorded`, stamped by a trigger from this transaction's approval record, immutable |
| Retrieval `match_knowledge_chunks_lexical` | every approved, in-force row | `verified` on the version **and** on its source |
| RLS on `knowledge_documents` / `knowledge_sources` | approved | `verified`, or `demo_unverified` only inside the demo RPC on an isolated database |
| Demo retrieval | the production RPC | separate `match_knowledge_chunks_lexical_demo`, refuses (42501) unless isolated, labels every row |
| Demo approval | switch on | switch on **and** the isolation gate passes |
| M4 evidence state | `active` = approved and in force | also `verified` on both sides; a demo version is `inactive` with reason `assurance_demo_unverified` |
| Answer path (`rag_application.py`) | n/a | production RPC by default; demo RPC only when `RetrievalSettings.include_demo`; demo citations titled `DEMO, NOT EXPERT-REVIEWED: ...` and `metadata.approval_assurance` set; an unknown assurance value refuses the row |

### 2.1 Assurance is derived by the database

- The caller's value is never used. On INSERT the column must be null (`23514` otherwise). On the
  transition to `approved`, `private.knowledge_stamp_approval_assurance` reads
  `knowledge_approval_records` for the same entity, the same approver and the **current transaction**
  (`recorded_xact = pg_current_xact_id()`); any `demo_unverified` record wins. No record: the
  approval is refused (`42501`). Afterwards the column is immutable, including for the owner
  (`23514`), and survives quarantine and archive.
- A CHECK ties `approved_at is null` to `approval_assurance is null`.
- The existing artifact hash binding (ST1.1) and the immutable approval records are unchanged; H-a
  only copies the record's assurance onto the row so every read path can filter on it.

### 2.2 Retrieval policy needs both the version and the source

A verified version of a demo-approved source is not served (test
`test_a_verified_version_of_a_demo_approved_source_is_not_served`). The document policy also
requires its source row to be visible through the source policy, which applies the same rule.

### 2.3 Backfill (deviation from the design, fail closed)

The design said an approved row without an approval record fails the migration. The
implementation stamps such a row `unrecorded` instead, and **no read path serves `unrecorded`**:
not retrieval, not RLS, not the demo RPC, not the M4 evidence state. Reason: rows approved before
M2 (M1 created no approval history) cannot be classified, and failing the whole migration would
force someone to guess. `unrecorded` keeps them out of every answer until they go through the
verified M2 flow as a new version. The migration prints the counts per table and assurance
(`H-a approval_assurance backfill: ...`) so the operator sees what was withheld. Any
`demo_unverified` record wins over `verified` for the same row.

## 3. The isolation gate

A database row alone cannot prove where a database runs, and a mutable flag alone does not prove
isolation: whoever holds the owner login can set it. H-a therefore uses a gate with an external and
an internal half. `private.knowledge_deployment_isolated()` is re-evaluated on every call (every
demo approval, every demo RPC call, every RLS check of a demo row).

**Internal half (database, all must hold):**

1. `private.knowledge_deployment.class = 'isolated_test'`. Default `shared`; no grant to any client
   or `service_role`; the row can be changed only by the owner-only functions
   `private.knowledge_declare_isolated_test(attestation)` / `private.knowledge_declare_shared()`.
   Direct INSERT/UPDATE/DELETE/TRUNCATE is refused, also for the owner.
2. The declaration is **bound** to this cluster and database: the `system_identifier` from
   `pg_control_system()` and `current_database()` recorded at declaration must equal the live
   values. A dump restored on another cluster (including a copy pushed to a shared project) is not
   isolated. If `pg_control_system()` is not readable, the gate is false.
3. The database holds **no account that looks real**: every `auth.users.email` is non-null and on a
   reserved test domain (`.invalid`, `.test`, `.example`, `.localhost`, `.local`,
   `example.com/.org/.net`). The shared project has real farmer and manager accounts, so it is never
   isolated whatever the row says; a declaration made earlier stops counting the moment a real
   account appears.

**External half (`scripts/ci/knowledge_isolation_gate.py`, run by the operator before declaring):**

- Refuses, **before connecting**, any target that is a Supabase-hosted endpoint (`*.supabase.co`,
  `*.supabase.com`, poolers) or that is not a loopback / RFC 1918 / ULA address. A hosted URL never
  reaches psycopg and is never printed.
- Prints a JSON report (target host:port, class, binding, system identifier, real accounts,
  isolated) and writes the checked target and system identifier into the attestation.
- `--revoke` sets the database back to `shared` from any target.

**Independent verification after the fact** (anyone with read access to the database, no trust in
the declaring session):

```sql
select d.class, d.bound_system_identifier = c.system_identifier as same_cluster,
       d.bound_database = current_database() as same_database,
       private.knowledge_has_real_accounts() as real_accounts,
       private.knowledge_deployment_isolated() as isolated, d.attestation, d.declared_at,
       d.declared_by_session_user
  from private.knowledge_deployment d, pg_control_system() c;
```

For the hosted project the expected answer is `class = shared`, `isolated = false`. The hosted
readiness check (section 8) runs exactly this query.

### 3.1 What the gate does not claim

- The database owner or any superuser can replace these functions, disable the triggers or call
  the declaration function directly with any attestation. That is the infrastructure trust boundary
  of M1 and M2, unchanged. The controls stop the shared service credential, clients and accidents (a
  copied database, a switch left on, a "staging" label on the shared project), not the owner.
- `environment_label` on `knowledge_demo_mode` is a note only. It is not read by any control.
- The account check is a heuristic on email domains. It is a strong signal for the shared project
  (real users), not a proof for an empty project. A dedicated hosted test project with no users
  would pass the internal half; the external half refuses any Supabase-hosted target, so declaring
  one needs the owner to bypass the script on purpose.

## 4. Demo retrieval on an isolated database

- `public.match_knowledge_chunks_lexical_demo(season, query, top_k)`: EXECUTE for `authenticated`
  only (not `anon`, not `service_role`), SECURITY INVOKER so RLS applies. Same tenant, organization
  and farm scope as production. Refuses with `42501` on a shared database (not an empty result).
- It sets the transaction-local `knowledge.include_demo = on`, which the RLS helper
  `private.knowledge_demo_read_enabled()` reads **together with** the gate. A client that sets the
  setting itself on a shared database still sees nothing (test
  `test_default_retrieval_and_rls_serve_verified_content_only`).
- Every row carries `approval_assurance`: `verified` only when both version and source are
  verified, else `demo_unverified`.
- The answer path uses it only when `RetrievalSettings.include_demo` is set (default off). The
  production route does not set it.

## 5. Local and CI fixtures

- Test fixtures that need demo approvals call `private.knowledge_declare_isolated_test(...)` on the
  owner connection inside the test transaction (`_demo` in `test_rag_knowledge_m2_approval.py`), so
  the declaration is rolled back with the test. The local and CI stacks use synthetic accounts on
  `.invalid` domains only, so the binding and account checks pass.
- Tests that assert retrieval of approved content go through the verified M2 flow
  (`tests/knowledge_status_paths.py`) or the demo RPC.
- A fresh database is `shared`, the demo switch is off, and a demo approval with the switch on is
  refused (`test_a_fresh_database_is_shared_and_demo_approval_is_refused_even_with_the_switch_on`).

## 6. Rollback

`supabase/rollbacks/20261113090000_knowledge_m2_hardening_assurance.down.sql`, one transaction, after
any H-b/H-c rollback and **before** the M4.1 rollback (the M4.1 rollback now refuses while H-a is
installed). It restores the exact pre-H-a bodies (M3 retrieval and document policy, base source
policy, M2 demo switch check, M4 evidence state; test
`test_rollback_restores_the_pre_h_a_bodies_verbatim` compares them with the migrations that define
them). After the rollback retrieval no longer reads assurance, so it **refuses**:

- without `set local knowledge.ha_rollback_confirmed = 'yes'`;
- while H-b or H-c is installed;
- while any approved version or source is `demo_unverified` and the database is not isolated (run
  `private.knowledge_demo_quarantine_all` first);
- while any approved row is `unrecorded`, unless `set local knowledge.ha_rollback_reserve_unrecorded
  = 'yes'` confirms that re-serving them is intended.

The approval records keep the assurance of every approval; only the copied column, the deployment
table and the demo RPC are dropped. A re-applied H-a starts `shared` again and re-derives the column
from the records (test `test_rollback_refuses_to_re_expose_demo_content_and_replay_backfills_fail_closed`).

Rollback order is now H-a, M4.1, M4, M3, M2, M1.

## 7. Tests

- `backend/tests/test_rag_knowledge_ha_assurance.py` (DB): gate default, grants, direct-write
  refusal, binding, real-account and reserved-domain cases, stamping and immutability (owner
  included), verified-only retrieval and RLS, source assurance, the demo RPC on isolated and shared,
  evidence state, rollback refusals, replay backfill and verbatim body restore.
- `backend/tests/test_knowledge_isolation_gate.py` (offline): hosted and public targets refused
  before connecting, no URL or secret printed.
- `backend/tests/test_rag_application.py`: demo citation label, unknown assurance refused, demo RPC
  only with `include_demo`.
- Updated M2/M3/M4/M4.1/status-events/storage DB tests for the new behaviour.

## 8. Hosted readiness (not done; needs an owner decision)

1. Read-only count on hosted of approved rows per table and of approval records per assurance, to
   know what `unrecorded` will withhold.
2. Apply H-a together with H-b (design section 7: no hosted M1 to M4.1 migration before H-a and H-b).
3. After applying: the verification query of section 3 returns `shared` / `false`; the demo switch
   is off; a demo approval attempt is refused.
4. Never run `knowledge_isolation_gate.py --declare` against hosted (it refuses).
