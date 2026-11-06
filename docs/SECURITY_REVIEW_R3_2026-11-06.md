# Security review package R3: web session, role verification and cache isolation (2026-11-06)

**Human review status: `HUMAN_REVIEW_PENDING`.**

An AI agent (Claude Code) prepared this package on 2026-11-06. **It is not a human review**, and nothing in it approves anything. It exists so that a human reviewer (SiriusNoPro, or another person with authority over the repository) can check the authentication and authorization code of the web dashboard quickly and record a verdict.

**What "human review complete" means for the release gate.** A human has reviewed **all** of these:
- the fix PR #21 (§6, R1–R10);
- #13, the RLS migration that is **already applied to the hosted database**;
- #15/#16, role verification through `/v1/me` (§8, R11–R15).

Approving #21 alone does not complete the human review. Every PR from #12 to #19 was merged with `--admin` and 0 human reviews.

Release R2 (#17, #18, #19) was merged with `--admin` on 2026-11-05. Before those merges, the only review was a read-only report by another AI agent (agy), with the verdict APPROVE (0 critical, 0 major). That report is not a human approval. This R3 review re-read the same code and found two Medium issues and four Low issues that the earlier report did not list (§4).

## 1. Scope

| Item | Value |
|---|---|
| Code reviewed | `main` at `1e720e5`. The web code equals production `654f95c` (`1e720e5` only adds docs) |
| Diffs reviewed | #17 (`f8aeb5a`, `38ca952`, `0828f05`, `66b494c`, merge `654f95c`), #18 (`e5f08b7`, `35dd20a`, merge `a2f4801`) |
| Focus files | `web-dashboard/src/App.tsx`, `src/api/auth.ts`, `src/api/me.ts`, `src/farmer/data.ts`, plus `src/api/client.ts`, `src/query/client.ts`, `src/api/organizations.ts`, `src/utils/supabase.ts` |
| Server side read | `backend/api.py` (`/v1/me`, password-change guard), `backend/infrastructure/read_repo.py` (`me()`), `backend/infrastructure/memberships.py` |
| Library behaviour checked | `@supabase/auth-js` 2.116.0 (`signOut`, `signInWithPassword`, locks), against the real client with a fake network |
| Fix PR | [#21](https://github.com/levuanh2/TEC2026/pull/21) `fix/web-auth-session-hardening` (`447a5e5` fixes, `83b17b6` coverage tests). Not merged; needs a human review |

## 2. Threat model (short)

**Assets.** Business data per organisation and farm (seasons, journals, Carbon, MRV); the Supabase session (access and refresh token in `localStorage`); the role that decides which shell renders.

**Trust boundary.** The browser is not trusted. FastAPI and Postgres RLS make every authorization decision. The web app's job is narrower:
1. never show data loaded for one person or scope to another person or scope;
2. never claim a state that is not true, for example "Bạn đã đăng xuất" while a session is still stored;
3. never send a request with a token that belongs to someone other than the person it was asked for.

**Actors and situations considered.**
- A shared browser or computer, with one person after another.
- Two tabs of one browser. They share the storage and the token, and Supabase broadcasts auth events between them.
- An account whose role, organisation membership or farm role changes while a tab stays open.
- A slow or hung network, 401/403/5xx answers, and requests still in flight during a sign-out, a token refresh or a takeover by another account.
- A crafted link (`/login?next=…`).

**Out of scope.** XSS in the app itself (none was found, but the missing CSP is reported in §4), the Flutter app, and server-side RLS policy changes (PR #20 is reviewed separately).

## 3. Properties checked

| # | Property | Result | Evidence |
|---|---|---|---|
| P1 | No business screen renders before `/v1/me` confirms the role **for the current session** | Holds | `App.tsx` `verifiedFor === session` gate; mutation E4 is killed by the tests |
| P2 | A failed `/v1/me` (0, 401, 403, 5xx, timeout) never assigns a role | Holds | neutral `ViewerUnverified`; `meRoleUnverified.dom.test.tsx` |
| P3 | A re-check with 401/403 drops the caches and the hint, and shows the neutral screen. A network error or 5xx keeps the confirmed role (availability; the server still refuses every new read) | Holds, by design | `sessionRevalidation.dom.test.tsx` |
| P4 | Sign-out and expiry clear every session-scoped cache (query, Farmer, organisation, hint) | Holds | `auth.ts finish()`; mutations E8 and E9 |
| P5 | A response that settles after a cache clear never writes into the cleared cache | Holds | `farmer/data.ts` generation; TanStack `clear()`; mutation E6 |
| P6 | A cross-tab sign-in of another person re-verifies from the skeleton, with no old data | Holds for SIGNED_IN. **Gap for a TOKEN_REFRESHED or a 401 refresh that returns the other person's session (F2)** | `sessionReplacement.dom.test.tsx`, `authReplacement.dom.test.ts` |
| P7 | A request is never sent, or retried, with another person's token | **Did not hold (F2)** | `sessionIdentity.test.ts` |
| P8 | A change of role, organisation or farm access drops the caches | Holds for the role, the first organisation and writable farms. **Not for read-only farms or a second organisation (F1)** | `accessScope.dom.test.tsx` |
| P9 | After "Bạn đã đăng xuất", nothing can restore the session | **Did not hold on a slow or hung `/logout` (F4)** | `authSignOutRealClient.dom.test.ts` (real auth-js) |
| P10 | Server side: `/v1/me` advertises only active memberships; protected routes answer 401 without a valid token; CORS allows only the site origin | Holds | `read_repo.me()` uses `active_memberships`; production probe 2026-11-06: 4 routes × (no token, invalid token) = 401; foreign origin preflight 400 |

## 4. Findings

Severity is for this application (web dashboard; authorization is server-enforced). None is Critical or High: no finding lets a person read data the server would refuse them, and no finding bypasses authentication.

| ID | Severity | Finding | Status |
|---|---|---|---|
| F4 | **Medium** | **Sign-out on a slow or hung network leaves the session restorable.** The shell leaves after 1.5 s, while auth-js removes the stored session only when `/logout` returns. Measured with the real auth-js 2.116 client: 1.6 s after sign-out, the stored session was still A's. Also seen in real Chrome on the #17 build: `/logout` hangs, the screen says "Bạn đã đăng xuất", the person closes the tab, and opening the site again in the same browser sends `/v1/me` with the Manager's token and **shows the Management shell**. Closing the tab also aborts the revocation, so the refresh token stays valid. Present since `3acfba7` (2026-09-23), so it is in every rollback target. **Found in the remediation pass, on #21's first head:** offline at sign-out, the screen still said "Bạn đã đăng xuất." with no server revocation; and a hung `/logout` in tab A left tab B of the same browser in the Manager shell. | Fixed in #21 (`f52300e`, `8fb4c0f`). Local cleanup and server revocation are reported separately: "Bạn đã đăng xuất." only when `/logout` answered and nothing is stored; otherwise a warning with "Thử xác nhận lại" (`/logout?scope=global`). The stored session is removed at once; `/logout` is bounded to 8 s; a `storage` removal ends every other tab. **Residual:** if the server is never reached and the access token expires before a retry, the refresh token stays valid on the server until used or revoked. The warning says so |
| F1 | **Medium** | **Losing read-only access is not detected by the open-tab re-check.** The compared scope was (user, role, first organisation, writable farms, password flag). Removing a `viewer` farm role, or ending a second organisation membership, changed none of them, so the rows cached under that access (the Farmer scope is cached for 5 min) stayed on screen. The server refuses new reads; what was already loaded stayed visible. | Fixed: the scope includes every membership and farm role from `/v1/me` (`access`) |
| F2 | Low | **A request can be retried, or sent from the read queue, with the next person's token.** On a 401, `send()` retried with the current token if it had changed, without checking whose it was. A read queued behind the 4-request limit was sent with whatever token was current when its slot came. A 401 refresh used the stored session, which another tab may have replaced. Only SIGNED_IN was recognised as a takeover. In the tests, the cache layers (generation counter, user-keyed query keys, unmounting) kept such answers off screen, so no exposure was observed. The property itself did not hold. | Fixed: an identity counter in `client.ts`; a takeover is recognised from any auth event and from a refresh |
| F5 | Low | **A late sign-out removes the next person's session.** `/logout` is slow, the shell has already left, and B signs in on the same tab. When A's call returns, auth-js removes the stored session, which is now B's, and emits SIGNED_OUT, which the app ignored while its sign-out flag was still set. B stays signed in until the token expires, then is dropped; a reload drops B at once. Reproduced with the real auth-js client. | Fixed: sign-in waits for a pending (bounded) sign-out |
| F3 | Low | The first `/v1/me` of a session was applied even when it named another `user_id` (token replaced in flight). That wrote the other person's role into this user's hint. Nothing rendered, because the session check still failed. | Fixed: the neutral screen; no hint |
| F6 | Low | `?next=/\evil.example` passed the `startsWith('/')` check. The browser resolves it to another origin, so `history.replaceState` throws and the sign-in fails with an error. This is not an open redirect. | Fixed: `next` is accepted only when it resolves to this origin |
| F7 | Medium (hardening) | The frontend sends no `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`/`frame-ancestors` or `Referrer-Policy` (only `X-Content-Type-Options`). The app can be framed (clickjacking), and nothing limits script sources, while the Supabase refresh token sits in `localStorage`. | **Open, plan ready: #23.** Staged headers, measured on the production bundle in real Chrome (0 violations with the full CSP enforced; framing refused). Not applied. Each stage is a `render.yaml` PR, and merging it is the rollout (Blueprint auto-sync). See §7 |
| F8 | Low | An account with no recognised role (for example, every organisation membership ended) falls back to the Farmer shell (`toCurrentUser`). Its reads are RLS-scoped and return nothing it may not see. | Open, product decision. A neutral "no role" screen would be stricter |
| F9 | Low | `organizationId` is the first membership, and the role is the highest across all memberships. A person who is a manager in org X and a farmer in org Y can get the Management UI pointed at Y. The server answers 403. | Open, UX only |
| F10 | Info | The viewer hint (`agricarbon.viewer.v1`: name, organisation id, writable farm ids) stays in `localStorage` until sign-out or expiry. It is not cleared when the browser closes. | Open, accepted (no authority; it only steers a prefetch) |
| F11 | Info | The QA runner's sidebar spec writes screenshots into `.qa-screenshots/` of the web checkout it runs from (gitignored, inside a worktree). Text artifacts are scrubbed; PNGs are not (passwords are masked dots). | Open, accepted |

No Critical or High finding, so no containment or rollback is proposed. The production build `654f95c` contains F1–F6. They are fixed in #21 (head `8fb4c0f`), which needs human review before it is merged or deployed.

## 5. Tests and mutation check

Gates on #21 head `8fb4c0f`: `tsc -b` and `npm run build` pass. Vitest **92 files / 719 tests** (main: 87 / 679). Playwright (mock) **111 / 111**. Real Chrome, two tabs of one browser with fake origins answered in the browser (`.tmp/release-r3/twotab/`, local), 12 scenarios: the production-equivalent #17 build passes **6 / 12** (every R3 sign-out scenario fails); #21's first head passes 9 / 12; **`8fb4c0f` passes 12 / 12**.

Regression tests added (each fails on `main`; 11 of the new cases were run against the `main` sources and failed):

| File | Covers |
|---|---|
| `src/api/sessionIdentity.test.ts` | F2: retry after a takeover, a refresh returning someone else, a sign-out in flight, a queued read; the same person's rotation still retried |
| `src/api/authReplacement.dom.test.ts` | F2: SIGNED_IN and TOKEN_REFRESHED of another user; a 401 recovery returning another user; the same user refreshed causes no replacement |
| `src/api/authSignOutRealClient.dom.test.ts` | F4, F5 with the **real auth-js client**: hung, slow, offline and refused `/logout`; a retry once the network is back; storage that silently keeps the session; the cross-tab `storage` event; the token dropped by the next sign-in; storage key pinned; `boundedAuthFetch` timeout |
| `src/signOutNotice.dom.test.tsx` | F4 on screen: the confirmation only when confirmed; the warning (`role=alert`), the retry, a late confirmation, "ended in another tab" |
| `src/accessScope.dom.test.tsx` | F1 (read-only farm, second organisation, reorder changes nothing), F3, F6 (3 crafted values, plus a real page still returned to) |

An existing backend guard caught a mistake in the remediation pass. `test_react_never_holds_a_service_role_credential` (CI on `8bc8fc6`) flagged the first "Thử xác nhận lại" implementation, which used `auth.admin.signOut(token)`. That call sends the user's own token, but the guard bans the `auth.admin` namespace in React code outright. `8fb4c0f` calls `POST /auth/v1/logout?scope=global` itself, with the publishable key and the user's token, and the guard passes. The guard was kept unchanged.

Targeted mutation run: each security guard disabled on its own, then the full Vitest suite run.

| Guards | First run | After `83b17b6` |
|---|---|---|
| 13 added by #21 (identity checks ×3, stored-session drop, sign-in wait, replacement on any event, refresh of another person, takeover moves the identity, `access` mapped, `access` compared, first `/v1/me` user check, same-origin `next`, `/logout` timeout) | 13 killed | 13 killed |
| 13 existing guards from #12/#15/#17 | 8 killed, **5 survived** | 13 killed |
| 11 F4 guards added in the remediation pass (`f52300e`, `8fb4c0f`) | 9 killed, 1 survived, 1 bad pattern | 11 killed (a test was added for the survivor) |

**Total on `8fb4c0f`: 37 / 37 guards killed.**

The 5 survivors were guards that no test exercised:
- the first `/v1/me` answer after the session ended (it rewrote the hint and redirected away from `/login`);
- a late re-check error from the previous session after a takeover (it sent the new person's verified shell back to the skeleton for good);
- sign-out clearing the query cache;
- a viewer hint returned for another user;
- a read queued when the session ends. On its own this one is equivalent to #21's identity check; mutated together with it, it is killed.

## 6. Reviewer checklist

Tick these in a GitHub review of the fix PR (or reply with the item numbers). A human reviewer should run or read, not take this package's word for it.

- [ ] R1. `App.tsx`: no business screen renders unless `verifiedFor === session` (the `ViewerVerifying` gate), including during a cross-tab takeover.
- [ ] R2. `App.tsx`: every `/v1/me` answer (first check and re-check) is applied only if it is for the live session **and** its `user_id` equals the session user.
- [ ] R3. `me.ts` + `App.tsx`: the compared scope includes every organisation membership and farm role (`access`), read-only ones included; a reorder is not a change.
- [ ] R4. `client.ts`: a request started under one identity is never sent (after the read queue) or retried (after a 401) under another; the same person's token rotation still retries once.
- [ ] R5. `auth.ts`: a session of another user arriving by SIGNED_IN, TOKEN_REFRESHED or the 401 refresh is a replacement (identity moved, caches and hint cleared, shell re-verifies).
- [ ] R6. `auth.ts` + `utils/supabase.ts`: after sign-out the stored session is gone even if `/logout` hangs; "Bạn đã đăng xuất." appears only when the server confirmed it AND nothing is stored, otherwise the warning and "Thử xác nhận lại"; `/logout` is bounded; a sign-in waits for a pending sign-out; a removal in another tab ends this tab. Check `authSignOutRealClient.dom.test.ts`, which uses the real auth-js client.
- [ ] R7. Fail-closed: 401/403 on a re-check gives the neutral screen; 0/5xx/timeout keeps the confirmed role. Agree, or ask for a stricter rule.
- [ ] R8. Server side: `/v1/me` filters ended memberships (`read_repo.me`); no web change weakens a server check (the PR touches only `web-dashboard/src`).
- [ ] R9. Open items F7–F11: agree with the severity, or say what has to change before PRODUCTION PASS.
- [ ] R10. The real-Chrome two-tab results (in the fix PR) match what the unit tests claim.
- [ ] R16. Behaviour change: when the stored session is removed in another tab, this tab ends ("kết thúc ở một tab khác") instead of following the next sign-in. The residual risk of F4 is accepted as written in §4.

For #13, #15 and #16, see §8 (R11–R15). The human review is complete only when §6 and §8 are both done.

Verdict line for the reviewer to copy: `HUMAN_REVIEW: APPROVE | REQUEST_CHANGES — <name>, <date>`.

## 7. F7 plan (#23, not applied)

**Correction.** The first version of this section (2026-11-06, `de27220`) proposed headers that were wrong:
- `includeSubDomains` before any subdomain audit;
- `script-src 'self'` without the hash, which silently blocks `index.html`'s font-switch handler (the UI would lose its font);
- a `wss://` source the app does not use;
- setting them by hand in the Render dashboard, although the Blueprint `tec` auto-syncs `render.yaml`.

Use #23 instead. It measured the policy on the production bundle in real Chrome, split it into stages, and comes with a runbook and a rollback.

| Stage | Headers | Status |
|---|---|---|
| 1 | `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy`, HSTS `max-age=300`, **enforced** `frame-ancestors 'none'; object-src 'none'; base-uri 'self'`, full policy **Report-Only** | ready; harness pass with 0 reports; owner approval needed |
| 2 | full CSP **enforced**, HSTS 1 day | harness pass with 0 violations; after ≥ 7 days of stage 1 |
| 3 | HSTS 1 year, this host only | after ≥ 14 days of stage 2 |

`render.yaml` is not code-owned, although its merge changes production. Adding it to CODEOWNERS is an owner decision.

## 8. Also pending human review: #13 (RLS, applied to hosted) and #15/#16 (role verification)

These were merged before R2's session work, with `--admin` and 0 human reviews, and no review was requested on them. They are in scope for the human review. #13 matters most: it changed which rows each person can read, and it runs on the production database now.

| PR | What it changed | State |
|---|---|---|
| #13 `ec5e81f` | Migration `20261104090000`: `private.readable_batch_ids()` and set-based SELECT policies on `activities` plus 7 detail tables (`… production_batch_id in (select private.readable_batch_ids())`) | Applied to hosted 2026-11-05 07:57:40Z. On 2026-11-06 the hosted history has 25 rows, equal to `main`. Evidence so far, all produced by AI agents: 14-identity equivalence, 0 mismatches; guards in a rolled-back transaction; rollback tested on an isolated stack (`.tmp/rls-20261104090000/ROLLOUT_LOG_2026-11-05.md`) |
| #15 `8aedb3d` | A failed `/v1/me` never assigns a role (neutral unverified screen) | In production since `71409ea` |
| #16 `71409ea` | #12 (query cache, lazy routes) integrated behind the `/v1/me` role gate | In production since `71409ea` |

R3 checked part of #13 again (AI, read-only): `readable_batch_ids()` follows the same chain as `user_can_read_batch` (batch → season → plot → `user_can_read_farm`, no `deleted_at` filter on the batch). It is `security definer` with `search_path = ''`, executable by `authenticated` only, and lives in `private`, which PostgREST does not expose. The live policies on hosted are the set-based ones. That is not a human review.

**Code-owner note.** #13 touches code-owned paths (`supabase/migrations/`, `scripts/ci/policy/`). Their only code owner is the PR's author (`levuanh2`), so no independent code-owner review is possible today. A review by SiriusNoPro (write access, not a code owner) is a valid human review, but GitHub does not count it as a code-owner approval. Either accept that and record it, or add a second code owner.

Checklist (tick in a review or a comment on the PR concerned):

- [ ] R11. #13 SQL: each new SELECT policy grants exactly what the per-row policy it replaced granted, for `activities` and each of the 7 detail tables (soft-deleted activities stay hidden from the detail rows).
- [ ] R12. #13 function: `private.readable_batch_ids()` is `stable`, `security definer`, `set search_path = ''`, fully qualified, `execute` revoked from `public`/`anon`; it returns only ids the caller may read.
- [ ] R13. #13 hosted state: the applied SQL equals the file on `main` (checksum in `scripts/ci/policy/migrations.sha256`); the rollback (`supabase/rollbacks/20261104090000_…down.sql`) restores the old policies; 026 (#20) must be rolled back first if it is ever applied.
- [ ] R14. #15: every `/v1/me` failure path (0, 401, 403, 5xx, timeout) renders the neutral screen and assigns no role (`meRoleUnverified.dom.test.tsx`).
- [ ] R15. #16: no Management or Farmer business read is rendered before `/v1/me` confirms the role; the speculative Farmer-scope prefetch is server-authorized, stays in memory and is not shown (`roleVerifiedQueryCache.dom.test.tsx`).

Verdict line per PR: `HUMAN_REVIEW #13|#15|#16: APPROVE | REQUEST_CHANGES — <name>, <date>`.

### R17–R19: #17 (open-tab re-check and multi-tab), merged

#17 is reviewed through #21: #21 changes the same code. These items are what #17 itself claims. They are checked by the tests named, and a human should confirm them.
- [ ] R17. Focus, visibility and a token refresh trigger at most one `/v1/me` per 60 s, never two in flight, and a hung check stops blocking after 30 s (`sessionRevalidation.dom.test.tsx`, real Chrome scenario 4).
- [ ] R18. A changed scope drops every cache and remounts the business tree (`scopeEpoch`); a 401/403 shows the neutral screen; 0/5xx keeps the role (`sessionRevalidation.dom.test.tsx`, real Chrome scenario 5).
- [ ] R19. A late answer for an ended or replaced session changes nothing (`sessionReplacement.dom.test.tsx`, real Chrome scenarios 2 and 3).

Verdict line: `HUMAN_REVIEW #17: APPROVE | REQUEST_CHANGES — <name>, <date>`. The verdict is recorded after the merge, and it does not turn #17's admin merge into a pre-merge approval.

## 9. What each kind of evidence is worth

| Kind | What exists | What it is not |
|---|---|---|
| **Human review** | **None so far**, on any PR from #12 to #23 | — |
| AI review | agy reports on #13, #17, #18, #19 (before merge); this R3 package and #21–#23 (Claude Code) | not an approval; the agy reports missed F1 and F4 |
| CI | 17 required checks green on `main` and on the open PRs | does not run real browsers against production, real Supabase sign-outs, or authenticated flows |
| Local test evidence | Vitest, Playwright mock, real auth-js client, real Chrome (two tabs), mutation runs, production smoke without credentials, F7 harness on the production bundle | not a real Manager or Farmer session |
| **Not verified** | authenticated Manager/Farmer QA and cross-account isolation with real accounts (`BLOCKED_CREDENTIALS`); endpoint p50/p95; EC2 5xx log; the subdomain list (for HSTS `includeSubDomains`); whether the Render dashboard headers survive a Blueprint sync | — |

## 10. Release gate (2026-11-06)

| Condition for PRODUCTION PASS | Status |
|---|---|
| 1. F1–F6 fixed and verified | **Fixed and verified in #21 `8fb4c0f`; not merged and not deployed.** Production still has them |
| 2. #21 human security review | **PENDING** (requested on `8fb4c0f`) |
| 3. Human review of the RLS/role changes (#13, #15/#16, #17) | **PENDING** (requested; record in the tracking issue) |
| 4. Authenticated Manager/Farmer QA | **BLOCKED_CREDENTIALS** |
| 5. No unresolved Critical/High | **Met**: none found |
| 6. Production smoke | **PASS** (no-credential smoke 6/6; F7 harness `LIVE=1` 5/5) |
| F7 | not a blocker per the owner decision; plan in #23; the residual risk is clickjacking and no CSP until stage 1 |

**Result: `PRODUCTION CONDITIONAL`.**
