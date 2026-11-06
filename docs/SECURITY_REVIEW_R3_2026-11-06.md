# Security review package R3: web session, role verification and cache isolation (2026-11-06)

**Human review status: `HUMAN_REVIEW_PENDING`.**

An AI agent (Claude Code) prepared this package on 2026-11-06. **It is not a human review**, and nothing in it approves anything. It exists so that a human reviewer (SiriusNoPro, or another person with authority over the repository) can check the authentication and authorization code of the web dashboard quickly and record a verdict.

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
| F4 | **Medium** | **Sign-out on a slow or hung network leaves the session restorable.** The shell leaves after 1.5 s, while auth-js removes the stored session only when `/logout` returns. Measured with the real auth-js 2.116 client: 1.6 s after sign-out, the stored session was still A's. Also seen in real Chrome on the #17 build: `/logout` hangs, the screen says "Bạn đã đăng xuất", the person closes the tab, and opening the site again in the same browser sends `/v1/me` with the Manager's token and **shows the Management shell**. Closing the tab also aborts the revocation, so the refresh token stays valid. Present since `3acfba7` (2026-09-23), so it is in every rollback target. | Fixed in #21: the stored session is removed locally when the server has not answered, and `/logout` is bounded to 8 s |
| F1 | **Medium** | **Losing read-only access is not detected by the open-tab re-check.** The compared scope was (user, role, first organisation, writable farms, password flag). Removing a `viewer` farm role, or ending a second organisation membership, changed none of them, so the rows cached under that access (the Farmer scope is cached for 5 min) stayed on screen. The server refuses new reads; what was already loaded stayed visible. | Fixed: the scope includes every membership and farm role from `/v1/me` (`access`) |
| F2 | Low | **A request can be retried, or sent from the read queue, with the next person's token.** On a 401, `send()` retried with the current token if it had changed, without checking whose it was. A read queued behind the 4-request limit was sent with whatever token was current when its slot came. A 401 refresh used the stored session, which another tab may have replaced. Only SIGNED_IN was recognised as a takeover. In the tests, the cache layers (generation counter, user-keyed query keys, unmounting) kept such answers off screen, so no exposure was observed. The property itself did not hold. | Fixed: an identity counter in `client.ts`; a takeover is recognised from any auth event and from a refresh |
| F5 | Low | **A late sign-out removes the next person's session.** `/logout` is slow, the shell has already left, and B signs in on the same tab. When A's call returns, auth-js removes the stored session, which is now B's, and emits SIGNED_OUT, which the app ignored while its sign-out flag was still set. B stays signed in until the token expires, then is dropped; a reload drops B at once. Reproduced with the real auth-js client. | Fixed: sign-in waits for a pending (bounded) sign-out |
| F3 | Low | The first `/v1/me` of a session was applied even when it named another `user_id` (token replaced in flight). That wrote the other person's role into this user's hint. Nothing rendered, because the session check still failed. | Fixed: the neutral screen; no hint |
| F6 | Low | `?next=/\evil.example` passed the `startsWith('/')` check. The browser resolves it to another origin, so `history.replaceState` throws and the sign-in fails with an error. This is not an open redirect. | Fixed: `next` is accepted only when it resolves to this origin |
| F7 | Medium (hardening) | The frontend sends no `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`/`frame-ancestors` or `Referrer-Policy` (only `X-Content-Type-Options`). The app can be framed (clickjacking), and nothing limits script sources, while the Supabase refresh token sits in `localStorage`. | **Open.** It needs a Render static-site header rule (or Cloudflare), which is a production configuration change outside this review's authority. Proposed values in §7 |
| F8 | Low | An account with no recognised role (for example, every organisation membership ended) falls back to the Farmer shell (`toCurrentUser`). Its reads are RLS-scoped and return nothing it may not see. | Open, product decision. A neutral "no role" screen would be stricter |
| F9 | Low | `organizationId` is the first membership, and the role is the highest across all memberships. A person who is a manager in org X and a farmer in org Y can get the Management UI pointed at Y. The server answers 403. | Open, UX only |
| F10 | Info | The viewer hint (`agricarbon.viewer.v1`: name, organisation id, writable farm ids) stays in `localStorage` until sign-out or expiry. It is not cleared when the browser closes. | Open, accepted (no authority; it only steers a prefetch) |
| F11 | Info | The QA runner's sidebar spec writes screenshots into `.qa-screenshots/` of the web checkout it runs from (gitignored, inside a worktree). Text artifacts are scrubbed; PNGs are not (passwords are masked dots). | Open, accepted |

