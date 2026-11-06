# F7: security headers for agricarbon.info.vn (staged rollout runbook)

**Status (2026-11-06): stage 1 is LIVE.** It was rolled out by #25 (merge `27c6cfa`, Blueprint sync `exe-dbmpfuff3r2c73aln6m0`, 09:03:54Z), and `--verify 1` plus the harness on the real headers (`LIVE=1 STAGE=1`) pass with 0 CSP reports. Rollback target: revert #25. **Stage 2 is not approved.** Earliest date to propose it: 2026-11-13 (7 days of stage 1).

Finding F7 (R3 security review, Medium, hardening): the frontend sends no HSTS, CSP, `frame-ancestors`/`X-Frame-Options`, `Referrer-Policy` or `Permissions-Policy`. The site can be framed (clickjacking), and nothing limits script or connection sources while the Supabase session sits in `localStorage`.

## Read this first: merging `render.yaml` IS the rollout

- `https://agricarbon.info.vn` is the Render static site **`agricarbon-web-staging`** (`srv-danpuojm8hqs73c59fj0`). The word "STAGING" in the name and in `render.yaml` is historical: **it is production**.
- The Render Blueprint **`tec`** (`exs-danp4ioae00c739j3ts0`) has **`autoSync: true`** on `render.yaml` of `main` (Render API, read-only, 2026-11-06). Merging any change to `render.yaml` applies it to production with no deploy button.
- So **this PR does not touch `render.yaml`**. Each stage is its own small PR that pastes the generated block into `render.yaml`. Merging that PR is the rollout. Merging its revert is the rollback.
- `render.yaml` has no code owner. The owner should decide whether to add it to `.github/CODEOWNERS`, a guarded path, so that every production-config change needs an explicit owner review.
- Do not set headers by hand in the Render dashboard: whether the next Blueprint sync keeps or drops them was not verified, and they would drift from the repo.

## Files

| File | What it does |
|---|---|
| `stages.json` | The policy and the headers of each stage (single source) |
| `headers.mjs` | `--check` invariants (no network) · `--yaml N` the `headers:` block for `render.yaml` · `--json N` · `--verify N` GET the live site and compare |
| `csp.spec.ts`, `playwright.config.ts` | Real-Chrome harness on the **production bundle**: the stage's headers are injected into each HTML response **in the browser** (or, with `LIVE=1`, the real headers are used) |

`--check` enforces:
- no `includeSubDomains`/`preload`;
- HSTS never shrinks and starts at ≤ 300 s;
- `frame-ancestors 'none'` is **enforced** in every stage (browsers ignore it in Report-Only) and `X-Frame-Options: DENY` is set;
- no `'unsafe-inline'`, `'unsafe-eval'` or wildcard;
- `connect-src` covers the API and Supabase;
- every inline handler in `web-dashboard/index.html` is allowed by hash, and no allowed hash is stale.

## What the app needs (measured)

| Resource | Origin | Directive |
|---|---|---|
| App code, CSS, 10 lazy chunks, chunk-recovery `fetch('/')` | self | `script-src`, `style-src`, `connect-src 'self'` |
| Webfont CSS / files | `fonts.googleapis.com` / `fonts.gstatic.com` | `style-src` / `font-src` |
| Non-render-blocking font switch: `<link … media="print" onload="this.media='all'">` | inline handler | `script-src 'unsafe-hashes' 'sha256-MhtPZXr7+LpJUY5qtMutB+qWfQtMaPccfe7QXtCcEYc='` |
| FastAPI | `https://api.agricarbon.info.vn` | `connect-src` |
| Supabase Auth (token refresh, `/logout`) | `https://awazhdqzkktekbwaqiic.supabase.co` | `connect-src` (no websocket: realtime is not used) |
| Favicon `data:,`, CV photo preview `blob:` | — | `img-src data: blob:` |
| Browser APIs | only `navigator.clipboard` (write) | `Permissions-Policy`: `clipboard-write=(self)`, everything else `()` |

Without the hash, the font handler is blocked silently: the stylesheet stays `media=print` and the UI loses the Be Vietnam Pro font with no error. The harness checks that the stylesheet becomes `all`, and its self-test (`DROP_HASH=1`) fails as it should.

## Stages

