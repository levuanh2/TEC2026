/**
 * Farmer request waterfall — the benchmark behind docs/FARMER_PERFORMANCE_ROUND4.md.
 *
 * For each screen it records every backend request (start/end/duration/bytes/
 * status) together with the backend's own `Server-Timing` — handler ms and the
 * number of backend->Supabase round trips that request issued — plus three
 * readiness marks defined as DOM facts rather than impressions:
 *
 *   shell   the Farmer navigation exists (app booted, route resolved)
 *   useful  the season hero/workspace title is visible and quick actions work
 *   full    nothing in flight and no skeleton left, EXCLUDING deliberately
 *           deferred work; `settled` is the same mark including it
 *
 * Run the backend with AGRICARBON_SERVER_TIMING=1 or the per-request Supabase
 * counts come back empty. Credentials come from the environment; this file
 * contains none.
 *
 *   FARMER_REAL_E2E_EMAIL=... FARMER_REAL_E2E_PASSWORD=...  *   SEASON=<crop_season_id> AUTH_ORIGIN=https://<project>.supabase.co  *   node tools/farmer-waterfall.mjs <label> [home|season ...]
 *
 * Output goes to .qa-screenshots/round4/<label>.json (gitignored: the raw runs
 * are specific to one machine and one dataset, the harness is not).
 */
import { chromium } from 'playwright-core'
import { writeFileSync, mkdirSync } from 'node:fs'

const label = process.argv[2] ?? 'run'
const only = process.argv.slice(3)
const BASE = process.env.BASE ?? 'http://127.0.0.1:5173'
const API = process.env.API ?? 'http://127.0.0.1:8010'
const FARMER = { email: process.env.FARMER_REAL_E2E_EMAIL, password: process.env.FARMER_REAL_E2E_PASSWORD }
const SEASON = process.env.SEASON
/** Supabase Auth is part of the login waterfall even though it is not our API. */
const AUTH = process.env.AUTH_ORIGIN ?? ''

if (!FARMER.email || !FARMER.password || !SEASON) {
  console.error('Set FARMER_REAL_E2E_EMAIL, FARMER_REAL_E2E_PASSWORD and SEASON (a crop_season_id inside that farmer scope).')
  process.exit(2)
}

/* Three explicit readiness definitions (§24), each a DOM fact, not a guess:
 *  shell    — the Farmer nav exists (app booted, route resolved)
 *  useful   — the season hero title + a usable quick action are on screen
 *  full     — every section has left its loading state AND the network is quiet */
const SCREENS = {
  home: {
    path: '/farmer',
    shell: 'nav[aria-label]',
    useful: '#fw-hero-title',
  },
  season: {
    path: `/farmer/crop-seasons/${SEASON}`,
    shell: 'nav[aria-label]',
    useful: '.fw-ws-head__title h1',
  },
}

function track(page) {
  const reqs = []
  const inflight = new Map()
  page.on('request', (r) => {
    const origin = r.url().startsWith(API) ? API : (AUTH && r.url().startsWith(AUTH)) ? AUTH : null
    if (!origin || r.method() === 'OPTIONS') return
    const rec = { method: r.method(), url: (origin === AUTH ? 'auth:' : '') + r.url().slice(origin.length), start: Date.now(), end: null, status: null, bytes: null, serverMs: null, dbCalls: null, dbMs: null, top: null }
    inflight.set(r, rec); reqs.push(rec)
  })
  page.on('response', async (res) => {
    const rec = inflight.get(res.request())
    if (!rec) return
    rec.status = res.status()
    const st = res.headers()['server-timing']
    if (st) {
      const total = /total;dur=([\d.]+)/.exec(st)
      const db = /db;dur=([\d.]+);desc="(\d+) calls"/.exec(st)
      if (total) rec.serverMs = Number(total[1])
      if (db) { rec.dbMs = Number(db[1]); rec.dbCalls = Number(db[2]) }
      rec.top = st.split(', ').slice(2).join(', ') || null
    }
    try { rec.bytes = (await res.body()).length } catch { /* body already gone */ }
  })
  const done = (r) => { const rec = inflight.get(r); if (rec) { rec.end = Date.now(); inflight.delete(r) } }
  page.on('requestfinished', done)
  page.on('requestfailed', (r) => { const rec = inflight.get(r); if (rec) { rec.status = 'failed'; rec.failure = r.failure()?.errorText ?? null } done(r) })
  return { reqs, inflight }
}

/** A request the page deliberately defers — it must not count toward full-content. */
const DEFERRED = (rec) => rec.method === 'POST' && rec.url.includes('/recommendations/generate')

/** Wait until nothing is in flight for `quietMs` and no skeleton is left.
 *  `countDeferred=false` ignores deliberately deferred work (§24), so the two
 *  marks are reported separately rather than one flattering number. */
