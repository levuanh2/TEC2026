# Production acceptance — Release R3 (2026-11-06)

**Release gate: `PRODUCTION CONDITIONAL`.**
**Flags: `AUTHENTICATED_QA_PENDING` · `HUMAN_SECURITY_REVIEW_PENDING`.**

Production is up and serves the intended build. No Critical or High finding is open. Two conditions for `PRODUCTION PASS` are still missing:
- authenticated QA with real Manager and Farmer accounts;
- a human security review.

An AI agent (Claude Code) prepared this report on 2026-11-06. It is **not** a human review and it approves nothing. Four kinds of evidence appear below. They are kept apart and never added together:

| Kind | Meaning |
|---|---|
| **Automated** | CI, local test suites, and scripted probes and browser runs against production |
| **AI audit** | code and SQL read by an AI agent (Claude Code, agy) |
| **Owner smoke** | a manual check that the repository owner ran and reported |
| **Human review** | a verdict from a person who read the code |

Earlier records: [`SECURITY_REVIEW_R3_2026-11-06.md`](SECURITY_REVIEW_R3_2026-11-06.md) (findings F1–F11, reviewer checklist R1–R19, rollout record) and [`QA_POST_ROLLOUT_2026-11-05.md`](QA_POST_ROLLOUT_2026-11-05.md). Review tracking: issue [#24](https://github.com/levuanh2/TEC2026/issues/24).

## 1. Production topology

| Part | Where | Notes |
|---|---|---|
| Frontend | `https://agricarbon.info.vn`. The Render static site `agricarbon-web-staging` (`srv-danpuojm8hqs73c59fj0`), behind Cloudflare | `www` and `http://` answer 301 → `https://agricarbon.info.vn/`. `index.html` has `s-maxage=300` at the CDN. Auto-deploy is off; the security headers come from `render.yaml` (Blueprint `tec`, auto-sync) |
| API | `https://api.agricarbon.info.vn`. FastAPI in one container on EC2 `t3.small` (ap-southeast-2), behind Caddy | DB through the Supabase session pooler (IPv4). Not changed in R3 |
| Database / Auth | Supabase hosted `awazhdqzkktekbwaqiic` (ap-northeast-2) | Public sign-up disabled (`disable_signup=true`, email provider only). Migration history: 25 rows, the last is 025 (`20261104090000`). **026 not applied** |

## 2. Versions and deployment

| Item | Value | Checked |
|---|---|---|
| `main` | `27c6cfa51eb8672d87651802122730093c273be0` (merge of #25) | GitHub API, 2026-11-06 |
| Frontend deploy | `dep-dbmp3eu1egvs73d85g60`, **live**, commit `48a5a2a` (merge of #21), finished 08:37:38Z | Render API |
| Served entry | `index-Xl7lm6cM.js` + `index-sAaNetWj.css`, through the CDN | `curl` of `/` |
| `48a5a2a` → `27c6cfa` | Only two docs and `render.yaml` (25 lines of headers) changed. The headers reached production through Blueprint sync `exe-dbmpfuff3r2c73aln6m0`. **No frontend redeploy is needed** | `git diff --stat` |
| Migrations | 025 applied; 026 (#20, Draft) not applied | R3 record; not re-queried, because this run made no DB connection |

## 3. F1–F6 remediation

| ID | Severity | Status |
|---|---|---|
| F4 | Medium | Fixed in #21, deployed. Local sign-out happens first and the other tabs end with it; then the server revocation, which counts as confirmed only on a 2xx; the retry is bounded. **Residual risk, accepted by the owner:** if the server is never reached and the access token expires first, the refresh token stays valid on the server until it is used or revoked |
| F1 | Medium | Fixed in #21, deployed. The compared scope includes every membership and farm role |
| F2, F3, F5, F6 | Low | Fixed in #21, deployed |

Mutation check on the #21 head `e1cc238`: **40/40** guard positions killed. Details: R3 §5.

## 4. F7 (security headers): Stage 1 live

Today's live headers on `https://agricarbon.info.vn/` match `render.yaml` on `main` exactly:

| Header | Live value |
|---|---|
| `Strict-Transport-Security` | `max-age=300` |
| `Content-Security-Policy` (enforced) | `frame-ancestors 'none'; object-src 'none'; base-uri 'self'` |
| `Content-Security-Policy-Report-Only` | the full policy, with the font-handler hash |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | as in `render.yaml` |
| `X-Content-Type-Options` | `nosniff`, sent by Render. Not duplicated |

In the 6 browser runs of §6, the console showed **0** Report-Only CSP messages. Stage 2 (CSP enforced, HSTS 1 day) is **not approved and not deployed**; see §10.

## 5. Manual login/logout confirmation

`MANUAL_LOGIN_LOGOUT_SMOKE = PASS (owner-reported)`

On 2026-11-06 the repository owner signed in and out on `https://agricarbon.info.vn` and reported that both work correctly. This is an **owner smoke**, not an automated test. Two things it does not show:
- the exact on-screen confirmation text;
- which role shell was used.

It covers the one path that R3 could not verify without credentials: a real sign-out with a real session (R3 §11).

## 6. Automated checks against production (2026-11-06, no credentials)

These are read-only probes. The browser runs use a fake session in `localStorage`, and every API and Supabase call in them is answered inside the browser. **None of this is authenticated QA.**

| # | Check | Result |
|---|---|---|
| 1 | Main SHA = production lineage; CI on `27c6cfa` (run `42192183560`) | PASS |
| 2 | Strict CI (nightly) last run `42133051409` (`1e720e5`, 2026-11-05 23:55Z) | PASS. It has not run on `27c6cfa` yet; the only diff since `1e720e5` is docs, headers and the already-gated #21 |
| 3 | Render: frontend deploy live at `48a5a2a`; service not suspended | PASS |
| 4 | Domain + CDN: apex 200; `www` 301; `http` 301; SPA deep link `/management/dashboard` 200 | PASS |
| 5 | API `/health` 200 (engine `0.2.0`, EF config `0.3.0-ipcc2019-tier1-ar5`) | PASS |
| 6 | `/health` latency, 20 sequential requests from Vietnam, new connection each | p50 **887 ms**, p95 **976 ms**. Network-bound (≈320 ms RTT), in line with 2026-11-05 (1047 / 1170 ms) |
| 7 | Frontend entry + all 8 chunks it references: 200. A missing asset: 404 `text/plain` (no SPA fallback). No source map | PASS |
| 8 | Stage 1 headers = `render.yaml` (§4) | PASS |
| 9 | Bundle secret scan. Only the publishable key (`sb_publishable_…`); no JWT; no service-role key or DB URL. The one hit on `sb_secret_` is supabase-js's own key-prefix check | PASS |
| 10 | API authorization: 8 data routes (`/v1/me`, `/v1/farmer/scope`, `/v1/farms`, a foreign farm, `/v1/organizations`, `/v1/mrv/cases`, `/v1/emission-factor-sets`, a foreign farm's seasons) answer **401** with no token and with a forged token. `POST /v1/carbon/calculate` with no token: 401. `/v1/carbon/scenarios` is public by design: it returns the constant list `awd, continuous_flooding, as_recorded` and no data | PASS |
| 11 | CORS: the site origin is allowed; `https://evil.example` → 400, with no `Access-Control-Allow-Origin` | PASS |
| 12 | PostgREST with only the publishable key (anon): every one of the 45 tables returns no row. 43 → 401; `audit` → 404 (schema not exposed); `season_recommendations` → **200 with 0 rows** (see F12) | PASS (no exposure) |
| 13 | Browser: chunk 404 on the same build → retry UI, no reload; "Thử lại" loads MRV in place | PASS |
| 14 | Browser: a newer build is deployed → exactly one automatic reload, then the retry UI (no loop) | PASS |
| 15 | Browser: a newer build with unsaved input on the page → no automatic reload | PASS |
| 16 | Browser: cold, warm and deep-link loads without a session, 0 failed requests | PASS |
| 17 | Browser: fake expired session + cached Manager hint at `/dashboard` → `verifying` → `/login?next=%2Fdashboard`, one `/v1/me` (401); no business shell painted | PASS |
| 18 | Browser: open tab, focus after 60 s → one re-check; a role change → Farmer UI; then 403 → neutral screen | PASS |

Browser runs: **6/6 PASS** (Playwright, real Chrome, `https://agricarbon.info.vn`). R3's own production smoke of the same bundle was 8/8; that covers the sign-out 204/offline/hung/401/503 states and cross-tab sign-out.

**Not checked:** the EC2 container log (5xx, statement timeouts). Agents are not allowed to SSH into it. The owner can run `bash .tmp/rls-20261104090000/ec2_error_counts.sh 24h` (read-only).

## 7. Authenticated QA

**`AUTHENTICATED_QA_PENDING`.** On 2026-11-06, `~/.agricarbon-qa.env` does not exist. As instructed, nobody searched for passwords, created accounts or reset passwords.

Readiness, checked today:
- The runner `.tmp/post-rollout-qa/run_real_qa.sh` passes its self-test (all scenarios: strict `KEY=VALUE` parser, never sources the file, prints no password, keeps the file unless `--delete-env-after`).
- All 8 audited spec files still match their read-only audit hashes, both in the runner's checkout and on `main` `27c6cfa`.

Not run, because each needs real accounts:
- Manager and Farmer login;
- Dashboard 27 seasons, Carbon, MRV, farm scope;
- cache isolation between the two accounts;
- logout/login, Back, revalidation and error handling with real data;
- authenticated API p50/p95 and `carbon-status` timing.

**To unblock (owner, about 2 minutes).** Create the file **outside the repository**, then run the runner:

```
copy .tmp\post-rollout-qa\qa.env.example %USERPROFILE%\.agricarbon-qa.env
notepad %USERPROFILE%\.agricarbon-qa.env      # fill REAL_E2E_PASSWORD and FARMER_REAL_E2E_PASSWORD
bash .tmp/post-rollout-qa/run_real_qa.sh --delete-env-after
```

Only the four keys `REAL_E2E_EMAIL/PASSWORD` and `FARMER_REAL_E2E_EMAIL/PASSWORD` are accepted. The run is read-only, and its results go to `~/.agricarbon-qa-results/<stamp>/`, outside the repository.

## 8. Security acceptance checklist (scope: #13, #15/#16, #17, #18, #21, #25)

This is the single checklist for issue #24. Each column is separate evidence.
- `—`: no evidence of that kind exists.
- `BLOCKED`: the check needs QA credentials.
- **Human review is `PENDING` in every row:** on 2026-11-06, GitHub shows **0 reviews** on #13, #15, #16, #17, #18, #21, #22, #23 and #25, and no person has posted a verdict on #24.

| # | Property | Automated | AI audit | Owner smoke | Human review |
|---|---|---|---|---|---|
| S1 | **Server-side authorization.** Every data route needs a valid token; the client grants nothing | Prod probe §6 #10–12 (today); backend RLS/permission tests + CI `rls-security` job on an isolated stack | R3 P10 | — | PENDING (R8) |
| S2 | **User identity.** A `/v1/me` answer applies only to the live session and its own `user_id` | `accessScope.dom.test.tsx` (F3), `meRoleUnverified.dom.test.tsx`; mutation 40/40; prod #17 | R3 P1, F3 | Login works (role shell not reported) | PENDING (R1, R2) |
| S3 | **Session isolation.** One person never gets another person's data, token or retry | `sessionIdentity.test.ts`, `authReplacement.dom.test.ts`, `sessionReplacement.dom.test.tsx`; real Chrome two-tab 16/16 (local build, fake origins). Real accounts: BLOCKED | R3 P6, P7, F2 | — | PENDING (R4, R5, R19) |
| S4 | **Revoked permissions.** A lost role, membership or farm role drops the cached data | `accessScope.dom.test.tsx` (F1), `sessionRevalidation.dom.test.tsx`; prod #18 (synthetic); hosted rolled-back transaction 2026-11-05 (reads drop to 0) | R3 P8, F1 | — | PENDING (R3, R18) |
| S5 | **Logout when offline or timed out.** No "Bạn đã đăng xuất." without server confirmation; nothing restorable | `authSignOutRealClient.dom.test.ts` (real auth-js), `signOutNotice.dom.test.tsx`; R3 prod smoke 8/8; real Supabase `403 bad_jwt` → "not confirmed" | R3 P9, F4, F5 | Normal sign-out PASS (owner-reported) | PENDING (R6) |
| S6 | **Cross-tab sync.** A sign-out or sign-in in one tab ends or re-verifies the others | Two-tab real Chrome 16/16; R3 prod smoke (cross-tab sign-out) | R3 P6, R16 (owner product decision) | — | PENDING (R6, R10) |
| S7 | **Stale API responses.** A late answer never writes into a cleared or replaced session | Farmer data generation counter, TanStack `clear()`; mutation E6; `sessionReplacement.dom.test.tsx` | R3 P5 | — | PENDING (R19) |
| S8 | **Cache isolation.** Sign-out, expiry and takeover clear every session-scoped cache | Mutations E8, E9; `roleVerifiedQueryCache.dom.test.tsx`. Between real accounts: BLOCKED | R3 P4 | — | PENDING (R15) |
| S9 | **RLS privilege boundaries** (#13, applied to hosted) | 14-identity equivalence with 0 mismatches (run by an AI agent on 2026-11-05); anon probe today; rollback tested on an isolated stack | R3 §8 re-read of `readable_batch_ids()` | — | PENDING (R11–R13) |
| S10 | **Error states.** 0/401/403/5xx/timeout never assign a role; a chunk failure recovers | `meRoleUnverified.dom.test.tsx`; prod #13–15 chunk recovery; `carbon-status` 503 bounded retry (synthetic, 2026-11-05) | R3 P2, P3 | — | PENDING (R7, R14) |

**Owner self-review:** none recorded. If the owner reads the code and signs off, record it as `OWNER_SELF_REVIEW`. That is not an independent review.

**Verdict line for a human reviewer** (on #24, or a review on the PR concerned):
`HUMAN_REVIEW #<PR>: APPROVE | REQUEST_CHANGES — <name>, <date>`

The full item list is R1–R19 in `SECURITY_REVIEW_R3_2026-11-06.md` §6 and §8.

## 9. CI evidence

| Run | Commit | Result |
|---|---|---|
| CI `42192183560` | `27c6cfa` (`main`, #25) | success |
| CI `42191211950` | `2b6295d` (`main`, #22) | success |
| CI `42187031841` | `48a5a2a` (`main`, #21, the deployed frontend) | success, 17 jobs |
| Strict CI (nightly) `42133051409` | `1e720e5` | success. The nightly runs of 11-03, 11-04 and 11-05 are green; 11-01 (`41357792331`) failed and the later runs on the same commit passed |

## 10. Known risks and limitations

| ID | Severity | Item | Disposition |
|---|---|---|---|
| — | Process | No human review on any PR from #12 to #25. The only code owner is the author, and `enforce_admins` is off, so every merge was an admin merge | Open: #24. A second human code owner is the owner's decision |
| — | Process | Authenticated QA has never run since the R2/R3 changes | Open: §7 |
| F4 residual | Low | The refresh token can outlive a sign-out that never reached the server | Accepted by the owner; the UI warns |
| F7 Stage 2 | Medium (hardening) | CSP only partly enforced (Report-Only for scripts and connections); HSTS 300 s | Frozen. Earliest proposal 2026-11-13, after observation and a separate compatibility check. Not a condition for closing R3 |
| F8–F11 | Low/Info | No-role fallback, first-organisation choice, viewer hint lifetime, QA screenshots | Open; R3 §4 |
| **F12** (new) | Low (defense in depth) | `anon` has table privileges on `public.season_recommendations`. The table was created after the baseline's `revoke … from anon`, and nothing revoked Supabase's default grant. RLS is enabled, the only policy is `for select to authenticated`, and there is no write policy, so anon reads 0 rows and cannot write. **No exposure.** The other 44 tables refuse anon | Follow-up migration (`revoke all on public.season_recommendations from anon`), applied only with approval. Not a blocker |
| **F13** (new) | Info | The API (Caddy) sends no `Strict-Transport-Security` or `X-Content-Type-Options`. It serves JSON only, so framing does not apply | Optional Caddy change; not a blocker |
| — | Ops | The API is one container with one worker on one EC2 host (single point of failure); round trip Sydney↔Seoul ≈138 ms per DB call | Known; region move is an open recommendation |
| #20 / 026 | — | Set-based policies for `production_batches` and `carbon_calculations` | **Frozen: stays Draft, not merged, not applied.** There is no endpoint evidence that it is needed |

## 11. Rollback targets

| Layer | Target | Note |
|---|---|---|
| Frontend | Render `dep-dbmcstd9fdbs73ckg6e0` (`654f95c`, `index-YKjxTk3n.js`) | **This brings F1–F6 back.** Use it only for a regression worse than they are. After any rollback, poll `/` until the old entry name appears (CDN up to 300 s) |
| Headers (F7 Stage 1) | Revert #25 in a PR. The merge is the rollout (Blueprint auto-sync) | HSTS is only 300 s, so browsers drop it within 5 min |
| Database (025) | `supabase/rollbacks/20261104090000_set_based_activity_read_policies.down.sql`, tested on an isolated stack | If 026 is ever applied, roll it back first |
| API | Unchanged in R3; the previous container is kept stopped on the host | — |

## 12. Release gate conclusion

| Condition for `PRODUCTION PASS` | Status |
|---|---|
| Real Manager and Farmer QA PASS | **PENDING** (`AUTHENTICATED_QA_PENDING`) |
| Cross-account isolation PASS | **PENDING**: needs real accounts |
| No unresolved Critical/High | **Met** (0 Critical, 0 High; F12/F13 new, Low/Info) |
| Human security review complete | **PENDING** (`HUMAN_SECURITY_REVIEW_PENDING`, 0 reviews) |
| Production smoke PASS | **Met**: §6 automated, plus the owner-reported login/logout |

**Conclusion: `PRODUCTION CONDITIONAL`.** Production is working. No security exposure or bypass was found, and no confirmed Critical or High issue is open. The gate moves to `PRODUCTION PASS` when both of these are done:
1. The runner in §7 passes with real Manager and Farmer accounts, including cross-account isolation.
2. A person who did not write the code posts `HUMAN_REVIEW` verdicts on #24 for #21, #13, #15/#16 and #17.

R3 needs no further deploy, merge or migration.
