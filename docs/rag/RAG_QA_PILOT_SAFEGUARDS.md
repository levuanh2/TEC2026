# Season Q&A READ-only pilot — rate limit, monitoring and emergency stop

Status: **local/CI only. Production NO-GO.** Every threshold below is a PROPOSAL pending the
owner's decisions A-12 (rate limit) and A-13 (monitoring / on-call). Nothing here was run on
hosted, staging or production.

## 1. Rate limit (A-12)

`POST /v1/crop-seasons/{crop_season_id}/questions`, in `RagQuestionService.answer`:

1. READ-only action-tier lock (PR #92): recommend / what_if / non-ASK → 503
   `action_tier_disabled`. Reads nothing, costs no quota.
2. Supabase Auth verifies the JWT (`reader.user_id()`): invalid, expired, logged-out or revoked
   → 401 `unauthenticated`. Not counted.
3. Pilot cohort gate: the verified user id must be in `RAG_QA_ALLOWED_USER_IDS`
   (comma-separated Auth user ids of the approved A-1 accounts). Anyone else → 403
   `question_not_enabled` "Tính năng hỏi đáp đang thử nghiệm và chưa mở cho tài khoản này.", same
   body for every season id, no quota used, nothing read. Unset/empty = nobody (fail closed); `*` =
   every signed-in user, an explicit owner decision for a later level, never for the L1 pilot.
   Without this gate, `RAG_QA_ENABLED=true` + `VITE_AI_QA_ENABLED=true` would open Q&A to every
   farmer and manager in production, not only to the cohort.
4. One question is counted for the **verified user id**. Over the limit → 429
   `question_rate_limited` + `Retry-After: <seconds>`, Vietnamese message
   "Bạn đã hỏi quá nhiều câu trong thời gian ngắn. Vui lòng thử lại sau." Same body for every
   season id (no tenant information; changing the season id does not reset the count).
5. Only then: scope check, season / Carbon / knowledge reads, composition.

| Setting (server env) | Default | Notes |
|---|---|---|
| `RAG_QA_RATE_LIMIT_PER_MINUTE` | 10 | sliding 60 s; integer ≥ 1, else start-up fails |
| `RAG_QA_RATE_LIMIT_PER_DAY` | 100 | sliding 24 h; integer ≥ 1 |
| `RAG_QA_RATE_LIMIT_STORE` | `postgres` | durable + atomic; needs migration `20261106090000` on that database |
| | `memory` | one API process only: N processes allow N × the limit, a restart forgets the counts |

There is no "off". If the store cannot answer (database down, migration missing) every question
is 503 `question_rate_limit_unavailable` — fail closed.

Why per user and not per IP: several farm households can share one network (a cooperative
office, a mobile carrier NAT). An IP limit would block a whole village for one user's burst, and
a single user could still dodge it by switching networks. An optional IP backstop belongs at the
proxy and needs a Caddy build with a rate-limit module (the official `caddy` image has none).

Only allowed questions are recorded (`private.rag_question_events`: user id + timestamp,
pruned after 24 h), so retrying while limited does not extend the wait.

## 2. Signals the API already writes

| Line | Fields | Use |
|---|---|---|
| `access` (logger `agricarbon.access`) | `request_id method path status duration_ms db_calls db_ms` | counts of 200/401/403/404/429/5xx; latency p50/p95; DB round trips |
| `rag_question` (`agricarbon.rag`) | `request_id intent mode status error llm_calls tokens cost llm_ms total_ms tier` | errors by code; `llm_calls`; tier |
| `rag_question_service` | `tier=read_only provider=not_loaded` / `tier=read_and_action ...` | start-up tier |
| `rag_question_rate_limited` | `request_id window retry_after_s` | 429 by window |
| `rag_question_rate_store_error` (ERROR) | `type` | the quota store failed; that question was 503 (fail closed) |
| `rag_question_cohort` | `mode=allow_list users=<n>` / `mode=closed users=0` / `mode=open_to_all_signed_in_users` (WARNING) | start-up cohort (§1 step 3) |
| `rag_alert` (ERROR) | `llm_calls_in_read_only` / `action_tier_enabled` | tripwires (§3) |
| `rag_tenant_isolation_violation` (ERROR) | — | security failure |

None of them carries the question, an answer, a JWT, a key, an e-mail or a user id. The crop
season id appears in the access-log path (an opaque UUID). `X-Request-ID` from a client is kept
only if it is 1–64 characters of `[A-Za-z0-9._-]`; otherwise the API generates one, so a client
cannot inject fake fields into these lines.

## 3. Alerts (proposed thresholds; owner decides A-13)

`scripts/ops/rag_qa_log_summary.py` reads these lines (stdin or a file), prints counts and
percentiles, and exits 1 on any alert. No paid monitoring service is needed:

    docker logs --since 15m <api container> 2>&1 | python3 scripts/ops/rag_qa_log_summary.py

| Alert | Condition | Severity |
|---|---|---|
| `llm_calls_in_read_only` | a READ-only `rag_question` line with `llm_calls > 0` | stop Q&A now |
| `llm_calls_nonzero` | any `llm_calls > 0` while READ-only is expected | stop Q&A now |
| `action_tier_enabled` | API started with `tier=read_and_action` | stop Q&A now |
| `tenant_isolation` | any tenant-isolation violation | stop Q&A now |
| `cohort_unrestricted` | API started with `RAG_QA_ALLOWED_USER_IDS=*` | stop Q&A now during the pilot (`*` is never a pilot value) |
| `quota_store_unavailable` | any `rag_question_rate_store_error` | investigate now; every question is refused while it lasts |
| `server_errors` | 5xx > 2 % of ≥ 20 questions in the window | investigate; stop if it persists |
| `latency_p95` | p95 > 8000 ms over ≥ 20 questions | investigate (each question is 26–41 sequential statements) |

The summary only sees an API that runs: an API that fails to start writes no Q&A line, so the
container state / a health probe must be watched separately.

Who receives the alert and who may stop Q&A: **PENDING (A-13)**. The person needs shell access to
the API host (container env + Caddy). Until A-13 is decided, the pilot must not open.

## 4. Emergency stop (rehearsed locally only)

| Method | What it does | Local measurement | Caveat |
|---|---|---|---|
| Caddy 503 route (`Caddyfile.qa-off`: POST-only matcher on `^/v1/crop-seasons/[^/]+/questions/?$`) | answers 503 `backend_not_configured` at the proxy; the API is untouched | reload ≈ 0.2 s, first 503 ≈ 0.23 s, back ≈ 0.6 s (caddy:2.8.4, 2026-11-21) | POST only, so CORS preflight still reaches the API; never edit production Caddy without the owner; keep the original file to restore byte-identically |
| `RAG_QA_ENABLED=false` | route answers 503 `backend_not_configured` | API healthy again ≈ 11 s (local) | the container reads `--env-file` only at `docker run`: this is a re-create, not `docker restart` |
| `RAG_QA_RATE_LIMIT_PER_MINUTE=1` | throttles without stopping | re-create, as above | not a stop |

## 5. Release order (mandatory)

The default store is `postgres`. Code from #95 deployed **without** migration `20261106090000` on
that database refuses **every** question with 503 `question_rate_limit_unavailable` (fail
closed). Verified locally: the refused request costs 2 database calls (Auth + the quota attempt),
an answered one 43, so nothing about the season is read before the refusal. The owner picks one
path **before** any deploy. Nothing in this section was run on hosted.

### Path A — Postgres store (recommended; owner approval required)

1. Owner approves migration `20261106090000_rag_question_rate_limit.sql` for the hosted database.
2. Read-only check of the hosted migration history and of the dependencies the migration uses
   (`auth.users`, schema `private`, role `service_role`), **and the role preflight, part 1
   (§5.1). It is mandatory: if it fails, stop here.**
3. In its own, separately approved change window: apply that one migration on hosted. Nothing
   else in the same step (one migration, verify, then the next).
4. Verify: `private.rag_question_events` exists with RLS enabled + forced and no policy; function
   `private.consume_rag_question_quota(uuid, integer, integer)` exists, is SECURITY INVOKER with
   `search_path=""`; no EXECUTE for `anon` / `authenticated`; `scripts/ci/db_audit.py` against the
   committed snapshot has no drift for these objects; **role preflight, part 2 (§5.1) passes.**
5. Fail-closed and recovery check on an isolated stack with the same versions (not on
   production): function missing → 503; function back → 200.
6. Only then deploy the code of #92 + #95, following the merge / release plan the owner approved.
   Before the running container is replaced, run the offline configuration check **in the
   candidate image** with the production env-file and no network:
   `docker run --rm --network none --env-file <api env-file> -v <approved ids file>:/run/cohort.txt:ro --entrypoint python <candidate image> -m rag_qa_preflight --expect-user-ids-file /run/cohort.txt`
   (the ids file is mounted read-only; without the mount the check stops with a USAGE error).
   It must print `RAG-QA-PREFLIGHT PASS (configuration only)`. It refuses `*`, an empty or
   malformed cohort, a cohort that differs from the approved set, the action tier, a provider or
   its credential variables, a store other than `postgres`, bad limits, a Carbon parameter file
   that does not load, a non-numeric `RAG_RETRIEVAL_MIN_FUSED_SCORE`, and settings main.py
   needs to wire Q&A. A malformed cohort or limit makes main.py fail at import, which stops the
   **whole** API, so this check comes first. PASS is configuration only: database, Auth and
   network readiness are shown by the candidate's start-up log and the smoke, not by it.
7. Production smoke (one QA account, within its quota): READ answers 200 with `llm_calls 0`;
   recommend 503 `action_tier_disabled`; question 11 within a minute 429 with `Retry-After`;
   another QA account is not affected; a cohort account asking about another tenant's season gets
   404; a signed-in account outside the cohort gets 403 `question_not_enabled`; an invalid JWT
   gets 401; `rag_qa_log_summary.py` over the
   smoke window shows no alert; p50 / p95 measured on production (not inferred from local).
8. Only then open Q&A to the approved QA cohort (A-1).

### 5.1 Database role preflight (mandatory for Path A; read-only; PREPARED, NOT EXECUTED on hosted)

**Which role runs the quota function.** The API calls `private.consume_rag_question_quota` over its
own `SUPABASE_DB_URL` (`infrastructure/pg_pool.py`: no `SET ROLE`, no PostgREST). So the login
in that URL executes it. It is **not** PostgREST's `service_role`. The function is SECURITY
INVOKER, and the table forces RLS with no policy. That login therefore needs:

- `BYPASSRLS` (or superuser). Without it every first insert fails with "new row violates
  row-level security policy", and the API answers **every** question with 503
  `question_rate_limit_unavailable` (fail closed, nothing read).
- EXECUTE on the function, USAGE on schema `private`, and SELECT, INSERT and DELETE on the
  table. As the owner of both objects it holds these implicitly.

The migration's EXECUTE grant to `service_role` is not what the API uses. `service_role` has no
table privilege, so a call as `service_role` fails.

Local evidence (isolated stack, 2026-11-24, branch head of #95), `tests/test_rag_question_rate_limit_db.py`:
- `test_the_backend_login_runs_the_function_and_meets_its_requirements`: the local login is not superuser, has `BYPASSRLS` and owns the table and the function. The table forces RLS, has 0 policies, and the function is not SECURITY DEFINER.
- `test_the_postgrest_service_role_is_not_the_role_that_runs_it`: a call as `service_role` gets "permission denied for table".
- `test_a_login_without_bypassrls_fails_closed_before_any_read`: a fresh role with every grant except `BYPASSRLS` is refused by RLS, the service answers 503 `question_rate_limit_unavailable`, and 0 events are written. The role exists only inside a rolled-back transaction.
- Mutation: giving that role `BYPASSRLS` makes the test fail, because the call then succeeds.
- The 15 existing tests (atomicity under 30 concurrent connections, sliding windows, `Retry-After`, `anon` / `authenticated` denied) pass in the same run.

**How to run it (owner-authorized; never by an agent on hosted).** Connect with the API's own
database URL (the same login the API uses), in a read-only session
(`PGOPTIONS='-c default_transaction_read_only=on'`), one transaction ending in `rollback`. No
role, grant, policy or data is created. Record the output without the URL or any credential.

```sql
begin read only;
-- part 1, before the migration
select current_user, session_user;
select rolsuper, rolbypassrls from pg_roles where rolname = current_user;
select has_schema_privilege(current_user, 'private', 'usage') as private_usage;
-- part 2, after the migration
select pg_get_userbyid(c.relowner) as table_owner, c.relrowsecurity, c.relforcerowsecurity,
       (select count(*) from pg_policies where schemaname = 'private' and tablename = 'rag_question_events') as policies
  from pg_class c where c.oid = 'private.rag_question_events'::regclass;
select pg_get_userbyid(p.proowner) as function_owner, p.prosecdef
  from pg_proc p where p.oid = 'private.consume_rag_question_quota(uuid,integer,integer)'::regprocedure;
select has_function_privilege(current_user, 'private.consume_rag_question_quota(uuid,integer,integer)', 'execute') as can_execute,
       has_table_privilege(current_user, 'private.rag_question_events', 'select') as can_select,
       has_table_privilege(current_user, 'private.rag_question_events', 'insert') as can_insert,
       has_table_privilege(current_user, 'private.rag_question_events', 'delete') as can_delete;
select has_function_privilege('anon', 'private.consume_rag_question_quota(uuid,integer,integer)', 'execute') as anon_exec,
       has_function_privilege('authenticated', 'private.consume_rag_question_quota(uuid,integer,integer)', 'execute') as authenticated_exec;
rollback;
```

**Pass:** `rolsuper` or `rolbypassrls` is true; `relforcerowsecurity` true; `policies` 0; `prosecdef`
false; `can_execute`, `can_select`, `can_insert`, `can_delete` all true; `anon_exec` and
`authenticated_exec` false. Part 1 must pass before the migration is applied, part 2 before the
code is deployed.

**If the API login is incompatible (for example no `BYPASSRLS`): rollout stays BLOCKED.** Do not
grant `BYPASSRLS`, disable or relax RLS, switch the function to SECURITY DEFINER or add a
permissive policy as a quick fix. A least-privilege remediation needs its own migration, review
and approval. The proposal, in order of preference:

1. **A policy scoped to the API login only.** Add a policy on `private.rag_question_events` for
   that one role (`for all to <api_login> using (true) with check (true)`) plus explicit
   SELECT, INSERT and DELETE grants. Keep FORCE RLS and the revokes from `public`, `anon` and
   `authenticated`. The table holds only user id + timestamp, and only this function touches it.
   No role gains BYPASSRLS anywhere else.
2. **A dedicated NOLOGIN owner role** that owns the table and a SECURITY DEFINER version of the
   function (`search_path=''`), with EXECUTE granted only to the API login. This changes the
   function's security mode, so it needs a separate security review.

Path B (memory store) needs no database role and is unaffected.

### Path B — memory store (alternative; never the default)

Only if the owner chooses it explicitly and confirms that production runs exactly **one** API
process / worker, accepts that every restart resets the counts, and accepts that the limit is not
durable. Set `RAG_QA_RATE_LIMIT_STORE=memory` in the API environment before the deploy. The API
never falls back to memory on its own: if Path B was not chosen and the migration is missing, the
API stays fail-closed.

### Rollback order

1. Switch Q&A off first (Caddy 503 route or `RAG_QA_ENABLED=false` + container re-create).
   Never roll back the quota schema while Q&A is serving.
2. Then, if the schema must go: run
   `supabase/rollbacks/20261106090000_rag_question_rate_limit.down.sql` by hand, in one
   transaction, then `supabase migration repair --status reverted 20261106090000`. The table
   holds only user id + timestamp for the last 24 h; check the retention / rollback policy
   before dropping a table that has rows.
3. Code rollback of #95 does not need the schema rollback (the table is unused without it).
4. Back on: re-apply the migration (or set Path B), verify as in Path A step 4, then switch Q&A
   on again. Rehearsed locally: down 16 ms → 503 → re-apply → 200; on the integration trial the
   E5.2 → E5.1 → rate-limit rollback and re-apply also left `db_audit` and the lifecycle probe
   (36/36) passing.

### Panel visibility (V-1b): deploy and rollback order

`VITE_AI_QA_ENABLED` is a build-time flag for the whole site. Since V-1b the web shows the panel only
when that flag is on AND `GET /v1/me` returned `ai_qa_available: true` for the current session, so
accounts outside `RAG_QA_ALLOWED_USER_IDS` do not see the feature at all (they would still get 403
`question_not_enabled` on a direct call).

1. Deploy the API with the capability field (and the Q&A env, preflight PASS) first.
2. Then build the web with `VITE_AI_QA_ENABLED=true` from a commit that contains V-1b.
3. A V-1b web against an older API (no field) hides the panel for everybody: safe, never open.
4. Rollback: never redeploy a web build that predates V-1b with `VITE_AI_QA_ENABLED=true` — it
   shows the panel to every signed-in user. Roll the web back to a V-1b build, or build with the
   flag off. Rolling the API back to one without the field hides the panel (fail closed).
5. The cohort is read at API start-up: removing an account means re-creating the API container
   with the new `RAG_QA_ALLOWED_USER_IDS` (after the preflight). An open tab then hides the panel
   at its next `/v1/me` re-check (window focus, tab shown again or token refresh; at most once a
   minute). Until then any question it sends gets 403; nothing is answered.

## 6. QA cohort and acceptance runs

The limit counts per **signed-in account**, not per person or device. Testers sharing one QA
account (for example the DEMO-FARM-01 farmers) share its 10 questions per minute. The earlier
acceptance suites (31 API cases, 30 Carbon cases, 20 browser cases) ask questions back to back
from one account and will hit 429 under the default limits.

* Acceptance on an isolated stack: give each tester or suite its own account, or raise
  `RAG_QA_RATE_LIMIT_PER_MINUTE` / `_PER_DAY` in that stack's API environment for the run.
* Production smoke: plan it within 10 questions per minute per account (step 7 asks exactly
  one question over the limit). Changing production limits for a smoke is an owner decision.
* CI cannot catch this: its Playwright runs on mock data.