async function waitQuiet(page, t, { countDeferred, quietMs = 1500, cap = 60000 }) {
  const t0 = Date.now()
  let lastBusy = Date.now()
  const busy = () => [...t.inflight.values()].filter((r) => countDeferred || !DEFERRED(r)).length
  while (Date.now() - t0 < cap) {
    if (busy() > 0) lastBusy = Date.now()
    else if (Date.now() - lastBusy >= quietMs) {
      const skeletons = await page.locator('[aria-busy="true"], .fw-sk').count().catch(() => 0)
      // `at` is when the page actually went quiet, not when this loop noticed:
      // the quiet window is how we confirm readiness, never part of the number.
      if (skeletons === 0) return { ok: true, at: lastBusy }
      lastBusy = Date.now() - quietMs + 300  // re-check shortly
    }
    await new Promise((r) => setTimeout(r, 100))
  }
  return { ok: false, reason: 'cap' }
}

async function mark(page, selector, t0, cap = 30000) {
  try { await page.locator(selector).first().waitFor({ state: 'visible', timeout: cap }); return Date.now() - t0 }
  catch { return null }
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page0 = await ctx.newPage()
await page0.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page0.getByLabel('Email').fill(FARMER.email)
await page0.getByLabel('Mật khẩu').fill(FARMER.password)

const loginTrack = track(page0)
const lt0 = Date.now()
await page0.getByRole('button', { name: 'Đăng nhập' }).click()
const loginShell = await mark(page0, 'nav[aria-label]', lt0)
const loginUseful = await mark(page0, '#fw-hero-title', lt0)
const loginFull = await waitQuiet(page0, loginTrack, { countDeferred: false })
const loginReqs = loginTrack.reqs.map((r) => ({ ...r, startRel: r.start - lt0, endRel: r.end ? r.end - lt0 : null, ms: r.end ? r.end - r.start : null })).sort((a, b) => a.startRel - b.startRel)
const login = { shellMs: loginShell, usefulMs: loginUseful, fullMs: loginFull.ok ? loginFull.at - lt0 : 'cap', requests: loginReqs }
console.log(`login  shell=${loginShell} useful=${loginUseful} full=${login.fullMs} reqs=${loginReqs.length}`)
for (const r of loginReqs) console.log(`   ${String(r.startRel).padStart(6)}→${String(r.endRel).padStart(6)} ${String(r.ms).padStart(6)}ms srv=${String(r.serverMs).padStart(6)} ${r.method} ${r.url}`)

const results = { label, base: BASE, at: new Date().toISOString(), login, screens: [] }

for (const [name, s] of Object.entries(SCREENS)) {
  if (only.length && !only.includes(name)) continue
  const page = await ctx.newPage()          // fresh tab = cold client cache, warm session
  const t = track(page)
  const t0 = Date.now()
  await page.goto(`${BASE}${s.path}`)
  const shellMs = await mark(page, s.shell, t0)
  const usefulMs = await mark(page, s.useful, t0)
  const full = await waitQuiet(page, t, { countDeferred: false })
  const fullMs = full.ok ? full.at - t0 : 'cap'
  // Then let any deferred work land too, so its real cost is visible as well.
  const settled = await waitQuiet(page, t, { countDeferred: true, quietMs: 1000 })
  const lastDeferred = t.reqs.filter(DEFERRED).reduce((m, r) => Math.max(m, r.end ?? 0), 0)
  const settledMs = !settled.ok ? 'cap' : lastDeferred ? Math.max(settled.at, lastDeferred) - t0 : fullMs
  const errors = await page.locator('.fw-error, [role="alert"]').allInnerTexts().catch(() => [])
  const reqs = t.reqs.map((r) => ({ ...r, startRel: r.start - t0, endRel: r.end ? r.end - t0 : null, ms: r.end ? r.end - r.start : null }))
  const rec = {
    screen: name, shellMs, usefulMs, fullMs, settledMs,
    requests: reqs.length,
    dbCalls: reqs.reduce((n, r) => n + (r.dbCalls ?? 0), 0),
    bytes: reqs.reduce((n, r) => n + (r.bytes ?? 0), 0),
    errors,
    waterfall: reqs.sort((a, b) => a.startRel - b.startRel),
  }
  results.screens.push(rec)
  console.log(`${name}  shell=${shellMs} useful=${usefulMs} full=${fullMs} settled=${settledMs} reqs=${rec.requests} dbCalls=${rec.dbCalls} bytes=${rec.bytes}`)
  for (const r of rec.waterfall) console.log(`   ${String(r.startRel).padStart(6)}→${String(r.endRel).padStart(6)} ${String(r.ms).padStart(6)}ms srv=${String(r.serverMs).padStart(6)} db=${r.dbCalls}/${r.dbMs} ${String(r.bytes).padStart(6)}B [${r.status}] ${r.method} ${r.url}`)
  if (rec.errors.length) console.log('   errors:', JSON.stringify(rec.errors).slice(0, 300))
  await page.close()
}

await ctx.close(); await browser.close()
mkdirSync('.qa-screenshots/round4', { recursive: true })
writeFileSync(`.qa-screenshots/round4/${label}.json`, JSON.stringify(results, null, 2))
console.log('saved', label)
