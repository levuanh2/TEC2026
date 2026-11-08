import { test, expect, type BrowserContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'

/* F7 harness: the REAL production bundle (https://agricarbon.info.vn) with the
 * headers of one stage (stages.json) added to every HTML document response IN
 * THE BROWSER. Production is not changed; the only requests that reach a server
 * are GETs of the public pages and assets, plus (flow "expired") the same
 * unauthenticated /v1/me and token refresh a logged-out visitor sends.
 *
 * Flows with a "signed-in" UI use a fake session; /v1/me is answered in the
 * browser and every other API and Supabase call gets 503 in the browser.
 *
 * Pass: every page renders, the webfont is applied, no page error, and no CSP
 * violation (enforced or Report-Only) for the stage; an iframe of the site is
 * refused from stage 1 on. Run (from the repo root):
 *   STAGE=1 NODE_PATH=web-dashboard/node_modules npx --prefix web-dashboard playwright test -c ops/security-headers/playwright.config.ts
 */
const STAGE = process.env.STAGE ?? '1'
// One source of truth: the same generator that writes the render.yaml block.
const STAGE_HEADERS = JSON.parse(execFileSync(process.execPath, [join(__dirname, 'headers.mjs'), '--json', STAGE], { encoding: 'utf8' })) as Record<string, string>
// Self-check of the harness: DROP_HASH=1 removes the allowed inline-handler
// hash; the login test must then FAIL (blocked handler, font not applied).
if (process.env.DROP_HASH === '1') {
  for (const k of Object.keys(STAGE_HEADERS)) STAGE_HEADERS[k] = STAGE_HEADERS[k].replace(/ 'unsafe-hashes' 'sha256-[^']+'/, '')
}
const SITE = 'https://agricarbon.info.vn'
const API = 'https://api.agricarbon.info.vn/'
const SB = 'https://awazhdqzkktekbwaqiic.supabase.co/'
const KEY = 'sb-awazhdqzkktekbwaqiic-auth-token'
const USER = '00000000-0000-4000-8000-0000000000aa'
const ORG = '00000000-0000-4000-8000-0000000000bb'
const cors = { 'access-control-allow-origin': SITE }
const MANAGER = { user_id: USER, full_name: 'CSP', roles: ['cooperative_manager'], organization_memberships: [{ organization_id: ORG, role: 'cooperative_manager' }], farm_memberships: [] }
const FARMER = { ...MANAGER, roles: ['farmer'], organization_memberships: [{ organization_id: ORG, role: 'farmer' }], farm_memberships: [{ farm_id: '00000000-0000-4000-8000-0000000000cc', farm_role: 'owner' }] }
const MANAGER_ROUTES = ['/dashboard', '/organizations', '/farms', '/seasons', '/data-gaps', '/carbon', '/performance', '/mrv', '/accounts/farmers']
const FARMER_ROUTES = ['/farmer', '/farmer/journal', '/farmer/carbon', '/farmer/farms', '/farmer/performance', '/farmer/account']

type Findings = { violations: string[]; pageErrors: string[]; refused: string[] }

/** LIVE=1: after a rollout, test the headers the site really sends (nothing is
 *  injected; the login test asserts they equal the stage). */
const LIVE = process.env.LIVE === '1'

async function withStageHeaders(ctx: BrowserContext) {
  if (!LIVE) await ctx.route((u) => u.origin === SITE, async (route) => {
    const req = route.request()
    if (req.resourceType() !== 'document') return route.continue()
    const res = await route.fetch()
    await route.fulfill({ response: res, headers: { ...res.headers(), ...STAGE_HEADERS } })
  })
  await ctx.addInitScript(() => {
    const w = window as unknown as { __csp: string[] }
    w.__csp = []
    document.addEventListener('securitypolicyviolation', (e) => {
      w.__csp.push(`${e.disposition} ${e.effectiveDirective} ${e.blockedURI || '(inline)'} @${e.sourceFile ?? ''}:${e.lineNumber ?? ''} ${e.sample ?? ''}`.trim())
    })
  })
}

async function fakeSession(ctx: BrowserContext, me: object) {
  await ctx.addInitScript(([key, user]) => {
    if (sessionStorage.getItem('csp-seeded')) return
    sessionStorage.setItem('csp-seeded', '1')
    localStorage.setItem(key, JSON.stringify({ access_token: 'fake.token.value', refresh_token: 'fake-refresh', token_type: 'bearer', expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      user: { id: user, aud: 'authenticated', role: 'authenticated', email: 'nobody@example.invalid', app_metadata: {}, user_metadata: {} } }))
  }, [KEY, USER])
  await ctx.route((u) => u.href.startsWith(SB), (r) => r.fulfill({ status: 503, headers: cors, body: '' }))
  await ctx.route((u) => u.href.startsWith(API), (r) => {
    if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: { ...cors, 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } })
    const path = new URL(r.request().url()).pathname
    if (path === '/v1/me') return r.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify(me) })
    return r.fulfill({ status: 503, headers: cors, contentType: 'application/json', body: '{"detail":{"error":{"code":"unavailable","message":"x"}}}' })
  })
}

function watch(page: Page): Findings {
  const f: Findings = { violations: [], pageErrors: [], refused: [] }
  page.on('pageerror', (e) => f.pageErrors.push(e.message))
  page.on('console', (m) => { if (/Refused to|Content Security Policy/i.test(m.text())) f.refused.push(m.text().slice(0, 300)) })
  return f
}
async function collect(page: Page, f: Findings) {
  f.violations.push(...await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp ?? []))
}
/** The webfont stylesheet is loaded with media="print" and switched to "all"
 *  by an inline onload handler: "all" proves the handler RAN under the CSP. */
