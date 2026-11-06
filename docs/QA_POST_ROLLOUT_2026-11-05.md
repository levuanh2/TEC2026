# Post-rollout QA — 2026-11-05

Scope: the production rollout of 2026-11-05, which had three parts:
- PR #13: RLS migration `20261104090000`, applied to hosted;
- PR #16: integration of #12 (query cache, lazy routes) and #15 (role verified by `/v1/me`);
- a Render static-site deploy of `71409ea`.

Production: https://agricarbon.info.vn (frontend), https://api.agricarbon.info.vn (FastAPI on EC2), Supabase hosted.

**Release gate: `PRODUCTION CONDITIONAL — AUTHENTICATED QA PENDING`.** No QA credentials were available to this run, so every flow that needs a real Manager or Farmer login is `BLOCKED_CREDENTIALS` below. Nothing marked PASS here was inferred from mock data.

> **Correction and status update, 2026-11-06 (Release R3).** This section was added after the fact. The text below it is kept as written on 2026-11-05.
>
> - **No pull request in this release had a human review.** #12–#19 were all merged by `levuanh2` with `--admin`, with **0 reviews** on GitHub, while `main` requires 1 approving review (`enforce_admins` is off, so an admin can bypass it). The review request to SiriusNoPro is still open on every one of them. The table in §6 lists each merge.
> - Where this report says "a separate read-only review with verdict APPROVE", that review was written by **an AI agent (agy)**, not by a person. It is evidence of a check. It is not an approval, and it does not replace a human review.
> - The R3 re-review (also by an AI agent, Claude Code) found 2 Medium and 4 Low issues in the #17-era session code that the agy report did not list. None is Critical or High. Fixes are on a separate branch that is waiting for human review. See [`SECURITY_REVIEW_R3_2026-11-06.md`](SECURITY_REVIEW_R3_2026-11-06.md).
> - Status flags: **`HUMAN_REVIEW_PENDING`** (#13, #15, #16, #17 and #18 change Auth/RBAC/RLS behaviour) and **`AUTHENTICATED_QA_PENDING`** (no QA credentials file on 2026-11-06 either: `BLOCKED_CREDENTIALS`).

## 1. Rollout facts

| Item | Value |
|---|---|
| main | `71409ea` (merge of #16); CI 17/17 green; `ec5e81f` (merge of #13); CI green |
| Migration | `20261104090000`, applied 2026-11-05 07:57:40Z, hosted history 25 rows |
| Frontend | Render static site, live at commit `71409ea` |
| Backend | unchanged (no EC2 rebuild in this rollout) |

## 2. Status by area

| Area | Check | Status | Evidence |
|---|---|---|---|
| Database | Migration history, catalog = `schema-audit.json` on main | PASS | read-only post-apply check |
| Database | Live policies = per-row definition on `activities` + 7 detail tables, 14 identities | PASS | 0 mismatches |
| Database | Password-change guard, ended membership, removed farm role | PASS | rolled-back transaction; reads drop to 0 |
| Database | `anon` on the 8 tables | PASS | no grant |
| Database | Rollback readiness | PASS | down migration tested on an isolated stack; catalog back to identical with main |
| API | Health, CORS (only the site origin), protected routes answer 401 without a token | PASS | `/health` 200; a foreign origin gets 400 |
| API | 5xx / statement timeouts in the container log, last 4 h | PASS (low traffic) | 0 × 5xx, 0 timeouts; 83 × 200 |
| Frontend | Served build = `71409ea`; HTTPS redirect; SPA deep links | PASS | |
| Frontend | No secret in the bundle (no service-role key, no DB URL; publishable key only) | PASS | bundle scan |
| Frontend | Stale session + cached Manager hint never paints a business shell | PASS | old build: farmer → management → login with 5 × 401; new: verifying → login with 1 × 401 |
| Frontend | Unauthenticated loads: 0 JS errors, 0 failed requests | PASS | |
| Frontend (synthetic API, real build) | `carbon-status` 503: retried at most twice (3 requests); other sources load | PASS | |
| Frontend (synthetic API, real build) | Bug A: no "Không có việc nào cần xử lý" while a source failed | PASS | shows "Chưa đọc được trạng thái Carbon, nên chưa thể kết luận…" |
| Frontend (synthetic API, real build) | Back navigation inside the stale window served from cache | PASS | 0 API calls on back; a reload refetches |
| Frontend (synthetic API, real build) | 300 px lazy table | INCONCLUSIVE | with empty synthetic data the page was not taller than the viewport; covered by unit tests only |
| Frontend | Route chunk fails to load (after a deploy, or offline) | **FAIL on `main`** → fixed in PR #18 | blank page (`#root` empty) reproduced on the `main` build |
| Manager | Login/logout, `/v1/me`, Dashboard 27 seasons, Carbon overview, MRV, data gaps, farms/plots, performance, menu, Back, refresh, stale warning + retry | BLOCKED_CREDENTIALS | runner ready (§5) |
| Farmer | Login/logout, farm scope, plots, seasons, journal, Carbon readiness, navigation, refresh, no out-of-scope data | BLOCKED_CREDENTIALS | runner ready (§5) |
| Cache & auth | Manager → logout → Farmer and back, cache isolation between real accounts | BLOCKED_CREDENTIALS | covered by unit and integration tests only |
| Performance | Dashboard time-to-stable, authenticated `carbon-status` p50/p95 | BLOCKED_CREDENTIALS | SQL-level numbers in §3 |

## 3. Performance after the migration

The figures separate the network, FastAPI, SQL and the frontend. All runs were sequential from one machine in Vietnam.

**Network and FastAPI** (20 requests each, new connection per request):

| Target | TCP | TLS | Server + 1 RTT | Total p50 / p95 |
|---|---|---|---|---|
| API `/health` | 322 ms | 333 ms | 381 ms | 1047 / 1170 ms |
| API `/v1/carbon/scenarios` | 324 ms | 333 ms | 324 ms | 993 / 1004 ms |
| Frontend `index.html` (Render CDN) | 28 ms | 46 ms | 61 ms | 149 / 186 ms |

The round trip to the API host is about 320 ms from this location, and FastAPI's own processing on these routes is under about 60 ms. A cold request is network-bound (TCP + TLS + 1 RTT). This is not evidence for or against changing the EC2 region, which would need measurements from the users' locations.

**SQL under RLS**, as `authenticated` with the user's claims, read-only. The figures include a ~95 ms round trip to the pooler. p50 / p95, n = 10:

| Read | Manager, HTX-DEMO-001 | Farmer QA |
|---|---|---|
| `activities` (changed by the migration) | 261 / 361 ms (258 rows); was 3.7 s | 108 / 123 ms; was ~5.5 s |
| `fertilizer_applications` | 122 / 179 ms; was 6.0 s | 120 / 122 ms |
| `crop_seasons`, `plots`, `farms` | 110–124 ms | 107–113 ms |
| `production_batches` (per-row policy, unchanged) | 486 / 546 ms (27 rows) | **669 / 681 ms (2 rows)** |

**Remaining per-row RLS hotspots** (not changed; candidates for the same set-based pattern), Manager, filtered the way the API reads them, n = 5:

| Read | Time | Rows |
|---|---|---|
| `production_batches` for the org's seasons | ~326 ms | 27 |
| `carbon_calculations` for the org's seasons | ~314 ms | 25 |
| `carbon_breakdowns` for those calculations | ~959 ms | 50 |

Unfiltered, they take 2.1 s (`carbon_calculations`) and 4.3 s (`carbon_breakdowns`) for both roles, even when the farmer sees 0 rows. `carbon-status` itself reads the calculations through the owner connection, so it does not pay this RLS cost.

Follow-up, the same day (read-only `EXPLAIN ANALYZE`, rolled back): which of these a user actually waits on, and what the set-based form would save.
- The API reads `production_batches` and `carbon_calculations` under RLS (`read_repo` through PostgREST: Manager rollups and the season hub). Server time for the Manager's 27 seasons: 235 ms and 227 ms; with a `readable_crop_ids()` predicate, 12.6 ms and 25.6 ms. 0 visibility mismatches for 14 identities.
- No API path reads `carbon_breakdowns` under RLS (only `pg_carbon_repo`, owner connection). Its 959 ms / 4.3 s does not reach users today.
- The farmer's 669 ms above is the unfiltered table read. Filtered by the farmer's own seasons, as the API reads it, it takes ~10 ms of server time either way. Full-table scans say nothing about the filtered endpoints.
- A candidate migration (`20261105090000`, not applied, not in a PR) is on the local branch `perf/rls-set-based-batch-carbon-reads`.

**Frontend, unauthenticated login page** (8 interleaved rounds):

| Load | p50 | p95 | Transferred |
|---|---|---|---|
| Cold | 788 ms | 1613 ms | 181 KB |
| Warm | 232 ms | 273 ms | – |
| Fast 3G cold (n = 5) | 3.18 s | 6.64 s | – |

The "hard refresh" variant still transferred 1 KB, so it did not bypass the cache, and it is not reported as a hard-refresh figure. No before/after speed claim is made for the frontend: the old build is no longer served, so an interleaved comparison is not possible.

## 4. Follow-up PRs

| PR | Purpose | Status |
|---|---|---|
| #18 `fix/web-chunk-load-recovery` | Error boundary, retry and a single bounded reload for route chunks that fail to load (P1) | Follow-up `35dd20a`: unsaved input in React-controlled fields was not detected (React 19 keeps `defaultValue` equal to `value`), fixed with edit tracking. CI 17/17; real-Chrome swap test 5/5 on the new head (the added React-style case fails on the old head); review requested |
| #17 `feat/web-session-revalidation` | Re-check `/v1/me` on focus, visibility and token refresh | Review found and fixed 3 bugs (cross-tab sign-in of another person, stale writes after a cache clear, hung re-check). Follow-up `0828f05`: tests for a re-check still pending at sign-out, at a cross-tab sign-in and at a token refresh, and for a Management read in flight when the scope changes. CI 17/17; review requested |

#17 and #18 both touch `App.tsx`. Whichever merges second needs one conflict hunk resolved (wrap the Farmer boundary with `key={scopeEpoch}`) and two mock lines added to `chunkRecoveryApp.dom.test.tsx`. Trial merge main + #18 (`35dd20a`) + #17 (`0828f05`) with that resolution: build passes, Vitest 87 files / 678 tests, Playwright (mock) 111/111.

### Release, 2026-11-06

Both PRs were merged with `--admin` as an owner-authorized exception, because the required reviewer had not responded. This is **not** an independent approval. The conditions are recorded on each PR: admin executor, verified HEAD, required CI 17/17, a separate read-only review with verdict APPROVE (0 critical, 0 major), and local gates.

*(R3 note: the "separate read-only review" was an AI agent's report (agy), not a person's. No human has reviewed #17 or #18. See §6.)*

| PR | Merge commit | Render deploy | Production check |
|---|---|---|---|
| #18 | `a2f4801` | `dep-dbmch5e1egvs73andcvg`, entry `index-Dz1ntsjT.js` | CDN, origin and browser serve the new entry. All lazy chunks return 200. No service-role key, DB URL or JWT in the bundle. The real bundle with browser-side interception: a chunk 404 shows the retry UI without a reload; a newer build triggers exactly one reload and no loop; unsaved input prevents the reload |
| #17 | `654f95c` | `dep-dbmcstd9fdbs73ckg6e0`, entry `index-YKjxTk3n.js` | Same checks as #18, plus revalidation on the real bundle with a fake session answered in the browser. A focus within 60 s sends nothing; a burst after 60 s sends one `/v1/me`; a role change shows the Farmer UI and sends no Management read; a 403 shows the neutral screen. The #17 build in real Chrome with two tabs: a sign-in by another person, a sign-out while a re-check is pending, and a late answer after a switch never show the old role |

The conflict was resolved as described above. After the merge: Vitest 87 files / 679 tests, Playwright (mock) 111/111.

Rollback (Render static site): to `dep-dbmch5e1egvs73andcvg` (`a2f4801`, #18 only), or to `dep-dbm3otd9fdbs73bp12i0` (`71409ea`, before both). After a deploy or rollback, wait until `https://agricarbon.info.vn/` names the expected `index-*.js` (Cloudflare `s-maxage=300`) before asking users to reload.

Authenticated QA with real Manager and Farmer accounts has **not** run, because no credentials have been provided. The release status stays **PRODUCTION CONDITIONAL — AUTHENTICATED QA PENDING**.

## 5. How to run the authenticated QA (pending)

`.tmp/post-rollout-qa/run_real_qa.sh` is a local file, not committed. It runs the existing read-only real specs (`web-real-data`, `farmer-real-data`, `round4-real`, `round44-real`, `sidebar-parity-real`) against production. A self-test with a fake Playwright (`test_run_real_qa.sh`) checks each point below.

- Fails when a test fails: Playwright's exit status survives the log pipeline (`pipefail`); a run in which no test executed fails too.
- One worker, no retries. The MRV export tests stay disabled, because they write a record.
- Runs only the audited spec files: it refuses when a spec, its helpers or the real config changed since the read-only audit (sha256 pinned).
- Credentials are read only from a file **outside the repository** (default `~/.agricarbon-qa.env`), parsed as plain `KEY=VALUE` lines with four allowed keys; nothing in the file is executed. The file is kept unless `--delete-env-after` is passed.
- Traces are off. Passwords, JWTs, Bearer/Authorization values and token fields are redacted from the log, and the failure artifacts are scrubbed and re-checked. Results go outside the repository.

## 6. Review and merge record (added 2026-11-06, R3)

From GitHub on 2026-11-06. Branch protection on `main`: 1 approving review required, code-owner review required, stale reviews dismissed, `enforce_admins` off.

| PR | Area | Merge commit | Merged (UTC) | By | Human reviews | AI review |
|---|---|---|---|---|---|---|
| #13 | **RLS** (migration `20261104090000`, applied to hosted) | `ec5e81f` | 2026-11-05 07:48 | levuanh2, `--admin` | 0 | agy (read-only) |
| #12 | Web query cache, lazy routes | `8aedb3d` | 2026-11-05 08:12 | levuanh2, `--admin` | 0 | — |
| #15 | **Auth/RBAC** (role verified by `/v1/me`) | `8aedb3d` | 2026-11-05 08:12 | levuanh2, `--admin` | 0 | — |
| #16 | Integration of #12 + #15 | `71409ea` | 2026-11-05 08:12 | levuanh2, `--admin` | 0 | — |
| #18 | Chunk-load recovery | `a2f4801` | 2026-11-05 18:10 | levuanh2, `--admin` | 0 | agy (read-only), APPROVE |
| #17 | **Auth/RBAC** (open-tab `/v1/me` re-check, cache isolation) | `654f95c` | 2026-11-05 18:35 | levuanh2, `--admin` | 0 | agy (read-only), APPROVE |
| #19 | Docs (this report) | `1e720e5` | 2026-11-05 18:55 | levuanh2, `--admin` | 0 | agy (read-only) |
| #21 | **Auth** (R3 security fixes F1–F6) | `48a5a2a` | 2026-11-06 | levuanh2, owner-authorized `--admin` (only the required review was missing; CI 17/17; head pinned) | 0 | Claude Code (author); human review pending in #24 |

A review request to SiriusNoPro is open on #17, #18, #19 and #20. #13, #15 and #16 had none; R3 requested one (2026-11-06). SiriusNoPro has write access and is not a code owner. The web source (`web-dashboard/src/**`) is not a code-owned path, so an approval by SiriusNoPro satisfies the review rule for a PR that changes only that path.

## 7. Release R3 status (2026-11-06)

| Area | Status | Evidence |
|---|---|---|
| `main` | `1e720e5`. CI `42088924919` and Strict CI (nightly) `42133051409` green | GitHub Actions |
| Production frontend | Render `dep-dbmp3eu1egvs73d85g60` live at `48a5a2a` (#21), entry `index-Xl7lm6cM.js`, deployed 2026-11-06. Before: `dep-dbmcstd9fdbs73ckg6e0` at `654f95c` (rollback target) | Render API; `curl https://agricarbon.info.vn/` |
| Rollback targets | `dep-dbmch5e1egvs73andcvg` (`a2f4801`, #18 only), then `dep-dbm3otd9fdbs73bp12i0` (`71409ea`) | unchanged from §4 |
| HTTPS and redirects | PASS. `http://` → 301 `https://`; `www` → 301 apex; API `http://` → 308 | `curl -I` |
| Bundle | PASS. 10 of 10 lazy chunks 200; no service-role key, DB URL or secret key; publishable key only | downloaded and scanned |
| API | PASS. `/health` 200; `/v1/me`, `/v1/farmer/scope`, `/v1/organizations`, `/v1/farms` → 401 without a token and with an invalid one; CORS allows only `https://agricarbon.info.vn`, a foreign origin's preflight → 400 | `curl` |
| Frontend in real Chrome, no credentials | PASS, 6 of 6. Cold, warm and deep-link loads: 0 JS errors. A fake expired session with a cached Manager hint goes verifying → login with one 401 (`/v1/me`). Chunk recovery (404 → retry UI; a newer build → exactly one reload; unsaved input → no reload) and the re-check (throttle, role change, 403) were run with browser-side interception | `.tmp/release-r2/prodsmoke/` (local) |
| Hosted migration history and RLS | PASS. 25 rows, last `20261104090000`, equal to the 25 files on `main`. 026 not applied (`private.readable_crop_ids` absent). `activities_select` is set-based; `production_batches_select` and both `carbon_calculations` SELECT policies are still per-row | read-only session (`transaction_read_only=on`), 2026-11-06 |
| API 5xx in the container log | Not checked in R3: reading the EC2 log needs the user to run `.tmp/rls-20261104090000/ec2_error_counts.sh` | — |
| Frontend security headers | **Open (Medium, hardening)**: only `X-Content-Type-Options`; no HSTS, CSP, `frame-ancestors`/`X-Frame-Options` or `Referrer-Policy`. A staged plan was measured on the production bundle (0 CSP violations with the full policy enforced; framing refused) and is in **#23, not applied** | finding F7; #23 |
| `render.yaml` | **Merging a change to it is a production rollout.** The Render Blueprint `tec` has `autoSync: true` on `main`, and `agricarbon-web-staging` is the production site. The file is not code-owned | Render API, read-only |
| Security review | **`HUMAN_REVIEW_PENDING`**. AI-prepared package with findings F1–F11 and a reviewer checklist. The scope of the human review is #21 **plus #13 (RLS, applied to hosted) and #15/#16 (role verification)**: approving #21 alone does not complete it | [`SECURITY_REVIEW_R3_2026-11-06.md`](SECURITY_REVIEW_R3_2026-11-06.md) |
| Security fixes | **F1–F6 fixed and deployed** (#21, merged `48a5a2a` by owner-authorized admin exception; independent human review pending). Final F4 design: local first, at once; only a 2xx from `/logout` confirms; bounded retry; the other tabs end. Vitest 727/727, Playwright mock 111/111, real Chrome 16/16 (old build 5/16), mutation 40/40; browser smoke on the deployed bundle 8/8 | PR #21; security review §11 |
| Manager and Farmer real QA, cross-account isolation | **`BLOCKED_CREDENTIALS` / `AUTHENTICATED_QA_PENDING`**. `~/.agricarbon-qa.env` does not exist. The runner was re-audited: self-test 24/24, specs unchanged since the audit (sha256), 1 worker, traces off, no write spec | `.tmp/post-rollout-qa/` (local) |
| Authenticated endpoint p50/p95 | `BLOCKED_CREDENTIALS` | — |
| PR #20 (migration 026) | Draft. **NO-GO / INSUFFICIENT ENDPOINT EVIDENCE**. The SQL review passes (same access as the per-row helpers) and CI is green; the gain is proven only at query level | PR #20 review comment |

**Release gate: `PRODUCTION CONDITIONAL`.** Human review is not done, authenticated QA has not run, and no Critical or High regression is confirmed. The production build contains the Medium findings F1 and F4 until the fix PR is reviewed and deployed. The conditions for PRODUCTION PASS, with their status, are in §10 of the security review.

## 8. Review rule for future Auth, RBAC and RLS pull requests

A pull request is in scope when it changes any of these:
- sign-in, sign-out, session restore or token handling (`web-dashboard/src/api/auth.ts`, `client.ts`, `utils/supabase.ts`, the session and role parts of `App.tsx`);
- role or scope resolution (`me.ts`, `/v1/me`, `memberships.py`);
- what is cached per user or scope;
- any FastAPI authorization check;
- any RLS policy, `private.*` helper, grant or migration under `supabase/migrations/`.

1. **A human approves it before it is merged.** The approval is a GitHub review by a person with authority (SiriusNoPro, or a code owner for code-owned paths). An AI review (agy, Claude, Codex) can be attached as evidence. It is never counted as the approval, and the PR text must call it an AI review.
2. **No `--admin` merge for these PRs.** If the owner still decides on an emergency exception, a comment on the PR says so in so many words ("owner-authorized exception, not reviewed"), the release gate cannot be higher than `PRODUCTION CONDITIONAL`, and a human review is requested again after the merge, with this status shown as `HUMAN_REVIEW_PENDING` until it lands.
3. **Fail-closed tests, proven by mutation.** Every guard the PR adds or relies on has a test that fails when the guard is removed. The PR lists the guards and the result of removing each one.
4. **Evidence beyond mocks.** At least one test runs the real library at the boundary (for example the real auth-js client with a fake network), plus a real-browser run for multi-tab behaviour. A PR that changes data visibility also needs an equivalence check per identity on an isolated stack.
5. **Hosted changes are separate decisions.** Merging a migration does not approve applying it. Each hosted apply needs its own owner approval, a preflight, a backup, a post-check and a tested rollback (see `MIGRATION_HISTORY.md`).
6. **The release record keeps the difference.** Release reports say "human review", "AI review" or "none" for each PR, and never upgrade an AI review or an admin merge into an approval.