| Stage | Headers | Gate to go to the next stage |
|---|---|---|
| 0 (now) | `X-Content-Type-Options: nosniff`, sent by Render itself on every response (origin and CDN). It is therefore never set in `render.yaml` (that would duplicate it), and `--verify` requires it | — |
| **1** | (`nosniff` from the host); `Referrer-Policy: strict-origin-when-cross-origin`; `X-Frame-Options: DENY`; `Permissions-Policy`; **`Strict-Transport-Security: max-age=300`**; **enforced** `Content-Security-Policy: frame-ancestors 'none'; object-src 'none'; base-uri 'self'`; the full policy as **`Content-Security-Policy-Report-Only`** | ≥ 7 days. Harness `LIVE=1 STAGE=1` green. Manager and Farmer real QA with no console CSP report. No user report of breakage |
| 2 | Full CSP **enforced**; HSTS `max-age=86400` | ≥ 14 days, same checks |
| 3 | HSTS `max-age=31536000` (this host only) | — |
| later | `includeSubDomains`, then `preload` | only after an audit of **every** subdomain of `agricarbon.info.vn` (DNS is in Cloudflare and was not visible to this review). `api.` already redirects to HTTPS (Caddy, 308); `www.` → 301 to the apex |

There is no CSP report endpoint. Report-Only reports reach only the visitor's browser console. In stage 1 the evidence is the harness on the live headers plus the real QA runs. A `report-to` endpoint would need a backend route, a separate change.

## Test results (2026-11-06, production bundle `index-YKjxTk3n.js`, real Chrome)

| Run | login + webfont | expired session (real 401 / refresh) | Manager, 9 routes (7 JS chunks) | Farmer, 6 routes | iframe of the site |
|---|---|---|---|---|---|
| stage 0 injected | pass | pass | pass | pass | rendered (framable today) |
| **stage 1 injected** | pass, 0 reports | pass | pass, 0 reports | pass, 0 reports | **refused** (`frame-ancestors 'none'`) |
| **stage 2 injected (full CSP enforced)** | pass, 0 violations | pass | pass, 0 violations | pass, 0 violations | **refused** |
| stage 2, `DROP_HASH=1` (self-test) | **fails** (font handler blocked), as it should | | | | |
| `LIVE=1 STAGE=0` (real headers today) | pass | pass | pass | pass | rendered |

Not covered by the harness: screens that need real data (the MRV export download uses a `blob:` link, which CSP does not govern for downloads; CV photo upload uses `blob:`, which is allowed). The authenticated QA after stage 1 covers them.

## Procedure for one stage (owner approval per stage)

1. Preflight, no production change:
   ```
   node ops/security-headers/headers.mjs --check
   node ops/security-headers/headers.mjs --verify <N-1>          # production is at the previous stage
   STAGE=<N> NODE_PATH=web-dashboard/node_modules npx --prefix web-dashboard playwright test -c ops/security-headers/playwright.config.ts
   ```
2. A PR that adds `node ops/security-headers/headers.mjs --yaml <N>` under the `agricarbon-web-staging` service in `render.yaml` (indentation: same level as `routes:`). It needs a human review that says "this merge rolls out stage N".
3. Merge at a time someone is watching. Then wait for the Blueprint sync (Render dashboard or `GET /v1/blueprints/exs-danp4ioae00c739j3ts0`) and for the Cloudflare HTML cache (`s-maxage=300`, up to 5 min).
4. Verify on the live site:
   ```
   node ops/security-headers/headers.mjs --verify <N>
   LIVE=1 STAGE=<N> NODE_PATH=web-dashboard/node_modules npx --prefix web-dashboard playwright test -c ops/security-headers/playwright.config.ts
   ```
   Then a Manager and a Farmer sign-in with the browser console open, or the authenticated QA runner when credentials exist.

## Rollback

- **Normal:** merge the revert of the stage PR (`render.yaml` back to stage N-1, or to no `headers:` block for stage 0). Then wait for the sync plus up to 5 min of Cloudflare cache, and run `--verify <N-1>`.
- **If the site is broken and the sync is slow:** delete the offending header in the Render dashboard (Settings → Headers) *and* merge the revert, so the next sync does not bring it back.
- **HSTS cannot be withdrawn from browsers that already saw it**: they keep it for `max-age`. That is why stage 1 uses 300 s. Only raise it once HTTPS is certain to stay on this host (it is: Cloudflare redirects `http://` → `https://`).
- CSP changes and `X-Frame-Options` take effect on the next page load after the cache expires. Nothing is cached in browsers.

## Residual risk until stage 1 is live

Clickjacking of the login and app pages is possible (a hostile page can frame the site). No script-source limit backs up the session in `localStorage`. No XSS was found in the R3 review, and `X-Content-Type-Options` is set. The R3 review does not count F7 as a release blocker: Medium, defence in depth. It does need a dated plan, which is this document.