async function fontApplied(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  return page.evaluate(() => [...document.styleSheets].some((s) => (s.href ?? '').includes('fonts.googleapis.com') && s.media.mediaText === 'all')
    && [...document.fonts].some((f) => f.family.replace(/"/g, '') === 'Be Vietnam Pro' && f.status === 'loaded'))
}

test.describe(`stage ${STAGE} headers on the production bundle`, () => {
  test('login page: renders, webfont applied, no violation', async ({ browser }) => {
    const ctx = await browser.newContext(); await withStageHeaders(ctx)
    const page = await ctx.newPage(); const f = watch(page)
    const res = await page.goto('/login')
    for (const [k, v] of Object.entries(STAGE_HEADERS)) expect(res!.headers()[k.toLowerCase()]).toBe(v)
    await expect(page.locator('input[name=password]')).toBeVisible()
    await expect.poll(() => fontApplied(page), { timeout: 15000 }).toBe(true)
    await collect(page, f)
    console.log('login', JSON.stringify(f))
    expect(f).toEqual({ violations: [], pageErrors: [], refused: [] })
    await ctx.close()
  })

  test('expired session: real unauthenticated /v1/me + token refresh, back to login, no violation', async ({ browser }) => {
    const ctx = await browser.newContext(); await withStageHeaders(ctx)
    await ctx.addInitScript(([key, user]) => {
      localStorage.setItem(key, JSON.stringify({ access_token: 'expired.fake.token', refresh_token: 'fake-refresh', token_type: 'bearer', expires_in: 3600,
        expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: user, aud: 'authenticated', role: 'authenticated', email: 'nobody@example.invalid', app_metadata: {}, user_metadata: {} } }))
    }, [KEY, USER])
    const page = await ctx.newPage(); const f = watch(page)
    const hosts = new Set<string>()
    page.on('request', (r) => hosts.add(new URL(r.url()).origin))
    await page.goto('/dashboard')
    await expect(page.locator('input[name=password]')).toBeVisible({ timeout: 20000 })
    await collect(page, f)
    console.log('expired', JSON.stringify({ ...f, hosts: [...hosts] }))
    expect(hosts.has('https://api.agricarbon.info.vn')).toBe(true)
    expect(f).toEqual({ violations: [], pageErrors: [], refused: [] })
    await ctx.close()
  })

  test('Manager UI, every route (lazy chunks), no violation', async ({ browser }) => {
    const ctx = await browser.newContext(); await withStageHeaders(ctx); await fakeSession(ctx, MANAGER)
    const page = await ctx.newPage(); const f = watch(page)
    const chunks = new Set<string>()
    page.on('response', (r) => { if (/\/assets\/.+\.js$/.test(r.url())) chunks.add(r.url().split('/').pop()!) })
    await page.goto('/dashboard')
    await expect(page.locator('.shell')).toBeVisible({ timeout: 20000 })
    for (const path of MANAGER_ROUTES) {
      await page.evaluate((p) => { history.pushState({}, '', p); dispatchEvent(new PopStateEvent('popstate')) }, path)
      await expect(page.locator('.shell')).toBeVisible()
      await page.waitForTimeout(1200)
      await expect(page.locator('.content')).not.toBeEmpty()
    }
    await collect(page, f)
    console.log('manager', JSON.stringify({ ...f, chunks: [...chunks] }))
    expect(f).toEqual({ violations: [], pageErrors: [], refused: [] })
    expect(chunks.size).toBeGreaterThan(3)
    await ctx.close()
  })

  test('Farmer UI, every route, no violation', async ({ browser }) => {
    const ctx = await browser.newContext(); await withStageHeaders(ctx); await fakeSession(ctx, FARMER)
    const page = await ctx.newPage(); const f = watch(page)
    await page.goto('/farmer')
    await expect(page.locator('.fw-shell')).toBeVisible({ timeout: 20000 })
    for (const path of FARMER_ROUTES) {
      await page.evaluate((p) => { history.pushState({}, '', p); dispatchEvent(new PopStateEvent('popstate')) }, path)
      await expect(page.locator('.fw-shell')).toBeVisible()
      await page.waitForTimeout(1000)
    }
    await collect(page, f)
    console.log('farmer', JSON.stringify(f))
    expect(f).toEqual({ violations: [], pageErrors: [], refused: [] })
    await ctx.close()
  })

  test('framing: an iframe of the site is refused from stage 1 on', async ({ browser }) => {
    const ctx = await browser.newContext(); await withStageHeaders(ctx)
    const page = await ctx.newPage()
    const msgs: string[] = []
    page.on('console', (m) => msgs.push(m.text()))
    await page.goto('/login') // a document of the site, so the framing below is same-origin AND still refused
    await page.setContent(`<iframe id="f" src="${SITE}/login" width="400" height="300"></iframe>`)
    await page.waitForTimeout(4000)
    const frame = page.frames().find((fr) => fr !== page.mainFrame())
    const rendered = frame ? await frame.locator('input[name=password]').count().catch(() => 0) : 0
    console.log('framing', JSON.stringify({ stage: STAGE, rendered, frameUrl: frame?.url(), refused: msgs.filter((m) => /Refused|frame-ancestors|X-Frame-Options/i.test(m)).map((m) => m.slice(0, 200)) }))
    if (STAGE === '0') expect(rendered).toBe(1)
    else expect(rendered).toBe(0)
    await ctx.close()
  })
})