No Critical or High finding, so no containment or rollback is proposed. The production build `654f95c` contains F1–F6. They are fixed on the fix branch, which needs human review before it is merged or deployed.

## 5. Tests and mutation check

Gates on #21: TypeScript `tsc -b` passes. Vitest **91 files / 707 tests** (main: 87 / 679). Playwright (mock) **111 / 111**. Real Chrome, two tabs of one browser with fake origins answered in the browser (`.tmp/release-r3/twotab/`, local): the #17 build passes 5 of 7 (the two sign-out scenarios fail); #21 passes **7 / 7**.

Regression tests added (each fails on `main`; 11 of the new cases were run against the `main` sources and failed):

| File | Covers |
|---|---|
| `src/api/sessionIdentity.test.ts` | F2: retry after a takeover, a refresh returning someone else, a sign-out in flight, a queued read; the same person's rotation still retried |
| `src/api/authReplacement.dom.test.ts` | F2: SIGNED_IN and TOKEN_REFRESHED of another user; a 401 recovery returning another user; the same user refreshed causes no replacement |
| `src/api/authSignOutRealClient.dom.test.ts` | F4, F5 with the **real auth-js client**; storage key pinned; `boundedAuthFetch` timeout |
| `src/accessScope.dom.test.tsx` | F1 (read-only farm, second organisation, reorder changes nothing), F3, F6 (3 crafted values, plus a real page still returned to) |

Targeted mutation run: each security guard disabled on its own, then the full Vitest suite run.

| Guards | First run | After `83b17b6` |
|---|---|---|
| 13 added by #21 (identity checks ×3, stored-session drop, sign-in wait, replacement on any event, refresh of another person, takeover moves the identity, `access` mapped, `access` compared, first `/v1/me` user check, same-origin `next`, `/logout` timeout) | 13 killed | 13 killed |
| 13 existing guards from #12/#15/#17 | 8 killed, **5 survived** | 13 killed |

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
- [ ] R6. `auth.ts` + `utils/supabase.ts`: after sign-out the stored session is gone even if `/logout` hangs; `/logout` is bounded; a sign-in waits for a pending sign-out. Check `authSignOutRealClient.dom.test.ts`, which uses the real auth-js client.
- [ ] R7. Fail-closed: 401/403 on a re-check gives the neutral screen; 0/5xx/timeout keeps the confirmed role. Agree, or ask for a stricter rule.
- [ ] R8. Server side: `/v1/me` filters ended memberships (`read_repo.me`); no web change weakens a server check (the PR touches only `web-dashboard/src`).
- [ ] R9. Open items F7–F11: agree with the severity, or say what has to change before PRODUCTION PASS.
- [ ] R10. The real-Chrome two-tab results (in the fix PR) match what the unit tests claim.

Verdict line for the reviewer to copy: `HUMAN_REVIEW: APPROVE | REQUEST_CHANGES — <name>, <date>`.

## 7. Proposed headers (F7, not applied)

For the Render static site (Settings → Headers, path `/*`). This is a production change, so it needs the owner's approval and a check that the login still works:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
Content-Security-Policy: frame-ancestors 'none'; default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' https://api.agricarbon.info.vn https://<project-ref>.supabase.co wss://<project-ref>.supabase.co; base-uri 'self'; form-action 'self'
Referrer-Policy: strict-origin-when-cross-origin
```

Start the CSP as `Content-Security-Policy-Report-Only` for a release, and check the browser console on the Manager and Farmer flows before you enforce it.
