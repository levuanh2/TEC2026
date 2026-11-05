# Post-rollout QA — 2026-11-05

Scope: the production rollout of 2026-11-05, which had three parts:
- PR #13: RLS migration `20261104090000`, applied to hosted;
- PR #16: integration of #12 (query cache, lazy routes) and #15 (role verified by `/v1/me`);
- a Render static-site deploy of `71409ea`.

Production: https://agricarbon.info.vn (frontend), https://api.agricarbon.info.vn (FastAPI on EC2), Supabase hosted.

**Release gate: `PRODUCTION CONDITIONAL — AUTHENTICATED QA PENDING`.** No QA credentials were available to this run, so every flow that needs a real Manager or Farmer login is `BLOCKED_CREDENTIALS` below. Nothing marked PASS here was inferred from mock data.

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
| #18 `fix/web-chunk-load-recovery` | Error boundary, retry and a single bounded reload for route chunks that fail to load (P1) | CI 17/17; real-Chrome swap test passes; review requested |
| #17 `feat/web-session-revalidation` | Re-check `/v1/me` on focus, visibility and token refresh | Review found and fixed 3 bugs (cross-tab sign-in of another person, stale writes after a cache clear, hung re-check); review requested |

#17 and #18 both touch `App.tsx`. Whichever merges second needs one conflict hunk resolved (wrap the Farmer boundary with `key={scopeEpoch}`) and two mock lines added to `chunkRecoveryApp.dom.test.tsx`. A trial merge with that resolution passes 87 files / 673 tests.

## 5. How to run the authenticated QA (pending)

`.tmp/post-rollout-qa/run_real_qa.sh` is a local file, not committed. It runs the existing read-only real specs (`web-real-data`, `farmer-real-data`, `round4-real`, `round44-real`, `sidebar-parity-real`) against production.

- One worker.
- The MRV export test is disabled, because it writes a record.
- Traces are off; screenshots are taken only on failure, and password fields are masked.
- Credentials are read only from a file **outside the repository** (default `~/.agricarbon-qa.env`). The runner deletes that file when it finishes and refuses a file inside the repository.
